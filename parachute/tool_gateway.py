from __future__ import annotations

from typing import Protocol

from .tool_contracts import (
    CreateAppointmentRequest,
    CreateAppointmentResult,
    ExtractDateRequest,
    ExtractDateResult,
    SafetyRequest,
    SafetyResult,
    SearchFAQsRequest,
    SearchFAQsResult,
    WeatherRequest,
    WeatherResult,
)


class ParachuteToolGateway(Protocol):
    """Frontera asíncrona para herramientas locales o remotas.

    La implementación MCP se añadirá en una fase posterior. Este protocolo no
    contiene lógica de negocio y permite mantener sin cambios la modalidad
    local síncrona actual.
    """

    async def search_faqs(self, request: SearchFAQsRequest) -> SearchFAQsResult:
        ...

    async def extract_date(self, request: ExtractDateRequest) -> ExtractDateResult:
        ...

    async def get_weather(self, request: WeatherRequest) -> WeatherResult:
        ...

    async def assess_safety(self, request: SafetyRequest) -> SafetyResult:
        ...

    async def create_appointment(
        self, request: CreateAppointmentRequest
    ) -> CreateAppointmentResult:
        ...
