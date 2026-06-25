import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from urllib.error import HTTPError

import scripts.run_deployed_webrtc_session_smoke as mod


class DeployedWebrtcSessionSmokeTest(unittest.TestCase):
    def test_creates_webrtc_session_without_reporting_secret_values(self):
        with patched_network() as calls:
            report = mod.run_smoke(args_for(internal_task_token="task-token"))

        self.assertEqual(report["status"], "ok")
        self.assertEqual(calls[0]["url"], "https://example.run.app/api/admin/realtime/sessions")
        self.assertEqual(calls[0]["method"], "POST")
        self.assertEqual(calls[0]["headers"]["X-internal-task-token"], "task-token")
        payload = json.loads(calls[0]["data"].decode("utf-8"))
        self.assertEqual(payload["model"], "gpt-realtime-translate")
        self.assertEqual(payload["targetLanguage"], "zh")
        self.assertEqual(payload["audioSourceKind"], "ipad_mic")
        self.assertTrue(report["realtimeSession"]["clientSecretReturned"])
        self.assertTrue(report["realtimeSession"]["eventTokenReturned"])
        rendered = json.dumps(report)
        self.assertNotIn("client-secret-value", rendered)
        self.assertNotIn("rt-event-token", rendered)
        self.assertFalse(report["clientSecretIncluded"])
        self.assertFalse(report["eventTokenIncluded"])

    def test_allows_admin_token_header(self):
        with patched_network() as calls:
            report = mod.run_smoke(args_for(admin_token="operator-token"))

        self.assertEqual(report["status"], "ok")
        self.assertEqual(calls[0]["headers"]["Authorization"], "Bearer operator-token")

    def test_fails_when_client_secret_is_missing(self):
        with patched_network(omit_client_secret=True):
            report = mod.run_smoke(args_for(internal_task_token="task-token"))

        self.assertEqual(report["status"], "failed")
        self.assertIn("create_webrtc_realtime_session", report["failedChecks"])
        self.assertIn("client_secret_returned_without_printing_value", report["failedChecks"])
        self.assertFalse(report["realtimeSession"]["clientSecretReturned"])

    def test_fails_on_old_translation_calls_url(self):
        with patched_network(webrtc_url="https://api.openai.com/v1/realtime/translations/calls"):
            report = mod.run_smoke(args_for(internal_task_token="task-token"))

        self.assertEqual(report["status"], "failed")
        self.assertIn("webrtc_calls_url", report["failedChecks"])

    def test_fails_cleanly_on_http_error(self):
        with patched_network(http_status=401):
            report = mod.run_smoke(args_for(internal_task_token="bad-token"))

        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["realtimeSession"]["httpStatus"], 401)
        self.assertEqual(report["realtimeSession"]["error"], "unauthorized")
        self.assertNotIn("bad-token", json.dumps(report))

    def test_main_writes_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.json"
            with patched_network():
                with unittest.mock.patch(
                    "sys.argv",
                    [
                        "run_deployed_webrtc_session_smoke.py",
                        "--base-url",
                        "https://example.run.app",
                        "--sunday",
                        "2026-06-28",
                        "--internal-task-token",
                        "task-token",
                        "--out",
                        str(out),
                    ],
                ):
                    exit_code = mod.main()

            written = json.loads(out.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(written["status"], "ok")
        self.assertNotIn("client-secret-value", json.dumps(written))


def args_for(admin_token=None, internal_task_token=None):
    return Namespace(
        base_url="https://example.run.app",
        sunday="2026-06-28",
        admin_token=admin_token,
        internal_task_token=internal_task_token,
        timeout_seconds=20,
        out=None,
    )


class FakeResponse:
    def __init__(self, *, body, status=201, content_type="application/json"):
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
    def __init__(
        self,
        *,
        http_status=201,
        omit_client_secret=False,
        webrtc_url="https://api.openai.com/v1/realtime/calls",
    ):
        self.http_status = http_status
        self.omit_client_secret = omit_client_secret
        self.webrtc_url = webrtc_url
        self.calls = []
        self.original_urlopen = mod.urlopen

    def __enter__(self):
        def fake_urlopen(request, timeout):
            headers = dict(getattr(request, "header_items", lambda: [])())
            self.calls.append(
                {
                    "url": request.full_url,
                    "method": request.get_method(),
                    "headers": headers,
                    "data": request.data,
                }
            )
            if self.http_status >= 400:
                raise HTTPError(
                    request.full_url,
                    self.http_status,
                    "unauthorized",
                    {"Content-Type": "application/json"},
                    FakeErrorBody(json.dumps({"error": "unauthorized"}).encode("utf-8")),
                )
            body = {
                "status": "ready",
                "sessionId": "rt_test",
                "eventToken": "rt-event-token",
                "model": "gpt-realtime-translate",
                "targetLanguage": "zh",
                "audioSourceKind": "ipad_mic",
                "clientSecret": {
                    "value": "client-secret-value",
                    "expiresAt": 1893456000,
                },
                "webrtc": {
                    "url": self.webrtc_url,
                    "model": "gpt-realtime-translate",
                },
            }
            if self.omit_client_secret:
                body["clientSecret"] = {}
            return FakeResponse(body=json.dumps(body), status=self.http_status)

        mod.urlopen = fake_urlopen
        return self.calls

    def __exit__(self, exc_type, exc, tb):
        mod.urlopen = self.original_urlopen
        return False


class FakeErrorBody:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body

    def close(self):
        return None


if __name__ == "__main__":
    unittest.main()
