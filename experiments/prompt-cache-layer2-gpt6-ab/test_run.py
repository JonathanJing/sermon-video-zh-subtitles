import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("prompt_cache_layer2_gpt6_ab",
                                              Path(__file__).with_name("run.py"))
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)


class PromptCacheLayer2GPT6ABTests(unittest.TestCase):
    def test_actual_runner_payloads_keep_semantics_across_arms(self):
        by_role = subject.payloads()
        self.assertEqual(len(subject.plan(by_role)), 10)
        for role, model in subject.MODELS.items():
            for current, candidate in zip(by_role[role]["current_order"],
                                          by_role[role]["stable_first"]):
                self.assertEqual(current["model"], model)
                self.assertEqual(candidate["model"], model)
                self.assertEqual(current["messages"][0], candidate["messages"][0])
                self.assertEqual(json.loads(current["messages"][1]["content"]),
                                 json.loads(candidate["messages"][1]["content"]))
                self.assertEqual(list(json.loads(candidate["messages"][1]["content"]))[:4],
                                 list(subject.STABLE_KEYS))
        for role in subject.MODELS:
            repeat = [step for step in subject.plan(by_role)
                      if step[0] == role and step[1] == "stable_first_repeat"][0]
            self.assertEqual(repeat[3], by_role[role]["stable_first"][0])

    def test_input_cost_uses_each_gpt6_model_rate(self):
        usage = {"prompt_tokens": 2000,
                 "prompt_tokens_details": {"cached_tokens": 500,
                                           "cache_write_tokens": 1000}}
        self.assertEqual(subject.input_cost("gpt-6-astra", usage), 0.018)
        self.assertEqual(subject.input_cost("gpt-6-sol", usage), 0.0036)
        self.assertIsNone(subject.input_cost("gpt-6-sol", {"prompt_tokens": 2000}))

    def test_weekly_policy_keeps_source_synthetic_and_arms_equivalent(self):
        fixture = subject.RunTargetLanguageModelsTests(
            methodName="test_astra_then_sol_each_group_and_admit_human_pending")
        fixture.setUp()
        try:
            policy = fixture.fixture.policy.copy()
            policy["terminology"] = {"synthetic": "longer weekly policy"}
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "policy.json"
                path.write_text(json.dumps(policy), encoding="utf-8")
                arms = subject.payloads(path, long_source=True)
            for role in subject.MODELS:
                current = arms[role]["current_order"]
                candidate = arms[role]["stable_first"]
                for a, b in zip(current, candidate):
                    values = json.loads(a["messages"][1]["content"])
                    self.assertEqual(values["terminology"], policy["terminology"])
                    self.assertGreater(len(values["englishUnits"][0]["english"]), 1000)
                    self.assertEqual(values,
                                     json.loads(b["messages"][1]["content"]))
                    self.assertEqual(a["messages"][0], b["messages"][0])
        finally:
            fixture.doCleanups()


if __name__ == "__main__":
    unittest.main()
