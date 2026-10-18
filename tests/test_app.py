import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app import NO_ANSWER, SEARCH_TOOL, answer_question
from load_faqs import parse_corpus


def completion(message):
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeCompletions:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return next(self.responses)


class FakeKnowledgeBase:
    def __init__(self):
        self.calls = []

    def search(self, query, limit=5):
        self.calls.append((query, limit))
        return [
            {
                "id": "FAQ-001",
                "pregunta": "¿Dónde es el evento?",
                "respuesta": "En Guatemala.",
                "similitud": 0.91,
            }
        ]


class EmptyKnowledgeBase:
    def search(self, query, limit=5):
        return []


class CorpusTests(unittest.TestCase):
    def test_parse_corpus_extracts_structured_record(self):
        content = """ID: FAQ-900
CATEGORÍA: Prueba
PREGUNTA: ¿Pregunta de prueba?
RESPUESTA: Respuesta de prueba.
METADATA: {"empresa": "Parachute S.A."}
------------------------------------------------------------
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "corpus.txt"
            path.write_text(content, encoding="utf-8")
            records = parse_corpus(path)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].source_id, "FAQ-900")
        self.assertEqual(records[0].metadata["empresa"], "Parachute S.A.")

    def test_parse_corpus_rejects_an_empty_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty.txt"
            path.write_text("", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                parse_corpus(path)

    def test_parse_corpus_rejects_duplicate_ids(self):
        entry = """ID: FAQ-900
CATEGORÍA: Prueba
PREGUNTA: ¿Pregunta de prueba?
RESPUESTA: Respuesta de prueba.
METADATA: {"empresa": "Parachute S.A."}
------------------------------------------------------------
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicates.txt"
            path.write_text(entry + entry, encoding="utf-8")
            with self.assertRaises(RuntimeError):
                parse_corpus(path)

    def test_real_corpus_contains_120_unique_records(self):
        path = Path(__file__).resolve().parents[1] / "Corpus_FAQs_Parachute_SA_2026.txt"
        records = parse_corpus(path)
        self.assertEqual(len(records), 120)
        self.assertEqual(len({record.source_id for record in records}), 120)


class AgentTests(unittest.TestCase):
    def test_tool_schema_requires_a_query(self):
        function = SEARCH_TOOL["function"]
        self.assertEqual(function["name"], "buscar_faqs")
        self.assertIn("consulta", function["parameters"]["required"])

    def test_agent_executes_search_tool_before_answering(self):
        tool_call = SimpleNamespace(
            id="call-1",
            function=SimpleNamespace(
                name="buscar_faqs",
                arguments=json.dumps({"consulta": "ubicación", "cantidad": 3}),
            ),
        )
        first = SimpleNamespace(content=None, tool_calls=[tool_call])
        second = SimpleNamespace(
            content="El evento es en Guatemala. (FAQ-001)", tool_calls=None
        )
        completions = FakeCompletions([completion(first), completion(second)])
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        kb = FakeKnowledgeBase()

        answer = answer_question(client, kb, "modelo", "¿Dónde es?")

        self.assertEqual(answer, "El evento es en Guatemala. (FAQ-001)")
        self.assertEqual(kb.calls, [("ubicación", 3)])
        self.assertEqual(completions.calls[0]["tool_choice"], "required")
        tool_messages = [
            message
            for message in completions.calls[1]["messages"]
            if message["role"] == "tool"
        ]
        self.assertEqual(len(tool_messages), 1)
        self.assertIn("FAQ-001", tool_messages[0]["content"])

    def test_agent_refuses_if_model_does_not_use_tool(self):
        message = SimpleNamespace(content="Respuesta inventada", tool_calls=None)
        completions = FakeCompletions([completion(message)])
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

        answer = answer_question(client, FakeKnowledgeBase(), "modelo", "Pregunta")

        self.assertEqual(answer, NO_ANSWER)

    def test_agent_refuses_immediately_when_search_has_no_results(self):
        tool_call = SimpleNamespace(
            id="call-empty",
            function=SimpleNamespace(
                name="buscar_faqs",
                arguments=json.dumps({"consulta": "tema inexistente"}),
            ),
        )
        message = SimpleNamespace(content=None, tool_calls=[tool_call])
        completions = FakeCompletions([completion(message)])
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

        answer = answer_question(
            client, EmptyKnowledgeBase(), "modelo", "Pregunta sin respuesta"
        )

        self.assertEqual(answer, NO_ANSWER)
        self.assertEqual(len(completions.calls), 1)


if __name__ == "__main__":
    unittest.main()
