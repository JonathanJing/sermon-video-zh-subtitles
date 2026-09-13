import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from quality_harness import compare, digest, evaluate, load_suite, number_present, verified_reference

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "quality-fixtures"


class QualityHarnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.suite = FIXTURES / "suite.json"
        self.baseline = FIXTURES / "baseline.json"
        self.saved = json.loads(self.baseline.read_text())

    def write(self, name, obj):
        path = self.work / name
        path.write_text(json.dumps(obj, ensure_ascii=False))
        return path

    def run_candidate(self, obj):
        return evaluate(self.suite, self.write("candidate.json", obj))

    def rules(self, obj):
        return {v["rule"] for v in self.run_candidate(obj)["violations"]}

    def test_baseline_pass_is_explicitly_not_human_acceptance(self):
        result = compare(self.suite, self.baseline, self.baseline)
        self.assertTrue(result["passed"])
        self.assertEqual(result["humanAcceptance"], "not_evaluated")
        self.assertEqual(result["candidate"]["evidence"]["status"], "not_provided")
        self.assertTrue(all(s["provenance"]["kind"] == "synthetic_fixture" for s in load_suite(self.suite)["samples"]))

    def test_fixed_negative_rejects_missing_segment_and_number_substring(self):
        result = compare(self.suite, self.baseline, FIXTURES / "candidate-regression.json")
        self.assertFalse(result["passed"])
        self.assertEqual({r["rule"] for r in result["regressions"]}, {"missing_sample", "number_constraint:5,300"})

    def test_bad_baseline_cannot_hide_existing_failures(self):
        bad = FIXTURES / "candidate-regression.json"
        result = compare(self.suite, bad, bad)
        self.assertEqual(result["regressions"], [])
        self.assertFalse(result["passed"])

    def test_source_change_and_suite_hash_change_rejected(self):
        self.saved["samples"][0]["en"] = "Changed source"
        self.assertIn("source_changed", self.rules(self.saved))
        self.saved["suiteSha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "different suite"):
            self.run_candidate(self.saved)

    def test_duplicate_extra_and_empty_samples_rejected(self):
        self.saved["samples"].append(copy.deepcopy(self.saved["samples"][0]))
        self.saved["samples"].append({"id": "unexpected"})
        self.saved["samples"][1]["zh"] = " "
        rules = self.rules(self.saved)
        self.assertTrue({"duplicate_sample_id", "unexpected_sample", "missing_chinese"} <= rules)

    def test_terms_spoken_and_duplicate_text_rejected(self):
        self.saved["samples"][2]["zh"] = "错误。错误。"
        self.saved["samples"][2]["spokenZh"] = "错误。错误。"
        self.saved["samples"][1]["spokenZh"] = "two thousand twenty six"
        rules = self.rules(self.saved)
        self.assertTrue({"duplicate_chinese_sentence", "missing_term:恩典", "spoken_text_mismatch"} <= rules)
        self.saved["samples"][2]["zh"] = self.saved["samples"][0]["zh"]
        self.assertIn("duplicate_chinese_segment", self.rules(self.saved))

    def evidence(self):
        refs = {}
        def add(name, content):
            path = self.work / (name + ".json")
            path.write_bytes(content if isinstance(content, bytes) else json.dumps(content).encode())
            refs[name] = {"path": path.name, "sha256": digest(path.read_bytes())}
        blocks = []
        for i, row in enumerate(self.saved["samples"]):
            row["blockId"] = i
            blocks.append({"id": i, "en": row["en"], "zh": row["zh"]})
        # These bytes/reports are test doubles, not playable or real review evidence.
        add("job", {"schemaVersion": "sermon-weekly-dubbing-job-v1", "units": [{"id": 0}], "blocks": blocks})
        add("naturalAudio", b"synthetic-natural")
        add("syncedAudio", b"synthetic-synced")
        job_hash = refs["job"]["sha256"]
        add("asrScreening", {"jobSha256": job_hash, "results": [{"sha256": refs["naturalAudio"]["sha256"], "fullDecode": "pass", "screenedUnits": 1, "expectedUnits": 1, "reviewCandidates": [{"kind": "recognition_difference"}]}]})
        add("timing", {"schemaVersion": "sermon-video-sync-budget-v1", "jobSha256": job_hash, "status": "natural_timing_fits", "failures": []})
        add("syncedAssembly", {"jobSha256": job_hash, "sha256": refs["syncedAudio"]["sha256"], "fullDecode": "pass", "sourceNaturalMp3Sha256": refs["naturalAudio"]["sha256"], "timingReportSha256": refs["timing"]["sha256"]})
        self.saved["evidence"] = refs
        return refs

    def change_report(self, refs, name, change):
        path = self.work / refs[name]["path"]
        data = json.loads(path.read_text())
        change(data)
        path.write_text(json.dumps(data))
        refs[name]["sha256"] = digest(path.read_bytes())

    def test_saved_reports_keep_asr_differences_separate_from_acceptance(self):
        self.evidence()
        result = self.run_candidate(self.saved)
        self.assertTrue(result["passed"])
        self.assertEqual(result["evidence"]["asrReviewCandidates"], 1)
        self.assertEqual(result["evidence"]["humanAcceptance"], "not_evaluated")

    def test_changed_audio_wrong_job_and_timing_failure_rejected(self):
        for failure in ("audio", "job", "timing", "coverage", "text"):
            with self.subTest(failure=failure):
                refs = self.evidence()
                if failure == "audio":
                    (self.work / refs["naturalAudio"]["path"]).write_bytes(b"changed")
                elif failure == "job":
                    self.change_report(refs, "asrScreening", lambda r: r.update(jobSha256="0" * 64))
                elif failure == "timing":
                    self.change_report(refs, "timing", lambda r: r.update(status="needs_timing_review", failures=["overflow"]))
                elif failure == "coverage":
                    self.change_report(refs, "asrScreening", lambda r: r["results"][0].update(screenedUnits=0))
                else:
                    self.saved["samples"][0]["zh"] = "Different candidate"
                self.assertIn("invalid_saved_evidence", self.rules(self.saved))
                self.saved = json.loads(self.baseline.read_text())

    def test_required_evidence_and_unproven_human_fixture_rejected(self):
        suite = json.loads(self.suite.read_text())
        suite["requireAudioEvidence"] = True
        self.suite = self.write("suite.json", suite)
        self.saved["suiteSha256"] = digest(self.suite.read_bytes())
        self.assertIn("missing_saved_evidence", self.rules(self.saved))
        suite["samples"][0]["provenance"] = {"kind": "human_reviewed"}
        self.write("suite.json", suite)
        with self.assertRaisesRegex(ValueError, "evidence reference"):
            load_suite(self.suite)

    def test_canonical_number_checks_reject_self_consistent_wrong_asr(self):
        self.assertFalse(number_present("垂直爬升五,三百英尺", "五千三百"))
        self.assertFalse(number_present("垂直爬升五三百英尺", "五千三百"))
        self.assertFalse(number_present("落差三零英尺", "三千"))
        self.assertTrue(number_present("垂直爬升五千三百英尺", "五千三百"))
        self.assertTrue(number_present("落差三千英尺", "三千"))
        self.assertFalse(number_present("15300 feet", "5300"))
        self.assertFalse(number_present("三千五百英尺", "三千"))

    def test_model_reviewed_schema_requires_real_bound_evidence(self):
        suite = json.loads(self.suite.read_text())
        suite["schemaVersion"] = "saturday-quality-suite-v2"
        for sample in suite["samples"]:
            sample["provenance"] = {"kind": "model_reviewed", "humanApproval": False}
            sample["constraints"]["numbers"] = []
        with self.assertRaisesRegex(ValueError, "hash-bound local reference"):
            load_suite(self.write("model-suite.json", suite))
        suite["samples"][0]["provenance"]["kind"] = "human_reviewed"
        with self.assertRaisesRegex(ValueError, "sample provenance"):
            load_suite(self.write("model-suite.json", suite))

    def test_frozen_reference_bytes_are_checked(self):
        path = self.write("receipt.json", {"state": "fixture"})
        ref = {"path": path.name, "sha256": digest(path.read_bytes())}
        self.assertEqual(verified_reference(ref, self.work), path.resolve())
        path.write_text("changed")
        with self.assertRaisesRegex(ValueError, "reference bytes changed"):
            verified_reference(ref, self.work)

    def test_cli_exit_codes_and_report_are_machine_readable(self):
        for candidate, expected in ((self.baseline, 0), (FIXTURES / "candidate-regression.json", 1), (self.work / "missing.json", 2)):
            with self.subTest(code=expected):
                report = self.work / "report.json"
                result = subprocess.run([sys.executable, str(HERE / "quality_harness.py"), "--suite", str(self.suite), "--baseline", str(self.baseline), "--candidate", str(candidate), "--out", str(report)], capture_output=True, text=True)
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertEqual(json.loads(report.read_text())["passed"], expected == 0)

    def test_report_cannot_overwrite_frozen_input_even_through_hardlink(self):
        baseline = self.write("frozen-baseline.json", self.saved)
        alias = self.work / "report-alias.json"
        alias.hardlink_to(baseline)
        original = baseline.read_bytes()
        for output in (baseline, alias):
            result = subprocess.run([sys.executable, str(HERE / "quality_harness.py"),
                "--suite", str(self.suite), "--baseline", str(baseline),
                "--candidate", str(baseline), "--out", str(output)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(baseline.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
