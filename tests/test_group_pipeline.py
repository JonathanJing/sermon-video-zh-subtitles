"""Per-group orchestration: status, paid run gating and merge (DEV-GRP-006/007)."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tests import test_prepare_target_language_speech_job as speech_fixture
from tests import test_produce_target_language_candidate as candidate_fixture
from tests.test_layer2_payload_cache_reuse import _Caller
from tongxing_production.orchestration import group_budget
from tongxing_production.orchestration import group_records as records
from tongxing_production.orchestration import group_pipeline
from tongxing_production.text import models


class GroupPipelineTests(unittest.TestCase):
    def setUp(self):
        fixture = candidate_fixture.ProduceTargetLanguageCandidateTests(
            "test_compiles_valid_candidate_without_human_approval")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        plan = models.group_plan(fixture.request, fixture.anchor)
        for row, group in zip(fixture.evidence["groups"], plan):
            row["translationGroupId"] = group["translationGroupId"]
        self.plan = plan
        self.groups = {tuple(row["sourceUnitIds"]): row for row in fixture.evidence["groups"]}
        self.config_path = self.root / "run.json"
        for name, value in (("source", fixture.source), ("anchor", fixture.anchor), ("policy", fixture.policy)):
            (self.root / f"{name}.json").write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        self.config_path.write_text(json.dumps({
            "schemaVersion": "sermon-group-run-config-v1",
            "source": "source.json", "anchor": "anchor.json",
            "locale": fixture.request["targetLocale"], "policy": "policy.json",
            "plugin": str(fixture.plugin_path),
            "records": "records", "work": "work", "merge": "merge",
        }, ensure_ascii=False), encoding="utf-8")
        self.config = group_pipeline.group_worker.load_configuration(self.config_path)

    def merge_dir(self):
        root = self.root / "merge" / self.config["locale"]
        pointer = json.loads((root / "current.json").read_text(encoding="utf-8"))
        return root / pointer["directory"]

    def caller(self, **options):
        return _Caller(self, **options)

    def run_all(self, caller=None, budget=None):
        caller = caller or self.caller()
        report = group_pipeline.run(self.config, [], budget=budget, caller=caller, api_key="fixture-key")
        return report, caller

    def test_status_is_read_only_and_reports_missing_stages(self):
        report = group_pipeline.status(self.config)
        self.assertEqual(report["schemaVersion"], group_pipeline.STATUS_SCHEMA)
        self.assertFalse(report["dispatched"])
        self.assertFalse(report["readyToMerge"])
        self.assertEqual(report["groupCount"], len(self.plan))
        self.assertEqual(report["summary"]["T"], {"missing": len(self.plan)})
        for row in report["groups"]:
            self.assertEqual(row["blockers"][0]["stage"], "T")
        self.assertEqual(list((self.root / "records").glob("**/*.json")), [])

    def test_run_executes_stale_groups_and_then_merges(self):
        report, caller = self.run_all()
        self.assertEqual([row["outcome"] for row in report["results"]], ["pass"] * len(self.plan))
        self.assertEqual(len(caller.calls), 2 * len(self.plan))
        status = group_pipeline.status(self.config)
        self.assertTrue(status["readyToMerge"])
        merged = group_pipeline.merge(self.config)
        self.assertEqual(merged["outcome"], "candidate_ready_layer3_pending")
        self.assertEqual(merged["groupCount"], len(self.plan))
        self.assertEqual(merged["completedSteps"],
                         ["readiness", "candidate_assembly", "whole_text_checks"])
        self.assertIn("speech_job_v3", merged["pendingSteps"])
        self.assertEqual(merged["layer3Preflight"]["candidateShape"], "pass")
        self.assertFalse(merged["layer3Preflight"]["admissible"])
        self.assertFalse(merged["releaseEligible"])
        self.assertFalse(merged["humanApproval"])
        directory = self.merge_dir()
        self.assertTrue((directory / "candidate.json").is_file())
        self.assertTrue((directory / "merge-manifest.json").is_file())
        on_disk = json.loads((directory / "merge-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(on_disk["schemaVersion"], group_pipeline.MERGE_SCHEMA)
        layer3 = group_pipeline.status(self.config)["layer3"]
        self.assertEqual(layer3["merge"], "merged")
        self.assertEqual(layer3["preparation"], "not_prepared")
        (directory / "l3-preparation.json").write_text(json.dumps(
            {"speechJobSha256": "a" * 64, "speechJobPath": "/tmp/job.json"}), encoding="utf-8")
        (directory / "l3-stages.json").write_text(json.dumps(
            {"status": "completed", "stages": [{"name": "formal_render"}]}), encoding="utf-8")
        layer3 = group_pipeline.status(self.config)["layer3"]
        self.assertEqual(layer3["preparation"], "prepared")
        self.assertEqual(layer3["stages"], "completed")
        self.assertEqual(layer3["stageNames"], ["formal_render"])
        self.assertEqual(on_disk["pendingSteps"], list(group_pipeline.PENDING_STEPS))

    def test_run_skips_groups_a_budget_did_not_reserve(self):
        budget = {"schemaVersion": group_budget.SCHEMA, "groups": []}
        report, caller = self.run_all(budget=budget)
        self.assertEqual({row["outcome"] for row in report["results"]}, {"refused"})
        self.assertEqual(caller.calls, [])

    def test_second_merge_without_changes_is_stable(self):
        self.run_all()
        first = group_pipeline.merge(self.config)
        self.assertEqual(first["outcome"], "candidate_ready_layer3_pending")
        second = group_pipeline.merge(self.config)
        self.assertEqual(second["outcome"], "candidate_ready_layer3_pending")
        self.assertEqual(second["changedGroupIds"], [])
        self.assertEqual(first["candidateSha256"], second["candidateSha256"])
        directory = self.merge_dir()
        self.assertTrue((directory / "merge-manifest.json").is_file())

    def test_merge_refuses_an_affected_list_that_does_not_match(self):
        self.run_all()
        self.assertEqual(group_pipeline.merge(self.config)["outcome"], "candidate_ready_layer3_pending")
        refused = group_pipeline.merge(self.config, affected=[self.plan[0]["translationGroupId"]])
        self.assertEqual(refused["outcome"], "refused")
        self.assertEqual(refused["missingChangedGroupIds"], [self.plan[0]["translationGroupId"]])
        self.assertEqual(refused["reasons"], {"changed_groups_not_affected": [self.plan[0]["translationGroupId"]]})

    def test_changed_groups_compares_selected_record_hashes(self):
        current = {"groups": [{"translationGroupId": "g1", "records": {"T": {"inputKey": "a", "recordSha256": "1"}}},
                              {"translationGroupId": "g2", "records": {"R": {"inputKey": "b", "recordSha256": "2"}}}]}
        previous = {"assembly": {"groups": [
            {"translationGroupId": "g1", "records": {"T": {"inputKey": "a", "recordSha256": "1"}}},
            {"translationGroupId": "g2", "records": {"R": {"inputKey": "old", "recordSha256": "0"}}}]}}
        self.assertEqual(group_pipeline._changed_groups(previous, current), {"g2"})
        self.assertEqual(group_pipeline._changed_groups(None, current), {"g1", "g2"})

    def test_redo_records_the_reason_and_reruns_only_the_listed_group(self):
        caller = self.caller()
        self.run_all(caller)
        self.assertEqual(group_pipeline.merge(self.config)["outcome"], "candidate_ready_layer3_pending")
        group_id = self.plan[0]["translationGroupId"]
        before = len(caller.calls)
        report = group_pipeline.redo(self.config, [group_id], "请更贴近原文",
                                     budget=None, caller=caller, api_key="fixture-key")
        self.assertEqual([row["outcome"] for row in report["results"]], ["pass"])
        self.assertEqual(report["operatorDirective"]["groupIds"], [group_id])
        self.assertEqual(len(caller.calls) - before, 2)
        self.assertTrue(any("请更贴近原文" in json.dumps(payload, ensure_ascii=False)
                            for payload in caller.calls[-2:]))
        status = group_pipeline.status(self.config)
        row = next(item for item in status["groups"] if item["translationGroupId"] == group_id)
        self.assertEqual(row["stages"]["T"]["status"], "fresh")
        store = records.RecordStore(self.config["records"])
        self.assertEqual(len(store.records(self.config["locale"], group_id, "T")), 2)
        refused = group_pipeline.merge(self.config)
        self.assertEqual(refused["outcome"], "refused")
        self.assertEqual(refused["unexpectedGroupIds"], [group_id])
        merged = group_pipeline.merge(self.config, affected=[group_id])
        self.assertEqual(merged["outcome"], "candidate_ready_layer3_pending")
        self.assertEqual(merged["changedGroupIds"], [group_id])
        self.assertEqual(group_pipeline.load_directives(self.config)[group_id]["note"], "请更贴近原文")

    def test_prepare_l3_uses_the_speech_job_producer(self):
        fixture = speech_fixture.TargetLanguageSpeechJobTests(
            "test_korean_candidate_and_prepared_job_match_published_contracts")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        merge_root = self.root / "l3merge" / "ko"
        merge_root.mkdir(parents=True)
        (merge_root / "candidate.json").write_bytes(fixture.candidate_path.read_bytes())
        (merge_root / "current.json").write_text(json.dumps({"directory": "."}), encoding="utf-8")
        config = {"source": fixture.source_package_path, "anchor": fixture.anchor_path,
                  "policy": fixture.policy_path, "locale": "ko", "merge": self.root / "l3merge",
                  "records": self.root / "l3records"}
        out = self.root / "l3job"
        group_pipeline.release_basis(config, fixture.human_review_receipt_path)
        with self.assertRaisesRegex(ValueError, "text_basis_differs"):
            group_pipeline.prepare_l3(
                config, text_basis=self.root / "source.json", adapter=fixture.adapter_path,
                registry=fixture.registry_path, out=self.root / "l3job-wrong")
        receipt = group_pipeline.prepare_l3(
            config, text_basis=fixture.human_review_receipt_path, adapter=fixture.adapter_path,
            registry=fixture.registry_path, out=out)
        self.assertEqual(receipt["schemaVersion"], group_pipeline.L3_PREPARATION_SCHEMA)
        self.assertTrue((out / "job.json").is_file())
        self.assertTrue((out / "l3-preparation.json").is_file())
        self.assertTrue((merge_root / "l3-preparation.json").is_file())
        self.assertEqual(receipt["speechJobStatus"], "prepared_adapter_validation_required")
        self.assertEqual(receipt["pendingSteps"][0], "formal_render")
        self.assertFalse(receipt["releaseEligible"])
        self.assertFalse(receipt["humanApproval"])

    def test_compare_offline_accepts_consistent_products(self):
        import hashlib
        sha = lambda value: hashlib.sha256(value.encode()).hexdigest()
        text = "要记得起初的爱。"
        checks = [{"checkId": "natural", "status": "pass", "evidence": "e"}]
        candidate = {"schemaVersion": "candidate", "targetLocale": "zh-Hans",
                     "englishSourcePackageJsonSha256": "1" * 64, "anchorManifestSha256": "2" * 64,
                     "translationPolicySha256": "3" * 64,
                     "groups": [{"translationGroupId": "g1", "sourceUnitIds": ["u1"],
                                 "targetUtterances": [text], "languageReview": {"checks": checks}}]}
        receipt = {"englishSourcePackageJsonSha256": "1" * 64, "anchorManifestSha256": "2" * 64,
                   "translationPolicySha256": "3" * 64,
                   "groupReviews": [{"translationGroupId": "g1", "targetTextSha256": sha(text),
                                     "status": "pass", "checks": checks}]}
        derived = {"g1": {"T": {"verdict": {"status": "pass"}, "spend": {"requestId": "t1"}},
                          "R": {"verdict": {"status": "pass"},
                                "outputs": {"targetTextSha256": sha(text)}, "spend": {"requestId": "r1"}}}}
        report = group_pipeline.compare_offline(candidate, receipt, derived)
        self.assertTrue(report["consistent"])
        self.assertEqual(report["mismatchCount"], 0)
        broken = dict(receipt, groupReviews=[dict(receipt["groupReviews"][0], targetTextSha256="0" * 64)])
        self.assertFalse(group_pipeline.compare_offline(candidate, broken, derived)["consistent"])

    def test_plan_subcommand_reaches_its_own_parser(self):
        with self.assertRaises(SystemExit) as caught:
            group_pipeline.main(["plan", "--help"])
        self.assertEqual(caught.exception.code, 0)

    def test_release_basis_binds_the_existing_receipt_to_the_candidate(self):
        fixture = speech_fixture.TargetLanguageSpeechJobTests(
            "test_korean_candidate_and_prepared_job_match_published_contracts")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        merge_root = self.root / "rb" / "ko"
        merge_root.mkdir(parents=True)
        (merge_root / "candidate.json").write_bytes(fixture.candidate_path.read_bytes())
        (merge_root / "current.json").write_text(json.dumps({"directory": "."}), encoding="utf-8")
        config = {"source": fixture.source_package_path, "anchor": fixture.anchor_path,
                  "policy": fixture.policy_path, "locale": "ko", "merge": self.root / "rb",
                  "records": self.root / "rbrecords"}
        record = group_pipeline.release_basis(config, fixture.human_review_receipt_path)
        self.assertEqual(record["schemaVersion"], group_pipeline.TEXT_RELEASE_SCHEMA)
        self.assertEqual(record["reviewKind"], "human_review")
        self.assertFalse(record["humanApproval"])
        self.assertTrue((merge_root / "text-release.json").is_file())
        other = json.loads(fixture.human_review_receipt_path.read_text(encoding="utf-8"))
        other["candidateJsonSha256"] = "0" * 64
        bad = self.root / "bad-receipt.json"
        bad.write_text(json.dumps(other), encoding="utf-8")
        with self.assertRaises(ValueError):
            group_pipeline.release_basis(config, bad)

    def test_merge_before_any_run_refuses_with_group_ids(self):
        report = group_pipeline.merge(self.config)
        self.assertEqual(report["outcome"], "refused")
        self.assertTrue(report["reasons"])
        self.assertTrue(all(isinstance(ids, list) for ids in report["reasons"].values()))
        self.assertTrue(report["nextActions"])
        known = {group["translationGroupId"] for group in self.plan}
        for action in report["nextActions"]:
            self.assertIn(action["action"], {"run", "redo", "reconcile", "merge"})
            self.assertTrue(set(action["groupIds"]) <= known)
        self.assertFalse((self.root / "merge" / self.config["locale"] / "current.json").exists())

    def test_cli_status_and_merge_use_the_config(self):
        self.assertEqual(group_pipeline.main(["status", "--config", str(self.config_path)]), 0)
        self.assertEqual(group_pipeline.main(["merge", "--config", str(self.config_path)]), 4)
        self.run_all()
        self.assertEqual(group_pipeline.main(["merge", "--config", str(self.config_path)]), 0)
        self.assertEqual(group_pipeline.main(["merge", "--config", str(self.config_path)]), 0)


if __name__ == "__main__":
    unittest.main()
