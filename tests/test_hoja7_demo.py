import asyncio
import io
import os
import re
import sqlite3
import sys
import tempfile
import threading
import unittest
from contextlib import closing, redirect_stdout
from datetime import date
from pathlib import Path
from socket import socket
from unittest.mock import patch

import uvicorn

import config
from app import NO_ANSWER
from parachute.a2a_contracts import RUNTIME_MODE_EXTENSION_URI
from parachute.a2a_executor import ParachuteA2AExecutor
from parachute.a2a_server import create_a2a_app, create_agent_card
from parachute.agents import DateAgent
from parachute.cli_a2a import describe_card
from parachute.demo import (
    DemoAppointmentRepository,
    DemoCalendar,
    DemoKnowledgeBase,
    DemoScenario,
    DemoWeatherService,
    list_demo_appointments,
    reset_demo_appointments,
)
from parachute.demo_admin import main as demo_admin_main
from parachute.mcp_client import RemoteMCPToolGateway
from parachute.mcp_server import MCPDependencies, create_mcp_server
from parachute.models import SafetyLevel
from parachute.safety import assess_weather
from parachute.weather import guatemala_today


def free_port():
    with closing(socket()) as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


class TrackingDemoWeatherService(DemoWeatherService):
    def __init__(self, calendar):
        super().__init__(calendar)
        self.calls = []

    def forecast(self, requested):
        self.calls.append(requested)
        return super().forecast(requested)


