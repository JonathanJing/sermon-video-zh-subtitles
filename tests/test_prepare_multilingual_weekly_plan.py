import importlib.util
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "prepare_multilingual_weekly_plan", ROOT / "scripts/prepare_multilingual_weekly_plan.py"
)
subject = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(subject)


class MultilingualWeeklyPlanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = json.loads((ROOT / "config/speaker-voice-registry.json").read_text())

    def source(self, status="candidate_ready_for_translation"):
        return {
            "schemaVersion": "sermon-english-source-package-v1",
            "packageId": "english-source-" + "a" * 24,
            "status": status,
            "candidateTranslationEligible": True,
            "translationEligible": status == "ready_for_translation",
            "downstreamInvalidationKey": "b" * 64,
        }

    def validate(self, filename, value):
        schema = json.loads((ROOT / "schemas" / filename).read_text())
        return list(Draft202012Validator(schema).iter_errors(value))

    def test_committed_registry_is_schema_valid_and_unique(self):
        self.assertEqual(self.validate("sermon-speaker-voice-registry-v1.schema.json", self.registry), [])
        subject.validate_registry(self.registry)
        self.assertEqual(len(self.registry["speakers"]), 6)
        self.assertEqual(self.registry["supportedTargetLocales"], ["zh-Hans", "ko", "es", "vi"])

    def test_shadow_plan_fans_out_without_locale_barrier(self):
        plan = subject.prepare_plan(
            self.source(),
            self.registry,
            speaker_id="jared_kirkwood",
            target_locales=["zh-Hans", "ko", "es", "vi"],
            mode="shadow",
        )
        self.assertEqual(self.validate("sermon-multilingual-weekly-plan-v1.schema.json", plan), [])
        self.assertEqual(plan["scheduling"]["localeBarrier"], "none")
        self.assertEqual([lane["targetLocale"] for lane in plan["lanes"]], ["zh-Hans", "ko", "es", "vi"])
        for lane in plan["lanes"]:
            self.assertEqual(lane["layer2"]["status"], "ready")
            self.assertEqual(lane["layer3"]["status"], "waiting_for_layer2_gate")

    def test_non_chinese_production_is_fail_closed_until_authorized_and_reviewed(self):
        with self.assertRaisesRegex(ValueError, "Production voice authorization is missing"):
            subject.prepare_plan(
                self.source("ready_for_translation"),
                self.registry,
                speaker_id="jared_kirkwood",
                target_locales=["ko"],
                mode="production",
            )

    def test_chinese_production_reuses_the_reviewed_checkpoint(self):
        plan = subject.prepare_plan(
            self.source("ready_for_translation"),
            self.registry,
            speaker_id="jared_kirkwood",
            target_locales=["zh-Hans"],
            mode="production",
        )
        self.assertEqual(plan["lanes"][0]["voice"]["capability"], "human_reviewed")
        self.assertEqual(plan["lanes"][0]["voice"]["adapter"], "qwen3_tts_sft")

    def test_vietnamese_lane_uses_its_explicit_adapter(self):
        plan = subject.prepare_plan(
            self.source(), self.registry, speaker_id="eric_geiger", target_locales=["vi"], mode="shadow"
        )
        voice = plan["lanes"][0]["voice"]
        self.assertEqual(voice["adapter"], "gwen_tts_zero_shot_reference")
        self.assertEqual(voice["model"], "g-group-ai-lab/gwen-tts-0.6B")
        self.assertTrue(voice["conditioningRef"].startswith("speaker-reference://"))

    def test_source_or_locale_changes_plan_identity(self):
        first = subject.prepare_plan(
            self.source(), self.registry, speaker_id="eric_geiger", target_locales=["ko"], mode="shadow"
        )
        second = subject.prepare_plan(
            self.source(), self.registry, speaker_id="eric_geiger", target_locales=["vi"], mode="shadow"
        )
        self.assertNotEqual(first["planId"], second["planId"])


if __name__ == "__main__":
    unittest.main()
