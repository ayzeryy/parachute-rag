from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Any

from .calendar import Appointment, AppointmentRepository
from .models import SafetyLevel, WeatherAssessment, WeatherSnapshot
from .safety import assess_weather
from .weather import ForecastDateError, WeatherService


DATE_PATTERN = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


class Intent(str, Enum):
    FAQ = "faq"
    APPOINTMENT = "appointment"


@dataclass(frozen=True)
class RequestContext:
    message: str
    customer: str = "Cliente"
    experienced_tandem: bool = False


@dataclass(frozen=True)
class AgentResult:
    message: str
    requested_date: date | None = None
    weather: WeatherSnapshot | None = None
    assessment: WeatherAssessment | None = None
    appointment: Appointment | None = None
    next_agent: str | None = None


class TriageAgent:
    name = "triage"

    def classify(self, message: str) -> Intent:
        lowered = message.casefold()
        booking_words = ("cita", "reserv", "calendar", "agend", "saltar el")
        return (
            Intent.APPOINTMENT
            if any(word in lowered for word in booking_words)
            else Intent.FAQ
        )


class DateAgent:
    name = "fecha"

    def extract(self, message: str) -> date:
        match = DATE_PATTERN.search(message)
        if not match:
            raise ValueError("Indica la fecha en formato AAAA-MM-DD.")
        try:
            return date.fromisoformat(match.group(1))
        except ValueError as exc:
            raise ValueError("La fecha no es válida; usa AAAA-MM-DD.") from exc


class WeatherAgent:
    name = "clima"

    def __init__(self, service: WeatherService) -> None:
        self.service = service

    def run(self, requested: date) -> WeatherSnapshot:
        return self.service.forecast(requested)


class SafetyAgent:
    name = "seguridad"

    def run(self, weather: WeatherSnapshot) -> WeatherAssessment:
        return assess_weather(weather)


class SchedulingAgent:
    name = "agenda"

    def __init__(self, repository: AppointmentRepository) -> None:
        self.repository = repository

    def run(
        self,
        context: RequestContext,
        requested: date,
        assessment: WeatherAssessment,
    ) -> AgentResult:
        if assessment.level is SafetyLevel.PROHIBITED:
            return AgentResult(
                f"No se creó la cita. {assessment.summary()}",
                requested,
                assessment=assessment,
            )
        if assessment.requires_experienced_tandem and not context.experienced_tandem:
            return AgentResult(
                "No se creó la cita: la condición es marginal y requiere un "
                f"tándem experimentado. {assessment.summary()}",
                requested,
                assessment=assessment,
            )
        appointment = self.repository.create(
            context.customer, requested, assessment
        )
        return AgentResult(
            f"Cita #{appointment.id} creada para {requested.isoformat()}. "
            f"{assessment.summary()}",
            requested,
            assessment=assessment,
            appointment=appointment,
        )


class FAQAgent:
    name = "faqs"

    def __init__(self, knowledge_base: Any | None = None) -> None:
        self.knowledge_base = knowledge_base

    def run(self, question: str) -> AgentResult:
        if self.knowledge_base is None:
            return AgentResult(
                "El agente FAQ requiere la base RAG configurada. Ejecuta primero "
                "load_faqs.py y configura PostgreSQL."
            )
        results = self.knowledge_base.search(question, limit=5)
        if not results:
            return AgentResult(
                "No puedo responder esa pregunta con la información disponible."
            )
        answer = "\n".join(
            f"- {item['respuesta']} ({item['id']})" for item in results[:3]
        )
        return AgentResult(answer)


def execute_appointment_pipeline(
    context: RequestContext,
    date_agent: DateAgent,
    weather_agent: WeatherAgent,
    safety_agent: SafetyAgent,
    scheduling_agent: SchedulingAgent,
) -> AgentResult:
    try:
        requested = date_agent.extract(context.message)
        weather = weather_agent.run(requested)
        assessment = safety_agent.run(weather)
        result = scheduling_agent.run(context, requested, assessment)
        return AgentResult(
            result.message,
            requested,
            weather,
            assessment,
            result.appointment,
        )
    except (ValueError, ForecastDateError, RuntimeError) as exc:
        return AgentResult(str(exc))
