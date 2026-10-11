import json
import tempfile
import unittest
from pathlib import Path

from scripts import judge_english_source_for_translation as judge
from scripts import build_english_source_package as layer1


def row(sentence_id, failing=()):
    return {"sourceSentenceId": sentence_id, "verdict": "fail" if failing else "pass", "risk": "high" if failing else "low",
            "checks": {name: ("fail" if name in failing else "pass") for name in judge.CHECKS},
            "evidence": "x", "unresolvedIssues": ["timing"] if failing else []}


class OperatorAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "acceptance.json"
        self.manifest = {"issues": [{"type": "alignment_word_duration_outlier", "sourceSentenceId": "c-s001",
                                     "wordId": "c-w0003", "durationSeconds": 3.1, "maximumSeconds": 2.5}]}

    def write(self, **changes):
        value = {"schemaVersion": judge.OPERATOR_ACCEPTANCE_SCHEMA,
                 "anchorManifestJsonSha256": layer1.json_sha256(self.manifest), "humanApproval": True,
                 "acceptedBy": "operator", "acceptedAt": "2026-10-11T00:00:00Z",
                 "accepted": [{"sourceSentenceId": "c-s001", "issueType": "alignment_word_duration_outlier",
                               "wordId": "c-w0003", "reason": "held vowel and pause"}]}
        value.update(changes)
        self.path.write_text(json.dumps(value))
        return self.path

    def test_timing_only_failure_with_matching_outlier_is_accepted(self):
        result = judge._operator_acceptance(self.write(), self.manifest, [row("c-s001", ["timelineCoherent"])])
        self.assertEqual(result["acceptedSentenceIds"], ["c-s001"])
        self.assertEqual(result["acceptedBy"], "operator")

    def test_acceptance_for_a_sentence_the_judge_passed_is_unused(self):
        result = judge._operator_acceptance(self.write(), self.manifest, [row("c-s001")])
        self.assertEqual(result["acceptedSentenceIds"], [])

    def test_semantic_failure_cannot_be_accepted(self):
        with self.assertRaisesRegex(ValueError, "timelineCoherent alone"):
            judge._operator_acceptance(self.write(), self.manifest,
                                       [row("c-s001", ["timelineCoherent", "quotationAndClauseIntegrity"])])

    def test_issue_absent_from_manifest_is_rejected(self):
        accepted = [{"sourceSentenceId": "c-s001", "issueType": "alignment_word_duration_outlier",
                     "wordId": "c-w0009", "reason": "x"}]
        with self.assertRaisesRegex(ValueError, "absent from the manifest"):
            judge._operator_acceptance(self.write(accepted=accepted), self.manifest, [row("c-s001", ["timelineCoherent"])])

    def test_acceptance_bound_to_another_manifest_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "another anchor manifest"):
            judge._operator_acceptance(self.write(anchorManifestJsonSha256="0" * 64), self.manifest,
                                       [row("c-s001", ["timelineCoherent"])])


if __name__ == "__main__":
    unittest.main()
