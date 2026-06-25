import unittest

from backend.config import AppConfig
from backend.worker import GenerationRequest, build_generation_command, build_generation_plan


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

    def test_build_generation_plan_runs_prepare_translate_notes_and_promote(self):
        plan = build_generation_plan(
            GenerationRequest(
                sunday="2026-06-28",
                live_url="https://www.youtube.com/watch?v=abc123",
                session_id="test-session",
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

        self.assertEqual(plan.session_id, "test-session")
        self.assertEqual(plan.prefix, "sundays/2026-06-28/runs/test-session")
        self.assertEqual(len(plan.commands), 5)
        joined_commands = [" ".join(command) for command in plan.commands]
        self.assertIn("prepare_live_link_playback.py", joined_commands[0])
        self.assertIn("translate_playback_with_openai.py", joined_commands[1])
        self.assertIn("gcloud storage cp", joined_commands[2])
        self.assertIn("web/playback-simulation.generated.js", joined_commands[2])
        self.assertIn("generate_notes_with_openai.py", joined_commands[3])
        self.assertIn("--model gpt-5.5-mini", joined_commands[3])
        self.assertIn("--reasoning-effort medium", joined_commands[3])
        self.assertIn("insights", joined_commands[3])
        self.assertIn("promote_sunday_manifest.py", joined_commands[4])
        self.assertIn("sundays/2026-06-28/runs/test-session/artifacts/cloud-manifest.json", joined_commands[4])
        self.assertIn("--gcs-prefix sundays", joined_commands[4])


if __name__ == "__main__":
    unittest.main()
