import asyncio
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from socket import socket
from unittest.mock import patch

import uvicorn
from a2a.helpers.proto_helpers import get_data_parts, get_message_text

from parachute.a2a_contracts import (
    A2AResponseCategory,
    A2AResponseData,
    A2ARoute,
)
from parachute.a2a_executor import ParachuteA2AExecutor
from parachute.a2a_server import create_a2a_app, create_agent_card
from parachute.agents import DateAgent
from parachute.calendar import AppointmentRepository
from parachute.cli_a2a import (
    A2ATerminalSession,
    ResponseUncertainError,
    TerminalOptions,
    TerminalResponse,
    build_parser,
    format_response,
    options_from_namespace,
    run_terminal,
)
from parachute.mcp_client import RemoteMCPToolGateway
from parachute.mcp_server import MCPDependencies, create_mcp_server


def free_port():
    with closing(socket()) as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


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


class UnexpectedWeatherService:
    def forecast(self, requested):
        raise AssertionError(
            f"La prueba FAQ no debe consultar clima para {requested}"
        )


def response(category, route=A2ARoute.FAQ, text="respuesta"):
    return TerminalResponse(
        text=text,
        data=A2AResponseData(
            category=category,
            route=route,
            correlation_id="corr-test",
        ),
    )


class FakeSession:
    def __init__(self, answers):
        self.answers = iter(answers)
        self.messages = []
        self.closed = False

    async def connect(self):
        return create_agent_card("http://test.invalid")

    async def ask(self, text):
        self.messages.append(text)
        answer = next(self.answers)
        if isinstance(answer, Exception):
            raise answer
        return answer

    async def close(self):
        self.closed = True


