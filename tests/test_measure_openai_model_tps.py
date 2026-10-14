import io
import os
from contextlib import redirect_stderr
from unittest import mock
import unittest

from scripts import measure_openai_model_tps as tps


class TimingMetricsTests(unittest.TestCase):
    def test_rates_use_end_to_end_and_first_content_windows(self):
        usage = {"completion_tokens": 300, "prompt_tokens": 50,
                 "completion_tokens_details": {"reasoning_tokens": 100}}
        metrics = tps.timing_metrics(usage, start=10.0, first_event=11.0,
                                     first_content=12.0, end=22.0)
        self.assertEqual(metrics["totalS"], 12.0)
        self.assertEqual(metrics["ttftS"], 2.0)
        self.assertEqual(metrics["genS"], 10.0)
        self.assertEqual(metrics["timingBasis"], "first_content")
        self.assertEqual(metrics["outputTpsEndToEnd"], 25.0)
        self.assertEqual(metrics["outputTpsGeneration"], 30.0)
        self.assertEqual(metrics["reasoningTokens"], 100)

    def test_falls_back_to_first_event_without_content(self):
        usage = {"completion_tokens": 40}
        metrics = tps.timing_metrics(usage, start=0.0, first_event=1.0,
                                     first_content=None, end=5.0)
        self.assertEqual(metrics["timingBasis"], "first_event")
        self.assertEqual(metrics["outputTpsGeneration"], 10.0)

    def test_missing_usage_yields_no_rates(self):
        metrics = tps.timing_metrics(None, start=0.0, first_event=None,
                                     first_content=None, end=3.0)
        self.assertIsNone(metrics["outputTpsEndToEnd"])
        self.assertIsNone(metrics["outputTpsGeneration"])
        self.assertIsNone(metrics["timingBasis"])


class SummarizeTests(unittest.TestCase):
    def test_counts_failures_and_medians_only_successful_calls(self):
        rows = [
            {"requestedTier": "fast", "outcome": "ok", "completionTokens": 100, "ttftS": 1.0,
             "totalS": 4.0, "reasoningTokens": 10, "outputTpsEndToEnd": 25.0,
             "outputTpsGeneration": 30.0, "appliedServiceTier": "priority"},
            {"requestedTier": "fast", "outcome": "ok", "completionTokens": 200, "ttftS": 3.0,
             "totalS": 8.0, "reasoningTokens": 20, "outputTpsEndToEnd": 25.0,
             "outputTpsGeneration": 50.0, "appliedServiceTier": "priority"},
            {"requestedTier": "fast", "outcome": "http_error", "completionTokens": None,
             "ttftS": None, "totalS": 0.1, "reasoningTokens": None, "outputTpsEndToEnd": None,
             "outputTpsGeneration": None, "appliedServiceTier": None},
            {"requestedTier": "default", "outcome": "ok", "completionTokens": 100, "ttftS": 2.0,
             "totalS": 10.0, "reasoningTokens": 10, "outputTpsEndToEnd": 10.0,
             "outputTpsGeneration": 12.5, "appliedServiceTier": "default"},
        ]
        summary = tps.summarize(rows, ("default", "fast"))
        self.assertEqual(summary["fast"]["ok"], 2)
        self.assertEqual(summary["fast"]["notOk"], 1)
        self.assertEqual(summary["fast"]["medianOutputTpsGeneration"], 40.0)
        self.assertEqual(summary["fast"]["appliedServiceTiers"], ["priority"])
        self.assertEqual(summary["default"]["medianOutputTpsEndToEnd"], 10.0)


class RouteGuardTests(unittest.TestCase):
    def test_refuses_without_selected_dev_route(self):
        env = {k: v for k, v in os.environ.items() if k != "SERMON_OPENAI_ENVIRONMENT"}
        with mock.patch.dict(os.environ, env, clear=True), redirect_stderr(io.StringIO()):
            self.assertEqual(tps.main(["--rounds", "1"]), 2)

    def test_refuses_prod_route(self):
        env = {"SERMON_OPENAI_ENVIRONMENT": "prod", "OPENAI_PROJECT_ID": "proj_prod_test",
               "SERMON_OPENAI_CREDENTIAL_ALIAS": "tongxing-prod-runtime", "OPENAI_API_KEY": "x"}
        with mock.patch.dict(os.environ, env, clear=True), redirect_stderr(io.StringIO()):
            self.assertEqual(tps.main(["--rounds", "1"]), 2)

    def test_rejects_round_count_out_of_bounds(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            tps.parse_args(["--rounds", "6"])


if __name__ == "__main__":
    unittest.main()
