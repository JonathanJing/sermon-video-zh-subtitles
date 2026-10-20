"""Per-group orchestration: status, paid run gating and merge (DEV-GRP-006/007)."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tests import test_produce_target_language_candidate as candidate_fixture
from tests.test_layer2_payload_cache_reuse import _Caller
from tongxing_production.orchestration import group_budget
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
        self.assertFalse(merged["releaseEligible"])
        self.assertFalse(merged["humanApproval"])
        directory = self.root / "merge" / self.config["locale"]
        self.assertTrue((directory / "candidate.json").is_file())
        self.assertTrue((directory / "merge-manifest.json").is_file())
        on_disk = json.loads((directory / "merge-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(on_disk["schemaVersion"], group_pipeline.MERGE_SCHEMA)
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
        directory = self.root / "merge" / self.config["locale"]
        self.assertEqual(json.loads((directory / "merge-manifest.json").read_text(encoding="utf-8")),
                         json.loads((directory / "merge-manifest.json").read_text(encoding="utf-8")))

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

    def test_merge_before_any_run_refuses_with_group_ids(self):
        report = group_pipeline.merge(self.config)
        self.assertEqual(report["outcome"], "refused")
        self.assertTrue(report["reasons"])
        self.assertTrue(all(isinstance(ids, list) for ids in report["reasons"].values()))
        directory = self.root / "merge" / self.config["locale"]
        self.assertFalse((directory / "candidate.json").exists())

    def test_cli_status_and_merge_use_the_config(self):
        self.assertEqual(group_pipeline.main(["status", "--config", str(self.config_path)]), 0)
        self.assertEqual(group_pipeline.main(["merge", "--config", str(self.config_path)]), 4)
        self.run_all()
        self.assertEqual(group_pipeline.main(["merge", "--config", str(self.config_path)]), 0)
        self.assertEqual(group_pipeline.main(["merge", "--config", str(self.config_path)]), 0)


if __name__ == "__main__":
    unittest.main()
