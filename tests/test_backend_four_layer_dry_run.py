import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import backend_four_layer_dry_run as dry
from scripts.firebase_dev_weekly_dry_run import checked_backend_run


class BackendFourLayerDryRunTests(unittest.TestCase):
    fixture = dry.ROOT / "config/backend-four-layer-dry-run.fixture.json"

    def test_link_through_preview_is_fast_and_cannot_claim_formal_approval(self):
        with TemporaryDirectory() as folder:
            root = Path(folder) / "run"
            report = dry.run(self.fixture, root)
            self.assertEqual(report["status"], "pass_simulated")
            self.assertEqual(report["schemaVersion"], "sermon-backend-four-layer-dry-run-v2")
            self.assertEqual(report["sourceAcquisition"], "simulated_no_network")
            self.assertEqual(set(report["layers"]), {"layer1", "layer2", "layer3", "layer4"})
            self.assertEqual(report["layers"]["layer1"]["status"],
                             "candidate_blocked_at_human_gate")
            self.assertEqual(report["layers"]["layer1"]["humanReview"], "pending")
            self.assertFalse(report["formalApproval"])
            self.assertFalse(report["productionReleaseEligible"])
            self.assertEqual(report["productionPlannerGate"], "rejected_simulated_source")
            self.assertEqual(sum(report["externalCalls"].values()), 0)
            layer4 = report["layers"]["layer4"]
            self.assertEqual(layer4["assetAssembly"], "copy_bound_asset_v1")
            self.assertEqual(len(layer4["assets"]), 3)
            for row in layer4["assets"]:
                copied = root / "public/flow" / row["path"].lstrip("/")
                self.assertEqual(dry.digest(copied), row["sha256"])
                self.assertEqual(copied.stat().st_size, row["sizeBytes"])
            self.assertEqual(len(report["events"]), 29)
            self.assertEqual(len([event for event in report["events"]
                                  if ":unit-" in event["step"]]), 18)
            self.assertEqual(report["sharedControlLoops"], {
                "layer2": "astra_sol_group_runner",
                "layer3": "pcm16_schedule_and_assembly"})
            self.assertEqual(sum(report["layers"]["layer2"][locale]["modelCalls"]
                                 for locale in dry.LOCALES), 12)
            for locale in dry.LOCALES:
                self.assertEqual(report["layers"]["layer2"][locale]["formalGate"],
                                 "rejected_simulated_source")
                request = json.loads((root / "layer2-model-loop" / locale / "request.json")
                                     .read_text(encoding="utf-8"))
                self.assertTrue(request["simulationOnly"])
                self.assertEqual(request["schemaVersion"],
                                 "sermon-dry-run-layer2-request-v1")
                self.assertFalse((root / "layer2-model-loop" / locale /
                                  "candidate.json").exists())
            self.assertTrue(all(event["startedAt"] and event["endedAt"]
                                and event["elapsedMs"] >= 0 for event in report["events"]))
            self.assertEqual(len(report["publicFiles"]), 5)
            self.assertFalse((root / "public/multilingual-v3.json").exists())
            self.assertFalse((root / "public/releases-v2").exists())
            public = (root / "public/flow/index.html").read_text(encoding="utf-8")
            self.assertIn("DRY RUN · SIMULATED", public)
            for locale in dry.LOCALES:
                self.assertIn(f"media/{locale}.wav", public)
                self.assertEqual(report["layers"]["layer3"][locale]["schedule"], "pass")
            checked_backend_run(root)

    def test_l3_completion_automatically_hands_bound_audio_to_layer4(self):
        with TemporaryDirectory() as folder:
            root = Path(folder) / "run"
            report = dry.run(self.fixture, root)
            self.assertEqual(report["status"], "pass_simulated")
            layer4_started = next(event for event in report["events"]
                                  if event["step"] == "layer4")["startedAt"]
            for locale in dry.LOCALES:
                l3_event = next(event for event in report["events"]
                                if event["step"] == f"layer3:{locale}")
                self.assertEqual(l3_event["status"], "pass")
                self.assertLessEqual(l3_event["endedAt"], layer4_started)

            assets = {row["path"]: row for row in report["layers"]["layer4"]["assets"]}
            for locale in dry.LOCALES:
                relative_path = f"/media/{locale}.wav"
                expected_sha = report["layers"]["layer3"][locale]["audioSha256"]
                self.assertEqual(assets[relative_path]["sha256"], expected_sha)
                copied = root / "public/flow" / relative_path.lstrip("/")
                self.assertEqual(dry.digest(copied), expected_sha)
            self.assertFalse(report["formalApproval"])
            self.assertFalse(report["productionReleaseEligible"])

    def test_l3_failure_stops_before_automatic_layer4_handoff(self):
        with TemporaryDirectory() as folder:
            root = Path(folder) / "failed-l3"
            report = dry.run(self.fixture, root, fail_at="layer3:ko")
            self.assertEqual(report["status"], "failed")
            self.assertEqual(report["events"][-1]["step"], "layer3:ko")
            self.assertEqual(report["events"][-1]["status"], "fail")
            self.assertNotIn("layer4", report["layers"])
            self.assertFalse((root / "public/flow/index.html").exists())
            with self.assertRaises(ValueError):
                checked_backend_run(root)

    def test_current_same_model_roles_keep_independent_review_and_legacy_failure_ids(self):
        call = dry.layer2_runner._model_call
        with TemporaryDirectory() as folder, patch.object(dry.layer2_runner, "_model_call", wraps=call) as observed:
            report = dry.run(self.fixture, Path(folder) / "run")
        self.assertEqual(report["status"], "pass_simulated")
        self.assertEqual(sum(report["externalCalls"].values()), 0)
        self.assertEqual(len(observed.call_args_list), 12)
        for dispatched in observed.call_args_list:
            role, prompt, policy = dispatched.args[:3]
            self.assertEqual(policy[role]["model"], "gpt-6.1-sol")
            self.assertEqual(policy[role]["reasoningEffort"], "high" if role == "translator" else "medium")
            self.assertEqual("astraDraft" in prompt["input"], role == "reviewer")
        events = [row["step"] for row in report["events"] if row["step"].endswith((":astra", ":sol"))]
        self.assertEqual(events[:2], ["layer2:zh-Hans:unit-0:astra", "layer2:zh-Hans:unit-0:sol"])

    def test_layer4_uses_formal_copy_gate_and_changed_upstream_never_creates_preview(self):
        from scripts import build_formal_dev_release_assets as formal
        from scripts import build_full_video_app_release as full
        self.assertIs(dry.copy_bound_asset, formal.copy_bound_asset)
        self.assertIs(dry.copy_bound_asset, full.copy_bound_asset)
        real_copy = dry.copy_bound_asset
        def changed(source, root, path, expected):
            if path == "/media/ko.wav":
                source.write_bytes(b"changed after Layer 3 receipt")
            return real_copy(source, root, path, expected)
        with TemporaryDirectory() as folder, patch.object(dry, "copy_bound_asset", side_effect=changed):
            root = Path(folder) / "failed-copy"
            report = dry.run(self.fixture, root)
            self.assertEqual(report["status"], "failed")
            self.assertEqual(report["events"][-1]["step"], "layer4")
            self.assertIn("admitted_identity", report["failure"])
            self.assertFalse((root / "public/flow/index.html").exists())
            self.assertFalse((root / "public/flow/media/ko.wav").exists())
            self.assertFalse(list(root.rglob(".asset-*")))
            self.assertFalse(report["formalApproval"])
            with self.assertRaises(ValueError):
                checked_backend_run(root)

    def test_injected_locale_failure_stops_before_layer4_and_is_not_publishable(self):
        with TemporaryDirectory() as folder:
            root = Path(folder) / "failed"
            report = dry.run(self.fixture, root, fail_at="layer2:ko")
            self.assertEqual(report["status"], "failed")
            self.assertEqual(report["events"][-1]["step"], "layer2:ko")
            self.assertEqual(report["events"][-1]["status"], "fail")
            self.assertFalse((root / "public/flow/index.html").exists())
            with self.assertRaises(ValueError):
                checked_backend_run(root)

    def test_injected_independent_review_failure_stops_before_audio_and_layer4(self):
        with TemporaryDirectory() as folder:
            root = Path(folder) / "failed-review"
            report = dry.run(self.fixture, root, fail_at="layer2:ko:unit-0:sol")
            self.assertEqual(report["status"], "failed")
            self.assertEqual(report["events"][-1]["step"], "layer2:ko:unit-0:sol")
            self.assertEqual(report["events"][-1]["status"], "fail")
            self.assertEqual(report["events"][-2]["step"], "layer2:ko:unit-0:astra")
            self.assertEqual(next(event for event in report["events"]
                                  if event["step"] == "layer2:ko")["status"], "fail")
            self.assertNotIn("layer3", report["layers"])
            self.assertFalse((root / "public/flow/index.html").exists())
            with self.assertRaises(ValueError):
                checked_backend_run(root)

    def test_unreachable_failure_point_cannot_report_success(self):
        with TemporaryDirectory() as folder:
            root = Path(folder) / "unreachable"
            report = dry.run(self.fixture, root, fail_at="layer2:ko:unit-7:sol")
            self.assertEqual(report["status"], "failed")
            self.assertIn("was not reached", report["failure"])
            self.assertFalse((root / "public/flow/index.html").exists())
            with self.assertRaises(ValueError):
                checked_backend_run(root)

    def test_rejects_real_link_and_tampered_preview(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            fixture = json.loads(self.fixture.read_text(encoding="utf-8"))
            fixture["sourceUrl"] = "https://example.com/actual-sermon"
            path = root / "fixture.json"
            path.write_text(json.dumps(fixture), encoding="utf-8")
            failed = dry.run(path, root / "bad-link")
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["events"][-1]["step"], "intake")
            good = root / "good"
            self.assertEqual(dry.run(self.fixture, good)["status"], "pass_simulated")
            (good / "public/flow/media/ko.wav").write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "changed"):
                checked_backend_run(good)


if __name__ == "__main__":
    unittest.main()
