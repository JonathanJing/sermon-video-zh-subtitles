"""The accepted whole-sentence strategy is enforced for new weekly jobs."""
import copy
import unittest

from apply_spoken_review import make_units
from weekly_dubbing import SENTENCE_SYNTHESIS_POLICY, validate_frozen, validate_synthesis_policy


class SentenceSynthesisPolicyTests(unittest.TestCase):
    def test_new_job_keeps_chinese_sentences_intact(self):
        blocks = [{"id": 0, "zh": "你有一个仇敌，是一头吼叫的狮子。正伺机毁灭你，吞吃你。"}]
        units = make_units(blocks, segmentation="sentence")
        self.assertEqual([unit["text"] for unit in units], [
            "你有一个仇敌，是一头吼叫的狮子。", "正伺机毁灭你，吞吃你。"])
        self.assertEqual([unit["gapAfterSeconds"] for unit in units], [.18, .45])
        job = {"schemaVersion": "sermon-weekly-dubbing-job-v1", "inputs": {}, "blocks": blocks,
               "units": units, "synthesisPolicy": copy.deepcopy(SENTENCE_SYNTHESIS_POLICY)}
        validate_frozen(job)

        split = copy.deepcopy(job)
        split["units"] = [
            {"id": 0, "blockId": 0, "text": "你有一个", "gapAfterSeconds": .18},
            {"id": 1, "blockId": 0, "text": "仇敌，是一头吼叫的狮子。正伺机毁灭你，吞吃你。", "gapAfterSeconds": .45},
        ]
        with self.assertRaisesRegex(ValueError, "intact Chinese"):
            validate_synthesis_policy(split)

    def test_policy_is_versioned_and_old_jobs_remain_unchanged(self):
        blocks = [{"id": 0, "zh": "第一句。第二句。"}]
        legacy = {"schemaVersion": "sermon-weekly-dubbing-job-v1", "inputs": {}, "blocks": blocks,
                  "units": make_units(blocks)}
        self.assertEqual(len(legacy["units"]), 1)
        validate_frozen(legacy)
        changed = {**legacy, "synthesisPolicy": {**SENTENCE_SYNTHESIS_POLICY, "rate": "forced_to_source_duration"}}
        with self.assertRaisesRegex(ValueError, "Unsupported or altered synthesis policy"):
            validate_frozen(changed)

    def test_long_sentence_requires_review_not_automatic_phrase_cut(self):
        blocks = [{"id": 0, "zh": "这" * 181 + "。"}]
        with self.assertRaisesRegex(ValueError, "reviewed sentence break"):
            make_units(blocks, segmentation="sentence")


if __name__ == "__main__":
    unittest.main()
