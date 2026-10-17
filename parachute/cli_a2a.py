from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

import httpx
from a2a.client import (
    A2ACardResolver,
    Client,
    ClientCallContext,
    ClientConfig,
    create_client,
)
from a2a.client.errors import A2AClientError, AgentCardResolutionError
from a2a.helpers.proto_helpers import (
    get_data_parts,
    get_message_text,
    new_data_part,
    new_text_part,
)
from a2a.types.a2a_pb2 import AgentCard, Message, Role, SendMessageRequest
from a2a.utils.constants import TransportProtocol
from dotenv import load_dotenv
from pydantic import ValidationError

from config import a2a_server_url

from .a2a_contracts import A2ARequestData, A2AResponseCategory, A2AResponseData


DEFAULT_TIMEOUT_SECONDS = 10.0
EXIT_COMMANDS = frozenset({"salir", "exit"})


class TerminalClientError(RuntimeError):
    """Error controlado que puede mostrarse sin traceback."""


class DiscoveryError(TerminalClientError):
    pass


class ResponseUncertainError(TerminalClientError):
    pass


class IncompatibleResponseError(TerminalClientError):
    pass


@dataclass(frozen=True)
class TerminalOptions:
    server_url: str
    cliente: str | None
    experienced_tandem: bool


@dataclass(frozen=True)
class TerminalResponse:
    text: str
    data: A2AResponseData


class TerminalSession(Protocol):
    async def connect(self) -> AgentCard: ...

    async def ask(self, text: str) -> TerminalResponse: ...

    async def close(self) -> None: ...


class A2ATerminalSession:
    """Sesión de terminal que sólo conoce el protocolo público A2A."""

    def __init__(
        self,
        options: TerminalOptions,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.options = options
        self.timeout_seconds = timeout_seconds
        self._id_factory = id_factory or (lambda: uuid4().hex)
        self._http_client: httpx.AsyncClient | None = None
        self._client: Client | None = None

    async def connect(self) -> AgentCard:
        if self._client is not None:
            raise TerminalClientError("La sesión A2A ya está conectada.")

        http_client = httpx.AsyncClient(timeout=self.timeout_seconds)
        self._http_client = http_client
        try:
            card = await A2ACardResolver(
                http_client,
                self.options.server_url,
            ).get_agent_card()
            self._client = await create_client(
                card,
                client_config=ClientConfig(
                    streaming=False,
                    httpx_client=http_client,
                    supported_protocol_bindings=[
                        TransportProtocol.JSONRPC.value
                    ],
                    accepted_output_modes=["text/plain", "application/json"],
                ),
            )
            return card
        except (AgentCardResolutionError, httpx.HTTPError, OSError) as exc:
            await self.close()
            raise DiscoveryError(
                "No se pudo descubrir la Agent Card del servidor A2A."
            ) from exc
        except (ValueError, A2AClientError) as exc:
            await self.close()
            raise DiscoveryError(
                "La Agent Card no anuncia una interfaz A2A compatible."
            ) from exc
        except Exception as exc:  # frontera defensiva del descubrimiento
            await self.close()
            raise DiscoveryError(
                "El servidor devolvió una Agent Card incompatible."
            ) from exc

    def build_request(self, text: str) -> SendMessageRequest:
        try:
            request_data = A2ARequestData(
                cliente=self.options.cliente,
                experienced_tandem=self.options.experienced_tandem,
            )
        except ValidationError as exc:
            raise TerminalClientError(
                "El cliente debe ser texto no vacío y sin espacios externos."
            ) from exc

        return SendMessageRequest(
            message=Message(
                message_id=self._id_factory(),
                context_id=self._id_factory(),
                role=Role.ROLE_USER,
                parts=[
                    new_text_part(text, media_type="text/plain"),
                    new_data_part(
                        request_data.model_dump(mode="json"),
                        media_type="application/json",
                    ),
                ],
            )
        )

    async def ask(self, text: str) -> TerminalResponse:
        if self._client is None:
            raise TerminalClientError("La sesión A2A no está conectada.")

        request = self.build_request(text)
        try:
            responses = [
                response
                async for response in self._client.send_message(
                    request,
                    context=ClientCallContext(timeout=self.timeout_seconds),
                )
            ]
        except (A2AClientError, httpx.HTTPError, OSError, TimeoutError) as exc:
            raise ResponseUncertainError(
                "Se perdió la respuesta del servidor. Si la solicitud era una "
                "reserva, su resultado no pudo confirmarse; no se reenviará "
                "automáticamente porque podría haberse creado."
            ) from exc
        except Exception as exc:  # la solicitud ya pudo haber salido
            raise ResponseUncertainError(
                "No se pudo interpretar la respuesta. Si la solicitud era una "
                "reserva, su resultado no pudo confirmarse; no se reenviará "
                "automáticamente."
            ) from exc

        if len(responses) != 1 or not responses[0].HasField("message"):
            raise IncompatibleResponseError(
                "El servidor devolvió un ciclo de respuesta A2A incompatible."
            )

        message = responses[0].message
        text_response = get_message_text(message).strip()
        data_parts = get_data_parts(message.parts)
        if not text_response or len(data_parts) != 1:
            raise IncompatibleResponseError(
                "La respuesta no contiene el texto y los datos esperados."
            )
        try:
            response_data = A2AResponseData.model_validate(data_parts[0])
        except ValidationError as exc:
            raise IncompatibleResponseError(
                "Los datos de la respuesta no cumplen el contrato A2A."
            ) from exc
        return TerminalResponse(text=text_response, data=response_data)

    async def close(self) -> None:
        client, self._client = self._client, None
        http_client, self._http_client = self._http_client, None
        try:
            if client is not None:
                await client.close()
        finally:
            if http_client is not None and not http_client.is_closed:
                await http_client.aclose()


def build_parser(*, default_server_url: str | None = None) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Terminal A2A para Asistente Parachute S.A."
    )
    parser.add_argument(
        "--server-url",
        default=default_server_url or a2a_server_url(),
        help="URL base del servidor A2A (predeterminada: %(default)s).",
    )
    parser.add_argument(
        "--cliente",
        default=None,
        help="Nombre exacto del cliente; es obligatorio para reservar.",
    )
    parser.add_argument(
        "--tandem-experimentado",
        action="store_true",
        help="Declara experiencia tándem; está desactivada por defecto.",
    )
    return parser


