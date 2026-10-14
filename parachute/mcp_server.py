from __future__ import annotations

import logging
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date
from typing import Any, TypeVar

from anyio import to_thread
from dotenv import load_dotenv
from mcp.server import MCPServer
from mcp.server.mcpserver import Context

from app import NO_ANSWER
from config import log_level, mcp_host, mcp_port
from knowledge_base import KnowledgeBase

from .agents import DateAgent, RequestContext, SchedulingAgent
from .calendar import AppointmentRepository, DuplicateAppointmentError
from .safety import assess_weather, safety_policy_markdown
from .tool_contracts import (
    AppointmentData,
    AppointmentDecisionData,
    AppointmentOutcome,
    CreateAppointmentRequest,
    CreateAppointmentResult,
    ExtractDateRequest,
    ExtractDateResult,
    ExtractedDateData,
    FAQEvidence,
    FAQSearchData,
    SafetyData,
    SafetyRequest,
    SafetyResult,
    SearchFAQsRequest,
    SearchFAQsResult,
    ToolError,
    ToolErrorKind,
    ToolResult,
    WeatherData,
    WeatherRequest,
    WeatherResult,
)
from .tool_gateway import ParachuteToolGateway
from .weather import ForecastDateError, WeatherService


logger = logging.getLogger(__name__)
ResultT = TypeVar("ResultT", bound=ToolResult[Any])


@dataclass(frozen=True)
class MCPDependencies:
    knowledge_base: Any
    weather_service: Any
    appointment_repository: AppointmentRepository
    date_agent: DateAgent

    @classmethod
    def from_env(cls) -> "MCPDependencies":
        return cls(
            knowledge_base=KnowledgeBase.from_env(),
            weather_service=WeatherService(),
            appointment_repository=AppointmentRepository(
                os.getenv("APPOINTMENTS_DB", "appointments.sqlite3")
            ),
            date_agent=DateAgent(),
        )


