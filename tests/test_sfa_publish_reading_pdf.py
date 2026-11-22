"""Reading-PDF archive step: a passed readback also stores the weekly PDF, observing only.

The step must name the object from the page (never from a guess), report success only for a
verified upload, and never turn a publishing result into a failure.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "experiments" / "sentence-first-agent" / "sfa_publish.py"


def load():
    spec = importlib.util.spec_from_file_location("sfa_publish_reading_pdf", PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["sfa_publish_reading_pdf"] = module
    spec.loader.exec_module(module)
    return module


VERIFIED = json.dumps({
    "status": "ok", "qaStatus": "pass", "cueCount": 457,
    "gcs": {"pdf": {"uri": "gs://bkt/sundays/2026-11-22/reading-pdf/a.pdf", "verified": True},
            "qa": {"uri": "gs://bkt/sundays/2026-11-22/reading-pdf/a.qa.json", "verified": True}},
})


class Config:
    page_id = "revelation-jesus-will-return-20261122"
    date = "2026-11-22"
    title = "耶稣必再来"
    locales = ("zh-Hans", "ko", "es")

    def __init__(self, runs_root: Path):
        self.runs_root = runs_root

    def origin(self) -> str:
        return "https://example.test"

    def run_dir(self, locale: str) -> Path:
        return self.runs_root / f"20261121-jesus-will-return-{locale}"


class ReadingPdfArchiveTest(unittest.TestCase):
    def setUp(self):
        self.mod = load()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = Config(Path(self.tmp.name))
        self.addCleanup(os.environ.pop, "SFA_READING_PDF", None)
        self.addCleanup(os.environ.pop, "TONGXING_ARTIFACT_BUCKET", None)

    def test_object_and_local_path_come_from_the_page(self):
        local, uri = self.mod._reading_pdf_destination(self.cfg)
        self.assertEqual(uri, "gs://sermon-zh-artifacts-ai-for-god/sundays/2026-11-22/"
                              "reading-pdf/2026-11-22-耶稣必再来-中英对照阅读版.pdf")
        self.assertEqual(local.parent.name, "reading-pdf")
        self.assertEqual(local.parent.parent, self.cfg.run_dir("zh-Hans"))
        self.assertFalse(local.exists())  # the destination is named, not created, here

    def test_bucket_override_and_unsafe_title(self):
        os.environ["TONGXING_ARTIFACT_BUCKET"] = "my-bucket"
        self.cfg.title = "耶稣 / 必再来"
        local, uri = self.mod._reading_pdf_destination(self.cfg)
        self.assertTrue(uri.startswith("gs://my-bucket/sundays/2026-11-22/reading-pdf/"))
        self.assertNotIn("/", uri.split("reading-pdf/")[1])
        self.assertIn("耶稣-必再来", local.name)

    def test_verified_upload_is_reported(self):
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout=VERIFIED, stderr="")
        with mock.patch.object(self.mod.subprocess, "run", return_value=completed) as run:
            report = self.mod._export_reading_pdf(self.cfg)
        self.assertEqual(report["qaStatus"], "pass")
        command = run.call_args.args[0]
        self.assertIn("workflows.dual_pdf.content_json_pdf", command)
        self.assertIn("--gcs-uri", command)
        self.assertEqual(command[command.index("--page-id") + 1], self.cfg.page_id)
        self.assertEqual(command[command.index("--base-url") + 1], self.cfg.origin())
        out = Path(command[command.index("--out") + 1])
        self.assertEqual(out.parent, self.cfg.run_dir("zh-Hans") / "reading-pdf")
        self.assertEqual(command[command.index("--gcs-uri") + 1],
                         self.mod._reading_pdf_destination(self.cfg)[1])

    def test_unverified_upload_is_not_reported_as_success(self):
        rejected = json.dumps({"qaStatus": "pass", "gcs": {"pdf": {"verified": False},
                                                          "qa": {"verified": False}}})
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout=rejected, stderr="")
        with mock.patch.object(self.mod.subprocess, "run", return_value=completed):
            self.assertIsNone(self.mod._export_reading_pdf(self.cfg))

    def test_failed_export_never_raises(self):
        failed = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="boom")
        with mock.patch.object(self.mod.subprocess, "run", return_value=failed):
            self.assertIsNone(self.mod._export_reading_pdf(self.cfg))
        with mock.patch.object(self.mod.subprocess, "run", side_effect=OSError("no gcloud")):
            self.assertIsNone(self.mod._export_reading_pdf(self.cfg))

    def test_switch_skips_the_step(self):
        os.environ["SFA_READING_PDF"] = "0"
        with mock.patch.object(self.mod.subprocess, "run") as run:
            self.assertIsNone(self.mod._export_reading_pdf(self.cfg))
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
