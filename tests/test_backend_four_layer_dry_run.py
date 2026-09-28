import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts import backend_four_layer_dry_run as dry
from scripts.firebase_dev_weekly_dry_run import checked_backend_run


class BackendFourLayerDryRunTests(unittest.TestCase):
    fixture = dry.ROOT / "config/backend-four-layer-dry-run.fixture.json"

    def test_link_through_preview_is_fast_and_cannot_claim_formal_approval(self):
        with TemporaryDirectory() as folder:
            root = Path(folder) / "run"
            report = dry.run(self.fixture, root)
            self.assertEqual(report["status"], "pass_simulated")
            self.assertEqual(report["sourceAcquisition"], "simulated_no_network")
            self.assertEqual(set(report["layers"]), {"layer1", "layer2", "layer3", "layer4"})
            self.assertEqual(report["layers"]["layer1"]["status"],
                             "candidate_blocked_at_human_gate")
            self.assertEqual(report["layers"]["layer1"]["humanReview"], "pending")
            self.assertFalse(report["formalApproval"])
            self.assertFalse(report["productionReleaseEligible"])
            self.assertEqual(report["productionPlannerGate"], "rejected_simulated_source")
            self.assertEqual(sum(report["externalCalls"].values()), 0)
            self.assertEqual(len(report["events"]), 23)
            self.assertEqual(len([event for event in report["events"]
                                  if ":unit-" in event["step"]]), 12)
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
