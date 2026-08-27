import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app import NO_ANSWER, ask, build_system_prompt, load_faq


class AppTests(unittest.TestCase):
    def test_load_faq_reads_utf8_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "faq.txt"
            path.write_text("¿Cuándo? Mañana.", encoding="utf-8")
            self.assertEqual(load_faq(path), "¿Cuándo? Mañana.")

    def test_load_faq_rejects_empty_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "faq.txt"
            path.write_text("   ", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                load_faq(path)

    def test_prompt_contains_context_and_fallback(self):
        prompt = build_system_prompt("Dato de prueba")
        self.assertIn("Dato de prueba", prompt)
        self.assertIn(NO_ANSWER, prompt)
        self.assertIn("solamente", prompt)

    def test_ask_returns_model_content(self):
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Respuesta"))]
        )
        completions = SimpleNamespace(create=lambda **_: response)
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        self.assertEqual(ask(client, "modelo", "contexto", "pregunta"), "Respuesta")


if __name__ == "__main__":
    unittest.main()
