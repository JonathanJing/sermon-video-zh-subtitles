"""Malformed translator/reviewer replies fail one group, not the whole locale run."""
import json
from pathlib import Path
import tempfile
import unittest

from scripts import layer2_auto_repair as repair
from scripts import run_target_language_models as runner


class UtteranceShapeTests(unittest.TestCase):
    def test_wrapped_utterances_accept_text_or_target_text(self):
        for key in ("targetText", "text"):
            with self.subTest(key=key):
                value = [{"sourceUnitIds": ["u1"], key: "一句话。"}]
                self.assertEqual(runner._utterances(value, ["u1"]), ["一句话。"])

    def test_conflicting_or_unbound_wrappers_are_still_rejected(self):
        for value in ([{"sourceUnitIds": ["u1"], "text": "甲", "targetText": "乙"}],
                      [{"sourceUnitIds": ["u2"], "text": "甲"}], [{"text": "甲"}]):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "nonempty targetUtterances"):
                runner._utterances(value, ["u1"])


class CollectorTests(unittest.TestCase):
    def test_malformed_translator_reply_becomes_a_translator_repair(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder) / "group-0001-astra.json"
            cache.write_text(json.dumps({"result": {}}))
            collector = repair.FailureCollector(461)
            group = {"translationGroupId": "g1", "sourceUnitIds": ["u1"]}
            collector.record_malformed_output(1, group, "translator", cache, "Model must return nonempty targetUtterances")
            failure = collector.failures[0]
            self.assertEqual(failure["failureCodes"], ["malformed_model_output"])
            self.assertEqual(failure["action"], "repair_translation")
            row = repair.repair_row(failure)
            self.assertEqual(row["failedRole"], "translator")
            self.assertIn("JSON contract", row["instruction"])
            self.assertFalse(collector.stopped())

    def test_unknown_role_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "translator or reviewer"):
            repair.FailureCollector(10).record_malformed_output(1, {"translationGroupId": "g", "sourceUnitIds": ["u"]},
                                                                "judge", Path("missing"), "x")

    def test_repeated_malformed_output_escalates(self):
        self.assertEqual(repair.REPEATED_FAILURE_ACTIONS["malformed_model_output"], "escalate_engineering")


if __name__ == "__main__":
    unittest.main()
