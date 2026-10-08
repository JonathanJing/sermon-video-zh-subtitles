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

    def test_index_lists_outcome_timings_and_failures(self):
        index = (self.export() / "INDEX.md").read_text()
        self.assertIn("**failed** exit 1", index)
        self.assertIn("ValueError: not in the subpath", index)
        self.assertIn("| baseline | pass | 93 |", index)
        self.assertIn("Failed stages: `upload`", index)
        self.assertIn("Not copied: 1 .wav", index)

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

    def test_write_report_for_drivers_never_raises(self):
        with patch.object(digest, "ROOT", self.base):
            dest = digest.write_report([self.run], "machine-qc-text")
            self.assertRegex(dest.name, r"^\d{8}-\d{6}-machine-qc-text$")
            self.assertTrue((dest / "INDEX.md").exists())
            self.assertIsNone(digest.write_report([self.base / "missing"], "machine-qc-text"))

    def test_oversized_digest_writes_nothing(self):
        with patch.object(digest, "MAX_DIGEST_BYTES", 10):
            self.assertEqual(digest.main([str(self.run), "--out", str(self.out), "--name", "20261007-big"]), 1)
        self.assertFalse((self.out / "20261007-big").exists())


if __name__ == "__main__":
    unittest.main()
