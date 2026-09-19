from __future__ import annotations

from .agents import (
    DateAgent,
    FAQAgent,
    Intent,
    RequestContext,
    SafetyAgent,
    SchedulingAgent,
    TriageAgent,
    WeatherAgent,
    execute_appointment_pipeline,
)


class CentralSupervisor:
    """Un supervisor posee la ruta y coordina directamente a cada especialista."""

    def __init__(self, specialists: dict[str, object]) -> None:
        self.triage = specialists["triage"]
        self.date_agent = specialists["date"]
        self.weather = specialists["weather"]
        self.safety = specialists["safety"]
        self.scheduling = specialists["scheduling"]
        self.faq = specialists["faq"]

    def run(self, context: RequestContext) -> str:
        intent = self.triage.classify(context.message)  # type: ignore[union-attr]
        if intent is Intent.FAQ:
            return self.faq.run(context.message).message  # type: ignore[union-attr]
        result = execute_appointment_pipeline(
            context,
            self.date_agent,  # type: ignore[arg-type]
            self.weather,  # type: ignore[arg-type]
            self.safety,  # type: ignore[arg-type]
            self.scheduling,  # type: ignore[arg-type]
        )
        return result.message
