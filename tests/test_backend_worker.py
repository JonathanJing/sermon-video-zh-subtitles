import unittest

from backend.config import AppConfig
from backend.worker import GenerationRequest, build_generation_command


class BackendWorkerTest(unittest.TestCase):
    def test_build_generation_command_uses_sunday_run_prefix_and_secret_reference(self):
        command = build_generation_command(
            GenerationRequest(
                sunday="2026-06-28",
                live_url="https://www.youtube.com/watch?v=abc123",
                session_id="test-session",
                dry_run_gcs=True,
            ),
            AppConfig(
                artifact_bucket="sermon-zh-artifacts-ai-for-god",
                artifact_prefix="sundays",
                current_manifest_uri=None,
                sunday_manifest_uri_template=None,
                timezone="America/Los_Angeles",
                openai_api_key_secret="projects/p/secrets/openai-api-key/versions/latest",
                operator_admin_token=None,
                internal_task_token=None,
                enable_inline_worker=False,
            ),
        )

        joined = " ".join(command)
        self.assertIn("--gcs-bucket sermon-zh-artifacts-ai-for-god", joined)
        self.assertIn("--gcs-prefix sundays/2026-06-28/runs/test-session", joined)
        self.assertIn("projects/p/secrets/openai-api-key/versions/latest", joined)
        self.assertIn("--gcs-dry-run", command)
        self.assertNotIn("sk-", joined)

    def test_requires_bucket_and_secret_reference(self):
        config = AppConfig(
            artifact_bucket=None,
            artifact_prefix="sundays",
            current_manifest_uri=None,
            sunday_manifest_uri_template=None,
            timezone="America/Los_Angeles",
            openai_api_key_secret=None,
            operator_admin_token=None,
            internal_task_token=None,
            enable_inline_worker=False,
        )

        with self.assertRaises(ValueError):
            build_generation_command(
                GenerationRequest(
                    sunday="2026-06-28",
                    live_url="https://www.youtube.com/watch?v=abc123",
                ),
                config,
            )


if __name__ == "__main__":
    unittest.main()
