"""Per-group candidate assembly equals the whole-sermon admission (DEV-GRP-002)."""
from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest

from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tests import test_produce_target_language_candidate as candidate_fixture
from tongxing_production.orchestration import group_assembly as subject
from tongxing_production.orchestration import group_records as records
from tongxing_production.text import models


PIPELINE = {"derivation": "per_group_pipeline"}
RUNNER = "a" * 64


class GroupAssemblyTests(unittest.TestCase):
    def setUp(self):
        fixture = candidate_fixture.ProduceTargetLanguageCandidateTests(
            "test_compiles_valid_candidate_without_human_approval")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        # The runner names groups by the plan; the whole-path fixture uses short IDs.
        plan = models.group_plan(fixture.request, fixture.anchor)
        for row, group in zip(fixture.evidence["groups"], plan):
            row["translationGroupId"] = group["translationGroupId"]
        self.plan = plan
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = records.RecordStore(self.root)
        self.payloads = subject.PayloadStore(self.root)
        self.layer1 = records.layer1_identity(fixture.request["englishSourcePackageJsonSha256"],
                                              fixture.request["anchorManifestSha256"])
        self.locale = fixture.request["targetLocale"]
        self.receipt = fixture.receipt()

    def record(self, stage, row, *, verdict="pass", provenance=PIPELINE, outputs=None, inputs=None,
               implementation=None):
        group_id, units = row["translationGroupId"], row["sourceUnitIds"]
        target = records.text_sha256("".join(row["targetUtterances"]))
        if stage == "T":
            values = {"draftTextSha256": records.text_sha256("draft " + group_id)}
            base = {name: None for name in records.STAGE_INPUTS["T"]}
        elif stage == "R":
            values = subject.reviewed_outputs(row, self.payloads)
            base = {name: None for name in records.STAGE_INPUTS["R"]}
            base["draftTextSha256"] = records.text_sha256("draft " + group_id)
        else:
            review = next(item for item in self.receipt["groupReviews"] if item["translationGroupId"] == group_id)
            values = subject.plugin_outputs(review, self.payloads)
            base = {"languageReviewPolicySha256": self.receipt["languageReviewPolicySha256"],
                    "englishUnitsSha256": None, "targetTextSha256": target}
        made = records.make_record(stage, self.layer1, self.locale, group_id, units, inputs or base,
                                   implementation or (self.fixture.plugin_sha if stage == "P" else RUNNER),
                                   outputs if outputs is not None else values, verdict,
                                   codes=["x"] if verdict in {"fail", "stopped"} else (), provenance=provenance)
        self.store.put(made)
        return made

    def variant(self, stage, row):
        """Inputs of a second run of this stage (another revision brief), so it gets its own key."""
        inputs = {name: None for name in records.STAGE_INPUTS[stage]}
        if stage == "R":
            inputs["draftTextSha256"] = records.text_sha256("draft " + row["translationGroupId"])
        inputs["revisionSha256"] = records.text_sha256("another revision brief")
        return inputs

    def write_all(self):
        for row in self.fixture.evidence["groups"]:
            for stage in subject.ASSEMBLED_STAGES:
                self.record(stage, row)

    def assemble(self, **kwargs):
        fixture = self.fixture
        return subject.assemble(fixture.source, fixture.anchor, fixture.policy, fixture.request, None,
                                fixture.plugin_path, self.store, self.payloads, **kwargs)

    def refused(self, **kwargs):
        with self.assertRaises(subject.AssemblyRefused) as caught:
            self.assemble(**kwargs)
        return caught.exception.reasons

    def test_assembled_candidate_is_byte_identical_to_whole_path_admission(self):
        self.write_all()
        result = self.assemble()
        whole = self.fixture.admit(self.receipt)
        self.assertEqual(subject.file_bytes(result["candidate"]), subject.file_bytes(whole))
        self.assertEqual(subject.file_bytes(result["languageReview"]), subject.file_bytes(self.receipt))
        self.assertEqual(result["evidence"], self.fixture.evidence)
        manifest = result["manifest"]
        self.assertEqual([row["translationGroupId"] for row in manifest["groups"]],
                         [row["translationGroupId"] for row in self.plan])
        self.assertEqual((manifest["releaseEligible"], manifest["humanApproval"], manifest["equivalenceCheck"]),
                         (False, False, False))

    def test_nested_key_order_survives_the_payload_store(self):
        row = copy.deepcopy(self.fixture.evidence["groups"][0])
        row["semanticReview"] = dict(reversed(list(row["semanticReview"].items())))
        sha = self.payloads.put(row)
        self.assertEqual(list(self.payloads.get(sha)["semanticReview"]), list(row["semanticReview"]))
        self.assertNotEqual(sha, self.payloads.put(self.fixture.evidence["groups"][0]))

    def test_records_read_from_whole_sermon_products_are_refused(self):
        self.write_all()
        first = self.fixture.evidence["groups"][0]
        self.record("R", first, provenance={"derivation": "legacy_round_cache"}, inputs=self.variant("R", first))
        reasons = self.refused()
        self.assertEqual(reasons, {"R:legacy_planning_only": [first["translationGroupId"]]})

    def test_unknown_outcome_blocks_only_by_naming_its_group(self):
        self.write_all()
        second = self.fixture.evidence["groups"][1]
        self.record("T", second, verdict="unknown", outputs={}, inputs=self.variant("T", second))
        self.assertEqual(self.refused(), {"unknown_outcome_needs_reconciliation": [second["translationGroupId"]]})

    def test_missing_stage_and_conflicting_reviews_are_named(self):
        first, second = self.fixture.evidence["groups"]
        for stage in ("T", "R"):
            self.record(stage, first)
        self.record("T", second)
        self.record("R", second)
        changed = copy.deepcopy(second)
        changed["semanticReview"]["evidence"] = "A second, different review of the same group."
        inputs = {name: None for name in records.STAGE_INPUTS["R"]}
        inputs.update(draftTextSha256=records.text_sha256("draft " + second["translationGroupId"]),
                      revisionSha256=records.text_sha256("a revision brief"))
        self.record("R", changed, inputs=inputs)
        self.record("P", second)
        self.assertEqual(self.refused(), {"P:missing_for_current_plugin_and_text": [first["translationGroupId"]],
                                          "R:conflict": [second["translationGroupId"]]})

    def test_plugin_record_for_another_plugin_does_not_count(self):
        self.write_all()
        first = self.fixture.evidence["groups"][0]
        # Replace the store with one whose P for the first group came from another plugin.
        self.store = records.RecordStore(self.root / "other")
        self.payloads = subject.PayloadStore(self.root / "other")
        for row in self.fixture.evidence["groups"]:
            self.record("T", row)
            self.record("R", row)
            self.record("P", row, implementation="b" * 64 if row is first else None)
        self.assertEqual(self.refused(), {"P:missing_for_current_plugin_and_text": [first["translationGroupId"]]})

    def test_review_must_chain_to_its_translator_draft(self):
        first = self.fixture.evidence["groups"][0]
        for row in self.fixture.evidence["groups"]:
            if row is first:
                self.record("T", row, outputs={"draftTextSha256": records.text_sha256("another draft")})
            else:
                self.record("T", row)
            self.record("R", row)
            self.record("P", row)
        self.assertEqual(self.refused(), {"T:missing_or_not_passed": [first["translationGroupId"]]})

    def test_plugin_record_must_match_a_fresh_plugin_run(self):
        first = self.fixture.evidence["groups"][0]
        for row in self.fixture.evidence["groups"]:
            self.record("T", row)
            self.record("R", row)
            if row is first:
                self.record("P", row, outputs=subject.plugin_outputs({"recorded": "elsewhere"}, self.payloads))
            else:
                self.record("P", row)
        with self.assertRaisesRegex(ValueError, "plugin_record_differs_from_fresh_run"):
            self.assemble()

    def test_changed_payload_bytes_are_refused(self):
        self.write_all()
        sha = self.payloads.put(self.fixture.evidence["groups"][0])
        path = self.payloads.path(sha)
        path.write_bytes(path.read_bytes().replace(b"translate-1", b"translate-9"))
        with self.assertRaisesRegex(ValueError, "payload_changed"):
            self.assemble()

    def test_equivalence_records_count_only_inside_the_equivalence_check(self):
        legacy = {}
        for row in self.fixture.evidence["groups"]:
            legacy[row["translationGroupId"]] = {
                stage: records.make_record(stage, self.layer1, self.locale, row["translationGroupId"],
                                           row["sourceUnitIds"],
                                           {name: None for name in records.STAGE_INPUTS[stage]}, RUNNER,
                                           ({"draftTextSha256": records.text_sha256("draft")} if stage == "T" else
                                            {"targetTextSha256": records.text_sha256("".join(row["targetUtterances"]))}),
                                           "pass", provenance={"derivation": "legacy_round_cache"})
                for stage in ("T", "R")}
        skipped = subject.equivalence_records(self.fixture.evidence, self.receipt, legacy, self.store, self.payloads)
        self.assertEqual(skipped, [])
        reasons = self.refused()
        self.assertLessEqual({f"{stage}:equivalence_record_outside_check" for stage in ("T", "R", "P")}, set(reasons))
        result = self.assemble(equivalence_check=True)
        self.assertEqual(subject.file_bytes(result["candidate"]), subject.file_bytes(self.fixture.admit(self.receipt)))
        self.assertTrue(result["manifest"]["equivalenceCheck"])

    def test_equivalence_split_never_invents_a_missing_translator_record(self):
        first, second = self.fixture.evidence["groups"]
        legacy = {}
        skipped = subject.equivalence_records(self.fixture.evidence, self.receipt, legacy, self.store, self.payloads)
        self.assertEqual(skipped, [first["translationGroupId"], second["translationGroupId"]])
        self.assertEqual(self.store.records(self.locale, first["translationGroupId"], "T"), [])


if __name__ == "__main__":
    unittest.main()
