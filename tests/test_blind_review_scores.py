"""Keep independent human ratings and old empty score templates readable."""

import copy
import unittest

from scripts.experiments import build_blind_review_scores as builder
from scripts.experiments import summarize_model_production_ab as summary


class BlindReviewScoreTests(unittest.TestCase):
    def setUp(self):
        self.sheet = {"schemaVersion": "layer2-ab-blind-review-v1", "targetLocale": "zh-Hans",
                      "groups": [{"translationGroupId": "group-1",
                                  "options": [{"code": code} for code in ("X", "Y", "Z")]}]}
        self.template = builder.build(self.sheet, "source-hash")

    def test_two_reviewers_keep_independent_scores(self):
        self.assertEqual(self.template["schemaVersion"], "layer2-ab-blind-scores-v2")
        first = self.template["ratings"][0]
        for reviewer in ("reviewer-1", "reviewer-2"):
            score = {field: 0 for field in builder.SCORE_FIELDS}
            score.update(naturalness1to5=4, editMinutes=2, criticalError=False, evidence="")
            first["reviews"].append({"reviewerId": reviewer, "draft": copy.deepcopy(score),
                                     "reviewed": copy.deepcopy(score)})
        first["reviews"][1]["draft"]["editMinutes"] = 5
        self.assertEqual(first["reviews"][0]["draft"]["editMinutes"], 2)
        self.assertEqual(summary.completed_blind_options(self.template), 1)
        with self.assertRaisesRegex(ValueError, "duplicate or missing reviewer identity"):
            first["reviews"][1]["reviewerId"] = "reviewer-1"
            summary.completed_blind_options(self.template)

    def test_migration_preserves_v1_review_and_rejects_anonymous_scores(self):
        old = copy.deepcopy(self.template)
        old["schemaVersion"] = "layer2-ab-blind-scores-v1"
        for row in old["ratings"]:
            row.pop("reviews")
            row.update(reviewerId=None, draft=builder.blank_score(),
                       reviewed=builder.blank_score())
        self.assertEqual(summary.completed_blind_options(old), 0)
        old["ratings"][0]["reviewerId"] = "reviewer-1"
        old["ratings"][0]["draft"]["naturalness1to5"] = 4
        migrated = builder.migrate_v1(old, builder.build(self.sheet, "source-hash"))
        self.assertEqual(migrated["ratings"][0]["reviews"][0]["draft"]["naturalness1to5"], 4)
        self.assertEqual(migrated["ratings"][1]["reviews"], [])
        with self.assertRaisesRegex(ValueError, "migration"):
            summary.completed_blind_options(old)
        old["ratings"][0]["reviewerId"] = None
        with self.assertRaisesRegex(ValueError, "no reviewer identity"):
            builder.migrate_v1(old, builder.build(self.sheet, "source-hash"))


if __name__ == "__main__":
    unittest.main()
