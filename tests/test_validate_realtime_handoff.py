import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import scripts.validate_realtime_handoff as mod


class ValidateRealtimeHandoffTest(unittest.TestCase):
    def test_valid_handoff_reports_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_reports(Path(tmp))

            report = mod.validate_handoff(args_for(paths))

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["failedChecks"], [])
        self.assertIn("artifacts/evidence/web-realtime-contract.json", report["requiredEvidenceReports"])
        self.assertFalse(report["apiKeyMaterialIncluded"])
        self.assertFalse(report["secretResourceNamesIncluded"])
        self.assertFalse(report["eventTokenIncluded"])

    def test_missing_browser_evidence_fails_all_handoff_layers(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_reports(Path(tmp), remove_browser_evidence=True)

            report = mod.validate_handoff(args_for(paths))

        self.assertEqual(report["status"], "failed")
        self.assertIn("live_plan_operator_choices", report["failedChecks"])
        self.assertIn("operator_runbook_operator_choices", report["failedChecks"])
        self.assertIn("go_live_live_stage_operator_choices", report["failedChecks"])

    def test_missing_asr_model_in_offline_handoff_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_reports(Path(tmp), remove_asr_model=True)

            report = mod.validate_handoff(args_for(paths))

        self.assertEqual(report["status"], "failed")
        self.assertIn("live_plan_offline_handoff", report["failedChecks"])
        self.assertIn("operator_runbook_offline_handoff", report["failedChecks"])

    def test_missing_go_live_asr_stage_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_reports(Path(tmp), remove_go_live_asr_stage=True)

            report = mod.validate_handoff(args_for(paths))

        self.assertEqual(report["status"], "failed")
        self.assertIn("go_live_no_caption_asr_stage", report["failedChecks"])

    def test_incomplete_go_live_asr_stage_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_reports(Path(tmp), incomplete_go_live_asr_stage=True)

            report = mod.validate_handoff(args_for(paths))

        self.assertEqual(report["status"], "failed")
        self.assertIn("go_live_no_caption_asr_stage", report["failedChecks"])
        check = next(check for check in report["checks"] if check["name"] == "go_live_no_caption_asr_stage")
        self.assertFalse(check["observed"]["hasOfflineAsrChainReport"])

    def test_main_writes_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = write_reports(root)
            out = root / "handoff-validation.json"
            original = mod.parse_args
            try:
                mod.parse_args = lambda: args_for(paths, out=out)
                code = mod.main()
            finally:
                mod.parse_args = original

            self.assertEqual(code, 0)
            written = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(written["status"], "ok")

    def test_secret_material_detector_allows_flags_but_blocks_real_material(self):
        self.assertFalse(mod.contains_secret_material("--internal-task-token $INTERNAL_TASK_TOKEN"))
        self.assertTrue(mod.contains_secret_material("sk-this-is-real-looking-key-material"))
        self.assertTrue(mod.contains_secret_material("projects/p/secrets/openai-api-key/versions/latest"))


def args_for(paths: dict[str, Path], out: Path | None = None):
    return Namespace(
        live_plan=paths["live"],
        operator_bundle=paths["operator"],
        go_live_sequence=paths["go_live"],
        out=out,
    )


def write_reports(
    root: Path,
    *,
    remove_browser_evidence=False,
    remove_asr_model=False,
    remove_go_live_asr_stage=False,
    incomplete_go_live_asr_stage=False,
):
    live = live_plan(remove_browser_evidence=remove_browser_evidence, remove_asr_model=remove_asr_model)
    operator = operator_bundle(live)
    go_live = go_live_sequence(
        live,
        remove_asr_stage=remove_go_live_asr_stage,
        incomplete_asr_stage=incomplete_go_live_asr_stage,
    )
    paths = {
        "live": root / "live-1130-realtime-run-plan.json",
        "operator": root / "operator-approval-bundle.json",
        "go_live": root / "production-go-live-sequence.json",
    }
    for key, path in paths.items():
        data = {"live": live, "operator": operator, "go_live": go_live}[key]
        path.write_text(json.dumps(data), encoding="utf-8")
    return paths


def live_plan(*, remove_browser_evidence=False, remove_asr_model=False):
    evidence = [
        "artifacts/evidence/web-realtime-contract.json",
        "artifacts/evidence/public-caption-view-runtime.json",
        "artifacts/evidence/realtime-public-sse-smoke.json",
        "artifacts/evidence/realtime-public-sse-smoke.session-validation.json",
    ]
    if remove_browser_evidence:
        evidence = ["artifacts/evidence/web-realtime-contract.json"]
    no_caption = [
        "If requested English captions are absent, extract authorized archive audio.",
        "Transcribe with gpt-4o-transcribe.",
        "Translate with gpt-5.5-mini.",
        "Validate not_realtime_chain before publishing.",
    ]
    if remove_asr_model:
        no_caption = [item.replace("gpt-4o-transcribe", "speech model") for item in no_caption]
    return {
        "schemaVersion": 1,
        "status": "ready_for_operator_review",
        "modelPolicy": {
            "realtimeDraftModel": "gpt-realtime-translate",
            "stableCorrectionModel": "gpt-5.5-mini",
            "offlineAsrModel": "gpt-4o-transcribe",
            "offlineTranslationModel": "gpt-5.5-mini",
            "forbiddenOfflineModel": "gpt-realtime-translate",
        },
        "operatorChoices": [
            {
                "id": "browser_webrtc_ipad_or_iphone_mic",
                "default": True,
                "source": "iPad/iPhone mic",
                "path": "browser WebRTC -> gpt-realtime-translate -> backend session events -> public caption SSE",
                "expectedAudioSourceKind": "ipad_mic",
                "operatorAction": "Open the admin page, choose iPad mic realtime mode, and start the microphone session.",
                "evidenceReports": evidence,
            },
            {
                "id": "server_worker_authorized_audio",
                "default": False,
                "source": "authorized audio URL/file or authorized YouTube live source",
                "path": "server media worker -> gpt-realtime-translate -> backend session events -> public caption SSE",
                "expectedAudioSourceKinds": ["authorized_audio_url", "authorized_audio_file", "authorized_youtube_source"],
                "command": [
                    "python3",
                    "scripts/run_realtime_live_session.py",
                    "--realtime-model",
                    "gpt-realtime-translate",
                    "--stable-model",
                    "gpt-5.5-mini",
                ],
            },
        ],
        "liveValidationCommands": [
            [
                "python3",
                "scripts/run_realtime_public_sse_smoke.py",
                "--web-realtime-contract-report",
                "artifacts/evidence/web-realtime-contract.json",
            ],
            [
                "python3",
                "scripts/validate_realtime_session.py",
                "--expected-model",
                "gpt-realtime-translate",
                "--expected-stable-model",
                "gpt-5.5-mini",
                "--require-stable-correction",
            ],
        ],
        "postLiveOfflineHandoff": {
            "trigger": "Run only after the YouTube live archive is available.",
            "captionFirst": [
                "Try requested English captions/VTT first.",
                "Translate with gpt-5.5-mini.",
                "Export zh VTT/SRT/playback JS/GCS manifest.",
            ],
            "noCaptionFallback": no_caption,
        },
        "passCriteria": [
            "Offline post-live route never uses gpt-realtime-translate.",
        ],
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
        "eventTokenIncluded": False,
    }


def operator_bundle(live):
    return {
        "schemaVersion": 1,
        "status": "approval_required",
        "live1130Runbook": {
            "status": live["status"],
            "modelPolicy": live["modelPolicy"],
            "operatorChoices": live["operatorChoices"],
            "liveValidationCommands": live["liveValidationCommands"],
            "postLiveOfflineHandoff": live["postLiveOfflineHandoff"],
            "passCriteria": live["passCriteria"],
        },
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
        "eventTokenIncluded": False,
    }


def go_live_sequence(live, *, remove_asr_stage=False, incomplete_asr_stage=False):
    sequence = [
        {
            "id": "live_1130_realtime_run",
            "state": "pending_realtime_field_run",
            "modelPolicy": live["modelPolicy"],
            "operatorChoices": live["operatorChoices"],
            "liveValidationCommands": live["liveValidationCommands"],
        }
    ]
    if not remove_asr_stage:
        asr_stage = {
            "id": "real_no_caption_asr_validation",
            "state": "needs_real_no_caption_archive",
            "commands": [
                ["python3", "scripts/run_offline_archive_preflight.py", "--asr-model", "gpt-4o-transcribe"],
                ["python3", "scripts/prepare_live_link_playback.py", "--asr-model", "gpt-4o-transcribe"],
                ["python3", "scripts/translate_playback_with_openai.py", "--model", "gpt-5.5-mini"],
                ["python3", "scripts/export_playback_captions.py", "--stem", "sermon.zh.live-aligned"],
                [
                    "python3",
                    "scripts/validate_offline_chain.py",
                    "--expected-asr-model",
                    "gpt-4o-transcribe",
                    "--expected-translation-model",
                    "gpt-5.5-mini",
                    "--out",
                    "artifacts/evidence/no-caption-offline-chain-validation.json",
                ],
                ["python3", "scripts/validate_production_readiness.py", "--out", "artifacts/evidence/asr-route-readiness.json"],
            ],
            "requiredModels": {
                "offlineAsr": "gpt-4o-transcribe",
                "offlineTranslation": "gpt-5.5-mini",
                "forbiddenOfflineModel": "gpt-realtime-translate",
            },
            "requiredReports": [
                "artifacts/evidence/no-caption-archive-preflight.json",
                "artifacts/evidence/no-caption-offline-chain-validation.json",
                "artifacts/evidence/asr-route-readiness.json",
            ],
            "passCriteria": [
                "Prepared offline report has caption_source.kind=openai_asr.",
                "validate_offline_chain.py status is ok and not_realtime_chain passes.",
            ],
            "nextAction": "Feed artifacts/evidence/no-caption-offline-chain-validation.json via --offline-asr-chain-validation-report.",
        }
        if incomplete_asr_stage:
            asr_stage["requiredReports"] = ["artifacts/evidence/asr-route-readiness.json"]
            asr_stage["nextAction"] = "Run ASR route."
        sequence.append(asr_stage)
    return {
        "schemaVersion": 1,
        "status": "not_ready_for_go_live",
        "sequence": sequence,
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
        "eventTokenIncluded": False,
    }


if __name__ == "__main__":
    unittest.main()