def options_from_namespace(args: argparse.Namespace) -> TerminalOptions:
    return TerminalOptions(
        server_url=args.server_url.rstrip("/"),
        cliente=args.cliente,
        experienced_tandem=args.tandem_experimentado,
    )


def describe_card(card: AgentCard) -> list[str]:
    skill_names = ", ".join(skill.name for skill in card.skills) or "ninguna"
    capabilities = ["respuestas directas"]
    if card.capabilities.streaming:
        capabilities.append("streaming")
    if card.capabilities.push_notifications:
        capabilities.append("notificaciones push")
    return [
        f"Conectado a: {card.name}",
        f"Skills: {skill_names}",
        f"Capacidades: {', '.join(capabilities)}",
    ]


def format_response(response: TerminalResponse) -> list[str]:
    category = response.data.category
    if category is A2AResponseCategory.BUSINESS_RESULT:
        label = (
            "FAQ procesada"
            if response.data.route.value == "faq"
            else "Reserva procesada; el mensaje indica si fue creada o rechazada"
        )
    elif category is A2AResponseCategory.INVALID_INPUT:
        label = "Entrada inválida"
    elif category is A2AResponseCategory.MCP_ERROR:
        label = "Error MCP"
    elif category is A2AResponseCategory.INFRASTRUCTURE_ERROR:
        label = "Error de infraestructura"
    else:
        label = "Resultado de reserva incierto"

    lines = [f"[{label}]", response.text]
    if category is A2AResponseCategory.WRITE_OUTCOME_UNKNOWN:
        lines.append(
            "No repitas la reserva sin revisar antes la agenda: podría haberse creado."
        )
    return lines


async def run_terminal(
    options: TerminalOptions,
    *,
    input_func: Callable[[str], str] = input,
    output_func: Callable[[str], None] = print,
    session_factory: Callable[[TerminalOptions], TerminalSession] = (
        A2ATerminalSession
    ),
) -> int:
    session = session_factory(options)
    try:
        try:
            card = await session.connect()
        except DiscoveryError as exc:
            output_func(f"Error de conexión: {exc}")
            return 2

        for line in describe_card(card):
            output_func(line)
        output_func(
            "Cada consulta es independiente. Escribe salir o exit para terminar."
        )

        while True:
            try:
                raw_message = input_func("Tú: ")
            except (EOFError, KeyboardInterrupt):
                output_func("Hasta luego.")
                return 0

            message = raw_message.strip()
            if message.casefold() in EXIT_COMMANDS:
                output_func("Hasta luego.")
                return 0
            if not message:
                continue

            try:
                response = await session.ask(message)
                for line in format_response(response):
                    output_func(line)
            except ResponseUncertainError as exc:
                output_func(f"[Resultado incierto] {exc}")
            except IncompatibleResponseError as exc:
                output_func(f"[Respuesta incompatible] {exc}")
            except TerminalClientError as exc:
                output_func(f"[Error del cliente] {exc}")
    finally:
        try:
            await session.close()
        except Exception:
            output_func(
                "Advertencia: no se pudo confirmar el cierre de la conexión A2A."
            )


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)
    options = options_from_namespace(args)
    try:
        return asyncio.run(run_terminal(options))
    except KeyboardInterrupt:
        print("\nHasta luego.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
