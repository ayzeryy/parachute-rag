from __future__ import annotations

from .agents import AgentResult, Intent, RequestContext


class PeerNetwork:
    """Red sin supervisor: cada agente elige explícitamente el siguiente handoff."""

    def __init__(self, specialists: dict[str, object]) -> None:
        self.specialists = specialists

    def run(self, context: RequestContext) -> str:
        current = "triage"
        requested = None
        weather = None
        assessment = None

        try:
            while current:
                if current == "triage":
                    intent = self.specialists["triage"].classify(context.message)  # type: ignore[union-attr]
                    current = "fecha" if intent is Intent.APPOINTMENT else "faqs"
                elif current == "faqs":
                    return self.specialists["faq"].run(context.message).message  # type: ignore[union-attr]
                elif current == "fecha":
                    requested = self.specialists["date"].extract(context.message)  # type: ignore[union-attr]
                    current = "clima"
                elif current == "clima":
                    weather = self.specialists["weather"].run(requested)  # type: ignore[union-attr]
                    current = "seguridad"
                elif current == "seguridad":
                    assessment = self.specialists["safety"].run(weather)  # type: ignore[union-attr]
                    current = "agenda"
                elif current == "agenda":
                    return self.specialists["scheduling"].run(  # type: ignore[union-attr]
                        context, requested, assessment
                    ).message
                else:
                    return AgentResult("Handoff desconocido en la red de agentes.").message
        except (ValueError, RuntimeError) as exc:
            return str(exc)
        return "La red terminó sin producir una respuesta."
