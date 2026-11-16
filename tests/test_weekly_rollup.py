"""Weekly rollup: fixed metrics from run reports, reviewer decisions, and next week's check."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from tools.development import weekly_frontend as frontend
from tools.development import weekly_rollup as rollup

RETROSPECTIVE = """# 复盘：{name}

## 结论先行

已发布。

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| L4 发布 | 漏发对齐 | 清单不全 | 发布后（用户指出） | 补发 | gate | — |
| L3 数字 | 千分位读错 | 表缺项 | 预检（合成前） | 补表 | 有 | abc123 |

## 可以改进的地方

| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 流程 | 开跑前写发布意图清单 | 首轮漏 3 件 | 省 25m | 主代理 | 待开 backlog |
| 预检 | 首次部署前干跑英文包 | 多走 4 次 replace | 省 2 次部署 | 主代理 | 待开 backlog |
"""


def journal(rows):
    return "".join(json.dumps({"at": f"2026-11-{day:02d}T{clock}+00:00", "stage": stage, "event": event}) + "\n"
                   for day, clock, stage, event in rows)


class WeeklyRollupTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.reports = self.base / "runs"
        self.weekly = self.base / "weekly"

    def report(self, name, *, day, deploys, publish_starts=1, structured=True, evidence=True):
        root = self.reports / name
        run = root / f"{name}-zh"
        run.mkdir(parents=True)
        if not structured:
            (root / "INDEX.md").write_text("# hand written\n", encoding="utf-8")
            (root / "RETROSPECTIVE.md").write_text("# hand written\n\n- 复盘要点\n", encoding="utf-8")
            return root
        (root / "manifest.json").write_text(json.dumps({"schemaVersion": "sermon-run-digest-v1", "runs": [], "files": []}))
        rows = [(day, "01:00:00", "l3.finish", "started"), (day, "01:10:00", "l3.finish", "finished"),
                (day, "01:10:00", "l4.preflight", "started"), (day, "01:10:30", "l4.preflight", "failed")]
        for index in range(publish_starts):
            rows += [(day, f"02:{index:02d}:00", "l4.publish", "started"), (day, f"02:{index:02d}:30", "l4.publish", "finished")]
        (run / "journal.ndjson").write_text(journal(rows))
        for index in range(deploys):
            stage = root / f"{name}-publish" / f"stage{index}"
            stage.mkdir(parents=True)
            (stage / "deployment-attempt-v2.json").write_text(json.dumps({"status": "deployed"}))
        (root / f"{name}-publish" / "publish-gate.json").write_text(json.dumps({"status": "pass", "failed": []}))
        (root / "RETROSPECTIVE.md").write_text(RETROSPECTIVE.format(name=name), encoding="utf-8")
        if evidence:
            (root / "private-evidence.json").write_text(json.dumps({"uploaded": True, "bundles": [{"runName": name}]}))
        return root

    def build(self, week, **kwargs):
        weekly = rollup.build(week, reports_root=self.reports, weekly_root=self.weekly, now="2026-11-16T00:00:00+00:00",
                              **kwargs)
        target = self.weekly / week
        target.mkdir(parents=True, exist_ok=True)
        (target / "weekly.json").write_text(json.dumps(weekly, ensure_ascii=False, indent=2))
        (target / "WEEKLY.md").write_text(rollup.render(weekly), encoding="utf-8")
        return weekly

    def test_week_must_be_a_sunday_and_window_is_seven_days(self):
        with self.assertRaises(ValueError):
            rollup.parse_week("20261114")
        self.report("20261108-page", day=8, deploys=1)
        self.report("20261109-experiment", day=9, deploys=0, structured=False)
        self.report("20261115-page", day=15, deploys=1)
        names = [p.name for p in rollup.reports_in_week(self.reports, rollup.parse_week("20261115"))]
        self.assertEqual(names, ["20261109-experiment", "20261115-page"])
        self.assertEqual(rollup.latest_sunday(rollup.parse_week("20261115").replace(day=18)), "20261115")

    def test_metrics_come_from_copied_evidence(self):
        self.report("20261108-page", day=8, deploys=5, publish_starts=3)
        self.report("20261108-hotfix", day=8, deploys=0, structured=False, evidence=False)
        weekly = self.build("20261108")
        metrics = weekly["metrics"]
        self.assertEqual((metrics["reports.total"], metrics["reports.production"]), (2, 1))
        self.assertEqual(metrics["publish.deployAttempts"], 5)
        self.assertEqual(metrics["publish.maxDeployAttemptsPerReport"], 5)
        self.assertEqual(metrics["publish.failedGateEvents"], 1)
        self.assertEqual(metrics["publish.gateFail"], 0)
        self.assertEqual(metrics["time.computeSeconds"], 600 + 30 + 90)
        self.assertEqual(metrics["time.reworkSeconds"], 60)
        self.assertEqual((metrics["errors.total"], metrics["errors.preflight"], metrics["errors.afterPublish"]), (2, 1, 1))
        self.assertEqual(metrics["errors.lateShare"], 0.5)
        self.assertEqual(metrics["collection.unstructuredReports"], 1)
        self.assertEqual(metrics["collection.withoutPrivateEvidence"], 1)
        self.assertFalse(weekly["humanApproval"])
        self.assertEqual([c["id"] for c in weekly["candidates"]], ["C1", "C2"])
        page = (self.weekly / "20261108" / "WEEKLY.md").read_text(encoding="utf-8")
        self.assertIn("humanApproval=false", page)
        self.assertIn("没有更早的周汇总", page)
        self.assertIn("不是导出器生成的", page)
        self.assertIn("| 20261108-page | l4.publish | 2 |", page)

    def decide(self, week, replacements):
        page = self.weekly / week / "WEEKLY.md"
        text = page.read_text(encoding="utf-8")
        for old, new in replacements:
            self.assertIn(old, text)
            text = text.replace(old, new)
        page.write_text(text, encoding="utf-8")

    def test_decisions_are_stored_and_checked_next_week(self):
        self.report("20261108-page", day=8, deploys=5, publish_starts=3)
        self.build("20261108")
        self.decide("20261108", [
            ("| C1 | 20261108-page | 流程 | 开跑前写发布意图清单 | 首轮漏 3 件 | — | — | — |",
             "| C1 | 20261108-page | 流程 | 开跑前写发布意图清单 | 首轮漏 3 件 | 接受 | DEV-WK-001 | `publish.deployAttempts <= 3` |"),
            ("| C2 | 20261108-page | 预检 | 首次部署前干跑英文包 | 多走 4 次 replace | — | — | — |",
             "| C2 | 20261108-page | 预检 | 首次部署前干跑英文包 | 多走 4 次 replace | 推迟 | | |"),
            ("| 20261108-page | l4.publish | 2 | 1m00s | — |", "| 20261108-page | l4.publish | 2 | 1m00s | 变更 |"),
        ])
        result = rollup.finalize(self.weekly / "20261108")
        self.assertEqual(result["accepted"], ["20261108-C1"])
        stored = json.loads((self.weekly / "20261108" / "weekly.json").read_text())
        self.assertTrue(stored["finalized"])
        self.assertEqual(stored["actions"][0]["baseline"], 5)
        self.assertEqual(stored["metrics"]["time.changeSeconds"], 60)
        self.assertEqual(stored["metrics"]["time.reworkOnlySeconds"], 0)
        self.assertEqual([c["decision"] for c in stored["candidates"]], ["accept", "defer"])

        self.report("20261115-page", day=15, deploys=3)
        better = self.build("20261115")
        self.assertEqual(better["previousWeek"], "20261108")
        self.assertEqual(better["actions"][0]["history"][-1], {"week": "20261115", "result": "effective", "value": 3})
        page = (self.weekly / "20261115" / "WEEKLY.md").read_text(encoding="utf-8")
        self.assertIn("| 20261108-C1 | DEV-WK-001 |", page)
        self.assertIn("生效", page)
        self.assertIn("| 托管部署次数 | 3 | 5 | -2 |", page)

    def test_the_evidence_index_marks_backfilled_reports(self):
        self.report("20261108-page", day=8, deploys=1, evidence=False)
        self.report("20261108-other", day=8, deploys=1, evidence=False)
        self.weekly.mkdir()
        (self.weekly / rollup.EVIDENCE_INDEX).write_text(json.dumps({"runs": [
            {"runName": "20261108-page-zh"}, {"runName": "20261108-page-publish"}, {"runName": "20261101-page-zh"}]}))
        weekly = self.build("20261108")
        by_name = {r["name"]: r["privateEvidence"] for r in weekly["reports"]}
        self.assertEqual(by_name["20261108-page"], {"uploaded": True, "bundles": 2})
        self.assertEqual(by_name["20261108-other"], {"uploaded": False, "bundles": 0})
        self.assertEqual(weekly["metrics"]["collection.withoutPrivateEvidence"], 1)

    def test_results_distinguish_regressed_no_effect_and_not_exercised(self):
        action = {"signal": {"metric": "publish.deployAttempts", "op": "<=", "value": 3}, "baseline": 5}
        self.assertEqual(rollup.evaluate(action, {"publish.deployAttempts": 4})["result"], "no_effect")
        self.assertEqual(rollup.evaluate(action, {"publish.deployAttempts": 9})["result"], "regressed")
        self.assertEqual(rollup.evaluate(action, {})["result"], "not_exercised")
        higher = {"signal": {"metric": "frontend.alignment.jumpRateOfRecorded", "op": ">=", "value": 0.8}, "baseline": 0.6}
        self.assertEqual(rollup.evaluate(higher, {"frontend.alignment.jumpRateOfRecorded": 0.5})["result"], "regressed")

    def test_an_accepted_candidate_needs_a_backlog_id_and_a_signal(self):
        self.report("20261108-page", day=8, deploys=1)
        self.build("20261108")
        self.decide("20261108", [("| 首轮漏 3 件 | — | — | — |", "| 首轮漏 3 件 | 接受 | DEV-WK-001 | 少部署 |")])
        with self.assertRaises(ValueError):
            rollup.finalize(self.weekly / "20261108")
        self.assertFalse(json.loads((self.weekly / "20261108" / "weekly.json").read_text())["finalized"])

    def test_frontend_metrics_enter_the_rollup_as_numbers_only(self):
        self.report("20261115-page", day=15, deploys=1)
        path = self.base / "frontend-metrics.json"
        path.write_text(json.dumps({"schemaVersion": frontend.SCHEMA, "range": {"from": "2026-11-09", "to": "2026-11-15"},
                                    "smallCountRule": "rule", "missing": ["alignment"], "reports": {
                                        "usage": {"totals": {"sessions": 40, "browserDays": 22},
                                                  "funnel": {"appOpenSessions": 30, "playSessions": 21, "downloadSessions": "<5",
                                                             "playRateOfOpens": 0.7}, "actions": [], "coverage": {}},
                                        "listening": {"totals": {"qualifiedSessions": "<5", "deviceDays": 6, "completionRate": None},
                                                      "groups": []}}}))
        weekly = self.build("20261115", frontend_path=path)
        self.assertEqual(weekly["metrics"]["frontend.usage.sessions"], 40)
        self.assertEqual(weekly["metrics"]["frontend.usage.playRateOfOpens"], 0.7)
        self.assertNotIn("frontend.listening.qualifiedSessions", weekly["metrics"])
        self.assertEqual(weekly["metrics"]["frontend.listening.deviceDays"], 6)
        page = (self.weekly / "20261115" / "WEEKLY.md").read_text(encoding="utf-8")
        self.assertIn("缺少的报表：alignment", page)


class WeeklyFrontendTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        events = [{"action": "nudge_back_1_click", "week": "2026-11-15", "positionSeconds": 605 + i} for i in range(6)]
        events += [{"action": "nudge_forward_1_click", "week": "2026-11-15", "positionSeconds": 1300}]
        events += [{"action": "play_click", "week": "2026-11-15", "positionSeconds": 0}]
        usage = {"schemaVersion": "sermon-private-usage-report-v1", "range": {"from": "2026-11-09", "to": "2026-11-15"},
                 "query": {"documentsRead": 9, "truncated": True},
                 "totals": {"sessions": 9, "browserDays": 3, "appOpens": 9, "events": 80, "cappedSessions": 0},
                 "funnel": {"appOpenSessions": 9, "appOpenAndPlaySessions": 6, "appOpenAndPlayAndDownloadSessions": 2},
                 "daily": [{"day": "2026-11-15", "anonymousBrowsers": 3, "sessions": 9}],
                 "hourly": [{"hour": 10, "activeSessionHours": 7}, {"hour": 3, "activeSessionHours": 0}],
                 "actions": [{"key": "play_click", "sessions": 6, "events": 14}, {"key": "outline_open", "sessions": 2, "events": 2}],
                 "voices": [], "sessions": [{"number": 1, "day": "2026-11-15", "events": events}]}
        listening = {"schemaVersion": "sermon-private-listening-report-v1", "range": {"from": "2026-11-09", "to": "2026-11-15"},
                     "totals": {"sessions": 12, "qualifiedSessions": 8, "deviceDays": 5, "listenedSeconds": 7200,
                                "completedSessions": 4, "ignoredRecords": 0},
                     "groups": [{"contentLocale": "ko", "audioLocale": "ko", "platform": "web", "sessions": 2,
                                 "qualifiedSessions": 2, "deviceDays": 1, "listenedSeconds": 900, "completedSessions": 1}],
                     "weeks": [], "crossTab": []}
        for kind, report in (("usage", usage), ("listening", listening)):
            (self.base / kind).mkdir()
            (self.base / kind / "summary.json").write_text(json.dumps(report))

    def test_small_counts_and_timelines_never_leave(self):
        metrics = frontend.build(self.base)
        self.assertEqual(metrics["missing"], ["alignment"])
        usage = metrics["reports"]["usage"]
        self.assertEqual(usage["totals"], {"sessions": 9, "browserDays": "<5", "appOpens": 9, "events": 80})
        self.assertEqual(usage["funnel"]["downloadSessions"], "<5")
        self.assertEqual(usage["funnel"]["playRateOfOpens"], 0.667)
        self.assertEqual(usage["funnel"]["downloadRateOfPlays"], 0.333)
        self.assertEqual(usage["positionHotspots"]["nudge"], [{"week": "2026-11-15", "minute": 10, "events": 6}])
        self.assertEqual(usage["positionHotspots"]["skip"], [])
        self.assertTrue(usage["coverage"]["truncated"])
        self.assertNotIn("sessions", {key for key in usage if key != "totals"})
        korean = metrics["reports"]["listening"]["groups"][0]
        self.assertEqual((korean["qualifiedSessions"], korean["listenedHours"], korean["completionRate"]), ("<5", None, None))
        totals = metrics["reports"]["listening"]["totals"]
        self.assertEqual((totals["listenedHours"], totals["completionRate"]), (2.0, 0.5))
        self.assertNotIn("positionSeconds", json.dumps(metrics))

    def test_reports_must_cover_the_same_range(self):
        other = json.loads((self.base / "listening" / "summary.json").read_text())
        other["range"]["to"] = "2026-11-16"
        (self.base / "listening" / "summary.json").write_text(json.dumps(other))
        with self.assertRaises(ValueError):
            frontend.build(self.base)

    def test_export_runs_the_three_private_reports_for_the_service_week(self):
        calls = []

        def runner(command, env=None, capture_output=None, text=None):
            calls.append((command[2], command[4], command[6], env["GOOGLE_CLOUD_PROJECT"]))
            kind, out = command[2], Path(command[8])
            out.mkdir()
            source = self.base / kind / "summary.json"
            report = json.loads(source.read_text()) if source.is_file() else {
                "schemaVersion": frontend.REPORTS[kind], "range": {"from": "2026-11-09", "to": "2026-11-15"}}
            (out / "summary.json").write_text(json.dumps(report))
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        from unittest.mock import patch
        with patch.object(frontend, "FEEDBACK", self.base / "feedback"):
            with self.assertRaises(ValueError):
                frontend.export_week("20261115", out_root=self.base / "out", store=False, runner=runner)
            (self.base / "feedback" / "node_modules").mkdir(parents=True)
            result = frontend.export_week("20261115", out_root=self.base / "out", store_uri=str(self.base / "store"),
                                          project="example-project", runner=runner)
        self.assertEqual(calls, [(kind, "2026-11-09", "2026-11-15", "example-project") for kind in frontend.REPORTS])
        self.assertEqual(result["missing"], [])
        self.assertTrue((self.base / "store/frontend/20261115/usage/summary.json").is_file())
        self.assertFalse((self.base / "store/frontend/20261115/frontend-metrics.json").exists())
        self.assertTrue(Path(result["metrics"]).is_file())

    def test_small_helper(self):
        self.assertEqual([frontend.small(v) for v in (0, 1, 4, 5, 6.5, None, True)], [0, "<5", "<5", 5, 6.5, None, None])
        self.assertIsNone(frontend.rate(3, 4))


if __name__ == "__main__":
    unittest.main()
