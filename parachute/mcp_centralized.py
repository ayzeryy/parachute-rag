from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from uuid import uuid4

from app import NO_ANSWER
from config import mcp_server_url, mcp_timeout_seconds

from .agents import Intent, RequestContext, TriageAgent
from .mcp_client import (
    MCPClientError,
    MCPConnectionError,
    MCPContractError,
    MCPProtocolError,
    MCPRemoteToolError,
    MCPToolCallError,
    MCPWriteOutcomeUnknownError,
    RemoteMCPToolGateway,
)
from .tool_contracts import (
    CreateAppointmentRequest,
    ExtractDateRequest,
    SafetyRequest,
    SearchFAQsRequest,
    ToolErrorKind,
    WeatherRequest,
)
from .tool_gateway import ParachuteToolGateway


MCP_UNAVAILABLE = (
    "No pude completar la solicitud porque el servidor MCP no está disponible."
)
MCP_PROTOCOL_FAILURE = (
    "No pude completar la solicitud por un error de protocolo MCP."
)
MCP_CONTRACT_FAILURE = (
    "No pude completar la solicitud porque el servidor MCP devolvió una "
    "respuesta incompatible."
)
MCP_TOOL_FAILURE = "No pude completar la solicitud en el servidor MCP."
MCP_WRITE_UNCONFIRMED = (
    "No se pudo confirmar el resultado de la reserva porque se perdió la "
    "respuesta del servidor. La solicitud pudo haber sido procesada; verifica "
    "la agenda antes de intentarlo de nuevo."
)


class MCPExecutionKind(str, Enum):
    BUSINESS_RESULT = "business_result"
    DOMAIN_ERROR = "domain_error"
    MCP_ERROR = "mcp_error"
    INFRASTRUCTURE_ERROR = "infrastructure_error"
    WRITE_OUTCOME_UNKNOWN = "write_outcome_unknown"


@dataclass(frozen=True)
class MCPExecutionResult:
    message: str
    kind: MCPExecutionKind


def execution_result_from_error(error: MCPClientError) -> MCPExecutionResult:
    if isinstance(error, MCPWriteOutcomeUnknownError):
        return MCPExecutionResult(
            MCP_WRITE_UNCONFIRMED,
            MCPExecutionKind.WRITE_OUTCOME_UNKNOWN,
        )
    if isinstance(error, MCPContractError):
        return MCPExecutionResult(MCP_CONTRACT_FAILURE, MCPExecutionKind.MCP_ERROR)
    if isinstance(error, MCPRemoteToolError):
        kind = (
            MCPExecutionKind.DOMAIN_ERROR
            if error.error.kind is ToolErrorKind.DOMAIN
            else MCPExecutionKind.INFRASTRUCTURE_ERROR
        )
        return MCPExecutionResult(
            f"No pude completar la solicitud: {error.error.message}",
            kind,
        )
    if isinstance(error, MCPToolCallError):
        return MCPExecutionResult(MCP_TOOL_FAILURE, MCPExecutionKind.MCP_ERROR)
    if isinstance(error, MCPProtocolError):
        return MCPExecutionResult(MCP_PROTOCOL_FAILURE, MCPExecutionKind.MCP_ERROR)
    if isinstance(error, MCPConnectionError):
        return MCPExecutionResult(
            MCP_UNAVAILABLE,
            MCPExecutionKind.INFRASTRUCTURE_ERROR,
        )
    return MCPExecutionResult(MCP_TOOL_FAILURE, MCPExecutionKind.MCP_ERROR)


class MCPAsyncCentralSupervisor:
    """Supervisor central asíncrono; el triaje local delega todo lo demás a MCP."""

    def __init__(
        self,
        gateway: ParachuteToolGateway,
        triage: TriageAgent | None = None,
    ) -> None:
        self.gateway = gateway
        self.triage = triage or TriageAgent()

    async def run(self, context: RequestContext, *, correlation_id: str) -> str:
        return (
            await self.run_result(context, correlation_id=correlation_id)
        ).message

    async def run_result(
        self, context: RequestContext, *, correlation_id: str
    ) -> MCPExecutionResult:
        try:
            intent = self.triage.classify(context.message)
            if intent is Intent.FAQ:
                message = await self._answer_faq(context, correlation_id)
            else:
                message = await self._schedule(context, correlation_id)
            return MCPExecutionResult(
                message,
                MCPExecutionKind.BUSINESS_RESULT,
            )
        except MCPClientError as exc:
            return execution_result_from_error(exc)

    async def _answer_faq(
        self, context: RequestContext, correlation_id: str
    ) -> str:
        result = await self.gateway.search_faqs(
            SearchFAQsRequest(
                query=context.message,
                limit=5,
                correlation_id=correlation_id,
            )
        )
        evidence = result.data.evidence  # ToolResult validado garantiza data
        if not evidence:
            return NO_ANSWER
        return "\n".join(
            f"- {item.answer} ({item.source_id})" for item in evidence[:3]
        )

    async def _schedule(
        self, context: RequestContext, correlation_id: str
    ) -> str:
        extracted = await self.gateway.extract_date(
            ExtractDateRequest(
                text=context.message,
                correlation_id=correlation_id,
            )
        )
        requested_date = extracted.data.requested_date

        weather = await self.gateway.get_weather(
            WeatherRequest(
                requested_date=requested_date,
                correlation_id=correlation_id,
            )
        )
        await self.gateway.assess_safety(
            SafetyRequest(
                weather=weather.data,
                correlation_id=correlation_id,
            )
        )

        # crear_cita vuelve a consultar y evaluar el clima. Su resultado es la
        # autoridad final, aunque difiera de la evaluación preliminar.
        final = await self.gateway.create_appointment(
            CreateAppointmentRequest(
                customer=context.customer,
                requested_date=requested_date,
                experienced_tandem=context.experienced_tandem,
                correlation_id=correlation_id,
            )
        )
        return final.data.message


async def run_centralized_via_mcp(
    context: RequestContext,
    *,
    correlation_id: str | None = None,
    server_url: str | None = None,
    timeout_seconds: float | None = None,
) -> str:
    """Compone una sesión MCP aislada para una solicitud del supervisor."""

    return (
        await run_centralized_result_via_mcp(
            context,
            correlation_id=correlation_id,
            server_url=server_url,
            timeout_seconds=timeout_seconds,
        )
    ).message


async def run_centralized_result_via_mcp(
    context: RequestContext,
    *,
    correlation_id: str | None = None,
    server_url: str | None = None,
    timeout_seconds: float | None = None,
) -> MCPExecutionResult:
    """Ejecuta una solicitud aislada conservando la categoría del resultado."""

    resolved_correlation_id = (
        correlation_id if correlation_id is not None else uuid4().hex
    )
    gateway = RemoteMCPToolGateway(
        server_url or mcp_server_url(),
        timeout_seconds=(
            timeout_seconds
            if timeout_seconds is not None
            else mcp_timeout_seconds()
        ),
    )
    try:
        async with gateway:
            supervisor = MCPAsyncCentralSupervisor(gateway)
            return await supervisor.run_result(
                context,
                correlation_id=resolved_correlation_id,
            )
    except MCPClientError as exc:
        return execution_result_from_error(exc)
