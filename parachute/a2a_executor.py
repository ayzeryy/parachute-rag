from __future__ import annotations

import logging
import time
from collections.abc import Callable

from a2a.helpers.proto_helpers import (
    get_data_parts,
    new_data_part,
    new_message,
    new_text_part,
)
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events.event_queue_v2 import EventQueue
from a2a.types.a2a_pb2 import Role
from a2a.utils.errors import UnsupportedOperationError
from pydantic import ValidationError

from config import mcp_server_url, mcp_timeout_seconds

from .a2a_contracts import (
    A2AInputError,
    A2ARequestData,
    A2AResponseCategory,
    A2AResponseData,
    A2ARoute,
    ParsedA2ARequest,
)
from .agents import Intent, RequestContext as ParachuteRequestContext, TriageAgent
from .mcp_centralized import (
    MCPAsyncCentralSupervisor,
    MCPExecutionKind,
    MCPExecutionResult,
    execution_result_from_error,
)
from .mcp_client import MCPClientError, RemoteMCPToolGateway


logger = logging.getLogger(__name__)
GatewayFactory = Callable[[], RemoteMCPToolGateway]


def _route_for(intent: Intent) -> A2ARoute:
    return (
        A2ARoute.APPOINTMENT
        if intent is Intent.APPOINTMENT
        else A2ARoute.FAQ
    )


def parse_a2a_request(
    context: RequestContext,
    triage: TriageAgent,
) -> ParsedA2ARequest:
    """Valida el contrato: una parte texto y, como máximo, una parte JSON."""

    message = context.message
    if message is None:
        raise A2AInputError("La solicitud no contiene un mensaje.")
    if message.role != Role.ROLE_USER:
        raise A2AInputError("El mensaje debe tener el rol de usuario.")
    if not message.message_id:
        raise A2AInputError("El mensaje debe incluir message_id.")

    text_parts = [part.text for part in message.parts if part.HasField("text")]
    data_parts = get_data_parts(message.parts)
    supported_parts = len(text_parts) + len(data_parts)
    if supported_parts != len(message.parts):
        raise A2AInputError(
            "Solo se admiten una parte de texto y una parte de datos JSON."
        )
    if len(text_parts) != 1 or not text_parts[0].strip():
        raise A2AInputError(
            "La solicitud debe contener exactamente una parte de texto no vacía."
        )
    if len(text_parts[0]) > 2_000:
        raise A2AInputError("El texto no puede superar 2000 caracteres.")
    if len(data_parts) > 1:
        raise A2AInputError("La solicitud admite una sola parte de datos JSON.")

    raw_data = data_parts[0] if data_parts else {}
    if not isinstance(raw_data, dict):
        raise A2AInputError("La parte de datos debe ser un objeto JSON.")
    try:
        request_data = A2ARequestData.model_validate(raw_data)
    except ValidationError as exc:
        raise A2AInputError(
            "La parte de datos debe usar cliente como texto y "
            "experienced_tandem como booleano."
        ) from exc

    route = _route_for(triage.classify(text_parts[0]))
    if route is A2ARoute.APPOINTMENT and request_data.cliente is None:
        raise A2AInputError(
            "Para reservar debes enviar un cliente válido en la parte de datos.",
            route=route,
        )

    return ParsedA2ARequest(
        text=text_parts[0],
        data=request_data,
        route=route,
        message_id=message.message_id,
        context_id=context.context_id or message.context_id,
    )


def _response_category(kind: MCPExecutionKind) -> A2AResponseCategory:
    categories = {
        MCPExecutionKind.BUSINESS_RESULT: A2AResponseCategory.BUSINESS_RESULT,
        MCPExecutionKind.DOMAIN_ERROR: A2AResponseCategory.INVALID_INPUT,
        MCPExecutionKind.MCP_ERROR: A2AResponseCategory.MCP_ERROR,
        MCPExecutionKind.INFRASTRUCTURE_ERROR: (
            A2AResponseCategory.INFRASTRUCTURE_ERROR
        ),
        MCPExecutionKind.WRITE_OUTCOME_UNKNOWN: (
            A2AResponseCategory.WRITE_OUTCOME_UNKNOWN
        ),
    }
    return categories[kind]


class ParachuteA2AExecutor(AgentExecutor):
    """Adapta mensajes A2A al supervisor que usa exclusivamente MCP."""

    def __init__(
        self,
        *,
        gateway_factory: GatewayFactory | None = None,
        triage: TriageAgent | None = None,
    ) -> None:
        self.triage = triage or TriageAgent()
        self._gateway_factory = gateway_factory or self._default_gateway

    @staticmethod
    def _default_gateway() -> RemoteMCPToolGateway:
        return RemoteMCPToolGateway(
            mcp_server_url(),
            timeout_seconds=mcp_timeout_seconds(),
        )

    async def _run_supervisor(
        self,
        request: ParsedA2ARequest,
    ) -> MCPExecutionResult:
        gateway = self._gateway_factory()
        try:
            async with gateway:
                supervisor = MCPAsyncCentralSupervisor(
                    gateway,
                    triage=self.triage,
                )
                return await supervisor.run_result(
                    ParachuteRequestContext(
                        message=request.text,
                        customer=request.data.cliente or "",
                        experienced_tandem=request.data.experienced_tandem,
                    ),
                    correlation_id=request.message_id,
                )
        except MCPClientError as exc:
            return execution_result_from_error(exc)

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        started = time.perf_counter()
        message = context.message
        correlation_id = (
            message.message_id
            if message is not None and message.message_id
            else context.task_id or "sin-correlacion"
        )
        route = A2ARoute.UNKNOWN
        logger.info(
            "a2a.request.received correlation_id=%s task_id=%s context_id=%s",
            correlation_id,
            context.task_id or "sin-tarea",
            context.context_id or "sin-contexto",
        )

        try:
            parsed = parse_a2a_request(context, self.triage)
            route = parsed.route
            logger.info(
                "a2a.request.processing correlation_id=%s route=%s",
                correlation_id,
                route.value,
            )
            execution = await self._run_supervisor(parsed)
            response_text = execution.message
            category = _response_category(execution.kind)
        except A2AInputError as exc:
            route = exc.route
            response_text = str(exc)
            category = A2AResponseCategory.INVALID_INPUT
        except Exception as exc:  # frontera defensiva A2A
            logger.error(
                "a2a.request.unexpected correlation_id=%s error_type=%s",
                correlation_id,
                type(exc).__name__,
            )
            response_text = "No pude completar la solicitud por un error interno."
            category = A2AResponseCategory.INFRASTRUCTURE_ERROR

        response_data = A2AResponseData(
            category=category,
            route=route,
            correlation_id=correlation_id,
        )
        response = new_message(
            parts=[
                new_text_part(response_text, media_type="text/plain"),
                new_data_part(
                    response_data.model_dump(mode="json"),
                    media_type="application/json",
                ),
            ],
            role=Role.ROLE_AGENT,
            task_id=context.task_id,
            context_id=context.context_id,
        )
        await event_queue.enqueue_event(response)

        duration_ms = (time.perf_counter() - started) * 1_000
        log_method = (
            logger.info
            if category is A2AResponseCategory.BUSINESS_RESULT
            else logger.warning
        )
        log_method(
            "a2a.request.finished correlation_id=%s route=%s "
            "result=%s duration_ms=%.2f",
            correlation_id,
            route.value,
            category.value,
            duration_ms,
        )

    async def cancel(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        del context, event_queue
        raise UnsupportedOperationError(
            message="Este agente responde de forma inmediata y no admite cancelación."
        )

