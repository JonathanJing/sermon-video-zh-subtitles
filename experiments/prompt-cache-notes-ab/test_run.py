import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("run.py")
SPEC = importlib.util.spec_from_file_location("prompt_cache_notes_ab", MODULE_PATH)
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)


class PromptCacheNotesABTests(unittest.TestCase):
    def test_arms_use_identical_notes_input_and_only_change_cache_mode(self):
        for index in range(len(subject.TOPICS)):
            pair = subject.request_pair(index)
            self.assertEqual(pair["implicit"], {
                key: value for key, value in pair["explicit_no_breakpoint"].items()
                if key != "prompt_cache_options"})
            self.assertEqual(pair["explicit_no_breakpoint"]["prompt_cache_options"],
                             {"mode": "explicit"})
            self.assertEqual(pair["implicit"]["model"], subject.MODEL)
            self.assertEqual(pair["implicit"]["reasoning"], {"effort": "high"})
            self.assertEqual(pair["implicit"]["max_output_tokens"], 512)

    def test_cost_uses_reported_reads_and_writes(self):
        usage = {"input_tokens": 2000,
                 "input_tokens_details": {"cached_tokens": 500,
                                          "cache_write_tokens": 1000}}
        self.assertEqual(subject.estimated_input_usd(usage), 0.0072)
        self.assertIsNone(subject.estimated_input_usd({"input_tokens": 2000}))

    def test_summary_keeps_missing_usage_unknown(self):
        report = subject.summarize_result({
            "planSha256": "test", "attempts": [
                {"arm": "implicit", "usage": {"input_tokens": 123},
                 "estimatedInputUsd": None, "responseStatus": "completed"},
            ],
        })
        implicit = report["byArm"]["implicit"]
        self.assertEqual(implicit["inputTokens"], 123)
        self.assertIsNone(implicit["cachedTokens"])
        self.assertIsNone(implicit["cacheWriteTokens"])
        self.assertIsNone(implicit["estimatedInputUsd"])


if __name__ == "__main__":
    unittest.main()
