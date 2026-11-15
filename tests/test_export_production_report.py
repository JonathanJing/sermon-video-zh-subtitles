"""Production report: one digest for every run directory of a page, private text only in the store."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.development import export_production_report as production
from tools.development import export_run_digest as digest

SFA = Path(__file__).resolve().parents[1] / "experiments" / "sentence-first-agent"


class ProductionReportTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.runs = self.base / "artifacts" / "sentence-first-agent"
        for name in ("20261115-x-zh", "20261115-x-ko", "20261115-x-es", "20261115-x-publish", "20261115-x-review",
                     "20261115-x-podcast-zh", "20261115-shared-source"):
            (self.runs / name).mkdir(parents=True)
        for locale in ("zh", "ko", "es"):
            run = self.runs / f"20261115-x-{locale}"
            (run / "outcome.json").write_text(json.dumps({"status": "track_ready_for_review"}))
            (run / "translations.jsonl").write_text('{"id": 1, "text": "私有译文 private translation"}\n', encoding="utf-8")
            (run / "journal.ndjson").write_text(
                '{"at": "2026-11-15T01:00:00+00:00", "stage": "l3.finish", "event": "started"}\n'
                '{"at": "2026-11-15T01:05:00+00:00", "stage": "l3.finish", "event": "finished"}\n')
        publish = self.runs / "20261115-x-publish"
        (publish / "stage1").mkdir()
        (publish / "publish-gate.json").write_text(json.dumps({"status": "pass", "failed": []}))
        (publish / "smoke-zh-Hans.json").write_text(json.dumps({"status": "pass"}))
        (publish / "stage1" / "deployment-attempt-v2.json").write_text(json.dumps({"status": "deployed"}))
        (self.runs / "20261115-x-review" / "human-review-verdict.json").write_text(json.dumps({"note": "听审意见"}))
        (self.runs / "20261115-shared-source" / "english-review.csv").write_text("id,text\n1,private english\n")
        self.out = self.base / "run-reports"
        self.store = self.base / "store"

    def test_stem_and_siblings(self):
        zh, ko = self.runs / "20261115-x-zh", self.runs / "20261115-x-ko"
        self.assertEqual(production.stem_of([zh, ko]), "20261115-x")
        self.assertEqual(production.stem_of([zh]), "20261115-x")
        self.assertEqual(production.stem_of([self.runs / "20261115-x-podcast-zh"]), "20261115-x-podcast")
        stem, dirs = production.production_dirs([zh], [self.runs / "20261115-shared-source"])
        self.assertEqual(stem, "20261115-x")
        self.assertEqual([d.name for d in dirs], ["20261115-shared-source", "20261115-x-es", "20261115-x-ko",
                                                  "20261115-x-publish", "20261115-x-review", "20261115-x-zh"])
        with self.assertRaises(ValueError):
            production.production_dirs([self.runs / "missing"])

    def test_export_writes_one_digest_and_private_bundles(self):
        result = production.export_production([self.runs / "20261115-x-zh"], also=[self.runs / "20261115-shared-source"],
                                              out=self.out, store_uri=str(self.store))
        self.assertEqual(result["problems"], [])
        report, = [Path(path) for path in result["reports"]]
        self.assertEqual(report.name, "20261115-x")
        manifest = json.loads((report / "manifest.json").read_text())
        self.assertEqual(len(manifest["runs"]), 6)
        copied = {f"{row['run']}/{row['path']}" for row in manifest["files"]}
        self.assertIn("20261115-x-publish/publish-gate.json", copied)
        self.assertIn("20261115-x-publish/smoke-zh-Hans.json", copied)
        self.assertIn("20261115-x-publish/stage1/deployment-attempt-v2.json", copied)
        public_text = "".join(p.read_text(encoding="utf-8") for p in report.rglob("*") if p.is_file())
        self.assertNotIn("私有译文", public_text)
        self.assertNotIn("private english", public_text)
        self.assertNotIn("听审意见", public_text)
        evidence = json.loads((report / production.EVIDENCE_NAME).read_text())
        self.assertTrue(evidence["uploaded"])
        self.assertEqual(len(evidence["bundles"]), 6)
        self.assertEqual(set(evidence["bundles"][0]),
                         {"runName", "store", "files", "omitted", "collectedAt", "manifestSha256"})
        self.assertIn("私有译文", (self.store / "runs/20261115-x-zh/translations.jsonl").read_text(encoding="utf-8"))
        self.assertTrue((self.store / "runs/20261115-shared-source/english-review.csv").is_file())
        self.assertEqual(digest.verify(report, []), [])
        self.assertEqual(digest.incomplete(report), [])

    def test_a_second_export_gets_a_new_name(self):
        first = production.export_production([self.runs / "20261115-x-zh"], out=self.out, upload=False)
        second = production.export_production([self.runs / "20261115-x-zh"], out=self.out, upload=False)
        self.assertEqual([Path(p).name for p in first["reports"] + second["reports"]], ["20261115-x", "20261115-x-r2"])
        evidence = json.loads((Path(first["reports"][0]) / production.EVIDENCE_NAME).read_text())
        self.assertFalse(evidence["uploaded"])

    def test_size_cap_splits_publish_from_the_rest(self):
        filler = json.dumps({"status": "pass", "rows": ["x" * 80] * 500})
        (self.runs / "20261115-x-publish" / "summary.json").write_text(filler)
        (self.runs / "20261115-x-zh" / "summary.json").write_text(filler)
        with patch.object(digest, "MAX_DIGEST_BYTES", 80_000):
            result = production.export_production([self.runs / "20261115-x-zh"], out=self.out, upload=False)
        self.assertEqual(sorted(Path(p).name for p in result["reports"]), ["20261115-x", "20261115-x-publish"])

    def test_upload_failure_keeps_the_digest(self):
        blocker = self.base / "not-a-directory"
        blocker.write_text("x")
        result = production.export_production([self.runs / "20261115-x-zh"], out=self.out,
                                              store_uri=str(blocker / "store"))
        self.assertEqual(len(result["reports"]), 1)
        self.assertTrue(any("private evidence not uploaded" in problem for problem in result["problems"]))


class PublishDriverHookTests(unittest.TestCase):
    def setUp(self):
        if str(SFA) not in sys.path:
            sys.path.insert(0, str(SFA))
        import sfa_publish
        self.sfa_publish = sfa_publish
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        (self.base / "runs" / "20261115-x-zh").mkdir(parents=True)
        (self.base / "runs" / "20261115-x-review").mkdir()

    def config(self):
        class Config:
            locales = ("zh-Hans",)
            verdict_path = self.base / "runs" / "20261115-x-review" / "human-review-verdict.json"
            english_source_path = self.base / "missing" / "english-source.json"

            def run_dir(inner, locale):
                return self.base / "runs" / "20261115-x-zh"
        return Config()

    def test_hook_passes_the_production_directories_and_never_raises(self):
        calls = []

        def fake(seeds, also=None):
            calls.append((seeds, also))
            raise RuntimeError("store unreachable")

        with patch("tools.development.export_production_report.export_production", fake), \
                patch.dict(os.environ, {"SFA_RUN_REPORT": "1"}):
            self.assertIsNone(self.sfa_publish._export_report(self.config(), self.base / "runs"))
        (seeds, also), = calls
        self.assertEqual([p.name for p in seeds], ["20261115-x-zh"])
        self.assertEqual([p.name for p in also], ["runs", "20261115-x-review"])

    def test_hook_can_be_turned_off(self):
        with patch("tools.development.export_production_report.export_production") as fake, \
                patch.dict(os.environ, {"SFA_RUN_REPORT": "0"}):
            self.assertIsNone(self.sfa_publish._export_report(self.config(), None))
        fake.assert_not_called()


if __name__ == "__main__":
    unittest.main()
