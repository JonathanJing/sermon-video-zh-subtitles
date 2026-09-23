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
        self.assertEqual(week["tracks"][0]["locale"], "zh-Hans", "Native listening stays Chinese-first")
        for track in week["tracks"]:
            name = f"{PAGE_ID}-{track['locale']}.mp3"
            self.assertEqual(track["file"], name)
            self.assertEqual(track["audioUrl"], f"/media/{name}")
            if track["locale"] == "en":
                expected_hash = load(PUBLIC / f"releases/{PAGE_ID}/en.json")["audioSha256"]
            else:
                expected_hash = load(PUBLIC / f"packages/layer3/{PAGE_ID}-{track['locale']}.json")["track"]["sha256"]
            self.assertEqual(track["sha256"], expected_hash)
        english = next(item for item in week["tracks"] if item["locale"] == "en")
        release = load(PUBLIC / f"releases/{PAGE_ID}/en.json")
        self.assertEqual(english["scope"], "english_source_reference_poc")
        self.assertEqual(english["subtitleTiming"], "layer_1_source_word_timeline")
        self.assertRegex(english["sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(release["audioSha256"], english["sha256"])
        self.assertEqual(len(english["cues"]), 6)

    def test_app_router_accepts_english(self):
        app = (PUBLIC / "app.js").read_text(encoding="utf-8")
        integrity = (PUBLIC / "dev-integrity.mjs").read_text(encoding="utf-8")
        self.assertIn("(en|zh-Hans|ko|es|vi)", app)
        self.assertIn("sermon-source-language-demo-package-v1", integrity)
        self.assertIn("fetchVerified(target.releasePackageUrl", app)
        self.assertIn("verifiedAudioURL(variant", app)

    def test_dev_release_hashes_bind_exact_committed_bytes(self):
        import hashlib

        catalog = load(PUBLIC / "multilingual.json")
        for page in catalog["pages"]:
            for locale, target in page["targets"].items():
                release_path = PUBLIC / target["releasePackageUrl"].lstrip("/")
                release = load(release_path)
                content_path = PUBLIC / release["contentUrl"].lstrip("/")
                self.assertEqual(
                    hashlib.sha256(release_path.read_bytes()).hexdigest(),
                    target["releasePackageJsonSha256"],
                    locale,
                )
                self.assertEqual(
                    hashlib.sha256(content_path.read_bytes()).hexdigest(),
                    release["contentSha256"],
                    locale,
                )

    def test_chinese_page_exposes_review_audio_variants_with_bound_timing(self):
        release = load(PUBLIC / f"releases/{PAGE_ID}/zh-Hans.json")
        content = load(PUBLIC / f"content/{PAGE_ID}/zh-Hans.json")
        variants = release["audioVariants"]
        self.assertEqual(
            [variant["id"] for variant in variants],
            [
                "current-poc", "source-pauses", "pace-instruct",
                "focus-baseline", "focus-internal-instruct", "focus-phrase-pauses",
                "focus-adaptive-pauses", "long-adaptive-pauses", "source-acoustic-pauses",
            ],
        )
        self.assertEqual(release["defaultAudioVariantId"], "source-pauses")
        self.assertIn("待人工校对", release["contentStatusLabel"])
        self.assertIn("待人工听审", release["audioStatusLabel"])
        expected_units = [cue["sourceUnitId"] for cue in content["cues"]]
        for variant in variants:
            self.assertRegex(variant["audioSha256"], r"^[0-9a-f]{64}$")
            if variant["id"] == "source-acoustic-pauses":
                self.assertEqual(variant["humanListeningStatus"], "user_reported_uncomfortable")
                self.assertIn("formal listening review remains pending", variant["listeningFeedback"])
            else:
                self.assertEqual(variant["humanListeningStatus"], "pending")
            self.assertFalse(variant["productionEligible"])
            if "cues" in variant:
                if variant.get("reviewFocus"):
                    self.assertTrue(all(
                        cue["sourceUnitId"].startswith(variant["reviewFocus"])
                        for cue in variant["cues"]
                    ))
                else:
                    self.assertEqual([cue["sourceUnitId"] for cue in variant["cues"]], expected_units)
                    self.assertEqual(len(variant["cues"]), 6)
                self.assertAlmostEqual(variant["cues"][-1]["end"], variant["durationSeconds"], delta=0.05)
        focus = [variant for variant in variants if variant.get("reviewFocus")]
        self.assertEqual(len(focus), 4)
        self.assertTrue(all(variant["reviewFocus"] == "block-59-u006" for variant in focus))
        adaptive = next(variant for variant in variants if variant["id"] == "focus-adaptive-pauses")
        self.assertEqual(len(adaptive["cues"]), 1)
        self.assertEqual(adaptive["cues"][0]["text"], content["cues"][-1]["text"])
        self.assertEqual(adaptive["internalSchedule"]["overrunPhraseCount"], 0)
        self.assertAlmostEqual(adaptive["internalSchedule"]["sentenceEndLagSeconds"], 0.28)
        long_sample = next(variant for variant in variants if variant["id"] == "long-adaptive-pauses")
        self.assertEqual(len(long_sample["cues"]), 6)
        self.assertEqual(long_sample["internalSchedule"]["phraseCount"], 18)
        self.assertEqual(long_sample["internalSchedule"]["sentenceCount"], 6)
        self.assertEqual([cue["text"] for cue in long_sample["cues"]], [cue["text"] for cue in content["cues"]])
        self.assertEqual(long_sample["internalSchedule"]["ratePolicy"], "measured_natural_phrase_audio_no_time_stretch")
        self.assertEqual(long_sample["supersededBy"], "source-pauses")
        acoustic = next(variant for variant in variants if variant["id"] == "source-acoustic-pauses")
        self.assertEqual(acoustic["supersededBy"], "source-pauses")
        self.assertEqual(len(acoustic["cues"]), 6)
        self.assertEqual(acoustic["internalSchedule"]["phraseCount"], 15)
        self.assertEqual(acoustic["internalSchedule"]["acousticSupportedInternalPauseCount"], 9)
        self.assertEqual([cue["text"] for cue in acoustic["cues"]], [cue["text"] for cue in content["cues"]])
        self.assertEqual(acoustic["machineScreeningStatus"], "pending_for_this_audio_variant")

    def test_app_supports_audio_variant_selection_and_variant_cues(self):
        app = (PUBLIC / "app.js").read_text(encoding="utf-8")
        html = (PUBLIC / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="audioVariantSelect"', html)
        self.assertIn("function activeCues()", app)
        self.assertIn("state.audioVariant?.cues", app)
        self.assertIn("tongxing-dev-audio-", app)

    def test_dev_shell_tracks_production_visual_base(self):
        production = ROOT / "experiments/sermon-dubbing-poc/web"
        self.assertTrue(
            (PUBLIC / "styles.css").read_bytes().startswith((production / "style.css").read_bytes()),
            "Dev CSS must start with the production stylesheet before Dev overrides",
        )
        self.assertEqual(
            (PUBLIC / "brand-icon.png").read_bytes(),
            (production / "brand-icon.png").read_bytes(),
        )


if __name__ == "__main__":
    unittest.main()
