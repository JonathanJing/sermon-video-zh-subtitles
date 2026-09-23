"""Source-scoped term admission and frozen plugin identity for Policy v2."""
import copy
from pathlib import Path
import json
import unittest

from scripts import target_language_policy as subject
from scripts import sermon_sentence_interpretation as interpretation


ROOT = Path(__file__).resolve().parents[1]


class ScopedPolicyTests(unittest.TestCase):
    def setUp(self):
        self.anchor = {"sourceUnits": [
            {"sourceUnitId": "u1", "english": "Ian Duguid says there are three."},
            {"sourceUnitId": "u2", "english": "Revelation chapter two."},
        ]}
        self.source = {"source": "approved fixture", "anchors": {
            "artifact": {"jsonSha256": interpretation.json_sha256(self.anchor)}}}
        self.candidate = {"targetLocale": "ko",
                          "englishSourcePackageJsonSha256": interpretation.json_sha256(self.source),
                          "groups": [{"coverage": [{"sourceUnitId": "u1",
                                                   "targetText": "이언 두기드는 세 가지라고 말합니다."}]}]}
        self.approval = {"targetLocale": "ko", "decision": "approved",
                         "humanApproval": True, "formalLayer2Admitted": False,
                         "englishSourcePackageJsonSha256": interpretation.json_sha256(self.source),
                         "candidateJsonSha256": subject.canonical_sha256(self.candidate),
                         "reviewedSourceUnitIds": ["u1", "u2"]}
        draft = json.loads((ROOT / "config/target-language-policies/ko.json")
                           .read_text(encoding="utf-8"))
        draft.pop("componentSha256")
        draft["schemaVersion"] = subject.POLICY_V2
        draft["languageReview"]["pluginImplementationSha256"] = "a" * 64
        draft["languageReview"]["implementationStatus"] = "verified"
        draft["terminology"]["properNames"] = [
            {"source": "Ian Duguid", "target": "이언 두기드", "reviewStatus": "human_reviewed"}]
        draft["sourceScope"] = {
            "englishSourcePackageJsonSha256": interpretation.json_sha256(self.source),
            "anchorManifestSha256": interpretation.json_sha256(self.anchor),
            "usedSeriesNames": [], "usedProperNames": ["Ian Duguid"],
            "termApprovalEvidence": [{"source": "Ian Duguid", "target": "이언 두기드",
                                      "sourceUnitId": "u1",
                                      "shadowCandidateJsonSha256": subject.canonical_sha256(self.candidate),
                                      "shadowContentApprovalJsonSha256": subject.canonical_sha256(self.approval)}],
        }
        self.draft = draft

    def freeze(self):
        return subject.freeze_policy(self.draft, shadow_candidate=self.candidate,
                                     content_approval=self.approval)

    def test_unused_series_terms_remain_pending_without_blocking_scoped_term_review(self):
        frozen = self.freeze()
        self.assertTrue(all(row["reviewStatus"] == "pending"
                            for row in frozen["terminology"]["seriesNames"]))
        identity = subject.validate_policy(frozen)
        self.assertNotIn("terminology_review_pending", identity["unresolved"])
        subject.validate_source_scope(frozen, self.source, self.anchor)
        self.assertFalse(identity["productionPolicyReady"])  # scripture remains pending

    def test_source_or_declared_name_drift_fails(self):
        frozen = self.freeze()
        changed = copy.deepcopy(self.anchor)
        changed["sourceUnits"][0]["english"] = "A different scholar speaks."
        with self.assertRaisesRegex(ValueError, "another English package or anchor"):
            subject.validate_source_scope(frozen, self.source, changed)
        altered = copy.deepcopy(frozen)
        altered["sourceScope"]["usedProperNames"] = []
        with self.assertRaisesRegex(ValueError, "proper names are incomplete"):
            subject.validate_source_scope(altered, self.source, self.anchor)

    def test_shadow_approval_is_bound_to_exact_term_and_candidate(self):
        with self.assertRaisesRegex(ValueError, "exact shadow candidate and human receipt"):
            subject.freeze_policy(self.draft)
        changed = copy.deepcopy(self.candidate)
        changed["groups"][0]["coverage"][0]["targetText"] = "다른 이름"
        with self.assertRaisesRegex(ValueError, "matching human-approved clip candidate"):
            subject.freeze_policy(self.draft, shadow_candidate=changed,
                                  content_approval=self.approval)
        revoked = copy.deepcopy(self.approval)
        revoked["decision"] = "rejected"
        with self.assertRaisesRegex(ValueError, "matching human-approved clip candidate"):
            subject.freeze_policy(self.draft, shadow_candidate=self.candidate,
                                  content_approval=revoked)

    def test_plugin_hash_participates_in_frozen_policy_identity(self):
        frozen = self.freeze()
        changed = copy.deepcopy(frozen)
        changed["languageReview"]["pluginImplementationSha256"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "component hash changed: languageReview"):
            subject.validate_policy(changed)


if __name__ == "__main__":
    unittest.main()
