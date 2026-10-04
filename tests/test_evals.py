import json
import unittest

from evals.provider import FINAL_MARKER, call_api


def run_case(**values):
    response = call_api(values["question"], {}, {"vars": values})
    calls, answer = response["output"].split(f"\n{FINAL_MARKER}\n", 1)
    names = [json.loads(line)["name"] for line in calls.splitlines()]
    return response, names, answer


class PromptfooProviderTests(unittest.TestCase):
    def test_faq_uses_only_faq_route(self):
        response, names, answer = run_case(
            question="¿Cuál es el peso máximo permitido?",
            faq_id="FAQ-021",
            faq_answer="El peso máximo es 100 kg.",
        )
        self.assertEqual(names, ["triage", "faqs"])
        self.assertIn("100 kg", answer)
        self.assertFalse(response["cached"])

    def test_appointment_uses_complete_route_without_persistence(self):
        _, names, answer = run_case(
            question="Quiero agendar cita el 2026-10-10",
            customer="Ana",
            rain=0,
            clouds=15,
            wind=12,
            gust=20,
        )
        self.assertEqual(
            names, ["triage", "fecha", "clima", "seguridad", "agenda"]
        )
        self.assertIn("Cita #1 creada", answer)

    def test_unsafe_appointment_is_not_created(self):
        _, names, answer = run_case(
            question="Reserva una cita el 2026-10-11",
            customer="Luis",
            rain=2.5,
            clouds=40,
            wind=14,
            gust=24,
        )
        self.assertEqual(
            names, ["triage", "fecha", "clima", "seguridad", "agenda"]
        )
        self.assertIn("No se creó la cita", answer)


if __name__ == "__main__":
    unittest.main()
