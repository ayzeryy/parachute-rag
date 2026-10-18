import asyncio
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path
from socket import socket

import uvicorn
from mcp import Client

from parachute.agents import DateAgent
from parachute.calendar import AppointmentRepository
from parachute.mcp_server import MCPDependencies, create_mcp_server
from parachute.models import WeatherSnapshot
from parachute.weather import ForecastDateError


TEST_DATE = date(2026, 10, 20)


class FixtureKnowledgeBase:
    def __init__(self):
        self.calls = []

    def search(self, query, limit=5):
        self.calls.append((query, limit))
        return [
            {
                "id": "FAQ-021",
                "categoria": "Requisitos",
                "pregunta": "¿Cuál es el peso máximo?",
                "respuesta": "El peso máximo es 100 kg.",
                "metadata": {"empresa": "Parachute S.A."},
                "similitud": 0.91,
            }
        ]


class FixtureWeatherService:
    def __init__(self):
        self.calls = []
        self.values = {}

    def set(self, requested, value):
        self.values[requested] = value

    def forecast(self, requested):
        self.calls.append(requested)
        value = self.values.get(requested)
        if isinstance(value, Exception):
            raise value
        if value is None:
            raise RuntimeError("fixture meteorológico faltante")
        return value


def snapshot(*, rain=0, clouds=15, wind=12, gust=20):
    return WeatherSnapshot(
        date=TEST_DATE,
        temperature_2m=26,
        precipitation=rain,
        cloud_cover=clouds,
        wind_speed_10m=wind,
        wind_gust_10m=gust,
    )


def free_port():
    with closing(socket()) as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


class MCPStreamableHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        asyncio.get_running_loop().set_debug(False)
        self.temp_directory = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_directory.name) / "appointments.sqlite3"
        self.knowledge_base = FixtureKnowledgeBase()
        self.weather = FixtureWeatherService()
        self.weather.set(TEST_DATE, snapshot())
        dependencies = MCPDependencies(
            knowledge_base=self.knowledge_base,
            weather_service=self.weather,
            appointment_repository=AppointmentRepository(self.db_path),
            date_agent=DateAgent(),
        )
        mcp_server = create_mcp_server(dependencies)
        app = mcp_server.streamable_http_app(
            streamable_http_path="/mcp",
            stateless_http=True,
            json_response=True,
            host="127.0.0.1",
        )
        self.port = free_port()
        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=self.port,
            log_level="critical",
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        for _ in range(100):
            if self.server.started:
                break
            await asyncio.sleep(0.02)
        if not self.server.started:
            self.fail("El servidor MCP de prueba no inició")
        self.url = f"http://127.0.0.1:{self.port}/mcp"

    async def asyncTearDown(self):
        self.server.should_exit = True
        await asyncio.to_thread(self.thread.join, 5)
        self.temp_directory.cleanup()

    async def call(self, name, arguments):
        async with Client(self.url, read_timeout_seconds=5) as client:
            result = await client.call_tool(name, arguments)
        return result

    def appointment_count(self):
        if not self.db_path.exists():
            return 0
        with closing(sqlite3.connect(self.db_path)) as connection:
            return connection.execute(
                "SELECT COUNT(*) FROM appointments"
            ).fetchone()[0]

    async def test_discovers_tools_resource_and_prompt_over_http(self):
        async with Client(self.url, read_timeout_seconds=5) as client:
            tools = await client.list_tools()
            resources = await client.list_resources()
            prompts = await client.list_prompts()
            resource = await client.read_resource(
                "parachute://politicas/seguridad"
            )
            prompt = await client.get_prompt(
                "consulta_faq", {"pregunta": "¿Cuál es el peso máximo?"}
            )

        self.assertEqual(
            {tool.name for tool in tools.tools},
            {
                "buscar_faqs",
                "extraer_fecha",
                "consultar_clima",
                "evaluar_seguridad",
                "crear_cita",
            },
        )
        self.assertIn(
            "parachute://politicas/seguridad",
            {str(item.uri) for item in resources.resources},
        )
        self.assertIn("consulta_faq", {item.name for item in prompts.prompts})
        self.assertIn("28 km/h", resource.contents[0].text)
        self.assertIn("buscar_faqs", prompt.messages[0].content.text)
        self.assertIn("FAQ-021", prompt.messages[0].content.text)

    async def test_invokes_faq_date_weather_and_safety_over_http(self):
        faq = await self.call(
            "buscar_faqs",
            {
                "request": {
                    "query": "peso máximo",
                    "limit": 3,
                    "correlation_id": "test-faq",
                }
            },
        )
        extracted = await self.call(
            "extraer_fecha", {"request": {"text": "Reserva el 2026-10-20"}}
        )
        weather = await self.call(
            "consultar_clima", {"request": {"requested_date": "2026-10-20"}}
        )
        safety = await self.call(
            "evaluar_seguridad",
            {
                "request": {
                    "weather": {
                        "requested_date": "2026-10-20",
                        "temperature_c": 26,
                        "precipitation_mm": 0,
                        "cloud_cover_percent": 15,
                        "wind_speed_kmh": 12,
                        "wind_gust_kmh": 20,
                    }
                }
            },
        )

        self.assertEqual(
            faq.structured_content["data"]["evidence"][0]["source_id"],
            "FAQ-021",
        )
        self.assertEqual(
            extracted.structured_content["data"]["requested_date"], "2026-10-20"
        )
        self.assertEqual(
            weather.structured_content["data"]["wind_speed_kmh"], 12
        )
        self.assertEqual(safety.structured_content["data"]["level"], "ideal")
        self.assertEqual(self.knowledge_base.calls, [("peso máximo", 3)])
        self.assertIn(TEST_DATE, self.weather.calls)

    async def test_create_appointment_rechecks_weather_and_controls_duplicates(self):
        arguments = {
            "request": {
                "customer": "Ana",
                "requested_date": "2026-10-20",
                "experienced_tandem": False,
            }
        }
        created = await self.call("crear_cita", arguments)
        duplicate = await self.call("crear_cita", arguments)

        self.assertEqual(
            created.structured_content["data"]["outcome"], "created"
        )
        self.assertEqual(
            duplicate.structured_content["data"]["outcome"], "duplicate"
        )
        self.assertEqual(self.weather.calls, [TEST_DATE, TEST_DATE])
        self.assertEqual(self.appointment_count(), 1)

    async def test_prohibited_and_marginal_weather_enforce_business_rules(self):
        self.weather.set(TEST_DATE, snapshot(rain=1.5, clouds=40, wind=24))
        prohibited = await self.call(
            "crear_cita",
            {
                "request": {
                    "customer": "Luis",
                    "requested_date": "2026-10-20",
                }
            },
        )
        self.assertEqual(
            prohibited.structured_content["data"]["outcome"], "rejected"
        )
        self.assertEqual(
            prohibited.structured_content["data"]["assessment"]["level"],
            "no_seguro",
        )
        self.assertEqual(self.appointment_count(), 0)

        self.weather.set(TEST_DATE, snapshot(wind=24, gust=30))
        denied = await self.call(
            "crear_cita",
            {
                "request": {
                    "customer": "Marta",
                    "requested_date": "2026-10-20",
                }
            },
        )
        allowed = await self.call(
            "crear_cita",
            {
                "request": {
                    "customer": "Marta",
                    "requested_date": "2026-10-20",
                    "experienced_tandem": True,
                }
            },
        )
        self.assertEqual(denied.structured_content["data"]["outcome"], "rejected")
        self.assertEqual(allowed.structured_content["data"]["outcome"], "created")
        self.assertEqual(self.appointment_count(), 1)

        self.weather.set(TEST_DATE, snapshot(clouds=50))
        clouds_only = await self.call(
            "crear_cita",
            {
                "request": {
                    "customer": "Nube",
                    "requested_date": "2026-10-20",
                }
            },
        )
        self.assertEqual(
            clouds_only.structured_content["data"]["outcome"], "created"
        )
        self.assertFalse(
            clouds_only.structured_content["data"]["assessment"][
                "requires_experienced_tandem"
            ]
        )
        self.assertEqual(self.appointment_count(), 2)

    async def test_weather_failure_or_invalid_date_never_persists(self):
        self.weather.set(TEST_DATE, RuntimeError("respuesta incompleta"))
        failed = await self.call(
            "crear_cita",
            {
                "request": {
                    "customer": "Ana",
                    "requested_date": "2026-10-20",
                }
            },
        )
        self.assertFalse(failed.structured_content["ok"])
        self.assertEqual(
            failed.structured_content["error"]["code"], "weather_unavailable"
        )
        self.assertEqual(self.appointment_count(), 0)

        other_date = date(2026, 12, 1)
        self.weather.set(
            other_date,
            ForecastDateError("La fecha está fuera de la ventana disponible."),
        )
        out_of_range = await self.call(
            "crear_cita",
            {
                "request": {
                    "customer": "Ana",
                    "requested_date": "2026-12-01",
                }
            },
        )
        self.assertFalse(out_of_range.structured_content["ok"])
        self.assertEqual(
            out_of_range.structured_content["error"]["kind"], "domain"
        )
        self.assertEqual(self.appointment_count(), 0)

    async def test_protocol_rejects_fabricated_approval(self):
        result = await self.call(
            "crear_cita",
            {
                "request": {
                    "customer": "Ana",
                    "requested_date": "2026-10-20",
                    "approved": True,
                }
            },
        )
        self.assertTrue(result.is_error)
        self.assertEqual(self.weather.calls, [])
        self.assertEqual(self.appointment_count(), 0)

    async def test_logs_start_finish_and_business_result(self):
        with self.assertLogs("parachute.mcp_server", level="INFO") as captured:
            await self.call(
                "crear_cita",
                {
                    "request": {
                        "customer": "Ana",
                        "requested_date": "2026-10-20",
                        "correlation_id": "corr-123",
                    }
                },
            )
        logs = "\n".join(captured.output)
        self.assertIn("mcp.tool.start tool=crear_cita", logs)
        self.assertIn("correlation_id=corr-123", logs)
        self.assertIn("mcp.tool.finish tool=crear_cita", logs)
        self.assertIn("result=reserva:created", logs)
        self.assertIn("duration_ms=", logs)


if __name__ == "__main__":
    unittest.main()
