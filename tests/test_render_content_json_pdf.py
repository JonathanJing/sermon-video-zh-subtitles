import base64
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.workflows.dual_pdf import content_json_pdf as mod


COMMAND = [sys.executable, str(Path(__file__).resolve().parents[1] / "tools/ops/run.py"),
           "workflows.dual_pdf.content_json_pdf"]


CONTENT = {
    "schemaVersion": "sermon-full-video-text-content-v3",
    "pageId": "page-1",
    "targetLocale": "zh-Hans",
    "sourceLocale": "en",
    "status": "machine_checked",
    "durationSeconds": 3726,
    "audioDurationSeconds": 3700,
    "reviewMode": "formal",
    "series": "启示录",
    "title": "耶稣配得",
    "date": "2026年10月11日",
    "cues": [
        {"start": 0, "end": 4.5, "text": "神爱世人。", "source": "God so loved the world."},
        {"start": 4.5, "end": 3725.25, "text": "甚至将他的独生子赐给他们。", "source": "He gave his only Son."},
        {"start": 9, "end": 10, "text": "  "},
    ],
    "disclosure": {"locale": "zh-Hans", "text": "本页文稿经机器质检，未经人工审核。", "english": "Machine-checked."},
}


class RenderContentJsonPdfTest(unittest.TestCase):
    def test_srt_time_formats_hours(self):
        self.assertEqual(mod.srt_time(3725.25), "01:02:05,250")
        self.assertEqual(mod.srt_time(-1), "00:00:00,000")

    def test_content_cues_skip_empty_text_and_pair_source(self):
        primary, secondary = mod.content_cues(CONTENT)
        self.assertEqual([cue.text for cue in primary], ["神爱世人。", "甚至将他的独生子赐给他们。"])
        self.assertEqual(secondary[1].text, "He gave his only Son.")
        self.assertEqual(primary[1].end, "01:02:05,250")

    def test_machine_checked_disclosure_stays_in_footer(self):
        self.assertTrue(mod.footer_disclaimer(CONTENT).startswith("本页文稿经机器质检"))
        self.assertEqual(mod.footer_disclaimer({}), mod.renderer.COMPACT_DISCLAIMER)
        with self.assertRaises(SystemExit):
            mod.footer_disclaimer({"status": "machine_checked"})

    def test_english_reference_fills_missing_source_by_group(self):
        content = {"pageId": "page-1", "targetLocale": "zh-Hans",
                   "cues": [{"start": 0, "end": 2, "text": "神爱世人。", "textGroupId": "g1"}]}
        reference = {"schemaVersion": "sermon-published-english-reference-v1", "reviewState": "human_approved",
                     "pageId": "page-1", "targets": {"zh-Hans": {
            "contentSha256": "abc", "blocks": [{"textGroupId": "g1", "english": "God so loved the world."}]}}}
        english = mod.reference_english(reference, content, "abc")
        _, secondary = mod.content_cues(content, english)
        self.assertEqual(secondary[0].text, "God so loved the world.")
        with self.assertRaises(SystemExit):
            mod.reference_english(reference, content, "other")
        with self.assertRaises(SystemExit):
            mod.reference_english(dict(reference, reviewState="draft"), content, "abc")

    def test_partial_english_is_rejected(self):
        content = {"cues": [{"start": 0, "end": 1, "text": "一。", "source": "One."},
                            {"start": 1, "end": 2, "text": "二。"}]}
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(SystemExit):
            mod.render_content_pdf(content, out=Path(tmp) / "p.pdf")

    def test_missing_english_is_rejected_unless_target_only(self):
        content = {"pageId": "page-1", "cues": [{"start": 0, "end": 2, "text": "神爱世人。"}]}
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "page.pdf"
            with self.assertRaises(SystemExit):
                mod.render_content_pdf(content, out=out)
            mod.render_content_pdf(content, out=out, include_english=False)
            self.assertTrue(out.read_bytes().startswith(b"%PDF"))

    def test_check_content_rejects_legacy_foreign_and_unsafe_pages(self):
        mod.check_content(CONTENT, "page-1")
        for bad in ({"schemaVersion": "sermon-demo-content-v1"}, {"targetLocale": "ko"}, {"pageId": "../x"},
                    {"status": "draft"}, {"schemaVersion": "sermon-full-video-text-content-v2"}):
            with self.assertRaises(SystemExit):
                mod.check_content(dict(CONTENT, **bad))
        with self.assertRaises(SystemExit):
            mod.check_content(CONTENT, "other-page")

    def test_overlapping_cues_keep_their_own_english(self):
        primary = [mod.renderer.Cue("00:00:00,000", "00:00:02,000", "一。"),
                   mod.renderer.Cue("00:00:01,500", "00:00:03,000", "二。")]
        blocks = mod.renderer.build_reading_blocks(primary, paired_secondary=["One.", "Two."])
        self.assertEqual(" ".join(block.secondary for block in blocks), "One. Two.")

    def test_partial_inline_english_still_needs_reference(self):
        self.assertTrue(mod.has_inline_english(CONTENT))
        mixed = {"cues": [{"text": "一。", "source": "One."}, {"text": "二。"}]}
        self.assertFalse(mod.has_inline_english(mixed))

    def test_reference_overrides_inline_source_and_timing_is_checked(self):
        content = {"cues": [{"start": 0, "end": 1, "text": "一。", "source": "Stale.", "textGroupId": "g1"}]}
        _, secondary = mod.content_cues(content, {"g1": "Approved."})
        self.assertEqual(secondary[0].text, "Approved.")
        for bad in ({"start": 2, "end": 1}, {"end": 1}, {"start": 0, "end": 99}):
            cue = dict({"start": 0, "end": 1, "text": "一。"}, **bad)
            if "start" not in bad and bad.get("end") == 1:
                cue.pop("start")
            with self.assertRaises(SystemExit):
                mod.content_cues({"durationSeconds": 10, "cues": [cue]})

    def test_out_of_order_cues_are_rejected(self):
        cues = [{"start": 10, "end": 11, "text": "一。"}, {"start": 0, "end": 1, "text": "二。"}]
        with self.assertRaises(SystemExit):
            mod.content_cues({"cues": cues})

    def test_renders_pdf_from_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "page.pdf"
            qa = mod.render_content_pdf(json.loads(json.dumps(CONTENT)), out=out)
            self.assertTrue(out.read_bytes().startswith(b"%PDF"))
            self.assertEqual(qa["contentStatus"], "machine_checked")
            self.assertTrue(qa["font"])
            self.assertEqual((qa["includeEnglish"], qa["includeTimecodes"]), (True, True))

    def test_cli_renders_local_content_from_other_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "content.json").write_text(json.dumps(CONTENT, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run([*COMMAND, "--content", "content.json", "--out", "out/page.pdf"],
                                    cwd=folder, capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((folder / "out/page.pdf").read_bytes().startswith(b"%PDF"))
            qa = json.loads((folder / "out/page.qa.json").read_text(encoding="utf-8"))
            self.assertEqual(qa["contentSource"], "content.json")
            self.assertEqual(qa["contentStatus"], "machine_checked")


class _FakeIamConfig:
    def __init__(self, uniform=True, pap="enforced"):
        self.uniform_bucket_level_access_enabled = uniform
        self.public_access_prevention = pap


class _FakeBlob:
    def __init__(self, name, *, corrupt=False):
        self.name = name
        self.corrupt = corrupt
        self.content_type = None
        self.md5_hash = None
        self.generation = 1
        self.data = b""

    def upload_from_string(self, data, content_type=None):
        self.data, self.content_type = data, content_type
        digest = hashlib.md5(data).digest()
        self.md5_hash = base64.b64encode(hashlib.md5(b"tampered").digest() if self.corrupt else digest).decode()
        self.generation += 1

    def reload(self):
        pass


class _FakeBucket:
    def __init__(self, name, *, uniform=True, pap="enforced", corrupt=False):
        self.name = name
        self.iam_configuration = _FakeIamConfig(uniform, pap)
        self.blobs = {}
        self.corrupt = corrupt

    def reload(self):
        pass

    def blob(self, name):
        return self.blobs.setdefault(name, _FakeBlob(name, corrupt=self.corrupt))


class _FakeClient:
    """Stands in for google.cloud.storage.Client so tests never touch the network."""

    def __init__(self, *, uniform=True, pap="enforced", corrupt=False):
        self.options = {"uniform": uniform, "pap": pap, "corrupt": corrupt}
        self.buckets = {}

    def bucket(self, name):
        return self.buckets.setdefault(name, _FakeBucket(name, **self.options))


class GcsUploadTest(unittest.TestCase):
    PDF_BYTES = b"%PDF-1.4 fake reading edition"

    def _files(self, folder: Path, *, corrupt: bool = False):
        pdf = folder / "page.pdf"
        pdf.write_bytes(self.PDF_BYTES)
        qa, qa_path = {"status": "pass"}, folder / "page.qa.json"
        mod.write_qa(qa_path, qa)
        return pdf, qa, qa_path

    def test_gcs_uri_names_one_pdf_object(self):
        self.assertEqual(mod.parse_gcs_pdf_uri(" gs://bkt/s/2026-11-22/reading-pdf/a.pdf "),
                         ("bkt", "s/2026-11-22/reading-pdf/a.pdf"))
        self.assertEqual(mod.qa_object_name("s/2026-11-22/reading-pdf/a.pdf"),
                         "s/2026-11-22/reading-pdf/a.qa.json")
        for bad in ("s3://bkt/a.pdf", "gs://bkt/a.txt", "gs://bkt/../a.pdf", "gs://bkt//a.pdf",
                    "gs://bkt", "gs:///a.pdf", "gs://bkt/a.pdf?x=1"):
            with self.assertRaises(ValueError):
                mod.parse_gcs_pdf_uri(bad)

    def test_upload_refuses_a_bucket_that_could_publish_sermon_text(self):
        mod.require_private_bucket("bkt", client=_FakeClient())
        for options in ({"uniform": False}, {"pap": None}, {"pap": "inherited"}):
            with self.assertRaises(SystemExit):
                mod.require_private_bucket("bkt", client=_FakeClient(**options))

    def test_publish_uploads_pdf_then_the_qa_report_that_records_it(self):
        client = _FakeClient()
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            pdf, qa, qa_path = self._files(folder)
            result = mod.publish_reading_pdf(
                pdf, qa, qa_path, uri="gs://bkt/sundays/2026-11-22/reading-pdf/page.pdf", client=client)
            stored = client.bucket("bkt").blobs
            pdf_name = "sundays/2026-11-22/reading-pdf/page.pdf"
            qa_name = "sundays/2026-11-22/reading-pdf/page.qa.json"
            self.assertEqual(sorted(stored), [pdf_name, qa_name])
            self.assertEqual(stored[pdf_name].data, self.PDF_BYTES)
            self.assertEqual(stored[pdf_name].content_type, "application/pdf")
            self.assertEqual(stored[qa_name].content_type, "application/json")
            self.assertEqual(result["pdf"]["md5Hex"], hashlib.md5(self.PDF_BYTES).hexdigest())
            self.assertTrue(result["pdf"]["verified"] and result["qa"]["verified"])
            saved = json.loads(qa_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["gcs"]["pdf"]["uri"], result["pdf"]["uri"])
            self.assertEqual(saved["gcs"]["pdf"]["generation"], result["pdf"]["generation"])
            self.assertEqual(saved["status"], "pass")
            # the report stored beside the PDF is the local one, upload block included
            self.assertEqual(stored[qa_name].data, qa_path.read_bytes())

    def test_stored_bytes_that_differ_fail_the_upload(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            pdf, qa, qa_path = self._files(folder)
            with self.assertRaises(SystemExit):
                mod.publish_reading_pdf(
                    pdf, qa, qa_path, uri="gs://bkt/s/page.pdf", client=_FakeClient(corrupt=True))
            self.assertEqual(json.loads(qa_path.read_text(encoding="utf-8")), {"status": "pass"})

    def test_cli_rejects_a_gcs_uri_without_a_pdf_object(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "content.json").write_text(json.dumps(CONTENT, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run(
                [*COMMAND, "--content", "content.json", "--out", "out/page.pdf",
                 "--gcs-uri", "gs://bkt/page.json"],
                cwd=folder, capture_output=True, text=True, timeout=120)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("gcs-uri", result.stderr)


if __name__ == "__main__":
    unittest.main()
