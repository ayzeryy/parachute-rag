from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types.a2a_pb2 import (
    AgentCapabilities,
    AgentCard,
    AgentExtension,
    AgentInterface,
    AgentSkill,
)
from a2a.utils.constants import PROTOCOL_VERSION_1_0, TransportProtocol
from dotenv import load_dotenv
from starlette.applications import Starlette

from config import (
    a2a_host,
    a2a_port,
    a2a_server_url,
    log_level,
    parachute_mode,
)

from .a2a_contracts import RUNTIME_MODE_EXTENSION_URI
from .a2a_executor import ParachuteA2AExecutor


logger = logging.getLogger(__name__)


def create_agent_card(
    public_url: str | None = None,
    *,
    runtime_mode: str | None = None,
) -> AgentCard:
    base_url = (public_url or a2a_server_url()).rstrip("/")
    mode = runtime_mode or parachute_mode()
    input_modes = ["text/plain", "application/json"]
    output_modes = ["text/plain", "application/json"]
    return AgentCard(
        name="Asistente Parachute S.A.",
        description=(
            "Responde preguntas frecuentes con evidencia y procesa solicitudes "
            "de reserva sujetas a clima y seguridad."
        ),
        supported_interfaces=[
            AgentInterface(
                url=f"{base_url}/",
                protocol_binding=TransportProtocol.JSONRPC.value,
                protocol_version=PROTOCOL_VERSION_1_0,
            )
        ],
        version="1.0.0",
        capabilities=AgentCapabilities(
            streaming=False,
            push_notifications=False,
            extended_agent_card=False,
            extensions=[
                AgentExtension(
                    uri=RUNTIME_MODE_EXTENSION_URI,
                    description="Modalidad explícita del servidor Parachute.",
                    required=False,
                    params={"mode": mode},
                )
            ],
        ),
        default_input_modes=input_modes,
        default_output_modes=output_modes,
        skills=[
            AgentSkill(
                id="consultar_faqs",
                name="consultar_faqs",
                description=(
                    "Responde preguntas sobre Parachute S.A. usando evidencia "
                    "del corpus de preguntas frecuentes."
                ),
                tags=["faqs", "rag", "paracaidismo"],
                examples=["¿Cuál es el peso máximo permitido para saltar?"],
                input_modes=input_modes,
                output_modes=output_modes,
            ),
            AgentSkill(
                id="reservar_salto",
                name="reservar_salto",
                description=(
                    "Procesa una solicitud de reserva para una fecha ISO; la "
                    "creación depende del pronóstico y las reglas de seguridad."
                ),
                tags=["reservas", "clima", "seguridad"],
                examples=["Quiero reservar un salto el 2026-10-20."],
                input_modes=input_modes,
                output_modes=output_modes,
            ),
        ],
    )


def create_a2a_app(
    *,
    public_url: str | None = None,
    executor: ParachuteA2AExecutor | None = None,
    runtime_mode: str | None = None,
) -> Starlette:
    """Construye el servidor A2A JSON-RPC 1.0 y su Agent Card pública."""

    mode = runtime_mode or parachute_mode()
    card = create_agent_card(public_url, runtime_mode=mode)
    resolved_executor = executor or ParachuteA2AExecutor()
    handler = DefaultRequestHandler(
        agent_executor=resolved_executor,
        task_store=InMemoryTaskStore(),
        agent_card=card,
        validate_input_modes=True,
    )

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        del app
        interface = card.supported_interfaces[0]
        log_method = logger.warning if mode == "demo" else logger.info
        mode_label = "MODO DEMO" if mode == "demo" else "REAL"
        log_method(
            "a2a.server.start mode=%s agent=%s transport=%s url=%s",
            mode_label,
            card.name,
            interface.protocol_binding,
            interface.url,
        )
        try:
            yield
        finally:
            await handler.aclose()
            logger.info("a2a.server.stop agent=%s", card.name)

    routes = [
        *create_agent_card_routes(card),
        *create_jsonrpc_routes(handler, rpc_url="/"),
    ]
    app = Starlette(routes=routes, lifespan=lifespan)
    app.state.agent_card = card
    app.state.request_handler = handler
    app.state.agent_executor = resolved_executor
    return app


def main() -> None:
    load_dotenv()
    logging.basicConfig(
        level=getattr(logging, log_level()),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    uvicorn.run(
        create_a2a_app(),
        host=a2a_host(),
        port=a2a_port(),
        log_level=log_level().lower(),
    )


if __name__ == "__main__":
    main()

