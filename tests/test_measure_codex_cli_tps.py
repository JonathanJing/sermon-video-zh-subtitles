from pathlib import Path
import unittest

from scripts import measure_codex_cli_tps as cli


class CliEnvironmentTests(unittest.TestCase):
    def test_strips_every_openai_credential_variable(self):
        env = cli.cli_environment({"OPENAI_API_KEY": "k", "OPENAI_PROJECT_ID": "p",
                                   "CODEX_API_KEY": "c", "HOME": "/h", "PATH": "/bin"})
        self.assertEqual(env, {"HOME": "/h", "PATH": "/bin"})


class CommandTests(unittest.TestCase):
    def test_default_and_fast_commands_match_transport_shape(self):
        default = cli.build_command(Path("/c"), "gpt-6-luna", "default", "medium")
        fast = cli.build_command(Path("/c"), "gpt-6-luna", "fast", "medium")
        self.assertIn('service_tier="default"', default)
        self.assertNotIn("--enable", default)
        self.assertIn('service_tier="fast"', fast)
        self.assertEqual(fast[-2:], ["--enable", "fast_mode"])
        self.assertIn('model_reasoning_effort="medium"', fast)
        self.assertIn("--ephemeral", fast)


class ParseEventsTests(unittest.TestCase):
    def test_turn_and_first_message_timings_from_arrival_times(self):
        rows = [(0.5, {"type": "thread.started"}), (1.0, {"type": "turn.started"}),
                (4.0, {"type": "item.completed", "item": {"type": "agent_message", "text": "x"}}),
                (6.0, {"type": "turn.completed", "usage": {"output_tokens": 300}})]
        parsed = cli.parse_events(rows)
        self.assertEqual(parsed["turnS"], 5.0)
        self.assertEqual(parsed["firstMessageS"], 4.0)
        self.assertEqual(parsed["toolItems"], 0)
        self.assertTrue(parsed["completed"])

    def test_tool_items_and_failures_are_flagged(self):
        rows = [(1.0, {"type": "turn.started"}),
                (2.0, {"type": "item.completed", "item": {"type": "command_execution"}}),
                (3.0, {"type": "turn.failed"})]
        parsed = cli.parse_events(rows)
        self.assertEqual(parsed["toolItems"], 1)
        self.assertTrue(parsed["turnFailed"])
        self.assertFalse(parsed["completed"])


class RateTests(unittest.TestCase):
    def test_wall_and_turn_rates(self):
        usage = {"input_tokens": 14000, "cached_input_tokens": 1000, "output_tokens": 300,
                 "reasoning_output_tokens": 80}
        out = cli.rates(usage, wall_s=10.0, turn_s=5.0)
        self.assertEqual(out["outputTpsWall"], 30.0)
        self.assertEqual(out["outputTpsTurn"], 60.0)
        self.assertEqual(out["reasoningTokens"], 80)

    def test_no_usage_gives_no_rates(self):
        self.assertIsNone(cli.rates(None, 10.0, 5.0)["outputTpsWall"])


if __name__ == "__main__":
    unittest.main()
