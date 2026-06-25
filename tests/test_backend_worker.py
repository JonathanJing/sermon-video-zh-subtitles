import unittest

from backend.config import AppConfig
from backend.worker import (
    GenerationRequest,
    build_generation_command,
    build_generation_plan,
    parse_generation_request,
)


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
        self.assertIn("--asr-model gpt-4o-transcribe", joined)
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

    def test_build_generation_plan_runs_caption_publish_before_optional_notes(self):
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
        self.assertEqual(len(plan.commands), 8)
        joined_commands = [" ".join(command) for command in plan.commands]
        self.assertIn("run_openai_model_access_preflight.py", joined_commands[0])
        self.assertIn("--model gpt-5.4-mini", joined_commands[0])
        self.assertIn("model-output/openai-model-access-preflight.json", joined_commands[0])
        self.assertIn("prepare_live_link_playback.py", joined_commands[1])
        self.assertIn("--asr-model gpt-4o-transcribe", joined_commands[1])
        self.assertIn("translate_playback_with_openai.py", joined_commands[2])
        self.assertIn("--model gpt-5.4-mini", joined_commands[2])
        self.assertIn("export_playback_captions.py", joined_commands[3])
        self.assertIn("--stem sermon.zh.live-aligned", joined_commands[3])
        self.assertIn("--manifest", joined_commands[3])
        self.assertIn("artifacts/cloud-manifest.json", joined_commands[3])
        self.assertIn("validate_offline_chain.py", joined_commands[4])
        self.assertIn("--expected-asr-model gpt-4o-transcribe", joined_commands[4])
        self.assertIn("--expected-translation-model gpt-5.4-mini", joined_commands[4])
        self.assertIn("sermon.zh.live-aligned.vtt", joined_commands[4])
        self.assertIn("sermon.zh.live-aligned.srt", joined_commands[4])
        self.assertIn("gcloud storage cp", joined_commands[5])
        self.assertIn("web/playback-simulation.generated.js", joined_commands[5])
        self.assertIn("gcloud storage cp", joined_commands[6])
        self.assertIn("artifacts/cloud-manifest.json", joined_commands[6])
        self.assertIn("promote_sunday_manifest.py", joined_commands[7])
        self.assertIn("sundays/2026-06-28/runs/test-session/artifacts/cloud-manifest.json", joined_commands[7])
        self.assertIn("--gcs-prefix sundays", joined_commands[7])
        self.assertIn("--source-mode youtube-live-archive", joined_commands[7])
        self.assertIn("--readiness-state published", joined_commands[7])
        self.assertIn("--offline-asr-model gpt-4o-transcribe", joined_commands[7])
        self.assertIn("--offline-translation-model gpt-5.4-mini", joined_commands[7])
        self.assertIn("--realtime-draft-model gpt-realtime-translate", joined_commands[7])
        self.assertIn("--stable-correction-model gpt-5.4-mini", joined_commands[7])
        self.assertNotIn("generate_notes_with_openai.py", " ".join(joined_commands))

    def test_build_generation_plan_can_include_insights_after_caption_publish(self):
        plan = build_generation_plan(
            GenerationRequest(
                sunday="2026-06-28",
                live_url="https://www.youtube.com/watch?v=abc123",
                session_id="test-session",
                include_insights=True,
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

        joined_commands = [" ".join(command) for command in plan.commands]

        self.assertEqual(len(plan.commands), 9)
        self.assertIn("promote_sunday_manifest.py", joined_commands[7])
        self.assertIn("generate_notes_with_openai.py", joined_commands[8])
        self.assertIn("--model gpt-5.4-mini", joined_commands[8])
        self.assertIn("--reasoning-effort medium", joined_commands[8])
        self.assertIn("insights", joined_commands[8])

    def test_parse_generation_request_accepts_include_insights(self):
        request = parse_generation_request(
            {
                "liveUrl": "https://www.youtube.com/watch?v=abc123",
                "includeInsights": True,
            },
            "2026-06-28",
        )

        self.assertTrue(request.include_insights)

    def test_build_generation_plan_can_replay_saved_translation_jsonl(self):
        plan = build_generation_plan(
            GenerationRequest(
                sunday="2026-06-28",
                live_url="https://www.youtube.com/watch?v=abc123",
                session_id="test-session",
                translations_jsonl="/tmp/sermon-worker/2026-06-28/test-session/model-output/openai-translation-output.jsonl",
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

        joined_commands = [" ".join(command) for command in plan.commands]

        self.assertEqual(len(plan.commands), 7)
        self.assertNotIn("run_openai_model_access_preflight.py", " ".join(joined_commands))
        self.assertIn("translate_playback_with_openai.py", joined_commands[1])
        self.assertIn("--translations-jsonl /tmp/sermon-worker/2026-06-28/test-session/model-output/openai-translation-output.jsonl", joined_commands[1])
        self.assertNotIn("--api-key-secret", joined_commands[1])
        self.assertIn("promote_sunday_manifest.py", joined_commands[6])

    def test_parse_generation_request_accepts_translations_jsonl(self):
        request = parse_generation_request(
            {
                "liveUrl": "https://www.youtube.com/watch?v=abc123",
                "translationsJsonl": "/tmp/saved.jsonl",
            },
            "2026-06-28",
        )

        self.assertEqual(request.translations_jsonl, "/tmp/saved.jsonl")


if __name__ == "__main__":
    unittest.main()
