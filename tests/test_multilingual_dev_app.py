import json
from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]
PUBLIC = ROOT / "firebase/dev/public"
PAGE_ID = "2026-09-20-lion-of-judah-poc"
LOCALES = ("en", "zh-Hans", "ko", "es", "vi")


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class MultilingualDevAppTest(unittest.TestCase):
    def test_catalog_exposes_english_source_before_target_languages(self):
        catalog = load(PUBLIC / "multilingual.json")
        page = next(item for item in catalog["pages"] if item["id"] == PAGE_ID)
        self.assertEqual(tuple(page["targets"]), LOCALES)
        self.assertEqual(page["sourceWindow"]["timebase"], "sermon_relative_seconds")
        self.assertEqual(page["sourceWindow"]["sourceMediaOffsetSeconds"], 1789.0)
        self.assertAlmostEqual(
            page["sourceWindow"]["sourceMediaOffsetSeconds"] + page["sourceWindow"]["startSeconds"],
            3647.4,
        )
        english = page["targets"]["en"]
        self.assertEqual(english["contentStatus"], "source_reference_machine_boundaries_human_review_pending")
        self.assertEqual(english["audioStatus"], "original_source")

    def test_english_page_is_source_reference_not_layer2_or_layer3(self):
        release = load(PUBLIC / f"releases/{PAGE_ID}/en.json")
        content = load(PUBLIC / f"content/{PAGE_ID}/en.json")
        self.assertEqual(release["schemaVersion"], "sermon-source-language-demo-package-v1")
        self.assertNotIn("layer2PackageUrl", release)
        self.assertNotIn("layer3PackageUrl", release)
        self.assertEqual(content["captionTiming"], "layer_1_source_word_timeline")
        self.assertEqual(content["audioStatus"], "original_source")
        self.assertFalse(release["productionEligible"])
        self.assertFalse(release["humanApproval"])

    def test_every_translation_uses_the_same_english_source_units(self):
        english = load(PUBLIC / f"content/{PAGE_ID}/en.json")
        expected = [(cue["sourceUnitId"], cue["text"]) for cue in english["cues"]]
        for locale in LOCALES[1:]:
            content = load(PUBLIC / f"content/{PAGE_ID}/{locale}.json")
            observed = [(cue["sourceUnitId"], cue["source"]) for cue in content["cues"]]
            self.assertEqual(observed, expected, locale)

    def test_weekly_manifest_binds_original_english_audio(self):
        weekly = load(PUBLIC / "weekly.json")
        week = next(item for item in weekly["weeks"] if item["id"] == PAGE_ID)
        english = next(item for item in week["tracks"] if item["locale"] == "en")
        release = load(PUBLIC / f"releases/{PAGE_ID}/en.json")
        self.assertEqual(english["scope"], "english_source_reference_poc")
        self.assertEqual(english["subtitleTiming"], "layer_1_source_word_timeline")
        self.assertRegex(english["sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(release["audioSha256"], english["sha256"])
        self.assertEqual(len(english["cues"]), 6)

    def test_app_router_accepts_english(self):
        app = (PUBLIC / "app.js").read_text(encoding="utf-8")
        self.assertIn("(en|zh-Hans|ko|es|vi)", app)
        self.assertIn("sermon-source-language-demo-package-v1", app)
        self.assertIn('searchParams.set("sha256", release.audioSha256)', app)


if __name__ == "__main__":
    unittest.main()