class A2ATerminalUnitTests(unittest.IsolatedAsyncioTestCase):
    def test_parser_uses_configuration_and_safe_defaults(self):
        with patch.dict(
            os.environ,
            {"A2A_SERVER_URL": "http://127.0.0.1:9123/"},
        ):
            args = build_parser().parse_args([])
        options = options_from_namespace(args)

        self.assertEqual(options.server_url, "http://127.0.0.1:9123")
        self.assertIsNone(options.cliente)
        self.assertFalse(options.experienced_tandem)
        help_text = build_parser(default_server_url="http://a2a").format_help()
        self.assertIn("--server-url", help_text)
        self.assertIn("--cliente", help_text)
        self.assertIn("--tandem-experimentado", help_text)

    def test_parser_preserves_explicit_customer_and_real_boolean(self):
        args = build_parser(default_server_url="http://a2a").parse_args(
            ["--cliente", "Ana Exacta", "--tandem-experimentado"]
        )
        options = options_from_namespace(args)

        self.assertEqual(options.cliente, "Ana Exacta")
        self.assertIs(options.experienced_tandem, True)

    def test_request_serialization_and_identifiers_are_exact_and_unique(self):
        identifiers = iter(["msg-1", "ctx-1", "msg-2", "ctx-2"])
        session = A2ATerminalSession(
            TerminalOptions("http://a2a", "Ana Exacta", False),
            id_factory=lambda: next(identifiers),
        )

        first = session.build_request("Primera consulta")
        second = session.build_request("Segunda consulta")

        self.assertEqual(first.message.message_id, "msg-1")
        self.assertEqual(first.message.context_id, "ctx-1")
        self.assertEqual(second.message.message_id, "msg-2")
        self.assertEqual(second.message.context_id, "ctx-2")
        self.assertEqual(get_message_text(first.message), "Primera consulta")
        self.assertEqual(
            get_data_parts(first.message.parts),
            [{"cliente": "Ana Exacta", "experienced_tandem": False}],
        )
        self.assertIs(
            get_data_parts(first.message.parts)[0]["experienced_tandem"],
            False,
        )

    async def test_multiple_queries_and_exit_close_the_session(self):
        fake = FakeSession(
            [
                response(A2AResponseCategory.BUSINESS_RESULT),
                response(A2AResponseCategory.INVALID_INPUT),
            ]
        )
        entries = iter(["pregunta uno", "pregunta dos", "salir"])
        output = []

        exit_code = await run_terminal(
            TerminalOptions("http://a2a", None, False),
            input_func=lambda _: next(entries),
            output_func=output.append,
            session_factory=lambda _: fake,
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(fake.messages, ["pregunta uno", "pregunta dos"])
        self.assertTrue(fake.closed)
        self.assertIn("Hasta luego.", output)

    async def test_uncertain_response_is_not_retried(self):
        fake = FakeSession(
            [ResponseUncertainError("resultado no confirmado")]
        )
        entries = iter(["Reserva mañana", "exit"])
        output = []

        await run_terminal(
            TerminalOptions("http://a2a", "Ana", False),
            input_func=lambda _: next(entries),
            output_func=output.append,
            session_factory=lambda _: fake,
        )

        self.assertEqual(fake.messages, ["Reserva mañana"])
        self.assertTrue(fake.closed)
        self.assertTrue(any("Resultado incierto" in line for line in output))

    def test_result_categories_have_distinct_presentations(self):
        cases = {
            A2AResponseCategory.BUSINESS_RESULT: "FAQ procesada",
            A2AResponseCategory.INVALID_INPUT: "Entrada inválida",
            A2AResponseCategory.MCP_ERROR: "Error MCP",
            A2AResponseCategory.INFRASTRUCTURE_ERROR: (
                "Error de infraestructura"
            ),
            A2AResponseCategory.WRITE_OUTCOME_UNKNOWN: (
                "Resultado de reserva incierto"
            ),
        }
        for category, label in cases.items():
            with self.subTest(category=category):
                rendered = "\n".join(format_response(response(category)))
                self.assertIn(label, rendered)
        uncertain = "\n".join(
            format_response(
                response(A2AResponseCategory.WRITE_OUTCOME_UNKNOWN)
            )
        )
        self.assertIn("podría haberse creado", uncertain)

    def test_import_does_not_load_local_execution_components(self):
        project_root = Path(__file__).resolve().parents[1]
        code = (
            "import sys; import parachute.cli_a2a; "
            "forbidden={'parachute.mcp_client','parachute.mcp_server',"
            "'parachute.factory','knowledge_base'}; "
            "assert forbidden.isdisjoint(sys.modules), forbidden & sys.modules"
        )
        completed = subprocess.run(
            [sys.executable, "-c", code],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)


class A2ATerminalEntryPointTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        asyncio.get_running_loop().set_debug(False)
        self.temp_directory = tempfile.TemporaryDirectory()
        self.knowledge_base = FixtureKnowledgeBase()
        dependencies = MCPDependencies(
            knowledge_base=self.knowledge_base,
            weather_service=UnexpectedWeatherService(),
            appointment_repository=AppointmentRepository(
                Path(self.temp_directory.name) / "appointments.sqlite3"
            ),
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

        def gateway_factory():
            return RemoteMCPToolGateway(self.mcp_url, timeout_seconds=5)

        self.a2a_port = free_port()
        self.a2a_url = f"http://127.0.0.1:{self.a2a_port}"
        a2a_app = create_a2a_app(
            public_url=self.a2a_url,
            executor=ParachuteA2AExecutor(
                gateway_factory=gateway_factory
            ),
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

    async def test_real_entry_point_routes_stdin_to_mcp_and_stdout(self):
        project_root = Path(__file__).resolve().parents[1]
        environment = os.environ.copy()
        environment["PYTHONIOENCODING"] = "utf-8"
        environment.pop("NVIDIA_API_KEY", None)
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "parachute.cli_a2a",
            "--server-url",
            self.a2a_url,
            "--cliente",
            "Cliente terminal",
            cwd=project_root,
            env=environment,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(
                    "¿Cuál es el peso máximo?\nsalir\n".encode("utf-8")
                ),
                timeout=15,
            )
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()

        decoded_stdout = stdout.decode("utf-8")
        decoded_stderr = stderr.decode("utf-8")
        self.assertEqual(process.returncode, 0, decoded_stderr)
        self.assertIn("Conectado a: Asistente Parachute S.A.", decoded_stdout)
        self.assertIn("[FAQ procesada]", decoded_stdout)
        self.assertIn("El peso máximo es 100 kg.", decoded_stdout)
        self.assertIn("Hasta luego.", decoded_stdout)
        self.assertEqual(
            self.knowledge_base.calls,
            [("¿Cuál es el peso máximo?", 5)],
        )


if __name__ == "__main__":
    unittest.main()