class DemoConfigurationTests(unittest.TestCase):
    def test_mode_is_explicit_and_never_falls_back_to_demo(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PARACHUTE_MODE", None)
            self.assertEqual(config.parachute_mode(), "real")
        with patch.dict(os.environ, {"PARACHUTE_MODE": "demo"}):
            self.assertEqual(config.parachute_mode(), "demo")
        with patch.dict(os.environ, {"PARACHUTE_MODE": "automatic"}):
            with self.assertRaises(ValueError):
                config.parachute_mode()

    def test_environment_composes_only_demo_external_substitutes(self):
        with tempfile.TemporaryDirectory() as directory:
            demo_path = Path(directory) / "appointments.demo.sqlite3"
            environment = {
                "PARACHUTE_MODE": "demo",
                "DEMO_APPOINTMENTS_DB": str(demo_path),
                "DEMO_CORPUS_PATH": str(
                    config.PROJECT_ROOT / config.DEFAULT_DEMO_CORPUS
                ),
                "APPOINTMENTS_DB": str(Path(directory) / "production.sqlite3"),
            }
            with patch.dict(os.environ, environment):
                dependencies = MCPDependencies.from_env()

            self.assertIsInstance(
                dependencies.knowledge_base,
                DemoKnowledgeBase,
            )
            self.assertIsInstance(
                dependencies.weather_service,
                DemoWeatherService,
            )
            self.assertIsInstance(
                dependencies.appointment_repository,
                DemoAppointmentRepository,
            )
            self.assertFalse(demo_path.exists())

    def test_demo_database_path_cannot_be_production_or_arbitrary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            demo = root / "appointments.demo.sqlite3"
            production = root / "appointments.sqlite3"
            with patch.dict(
                os.environ,
                {
                    "DEMO_APPOINTMENTS_DB": str(demo),
                    "APPOINTMENTS_DB": str(production),
                },
            ):
                self.assertEqual(config.demo_appointments_db(), demo.resolve())
            with patch.dict(
                os.environ,
                {
                    "DEMO_APPOINTMENTS_DB": str(production),
                    "APPOINTMENTS_DB": str(production),
                },
            ):
                with self.assertRaises(ValueError):
                    config.demo_appointments_db()
            with patch.dict(
                os.environ,
                {
                    "DEMO_APPOINTMENTS_DB": str(root / "otra.sqlite3"),
                    "APPOINTMENTS_DB": str(production),
                },
            ):
                with self.assertRaises(ValueError):
                    config.demo_appointments_db()

    def test_relative_calendar_reuses_domain_safety_rules(self):
        controlled_today = date(2030, 5, 10)
        calendar = DemoCalendar(today_provider=lambda: controlled_today)
        service = DemoWeatherService(calendar)
        days = {item.scenario: item.date for item in calendar.days()}

        ideal = assess_weather(service.forecast(days[DemoScenario.IDEAL]))
        prohibited = assess_weather(
            service.forecast(days[DemoScenario.PROHIBITED])
        )
        wind = assess_weather(
            service.forecast(days[DemoScenario.MARGINAL_WIND])
        )
        clouds = assess_weather(
            service.forecast(days[DemoScenario.MARGINAL_CLOUDS])
        )

        self.assertEqual(ideal.level, SafetyLevel.IDEAL)
        self.assertEqual(prohibited.level, SafetyLevel.PROHIBITED)
        self.assertTrue(wind.requires_experienced_tandem)
        self.assertEqual(clouds.level, SafetyLevel.MARGINAL)
        self.assertFalse(clouds.requires_experienced_tandem)
        self.assertEqual(
            service.forecast(days[DemoScenario.IDEAL]),
            service.forecast(days[DemoScenario.IDEAL]),
        )

    def test_demo_faq_uses_verified_real_corpus_record(self):
        knowledge_base = DemoKnowledgeBase(
            config.PROJECT_ROOT / config.DEFAULT_DEMO_CORPUS
        )
        evidence = knowledge_base.search(
            "¿Cuál es el peso máximo permitido para saltar?"
        )

        self.assertEqual(evidence[0]["id"], "FAQ-021")
        self.assertEqual(
            evidence[0]["pregunta"],
            "¿Cuál es el peso máximo permitido para saltar?",
        )
        self.assertIn("límite de peso máximo estricto", evidence[0]["respuesta"])
        self.assertEqual(
            knowledge_base.search("¿Ofrecen cursos de cocina vegana?"),
            [],
        )

    def test_reset_requires_marked_demo_database_and_admin_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            demo_path = root / "appointments.demo.sqlite3"
            production_path = root / "appointments.sqlite3"
            repository = DemoAppointmentRepository(demo_path)
            calendar = DemoCalendar(today_provider=lambda: date(2030, 5, 10))
            requested = calendar.days()[0].date
            assessment = assess_weather(
                DemoWeatherService(calendar).forecast(requested)
            )
            repository.create("Ana", requested, assessment)
            self.assertEqual(len(list_demo_appointments(demo_path)), 1)

            environment = {
                "DEMO_APPOINTMENTS_DB": str(demo_path),
                "APPOINTMENTS_DB": str(production_path),
            }
            with patch.dict(os.environ, environment), redirect_stdout(io.StringIO()):
                self.assertEqual(demo_admin_main(["reset"]), 2)
                self.assertEqual(len(list_demo_appointments(demo_path)), 1)
                self.assertEqual(
                    demo_admin_main(["reset", "--confirm"]),
                    0,
                )
            self.assertEqual(list_demo_appointments(demo_path), [])

            unmarked = root / "unmarked.demo.sqlite3"
            with closing(sqlite3.connect(unmarked)) as connection:
                connection.execute("CREATE TABLE appointments (id INTEGER)")
            with self.assertRaises(ValueError):
                reset_demo_appointments(unmarked)

    def test_agent_card_explicitly_announces_demo_mode(self):
        card = create_agent_card(
            "http://127.0.0.1:8000",
            runtime_mode="demo",
        )
        extension = next(
            item
            for item in card.capabilities.extensions
            if item.uri == RUNTIME_MODE_EXTENSION_URI
        )
        self.assertEqual(extension.params.fields["mode"].string_value, "demo")
        self.assertIn("Modo del servidor: MODO DEMO", describe_card(card))


class DemoEndToEndTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        asyncio.get_running_loop().set_debug(False)
        self.temp_directory = tempfile.TemporaryDirectory()
        self.db_path = (
            Path(self.temp_directory.name) / "appointments.demo.sqlite3"
        )
        self.today = guatemala_today()
        self.calendar = DemoCalendar(today_provider=lambda: self.today)
        self.weather = TrackingDemoWeatherService(self.calendar)
        self.repository = DemoAppointmentRepository(self.db_path)
        dependencies = MCPDependencies(
            knowledge_base=DemoKnowledgeBase(
                config.PROJECT_ROOT / config.DEFAULT_DEMO_CORPUS
            ),
            weather_service=self.weather,
            appointment_repository=self.repository,
            date_agent=DateAgent(),
        )

        self.mcp_port = free_port()
        self.mcp_url = f"http://127.0.0.1:{self.mcp_port}/mcp"
        with self.assertLogs(
            "parachute.mcp_server", level="WARNING"
        ) as mcp_start:
            mcp_server = create_mcp_server(
                dependencies,
                runtime_mode="demo",
            )
        self.assertIn("MODO DEMO", "\n".join(mcp_start.output))
        mcp_app = mcp_server.streamable_http_app(
            streamable_http_path="/mcp",
            stateless_http=True,
            json_response=True,
            host="127.0.0.1",
        )
        self.mcp_uvicorn, self.mcp_thread = await self.start_server(
            mcp_app, self.mcp_port
        )

        def gateway_factory():
            return RemoteMCPToolGateway(self.mcp_url, timeout_seconds=5)

        self.a2a_port = free_port()
        self.a2a_url = f"http://127.0.0.1:{self.a2a_port}"
        a2a_app = create_a2a_app(
            public_url=self.a2a_url,
            executor=ParachuteA2AExecutor(gateway_factory=gateway_factory),
            runtime_mode="demo",
        )
        with self.assertLogs(
            "parachute.a2a_server", level="WARNING"
        ) as a2a_start:
            self.a2a_uvicorn, self.a2a_thread = await self.start_server(
                a2a_app, self.a2a_port
            )
        self.assertIn("MODO DEMO", "\n".join(a2a_start.output))

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

    async def run_cli(self, customer, queries, *, experienced=False):
        project_root = Path(__file__).resolve().parents[1]
        environment = os.environ.copy()
        environment["PYTHONIOENCODING"] = "utf-8"
        environment.pop("NVIDIA_API_KEY", None)
        arguments = [
            sys.executable,
            "-m",
            "parachute.cli_a2a",
            "--server-url",
            self.a2a_url,
            "--cliente",
            customer,
        ]
        if experienced:
            arguments.append("--tandem-experimentado")
        process = await asyncio.create_subprocess_exec(
            *arguments,
            cwd=project_root,
            env=environment,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdin = "\n".join([*queries, "salir", ""])
            stdout, stderr = await asyncio.wait_for(
                process.communicate(stdin.encode("utf-8")),
                timeout=30,
            )
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
        decoded_stderr = stderr.decode("utf-8")
        self.assertEqual(process.returncode, 0, decoded_stderr)
        return stdout.decode("utf-8")

    async def test_complete_demo_route_and_persistence(self):
        days = {item.scenario: item.date for item in self.calendar.days()}
        standard_queries = [
            "¿Cuál es el peso máximo permitido para saltar?",
            "¿Ofrecen cursos de cocina vegana?",
            f"Quiero reservar el {days[DemoScenario.IDEAL].isoformat()}",
            f"Quiero reservar el {days[DemoScenario.PROHIBITED].isoformat()}",
            (
                "Quiero reservar el "
                f"{days[DemoScenario.MARGINAL_WIND].isoformat()}"
            ),
            (
                "Quiero reservar el "
                f"{days[DemoScenario.MARGINAL_CLOUDS].isoformat()}"
            ),
            f"Quiero reservar el {days[DemoScenario.IDEAL].isoformat()}",
        ]
        experienced_queries = [
            (
                "Quiero reservar el "
                f"{days[DemoScenario.MARGINAL_WIND].isoformat()}"
            )
        ]

        with self.assertLogs(
            "parachute.a2a_executor", level="INFO"
        ) as a2a_logs, self.assertLogs(
            "parachute.mcp_server", level="INFO"
        ) as mcp_logs:
            standard_output = await self.run_cli(
                "Cliente Demo",
                standard_queries,
            )
            experienced_output = await self.run_cli(
                "Cliente Experta",
                experienced_queries,
                experienced=True,
            )

        output = standard_output + experienced_output
        self.assertIn("Modo del servidor: MODO DEMO", output)
        self.assertIn("FAQ-021", output)
        self.assertIn("límite de peso máximo estricto", output)
        self.assertIn(NO_ANSWER, output)
        self.assertIn("No se creó la cita. Condición NO_SEGURO", output)
        self.assertIn("requiere un tándem experimentado", output)
        self.assertIn("Ya existe una cita", output)

        stored = list_demo_appointments(self.db_path)
        self.assertEqual(
            [(row[1], row[2], row[3]) for row in stored],
            [
                (
                    "Cliente Demo",
                    days[DemoScenario.IDEAL].isoformat(),
                    "ideal",
                ),
                (
                    "Cliente Demo",
                    days[DemoScenario.MARGINAL_CLOUDS].isoformat(),
                    "marginal",
                ),
                (
                    "Cliente Experta",
                    days[DemoScenario.MARGINAL_WIND].isoformat(),
                    "marginal",
                ),
            ],
        )

        expected_weather_calls = {
            days[DemoScenario.IDEAL]: 4,
            days[DemoScenario.PROHIBITED]: 2,
            days[DemoScenario.MARGINAL_WIND]: 4,
            days[DemoScenario.MARGINAL_CLOUDS]: 2,
        }
        self.assertEqual(
            {
                requested: self.weather.calls.count(requested)
                for requested in expected_weather_calls
            },
            expected_weather_calls,
        )

        correlations = re.findall(r"Correlación: ([0-9a-f]{32})", output)
        self.assertEqual(len(correlations), 8)
        self.assertEqual(len(set(correlations)), 8)
        a2a_output = "\n".join(a2a_logs.output)
        mcp_output = "\n".join(mcp_logs.output)
        for correlation_id in correlations:
            self.assertIn(f"correlation_id={correlation_id}", a2a_output)
            self.assertIn(f"correlation_id={correlation_id}", mcp_output)


if __name__ == "__main__":
    unittest.main()