class ToolOperationError(Exception):
    def __init__(
        self,
        *,
        kind: ToolErrorKind,
        code: str,
        message: str,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.error = ToolError(
            kind=kind,
            code=code,
            message=message,
            retryable=retryable,
        )


def _correlation_id(explicit: str | None, context: Context) -> str:
    if explicit:
        return explicit
    request_id = context.request_id
    return str(request_id) if request_id is not None else "sin-correlacion"


def _result_summary(result: ToolResult[Any]) -> str:
    if not result.ok:
        return f"error:{result.error.code if result.error else 'unknown'}"
    data = result.data
    if isinstance(data, FAQSearchData):
        return f"evidencias:{len(data.evidence)}"
    if isinstance(data, AppointmentDecisionData):
        return f"reserva:{data.outcome.value}"
    if isinstance(data, SafetyData):
        return f"seguridad:{data.level.value}"
    return "ok"


async def _run_tool(
    *,
    name: str,
    correlation_id: str,
    safe_parameters: dict[str, Any],
    result_type: type[ResultT],
    operation: Callable[[], Awaitable[ResultT]],
) -> ResultT:
    started = time.perf_counter()
    logger.info(
        "mcp.tool.start tool=%s correlation_id=%s params=%s",
        name,
        correlation_id,
        safe_parameters,
    )
    try:
        result = await operation()
    except ToolOperationError as exc:
        result = result_type(ok=False, error=exc.error)
    except Exception as exc:  # frontera defensiva: nunca filtra detalles internos
        logger.error(
            "mcp.tool.unexpected tool=%s correlation_id=%s error_type=%s",
            name,
            correlation_id,
            type(exc).__name__,
        )
        result = result_type(
            ok=False,
            error=ToolError(
                kind=ToolErrorKind.INFRASTRUCTURE,
                code="internal_error",
                message="Error interno al ejecutar la herramienta.",
                retryable=False,
            ),
        )
    duration_ms = (time.perf_counter() - started) * 1_000
    log_method = logger.info if result.ok else logger.warning
    log_method(
        "mcp.tool.finish tool=%s correlation_id=%s duration_ms=%.2f result=%s",
        name,
        correlation_id,
        duration_ms,
        _result_summary(result),
    )
    return result


def _domain_error(code: str, message: str) -> ToolOperationError:
    return ToolOperationError(kind=ToolErrorKind.DOMAIN, code=code, message=message)


def _infrastructure_error(
    code: str, message: str, *, retryable: bool = True
) -> ToolOperationError:
    return ToolOperationError(
        kind=ToolErrorKind.INFRASTRUCTURE,
        code=code,
        message=message,
        retryable=retryable,
    )


def _validated_weather(snapshot: Any, requested_date: date) -> WeatherData:
    try:
        weather = WeatherData.from_domain(snapshot)
    except (AttributeError, TypeError, ValueError) as exc:
        raise _infrastructure_error(
            "weather_unavailable",
            "El servicio meteorológico devolvió datos incompletos o inválidos.",
        ) from exc
    if weather.requested_date != requested_date:
        raise _infrastructure_error(
            "weather_unavailable",
            "El pronóstico recibido no corresponde a la fecha solicitada.",
        )
    return weather


class DomainToolGateway:
    """Implementación asíncrona del gateway sobre los servicios de dominio."""

    def __init__(self, dependencies: MCPDependencies) -> None:
        self.dependencies = dependencies

    async def search_faqs(self, request: SearchFAQsRequest) -> SearchFAQsResult:
        async def operation() -> SearchFAQsResult:
            try:
                rows = await to_thread.run_sync(
                    lambda: self.dependencies.knowledge_base.search(
                        request.query, limit=request.limit
                    )
                )
            except Exception as exc:
                raise _infrastructure_error(
                    "faq_search_unavailable",
                    "No se pudo consultar la base de preguntas frecuentes.",
                ) from exc
            evidence = [FAQEvidence.from_search_result(item) for item in rows]
            return SearchFAQsResult(
                ok=True,
                data=FAQSearchData(query=request.query, evidence=evidence),
            )

        return await _run_tool(
            name="buscar_faqs",
            correlation_id=request.correlation_id or "sin-correlacion",
            safe_parameters={"query_length": len(request.query), "limit": request.limit},
            result_type=SearchFAQsResult,
            operation=operation,
        )

    async def extract_date(self, request: ExtractDateRequest) -> ExtractDateResult:
        async def operation() -> ExtractDateResult:
            try:
                requested = self.dependencies.date_agent.extract(request.text)
            except ValueError as exc:
                raise _domain_error("invalid_date", str(exc)) from exc
            return ExtractDateResult(
                ok=True, data=ExtractedDateData(requested_date=requested)
            )

        return await _run_tool(
            name="extraer_fecha",
            correlation_id=request.correlation_id or "sin-correlacion",
            safe_parameters={"text_length": len(request.text)},
            result_type=ExtractDateResult,
            operation=operation,
        )

    async def get_weather(self, request: WeatherRequest) -> WeatherResult:
        async def operation() -> WeatherResult:
            try:
                snapshot = await to_thread.run_sync(
                    self.dependencies.weather_service.forecast,
                    request.requested_date,
                )
            except ForecastDateError as exc:
                raise _domain_error("date_out_of_range", str(exc)) from exc
            except Exception as exc:
                raise _infrastructure_error(
                    "weather_unavailable",
                    "No se pudo obtener un pronóstico meteorológico válido.",
                ) from exc
            return WeatherResult(
                ok=True,
                data=_validated_weather(snapshot, request.requested_date),
            )

        return await _run_tool(
            name="consultar_clima",
            correlation_id=request.correlation_id or "sin-correlacion",
            safe_parameters={"requested_date": request.requested_date.isoformat()},
            result_type=WeatherResult,
            operation=operation,
        )

    async def assess_safety(self, request: SafetyRequest) -> SafetyResult:
        async def operation() -> SafetyResult:
            assessment = assess_weather(request.weather.to_domain())
            return SafetyResult(ok=True, data=SafetyData.from_domain(assessment))

        return await _run_tool(
            name="evaluar_seguridad",
            correlation_id=request.correlation_id or "sin-correlacion",
            safe_parameters={"requested_date": request.weather.requested_date.isoformat()},
            result_type=SafetyResult,
            operation=operation,
        )

    async def create_appointment(
        self, request: CreateAppointmentRequest
    ) -> CreateAppointmentResult:
        async def operation() -> CreateAppointmentResult:
            try:
                snapshot = await to_thread.run_sync(
                    self.dependencies.weather_service.forecast,
                    request.requested_date,
                )
            except ForecastDateError as exc:
                raise _domain_error("date_out_of_range", str(exc)) from exc
            except Exception as exc:
                raise _infrastructure_error(
                    "weather_unavailable",
                    "No se pudo obtener un pronóstico meteorológico válido; "
                    "la cita no fue creada.",
                ) from exc

            weather = _validated_weather(snapshot, request.requested_date)
            assessment = assess_weather(weather.to_domain())
            safety = SafetyData.from_domain(assessment)
            scheduler = SchedulingAgent(
                self.dependencies.appointment_repository
            )
            context = RequestContext(
                message=f"cita {request.requested_date.isoformat()}",
                customer=request.customer,
                experienced_tandem=request.experienced_tandem,
            )
            try:
                decision = await to_thread.run_sync(
                    scheduler.run, context, request.requested_date, assessment
                )
            except DuplicateAppointmentError as exc:
                return CreateAppointmentResult(
                    ok=True,
                    data=AppointmentDecisionData(
                        outcome=AppointmentOutcome.DUPLICATE,
                        message=str(exc),
                        assessment=safety,
                    ),
                )
            except Exception as exc:
                raise _infrastructure_error(
                    "appointment_storage_unavailable",
                    "No se pudo guardar la cita.",
                ) from exc

            if decision.appointment is None:
                return CreateAppointmentResult(
                    ok=True,
                    data=AppointmentDecisionData(
                        outcome=AppointmentOutcome.REJECTED,
                        message=decision.message,
                        assessment=safety,
                    ),
                )
            return CreateAppointmentResult(
                ok=True,
                data=AppointmentDecisionData(
                    outcome=AppointmentOutcome.CREATED,
                    message=decision.message,
                    assessment=safety,
                    appointment=AppointmentData.from_domain(decision.appointment),
                ),
            )

        return await _run_tool(
            name="crear_cita",
            correlation_id=request.correlation_id or "sin-correlacion",
            safe_parameters={
                "requested_date": request.requested_date.isoformat(),
                "experienced_tandem": request.experienced_tandem,
                "customer_provided": bool(request.customer),
            },
            result_type=CreateAppointmentResult,
            operation=operation,
        )


def _with_context_correlation(
    request: Any, context: Context
) -> Any:
    if request.correlation_id:
        return request
    return request.model_copy(
        update={"correlation_id": _correlation_id(None, context)}
    )


def create_mcp_server(
    dependencies: MCPDependencies | None = None,
) -> MCPServer:
    deps = dependencies or MCPDependencies.from_env()
    server = MCPServer(
        name="parachute-tools",
        title="Herramientas de Parachute S.A.",
        description="FAQs, clima, seguridad y reservas de Parachute S.A.",
        version="1.0.0",
        log_level=log_level(),
    )
    gateway: ParachuteToolGateway = DomainToolGateway(deps)

    @server.tool(
        name="buscar_faqs",
        description="Busca evidencias en el corpus de preguntas frecuentes.",
        structured_output=True,
    )
    async def buscar_faqs(
        request: SearchFAQsRequest,
        ctx: Context,
    ) -> SearchFAQsResult:
        return await gateway.search_faqs(_with_context_correlation(request, ctx))

    @server.tool(
        name="extraer_fecha",
        description="Extrae una fecha ISO AAAA-MM-DD de una solicitud.",
        structured_output=True,
    )
    async def extraer_fecha(
        request: ExtractDateRequest,
        ctx: Context,
    ) -> ExtractDateResult:
        return await gateway.extract_date(_with_context_correlation(request, ctx))

    @server.tool(
        name="consultar_clima",
        description=(
            "Consulta el pronóstico de Open-Meteo para una fecha ISO y devuelve "
            "unidades explícitas."
        ),
        structured_output=True,
    )
    async def consultar_clima(
        request: WeatherRequest,
        ctx: Context,
    ) -> WeatherResult:
        return await gateway.get_weather(_with_context_correlation(request, ctx))

    @server.tool(
        name="evaluar_seguridad",
        description="Aplica las reglas deterministas de seguridad al pronóstico.",
        structured_output=True,
    )
    async def evaluar_seguridad(
        request: SafetyRequest,
        ctx: Context,
    ) -> SafetyResult:
        return await gateway.assess_safety(_with_context_correlation(request, ctx))

    @server.tool(
        name="crear_cita",
        description=(
            "Consulta nuevamente el clima, evalúa la seguridad en el servidor y "
            "solo entonces crea una cita."
        ),
        structured_output=True,
    )
    async def crear_cita(
        request: CreateAppointmentRequest,
        ctx: Context,
    ) -> CreateAppointmentResult:
        return await gateway.create_appointment(
            _with_context_correlation(request, ctx)
        )

    @server.resource(
        "parachute://politicas/seguridad",
        name="politicas_seguridad",
        title="Políticas meteorológicas de seguridad",
        description="Umbrales deterministas usados para aceptar o rechazar citas.",
        mime_type="text/markdown",
    )
    def politicas_seguridad() -> str:
        return safety_policy_markdown()

    @server.prompt(
        name="consulta_faq",
        title="Consulta de preguntas frecuentes",
        description="Guía para responder usando únicamente evidencia del corpus.",
    )
    def consulta_faq(pregunta: str) -> str:
        return (
            "Busca primero evidencia con la herramienta buscar_faqs para esta "
            f"pregunta: {pregunta}\n"
            "Responde en español, brevemente y solo con la evidencia recuperada. "
            "Incluye los identificadores de las fichas entre paréntesis, por "
            f"ejemplo (FAQ-021). Sin evidencia responde exactamente: {NO_ANSWER}"
        )

    return server


def main() -> None:
    load_dotenv()
    logging.basicConfig(
        level=getattr(logging, log_level()),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    host = mcp_host()
    port = mcp_port()
    logger.info(
        "mcp.server.start transport=streamable-http url=http://%s:%s/mcp",
        host,
        port,
    )
    try:
        create_mcp_server().run(
            transport="streamable-http",
            host=host,
            port=port,
            streamable_http_path="/mcp",
        )
    except KeyboardInterrupt:
        logger.info("mcp.server.stop")


if __name__ == "__main__":
    main()
