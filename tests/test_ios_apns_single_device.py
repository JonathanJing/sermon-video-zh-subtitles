import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

MODULE = Path(__file__).parents[1] / "apps/tongxing-ios/scripts/apns-single-device.py"
spec = importlib.util.spec_from_file_location("apns_single", MODULE)
apns = importlib.util.module_from_spec(spec)
spec.loader.exec_module(apns)


class APNsSingleDeviceTests(unittest.TestCase):
    def device(self):
        return {"schemaVersion": "tongxing-beta-apns-device-v1", "bundleID": apns.BUNDLE,
                "environment": "production", "deviceToken": "ab" * 40, "locale": "zh-Hans"}

    def test_private_receipt_rejects_formal_identity_unknown_environment_and_world_readable(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "device.json"
            device = self.device()
            for field, bad in [("bundleID", "com.jonathanjing.tongxing.dev"), ("environment", "unknown")]:
                path.write_text(json.dumps(dict(device, **{field: bad})))
                os.chmod(path, 0o600)
                with self.assertRaises(apns.TestValidationError):
                    apns.device_receipt(path)
            path.write_text(json.dumps(device))
            os.chmod(path, 0o644)
            with self.assertRaises(apns.TestValidationError):
                apns.device_receipt(path)
            os.chmod(path, 0o600)
            self.assertEqual(apns.device_receipt(path), device)

    def test_unpublished_or_simulated_target_cannot_be_sent(self):
        target = {"contentStatus": "human_reviewed", "releasePackageJsonSha256": "a" * 64}
        catalog = {"schemaVersion": "sermon-multilingual-catalog-v3", "defaultPageId": "week",
                   "pages": [{"id": "week", "date": "2026-10-04", "targets": {"zh-Hans": target}}]}
        payload, _ = apns.notice_payload(catalog, None, "zh-Hans")
        self.assertEqual(payload["tongxing"]["pageID"], "week")
        for flag in ["simulationOnly", "diagnosticOnly"]:
            catalog["pages"][0][flag] = True
            with self.assertRaises(apns.TestValidationError):
                apns.notice_payload(catalog, None, "zh-Hans")
            catalog["pages"][0].pop(flag)
        for bad in [{"simulationOnly": True}, {"diagnosticOnly": True}, {"contentStatus": "candidate"}]:
            target.update(bad)
            with self.assertRaises(apns.TestValidationError):
                apns.notice_payload(catalog, None, "zh-Hans")
            target.pop("simulationOnly", None)
            target.pop("diagnosticOnly", None)
            target["contentStatus"] = "human_reviewed"

    def test_failed_request_is_not_retried_and_receipt_and_argv_do_not_expose_secrets(self):
        device = self.device()
        jwt = "private.jwt.secret"
        payload = {"aps": {"alert": {"title": "test"}}, "tongxing": {"pageID": "week"}}
        with tempfile.TemporaryDirectory() as root:
            with patch.object(apns.subprocess, "run", return_value=subprocess.CompletedProcess([], 28, "000", "")) as run:
                self.assertFalse(apns.send(device, payload, jwt, root))
                self.assertEqual(run.call_count, 1)
                self.assertEqual(run.call_args.args[0][:2], ["/usr/bin/curl", "-q"])
                self.assertNotIn(device["deviceToken"], str(run.call_args.args))
                self.assertNotIn(jwt, str(run.call_args.args))
            saved = next(Path(root).glob("*.json")).read_text()
            self.assertNotIn(device["deviceToken"], saved)
            self.assertNotIn(jwt, saved)
            self.assertEqual(json.loads(saved)["deviceDisplayed"], "not_run")


    def test_unknown_transport_preserves_intent_without_claiming_unsent(self):
        with tempfile.TemporaryDirectory() as root:
            with patch.object(apns.subprocess, "run", side_effect=OSError("transport unavailable")) as run:
                with self.assertRaises(apns.OutcomeUnknownError):
                    apns.send(self.device(), {"tongxing": {"pageID": "week"}}, "private.jwt", root)
                self.assertEqual(run.call_count, 1)
            intent = json.loads(next(Path(root).glob("*.json")).read_text())
            self.assertEqual(intent["phase"], "request_outcome_unknown")
            self.assertNotIn("deviceToken", intent)


if __name__ == "__main__":
    unittest.main()
