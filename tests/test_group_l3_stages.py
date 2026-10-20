"""Layer 3 stage runner: order, resume, failure and refusal (DEV-GRP-006, steps 7-9)."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.orchestration import group_l3


PY = sys.executable


class GroupL3StagesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in ("source", "anchor", "candidate", "policy", "adapter", "registry", "speechJob"):
            (self.root / f"{name}.json").write_text("{}", encoding="utf-8")
        self.out = self.root / "run"
        self.out.mkdir()
        self.config_path = self.root / "stages.json"

    def write_config(self, stages, paths=None):
        paths = paths or {name: f"{name}.json" for name in
                          ("source", "anchor", "candidate", "policy", "adapter", "registry", "speechJob")}
        paths = {**paths, "mergeDir": "merge"}
        self.config_path.write_text(json.dumps({
            "schemaVersion": group_l3.CONFIG_SCHEMA, "paths": paths, "stages": stages,
        }, ensure_ascii=False), encoding="utf-8")
        return self.config_path

    @staticmethod
    def write_stage(name, target, content="x"):
        return {"name": name,
                "command": [PY, "-c",
                            f"import pathlib; pathlib.Path(r'{{out}}/{target}').write_text({content!r})"],
                "produces": target}

    def execute(self, **kwargs):
        return group_l3.run_stages(group_l3.load_configuration(self.config_path), self.out, **kwargs)

    def test_runs_stages_in_order_and_records_a_receipt(self):
        self.write_config([self.write_stage("formal_render", "rendered.json"),
                           self.write_stage("package", "package.json")])
        report = self.execute()
        self.assertEqual(report["status"], "completed")
        self.assertEqual([row["status"] for row in report["stages"]], ["done", "done"])
        self.assertTrue((self.out / "rendered.json").is_file())
        self.assertTrue((self.out / "package.json").is_file())
        on_disk = json.loads((self.out / "stage-report.json").read_text(encoding="utf-8"))
        self.assertEqual(on_disk["schemaVersion"], group_l3.REPORT_SCHEMA)
        self.assertEqual(len(on_disk["stages"][0]["commandSha256"]), 64)
        self.assertFalse(on_disk["releaseEligible"])
        self.assertFalse(on_disk["humanApproval"])

    def test_second_run_skips_existing_products(self):
        self.write_config([self.write_stage("formal_render", "rendered.json")])
        self.execute()
        report = self.execute()
        self.assertEqual(report["stages"][0]["status"], "skipped_existing")

    def test_a_failing_stage_stops_the_remaining_stages(self):
        self.write_config([
            {"name": "formal_render", "command": [PY, "-c", "raise SystemExit(3)"], "produces": "rendered.json"},
            self.write_stage("package", "package.json"),
        ])
        with self.assertRaises(group_l3.StageRefused) as caught:
            self.execute()
        self.assertEqual(caught.exception.stage, "formal_render")
        self.assertFalse((self.out / "package.json").exists())
        report = json.loads((self.out / "stage-report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["stages"][-1]["exitCode"], 3)

    def test_failure_reads_the_producers_group_ids(self):
        command = ("import json, pathlib; "
                   "pathlib.Path(r'{out}/qc.json').write_text("
                   "json.dumps({'failedGroups': ['g1', 'g2']})); raise SystemExit(1)")
        self.write_config([{"name": "audio_qc", "command": [PY, "-c", command],
                            "produces": "qc-done.json", "failures": "qc.json"}])
        with self.assertRaises(group_l3.StageRefused) as caught:
            self.execute()
        self.assertEqual(caught.exception.group_ids, ["g1", "g2"])
        report = json.loads((self.out / "stage-report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["stages"][-1]["failedGroupIds"], ["g1", "g2"])
        self.assertEqual(report["nextActions"], [{"action": "redo", "groupIds": ["g1", "g2"],
                                                  "reason": "audio_qc failed"}])

    def test_success_without_the_named_product_is_refused(self):
        self.write_config([{"name": "formal_render", "command": [PY, "-c", "pass"], "produces": "missing.json"}])
        with self.assertRaisesRegex(group_l3.StageRefused, "produces_missing"):
            self.execute()

    def test_dry_run_plans_without_running(self):
        self.write_config([self.write_stage("formal_render", "rendered.json")])
        report = self.execute(dry_run=True)
        self.assertEqual(report["status"], "planned")
        self.assertEqual(report["stages"][0]["status"], "planned")
        self.assertFalse((self.out / "rendered.json").exists())

    def test_declared_variables_interpolate_into_commands(self):
        self.write_config([{"name": "formal_render",
                            "command": [PY, "-c", "import pathlib; pathlib.Path(r'{out}/{locale}-{code}.txt').write_text('x')"],
                            "produces": "ko-abc.txt"}], paths=None)
        config = json.loads(self.config_path.read_text(encoding="utf-8"))
        config["variables"] = {"locale": "ko", "code": "abc"}
        self.config_path.write_text(json.dumps(config), encoding="utf-8")
        self.execute()
        self.assertTrue((self.out / "ko-abc.txt").is_file())

    def test_unknown_placeholder_is_refused_before_dispatch(self):
        self.write_config([{"name": "formal_render",
                            "command": [PY, "-c", "pass", "{nope}"], "produces": "x.json"}])
        with self.assertRaisesRegex(ValueError, "unknown_placeholder"):
            self.execute()

    def test_group_tasks_stages_dispatches_to_the_stage_runner(self):
        from tongxing_production.orchestration import group_pipeline
        self.write_config([self.write_stage("formal_render", "rendered.json")])
        code = group_pipeline.main(["stages", "--config", str(self.config_path), "--out", str(self.out)])
        self.assertEqual(code, 0)
        self.assertTrue((self.out / "rendered.json").is_file())

    def test_the_draft_plan_parses_and_plans_five_stages(self):
        draft_path = Path(__file__).parents[1] / "config/group-l3-stages.draft.json"
        draft = json.loads(draft_path.read_text(encoding="utf-8"))
        for name in group_l3.REQUIRED_PATHS:
            (self.root / f"{name}.json").write_text("{}", encoding="utf-8")
            draft["paths"][name] = f"{name}.json"
        draft["variables"].update(python=PY, stageDir=str(self.root))
        self.config_path.write_text(json.dumps(draft), encoding="utf-8")
        report = self.execute(dry_run=True)
        self.assertEqual([row["name"] for row in report["stages"]],
                         ["formal_render", "compact", "screen", "package", "audio_qc"])
        self.assertEqual({row["status"] for row in report["stages"]}, {"planned"})

    def test_cli_returns_five_on_a_failed_stage(self):
        self.write_config([{"name": "formal_render", "command": [PY, "-c", "raise SystemExit(2)"],
                            "produces": "x.json"}])
        self.assertEqual(group_l3.main(["--config", str(self.config_path), "--out", str(self.out)]), 5)


if __name__ == "__main__":
    unittest.main()
