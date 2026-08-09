import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "render_sermon_companion_pdf.py"
SPEC = importlib.util.spec_from_file_location("render_sermon_companion_pdf", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class RenderSermonCompanionPdfTest(unittest.TestCase):
    def test_renders_companion_without_discussion_questions(self):
        insights = {
            "schemaVersion": 2,
            "artifactType": "sermon_companion",
            "sermonTitle": "在改变中信靠神",
            "speaker": "Eric Geiger",
            "sermonDate": "2026-08-09",
            "sourceLabel": "本材料基于所选直播版本；其他场次的具体措辞可能不同。",
            "summaryZh": "证道说明环境变化会引发焦虑，但神借着稳定的属灵节奏提醒我们继续信靠祂。",
            "outlineZh": [
                {"title": "变化带来的压力", "points": ["生活环境变化会放大人的焦虑。"]},
                {"title": "重新建立节奏", "points": ["经文与群体生活帮助人重新定向。"]},
            ],
            "scriptureRefs": ["腓立比书 4:6-7"],
            "quotes": [
                {
                    "textZh": "环境改变时，我们最容易感到焦虑。",
                    "sourceSegmentId": "srt-0007",
                    "sourceTextZh": "环境改变时，我们最容易感到焦虑。",
                    "sourceTextEn": "We are most anxious when our context changes.",
                    "startMs": 133_000,
                    "endMs": 140_000,
                    "exactSourceMatch": True,
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tempdir:
            out = Path(tempdir) / "sermon_companion_zh.pdf"
            qa = mod.render_companion_pdf(insights, out)

            self.assertTrue(out.read_bytes().startswith(b"%PDF"))
            self.assertGreater(out.stat().st_size, 500)
            self.assertEqual(qa["status"], "pass")
            self.assertFalse(qa["discussionQuestionsIncluded"])
            self.assertEqual(qa["forbiddenFieldPaths"], [])
            self.assertGreaterEqual(qa["pageCount"], 1)

    def test_qa_rejects_question_or_application_fields(self):
        insights = {
            "summaryZh": "证道摘要。",
            "outlineZh": [{"title": "要点", "points": ["内容"]}],
            "applicationQuestionsZh": ["你会如何回应？"],
        }
        with tempfile.TemporaryDirectory() as tempdir:
            qa = mod.render_companion_pdf(insights, Path(tempdir) / "companion.pdf")

        self.assertEqual(qa["status"], "needs_review")
        self.assertIn("applicationQuestionsZh", qa["forbiddenFieldPaths"])
        self.assertIn("discussion_or_application_fields_present", qa["failures"])

    def test_cli_writes_pdf_and_qa(self):
        insights = {
            "summaryZh": "证道摘要。",
            "outlineZh": [{"title": "要点", "points": ["内容"]}],
            "quotes": [],
        }
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            source = root / "insights.json"
            out = root / "companion.pdf"
            qa_out = root / "companion.qa.json"
            source.write_text(json.dumps(insights, ensure_ascii=False), encoding="utf-8")
            old_argv = sys.argv
            try:
                sys.argv = [str(SCRIPT_PATH), "--input", str(source), "--out", str(out), "--qa-out", str(qa_out)]
                self.assertEqual(mod.main(), 0)
            finally:
                sys.argv = old_argv

            qa = json.loads(qa_out.read_text(encoding="utf-8"))

        self.assertEqual(qa["status"], "pass")


if __name__ == "__main__":
    unittest.main()
