from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .calendar import Appointment
from .models import (
    SafetyLevel,
    WeatherAssessment,
    WeatherSnapshot,
)


class ContractModel(BaseModel):
    """Base estricta para contratos que cruzarán la frontera MCP."""

    model_config = ConfigDict(extra="forbid")


class CorrelatedRequest(ContractModel):
    correlation_id: str | None = Field(
        default=None,
        description="Identificador opaco para correlacionar logs entre A2A y MCP.",
        max_length=128,
    )


class ToolErrorKind(str, Enum):
    DOMAIN = "domain"
    INFRASTRUCTURE = "infrastructure"


class ToolError(ContractModel):
    kind: ToolErrorKind
    code: str
    message: str
    retryable: bool = False


PayloadT = TypeVar("PayloadT", bound=BaseModel)


class ToolResult(ContractModel, Generic[PayloadT]):
    """Sobre común que distingue éxito técnico de fallo de herramienta."""

    ok: bool
    data: PayloadT | None = None
    error: ToolError | None = None

    @model_validator(mode="after")
    def validate_envelope(self) -> "ToolResult[PayloadT]":
        if self.ok and (self.data is None or self.error is not None):
            raise ValueError("Un resultado exitoso requiere data y no admite error")
        if not self.ok and (self.error is None or self.data is not None):
            raise ValueError("Un resultado fallido requiere error y no admite data")
        return self


class SearchFAQsRequest(CorrelatedRequest):
    query: str = Field(min_length=1, max_length=2_000)
    limit: int = Field(default=5, ge=1, le=8)


class FAQEvidence(ContractModel):
    source_id: str
    category: str
    question: str
    answer: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    similarity: float = Field(ge=-1.0, le=1.0)

    @classmethod
    def from_search_result(cls, item: dict[str, Any]) -> "FAQEvidence":
        return cls(
            source_id=str(item["id"]),
            category=str(item.get("categoria", "")),
            question=str(item.get("pregunta", "")),
            answer=str(item["respuesta"]),
            metadata=dict(item.get("metadata") or {}),
            similarity=float(item.get("similitud", 0.0)),
        )


class FAQSearchData(ContractModel):
    query: str
    evidence: list[FAQEvidence]


class SearchFAQsResult(ToolResult[FAQSearchData]):
    pass


class ExtractDateRequest(CorrelatedRequest):
    text: str = Field(min_length=1, max_length=2_000)


class ExtractedDateData(ContractModel):
    requested_date: date


class ExtractDateResult(ToolResult[ExtractedDateData]):
    pass


class WeatherRequest(CorrelatedRequest):
    requested_date: date


class WeatherData(ContractModel):
    """Pronóstico con unidades explícitas para evitar conversiones ambiguas."""

    requested_date: date
    temperature_c: float
    precipitation_mm: float = Field(ge=0)
    cloud_cover_percent: float = Field(ge=0, le=100)
    wind_speed_kmh: float = Field(ge=0)
    wind_gust_kmh: float = Field(ge=0)

    @classmethod
    def from_domain(cls, snapshot: WeatherSnapshot) -> "WeatherData":
        return cls(
            requested_date=snapshot.date,
            temperature_c=snapshot.temperature_2m,
            precipitation_mm=snapshot.precipitation,
            cloud_cover_percent=snapshot.cloud_cover,
            wind_speed_kmh=snapshot.wind_speed_10m,
            wind_gust_kmh=snapshot.wind_gust_10m,
        )

    def to_domain(self) -> WeatherSnapshot:
        return WeatherSnapshot(
            date=self.requested_date,
            temperature_2m=self.temperature_c,
            precipitation=self.precipitation_mm,
            cloud_cover=self.cloud_cover_percent,
            wind_speed_10m=self.wind_speed_kmh,
            wind_gust_10m=self.wind_gust_kmh,
        )


class WeatherResult(ToolResult[WeatherData]):
    pass


class SafetyRequest(CorrelatedRequest):
    weather: WeatherData


class SafetyData(ContractModel):
    level: SafetyLevel
    reasons: list[str]
    can_schedule: bool
    requires_experienced_tandem: bool
    weather: WeatherData

    @classmethod
    def from_domain(cls, assessment: WeatherAssessment) -> "SafetyData":
        return cls(
            level=assessment.level,
            reasons=list(assessment.reasons),
            can_schedule=assessment.can_schedule,
            requires_experienced_tandem=(
                assessment.requires_experienced_tandem
            ),
            weather=WeatherData.from_domain(assessment.snapshot),
        )


class SafetyResult(ToolResult[SafetyData]):
    pass


class CreateAppointmentRequest(CorrelatedRequest):
    """Datos declarados por el cliente; nunca incluye una aprobación externa."""

    customer: str = Field(min_length=1, max_length=200)
    requested_date: date
    experienced_tandem: bool = False


class AppointmentOutcome(str, Enum):
    CREATED = "created"
    REJECTED = "rejected"
    DUPLICATE = "duplicate"


class AppointmentData(ContractModel):
    appointment_id: int = Field(gt=0)
    customer: str
    requested_date: date
    condition: SafetyLevel

    @classmethod
    def from_domain(cls, appointment: Appointment) -> "AppointmentData":
        return cls(
            appointment_id=appointment.id,
            customer=appointment.customer,
            requested_date=appointment.date,
            condition=appointment.condition,
        )


class AppointmentDecisionData(ContractModel):
    outcome: AppointmentOutcome
    message: str
    assessment: SafetyData
    appointment: AppointmentData | None = None

    @model_validator(mode="after")
    def validate_appointment_presence(self) -> "AppointmentDecisionData":
        if self.outcome is AppointmentOutcome.CREATED and self.appointment is None:
            raise ValueError("Una cita creada requiere datos de la cita")
        if self.outcome is not AppointmentOutcome.CREATED and self.appointment is not None:
            raise ValueError("Una cita no creada no debe incluir una cita persistida")
        return self


class CreateAppointmentResult(ToolResult[AppointmentDecisionData]):
    pass
