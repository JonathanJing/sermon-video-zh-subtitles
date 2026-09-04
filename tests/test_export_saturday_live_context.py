from __future__ import annotations

from datetime import datetime
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from zoneinfo import ZoneInfo


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "export_saturday_live_context.py"
SPEC = importlib.util.spec_from_file_location("export_saturday_live_context", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def prepare_run(root: Path) -> Path:
    run_root = root / "post-live-run"
    (run_root / "download").mkdir(parents=True)
    (run_root / "pipeline").mkdir(parents=True)
    (run_root / "download" / "source_audio.m4a").write_bytes(b"full saturday source audio")
    (run_root / "pipeline" / "source_clip.m4a").write_bytes(b"approved sermon clip audio")
    english = [
        {
            "id": 0,
            "start": 0.0,
            "end": 4.2,
            "text": "Grace leads us through the truth.",
            "source": "gpt-transcribe-reading-layout",
            "timingQuality": "synthetic_not_for_subtitles",
        },
        {
            "id": 1,
            "start": 4.2,
            "end": 8.6,
            "text": "God is faithful in every season.",
            "source": "gpt-transcribe-reading-layout",
            "timingQuality": "synthetic_not_for_subtitles",
        },
    ]
    chinese = [
        {**english[0], "zh": "恩典带领我们经过真理。"},
        {**english[1], "zh": "神在每个季节都信实。"},
    ]
    write_json(run_root / "pipeline" / "segments_timed_en_corrected.json", english)
    write_json(run_root / "pipeline" / "segments_timed_zh.json", chinese)
    write_json(run_root / "pipeline" / "summary.json", {
        "outputMode": "reading",
        "timingPrecision": "synthetic_reading_layout_only",
        "pipelineInputFingerprint": "f" * 64,
        "models": {
            "referenceAsr": "gpt-transcribe",
            "chineseTranslation": "gpt-5.6",
        },
    })
    write_json(run_root / "operator-window-approval.json", {
        "schemaVersion": 1,
        "status": "approved",
        "humanApproval": True,
        "sourceUrlHash": "source-url-hash",
        "startTime": "00:20:00",
        "endTime": "00:50:00",
        "approvedBy": "operator",
    })
    write_json(run_root / "message-identity-approval.json", {
        "schemaVersion": "saturday-message-identity-approval-v1",
        "status": "approved",
        "humanApproval": True,
        "matchStatus": "human_confirmed",
        "messageKey": "series-week-title",
        "targetSunday": "2026-09-06",
        "sourceServiceDate": "2026-09-05",
        "approvedBy": "operator",
        "approvedAt": "2026-09-05T20:00:00-07:00",
    })
    return run_root


class ExportSaturdayLiveContextTest(unittest.TestCase):
    def test_exports_machine_chinese_as_english_map_only_pack(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_root = prepare_run(root)
            output = root / "runtime-pack"
            report = mod.export_context(
                run_root=run_root,
                output_dir=output,
                target_sunday="2026-09-06",
                source_service_date="2026-09-05",
                message_key="series-week-title",
                message_match_status="human_confirmed",
                phrase_candidates=["Mariners Church", "Eric Geiger", "Mariners Church"],
                now=datetime(2026, 9, 6, 12, 0, tzinfo=ZoneInfo("America/Los_Angeles")),
            )

            pack = json.loads((output / "weekly-pack.json").read_text(encoding="utf-8"))
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            readiness = json.loads((output / "pack-readiness.json").read_text(encoding="utf-8"))
            segments = [
                json.loads(line)
                for line in (output / "saturday-segments.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            phrase_text = (output / "asr-phrases.candidate.txt").read_text(encoding="utf-8")
            message_approval = json.loads(
                (output / "message-identity-approval.json").read_text(encoding="utf-8")
            )

        self.assertEqual("degraded", report["readinessStatus"])
        self.assertEqual("english_map_only", report["runtimeMode"])
        self.assertEqual("synthetic_sequence_only", report["timingQuality"])
        self.assertEqual("2026-09-07T06:59:59Z", pack["validUntil"])
        self.assertEqual("America/Los_Angeles", pack["validUntilTimezone"])
        self.assertEqual("machine_generated", segments[0]["translationStatus"])
        self.assertFalse(pack["entries"][0]["canInjectTranslation"])
        self.assertTrue(manifest["capabilities"]["asrPhraseCandidatesReady"])
        self.assertEqual(2, manifest["review"]["asrPhraseCandidateCount"])
        self.assertEqual([], readiness["blockers"])
        self.assertEqual("Eric Geiger\nMariners Church\n", phrase_text)
        self.assertTrue(message_approval["humanApproval"])

    def test_unconfirmed_message_exports_but_readiness_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_root = prepare_run(root)
            report = mod.export_context(
                run_root=run_root,
                output_dir=root / "runtime-pack",
                target_sunday="2026-09-06",
                source_service_date="2026-09-05",
                message_key="series-week-title",
                message_match_status="inferred",
                now=datetime(2026, 9, 6, 12, 0, tzinfo=ZoneInfo("America/Los_Angeles")),
            )
            readiness = json.loads(
                (root / "runtime-pack" / "pack-readiness.json").read_text(encoding="utf-8")
            )

        self.assertEqual("invalid", report["readinessStatus"])
        self.assertEqual("none", report["runtimeMode"])
        self.assertIn("message_match_not_confirmed:inferred", readiness["blockers"])

    def test_rejects_misaligned_chinese_source_text(self):
        english = [{"id": 0, "start": 0.0, "end": 1.0, "text": "Grace is enough."}]
        chinese = [{"id": 0, "start": 0.0, "end": 1.0, "text": "Different source.", "zh": "恩典够用。"}]

        with self.assertRaisesRegex(mod.ExportError, "source text mismatch"):
            mod.convert_pipeline_segments(english, chinese)

    def test_failed_refresh_preserves_existing_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_root = prepare_run(root)
            output = root / "runtime-pack"
            output.mkdir()
            old_manifest = '{"old":"still-valid"}\n'
            (output / "manifest.json").write_text(old_manifest, encoding="utf-8")
            (run_root / "message-identity-approval.json").unlink()

            with self.assertRaisesRegex(mod.ExportError, "requires a message identity approval"):
                mod.export_context(
                    run_root=run_root,
                    output_dir=output,
                    target_sunday="2026-09-06",
                    source_service_date="2026-09-05",
                    message_key="series-week-title",
                    message_match_status="human_confirmed",
                    now=datetime(2026, 9, 6, 12, 0, tzinfo=ZoneInfo("America/Los_Angeles")),
                )

            self.assertEqual(old_manifest, (output / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(["manifest.json"], [path.name for path in output.iterdir()])


if __name__ == "__main__":
    unittest.main()
