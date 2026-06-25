import importlib.util
import io
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

    def test_rejects_realtime_model_for_offline_translation(self):
        with self.assertRaises(SystemExit):
            mod.validate_offline_translation_model("gpt-realtime-translate")

    def test_rejects_non_required_model_for_offline_translation(self):
        with self.assertRaises(SystemExit):
            mod.validate_offline_translation_model("gpt-5.5")

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
            model="gpt-5.5-mini",
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

    def test_translation_report_omits_secret_resource_name(self):
        report = mod.build_report(
            original={"translationStatus": "needs_translation"},
            translated={"segments": [{"id": "sim_0001"}], "translationStatus": "ready"},
            translations=[{"id": "sim_0001"}],
            model="gpt-5.5-mini",
            api_key_secret="projects/p/secrets/openai-api-key/versions/latest",
            jsonl_path=Path("artifacts/openai-translation-output.jsonl"),
            out_path=Path("web/playback-simulation.generated.js"),
        )
        rendered = json.dumps(report, ensure_ascii=False)

        self.assertNotIn("apiKeySecret", rendered)
        self.assertNotIn("projects/p/secrets", rendered)
        self.assertNotIn("openai-api-key", rendered)
        self.assertFalse(report["apiKeyMaterialIncluded"])
        self.assertFalse(report["secretResourceNamesIncluded"])
        self.assertTrue(report["serverSideSecretConfigured"])

    def test_translation_report_counts_only_applied_segments(self):
        report = mod.build_report(
            original={"translationStatus": "needs_translation"},
            translated={
                "translationStatus": "ready",
                "segments": [
                    {"id": "sim_0001", "zh": "神爱世人。", "translationStatus": "ready"},
                    {"id": "sim_0002", "zh": "AI 中文待生成", "translationStatus": "needs_translation"},
                ],
            },
            translations=[{"id": "sim_0001"}, {"id": "missing"}],
            model="gpt-5.5-mini",
            api_key_secret="",
            jsonl_path=Path("artifacts/openai-translation-output.jsonl"),
            out_path=Path("web/playback-simulation.generated.js"),
        )

        self.assertEqual(report["translatedSegments"], 1)

    def test_applies_saved_translation_jsonl_without_api_key_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_js = root / "playback.js"
            out_js = root / "translated.js"
            out_dir = root / "model-output"
            translations_jsonl = root / "saved-output.jsonl"
            input_js.write_text(
                mod.render_js(
                    {
                        "translationStatus": "needs_translation",
                        "segments": [
                            {
                                "id": "sim_0001",
                                "startMs": 0,
                                "endMs": 1500,
                                "en": "God loved the world.",
                                "zh": "AI 中文待生成：God loved the world.",
                                "translationStatus": "needs_translation",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            translations_jsonl.write_text(
                json.dumps({"segments": [{"id": "sim_0001", "zh": "神爱世人。"}]}, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            argv = [
                "translate_playback_with_openai.py",
                "--input",
                str(input_js),
                "--out",
                str(out_js),
                "--out-dir",
                str(out_dir),
                "--translations-jsonl",
                str(translations_jsonl),
                "--model",
                "gpt-5.5-mini",
            ]
            original_argv = mod.sys.argv
            original_stdout = mod.sys.stdout
            stdout = io.StringIO()
            try:
                mod.sys.argv = argv
                mod.sys.stdout = stdout
                exit_code = mod.main()
            finally:
                mod.sys.argv = original_argv
                mod.sys.stdout = original_stdout

            translated = mod.read_simulation(out_js)
            report = json.loads((out_dir / "openai-translation-report.json").read_text(encoding="utf-8"))
            rendered = out_js.read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertEqual(translated["translationStatus"], "ready")
        self.assertEqual(translated["segments"][0]["zh"], "神爱世人。")
        self.assertEqual(translated["translationProvider"]["model"], "gpt-5.5-mini")
        self.assertEqual(report["translatedSegments"], 1)
        self.assertEqual(report["modelOutputJsonl"], "saved-output.jsonl")
        self.assertNotIn("apiKeySecret", rendered)
        self.assertNotIn("projects/", rendered)
        self.assertIn('"status": "ok"', stdout.getvalue())

    def test_failure_report_omits_secret_resource_name(self):
        report = mod.build_failure_report(
            original={"translationStatus": "needs_translation", "segments": [{"id": "sim_0001"}]},
            model="gpt-5.5-mini",
            api_key_secret="projects/p/secrets/openai-api-key/versions/latest",
            status_code=404,
            message="The model gpt-5.5-mini does not exist.",
            out_path=Path("web/playback-simulation.generated.js"),
        )
        rendered = json.dumps(report, ensure_ascii=False)

        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["failureStage"], "openai_translation")
        self.assertEqual(report["httpStatus"], 404)
        self.assertEqual(report["failureKind"], "model_unavailable_or_not_found")
        self.assertNotIn("apiKeySecret", rendered)
        self.assertNotIn("projects/p/secrets", rendered)
        self.assertNotIn("openai-api-key", rendered)
        self.assertFalse(report["apiKeyMaterialIncluded"])
        self.assertFalse(report["secretResourceNamesIncluded"])

    def test_failure_kind_classification(self):
        self.assertEqual(
            mod.classify_model_access_failure(400, "The requested model does not exist."),
            "model_unavailable_or_not_found",
        )
        self.assertEqual(mod.classify_model_access_failure(403, "permission denied"), "auth_or_permission_denied")
        self.assertEqual(mod.classify_model_access_failure(429, "rate limited"), "rate_limited")
        self.assertEqual(mod.classify_model_access_failure(500, "server error"), "provider_server_error")

    def test_sanitizes_failure_error_message(self):
        message = (
            "bad sk-secret123 from projects/p/secrets/openai-api-key/versions/latest"
        )

        clean = mod.sanitize_error_message(message)

        self.assertIn("sk-REDACTED", clean)
        self.assertIn("projects/REDACTED/secrets/REDACTED/versions/REDACTED", clean)
        self.assertNotIn("sk-secret123", clean)
        self.assertNotIn("openai-api-key", clean)

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

    def test_translate_batch_uses_responses_api_and_typed_output(self):
        calls = []

        class FakeResponse:
            status_code = 200
            text = ""

            def json(self):
                return {
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": (
                                        "{\"segments\":[{\"id\":\"sim_0001\","
                                        "\"zh\":\"耶稣是我们的中保。\"}]}"
                                    ),
                                }
                            ],
                        }
                    ]
                }

        original_post = mod.requests.post
        try:
            def fake_post(url, headers, json, timeout):
                calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
                return FakeResponse()

            mod.requests.post = fake_post
            translations = mod.translate_batch(
                [{"id": "sim_0001", "en": "Jesus is our mediator.", "ref": "", "note": ""}],
                api_key="sk-test",
                model="gpt-5.5-mini",
            )
        finally:
            mod.requests.post = original_post

        self.assertEqual(translations[0]["zh"], "耶稣是我们的中保。")
        self.assertEqual(calls[0]["url"], mod.OPENAI_RESPONSES_URL)
        self.assertEqual(calls[0]["json"]["model"], "gpt-5.5-mini")
        self.assertIn("input", calls[0]["json"])
        self.assertNotIn("messages", calls[0]["json"])
        self.assertEqual(calls[0]["json"]["text"]["format"]["type"], "json_object")


if __name__ == "__main__":
    unittest.main()
