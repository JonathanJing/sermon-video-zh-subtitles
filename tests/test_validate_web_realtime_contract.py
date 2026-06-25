import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "validate_web_realtime_contract.py"
SPEC = importlib.util.spec_from_file_location("validate_web_realtime_contract", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class ValidateWebRealtimeContractTest(unittest.TestCase):
    def test_current_app_contract_passes(self):
        report = mod.validate_web_realtime_contract(mod.DEFAULT_APP_JS)

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["failedChecks"], [])
        self.assertEqual(report["models"]["realtimeDraft"], "gpt-realtime-translate")
        self.assertEqual(report["normalizationProbe"]["status"], "ok")
        runtime_check = next(check for check in report["checks"] if check["name"] == "openai_event_normalization_runtime")
        self.assertEqual(runtime_check["state"], "pass")
        fallback_check = next(check for check in report["checks"] if check["name"] == "no_browser_speech_success_fallback")
        self.assertEqual(fallback_check["state"], "pass")
        self.assertEqual(fallback_check["forbiddenPresent"], [])
        runtime_results = {item["name"]: item["actual"] for item in report["normalizationProbe"]["results"]}
        self.assertEqual(runtime_results["output_delta"]["type"], "caption_delta")
        self.assertEqual(runtime_results["output_delta"]["zh"], "神爱世人")
        self.assertEqual(runtime_results["nested_input_delta"]["type"], "input_transcript_delta")
        self.assertEqual(runtime_results["nested_input_delta"]["en"], "God loved the world")
        session_probe = report["normalizationProbe"]["sessionProbe"]
        self.assertEqual(session_probe["status"], "ok")
        self.assertTrue(session_probe["checks"]["createUsesRealtimeTranslate"])
        self.assertTrue(session_probe["checks"]["createTargetsChinese"])
        self.assertTrue(session_probe["checks"]["createUsesIpadMic"])
        self.assertTrue(session_probe["checks"]["backendPostUsesSessionEndpoint"])
        self.assertTrue(session_probe["checks"]["backendPostUsesEventTokenHeader"])
        self.assertTrue(session_probe["checks"]["backendPostStoresEnglishDelta"])
        self.assertTrue(session_probe["checks"]["backendPostStoresChineseDelta"])
        self.assertTrue(session_probe["checks"]["backendPostStoresSegmentId"])
        self.assertTrue(session_probe["checks"]["backendPostDoesNotIncludeClientSecret"])
        self.assertTrue(session_probe["checks"]["backendPostDoesNotIncludeEventToken"])
        self.assertEqual(session_probe["createRequest"]["body"]["model"], "gpt-realtime-translate")
        self.assertEqual(session_probe["createRequest"]["body"]["targetLanguage"], "zh")
        self.assertEqual(session_probe["createRequest"]["body"]["audioSourceKind"], "ipad_mic")
        backend_posts = {post["body"]["type"]: post for post in session_probe["backendPosts"]}
        self.assertEqual(backend_posts["input_transcript_delta"]["body"]["en"], "God loved the world")
        self.assertEqual(backend_posts["caption_delta"]["body"]["zh"], "神爱世人")
        self.assertEqual(backend_posts["input_transcript_delta"]["body"]["segmentId"], "seg_post_1")
        self.assertEqual(backend_posts["caption_delta"]["body"]["segmentId"], "seg_post_1")
        self.assertEqual(backend_posts["caption_delta"]["body"]["source"], "openai-realtime-webrtc")
        self.assertEqual(session_probe["persistedEvents"], 2)
        self.assertEqual(session_probe["persistFailures"], 0)
        self.assertIn(
            {
                "sourceEvent": "session.output_transcript.delta",
                "backendEvent": "caption_delta",
                "publicView": "handleRealtimeCaptionEvent -> upsertRealtimeChineseSegment",
            },
            report["eventMappings"],
        )
        self.assertFalse(report["apiKeyMaterialIncluded"])
        self.assertFalse(report["secretResourceNamesIncluded"])
        self.assertFalse(report["eventTokenIncluded"])
        self.assertFalse(report["clientSecretIncluded"])
        self.assertNotIn("projects/", json.dumps(report))
        self.assertNotIn("/secrets/", json.dumps(report))

    def test_missing_webrtc_contract_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_js = Path(tmp) / "app.js"
            app_js.write_text("navigator.mediaDevices.getUserMedia", encoding="utf-8")

            report = mod.validate_web_realtime_contract(app_js)

        self.assertEqual(report["status"], "failed")
        self.assertIn("openai_realtime_webrtc", report["failedChecks"])
        self.assertIn("backend_delta_persistence", report["failedChecks"])

    def test_main_writes_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "web-realtime-contract.json"
            argv = ["validate_web_realtime_contract.py", "--out", str(out)]
            stdout = io.StringIO()
            original_argv = mod.sys.argv
            original_stdout = mod.sys.stdout
            try:
                mod.sys.argv = argv
                mod.sys.stdout = stdout
                exit_code = mod.main()
            finally:
                mod.sys.argv = original_argv
                mod.sys.stdout = original_stdout

            payload = json.loads(out.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(json.loads(stdout.getvalue())["status"], "ok")


if __name__ == "__main__":
    unittest.main()
