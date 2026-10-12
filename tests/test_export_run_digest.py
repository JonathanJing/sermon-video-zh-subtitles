"""Run digest: copies only small evidence, redacts secrets, and indexes outcomes."""
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts import export_run_digest as digest


class ExportRunDigestTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.run = self.base / "e2e-20261007T193332Z"
        (self.run / "audio").mkdir(parents=True)
        (self.run / "timings.tsv").write_text("stage\tstatus\tseconds\nbaseline\tpass\t93\nupload\tfail\t4\n")
        (self.run / "audio" / "outcome.json").write_text(json.dumps({
            "status": "failed", "exitCode": 1, "startedAt": "a", "endedAt": "b",
            "error": {"type": "ValueError", "message": "not in the subpath"}}))
        (self.run / "audio" / "tts-receipt.json").write_text(json.dumps({"inferenceSeconds": 0.0, "inputTokens": 12}))
        (self.run / "audio" / "out.wav").write_bytes(b"RIFF" * 10)
        (self.run / "upload.log").write_text(
            "OPENAI_API_KEY=sk-proj-abcdefghijklmnopqrstuvwxyz\n"
            "Authorization: Bearer abc.def.ghi\n"
            "wrote /Users/achillesjing/repo/artifacts/x from 192.168.1.20 for someone@example.com\n"
            "ssh spark-dgx.tail1234.ts.net ok\n"
            "token from env: supersecretvalue123\n")
        self.out = self.base / "digests"

    def export(self, *extra):
        with patch.dict("os.environ", {"SPARK_TOKEN": "supersecretvalue123"}, clear=False):
            self.assertEqual(digest.main([str(self.run), "--out", str(self.out), "--name", "20261007-e2e", *extra]), 0)
        return self.out / "20261007-e2e"

    def test_copies_evidence_only_and_redacts(self):
        dest = self.export("--zip")
        log = (dest / self.run.name / "upload.log").read_text()
        for secret in ("sk-proj-abc", "abc.def.ghi", "achillesjing", "192.168.1.20", "someone@example.com",
                       "supersecretvalue123", "tail1234"):
            self.assertNotIn(secret, log)
        self.assertIn("~/repo/artifacts/x", log)
        self.assertFalse((dest / self.run.name / "audio" / "out.wav").exists())
        receipt = json.loads((dest / self.run.name / "audio" / "tts-receipt.json").read_text())
        self.assertEqual(receipt, {"inferenceSeconds": 0.0, "inputTokens": 12})
        manifest = json.loads((dest / "manifest.json").read_text())
        self.assertEqual(manifest["runs"][0]["skipped"], {".wav": 1})
        self.assertTrue(all(len(f["sha256"]) == 64 for f in manifest["files"]))
        self.assertTrue(zipfile.is_zipfile(str(dest) + ".zip"))
        self.assertIn("## 遗留状态", (dest / "RETROSPECTIVE.md").read_text())

    def test_keys_that_redact_alike_keep_every_entry(self):
        # Review finding: a host map keyed by user@private-IP collapsed to one "<email>" entry.
        (self.run / "summary.json").write_text(json.dumps({"hosts": {
            "alice@192.168.1.1": {"ok": True}, "bob@192.168.1.2": {"ok": False}, "carol@192.168.1.3": {"ok": True}}}))
        dest = self.export()
        hosts = json.loads((dest / self.run.name / "summary.json").read_text())["hosts"]
        self.assertEqual(sorted(hosts), ["<email>", "<email>#2", "<email>#3"])
        self.assertEqual([row["ok"] for row in hosts.values()], [True, False, True])
        entry = next(f for f in json.loads((dest / "manifest.json").read_text())["files"] if f["path"] == "summary.json")
        self.assertEqual(entry["redactions"]["key_collision"], 2)

    def test_model_evidence_acceptances_and_approvals_are_not_copied(self):
        # Review finding: Layer 2 evidence.json carries source text and translations under the size cap.
        layer2 = self.run / "layer2" / "ko"
        layer2.mkdir(parents=True)
        (layer2 / "evidence.json").write_text(json.dumps({"groups": [{"source": "Jesus warns", "translation": "예수님은 경고하십니다"}]}))
        (layer2 / "ko-human-acceptance-c5.json").write_text(json.dumps({"units": [{"text": "예수님은"}]}))
        (layer2 / "content-approval.json").write_text(json.dumps({"text": "예수님은"}))
        (layer2 / "outline-review.evidence.txt").write_text("예수님은")
        (self.run / "journal.ndjson").write_text('{"at": "t", "stage": "layer1", "event": "started"}\n')
        (self.run / "decisions.ndjson").write_text('{"at": "t", "question": "q", "choice": "c"}\n')
        dest = self.export()
        copied = sorted(str(path.relative_to(dest / self.run.name)) for path in (dest / self.run.name).rglob("*") if path.is_file())
        self.assertEqual(copied, ["audio/outcome.json", "audio/tts-receipt.json", "decisions.ndjson", "journal.ndjson",
                                  "timings.tsv", "upload.log"])
        self.assertNotIn("예수님은", "".join(path.read_text() for path in dest.rglob("*") if path.is_file()))

    def test_source_budget_ledger_is_summarized_not_copied(self):
        # Review finding: the ledger's settlements were only counted as a skipped .json file.
        budget = self.run / ".jobs3.source-budget"
        budget.mkdir()
        settled = lambda model, micro, status="estimated_upper_bound", reason=None: {
            "costStatus": status, "costMicrousd": micro, "reasonCode": reason, "requestedModel": model,
            "usage": {"inputTokens": 1000, "outputTokens": 200, "cachedInputTokens": None, "reasoningTokens": 50}}
        row = lambda status, cost, settlement=None: {"identitySha256": "a" * 64, "status": status,
            "bounds": {"requests": 1, "wallTimeMs": 1000, "costMicrousd": cost},
            "resourceBinding": {"owner": {"sourceBudgetRoot": "/Users/achillesjing/run"}},
            **({"settlement": settlement} if settlement else {})}
        (budget / "source-budget.json").write_text(json.dumps({"schemaVersion": "sermon-source-budget-ledger-v3", "requests": {
            "judge.1": row("returned", 400_000, settled("gpt-6.1-sol", 120_000)),
            "judge.2": row("returned", 400_000, settled("gpt-6.1-sol", 80_000)),
            "asr.0000": row("returned", 13_500, settled("gpt-transcribe", None, "unknown", "no_frozen_price_for_model")),
            "asr.0001": row("started_response_unconfirmed", 13_500)}}))
        dest = self.export()
        self.assertFalse((dest / self.run.name / ".jobs3.source-budget" / "source-budget.json").exists())
        summary = json.loads((dest / self.run.name / ".jobs3.source-budget" / digest.BUDGET_SUMMARY_NAME).read_text())
        self.assertEqual((summary["requests"], summary["returned"], summary["priced"], summary["estimatedMicrousd"],
                          summary["reservedMicrousd"], summary["unknownCost"], summary["withoutSettlement"]),
                         (4, 3, 2, 200_000, 827_000, {"no_frozen_price_for_model": 1}, 0))
        self.assertEqual(summary["statuses"], {"returned": 3, "started_response_unconfirmed": 1})
        self.assertEqual(summary["tokens"]["inputTokens"], 3000)
        self.assertEqual(summary["byModel"]["gpt-6.1-sol"], {"returned": 2, "priced": 2, "estimatedMicrousd": 200_000})
        self.assertNotIn("achillesjing", json.dumps(summary))
        entry = next(f for f in json.loads((dest / "manifest.json").read_text())["files"] if f["kind"] == "budget")
        self.assertEqual((entry["source"], entry["path"]), (".jobs3.source-budget/source-budget.json",
                                                            ".jobs3.source-budget/" + digest.BUDGET_SUMMARY_NAME))
        self.assertEqual(len(entry["sha256"]), 64)
        index = (dest / "INDEX.md").read_text()
        self.assertIn("3 of 4 requests returned; reserved US$0.83; estimated US$0.20 over 2 priced; "
                      "cost unknown: no_frozen_price_for_model ×1; invoice not verified", index)

    def test_a_v2_budget_ledger_says_its_settlement_was_not_recorded(self):
        (self.run / "source-budget.json").write_text(json.dumps({"schemaVersion": "sermon-source-budget-ledger-v2", "requests": {
            "asr.0000": {"status": "returned", "bounds": {"costMicrousd": 13_500}}}}))
        index = (self.export() / "INDEX.md").read_text()
        self.assertIn("1 without settlement (ledger sermon-source-budget-ledger-v2; SourceBudget.migrate_to_v3 books it)", index)

    def test_index_lists_outcome_timings_and_failures(self):
        index = (self.export() / "INDEX.md").read_text()
        self.assertIn("**failed** exit 1", index)
        self.assertIn("ValueError: not in the subpath", index)
        self.assertIn("| baseline | pass | 93 |", index)
        self.assertIn("Failed stages: `upload`", index)
        self.assertIn("Not copied: 1 .wav", index)

    def test_trial_case_results_are_exported_redacted_and_size_bounded(self):
        for name in ("diagnose.json", "refute.json", "risk.json"):
            (self.run / name).write_text(json.dumps({"cases": [{
                "caseId": "f05", "correct": False, "apiToken": "abcdefgh",
                "evidence": "/Users/private-user/run/evidence.txt"}]}))
        oversized = self.run / "nested" / "diagnose.json"
        oversized.parent.mkdir()
        oversized.write_text(" " * (digest.MAX_WHOLE_BYTES + 1))
        (self.run / "raw-response.json").write_text('{"private": "unlisted"}')

        dest = self.export()
        for name in ("diagnose.json", "refute.json", "risk.json"):
            result = json.loads((dest / self.run.name / name).read_text())
            self.assertEqual(result["cases"], [{"caseId": "f05", "correct": False,
                "apiToken": "<redacted>", "evidence": "~/run/evidence.txt"}])
        self.assertFalse((dest / self.run.name / "nested" / "diagnose.json").exists())
        self.assertFalse((dest / self.run.name / "raw-response.json").exists())
        manifest = json.loads((dest / "manifest.json").read_text())
        omitted = next(f for f in manifest["files"] if f["path"] == "nested/diagnose.json")
        self.assertEqual(omitted["omitted"], "over_size_cap")

    def test_long_log_keeps_head_tail_and_errors(self):
        lines = [f"line {i}\n" for i in range(1000)]
        lines[500] = "Traceback (most recent call last):\n"
        (self.run / "upload.log").write_text("".join(lines))
        dest = self.export()
        text = (dest / self.run.name / "upload.log").read_text()
        self.assertIn("line 0\n", text)
        self.assertIn("line 999\n", text)
        self.assertIn("[line 501] Traceback", text)
        self.assertNotIn("line 400\n", text)
        entry = next(f for f in json.loads((dest / "manifest.json").read_text())["files"] if f["path"] == "upload.log")
        self.assertTrue(entry["truncated"])

    def test_refuses_existing_digest_and_undated_name(self):
        self.export()
        for name in ("20261007-e2e", "e2e-only"):
            with self.assertRaises(SystemExit):
                digest.main([str(self.run), "--out", str(self.out), "--name", name])

    def test_default_name_is_dated_and_zip_is_opt_in(self):
        self.assertEqual(digest.main([str(self.run), "--out", str(self.out)]), 0)
        (dest,) = self.out.iterdir()
        self.assertRegex(dest.name, r"^\d{8}-e2e-20261007T193332Z$")

    def test_verify_passes_a_fresh_digest_and_catches_a_leak(self):
        dest = self.export()
        with patch.dict("os.environ", {"SPARK_TOKEN": "supersecretvalue123"}, clear=False):
            self.assertEqual(digest.main([str(dest), "--verify"]), 0)
            (dest / "INDEX.md").write_text("pasted sk-proj-abcdefghijklmnopqrstuvwxyz and supersecretvalue123\n")
            self.assertEqual(digest.main([str(dest), "--verify"]), 1)
            for leak in ('{"password": "correct horse battery staple"}\n', "token=abc123xyz\n"):
                (dest / "INDEX.md").write_text(leak)
                self.assertEqual(digest.main([str(dest), "--verify"]), 1, leak)

    def test_json_stays_valid_and_summary_status_is_indexed(self):
        (self.run / "summary.json").write_text(json.dumps({"locales": {
            "ko": {"status": "requires_repair", "reason": "g003 back-translation drift"},
            "es": {"status": "text_waiver_issued"}},
            "authorization": {"user": "x", "password": "y"}, "apiToken": "abcdefgh"}))
        dest = self.export()
        summary = json.loads((dest / self.run.name / "summary.json").read_text())
        self.assertEqual((summary["authorization"], summary["apiToken"]), ("<redacted>", "<redacted>"))
        index = (dest / "INDEX.md").read_text()
        self.assertIn("ko: **requires_repair** (g003 back-translation drift)", index)
        self.assertIn("es: **text_waiver_issued**", index)

    def test_non_ascii_run_directory_gets_a_publishable_default_name(self):
        run = self.base / "机器质检 run"
        run.mkdir()
        (run / "timings.tsv").write_text("stage\tstatus\tseconds\n")
        self.assertEqual(digest.main([str(run), "--out", str(self.out)]), 0)
        (dest,) = self.out.iterdir()
        self.assertRegex(dest.name, r"^\d{8}-run$")
        with self.assertRaises(SystemExit):
            digest.main([str(run), "--out", str(self.out), "--name", "20261008-机器质检"])

    def test_write_report_for_drivers_never_raises(self):
        with patch.object(digest, "ROOT", self.base):
            dest = digest.write_report([self.run], "machine-qc-text")
            self.assertRegex(dest.name, r"^\d{8}-\d{6}-machine-qc-text$")
            self.assertTrue((dest / "INDEX.md").exists())
            self.assertIsNone(digest.write_report([self.base / "missing"], "machine-qc-text"))

    def test_oversized_trial_rows_are_exported_in_chunks(self):
        rows = [{"case": f"c{i}", "note": "x " * 1000, "email": "someone@example.com"} for i in range(40)]
        (self.run / "risk.json").write_text(json.dumps({"rows": rows, "summary": {"n": 40}}))
        with patch.object(digest, "MAX_WHOLE_BYTES", 20 * 1024):
            dest = self.export()
        entry = next(e for e in json.loads((dest / "manifest.json").read_text())["files"] if e["path"] == "risk.json")
        self.assertNotIn("omitted", entry)
        self.assertGreater(len(entry["chunks"]), 1)
        parts = [json.loads((dest / self.run.name / name).read_text()) for name in entry["chunks"]]
        self.assertEqual([r["case"] for p in parts for r in p["rows"]], [r["case"] for r in rows])
        self.assertEqual(parts[0]["summary"], {"n": 40})
        self.assertTrue(all(len((dest / self.run.name / n).read_bytes()) <= 20 * 1024 for n in entry["chunks"]))
        self.assertNotIn("someone@example.com", (dest / self.run.name / entry["chunks"][0]).read_text())
        index = json.loads((dest / self.run.name / "risk.json").read_text())
        self.assertEqual(index, {"source": "risk.json", "chunked": True, "rowCount": 40, "parts": entry["chunks"]})

    def test_compact_rows_that_grow_past_the_cap_when_indented_are_chunked(self):
        rows = [{"case": f"c{i}", "ok": True, "tier": "approval"} for i in range(600)]
        compact = json.dumps({"rows": rows}, separators=(",", ":"))
        (self.run / "risk.json").write_text(compact)
        cap = len(compact) + 1024
        self.assertGreater(len(json.dumps({"rows": rows}, indent=2)), cap)
        with patch.object(digest, "MAX_WHOLE_BYTES", cap):
            dest = self.export()
        entry = next(e for e in json.loads((dest / "manifest.json").read_text())["files"] if e["path"] == "risk.json")
        self.assertNotIn("omitted", entry)
        self.assertGreater(len(entry["chunks"]), 1)
        self.assertTrue(all(len((dest / self.run.name / n).read_bytes()) <= cap for n in entry["chunks"]))
        self.assertEqual(json.loads((dest / self.run.name / "risk.json").read_text())["rowCount"], 600)

    def test_trial_row_over_the_cap_is_reported_as_omitted(self):
        (self.run / "risk.json").write_text(json.dumps({"rows": [{"case": "c0", "note": "x " * 15000}]}))
        with patch.object(digest, "MAX_WHOLE_BYTES", 20 * 1024):
            dest = self.export()
        entry = next(e for e in json.loads((dest / "manifest.json").read_text())["files"] if e["path"] == "risk.json")
        self.assertEqual(entry["omitted"], "over_size_cap")
        self.assertNotIn("chunks", entry)
        self.assertEqual(list((dest / self.run.name).glob("risk.rows-*.json")), [])
        self.assertFalse((dest / self.run.name / "risk.json").exists())

    def test_oversized_digest_writes_nothing(self):
        with patch.object(digest, "MAX_DIGEST_BYTES", 10):
            self.assertEqual(digest.main([str(self.run), "--out", str(self.out), "--name", "20261007-big"]), 1)
        self.assertFalse((self.out / "20261007-big").exists())


if __name__ == "__main__":
    unittest.main()
