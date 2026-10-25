"""Prepared term decisions bound to a formal source as v4 policy drafts (DEV-PREP-003)."""
import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.text import policy
from tongxing_production.text import term_scope as subject


ROOT = Path(__file__).resolve().parents[1]
REVIEW = {"reviewed_by": "operator", "reviewed_at": "2026-10-25T01:20:46Z",
          "user_statement": "按照预热包里的来"}


def ko_base():
    draft = json.loads((ROOT / "config/target-language-policies/ko.json").read_text(encoding="utf-8"))
    draft.pop("componentSha256", None)
    draft["languageReview"].update(policy.machine_qc_language_review("ko"))
    return draft


def decisions(**changes):
    value = {
        "schemaVersion": subject.DECISIONS_SCHEMA,
        "properNames": [
            {"source": "Martin Luther", "target": {"zh-Hans": "马丁·路德", "ko": "마르틴 루터", "es": "Martín Lutero"}},
            {"source": "Corrie ten Boom", "target": {"zh-Hans": "彭柯丽", "ko": "코리 텐 붐", "es": "Corrie ten Boom"}},
            {"source": "Holland", "target": {"zh-Hans": "荷兰", "ko": "네덜란드", "es": "Holanda"}},
            {"source": "Moses", "target": {"zh-Hans": "摩西", "ko": "모세", "es": "Moisés"}},
        ],
        "seriesNames": [{"source": "If I Had More Time",
                         "target": {"zh-Hans": "如果我有更多时间", "ko": "If I Had More Time", "es": "If I Had More Time"}}],
        "predictedOrdinaryPhraseExclusions": ["Savior Jesus", "Half Times"],
    }
    value.update(changes)
    return value


class TermScopeTests(unittest.TestCase):
    def setUp(self):
        self.anchor = {"sourceUnits": [
            {"sourceUnitId": "u1", "english": "Martin Luther said it."},
            {"sourceUnitId": "u2", "english": "Listen to the If I Had More Time podcast."},
            {"sourceUnitId": "u3", "english": "Corrie ten Boom lived in Holland with our Savior Jesus."},
        ]}
        self.source = {"source": "fixture", "anchors": {"artifact": {"jsonSha256": "x" * 64}}}
        self.table = policy._series_table()

    def scope(self, value=None, base=None, anchor=None):
        return subject.scope_locale(value or decisions(), self.source, anchor or self.anchor, "ko",
                                    base or ko_base(), series_table=self.table, **REVIEW)

    def test_draft_binds_present_terms_to_their_units_and_freezes(self):
        draft, report = self.scope()
        self.assertEqual(report["status"], "draft_ready")
        self.assertEqual(report["freezeCheck"]["status"], "pass", report["freezeCheck"])
        receipt = draft["sourceScope"]["termApprovalReceipt"]
        self.assertEqual({row["source"]: row["sourceUnitId"] for row in receipt["approvedTerms"]},
                         {"Martin Luther": "u1", "Corrie ten Boom": "u3", "Holland": "u3"})
        self.assertTrue(receipt["humanApproval"])
        self.assertEqual(receipt["reviewedBy"], "operator")
        self.assertEqual(report["decisionsAbsentFromSource"], ["Moses"])
        self.assertEqual(draft["sourceScope"]["usedSeriesNames"], ["If I Had More Time"])
        self.assertEqual(draft["sourceScope"]["ordinaryPhraseExclusions"], ["Savior Jesus"])
        self.assertEqual(report["predictedExclusionsNotProduced"], ["Half Times"])
        series = {row["source"]: row for row in draft["terminology"]["seriesNames"]}
        self.assertEqual(series["If I Had More Time"]["target"], "If I Had More Time")
        self.assertEqual(series["If I Had More Time"]["reviewStatus"], "human_reviewed")
        self.assertNotIn("componentSha256", draft)
        frozen = policy.freeze_policy(copy.deepcopy(draft), series_table=self.table)
        policy.validate_source_scope(frozen, self.source, self.anchor)

    def test_uncovered_scanner_name_withholds_the_draft_and_names_its_unit(self):
        anchor = copy.deepcopy(self.anchor)
        anchor["sourceUnits"].append({"sourceUnitId": "u4", "english": "D. A. Carson and Orange County."})
        draft, report = self.scope(anchor=anchor)
        self.assertIsNone(draft)
        self.assertEqual(report["status"], "needs_decision")
        self.assertEqual(report["uncoveredScannerNames"], [{"name": "Orange County", "sourceUnitIds": ["u4"]}])

    def test_used_series_without_a_target_needs_a_decision(self):
        draft, report = self.scope(decisions(seriesNames=[]))
        self.assertIsNone(draft)
        self.assertEqual(report["seriesNamesWithoutTarget"], ["If I Had More Time"])

    def test_chinese_series_decision_must_match_the_table(self):
        wrong = decisions(seriesNames=[{"source": "If I Had More Time", "target": {"zh-Hans": "If I Had More Time 播客"}}])
        base = json.loads((ROOT / "config/target-language-policies/zh-Hans.json").read_text(encoding="utf-8"))
        with self.assertRaisesRegex(ValueError, "differs from the series table"):
            subject.scope_locale(wrong, self.source, self.anchor, "zh-Hans", base,
                                 series_table=self.table, **REVIEW)

    def test_decisions_and_base_locale_are_checked(self):
        with self.assertRaisesRegex(ValueError, "Duplicate properNames"):
            self.scope(decisions(properNames=decisions()["properNames"] * 2))
        with self.assertRaisesRegex(ValueError, "Base policy is for"):
            subject.scope_locale(decisions(), self.source, self.anchor, "es", ko_base(),
                                 series_table=self.table, **REVIEW)

    def test_plugin_pin_reports_current_stale_and_missing(self):
        draft, _ = self.scope()
        self.assertEqual(subject.plugin_pin_check(draft)["status"], "current")
        draft["languageReview"]["pluginImplementationSha256"] = "0" * 64
        self.assertEqual(subject.plugin_pin_check(draft)["status"], "stale")
        draft["languageReview"]["pluginId"] = "zh-Hans-weekly-auto-v1"
        self.assertEqual(subject.plugin_pin_check(draft)["status"], "missing")
        del draft["languageReview"]["pluginId"]
        self.assertEqual(subject.plugin_pin_check(draft)["status"], "unbound")

    def test_cli_writes_new_files_only_and_reports_exit_status(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            for name, value in (("decisions.json", decisions()), ("source.json", self.source),
                                ("anchor.json", self.anchor), ("ko-base.json", ko_base())):
                (folder / name).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            argv = ["--decisions", str(folder / "decisions.json"), "--source-package", str(folder / "source.json"),
                    "--anchor-manifest", str(folder / "anchor.json"), "--locale", "ko",
                    "--base", f"ko={folder / 'ko-base.json'}", "--reviewed-by", "operator",
                    "--reviewed-at", REVIEW["reviewed_at"], "--user-statement", REVIEW["user_statement"],
                    "--out-dir", str(folder / "out")]
            with redirect_stdout(io.StringIO()):
                self.assertEqual(subject.main(argv), 0)
            self.assertTrue((folder / "out/ko-policy-draft.json").is_file())
            self.assertTrue((folder / "out/ko-term-scope-report.json").is_file())
            with redirect_stdout(io.StringIO()), self.assertRaises(FileExistsError):
                subject.main(argv)


if __name__ == "__main__":
    unittest.main()
