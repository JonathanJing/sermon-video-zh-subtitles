import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts import build_target_language_audio_package as subject


class AnchorExceptionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.source = {"anchors": {"issueCount": 1}}
        self.issue = {"type": "clause_unit_exceeds_target_without_safe_boundary",
                      "sourceSentenceId": "0-s202", "durationSeconds": 9.199951,
                      "maximumSeconds": 8.0, "sourceWordIds": ["0-w3295"],
                      "english": "‘Don’t harm the earth or the sea or the trees until we seal the servants of our God on their foreheads.’"}
        self.anchor = {"issues": [self.issue]}
        self.paths = {name: root / (name + ".json") for name in
                      ("source", "anchor", "anchor_exception_receipt")}
        for name, value in (("source", self.source), ("anchor", self.anchor)):
            self.paths[name].write_text(json.dumps(value))
        self.receipt = {"schemaVersion": "sermon-human-anchor-exception-receipt-v1",
                        "status": "approved", "humanApproval": True,
                        "reviewedBy": "human-user", "reviewedAt": "2026-10-04T12:00:00Z",
                        "userDecision": "授权本次例外，立即发布中文",
                        "reason": "preserve_complete_scripture_sentence", "targetLocale": "zh-Hans",
                        "acceptedIssue": copy.deepcopy(self.issue)}
        for key, name, value in (("englishSourcePackage", "source", self.source),
                                 ("anchorManifest", "anchor", self.anchor)):
            self.receipt[key] = {"sha256": subject.file_sha256(self.paths[name]),
                                 "jsonSha256": subject.json_sha256(value)}
        self.write_receipt()

    def write_receipt(self):
        self.paths["anchor_exception_receipt"].write_text(json.dumps(self.receipt))

    def validate(self, locale="zh-Hans"):
        candidate = {"targetLocale": locale, "groups": []}
        self.paths["candidate"] = Path(self.tmp.name) / "candidate.json"
        self.paths["candidate"].write_text(json.dumps(candidate))
        return subject.validate_anchor_exception(self.source, self.anchor, candidate, self.paths)

    def test_accepts_bound_authorization_without_mutating_inputs(self):
        before = copy.deepcopy((self.source, self.anchor))
        self.assertTrue(self.validate())
        self.assertEqual(before, (self.source, self.anchor))

    def test_absent_receipt_does_not_accept(self):
        self.paths.pop("anchor_exception_receipt")
        self.assertFalse(self.validate())

    def test_rejects_changed_binding_or_human_decision(self):
        for key, value in (("humanApproval", False), ("userDecision", "approved"),
                           ("acceptedIssue", {})):
            with self.subTest(key=key):
                original = self.receipt[key]
                self.receipt[key] = value
                self.write_receipt()
                with self.assertRaises(ValueError):
                    self.validate()
                self.receipt[key] = original
        self.receipt["englishSourcePackage"]["sha256"] = "0" * 64
        self.write_receipt()
        with self.assertRaises(ValueError):
            self.validate()

    def test_rejects_other_locale_and_extra_issue(self):
        with self.assertRaises(ValueError):
            self.validate("es-ES")
        self.anchor["issues"].append(copy.deepcopy(self.issue))
        with self.assertRaises(ValueError):
            self.validate()

    def test_v2_binds_locale_and_exact_candidate_hashes(self):
        candidate = {"targetLocale": "ko", "groups": [{"id": "g"}]}
        candidate_path = Path(self.tmp.name) / "candidate.json"
        candidate_path.write_text(json.dumps(candidate))
        self.paths["candidate"] = candidate_path
        self.receipt.update(schemaVersion="sermon-human-anchor-exception-receipt-v2",
                            userDecision="授权本次例外，立即发布该语言", targetLocale="ko",
                            candidate={"sha256": subject.file_sha256(candidate_path),
                                       "jsonSha256": subject.json_sha256(candidate)})
        self.write_receipt()
        self.assertTrue(subject.validate_anchor_exception(self.source, self.anchor, candidate, self.paths))
        with self.assertRaises(ValueError):
            subject.validate_anchor_exception(self.source, self.anchor,
                                              {**candidate, "targetLocale": "es"}, self.paths)
        self.receipt["candidate"]["sha256"] = "0" * 64
        self.write_receipt()
        with self.assertRaises(ValueError):
            subject.validate_anchor_exception(self.source, self.anchor, candidate, self.paths)
