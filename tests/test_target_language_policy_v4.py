"""Direct source-bound human term receipts and explicit scanner exclusions."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from scripts import target_language_policy as subject
from scripts import sermon_sentence_interpretation as interpretation


ROOT = Path(__file__).resolve().parents[1]


class DirectTermReceiptTests(unittest.TestCase):
    def setUp(self):
        self.anchor = {"sourceUnits": [
            {"sourceUnitId": "u1", "english": "Big Sur and Some Christians visit Southern California."},
            {"sourceUnitId": "u2", "english": "K heard Alexis speak."},
        ]}
        self.source = {"schemaVersion": "fixture", "anchors": {
            "artifact": {"jsonSha256": interpretation.json_sha256(self.anchor)}}}
        self.source_hash = interpretation.json_sha256(self.source)
        self.anchor_hash = interpretation.json_sha256(self.anchor)
        draft = json.loads((ROOT / "config/target-language-policies/ko.json")
                           .read_text(encoding="utf-8"))
        draft.pop("componentSha256")
        draft["schemaVersion"] = subject.POLICY_V4
        draft["languageReview"]["pluginImplementationSha256"] = "a" * 64
        draft["languageReview"]["implementationStatus"] = "verified"
        draft["terminology"]["properNames"] = [
            {"source": "Big Sur", "target": "빅서", "reviewStatus": "human_reviewed"},
            {"source": "Southern California", "target": "남부 캘리포니아", "reviewStatus": "human_reviewed"},
            {"source": "K", "target": "K", "reviewStatus": "human_reviewed"},
            {"source": "Alexis", "target": "Alexis", "reviewStatus": "human_reviewed"},
        ]
        receipt = {
            "schemaVersion": "sermon-source-scoped-term-approval-v1",
            "targetLocale": "ko",
            "englishSourcePackageJsonSha256": self.source_hash,
            "anchorManifestSha256": self.anchor_hash,
            "decision": "approved", "humanApproval": True,
            "reviewedBy": "user", "reviewedAt": "2026-10-04T03:30:00Z",
            "userStatement": "按建议建词表",
            "approvedTerms": [
                {"source": "Big Sur", "target": "빅서", "sourceUnitId": "u1"},
                {"source": "Southern California", "target": "남부 캘리포니아", "sourceUnitId": "u1"},
                {"source": "K", "target": "K", "sourceUnitId": "u2"},
                {"source": "Alexis", "target": "Alexis", "sourceUnitId": "u2"},
            ],
            "excludedScannerPhrases": ["Some Christians"],
        }
        draft["sourceScope"] = {
            "englishSourcePackageJsonSha256": self.source_hash,
            "anchorManifestSha256": self.anchor_hash,
            "usedSeriesNames": [],
            "usedProperNames": ["Big Sur", "Southern California"],
            "ordinaryPhraseExclusions": ["Some Christians"],
            "termApprovalEvidence": [],
            "termApprovalReceipt": receipt,
        }
        self.draft = draft

    def test_freezes_direct_user_decision_and_excludes_false_positive(self):
        frozen = subject.freeze_policy(self.draft)
        self.assertEqual(frozen["schemaVersion"], subject.POLICY_V4)
        subject.validate_source_scope(frozen, self.source, self.anchor)
        identity = subject.validate_policy(frozen)
        self.assertNotIn("proper_name_approval_evidence_pending", identity["unresolved"])
        self.assertIn("scripture_policy_pending", identity["unresolved"])
        self.assertIn("Some Christians", frozen["sourceScope"]["ordinaryPhraseExclusions"])

    def test_exclusion_must_be_real_and_receipt_bound_to_exact_locale_and_source(self):
        changed = copy.deepcopy(self.draft)
        changed["sourceScope"]["ordinaryPhraseExclusions"] = ["Invented Phrase"]
        changed["sourceScope"]["termApprovalReceipt"]["excludedScannerPhrases"] = ["Invented Phrase"]
        frozen = subject.freeze_policy(changed)
        with self.assertRaisesRegex(ValueError, "not source-scoped name candidates"):
            subject.validate_source_scope(frozen, self.source, self.anchor)
        changed = copy.deepcopy(self.draft)
        changed["sourceScope"]["termApprovalReceipt"]["targetLocale"] = "es"
        with self.assertRaisesRegex(ValueError, "Direct human term receipt"):
            subject.freeze_policy(changed)

    def test_term_target_must_match_user_receipt(self):
        changed = copy.deepcopy(self.draft)
        changed["terminology"]["properNames"][0]["target"] = "다른 표기"
        with self.assertRaisesRegex(ValueError, "Direct human term receipt"):
            subject.freeze_policy(changed)


if __name__ == "__main__":
    unittest.main()
