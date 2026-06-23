import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "translate_playback_with_openai.py"
SPEC = importlib.util.spec_from_file_location("translate_playback_with_openai", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class TranslatePlaybackWithOpenAITest(unittest.TestCase):
    def test_reads_and_renders_playback_simulation_js(self):
        simulation = {
            "translationStatus": "needs_translation",
            "segments": [{"id": "sim_0001", "en": "Jesus is our mediator.", "zh": "AI 中文待生成"}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "playback.js"
            path.write_text(mod.render_js(simulation), encoding="utf-8")

            loaded = mod.read_simulation(path)

        self.assertEqual(loaded["segments"][0]["id"], "sim_0001")
        self.assertTrue(mod.render_js(loaded).startswith(mod.JS_PREFIX))

    def test_selects_only_untranslated_english_segments(self):
        simulation = {
            "segments": [
                {"id": "sim_0001", "en": "Translate me.", "zh": "AI 中文待生成", "translationStatus": "needs_translation"},
                {"id": "sim_0002", "en": "Already done.", "zh": "已翻译。", "translationStatus": "ready"},
                {"id": "sim_0003", "zh": "没有英文。"},
            ]
        }

        candidates = mod.translation_candidates(simulation, max_segments=None)

        self.assertEqual([item["id"] for item in candidates], ["sim_0001"])

    def test_applies_translations_without_secret_material(self):
        simulation = {
            "translationStatus": "needs_translation",
            "secrets": {"apiKeySecret": "projects/p/secrets/openai-api-key/versions/latest"},
            "segments": [
                {"id": "sim_0001", "en": "Jesus is our mediator.", "zh": "AI 中文待生成", "confidence": 72}
            ],
        }
        translations = [
            {
                "id": "sim_0001",
                "zh": "耶稣是我们的中保。",
                "draft": "耶稣是我们的中保。",
                "ref": "Jesus",
                "note": "术语 Mediator 译为中保。",
            }
        ]

        translated = mod.apply_translations(
            simulation=simulation,
            translations=translations,
            model="gpt-4.1-mini",
            api_key_secret="projects/p/secrets/openai-api-key/versions/latest",
        )

        self.assertEqual(translated["translationStatus"], "ready")
        self.assertEqual(translated["segments"][0]["zh"], "耶稣是我们的中保。")
        self.assertEqual(translated["segments"][0]["translationStatus"], "ready")
        self.assertFalse(translated["secrets"]["apiKeyMaterialIncluded"])
        self.assertFalse(translated["translationProvider"]["apiKeyMaterialIncluded"])
        rendered = mod.render_js(translated)
        self.assertNotIn("sk-", rendered)
        self.assertNotIn("openai-api-key", rendered)
        self.assertNotIn("projects/p/secrets", rendered)
        self.assertEqual(json.loads(rendered.split(" = ", 1)[1].rstrip(";\n"))["translationStatus"], "ready")

    def test_sanitizes_public_simulation_secret_references(self):
        simulation = {
            "secrets": {
                "apiKeySecret": "projects/p/secrets/openai-api-key/versions/latest",
                "apiKeyMaterialIncluded": False,
            },
            "translationProvider": {
                "provider": "openai",
                "apiKeySecret": "projects/p/secrets/openai-api-key/versions/latest",
            },
        }

        sanitized = mod.sanitize_public_simulation(simulation)
        rendered = mod.render_js(sanitized)

        self.assertNotIn("apiKeySecret", rendered)
        self.assertNotIn("openai-api-key", rendered)
        self.assertFalse(sanitized["secrets"]["apiKeyMaterialIncluded"])
        self.assertFalse(sanitized["translationProvider"]["secretResourceNamesIncluded"])

    def test_rejects_raw_api_key_as_secret_resource(self):
        with self.assertRaises(SystemExit):
            mod.validate_secret_resource_name("sk-this-should-not-be-accepted")

    def test_accepts_common_translation_field_aliases(self):
        normalized = mod.normalize_translation(
            {
                "segment_id": "sim_0001",
                "translation": "今天我们来看民数记十六章。",
                "note": "OpenAI output",
            }
        )

        self.assertEqual(normalized["id"], "sim_0001")
        self.assertEqual(normalized["zh"], "今天我们来看民数记十六章。")


if __name__ == "__main__":
    unittest.main()
