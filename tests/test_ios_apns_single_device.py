import importlib.util
import hashlib
import urllib.error
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

    def fixture(self, machine=True):
        status = "machine_checked" if machine else "human_reviewed"
        version = "v4" if machine else "v2"
        release = {"schemaVersion": "sermon-target-language-release-package-" + version,
                   "pageId": "week", "targetLocale": "zh-Hans", "status": "published_http_verified",
                   "contentStatus": status, "audioStatus": status, "httpVerification": {"status": "pass"}}
        raw = json.dumps(release).encode()
        target = {"contentStatus": status, "audioStatus": status,
                  "releasePackageUrl": f"/releases-{version}/week/zh-Hans.json",
                  "releasePackageJsonSha256": hashlib.sha256(raw).hexdigest()}
        catalog = {"schemaVersion": "sermon-multilingual-catalog-" + ("v4" if machine else "v3"),
                   "defaultPageId": "week", "pages": [{"id": "week", "targets": {"zh-Hans": target}}]}
        return catalog, target, release, raw

    def test_v4_machine_and_v3_human_release_binding(self):
        for machine in (True, False):
            catalog, target, release, raw = self.fixture(machine)
            with patch.object(apns, "fetch_json", return_value=(release, raw)) as fetch:
                self.assertEqual(apns.verified_notice(catalog, None, "zh-Hans")["tongxing"]["pageID"], "week")
                fetch.assert_called_once_with(apns.ORIGIN + target["releasePackageUrl"])

    def test_catalog_fallback_only_for_missing_v4(self):
        v4 = self.fixture()[0]
        v3 = self.fixture(False)[0]
        with patch.object(apns, "fetch_json", return_value=(v4, b"")) as fetch:
            self.assertEqual(apns.load_catalog(), v4)
            fetch.assert_called_once_with(apns.ORIGIN + "/multilingual-v4.json")
        missing = urllib.error.HTTPError("test", 404, "missing", {}, None)
        with patch.object(apns, "fetch_json", side_effect=[missing, (v3, b"")]) as fetch:
            self.assertEqual(apns.load_catalog(), v3)
            self.assertEqual(fetch.call_count, 2)
        for failure in (urllib.error.HTTPError("test", 503, "unavailable", {}, None), ValueError("bad JSON")):
            with patch.object(apns, "fetch_json", side_effect=failure) as fetch:
                with self.assertRaises(type(failure)):
                    apns.load_catalog()
                self.assertEqual(fetch.call_count, 1)
        with patch.object(apns, "fetch_json", return_value=(v3, b"")):
            with self.assertRaises(apns.TestValidationError):
                apns.load_catalog()

    def test_invalid_release_bindings_rejected(self):
        for field, value in (("status", "candidate"), ("schemaVersion", "sermon-target-language-release-package-v2"),
                             ("targetLocale", "ko"), ("pageId", "old-week"), ("contentStatus", "human_reviewed"),
                             ("httpVerification", {"status": "fail"})):
            catalog, target, release, _ = self.fixture()
            release[field] = value
            raw = json.dumps(release).encode()
            target["releasePackageJsonSha256"] = hashlib.sha256(raw).hexdigest()
            with patch.object(apns, "fetch_json", return_value=(release, raw)):
                with self.assertRaises(apns.TestValidationError):
                    apns.verified_notice(catalog, None, "zh-Hans")
        for field, value in (("releasePackageUrl", "/releases-v2/week/zh-Hans.json"),
                             ("releasePackageUrl", "/releases-v4/week/zh-Hans.json?x=1"),
                             ("releasePackageJsonSha256", "f" * 64)):
            catalog, target, release, raw = self.fixture()
            target[field] = value
            with patch.object(apns, "fetch_json", return_value=(release, raw)):
                with self.assertRaises(apns.TestValidationError):
                    apns.verified_notice(catalog, None, "zh-Hans")

    def test_dry_run_does_not_send(self):
        catalog, _, release, raw = self.fixture()
        with patch("sys.argv", [str(MODULE), "--key-file", "unused", "--key-id", "A" * 10,
                               "--team-id", "B" * 10, "--device", "unused"]), \
             patch.object(apns, "device_receipt", return_value=self.device()), \
             patch.object(apns, "load_catalog", return_value=catalog), \
             patch.object(apns, "fetch_json", return_value=(release, raw)), \
             patch.object(apns, "provider_token", return_value="private.jwt"), \
             patch.object(apns, "send") as send, patch("builtins.print"):
            self.assertEqual(apns.main(), 0)
            send.assert_not_called()

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
