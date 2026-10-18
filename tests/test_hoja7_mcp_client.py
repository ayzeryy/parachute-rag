import asyncio
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path
from socket import socket
from unittest.mock import AsyncMock

import uvicorn
from mcp import MCPError
from mcp.types import CallToolResult

from parachute.agents import DateAgent, RequestContext
from parachute.calendar import AppointmentRepository
from parachute.mcp_centralized import (
    MCPAsyncCentralSupervisor,
    MCP_UNAVAILABLE,
    MCP_WRITE_UNCONFIRMED,
    run_centralized_via_mcp,
)
from parachute.mcp_client import (
    MCPClientStateError,
    MCPContractError,
    MCPProtocolError,
    MCPRemoteToolError,
    MCPToolCallError,
    MCPWriteOutcomeUnknownError,
    RemoteMCPToolGateway,
)
from parachute.mcp_server import MCPDependencies, create_mcp_server
from parachute.models import SafetyLevel, WeatherSnapshot
from parachute.tool_contracts import (
    ExtractDateResult,
    ExtractedDateData,
    SafetyData,
    SafetyResult,
    SearchFAQsRequest,
    WeatherData,
    WeatherRequest,
    WeatherResult,
)


TEST_DATE = date(2026, 10, 20)


class ConfigurableKnowledgeBase:
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


class DeterministicWeatherService:
    def __init__(self):
        self.calls = []
        self.value = weather_snapshot()
        self.sequence = []

    def forecast(self, requested):
        self.calls.append(requested)
        value = self.sequence.pop(0) if self.sequence else self.value
        if isinstance(value, Exception):
            raise value
        return value


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


class StubMCPClient:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    async def call_tool(self, name, arguments, read_timeout_seconds=None):
        self.calls.append((name, arguments, read_timeout_seconds))
        if self.error is not None:
            raise self.error
        return self.result


class MCPResultClassificationTests(unittest.IsolatedAsyncioTestCase):
    def gateway_with(self, client):
        gateway = RemoteMCPToolGateway("http://mcp.invalid/mcp")
        gateway._client = client
        return gateway

    async def test_sends_arguments_nested_under_request(self):
        client = StubMCPClient(
            CallToolResult(
                content=[],
                structuredContent={
                    "ok": True,
                    "data": {"query": "peso", "evidence": []},
                    "error": None,
                },
            )
        )
        gateway = self.gateway_with(client)

        await gateway.search_faqs(
            SearchFAQsRequest(query="peso", correlation_id="corr-schema")
        )

        _, arguments, timeout = client.calls[0]
        self.assertEqual(
            arguments,
            {
                "request": {
                    "query": "peso",
                    "limit": 5,
                    "correlation_id": "corr-schema",
                }
            },
        )
        self.assertEqual(timeout, 10.0)

    async def test_distinguishes_mcp_tool_and_protocol_errors(self):
        tool_gateway = self.gateway_with(
            StubMCPClient(CallToolResult(content=[], isError=True))
        )
        with self.assertRaises(MCPToolCallError):
            await tool_gateway.search_faqs(SearchFAQsRequest(query="peso"))

        protocol_gateway = self.gateway_with(
            StubMCPClient(error=MCPError(-32603, "fallo de protocolo"))
        )
        with self.assertRaises(MCPProtocolError):
            await protocol_gateway.search_faqs(SearchFAQsRequest(query="peso"))

    async def test_rejects_structured_content_incompatible_with_contract(self):
        gateway = self.gateway_with(
            StubMCPClient(
                CallToolResult(
                    content=[],
                    structuredContent={
                        "ok": True,
                        "data": {"query": "peso", "evidence": "inválida"},
                    },
                )
            )
        )

        with self.assertRaises(MCPContractError):
            await gateway.search_faqs(SearchFAQsRequest(query="peso"))


class ProductionMCPClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        asyncio.get_running_loop().set_debug(False)
        self.temp_directory = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_directory.name) / "appointments.sqlite3"
        self.knowledge_base = ConfigurableKnowledgeBase()
        self.weather = DeterministicWeatherService()
        dependencies = MCPDependencies(
            knowledge_base=self.knowledge_base,
            weather_service=self.weather,
            appointment_repository=AppointmentRepository(self.db_path),
            date_agent=DateAgent(),
        )
        server = create_mcp_server(dependencies)
        app = server.streamable_http_app(
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

    async def run_remote(
        self,
        context,
        correlation_id="test-correlation",
    ):
        return await run_centralized_via_mcp(
            context,
            correlation_id=correlation_id,
            server_url=self.url,
            timeout_seconds=5,
        )

    def stored_appointments(self):
        if not self.db_path.exists():
            return []
        with closing(sqlite3.connect(self.db_path)) as connection:
            return connection.execute(
                "SELECT customer, appointment_date, condition "
                "FROM appointments ORDER BY id"
            ).fetchall()

    async def test_faq_with_and_without_evidence_uses_remote_tool(self):
        answer = await self.run_remote(
            RequestContext("¿Cuál es el peso máximo?"),
            correlation_id="corr-faq-evidence",
        )
        self.assertEqual(answer, "- El peso máximo es 100 kg. (FAQ-021)")

        self.knowledge_base.rows = []
        no_answer = await self.run_remote(
            RequestContext("¿Tienen vuelos nocturnos?"),
            correlation_id="corr-faq-empty",
        )
        self.assertEqual(
            no_answer,
            "No puedo responder esa pregunta con la información disponible.",
        )
        self.assertEqual(
            self.knowledge_base.calls,
            [
                ("¿Cuál es el peso máximo?", 5),
                ("¿Tienen vuelos nocturnos?", 5),
            ],
        )

    async def test_approved_reservation_preserves_customer_and_experience(self):
        self.weather.value = weather_snapshot(wind=24, gust=30)
        with self.assertLogs("parachute.mcp_server", level="INFO") as captured:
            answer = await self.run_remote(
                RequestContext(
                    "Quiero reservar cita el 2026-10-20",
                    customer="Ana Exacta",
                    experienced_tandem=True,
                ),
                correlation_id="corr-approved",
            )

        self.assertIn("Cita #1 creada", answer)
        self.assertEqual(
            self.stored_appointments(),
            [("Ana Exacta", "2026-10-20", "marginal")],
        )
        self.assertEqual(self.weather.calls, [TEST_DATE, TEST_DATE])
        logs = "\n".join(captured.output)
        for tool_name in (
            "extraer_fecha",
            "consultar_clima",
            "evaluar_seguridad",
            "crear_cita",
        ):
            self.assertIn(f"mcp.tool.start tool={tool_name}", logs)
        self.assertIn("correlation_id=corr-approved", logs)

    async def test_rejected_reservation_uses_final_create_decision(self):
        self.weather.value = weather_snapshot(rain=2, clouds=70, wind=30, gust=40)
        answer = await self.run_remote(
            RequestContext(
                "Reserva para 2026-10-20",
                customer="Luis",
                experienced_tandem=True,
            ),
            correlation_id="corr-rejected",
        )

        self.assertIn("No se creó la cita", answer)
        self.assertEqual(self.stored_appointments(), [])
        self.assertEqual(self.weather.calls, [TEST_DATE, TEST_DATE])

    async def test_create_result_overrides_preliminary_weather_assessment(self):
        self.weather.sequence = [
            weather_snapshot(),
            weather_snapshot(rain=2, clouds=70, wind=30, gust=40),
        ]
        answer = await self.run_remote(
            RequestContext(
                "Reserva para 2026-10-20",
                customer="Clima cambiante",
                experienced_tandem=True,
            ),
            correlation_id="corr-weather-change",
        )

        self.assertIn("No se creó la cita", answer)
        self.assertIn("NO_SEGURO", answer)
        self.assertEqual(self.stored_appointments(), [])
        self.assertEqual(self.weather.calls, [TEST_DATE, TEST_DATE])

    async def test_tool_failure_is_distinct_and_never_falls_back_locally(self):
        self.weather.value = RuntimeError("servicio caído")
        async with RemoteMCPToolGateway(
            self.url, timeout_seconds=5
        ) as gateway:
            with self.assertRaises(MCPRemoteToolError) as captured:
                await gateway.get_weather(
                    WeatherRequest(
                        requested_date=TEST_DATE,
                        correlation_id="corr-tool-error",
                    )
                )
        self.assertEqual(captured.exception.error.code, "weather_unavailable")
        self.assertEqual(self.stored_appointments(), [])

    async def test_connection_failure_returns_controlled_error_without_fallback(self):
        unavailable_url = f"http://127.0.0.1:{free_port()}/mcp"
        answer = await run_centralized_via_mcp(
            RequestContext(
                "Reserva el 2026-10-20",
                customer="Sin respaldo",
            ),
            correlation_id="corr-unavailable",
            server_url=unavailable_url,
            timeout_seconds=0.2,
        )

        self.assertEqual(answer, MCP_UNAVAILABLE)
        self.assertEqual(self.weather.calls, [])
        self.assertEqual(self.stored_appointments(), [])

    async def test_context_manager_closes_real_client_resources(self):
        gateway = RemoteMCPToolGateway(self.url, timeout_seconds=5)
        async with gateway:
            self.assertTrue(gateway.is_open)
        self.assertFalse(gateway.is_open)
        with self.assertRaises(MCPClientStateError):
            await gateway.search_faqs(
                SearchFAQsRequest(query="peso")
            )

    async def test_parallel_requests_do_not_share_customer_or_experience(self):
        self.weather.value = weather_snapshot(wind=24, gust=30)
        with self.assertLogs("parachute.mcp_server", level="INFO") as captured:
            approved, rejected = await asyncio.gather(
                self.run_remote(
                    RequestContext(
                        "Reserva el 2026-10-20",
                        customer="Cliente experimentada",
                        experienced_tandem=True,
                    ),
                    correlation_id="corr-experienced",
                ),
                self.run_remote(
                    RequestContext(
                        "Reserva el 2026-10-20",
                        customer="Cliente inicial",
                        experienced_tandem=False,
                    ),
                    correlation_id="corr-beginner",
                ),
            )

        self.assertIn("creada", approved)
        self.assertIn("requiere un tándem experimentado", rejected)
        self.assertEqual(
            self.stored_appointments(),
            [("Cliente experimentada", "2026-10-20", "marginal")],
        )
        logs = "\n".join(captured.output)
        self.assertIn("correlation_id=corr-experienced", logs)
        self.assertIn("correlation_id=corr-beginner", logs)

    async def test_uncertain_write_is_not_retried_or_reported_as_rejected(self):
        weather = WeatherData.from_domain(weather_snapshot())
        safety = SafetyData(
            level=SafetyLevel.IDEAL,
            reasons=["Condiciones adecuadas."],
            can_schedule=True,
            requires_experienced_tandem=False,
            weather=weather,
        )
        gateway = AsyncMock()
        gateway.extract_date.return_value = ExtractDateResult(
            ok=True,
            data=ExtractedDateData(requested_date=TEST_DATE),
        )
        gateway.get_weather.return_value = WeatherResult(ok=True, data=weather)
        gateway.assess_safety.return_value = SafetyResult(ok=True, data=safety)
        gateway.create_appointment.side_effect = MCPWriteOutcomeUnknownError(
            "respuesta perdida"
        )
        supervisor = MCPAsyncCentralSupervisor(gateway)

        answer = await supervisor.run(
            RequestContext("Reserva el 2026-10-20", customer="Ana"),
            correlation_id="corr-uncertain",
        )

        self.assertEqual(answer, MCP_WRITE_UNCONFIRMED)
        gateway.create_appointment.assert_awaited_once()
        self.assertNotIn("no se creó", answer.casefold())


if __name__ == "__main__":
    unittest.main()
