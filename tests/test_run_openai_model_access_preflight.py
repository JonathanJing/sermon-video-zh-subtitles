import importlib.util
import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_openai_model_access_preflight.py"
SPEC = importlib.util.spec_from_file_location("run_openai_model_access_preflight", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self.payload = payload if payload is not None else {}
        self.text = text

    def json(self):
        return self.payload


class OpenAIModelAccessPreflightTest(unittest.TestCase):
    def args_for(self, **overrides):
        return Namespace(
            api_key_secret=overrides.get(
                "api_key_secret",
                "projects/p/secrets/openai-api-key/versions/latest",
            ),
            cloud_run_service=overrides.get("cloud_run_service"),
            project=overrides.get("project"),
            region=overrides.get("region"),
            api_key_env=overrides.get("api_key_env", "OPENAI_API_KEY_SECRET"),
            models=overrides.get("models", ["gpt-5.4-mini"]),
            out=overrides.get("out"),
        )

    def test_model_access_ok(self):
        original_access_secret = mod.access_secret
        original_post = mod.requests.post
        calls = []
        try:
            mod.access_secret = lambda secret: "sk-test"

            def fake_post(url, headers, json, timeout):
                calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
                return FakeResponse(
                    200,
                    {
                        "output": [
                            {
                                "type": "message",
                                "content": [{"type": "output_text", "text": "{\"ok\":true}"}],
                            }
                        ]
                    },
                )

            mod.requests.post = fake_post

            report = mod.run_preflight(self.args_for())
        finally:
            mod.access_secret = original_access_secret
            mod.requests.post = original_post

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["failedChecks"], [])
        self.assertEqual(calls[0]["url"], mod.OPENAI_RESPONSES_URL)
        self.assertEqual(calls[0]["json"]["model"], "gpt-5.4-mini")
        self.assertIn("input", calls[0]["json"])
        self.assertNotIn("messages", calls[0]["json"])
        self.assertEqual(report["checks"][1]["observed"]["endpoint"], "responses")
        self.assertFalse(report["apiKeyMaterialIncluded"])
        self.assertFalse(report["secretResourceNamesIncluded"])

    def test_model_access_404_is_failed_and_sanitized(self):
        original_access_secret = mod.access_secret
        original_post = mod.requests.post
        try:
            mod.access_secret = lambda secret: "sk-test"
            mod.requests.post = lambda *args, **kwargs: FakeResponse(
                404,
                {"error": {"message": "The model `gpt-5.4-mini` does not exist or you do not have access to it."}},
            )

            report = mod.run_preflight(self.args_for())
        finally:
            mod.access_secret = original_access_secret
            mod.requests.post = original_post

        self.assertEqual(report["status"], "failed")
        self.assertIn("responses_model:gpt-5.4-mini", report["failedChecks"])
        observed = report["checks"][1]["observed"]
        self.assertEqual(observed["httpStatus"], 404)
        self.assertEqual(observed["endpoint"], "responses")
        self.assertEqual(observed["failureKind"], "model_unavailable_or_not_found")
        self.assertNotIn("sk-test", json.dumps(report))
        self.assertNotIn("openai-api-key", json.dumps(report))

    def test_cloud_run_secret_source_uses_env_value_without_reporting_resource(self):
        original_load_service = mod.load_cloud_run_service
        original_access_secret = mod.access_secret
        original_post = mod.requests.post
        accessed = []
        try:
            mod.load_cloud_run_service = lambda **kwargs: {
                "spec": {
                    "template": {
                        "spec": {
                            "containers": [
                                {
                                    "env": [
                                        {
                                            "name": "OPENAI_API_KEY_SECRET",
                                            "value": "projects/p/secrets/openai-api-key/versions/latest",
                                        }
                                    ]
                                }
                            ]
                        }
                    }
                }
            }

            def fake_access_secret(secret):
                accessed.append(secret)
                return "sk-test"

            mod.access_secret = fake_access_secret
            mod.requests.post = lambda *args, **kwargs: FakeResponse(200, {"output_text": "{\"ok\":true}"})

            report = mod.run_preflight(
                self.args_for(
                    api_key_secret=None,
                    cloud_run_service="sermon-zh-caption-web",
                    project="ai-for-god",
                    region="us-west1",
                )
            )
        finally:
            mod.load_cloud_run_service = original_load_service
            mod.access_secret = original_access_secret
            mod.requests.post = original_post

        self.assertEqual(report["status"], "ok")
        self.assertEqual(accessed, ["projects/p/secrets/openai-api-key/versions/latest"])
        rendered = json.dumps(report)
        self.assertNotIn("openai-api-key", rendered)
        self.assertNotIn("sk-test", rendered)

    def test_model_access_failure_kind_classification(self):
        self.assertEqual(
            mod.classify_model_access_failure(400, "The requested model does not exist."),
            "model_unavailable_or_not_found",
        )
        self.assertEqual(mod.classify_model_access_failure(403, "permission denied"), "auth_or_permission_denied")
        self.assertEqual(mod.classify_model_access_failure(429, "too many requests"), "rate_limited")
        self.assertEqual(mod.classify_model_access_failure(503, "service unavailable"), "provider_server_error")

    def test_secret_access_failure_is_failed_and_sanitized(self):
        original_access_secret = mod.access_secret
        try:
            mod.access_secret = lambda secret: (_ for _ in ()).throw(
                RuntimeError("bad sk-secret at projects/p/secrets/openai-api-key/versions/latest")
            )

            report = mod.run_preflight(self.args_for())
        finally:
            mod.access_secret = original_access_secret

        self.assertEqual(report["status"], "failed")
        rendered = json.dumps(report)
        self.assertIn("api_key_secret_access", report["failedChecks"])
        self.assertNotIn("sk-secret", rendered)
        self.assertNotIn("openai-api-key", rendered)

    def test_main_writes_report(self):
        original_access_secret = mod.access_secret
        original_post = mod.requests.post
        try:
            mod.access_secret = lambda secret: "sk-test"
            mod.requests.post = lambda *args, **kwargs: FakeResponse(
                200,
                {"output_text": "{\"ok\":true}"},
            )
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "report.json"
                code = mod.run_and_write(self.args_for(out=out))
                written = json.loads(out.read_text())
        finally:
            mod.access_secret = original_access_secret
            mod.requests.post = original_post

        self.assertEqual(code, 0)
        self.assertEqual(written["status"], "ok")


if __name__ == "__main__":
    unittest.main()
