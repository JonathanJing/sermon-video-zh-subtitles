"""Per-group candidate assembly equals the whole-sermon admission (DEV-GRP-002)."""
from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest

from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tests import test_produce_target_language_candidate as candidate_fixture
from tongxing_production.orchestration import group_assembly as subject
from tongxing_production.orchestration import group_legacy
from tongxing_production.orchestration import group_plan
from tongxing_production.orchestration import group_records as records
from tongxing_production.text import models
from tongxing_production.text import policy as policy_tools


PIPELINE = {"derivation": "per_group_pipeline"}
RUNNER = models.RUNNER_PRODUCTION_IDENTITY_SHA256


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
        self.plan = {group["translationGroupId"]: group for group in plan}
        self.contexts = group_legacy.group_contexts(fixture.anchor, plan)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = records.RecordStore(self.root)
        self.payloads = subject.PayloadStore(self.root)
        self.resolutions = subject.ResolutionStore(self.root)
        self.layer1 = records.layer1_identity(fixture.request["englishSourcePackageJsonSha256"],
                                              fixture.request["anchorManifestSha256"])
        self.locale = fixture.request["targetLocale"]
        self.receipt = fixture.receipt()
        self.identity = {"pluginImplementationSha256": fixture.plugin_sha,
                         "languageReviewPolicySha256":
                             policy_tools.validate_policy(fixture.policy)["languageReviewPolicySha256"]}

    def current(self, stage, row, **changes):
        """The inputs the current request would carry for this group, as the plan computes them."""
        group = self.plan[row["translationGroupId"]]
        values = group_plan.current_inputs("T" if stage == "P" else stage, group,
                                           self.contexts[group["translationGroupId"]], self.fixture.anchor,
                                           self.fixture.policy, self.identity, {})
        inputs = {name: None for name in records.STAGE_INPUTS[stage]}
        if stage == "P":
            inputs.update(languageReviewPolicySha256=self.identity["languageReviewPolicySha256"],
                          englishUnitsSha256=values["englishUnitsSha256"],
                          targetTextSha256=records.text_sha256("".join(row["targetUtterances"])))
        else:
            inputs.update({name: value for name, value in values.items() if name in inputs})
            inputs["boundedPayloadSha256"] = records.text_sha256(f"{stage} payload {row['translationGroupId']}")
        if stage == "R":
            inputs["draftTextSha256"] = records.text_sha256("draft " + row["translationGroupId"])
        inputs.update(changes)
        return inputs

    def record(self, stage, row, *, verdict="pass", provenance=PIPELINE, outputs=None, inputs=None,
               implementation=None):
        group_id, units = row["translationGroupId"], row["sourceUnitIds"]
        if stage == "T":
            values = {"draftTextSha256": records.text_sha256("draft " + group_id)}
        elif stage == "R":
            values = subject.reviewed_outputs(row, self.payloads)
        else:
            review = next(item for item in self.receipt["groupReviews"] if item["translationGroupId"] == group_id)
            values = subject.plugin_outputs(review, self.payloads)
        made = records.make_record(stage, self.layer1, self.locale, group_id, units,
                                   inputs if inputs is not None else self.current(stage, row),
                                   implementation or (self.fixture.plugin_sha if stage == "P" else RUNNER),
                                   outputs if outputs is not None else values, verdict,
                                   codes=["x"] if verdict in {"fail", "stopped"} else (), provenance=provenance)
        self.store.put(made)
        return made

    def write_all(self, skip=()):
        for row in self.fixture.evidence["groups"]:
            for stage in subject.ASSEMBLED_STAGES:
                if (row["translationGroupId"], stage) not in skip:
                    self.record(stage, row)

    def groups(self):
        return self.fixture.evidence["groups"]

    def assemble(self, **kwargs):
        fixture = self.fixture
        return subject.assemble(fixture.source, fixture.anchor, fixture.policy, fixture.request, None,
                                fixture.plugin_path, self.store, self.payloads, resolutions=self.resolutions,
                                **kwargs)

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
        self.assertEqual([row["translationGroupId"] for row in manifest["groups"]], list(self.plan))
        self.assertEqual((manifest["releaseEligible"], manifest["humanApproval"], manifest["equivalenceCheck"]),
                         (False, False, False))
        self.assertEqual(manifest["runnerImplementationSha256"], RUNNER)

    def test_manifest_binds_each_complete_selected_record(self):
        self.write_all()
        first = self.groups()[0]
        entry = self.assemble()["manifest"]["groups"][0]["records"]["R"]
        stored = self.store.records(self.locale, first["translationGroupId"], "R")
        self.assertEqual(entry, {"inputKey": stored[0]["inputKey"], "recordSha256": records.json_sha256(stored[0])})

    def test_nested_key_order_survives_the_payload_store(self):
        row = copy.deepcopy(self.groups()[0])
        row["semanticReview"] = dict(reversed(list(row["semanticReview"].items())))
        sha = self.payloads.put(row)
        self.assertEqual(list(self.payloads.get(sha)["semanticReview"]), list(row["semanticReview"]))
        self.assertNotEqual(sha, self.payloads.put(self.groups()[0]))

    def test_records_from_an_older_policy_or_runner_are_not_current(self):
        first, second = self.groups()
        self.write_all(skip={(first["translationGroupId"], "T"), (second["translationGroupId"], "T")})
        # The translation policy's model-facing part changed after the first group ran.
        self.record("T", first, inputs=self.current("T", first, modelFacingPolicySha256=records.text_sha256("old")))
        # The second group ran under an older runner.
        self.record("T", second, implementation="b" * 64)
        self.assertEqual(self.refused(), {"T:missing_or_not_current": [first["translationGroupId"],
                                                                       second["translationGroupId"]]})

    def test_a_revision_with_current_inputs_replaces_nothing_but_can_conflict(self):
        self.write_all()
        second = self.groups()[1]
        changed = copy.deepcopy(second)
        changed["semanticReview"]["evidence"] = "A second, different review of the same group."
        self.record("R", changed, inputs=self.current("R", second,
                                                      boundedPayloadSha256=records.text_sha256("other payload")))
        self.assertEqual(self.refused(), {"R:conflict": [second["translationGroupId"]]})

    def test_records_read_from_whole_sermon_products_are_refused(self):
        self.write_all()
        first = self.groups()[0]
        self.record("R", first, provenance={"derivation": "legacy_round_cache"},
                    inputs=self.current("R", first, revisionSha256=records.text_sha256("brief")))
        self.assertEqual(self.refused(), {"R:legacy_planning_only": [first["translationGroupId"]]})

    def test_records_missing_inputs_do_not_count_in_a_production_merge(self):
        first = self.groups()[0]
        self.write_all(skip={(first["translationGroupId"], "T")})
        self.record("T", first, provenance={"derivation": "per_group_pipeline", "notRecorded": ["stageImplementation"]})
        self.assertEqual(self.refused(), {"T:inputs_not_recorded": [first["translationGroupId"]],
                                          "T:missing_or_not_current": [first["translationGroupId"]]})

    def test_unsettled_current_unknown_blocks_its_group(self):
        self.write_all()
        second = self.groups()[1]
        self.record("T", second, verdict="unknown", outputs={},
                    inputs=self.current("T", second, revisionSha256=records.text_sha256("retry")))
        self.assertEqual(self.refused(), {"unknown_outcome_needs_reconciliation": [second["translationGroupId"]]})

    def test_unknown_under_old_inputs_does_not_block(self):
        self.write_all()
        second = self.groups()[1]
        self.record("T", second, verdict="unknown", outputs={},
                    inputs=self.current("T", second, modelSettingsSha256=records.text_sha256("old model")))
        self.assertTrue(self.assemble()["candidate"])

    def test_a_resolution_settles_an_unknown_attempt(self):
        first = self.groups()[0]
        self.write_all(skip={(first["translationGroupId"], "T")})
        unknown = self.record("T", first, verdict="unknown", outputs={})
        reasons = self.refused()
        self.assertIn("unknown_outcome_needs_reconciliation", reasons)
        resolved = records.make_record("T", self.layer1, self.locale, first["translationGroupId"],
                                       first["sourceUnitIds"], unknown["inputs"], RUNNER,
                                       {"draftTextSha256": records.text_sha256("draft " + first["translationGroupId"])},
                                       "pass", provenance={"derivation": "per_group_pipeline",
                                                           "reconciledFrom": "provider_returned_response"})
        self.resolutions.put(unknown, resolved)
        entry = self.assemble()["manifest"]["groups"][0]["records"]["T"]
        self.assertEqual(entry["resolvesUnknownRecordSha256"], records.json_sha256(unknown))
        self.assertEqual(entry["recordSha256"], records.json_sha256(resolved))
        with self.assertRaisesRegex(ValueError, "resolution_must_settle_the_same_attempt"):
            self.resolutions.put(resolved, resolved)

    def test_plugin_record_for_another_plugin_does_not_count(self):
        first = self.groups()[0]
        self.write_all(skip={(first["translationGroupId"], "P")})
        self.record("P", first, implementation="b" * 64)
        self.assertEqual(self.refused(), {"P:missing_for_current_plugin_and_text": [first["translationGroupId"]]})

    def test_review_must_chain_to_its_translator_draft(self):
        first = self.groups()[0]
        self.write_all(skip={(first["translationGroupId"], "T")})
        self.record("T", first, outputs={"draftTextSha256": records.text_sha256("another draft")})
        self.assertEqual(self.refused(), {"R:missing_or_not_current": [first["translationGroupId"]]})

    def test_plugin_record_must_match_a_fresh_plugin_run(self):
        first = self.groups()[0]
        self.write_all(skip={(first["translationGroupId"], "P")})
        self.record("P", first, outputs=subject.plugin_outputs({"recorded": "elsewhere"}, self.payloads))
        with self.assertRaisesRegex(ValueError, "plugin_record_differs_from_fresh_run"):
            self.assemble()

    def test_changed_payload_bytes_are_refused(self):
        self.write_all()
        sha = self.payloads.put(self.groups()[0])
        path = self.payloads.path(sha)
        path.write_bytes(path.read_bytes().replace(b"translate-1", b"translate-9"))
        with self.assertRaisesRegex(ValueError, "payload_changed"):
            self.assemble()

    def legacy(self, *, review_verdict="pass", review_text=None):
        out = {}
        for row in self.groups():
            text = review_text or "".join(row["targetUtterances"])
            out[row["translationGroupId"]] = {
                "T": records.make_record("T", self.layer1, self.locale, row["translationGroupId"],
                                         row["sourceUnitIds"], self.current("T", row), RUNNER,
                                         {"draftTextSha256": records.text_sha256("draft " + row["translationGroupId"])},
                                         "pass", provenance={"derivation": "legacy_round_cache"}),
                "R": records.make_record("R", self.layer1, self.locale, row["translationGroupId"],
                                         row["sourceUnitIds"], self.current("R", row), RUNNER,
                                         {"targetTextSha256": records.text_sha256(text)}, review_verdict,
                                         codes=["semantic_review_not_passed"] if review_verdict == "fail" else (),
                                         provenance={"derivation": "legacy_round_cache"})}
        return out

    def test_equivalence_records_count_only_inside_the_equivalence_check(self):
        skipped = subject.equivalence_records(self.fixture.evidence, self.receipt, self.legacy(),
                                              self.store, self.payloads)
        self.assertEqual(skipped, [])
        reasons = self.refused()
        self.assertLessEqual({f"{stage}:equivalence_record_outside_check" for stage in ("T", "R", "P")}, set(reasons))
        with self.assertRaisesRegex(ValueError, "runner_identity_required"):
            subject.select(self.store, self.fixture.anchor, self.fixture.policy, self.layer1, self.locale,
                           list(self.plan.values()), dict(self.identity, runnerImplementationSha256=None))
        result = self.assemble(equivalence_check=True)
        self.assertEqual(subject.file_bytes(result["candidate"]), subject.file_bytes(self.fixture.admit(self.receipt)))
        self.assertTrue(result["manifest"]["equivalenceCheck"])
        self.assertIsNone(result["manifest"]["runnerImplementationSha256"])

    def test_equivalence_split_needs_a_passing_review_of_the_same_text(self):
        everyone = [row["translationGroupId"] for row in self.groups()]
        for legacy in (self.legacy(review_verdict="fail"), self.legacy(review_text="另一段译文。"), {}):
            store = records.RecordStore(self.root / str(len(legacy)) / str(id(legacy)))
            payloads = subject.PayloadStore(store.root)
            self.assertEqual(subject.equivalence_records(self.fixture.evidence, self.receipt, legacy, store,
                                                         payloads), everyone)
            self.assertEqual(store.records(self.locale, everyone[0], "R"), [])


if __name__ == "__main__":
    unittest.main()
