import unittest

from scripts import post_live_run_status as mod


class PostLiveRunStatusTest(unittest.TestCase):
    def test_idempotent_stage_lifecycle_and_attempts(self):
        status = mod.new_status("2026-07-19", source_url="https://youtu.be/test")
        status = mod.update_stage(status, "2026-07-19", "downloaded", "running")
        status = mod.update_stage(status, "2026-07-19", "downloaded", "blocked", reason="auth")
        status = mod.update_stage(status, "2026-07-19", "downloaded", "running")
        status = mod.update_stage(status, "2026-07-19", "downloaded", "complete", duration_seconds=12.5)

        self.assertEqual(status["stages"]["downloaded"]["attempts"], 2)
        self.assertEqual(status["stages"]["downloaded"]["durationSeconds"], 12.5)
        self.assertIsNone(status["blocker"])


if __name__ == "__main__":
    unittest.main()
