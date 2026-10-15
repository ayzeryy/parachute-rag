from __future__ import annotations

from typing import Any, TypeVar

import httpx
from anyio import Lock
from mcp import Client, MCPError
from pydantic import ValidationError

from .tool_contracts import (
    CreateAppointmentRequest,
    CreateAppointmentResult,
    ExtractDateRequest,
    ExtractDateResult,
    SafetyRequest,
    SafetyResult,
    SearchFAQsRequest,
    SearchFAQsResult,
    ToolError,
    ToolResult,
    WeatherRequest,
    WeatherResult,
)


REQUIRED_TOOLS = frozenset(
    {
        "buscar_faqs",
        "extraer_fecha",
        "consultar_clima",
        "evaluar_seguridad",
        "crear_cita",
    }
)
ResultT = TypeVar("ResultT", bound=ToolResult[Any])


class MCPClientError(RuntimeError):
    """Error controlado al cruzar la frontera del servidor MCP."""


class MCPClientStateError(MCPClientError):
    pass


class MCPConnectionError(MCPClientError):
    pass


class MCPProtocolError(MCPClientError):
    pass


class MCPDiscoveryError(MCPProtocolError):
    pass


class MCPToolCallError(MCPClientError):
    pass


class MCPRemoteToolError(MCPClientError):
    def __init__(self, tool_name: str, error: ToolError) -> None:
        super().__init__(error.message)
        self.tool_name = tool_name
        self.error = error


class MCPContractError(MCPClientError):
    pass


class MCPWriteOutcomeUnknownError(MCPConnectionError):
    """La llamada de escritura salió, pero su respuesta no pudo confirmarse."""


