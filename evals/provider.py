"""Proveedor reproducible de Promptfoo para la arquitectura centralizada.

Ejecuta el supervisor real y reemplaza únicamente los bordes no deterministas
(Open-Meteo, pgvector y SQLite) por fixtures definidos en cada caso de prueba.
La salida incluye llamadas OpenAI-compatible para que `tool-call-f1` pueda
calificar la selección de herramientas y separa la respuesta final con una
marca que las demás aserciones transforman antes de evaluarla.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from parachute.agents import (  # noqa: E402
    DateAgent,
    FAQAgent,
    RequestContext,
    SafetyAgent,
    SchedulingAgent,
    TriageAgent,
    WeatherAgent,
)
from parachute.calendar import Appointment  # noqa: E402
from parachute.centralized import CentralSupervisor  # noqa: E402
from parachute.models import SafetyLevel, WeatherAssessment, WeatherSnapshot  # noqa: E402


FINAL_MARKER = "FINAL_ANSWER"


class Trace:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def add(self, name: str, arguments: dict[str, Any]) -> None:
        number = len(self.calls) + 1
        self.calls.append(
            {
                "type": "function_call",
                "id": f"fc_{number}",
                "call_id": f"call_{number}",
                "name": name,
                "arguments": json.dumps(arguments, ensure_ascii=False),
            }
        )


class FixtureKnowledgeBase:
    def __init__(self, trace: Trace, result: dict[str, str] | None) -> None:
        self.trace = trace
        self.result = result

    def search(self, query: str, limit: int = 5) -> list[dict[str, str]]:
        self.trace.add("faqs", {"consulta": query, "cantidad": limit})
        return [self.result] if self.result else []


class FixtureWeatherService:
    def __init__(self, trace: Trace, values: dict[str, Any]) -> None:
        self.trace = trace
        self.values = values

    def forecast(self, requested: date) -> WeatherSnapshot:
        self.trace.add("clima", {"fecha": requested.isoformat()})
        return WeatherSnapshot(
            date=requested,
            temperature_2m=float(self.values.get("temperature", 26)),
            precipitation=float(self.values.get("rain", 0)),
            cloud_cover=float(self.values.get("clouds", 15)),
            wind_speed_10m=float(self.values.get("wind", 12)),
            wind_gust_10m=float(self.values.get("gust", 20)),
        )


class InMemoryAppointmentRepository:
    """Repositorio sin efectos persistentes para una evaluación aislada."""

    def create(
        self, customer: str, requested: date, assessment: WeatherAssessment
    ) -> Appointment:
        if not assessment.can_schedule:
            raise ValueError("Una condición no segura nunca se puede calendarizar.")
        return Appointment(1, customer, requested, assessment.level)


class TracedTriageAgent(TriageAgent):
    def __init__(self, trace: Trace) -> None:
        self.trace = trace

    def classify(self, message: str):
        result = super().classify(message)
        self.trace.add("triage", {"mensaje": message, "intencion": result.value})
        return result


class TracedDateAgent(DateAgent):
    def __init__(self, trace: Trace) -> None:
        self.trace = trace

    def extract(self, message: str) -> date:
        requested = super().extract(message)
        self.trace.add("fecha", {"fecha": requested.isoformat()})
        return requested


class TracedSafetyAgent(SafetyAgent):
    def __init__(self, trace: Trace) -> None:
        self.trace = trace

    def run(self, weather: WeatherSnapshot) -> WeatherAssessment:
        assessment = super().run(weather)
        self.trace.add(
            "seguridad",
            {
                "fecha": weather.date.isoformat(),
                "resultado": assessment.level.value,
            },
        )
        return assessment


class TracedSchedulingAgent(SchedulingAgent):
    def __init__(self, trace: Trace, repository: InMemoryAppointmentRepository) -> None:
        super().__init__(repository)  # type: ignore[arg-type]
        self.trace = trace

    def run(self, context, requested, assessment):
        # La decisión de agenda también es una herramienta, aunque el repositorio
        # solo se invoca cuando la condición permite crear la cita.
        self.trace.add(
            "agenda",
            {
                "cliente": context.customer,
                "fecha": requested.isoformat(),
                "accion": "evaluar",
            },
        )
        return super().run(context, requested, assessment)


def _build_system(values: dict[str, Any], trace: Trace) -> CentralSupervisor:
    faq_result = None
    if values.get("faq_answer"):
        faq_result = {
            "id": str(values.get("faq_id", "FAQ-EVAL")),
            "respuesta": str(values["faq_answer"]),
        }

    repository = InMemoryAppointmentRepository()
    specialists = {
        "triage": TracedTriageAgent(trace),
        "date": TracedDateAgent(trace),
        "weather": WeatherAgent(FixtureWeatherService(trace, values)),
        "safety": TracedSafetyAgent(trace),
        "scheduling": TracedSchedulingAgent(trace, repository),
        "faq": FAQAgent(FixtureKnowledgeBase(trace, faq_result)),
    }
    return CentralSupervisor(specialists)


def call_api(prompt: str, options: dict[str, Any], context: dict[str, Any]):
    """Contrato del proveedor Python de Promptfoo."""
    started = time.perf_counter()
    values = dict(context.get("vars") or {})
    trace = Trace()
    system = _build_system(values, trace)
    answer = system.run(
        RequestContext(
            message=prompt,
            customer=str(values.get("customer", "Cliente")),
            experienced_tandem=bool(values.get("experienced_tandem", False)),
        )
    )
    elapsed_ms = max(1, round((time.perf_counter() - started) * 1000))
    serialized_calls = "\n".join(
        json.dumps(call, ensure_ascii=False) for call in trace.calls
    )
    output = f"{serialized_calls}\n{FINAL_MARKER}\n{answer}"
    return {
        "output": output,
        "latencyMs": elapsed_ms,
        "cached": False,
        "metadata": {"architecture": "centralized", "toolCalls": trace.calls},
    }

