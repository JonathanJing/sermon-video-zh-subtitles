import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import scripts.write_no_caption_asr_fallback_plan as mod


class WriteNoCaptionAsrFallbackPlanTest(unittest.TestCase):
    def test_plan_documents_real_no_caption_asr_route(self):
        report = mod.build_plan(Namespace(sunday="2026-06-28", session_id="no-caption-asr-route", out=None))

        self.assertEqual(report["status"], "needs_real_no_caption_archive")
        self.assertEqual(report["requiredModels"]["offlineAsr"], "gpt-4o-transcribe")
        self.assertEqual(report["requiredModels"]["offlineTranslation"], "gpt-5.5-mini")
        self.assertEqual(report["requiredModels"]["forbiddenOfflineModel"], "gpt-realtime-translate")
        commands = json.dumps(report["commands"])
        self.assertIn("run_offline_archive_preflight.py", commands)
        self.assertIn("prepare_live_link_playback.py", commands)
        self.assertIn("validate_offline_chain.py", commands)
        self.assertIn("validate_production_readiness.py", commands)
        self.assertIn("--input", commands)
        self.assertNotIn("--playback-js", " ".join(" ".join(command) for command in report["commands"][:4]))
        translate_command = next(command for command in report["commands"] if "scripts/translate_playback_with_openai.py" in command)
        playback_js = "artifacts/evidence/2026-06-28-no-caption-asr-route/web/playback-simulation.generated.js"
        prepare_command = next(command for command in report["commands"] if "scripts/prepare_live_link_playback.py" in command)
        self.assertEqual(
            prepare_command[prepare_command.index("--out-dir") + 1],
            "artifacts/evidence/2026-06-28-no-caption-asr-route/artifacts",
        )
        self.assertEqual(prepare_command[prepare_command.index("--web-out") + 1], playback_js)
        self.assertEqual(prepare_command[prepare_command.index("--gcs-bucket") + 1], "sermon-zh-artifacts-ai-for-god")
        self.assertEqual(
            prepare_command[prepare_command.index("--gcs-prefix") + 1],
            "sundays/2026-06-28/runs/no-caption-asr-route",
        )
        self.assertIn("--gcs-dry-run", prepare_command)
        self.assertEqual(translate_command[translate_command.index("--input") + 1], playback_js)
        self.assertEqual(translate_command[translate_command.index("--out") + 1], playback_js)
        self.assertIn("--api-key-secret", translate_command)
        export_command = next(command for command in report["commands"] if "scripts/export_playback_captions.py" in command)
        self.assertEqual(export_command[export_command.index("--input") + 1], playback_js)
        self.assertEqual(export_command[export_command.index("--stem") + 1], "sermon.zh.live-aligned")
        self.assertEqual(
            export_command[export_command.index("--manifest") + 1],
            "artifacts/evidence/2026-06-28-no-caption-asr-route/artifacts/cloud-manifest.json",
        )
        self.assertEqual(export_command[export_command.index("--gcs-bucket") + 1], "sermon-zh-artifacts-ai-for-god")
        self.assertEqual(
            export_command[export_command.index("--gcs-prefix") + 1],
            "sundays/2026-06-28/runs/no-caption-asr-route",
        )
        self.assertIn("--gcs-dry-run", export_command)
        validate_command = next(command for command in report["commands"] if "scripts/validate_offline_chain.py" in command)
        self.assertEqual(
            validate_command[validate_command.index("--report") + 1],
            "artifacts/evidence/2026-06-28-no-caption-asr-route/artifacts/report.json",
        )
        self.assertEqual(validate_command[validate_command.index("--expected-asr-model") + 1], "gpt-4o-transcribe")
        self.assertEqual(validate_command[validate_command.index("--expected-translation-model") + 1], "gpt-5.5-mini")
        self.assertIn("use_asr_fallback", " ".join(report["passCriteria"]))
        self.assertIn("no requested English caption track", " ".join(report["passCriteria"]))
        self.assertIn("extracted audio artifact", " ".join(report["passCriteria"]))
        self.assertFalse(report["apiKeyMaterialIncluded"])
        self.assertFalse(report["secretResourceNamesIncluded"])
        rendered = json.dumps(report)
        self.assertNotIn("projects/", rendered)
        self.assertNotIn("/secrets/", rendered)

    def test_main_writes_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "plan.json"
            original_argv = sys.argv
            try:
                sys.argv = [
                    "write_no_caption_asr_fallback_plan.py",
                    "--sunday",
                    "2026-06-28",
                    "--out",
                    str(out),
                ]
                exit_code = mod.main()
            finally:
                sys.argv = original_argv

            written = json.loads(out.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(written["status"], "needs_real_no_caption_archive")


if __name__ == "__main__":
    unittest.main()
