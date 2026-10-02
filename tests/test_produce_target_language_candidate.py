import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import produce_target_language_candidate as subject
from scripts import prepare_target_language_speech_job as handoff
from scripts import review_target_language_candidate as human_review
from scripts import sermon_sentence_interpretation as interpretation
from scripts import target_language_policy as policy_tools
from scripts import four_layer_progress as progress
from scripts import sermon_accounting as accounting
from scripts import build_four_layer_tracker_snapshot as tracker_snapshot
from scripts import build_english_source_package as english_source
from tests import test_build_english_source_package as source_fixtures


ROOT = Path(__file__).resolve().parents[1]


class ProduceTargetLanguageCandidateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.plugin_path = Path(temporary.name) / "zh_review_plugin.py"
        self.plugin_path.write_text('''PLUGIN_ID = "zh-Hans-sermon-v1"
PLUGIN_VERSION = "test-v1"

def review_group(policy, english_units, group):
    status = "fail" if "禁" in group["targetText"] else "pass"
    return [{"checkId": check, "status": status,
             "evidence": "Deterministic fixture check for " + group["translationGroupId"]}
            for check in policy["languageReview"]["requiredChecks"]]
''', encoding="utf-8")
        self.plugin_sha = subject.plugin_implementation_sha256(self.plugin_path)
        # Build a complete synthetic Layer 1 package through the real builder,
        # rather than teaching production admission to accept incomplete stubs.
        source = source_fixtures.EnglishSourcePackageTests()
        source.setUp(); self.addCleanup(source.doCleanups)
        segments = []
        for index, text in enumerate(("Remember your first love.", "Return to it.")):
            words = text.split()
            start = index * 3.0
            segments.append({"id": index, "referenceChunkId": "block-1", "text": text,
                "start": start, "end": start + len(words) * .3,
                "sentenceBoundarySource": "frozen_reference_punctuation",
                "wordTimes": [{"text": word, "start": start + n * .3,
                               "end": start + (n + 1) * .3} for n, word in enumerate(words)]})
        source_fixtures.write_json(source.segments_path, segments)
        self.anchor = interpretation.build_anchor_manifest(segments, source_path=source.segments_path,
                                                           unit_policy=interpretation.UNIT_POLICY_V2)
        source_fixtures.write_json(source.manifest_path, self.anchor)
        review_path = source.root / "synthetic-review.json"
        source_fixtures.write_json(review_path, {
            "schemaVersion": english_source.REVIEW_SCHEMA_VERSION,
            "alignedSegmentsSha256": english_source.file_sha256(source.segments_path),
            "anchorManifestJsonSha256": interpretation.json_sha256(self.anchor),
            "humanApproval": True, "reviewedBy": "Synthetic fixture reviewer",
            "reviewedAt": "2026-09-30T00:00:00Z",
            "reviewedSourceUnitIds": [u["sourceUnitId"] for u in self.anchor["sourceUnits"]],
            "checks": {name: "approved" for name in english_source.APPROVED_CHECKS}})
        self.source = source.build(review_path=review_path)
        policy = json.loads((ROOT / "config/target-language-policies/zh-Hans.json")
                            .read_text(encoding="utf-8"))
        policy.pop("componentSha256")
        policy["schemaVersion"] = policy_tools.POLICY_V2
        policy["sourceScope"] = {
            "englishSourcePackageJsonSha256": interpretation.json_sha256(self.source),
            "anchorManifestSha256": interpretation.json_sha256(self.anchor),
            "usedSeriesNames": [], "usedProperNames": [], "termApprovalEvidence": [],
        }
        policy["languageReview"]["implementationStatus"] = "verified"
        policy["languageReview"]["pluginImplementationSha256"] = self.plugin_sha
        self.policy = policy_tools.freeze_policy(policy)
        self.identity = policy_tools.validate_policy(self.policy)
        self.request = subject.prepare_request(self.source, self.anchor, self.policy)
        self.evidence = copy.deepcopy(self.request)
        self.evidence["generation"] = {
            "translator": {"model": self.policy["translator"]["model"],
                           "promptVersion": self.policy["translator"]["promptVersion"],
                           "requestIds": ["translate-1", "translate-2"]},
            "reviewer": {"model": self.policy["reviewer"]["model"],
                         "promptVersion": self.policy["reviewer"]["promptVersion"],
                         "requestIds": ["review-1", "review-2"]},
        }
        self.evidence["groups"] = [
            self.group(index, source_unit, text) for index, (source_unit, text) in enumerate(
                (("block-1-u001", "要记得起初的爱。"),
                 ("block-1-u002", "回到那份爱中。")), 1)
        ]

    def group(self, index, unit_id, text):
        return {
            "translationGroupId": f"g{index}",
            "sourceUnitIds": [unit_id],
            "targetUtterances": [text],
            "coverage": [{"sourceUnitId": unit_id, "targetText": text}],
            "semanticReview": {
                "status": "pass", "checks": {
                    "completeMeaning": "pass", "negationsNumbersNames": "pass",
                    "quotationAttribution": "pass", "noAddedMeaning": "pass",
                }, "evidence": "Independent model review record for this group.",
                "uncertainty": [], "issues": [],
            },
            "translatorRequestId": f"translate-{index}",
            "reviewerRequestId": f"review-{index}",
        }

    def receipt(self):
        return subject.run_language_plugin(self.source, self.anchor, self.policy,
                                           self.request, self.evidence,
                                           self.plugin_path, self.plugin_sha)

    def admit(self, receipt=None):
        if receipt is None:
            receipt = self.receipt()
        return subject.admit_evidence(self.source, self.anchor, self.policy,
                                      self.request, self.evidence, receipt,
                                      self.plugin_path, self.plugin_sha)

    def test_compiles_valid_candidate_without_human_approval(self):
        candidate = self.admit()
        self.assertEqual(candidate["status"], "machine_review_pass_human_review_pending")
        self.assertFalse(candidate["releaseEligible"])
        self.assertEqual(candidate["humanReview"]["translation"], "pending")
        self.assertEqual(candidate["groups"][0]["targetText"], "要记得起初的爱。")
        self.assertNotIn("translatorRequestId", candidate["groups"][0])
        self.assertEqual(candidate["groups"][0]["languageReview"]["status"], "pass")
        handoff.validate_target_candidate(self.source, self.anchor, candidate,
                                          require_human_approval=False)
        handoff.validate_policy_binding(candidate, self.policy)
        worksheet = human_review.build_worksheet(self.source, self.anchor,
                                                 candidate, self.policy)
        self.assertEqual(len(worksheet["groupReviews"]), 2)
        with self.assertRaisesRegex(ValueError, "Human translation approval"):
            handoff.validate_target_candidate(self.source, self.anchor, candidate)

    def test_prepare_cli_records_timing_and_source_units(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = {name: root / f"{name}.json" for name in ("source", "anchor", "policy")}
            for name, value in (("source", self.source), ("anchor", self.anchor), ("policy", self.policy)):
                paths[name].write_text(json.dumps(value), encoding="utf-8")
            ledger = root / "four-layer-progress.json"
            progress.save(ledger, progress.new_ledger("test-page", ["zh-Hans"]))
            output = root / "request.json"
            argv = ["produce", "prepare", "--english-source-package", str(paths["source"]),
                    "--anchor", str(paths["anchor"]), "--policy", str(paths["policy"]),
                    "--progress-ledger", str(ledger), "--out", str(output)]
            with patch.object(sys, "argv", argv):
                subject.main()
            self.assertEqual(json.loads(output.read_text())["targetLocale"], "zh-Hans")
            events, damaged = accounting.read_events(root / "accounting")
            self.assertFalse(damaged)
            stages = [event for event in events if event["event"] == "stage_finished"
                      and event["stage"] == "four_layer.L2-01:zh-Hans"]
            self.assertEqual(len(stages), 1)
            workload = next(event for event in events if event["event"] == "workload"
                            and event["stage"] == "four_layer.L2-01:zh-Hans")
            self.assertEqual(workload["metrics"]["sourceUnits"], 2)
            self.assertEqual(progress.load(ledger)["steps"]["L2-01@zh-Hans"]["status"], "pending")
            snapshot_path = root / "public-snapshot.json"
            with patch.object(sys, "argv", ["tracker", "--ledger", str(ledger),
                                            "--out", str(snapshot_path)]):
                tracker_snapshot.main()
            snapshot = json.loads(snapshot_path.read_text())
            step = next(row for row in snapshot["steps"] if row["id"] == "L2-01@zh-Hans")
            self.assertEqual(step["timing"]["executionAttempts"], 1)
            self.assertEqual(snapshot["timingCoverage"]["measuredStepCount"], 1)

    def test_pending_policy_or_source_rejected_before_request(self):
        pending = json.loads((ROOT / "config/target-language-policies/zh-Hans.json")
                             .read_text(encoding="utf-8"))
        with self.assertRaisesRegex(ValueError, "Production policy"):
            subject.prepare_request(self.source, self.anchor, pending)
        source = copy.deepcopy(self.source)
        source["status"] = "candidate_ready_for_translation"
        with self.assertRaisesRegex(ValueError, "Approved English Source Package"):
            subject.prepare_request(source, self.anchor, self.policy)
        source = copy.deepcopy(self.source)
        source["review"]["checks"]["wordAlignment"] = "pending"
        with self.assertRaisesRegex(ValueError, "complete human review"):
            subject.prepare_request(source, self.anchor, self.policy)

    def test_rejects_stale_identity_cross_locale_and_review_request_reuse(self):
        self.evidence["englishSourcePackageJsonSha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "identity changed"):
            self.admit()
        self.evidence = copy.deepcopy(self.request)
        self.evidence["targetLocale"] = "ko"
        with self.assertRaisesRegex(ValueError, "identity changed"):
            self.admit()
        self.evidence["targetLocale"] = "zh-Hans"
        self.evidence["generation"] = {
            "translator": {"model": "x", "promptVersion": "x", "requestIds": ["same"]},
            "reviewer": {"model": "x", "promptVersion": "x", "requestIds": ["same"]},
        }
        self.evidence["groups"] = [self.group(1, "block-1-u001", "甲")]
        self.evidence["groups"][0]["translatorRequestId"] = "same"
        self.evidence["groups"][0]["reviewerRequestId"] = "same"
        with self.assertRaisesRegex(ValueError, "distinct nonempty"):
            self.admit()

    def test_rejects_missing_coverage_and_wrong_plugin_evidence(self):
        self.evidence["groups"].pop()
        self.evidence["generation"]["translator"]["requestIds"].pop()
        self.evidence["generation"]["reviewer"]["requestIds"].pop()
        with self.assertRaisesRegex(ValueError, "cover every source unit"):
            self.admit()
        self.evidence["groups"].append(self.group(2, "block-1-u002", "回去。"))
        self.evidence["generation"]["translator"]["requestIds"].append("translate-2")
        self.evidence["generation"]["reviewer"]["requestIds"].append("review-2")
        receipt = self.receipt()
        receipt["pluginId"] = "wrong-plugin"
        with self.assertRaisesRegex(ValueError, "receipt is missing, stale"):
            self.admit(receipt)

    def test_rejects_missing_tampered_or_false_pass_plugin_receipt(self):
        with self.assertRaises(TypeError):
            subject.admit_evidence(self.source, self.anchor, self.policy,
                                   self.request, self.evidence)  # type: ignore[call-arg]
        receipt = self.receipt()
        receipt["groupReviews"][0]["targetTextSha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "receipt is missing, stale"):
            self.admit(receipt)
        receipt = self.receipt()
        self.evidence["groups"][0]["targetUtterances"] = ["改过的文本。"]
        with self.assertRaisesRegex(ValueError, "receipt is missing, stale"):
            self.admit(receipt)
        self.evidence["groups"][0]["targetUtterances"] = ["要记得起初的爱。"]
        self.evidence["groups"][0]["languageReview"] = {"status": "pass"}
        with self.assertRaisesRegex(ValueError, "exact translation"):
            self.admit(self.receipt())
        del self.evidence["groups"][0]["languageReview"]
        receipt = self.receipt()
        receipt["targetLocale"] = "ko"
        with self.assertRaisesRegex(ValueError, "receipt is missing, stale"):
            self.admit(receipt)
        receipt = self.receipt()
        receipt["groupReviews"].pop()
        with self.assertRaisesRegex(ValueError, "receipt is missing, stale"):
            self.admit(receipt)
        self.evidence["groups"][0]["targetUtterances"] = ["禁用文本。"]
        receipt = self.receipt()
        self.assertEqual(receipt["groupReviews"][0]["status"], "fail")
        receipt["groupReviews"][0]["status"] = "pass"
        with self.assertRaisesRegex(ValueError, "receipt is missing, stale"):
            self.admit(receipt)
        with self.assertRaisesRegex(ValueError, "Language plugin rejected"):
            self.admit(self.receipt())

    def test_rejects_changed_plugin_implementation(self):
        receipt = self.receipt()
        self.plugin_path.write_text(self.plugin_path.read_text(encoding="utf-8") + "\n# drift\n",
                                    encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "implementation hash differs from frozen policy"):
            self.admit(receipt)

    def test_rejects_replaced_plugin_even_if_cli_reports_its_new_hash(self):
        self.plugin_path.write_text(self.plugin_path.read_text(encoding="utf-8")
                                    + "\n# replacement claims same plugin ID and passes checks\n",
                                    encoding="utf-8")
        replacement_sha = subject.plugin_implementation_sha256(self.plugin_path)
        with self.assertRaisesRegex(ValueError, "implementation hash differs from frozen policy"):
            subject.run_language_plugin(self.source, self.anchor, self.policy,
                                        self.request, self.evidence, self.plugin_path,
                                        replacement_sha)
        with self.assertRaisesRegex(ValueError, "implementation hash differs from frozen policy"):
            subject.admit_evidence(self.source, self.anchor, self.policy,
                                   self.request, self.evidence, {}, self.plugin_path,
                                   replacement_sha)

    def test_new_policy_hash_cannot_reuse_old_translation_request(self):
        changed_policy = copy.deepcopy(self.policy)
        changed_policy["languageReview"]["pluginImplementationSha256"] = "b" * 64
        changed_policy["componentSha256"]["languageReview"] = (
            policy_tools.canonical_sha256(changed_policy["languageReview"]))
        with self.assertRaisesRegex(ValueError, "request was changed"):
            subject.run_language_plugin(self.source, self.anchor, changed_policy,
                                        self.request, self.evidence, self.plugin_path,
                                        "b" * 64)


if __name__ == "__main__":
    unittest.main()
