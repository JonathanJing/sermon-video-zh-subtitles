import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import assemble_multilingual_hosting as hosting
from scripts import stage_production_voice_samples as voices


def write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) if isinstance(value, dict) else value, encoding="utf-8")


class ProductionVoiceWeeklyRefreshTests(unittest.TestCase):
    def test_refresh_preserves_voice_samples_and_current_home(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base, legacy, out = (root / name for name in ("base", "legacy", "out"))
            old_weekly = {"weeks": [{"id": "2026-09-20"}],
                          "voiceBank": {"speakers": [{"id": "eric", "name": "Eric"}]}}
            new_weekly = {"weeks": [{"id": "2026-09-20"}, {"id": "2026-09-27"}],
                          "voiceBank": old_weekly["voiceBank"]}
            write(base / "public/index.html", "current Production home with voice auditions")
            write(base / "public/style.css", "current Production styles")
            write(base / "public/weekly.json", old_weekly)
            write(base / "public/voice-demos/demo/eric/ko.mp3", "approved audition bytes")
            write(base / "firebase.json", {"hosting": {"site": voices.SITE}})
            report = {"schemaVersion": voices.SCHEMA, "status": "validated_not_deployed",
                      "files": voices.inventory(base / "public"), "feedbackEnabled": False}
            write(base / "build-report.json", report)
            prior = root / "prior.json"
            write(prior, {"schemaVersion": "sermon-production-voice-http-v1",
                          "status": "pass", "phase": "published", "origin": voices.ORIGIN,
                          "buildReportSha256": hosting.digest(base / "build-report.json"),
                          "checkedFiles": len(report["files"])})
            write(legacy / "public/index.html", "older registered home")
            write(legacy / "public/style.css", "older registered styles")
            write(legacy / "public/weekly.json", new_weekly)
            write(legacy / "public/media/new.mp3", "new published track")
            write(legacy / "build-report.json", {"feedbackEnabled": False})
            write(legacy / "release-plan.json", {
                "schemaVersion": "sermon-weekly-release-plan-v1", "status": "prepared_not_deployed",
                "origin": voices.ORIGIN, "buildReportSha256": hosting.digest(legacy / "build-report.json"),
                "previousWeekIds": ["2026-09-20"],
                "weekIds": ["2026-09-20", "2026-09-27"],
                "changes": {"removed": []}, "uiPolicy": "reuse_registered_ui_and_settings"})
            with patch.object(voices, "verify_candidate",
                              side_effect=lambda candidate: hosting.load(candidate / "build-report.json")), \
                 patch.object(voices.weekly_release, "read_release",
                              return_value=({"feedbackEnabled": False}, new_weekly)):
                refreshed = voices.refresh(base, legacy, prior, out)
            self.assertEqual((out / "public/index.html").read_text(),
                             "current Production home with voice auditions")
            self.assertEqual(hosting.digest(out / "public/voice-demos/demo/eric/ko.mp3"),
                             hosting.digest(base / "public/voice-demos/demo/eric/ko.mp3"))
            self.assertEqual(hosting.load(out / "public/weekly.json"), new_weekly)
            self.assertEqual((out / "public/media/new.mp3").read_text(), "new published track")
            self.assertEqual(refreshed["modifiedFiles"], ["weekly.json"])
            self.assertEqual(refreshed["addedFiles"], ["media/new.mp3"])


if __name__ == "__main__":
    unittest.main()
