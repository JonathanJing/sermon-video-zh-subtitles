import importlib.util
from pathlib import Path
import unittest


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("render_sentence_reanchor", HERE / "render_sentence_reanchor.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class RenderSentenceReanchorTests(unittest.TestCase):
    def report(self):
        return {
            "structuralPass": True,
            "releaseEligible": False,
            "input": {"clipSourceStartSeconds": 300.0, "sermonSourceStartSeconds": 100.0},
            "translationGroups": [{
                "translationGroupId": "g1",
                "chinese": "中文。",
                "sentenceAnchoredPlan": {"start": 203.0, "end": 211.0},
                "measuredChineseAudio": {"currentStart": 190.0, "currentEnd": 198.0},
            }],
        }

    def test_plan_coordinates_places_audio_inside_clip(self):
        plan = MODULE.plan_coordinates(self.report(), 14.0)
        self.assertEqual(plan["plannedDelaySeconds"], 3.0)
        self.assertEqual(plan["plannedLocalEndSeconds"], 11.0)
        self.assertEqual(plan["cueDurationSeconds"], 8.0)

    def test_plan_coordinates_rejects_overflow(self):
        report = self.report()
        report["translationGroups"][0]["sentenceAnchoredPlan"]["end"] = 216.0
        with self.assertRaisesRegex(ValueError, "does not fit"):
            MODULE.plan_coordinates(report, 14.0)


if __name__ == "__main__":
    unittest.main()
