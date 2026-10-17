from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator


RUNTIME_MODE_EXTENSION_URI = "urn:parachute:runtime-mode:v1"


class A2ARoute(str, Enum):
    FAQ = "faq"
    APPOINTMENT = "reserva"
    UNKNOWN = "desconocida"


class A2AResponseCategory(str, Enum):
    BUSINESS_RESULT = "business_result"
    INVALID_INPUT = "invalid_input"
    MCP_ERROR = "mcp_error"
    INFRASTRUCTURE_ERROR = "infrastructure_error"
    WRITE_OUTCOME_UNKNOWN = "write_outcome_unknown"


class A2ARequestData(BaseModel):
    """Parte JSON de entrada transportada junto con el texto A2A."""

    model_config = ConfigDict(extra="forbid", strict=True)

    cliente: str | None = Field(default=None, max_length=200)
    experienced_tandem: StrictBool = False

    @field_validator("cliente")
    @classmethod
    def validate_customer(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value or value != value.strip():
            raise ValueError(
                "cliente debe ser texto no vacío y no incluir espacios externos"
            )
        return value


class A2AResponseData(BaseModel):
    """Clasificación legible por clientes sin inferir éxito desde el texto."""

    model_config = ConfigDict(extra="forbid")

    category: A2AResponseCategory
    route: A2ARoute
    correlation_id: str


@dataclass(frozen=True)
class ParsedA2ARequest:
    text: str
    data: A2ARequestData
    route: A2ARoute
    message_id: str
    context_id: str


class A2AInputError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        route: A2ARoute = A2ARoute.UNKNOWN,
    ) -> None:
        super().__init__(message)
        self.route = route

