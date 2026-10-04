from __future__ import annotations

from .agents import (
    Intent,
    RequestContext,
    execute_appointment_pipeline,
)


class InformationManager:
    def __init__(self, faq_agent: object) -> None:
        self.faq_agent = faq_agent

    def run(self, context: RequestContext) -> str:
        return self.faq_agent.run(context.message).message  # type: ignore[union-attr]


class OperationsManager:
    """Manager intermedio que coordina el equipo de fecha, clima y agenda."""

    def __init__(self, specialists: dict[str, object]) -> None:
        self.date_agent = specialists["date"]
        self.weather = specialists["weather"]
        self.safety = specialists["safety"]
        self.scheduling = specialists["scheduling"]

    def run(self, context: RequestContext) -> str:
        return execute_appointment_pipeline(
            context,
            self.date_agent,  # type: ignore[arg-type]
            self.weather,  # type: ignore[arg-type]
            self.safety,  # type: ignore[arg-type]
            self.scheduling,  # type: ignore[arg-type]
        ).message


class ExecutiveManager:
    """Manager raíz que solo delega a managers de dominio."""

    def __init__(self, specialists: dict[str, object]) -> None:
        self.triage = specialists["triage"]
        self.information = InformationManager(specialists["faq"])
        self.operations = OperationsManager(specialists)

    def run(self, context: RequestContext) -> str:
        intent = self.triage.classify(context.message)  # type: ignore[union-attr]
        manager = self.operations if intent is Intent.APPOINTMENT else self.information
        return manager.run(context)
