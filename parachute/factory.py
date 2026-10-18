from __future__ import annotations

import os
from pathlib import Path

from knowledge_base import KnowledgeBase

from .agents import (
    DateAgent,
    FAQAgent,
    SafetyAgent,
    SchedulingAgent,
    TriageAgent,
    WeatherAgent,
)
from .calendar import AppointmentRepository
from .weather import WeatherService


def build_specialists(
    *,
    database_path: str | Path | None = None,
    enable_rag: bool = True,
    weather_service: WeatherService | None = None,
) -> dict[str, object]:
    """Única composición de integraciones compartida por las arquitecturas."""
    kb = KnowledgeBase.from_env() if enable_rag else None
    repository = AppointmentRepository(
        database_path or os.getenv("APPOINTMENTS_DB", "appointments.sqlite3")
    )
    return {
        "triage": TriageAgent(),
        "date": DateAgent(),
        "weather": WeatherAgent(weather_service or WeatherService()),
        "safety": SafetyAgent(),
        "scheduling": SchedulingAgent(repository),
        "faq": FAQAgent(kb),
    }
