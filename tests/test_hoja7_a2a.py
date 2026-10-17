import asyncio
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path
from socket import socket

import httpx
import uvicorn
from a2a.client import A2ACardResolver, ClientCallContext, ClientConfig, create_client
from a2a.helpers.proto_helpers import (
    get_data_parts,
    get_message_text,
    new_data_part,
    new_text_part,
)
from a2a.types.a2a_pb2 import Message, Role, SendMessageRequest
from a2a.utils.constants import TransportProtocol

from parachute.a2a_contracts import A2AResponseCategory
from parachute.a2a_executor import ParachuteA2AExecutor, _response_category
from parachute.a2a_server import create_a2a_app
from parachute.agents import DateAgent
from parachute.calendar import AppointmentRepository
from parachute.mcp_client import RemoteMCPToolGateway
from parachute.mcp_centralized import MCPExecutionKind
from parachute.mcp_server import MCPDependencies, create_mcp_server
from parachute.models import WeatherSnapshot


TEST_DATE = date(2026, 10, 20)


class FixtureKnowledgeBase:
    def __init__(self):
        self.calls = []
        self.rows = [
            {
                "id": "FAQ-021",
                "categoria": "Requisitos",
                "pregunta": "¿Cuál es el peso máximo?",
                "respuesta": "El peso máximo es 100 kg.",
                "metadata": {"empresa": "Parachute S.A."},
                "similitud": 0.91,
            }
        ]

    def search(self, query, limit=5):
        self.calls.append((query, limit))
        return list(self.rows[:limit])


class FixtureWeatherService:
    def __init__(self):
        self.calls = []
        self.value = weather_snapshot()

    def forecast(self, requested):
        self.calls.append(requested)
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


def weather_snapshot(*, rain=0, clouds=15, wind=12, gust=20):
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


class A2AResultMappingTests(unittest.TestCase):
    def test_uncertain_write_has_an_explicit_non_business_category(self):
        self.assertEqual(
            _response_category(MCPExecutionKind.WRITE_OUTCOME_UNKNOWN),
            A2AResponseCategory.WRITE_OUTCOME_UNKNOWN,
        )