class RemoteMCPToolGateway:
    """Cliente remoto de ``ParachuteToolGateway`` sobre Streamable HTTP.

    Cada instancia es dueña de una sola sesión MCP y se debe usar como contexto
    asíncrono por solicitud del supervisor. Las llamadas se serializan porque el
    SDK mantiene estado de sesión y caché de descubrimiento.
    """

    def __init__(self, server_url: str, *, timeout_seconds: float = 10.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds debe ser mayor que cero")
        self.server_url = server_url
        self.timeout_seconds = timeout_seconds
        self._client: Client | None = None
        self._call_lock = Lock()

    @property
    def is_open(self) -> bool:
        return self._client is not None

    async def __aenter__(self) -> "RemoteMCPToolGateway":
        await self.open()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        await self.close(exc_type, exc_value, traceback)

    async def open(self) -> None:
        if self._client is not None:
            raise MCPClientStateError("El cliente MCP ya está abierto.")

        client = Client(
            self.server_url,
            raise_exceptions=False,
            read_timeout_seconds=self.timeout_seconds,
        )
        try:
            await client.__aenter__()
            discovered = await client.list_tools(cache_mode="refresh")
            tools_by_name = {tool.name: tool for tool in discovered.tools}
            missing = REQUIRED_TOOLS - tools_by_name.keys()
            if missing:
                missing_list = ", ".join(sorted(missing))
                raise MCPDiscoveryError(
                    f"El servidor MCP no publica las herramientas requeridas: "
                    f"{missing_list}."
                )
            incompatible = [
                name
                for name in REQUIRED_TOOLS
                if "request"
                not in tools_by_name[name].input_schema.get("properties", {})
                or "request"
                not in tools_by_name[name].input_schema.get("required", [])
            ]
            if incompatible:
                incompatible_list = ", ".join(sorted(incompatible))
                raise MCPDiscoveryError(
                    "Las herramientas MCP no usan el contrato requerido bajo "
                    f"el objeto request: {incompatible_list}."
                )
        except MCPClientError:
            await client.__aexit__(None, None, None)
            raise
        except MCPError as exc:
            await client.__aexit__(None, None, None)
            raise MCPProtocolError(
                "El servidor rechazó el descubrimiento MCP."
            ) from exc
        except ValidationError as exc:
            await client.__aexit__(None, None, None)
            raise MCPProtocolError(
                "El servidor devolvió un descubrimiento MCP inválido."
            ) from exc
        except Exception as exc:
            await client.__aexit__(None, None, None)
            raise MCPConnectionError(
                "No se pudo abrir la conexión con el servidor MCP."
            ) from exc

        self._client = client

    async def close(
        self,
        exc_type: type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: Any = None,
    ) -> None:
        async with self._call_lock:
            client, self._client = self._client, None
            if client is None:
                return
            try:
                await client.__aexit__(exc_type, exc_value, traceback)
            except Exception as exc:
                raise MCPConnectionError(
                    "No se pudo cerrar correctamente la conexión MCP."
                ) from exc

    def _active_client(self) -> Client:
        if self._client is None:
            raise MCPClientStateError(
                "El cliente MCP debe abrirse antes de invocar herramientas."
            )
        return self._client

    async def _call(
        self,
        tool_name: str,
        request: Any,
        result_type: type[ResultT],
        *,
        write: bool = False,
    ) -> ResultT:
        client = self._active_client()
        arguments = {"request": request.model_dump(mode="json")}
        try:
            async with self._call_lock:
                result = await client.call_tool(
                    tool_name,
                    arguments,
                    read_timeout_seconds=self.timeout_seconds,
                )
        except MCPError as exc:
            raise MCPProtocolError(
                f"El servidor rechazó la invocación de {tool_name}."
            ) from exc
        except ValidationError as exc:
            raise MCPProtocolError(
                f"La respuesta de protocolo para {tool_name} es inválida."
            ) from exc
        except (TimeoutError, httpx.TimeoutException, OSError) as exc:
            if write:
                raise MCPWriteOutcomeUnknownError(
                    "Se perdió la respuesta de crear_cita después de enviar la "
                    "solicitud; no se pudo confirmar el resultado."
                ) from exc
            raise MCPConnectionError(
                f"Falló la conexión al invocar {tool_name}."
            ) from exc
        except Exception as exc:
            if write:
                raise MCPWriteOutcomeUnknownError(
                    "Se perdió la respuesta de crear_cita después de enviar la "
                    "solicitud; no se pudo confirmar el resultado."
                ) from exc
            raise MCPConnectionError(
                f"Falló el transporte MCP al invocar {tool_name}."
            ) from exc

        if result.is_error:
            raise MCPToolCallError(
                f"La herramienta MCP {tool_name} devolvió un error de ejecución."
            )
        if not isinstance(result.structured_content, dict):
            raise MCPContractError(
                f"La herramienta {tool_name} no devolvió contenido estructurado."
            )
        try:
            validated = result_type.model_validate(result.structured_content)
        except ValidationError as exc:
            raise MCPContractError(
                f"La respuesta de {tool_name} no cumple el contrato esperado."
            ) from exc
        if not validated.ok:
            if validated.error is None:  # protegido además por ToolResult
                raise MCPContractError(
                    f"La respuesta fallida de {tool_name} no contiene error."
                )
            raise MCPRemoteToolError(tool_name, validated.error)
        return validated

    async def search_faqs(self, request: SearchFAQsRequest) -> SearchFAQsResult:
        return await self._call("buscar_faqs", request, SearchFAQsResult)

    async def extract_date(self, request: ExtractDateRequest) -> ExtractDateResult:
        return await self._call("extraer_fecha", request, ExtractDateResult)

    async def get_weather(self, request: WeatherRequest) -> WeatherResult:
        return await self._call("consultar_clima", request, WeatherResult)

    async def assess_safety(self, request: SafetyRequest) -> SafetyResult:
        return await self._call("evaluar_seguridad", request, SafetyResult)

    async def create_appointment(
        self, request: CreateAppointmentRequest
    ) -> CreateAppointmentResult:
        return await self._call(
            "crear_cita", request, CreateAppointmentResult, write=True
        )

