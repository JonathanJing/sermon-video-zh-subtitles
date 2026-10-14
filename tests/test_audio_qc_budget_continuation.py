"""A QC continuation reads old returned calls and charges only a new missing judge call."""
import json
from pathlib import Path
import unittest

from scripts import run_audio_qc_budget_continuation as continuation
from scripts import run_machine_qc_clip_test as driver
from tests import test_run_start_tools as fixtures


SCHEMA = {"type": "object", "properties": {"status": {"type": "string"}},
          "required": ["status"], "additionalProperties": False}


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.PlanTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.paths = {key: str(self.fixture.base / name) for key, name in
                      (("source", "source.json"), ("anchor", "anchor.json"), ("policy", "ko.json"))}

    def judge(self, name):
        stage = self.fixture.load(name)["stages"][0]
        return driver.api_judge_for_resolved(Path(stage["authorization"]),
                                             {"ko": self.paths}, requested_locales=["ko"])

    def test_prior_returned_call_is_free_and_only_missing_call_uses_new_authority(self):
        self.assertEqual(fixtures.run_plan(*self.fixture.args("prior"))[0], 0)
        prior = self.judge("prior")
        calls = {"prior": 0, "current": 0}

        def transport(which):
            def answer(*_):
                calls[which] += 1
                return {"model": "gpt-6.1-sol", "choices": [{"finish_reason": "stop",
                        "message": {"content": '{"status":"pass"}'}}],
                        "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}}
            return answer

        prior.ledger.transport = transport("prior")
        self.assertEqual(prior("judge", "Review", "already returned", SCHEMA), {"status": "pass"})
        self.assertEqual(fixtures.run_plan(*self.fixture.args("current"))[0], 0)
        current = self.judge("current")
        current.ledger.transport = transport("current")
        routed = continuation.RoutedJudge(prior, current)
        self.assertEqual(routed.cached("judge", "Review", "already returned", SCHEMA), {"status": "pass"})
        self.assertIsNone(routed.cached("judge", "Review", "new call", SCHEMA))
        self.assertEqual(routed("judge", "Review", "new call", SCHEMA), {"status": "pass"})
        self.assertEqual(calls, {"prior": 1, "current": 1})
        self.assertEqual(routed.ledger.root, current.ledger.root)
        old_rows = json.loads((prior.ledger.root / "source-budget.json").read_text())["requests"]
        new_rows = json.loads((current.ledger.root / "source-budget.json").read_text())["requests"]
        self.assertEqual(len(old_rows), len(new_rows))
        self.assertNotEqual(set(old_rows), set(new_rows))

    def test_changed_judge_identity_refuses_routing(self):
        self.assertEqual(fixtures.run_plan(*self.fixture.args("prior"))[0], 0)
        self.assertEqual(fixtures.run_plan(*self.fixture.args("current"))[0], 0)
        prior, current = self.judge("prior"), self.judge("current")
        current.identity = {**current.identity, "backend": "other"}
        with self.assertRaisesRegex(ValueError, "identity_changed"):
            continuation.RoutedJudge(prior, current)


if __name__ == "__main__":
    unittest.main()