class A2AHTTPIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        asyncio.get_running_loop().set_debug(False)
        self.temp_directory = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_directory.name) / "appointments.sqlite3"
        self.knowledge_base = FixtureKnowledgeBase()
        self.weather = FixtureWeatherService()
        dependencies = MCPDependencies(
            knowledge_base=self.knowledge_base,
            weather_service=self.weather,
            appointment_repository=AppointmentRepository(self.db_path),
            date_agent=DateAgent(),
        )

        self.mcp_port = free_port()
        self.mcp_url = f"http://127.0.0.1:{self.mcp_port}/mcp"
        mcp_server = create_mcp_server(dependencies)
        mcp_app = mcp_server.streamable_http_app(
            streamable_http_path="/mcp",
            stateless_http=True,
            json_response=True,
            host="127.0.0.1",
        )
        self.mcp_uvicorn, self.mcp_thread = await self.start_server(
            mcp_app, self.mcp_port
        )

        self.gateways = []

        def gateway_factory():
            gateway = RemoteMCPToolGateway(self.mcp_url, timeout_seconds=5)
            self.gateways.append(gateway)
            return gateway

        self.executor = ParachuteA2AExecutor(gateway_factory=gateway_factory)
        self.a2a_port = free_port()
        self.a2a_url = f"http://127.0.0.1:{self.a2a_port}"
        a2a_app = create_a2a_app(
            public_url=self.a2a_url,
            executor=self.executor,
        )
        self.a2a_uvicorn, self.a2a_thread = await self.start_server(
            a2a_app, self.a2a_port
        )

    async def asyncTearDown(self):
        self.a2a_uvicorn.should_exit = True
        await asyncio.to_thread(self.a2a_thread.join, 5)
        self.mcp_uvicorn.should_exit = True
        await asyncio.to_thread(self.mcp_thread.join, 5)
        self.assertFalse(self.a2a_thread.is_alive())
        self.assertFalse(self.mcp_thread.is_alive())
        self.temp_directory.cleanup()

    async def start_server(self, app, port):
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                host="127.0.0.1",
                port=port,
                log_level="critical",
            )
        )
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        for _ in range(100):
            if server.started:
                return server, thread
            await asyncio.sleep(0.02)
        self.fail(f"El servidor de prueba no inició en el puerto {port}")

    async def send(
        self,
        text,
        data=None,
        *,
        message_id="msg-test",
        context_id="ctx-test",
    ):
        parts = [new_text_part(text, media_type="text/plain")]
        if data is not None:
            parts.append(new_data_part(data, media_type="application/json"))
        request = SendMessageRequest(
            message=Message(
                message_id=message_id,
                context_id=context_id,
                role=Role.ROLE_USER,
                parts=parts,
            )
        )
        http_client = httpx.AsyncClient(timeout=5)
        client = await create_client(
            self.a2a_url,
            client_config=ClientConfig(
                streaming=False,
                httpx_client=http_client,
                supported_protocol_bindings=[TransportProtocol.JSONRPC.value],
            ),
        )
        try:
            responses = [
                response
                async for response in client.send_message(
                    request,
                    context=ClientCallContext(timeout=5),
                )
            ]
        finally:
            await client.close()
        self.assertTrue(http_client.is_closed)

        self.assertEqual(len(responses), 1)
        self.assertTrue(responses[0].HasField("message"))
        message = responses[0].message
        response_data = get_data_parts(message.parts)
        self.assertEqual(len(response_data), 1)
        return get_message_text(message), response_data[0], message

    def stored_appointments(self):
        if not self.db_path.exists():
            return []
        with closing(sqlite3.connect(self.db_path)) as connection:
            return connection.execute(
                "SELECT customer, appointment_date, condition "
                "FROM appointments ORDER BY id"
            ).fetchall()

    async def test_discovers_agent_card_and_exact_skills(self):
        async with httpx.AsyncClient(timeout=5) as http_client:
            card = await A2ACardResolver(
                http_client, self.a2a_url
            ).get_agent_card()

        self.assertEqual(card.name, "Asistente Parachute S.A.")
        self.assertEqual(
            {skill.id for skill in card.skills},
            {"consultar_faqs", "reservar_salto"},
        )
        self.assertEqual(len(card.supported_interfaces), 1)
        interface = card.supported_interfaces[0]
        self.assertEqual(interface.url, f"{self.a2a_url}/")
        self.assertEqual(interface.protocol_binding, "JSONRPC")
        self.assertEqual(interface.protocol_version, "1.0")
        self.assertFalse(card.capabilities.streaming)
        self.assertFalse(card.capabilities.push_notifications)

    async def test_faq_with_and_without_evidence_crosses_both_protocols(self):
        answer, data, response = await self.send(
            "¿Cuál es el peso máximo?",
            {"cliente": "Ana", "experienced_tandem": False},
            message_id="corr-faq-evidence",
            context_id="ctx-faq",
        )
        self.assertEqual(answer, "- El peso máximo es 100 kg. (FAQ-021)")
        self.assertEqual(data["category"], "business_result")
        self.assertEqual(data["route"], "faq")
        self.assertEqual(data["correlation_id"], "corr-faq-evidence")
        self.assertEqual(response.context_id, "ctx-faq")

        self.knowledge_base.rows = []
        no_answer, empty_data, _ = await self.send(
            "¿Tienen vuelos nocturnos?",
            {"cliente": "Ana"},
            message_id="corr-faq-empty",
        )
        self.assertEqual(
            no_answer,
            "No puedo responder esa pregunta con la información disponible.",
        )
        self.assertEqual(empty_data["category"], "business_result")
        self.assertEqual(
            self.knowledge_base.calls,
            [
                ("¿Cuál es el peso máximo?", 5),
                ("¿Tienen vuelos nocturnos?", 5),
            ],
        )
        self.assertTrue(all(not gateway.is_open for gateway in self.gateways))

    async def test_approved_reservation_proves_a2a_to_mcp_route(self):
        self.weather.value = weather_snapshot(wind=24, gust=30)
        with self.assertLogs(
            "parachute.a2a_executor", level="INFO"
        ) as a2a_logs, self.assertLogs(
            "parachute.mcp_server", level="INFO"
        ) as mcp_logs:
            answer, data, _ = await self.send(
                "Quiero reservar cita el 2026-10-20",
                {"cliente": "Ana Exacta", "experienced_tandem": True},
                message_id="corr-e2e-approved",
                context_id="ctx-e2e-approved",
            )

        self.assertIn("Cita #1 creada", answer)
        self.assertEqual(data["category"], "business_result")
        self.assertEqual(data["route"], "reserva")
        self.assertEqual(
            self.stored_appointments(),
            [("Ana Exacta", "2026-10-20", "marginal")],
        )
        self.assertEqual(self.weather.calls, [TEST_DATE, TEST_DATE])
        a2a_output = "\n".join(a2a_logs.output)
        mcp_output = "\n".join(mcp_logs.output)
        self.assertIn("a2a.request.received", a2a_output)
        self.assertIn("a2a.request.processing", a2a_output)
        self.assertIn("a2a.request.finished", a2a_output)
        self.assertIn("correlation_id=corr-e2e-approved", a2a_output)
        for tool_name in (
            "extraer_fecha",
            "consultar_clima",
            "evaluar_seguridad",
            "crear_cita",
        ):
            self.assertIn(f"mcp.tool.start tool={tool_name}", mcp_output)
        self.assertIn("correlation_id=corr-e2e-approved", mcp_output)
        self.assertTrue(all(not gateway.is_open for gateway in self.gateways))

    async def test_rejected_reservation_is_a_business_result(self):
        self.weather.value = weather_snapshot(rain=2, wind=30, gust=40)
        answer, data, _ = await self.send(
            "Reserva el 2026-10-20",
            {"cliente": "Luis", "experienced_tandem": True},
            message_id="corr-rejected",
        )

        self.assertIn("No se creó la cita", answer)
        self.assertEqual(data["category"], "business_result")
        self.assertEqual(data["route"], "reserva")
        self.assertEqual(self.stored_appointments(), [])

    async def test_missing_or_mistyped_input_is_rejected_before_mcp(self):
        missing_customer, missing_data, _ = await self.send(
            "Reserva el 2026-10-20",
            {"experienced_tandem": False},
            message_id="corr-missing-customer",
        )
        self.assertIn("cliente válido", missing_customer)
        self.assertEqual(missing_data["category"], "invalid_input")
        self.assertEqual(missing_data["route"], "reserva")

        wrong_boolean, wrong_data, _ = await self.send(
            "Reserva el 2026-10-20",
            {"cliente": "Ana", "experienced_tandem": "false"},
            message_id="corr-wrong-bool",
        )
        self.assertIn("como booleano", wrong_boolean)
        self.assertEqual(wrong_data["category"], "invalid_input")
        self.assertEqual(self.gateways, [])
        self.assertEqual(self.weather.calls, [])
        self.assertEqual(self.stored_appointments(), [])

    async def test_missing_experience_defaults_to_safe_false(self):
        self.weather.value = weather_snapshot(wind=24, gust=30)
        answer, data, _ = await self.send(
            "Reserva el 2026-10-20",
            {"cliente": "Principiante"},
            message_id="corr-default-false",
        )

        self.assertIn("requiere un tándem experimentado", answer)
        self.assertEqual(data["category"], "business_result")
        self.assertEqual(self.stored_appointments(), [])

    async def test_mcp_failure_has_no_local_fallback(self):
        unavailable_url = f"http://127.0.0.1:{free_port()}/mcp"

        def unavailable_gateway_factory():
            gateway = RemoteMCPToolGateway(
                unavailable_url,
                timeout_seconds=0.2,
            )
            self.gateways.append(gateway)
            return gateway

        self.executor._gateway_factory = unavailable_gateway_factory
        answer, data, _ = await self.send(
            "Reserva el 2026-10-20",
            {"cliente": "Sin respaldo", "experienced_tandem": True},
            message_id="corr-mcp-down",
        )

        self.assertIn("servidor MCP no está disponible", answer)
        self.assertEqual(data["category"], "infrastructure_error")
        self.assertEqual(self.weather.calls, [])
        self.assertEqual(self.stored_appointments(), [])
        self.assertTrue(all(not gateway.is_open for gateway in self.gateways))

    async def test_parallel_requests_keep_context_isolated(self):
        self.weather.value = weather_snapshot(wind=24, gust=30)
        with self.assertLogs("parachute.mcp_server", level="INFO") as captured:
            approved, rejected = await asyncio.gather(
                self.send(
                    "Reserva el 2026-10-20",
                    {
                        "cliente": "Cliente experimentada",
                        "experienced_tandem": True,
                    },
                    message_id="corr-experienced",
                    context_id="ctx-experienced",
                ),
                self.send(
                    "Reserva el 2026-10-20",
                    {
                        "cliente": "Cliente inicial",
                        "experienced_tandem": False,
                    },
                    message_id="corr-beginner",
                    context_id="ctx-beginner",
                ),
            )

        self.assertIn("creada", approved[0])
        self.assertIn("requiere un tándem experimentado", rejected[0])
        self.assertEqual(approved[1]["correlation_id"], "corr-experienced")
        self.assertEqual(rejected[1]["correlation_id"], "corr-beginner")
        self.assertEqual(approved[2].context_id, "ctx-experienced")
        self.assertEqual(rejected[2].context_id, "ctx-beginner")
        self.assertEqual(
            self.stored_appointments(),
            [("Cliente experimentada", "2026-10-20", "marginal")],
        )
        logs = "\n".join(captured.output)
        self.assertIn("correlation_id=corr-experienced", logs)
        self.assertIn("correlation_id=corr-beginner", logs)
        self.assertEqual(len(self.gateways), 2)
        self.assertTrue(all(not gateway.is_open for gateway in self.gateways))


if __name__ == "__main__":
    unittest.main()

