"""Lanes: one GPU slot across locales, CPU stages overlap, a failing lane stays alone."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.orchestration import group_l3, group_l3_lanes


PY = sys.executable
REQUIRED = ("source", "anchor", "candidate", "policy", "adapter", "registry", "speechJob")


def timed_stage(name, resource, seconds, target, fail=False):
    """A stage that records its own wall-clock interval into its product."""
    code = (f"import json,pathlib,time; t0=time.time(); time.sleep({seconds}); "
            f"pathlib.Path(r'{{out}}/{target}').write_text(json.dumps([t0, time.time()]))"
            + ("; raise SystemExit(3)" if fail else ""))
    return {"name": name, "resource": resource, "command": [PY, "-c", code], "produces": target}


class GroupL3LanesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in REQUIRED:
            (self.root / f"{name}.json").write_text("{}", encoding="utf-8")

    def write_lane(self, locale, stages):
        directory = self.root / locale
        directory.mkdir()
        (directory / "run").mkdir()
        (directory / "l3-stages.json").write_text(json.dumps({
            "schemaVersion": group_l3.CONFIG_SCHEMA,
            "paths": {name: f"../{name}.json" for name in REQUIRED}, "stages": stages}), encoding="utf-8")
        return {"locale": locale, "config": f"{locale}/l3-stages.json", "out": f"{locale}/run"}

    def write_lanes(self, lanes):
        path = self.root / "lanes.json"
        path.write_text(json.dumps({"schemaVersion": group_l3_lanes.CONFIG_SCHEMA, "lanes": lanes}), encoding="utf-8")
        return path

    def interval(self, locale, target):
        return json.loads((self.root / locale / "run" / target).read_text())

    def test_gpu_stages_take_turns_while_cpu_stages_overlap(self):
        lanes = self.write_lanes([
            self.write_lane("zh", [timed_stage("formal_render", "gpu", 0.3, "render.json"),
                                   timed_stage("compact", "cpu", 1.0, "compact.json"),
                                   timed_stage("screen", "gpu", 0.2, "screen.json")]),
            self.write_lane("ko", [timed_stage("formal_render", "gpu", 0.5, "render.json")]),
        ])
        report = group_l3_lanes.run_lanes(group_l3_lanes.load_configuration(lanes), self.root / "lanes")
        self.assertEqual(report["status"], "completed")
        self.assertEqual([lane["status"] for lane in report["lanes"]], ["completed", "completed"])
        zh_render, zh_compact, zh_screen = (self.interval("zh", f"{n}.json") for n in ("render", "compact", "screen"))
        ko_render = self.interval("ko", "render.json")
        # The lowest lane renders first; the GPU is never shared.
        self.assertLessEqual(zh_render[1], ko_render[0] + 0.05)
        self.assertLessEqual(ko_render[1], zh_screen[0] + 0.05)
        # ko's render ran while zh compacted: the overlap this scheduler exists for.
        self.assertLess(ko_render[0], zh_compact[1])
        self.assertLess(zh_compact[0], ko_render[1])
        self.assertIn({"cpuStage": {"locale": "zh", "stage": "compact"},
                       "gpuStage": {"locale": "ko", "stage": "formal_render"}}, report["overlaps"])
        on_disk = json.loads((self.root / "lanes" / "lanes-report.json").read_text())
        self.assertEqual(on_disk["schemaVersion"], group_l3_lanes.REPORT_SCHEMA)
        self.assertFalse(on_disk["releaseEligible"])
        ko_stage = on_disk["lanes"][1]["stages"][0]
        self.assertEqual(ko_stage["resource"], "gpu")
        self.assertGreater(ko_stage["waitSeconds"], 0.2)
        zh_stage_report = json.loads((self.root / "zh/run/stage-report.json").read_text())
        self.assertEqual([row["resource"] for row in zh_stage_report["stages"]], ["gpu", "cpu", "gpu"])

    def test_a_failing_lane_does_not_stop_the_other_lane(self):
        lanes = self.write_lanes([
            self.write_lane("zh", [timed_stage("formal_render", "gpu", 0.1, "render.json", fail=True),
                                   timed_stage("compact", "cpu", 0.1, "compact.json")]),
            self.write_lane("ko", [timed_stage("formal_render", "gpu", 0.1, "render.json"),
                                   timed_stage("compact", "cpu", 0.1, "compact.json")]),
        ])
        report = group_l3_lanes.run_lanes(group_l3_lanes.load_configuration(lanes), self.root / "lanes")
        self.assertEqual(report["status"], "failed")
        zh, ko = report["lanes"]
        self.assertEqual((zh["status"], zh["stage"], zh["reason"]), ("failed", "formal_render", "exit 3"))
        self.assertFalse((self.root / "zh/run/compact.json").exists())
        self.assertEqual(ko["status"], "completed")
        self.assertTrue((self.root / "ko/run/compact.json").is_file())

    def test_dry_run_plans_every_lane_without_running(self):
        lanes = self.write_lanes([self.write_lane("zh", [timed_stage("formal_render", "gpu", 0.1, "render.json")]),
                                  self.write_lane("ko", [timed_stage("formal_render", "gpu", 0.1, "render.json")])])
        report = group_l3_lanes.run_lanes(group_l3_lanes.load_configuration(lanes), self.root / "lanes", dry_run=True)
        self.assertEqual(report["status"], "planned")
        self.assertEqual([lane["stages"][0]["status"] for lane in report["lanes"]], ["planned", "planned"])
        self.assertFalse((self.root / "zh/run/render.json").exists())

    def test_duplicate_locale_or_output_is_refused(self):
        zh = self.write_lane("zh", [timed_stage("formal_render", "gpu", 0.1, "render.json")])
        with self.assertRaisesRegex(ValueError, "duplicate_group_l3_lane"):
            group_l3_lanes.load_configuration(self.write_lanes([zh, dict(zh, locale="ko")]))
        with self.assertRaisesRegex(ValueError, "duplicate_group_l3_lane"):
            group_l3_lanes.load_configuration(self.write_lanes([zh, dict(zh, out="zh/run")]))

    def test_unlabeled_stages_default_to_the_gpu_and_bad_labels_are_refused(self):
        stage = timed_stage("formal_render", "gpu", 0.0, "render.json")
        del stage["resource"]
        self.assertEqual(group_l3.stage_resource(stage), "gpu")
        lane = self.write_lane("zh", [dict(stage, resource="tpu")])
        with self.assertRaisesRegex(ValueError, "invalid_group_l3_stage"):
            group_l3.load_configuration(self.root / lane["config"])

    def test_group_tasks_lanes_dispatches_and_returns_five_on_failure(self):
        from tongxing_production.orchestration import group_pipeline
        lanes = self.write_lanes([self.write_lane("zh", [timed_stage("formal_render", "gpu", 0.0, "render.json", fail=True)])])
        self.assertEqual(group_pipeline.main(["lanes", "--config", str(lanes), "--out", str(self.root / "lanes")]), 5)
        lanes_ok = self.write_lanes([self.write_lane("ko", [timed_stage("formal_render", "gpu", 0.0, "render.json")])])
        self.assertEqual(group_pipeline.main(["lanes", "--config", str(lanes_ok), "--out", str(self.root / "lanes2")]), 0)

    def test_the_draft_lanes_plan_parses_with_the_draft_stage_plan(self):
        repo = Path(__file__).parents[1]
        stage_draft = json.loads((repo / "config/group-l3-stages.draft.json").read_text(encoding="utf-8"))
        self.assertEqual([stage["resource"] for stage in stage_draft["stages"]], ["gpu", "cpu", "cpu"])
        lanes_draft = json.loads((repo / "config/group-l3-lanes.draft.json").read_text(encoding="utf-8"))
        for lane in lanes_draft["lanes"]:
            directory = self.root / lane["locale"]
            directory.mkdir()
            plan = dict(stage_draft, paths={**stage_draft["paths"], **{name: f"../{name}.json" for name in REQUIRED}})
            plan["variables"].update(python=PY, stageDir=str(self.root))
            (directory / "l3-stages.json").write_text(json.dumps(plan), encoding="utf-8")
        path = self.root / "lanes.json"
        path.write_text(json.dumps(lanes_draft), encoding="utf-8")
        report = group_l3_lanes.run_lanes(group_l3_lanes.load_configuration(path), self.root / "lanes", dry_run=True)
        self.assertEqual([lane["locale"] for lane in report["lanes"]], ["zh-Hans", "ko", "es"])
        self.assertEqual(report["status"], "planned")


if __name__ == "__main__":
    unittest.main()
