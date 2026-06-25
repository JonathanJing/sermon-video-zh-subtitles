import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import scripts.write_1130_live_realtime_run_plan as mod


class Write1130LiveRealtimeRunPlanTest(unittest.TestCase):
    def test_plan_documents_live_realtime_and_offline_handoff_policy(self):
        report = mod.build_plan(
            Namespace(sunday="2026-06-28", base_url="https://example.test", out=None)
        )

        self.assertEqual(report["status"], "ready_for_operator_review")
        self.assertEqual(report["targetWindow"]["liveCaptionStart"], "11:30 PT")
        self.assertEqual(report["modelPolicy"]["realtimeDraftModel"], "gpt-realtime-translate")
        self.assertEqual(report["modelPolicy"]["stableCorrectionModel"], "gpt-5.4-mini")
        self.assertEqual(report["modelPolicy"]["offlineAsrModel"], "gpt-4o-transcribe")
        self.assertEqual(report["modelPolicy"]["offlineTranslationModel"], "gpt-5.4-mini")
        self.assertEqual(report["modelPolicy"]["forbiddenOfflineModel"], "gpt-realtime-translate")
        self.assertTrue(report["modelPolicy"]["doNotSubstituteAlternativeForRequiredMini"])
        browser = report["operatorChoices"][0]
        self.assertEqual(browser["id"], "browser_webrtc_ipad_or_iphone_mic")
        self.assertTrue(browser["default"])
        self.assertEqual(browser["expectedAudioSourceKind"], "ipad_mic")
        server_command = report["operatorChoices"][1]["command"]
        self.assertIn("scripts/run_realtime_live_session.py", server_command)
        self.assertEqual(
            server_command[server_command.index("--realtime-model") + 1],
            "gpt-realtime-translate",
        )
        self.assertEqual(server_command[server_command.index("--stable-model") + 1], "gpt-5.4-mini")
        self.assertIn("--require-stable-correction", server_command)
        stabilizer_command = report["stabilizerFallbackCommand"]
        self.assertIn("scripts/run_realtime_stabilizer_loop.py", stabilizer_command)
        self.assertEqual(stabilizer_command[stabilizer_command.index("--model") + 1], "gpt-5.4-mini")
        live_validation_commands = json.dumps(report["liveValidationCommands"])
        self.assertIn("scripts/run_realtime_public_sse_smoke.py", live_validation_commands)
        self.assertIn("--web-realtime-contract-report", live_validation_commands)
        self.assertIn("artifacts/evidence/web-realtime-contract.json", live_validation_commands)
        offline_commands = json.dumps(report["postLiveOfflineHandoff"]["commands"])
        no_caption_runner = report["postLiveOfflineHandoff"]["noCaptionRunnerCommand"]
        self.assertIn("scripts/run_no_caption_archive_asr_route.py", no_caption_runner)
        self.assertEqual(no_caption_runner[no_caption_runner.index("--asr-model") + 1], "gpt-4o-transcribe")
        self.assertEqual(no_caption_runner[no_caption_runner.index("--translation-model") + 1], "gpt-5.4-mini")
        self.assertIn("scripts/validate_offline_chain.py", offline_commands)
        self.assertIn("gpt-4o-transcribe", offline_commands)
        self.assertIn("gpt-5.4-mini", offline_commands)
        self.assertIn("Offline post-live route never uses gpt-realtime-translate.", report["passCriteria"])
        self.assertTrue(report["guards"]["doesNotCallOpenAI"])
        self.assertFalse(report["apiKeyMaterialIncluded"])
        self.assertFalse(report["secretResourceNamesIncluded"])
        self.assertFalse(report["eventTokenIncluded"])
        rendered = json.dumps(report)
        self.assertNotIn("/secrets/", rendered)
        self.assertNotIn("projects/", rendered)
        self.assertNotIn("sk-test", rendered)
        self.assertNotIn("sk_live", rendered)

    def test_main_writes_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "plan.json"
            original_argv = sys.argv
            try:
                sys.argv = [
                    "write_1130_live_realtime_run_plan.py",
                    "--sunday",
                    "2026-06-28",
                    "--base-url",
                    "https://example.test",
                    "--out",
                    str(out),
                ]
                exit_code = mod.main()
            finally:
                sys.argv = original_argv

            written = json.loads(out.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(written["status"], "ready_for_operator_review")


if __name__ == "__main__":
    unittest.main()
