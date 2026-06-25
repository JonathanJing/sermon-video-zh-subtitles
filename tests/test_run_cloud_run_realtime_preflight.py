import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import scripts.run_cloud_run_realtime_preflight as mod


class CloudRunRealtimePreflightTest(unittest.TestCase):
    def test_read_only_preflight_passes_with_warning_when_session_creation_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "cloud-run-config.json"
            config.write_text(json.dumps({"status": "ok", "cloudRun": {"maxInstances": 1}}), encoding="utf-8")

            with patched_network() as calls:
                report = mod.run_preflight(args_for(config_report=config))

        self.assertEqual(report["status"], "ok")
        self.assertIn("realtime_local_session_create", report["warnings"])
        self.assertEqual([call["method"] for call in calls], ["GET", "GET", "GET", "GET"])
        self.assertFalse(report["apiKeyMaterialIncluded"])
        self.assertFalse(report["secretResourceNamesIncluded"])
        self.assertFalse(report["eventTokenIncluded"])

    def test_can_create_realtime_session_without_reporting_event_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "cloud-run-config.json"
            config.write_text(json.dumps({"status": "ok", "cloudRun": {"maxInstances": 1}}), encoding="utf-8")

            with patched_network() as calls:
                report = mod.run_preflight(
                    args_for(
                        config_report=config,
                        create_realtime_session=True,
                        admin_token="operator-token",
                    )
                )

        self.assertEqual(report["status"], "ok")
        self.assertNotIn("realtime_local_session_create", report["warnings"])
        self.assertEqual(calls[-1]["method"], "POST")
        self.assertEqual(calls[-1]["headers"]["Authorization"], "Bearer operator-token")
        self.assertEqual(report["realtimeSession"]["targetLanguage"], "zh")
        self.assertEqual(report["realtimeSession"]["audioSourceKind"], "ipad_mic")
        self.assertTrue(report["realtimeSession"]["eventTokenReturned"])
        self.assertNotIn("rt-event-token", json.dumps(report))

    def test_fails_when_realtime_session_metadata_is_missing(self):
        with patched_network(omit_audio_source_kind=True):
            report = mod.run_preflight(
                args_for(
                    create_realtime_session=True,
                    internal_task_token="task-token",
                )
            )

        self.assertEqual(report["status"], "failed")
        self.assertIn("realtime_local_session_create", report["failedChecks"])
        self.assertIn("realtime_local_session_metadata", report["failedChecks"])
        self.assertIsNone(report["realtimeSession"]["audioSourceKind"])

    def test_fails_when_health_is_not_ok(self):
        with patched_network(health_status="degraded"):
            report = mod.run_preflight(args_for())

        self.assertEqual(report["status"], "failed")
        self.assertIn("api_health", report["failedChecks"])

    def test_detects_secret_material_in_http_responses(self):
        with patched_network(root_body="<html>sk-testsecretsecret</html>"):
            report = mod.run_preflight(args_for())

        self.assertEqual(report["status"], "failed")
        self.assertIn("no_secret_material_in_http_responses", report["failedChecks"])


def args_for(config_report=None, create_realtime_session=False, admin_token=None, internal_task_token=None):
    return Namespace(
        base_url="https://example.run.app",
        cloud_run_config_report=config_report,
        sunday="current",
        admin_token=admin_token,
        internal_task_token=internal_task_token,
        create_realtime_session=create_realtime_session,
        timeout_seconds=20,
        out=None,
    )


class FakeResponse:
    def __init__(self, *, body, status=200, content_type="application/json"):
        self.body = body.encode("utf-8")
        self.status = status
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.body


class patched_network:
    def __init__(self, *, health_status="ok", root_body="<html>ok</html>", omit_audio_source_kind=False):
        self.health_status = health_status
        self.root_body = root_body
        self.omit_audio_source_kind = omit_audio_source_kind
        self.calls = []
        self.original_urlopen = mod.urlopen

    def __enter__(self):
        def fake_urlopen(request, timeout):
            url = getattr(request, "full_url", request)
            method = getattr(request, "get_method", lambda: "GET")()
            headers = dict(getattr(request, "header_items", lambda: [])())
            self.calls.append({"url": url, "method": method, "headers": headers})
            if url.endswith("/"):
                return FakeResponse(body=self.root_body, content_type="text/html")
            if url.endswith("/api/health"):
                return FakeResponse(body=json.dumps({"status": self.health_status}))
            if url.endswith("/api/sundays/current"):
                return FakeResponse(
                    body=json.dumps(
                        {
                            "sunday": "2026-06-28",
                            "translationStatus": "ready",
                            "artifactCount": 3,
                            "readiness": {"state": "published"},
                        }
                    )
                )
            if url.endswith("/api/admin/status"):
                return FakeResponse(
                    body=json.dumps(
                        {
                            "status": "ok",
                            "service": {"health": "ok"},
                            "artifact": {"bucket": "bucket"},
                            "secrets": {
                                "openaiApiKey": "configured",
                                "operatorAdminToken": "configured",
                                "internalTaskToken": "configured",
                            },
                            "realtime": {
                                "eventArchive": {
                                    "enabled": True,
                                    "gcsMirrorEnabled": True,
                                }
                            },
                        }
                    )
                )
            if url.endswith("/api/admin/realtime/local-sessions"):
                session_body = {
                    "status": "ready",
                    "sessionId": "rt_test",
                    "eventToken": "rt-event-token",
                    "model": "gpt-realtime-translate",
                    "targetLanguage": "zh",
                    "audioSourceKind": "ipad_mic",
                    "webrtc": None,
                }
                if self.omit_audio_source_kind:
                    session_body.pop("audioSourceKind")
                return FakeResponse(
                    body=json.dumps(session_body),
                    status=201,
                )
            raise AssertionError(f"unexpected URL: {url}")

        mod.urlopen = fake_urlopen
        return self.calls

    def __exit__(self, exc_type, exc, tb):
        mod.urlopen = self.original_urlopen
        return False


if __name__ == "__main__":
    unittest.main()
