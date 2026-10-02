"""Synthetic and fault-injection checks only; no real acoustic sample claims."""
import copy
import hashlib
import json
import os
import io
import struct
import wave
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import run_benchmark as benchmark

HERE = Path(__file__).resolve().parent


class BenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = tempfile.TemporaryDirectory(prefix="field09-test-")
        cls.fixture = Path(cls.base.name) / "fixture"
        subprocess.run(["node", str(HERE / "make_synthetic_fixture.mjs"), str(cls.fixture)], check=True, capture_output=True)
        cls.original = json.loads((cls.fixture / "manifest.json").read_text())

    @classmethod
    def tearDownClass(cls):
        cls.base.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="field09-private-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "data"
        shutil.copytree(self.fixture, self.root)
        self.manifest = copy.deepcopy(self.original)

    def run_report(self):
        return benchmark.run(json.dumps(self.manifest).encode(), self.root)

    def write_asset(self, asset, data):
        (self.root / asset["path"]).write_bytes(data)
        asset["sha256"] = hashlib.sha256(data).hexdigest()

    def assert_invalid(self, code):
        with self.assertRaisesRegex(benchmark.BenchmarkError, "^" + code + "$"):
            benchmark.validate_manifest(self.manifest)

    def cli(self, report, manifest=None):
        file = self.root / "manifest.json"
        file.write_text(json.dumps(self.manifest) if manifest is None else manifest)
        return subprocess.run([sys.executable, str(HERE / "run_benchmark.py"), "--manifest", str(file),
                               "--data-root", str(self.root), "--report", str(report)], capture_output=True, text=True)

    def test_schema_is_valid_and_fixture_matches_real_dsp_with_nonzero_origin(self):
        benchmark.Draft202012Validator.check_schema(json.loads(benchmark.SCHEMA.read_text()))
        report = self.run_report()
        self.assertEqual([c["status"] for c in report["cases"]], ["accepted", "rejected", "accepted", "rejected"])
        for split in ("dev", "holdout"):
            m = report["metrics"][split]
            self.assertEqual(m["positiveCorrectWithinTolerance"], {"numerator": 1, "denominator": 1, "value": 1})
            self.assertEqual(m["negativeCorrectRejectionAllPlanned"]["value"], 1)
            self.assertEqual(m["captureSessionCount"], 2)
            self.assertEqual(m["sourceRecordingCount"], 1)
            self.assertIsNone(m["independentAcousticSampleCount"])
        self.assertEqual(report["cases"][0]["predictedSourceStartSeconds"], 19.984)
        self.assertEqual(report["cases"][0]["provenance"]["inputVerification"], "verified")
        self.assertEqual(report["evidenceScope"], "synthetic_harness_only")
        self.assertFalse(report["promotionAllowed"])
        self.assertTrue(all(v == "not_run" for v in report["acceptance"].values()))
        self.assertEqual(report["manifestSha256"], hashlib.sha256(json.dumps(self.manifest).encode()).hexdigest())
        for key, file in (("runnerSha256", HERE / "run_benchmark.py"), ("workerSha256", benchmark.WORKER), ("algorithmSha256", benchmark.CORE), ("manifestSchemaSha256", benchmark.SCHEMA)):
            self.assertEqual(report["implementation"][key], hashlib.sha256(file.read_bytes()).hexdigest())

    def test_pcm16_44100_and_48000_queries_use_unchanged_resampler(self):
        original = (self.fixture / "dev-match.wav").read_bytes()
        samples = struct.unpack("<" + "h" * ((len(original) - 44) // 2), original[44:])
        asset = self.manifest["sessions"][0]["recording"]
        for rate in (44100, 48000):
            with self.subTest(rate=rate):
                out = io.BytesIO()
                resampled = []
                for i in range(rate * 10):
                    position = i * 8000 / rate
                    left = int(position)
                    fraction = position - left
                    resampled.append(round(samples[left] * (1 - fraction) + samples[min(left + 1, len(samples) - 1)] * fraction))
                with wave.open(out, "wb") as stream:
                    stream.setnchannels(1)
                    stream.setsampwidth(2)
                    stream.setframerate(rate)
                    stream.writeframes(struct.pack("<" + "h" * len(resampled), *resampled))
                self.write_asset(asset, out.getvalue())
                c = self.run_report()["cases"][0]
                self.assertEqual(c["status"], "accepted")
                self.assertEqual(c["inputSampleRate"], rate)
                self.assertTrue(c["correctWithinTolerance"])

    def test_source_family_cannot_cross_split_even_with_different_hashes(self):
        self.manifest["sources"][1]["familyId"] = self.manifest["sources"][0]["familyId"]
        self.assert_invalid("split_leakage")

    def test_recording_bytes_cannot_cross_split_under_new_ids(self):
        self.manifest["sources"][1]["recording"]["sha256"] = self.manifest["sources"][0]["recording"]["sha256"]
        self.assert_invalid("split_leakage")

    def test_capture_bytes_cannot_cross_split_under_new_session_id(self):
        self.manifest["sessions"][2]["recording"]["sha256"] = self.manifest["sessions"][0]["recording"]["sha256"]
        self.assert_invalid("split_leakage")

    def test_asset_paths_cannot_cross_split_even_if_claimed_hash_changes(self):
        self.manifest["sessions"][2]["recording"]["path"] = self.manifest["sessions"][0]["recording"]["path"]
        self.assert_invalid("split_leakage")

    def test_session_source_must_share_split(self):
        self.manifest["sessions"][2]["sourceRecordingId"] = "source-dev"
        self.assert_invalid("session_source_split_invalid")

    def test_capture_session_group_cannot_cross_split_after_file_relabeling(self):
        self.manifest["sessions"][2]["captureSessionId"] = self.manifest["sessions"][0]["captureSessionId"]
        self.assert_invalid("split_leakage")

    def test_multiple_files_from_one_capture_are_not_counted_as_independent_sessions(self):
        self.manifest["sessions"][1]["captureSessionId"] = self.manifest["sessions"][0]["captureSessionId"]
        m = self.run_report()["metrics"]["dev"]
        self.assertEqual(m["captureSessionCount"], 1)
        self.assertEqual(m["captureAssetCount"], 2)

    def test_target_requires_index_but_negative_query_source_does_not(self):
        self.manifest["sources"][0].pop("index")
        self.assert_invalid("target_index_required")
        self.manifest = copy.deepcopy(self.original)
        recording = {"path": "negative-source.bin", "sha256": hashlib.sha256(b"synthetic source").hexdigest()}
        (self.root / recording["path"]).write_bytes(b"synthetic source")
        self.manifest["sources"].append({"id": "noise-source", "familyId": "noise-family", "split": "dev", "recording": recording})
        self.manifest["sessions"][1]["sourceRecordingId"] = "noise-source"
        r = self.run_report()
        self.assertEqual(r["cases"][1]["status"], "rejected")
        (self.root / recording["path"]).write_bytes(b"changed")
        self.assertEqual(self.run_report()["cases"][1]["reason"], "asset_hash_mismatch")

    def test_case_target_cannot_cross_split(self):
        self.manifest["cases"][0]["targetSourceRecordingId"] = "source-holdout"
        self.assert_invalid("case_reference_or_split_invalid")

    def test_overlapping_windows_stay_one_session_and_all_planned_count(self):
        extra = copy.deepcopy(self.manifest["cases"][0])
        extra["id"] = "overlap-dev"
        self.manifest["cases"].append(extra)
        m = self.run_report()["metrics"]["dev"]
        self.assertEqual(m["caseCount"], 3)
        self.assertEqual(m["captureSessionCount"], 2)
        self.assertIsNone(m["independentAcousticSampleCount"])

    def test_duplicate_ids_and_unused_sessions_are_rejected(self):
        for key, code in (("sources", "duplicate_source_id"), ("sessions", "duplicate_session_id"), ("cases", "duplicate_case_id")):
            with self.subTest(key=key):
                self.manifest = copy.deepcopy(self.original)
                self.manifest[key].append(copy.deepcopy(self.manifest[key][0]))
                self.assert_invalid(code)
        self.manifest = copy.deepcopy(self.original)
        self.manifest["cases"].pop()
        self.assert_invalid("unused_source_or_session")

    def test_both_dev_and_holdout_required(self):
        for key in ("sources", "sessions"):
            self.manifest[key] = [v for v in self.manifest[key] if v["split"] == "dev"]
        self.manifest["cases"] = self.manifest["cases"][:2]
        self.assert_invalid("both_splits_required")

    def test_unknown_metadata_and_invalid_paths_rejected(self):
        for value in ("../secret.wav", "/secret.wav", "https://example.com/audio.wav", "a\\b.wav"):
            with self.subTest(value=value):
                self.manifest = copy.deepcopy(self.original)
                self.manifest["sessions"][0]["recording"]["path"] = value
                self.assert_invalid("manifest_schema_invalid")
        self.manifest = copy.deepcopy(self.original)
        self.manifest["sessions"][0]["deviceName"] = "private-device"
        self.assert_invalid("manifest_schema_invalid")

    def test_synthetic_cannot_be_relabeled_as_acoustic_without_explicit_manifest_change(self):
        self.manifest["datasetKind"] = "authorized_recordings"
        self.assert_invalid("evidence_kind_invalid")

    def test_mismatched_capture_hash_is_retained_as_failure(self):
        (self.root / "dev-match.wav").write_bytes(b"private-path-sensitive-content")
        report = self.run_report()
        c = report["cases"][0]
        self.assertEqual((c["status"], c["reason"]), ("failed", "asset_hash_mismatch"))
        self.assertEqual(c["provenance"]["inputVerification"], "incomplete")
        self.assertEqual(report["metrics"]["dev"]["positiveCorrectWithinTolerance"]["denominator"], 1)
        self.assertEqual(report["metrics"]["dev"]["positiveCorrectWithinTolerance"]["numerator"], 0)
        self.assertEqual(len(report["cases"]), 4)
        self.assertNotIn("private-path-sensitive-content", json.dumps(report))

    def test_mismatched_source_and_index_hashes_are_retained_per_case(self):
        for kind in ("recording", "index"):
            with self.subTest(kind=kind):
                self.manifest = copy.deepcopy(self.original)
                self.manifest["sources"][0][kind]["sha256"] = "0" * 64
                r = self.run_report()
                self.assertEqual([c["reason"] for c in r["cases"][:2]], ["asset_hash_mismatch"] * 2)
                self.assertEqual(r["metrics"]["dev"]["caseCount"], 2)

    def test_index_source_binding_is_checked_even_with_valid_index_hash(self):
        asset = self.manifest["sources"][0]["index"]
        index = json.loads((self.root / asset["path"]).read_text())
        index["sourceSha256"] = "0" * 64
        self.write_asset(asset, json.dumps(index).encode())
        r = self.run_report()
        self.assertEqual([c["reason"] for c in r["cases"][:2]], ["index_binding_invalid"] * 2)

    def test_index_origin_and_postings_are_validated(self):
        for field, value, reason in (("sourceStartSeconds", -1, "index_binding_invalid"),
                                     ("postings", {"123": [-1]}, "index_postings_invalid")):
            with self.subTest(field=field):
                asset = self.manifest["sources"][0]["index"]
                index = json.loads((self.fixture / "dev-index.json").read_text())
                index[field] = value
                self.write_asset(asset, json.dumps(index).encode())
                self.assertEqual(self.run_report()["cases"][0]["reason"], reason)

    def test_unsupported_wav_and_truncated_capture_not_dropped(self):
        asset = self.manifest["sessions"][0]["recording"]
        wav = bytearray((self.root / asset["path"]).read_bytes())
        wav[22:24] = (2).to_bytes(2, "little")
        self.write_asset(asset, wav)
        self.assertEqual(self.run_report()["cases"][0]["reason"], "wav_unsupported")
        self.write_asset(asset, b"bad wav")
        self.assertEqual(self.run_report()["cases"][0]["reason"], "wav_invalid")

    def test_missing_asset_and_symlink_escape_are_redacted(self):
        capture = self.root / "dev-match.wav"
        capture.unlink()
        self.assertEqual(self.run_report()["cases"][0]["reason"], "asset_unavailable")
        outside = Path(self.tmp.name) / "private-person-name.wav"
        outside.write_bytes(b"private")
        capture.symlink_to(outside)
        r = self.run_report()
        self.assertEqual(r["cases"][0]["reason"], "asset_outside_root")
        serialized = json.dumps(r)
        self.assertNotIn("private-person-name", serialized)
        self.assertNotIn(str(self.root), serialized)
        self.assertNotIn("dev-match.wav", serialized)
        self.assertNotIn("postings", serialized)
        self.assertNotIn("samples", serialized.replace("independent_acoustic_samples", ""))

    def test_capture_window_and_ground_truth_bounds(self):
        self.manifest["cases"][0]["captureStartSeconds"] = 1
        self.assertEqual(self.run_report()["cases"][0]["reason"], "capture_window_invalid")
        self.manifest["cases"][0]["captureStartSeconds"] = 0
        self.manifest["cases"][0]["expected"]["sourceStartSeconds"] = 0
        self.assertEqual(self.run_report()["cases"][0]["reason"], "ground_truth_outside_index")

    def test_short_query_rejection_stays_in_positive_denominator(self):
        self.manifest["cases"][0]["durationSeconds"] = 3
        r = self.run_report()
        self.assertEqual(r["cases"][0]["reason"], "insufficient_audio")
        self.assertEqual(r["metrics"]["dev"]["positiveCorrectWithinTolerance"], {"numerator": 0, "denominator": 1, "value": 0})
        self.assertEqual(r["metrics"]["dev"]["positiveAcceptedAbsoluteLocalizationErrorSeconds"]["count"], 0)

    def test_mislocalized_acceptance_keeps_absolute_error_and_is_not_success(self):
        self.manifest["cases"][0]["expected"]["sourceStartSeconds"] = 25
        r = self.run_report()
        self.assertEqual(r["cases"][0]["status"], "accepted")
        self.assertFalse(r["cases"][0]["correctWithinTolerance"])
        self.assertGreater(r["cases"][0]["absoluteLocalizationErrorSeconds"], 5)
        self.assertEqual(r["metrics"]["dev"]["positiveAcceptedOutsideTolerance"]["numerator"], 1)
        self.assertEqual(r["metrics"]["dev"]["observedWrongJumpAllPlanned"]["numerator"], 1)
        self.assertEqual(r["metrics"]["dev"]["positiveCorrectWithinTolerance"]["numerator"], 0)

    def test_real_process_deadline_retains_every_case(self):
        self.manifest["protocol"]["caseTimeoutSeconds"] = .001
        r = self.run_report()
        self.assertEqual([c["status"] for c in r["cases"]], ["timeout"] * 4)
        for m in r["metrics"].values():
            self.assertEqual(m["caseWallMsAllPlanned"]["count"], 2)
            self.assertEqual(m["negativeUnresolvedCount"], 1)
            self.assertIsNone(m["negativeFalseAcceptObserved"]["value"])
        self.assertTrue(all(c["timeoutRightCensored"] for c in r["cases"]))

    def test_negative_false_accepts_and_failures_have_honest_denominators(self):
        self.manifest["cases"][0]["expected"] = {"kind": "negative"}
        (self.root / "dev-silence.wav").unlink()
        r = self.run_report()
        m = r["metrics"]["dev"]
        self.assertEqual(m["negativeFalseAcceptAllPlanned"], {"numerator": 1, "denominator": 2, "value": .5})
        self.assertEqual(m["negativeFalseAcceptObserved"], {"numerator": 1, "denominator": 1, "value": 1})
        self.assertEqual(m["negativeUnresolvedCount"], 1)
        self.assertIsNone(m["positiveCorrectWithinTolerance"]["value"])

    def test_percentile_nearest_rank_and_zero_denominator(self):
        self.assertEqual(benchmark.distribution([]), {"count": 0, "p50": None, "p95": None})
        self.assertEqual(benchmark.distribution(range(1, 21)), {"count": 20, "p50": 10, "p95": 19})
        self.assertIsNone(benchmark.rate(0, 0)["value"])

    def test_cli_immutable_output_permissions_and_error_privacy(self):
        report = Path(self.tmp.name) / "report.json"
        first = self.cli(report)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(report.stat().st_mode & 0o777, 0o600)
        original = report.read_bytes()
        second = self.cli(report)
        self.assertEqual(second.returncode, 2)
        self.assertEqual(report.read_bytes(), original)
        self.assertNotIn(str(report), second.stderr)

    def test_cli_invalid_manifest_leaves_no_report_or_private_error(self):
        report = Path(self.tmp.name) / "report.json"
        result = self.cli(report, '{"privateName":"sensitive",broken')
        self.assertEqual(result.returncode, 2)
        self.assertFalse(report.exists())
        self.assertNotIn("sensitive", result.stderr)
        self.assertNotIn(str(self.root), result.stderr)

    def test_cli_unresolved_exit_code_still_has_all_cases(self):
        (self.root / "dev-match.wav").unlink()
        report = Path(self.tmp.name) / "report.json"
        result = self.cli(report)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(json.loads(report.read_text())["cases"]), 4)

    def test_duplicate_json_keys_and_nonfinite_values_fail_closed(self):
        for data in (b'{"a":1,"a":2}', b'{"x": NaN}'):
            with self.subTest(data=data), self.assertRaisesRegex(benchmark.BenchmarkError, "manifest_json_invalid"):
                benchmark.run(data, self.root)

    def test_worker_crash_missing_node_and_private_stderr_are_not_exported(self):
        for response in (subprocess.CompletedProcess([], 1, "", "private stack/path"), OSError("private binary path")):
            with self.subTest(response=response):
                context = patch.object(benchmark.subprocess, "run", side_effect=response) if isinstance(response, Exception) else patch.object(benchmark.subprocess, "run", return_value=response)
                with context:
                    r = self.run_report()
                self.assertTrue(all(c["status"] == "failed" for c in r["cases"]))
                self.assertNotIn("private", json.dumps(r))


if __name__ == "__main__":
    unittest.main()
