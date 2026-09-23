import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from scripts import generate_multilingual_fragment_poc as subject
from scripts import judge_english_source_for_translation as machine_judge
from scripts import prepare_sentence_interpretation_shadow as shadow
from tests.test_prepare_sentence_interpretation_shadow import write_segments


class GenerateMultilingualFragmentPocTests(unittest.TestCase):
    def test_shadow_groups_keep_western_word_boundaries_and_unit_reviews(self):
        checks = {name: "pass" for name in ("completeMeaning", "negationsNumbersNames",
                                             "quotationAttribution", "noAddedMeaning")}
        units = [("u1", "La palabra.", {"evidence": "First sentence."}, checks, True),
                 ("u2", "Dios habla.", {"evidence": "Second sentence."}, checks, True)]
        groups = subject.build_shadow_groups("fragment", "es", "a" * 64, units)
        self.assertEqual([group["sourceUnitIds"] for group in groups], [["u1"], ["u2"]])
        self.assertEqual([group["targetText"] for group in groups], ["La palabra.", "Dios habla."])
        self.assertTrue(all(group["targetText"] == "".join(group["targetUtterances"])
                            for group in groups))
        self.assertEqual(groups[1]["semanticReview"]["evidence"], "Second sentence.")

    def test_selected_locales_are_exact_and_ordered(self):
        source_ids = ["u1", "u2"]
        value = {"locales": [{"targetLocale": locale, "units": [
            {"sourceUnitId": unit, "targetText": f"{locale}-{unit}"} for unit in source_ids
        ]} for locale in ("zh-Hans", "ko", "es")]}
        result = subject.index_output(value, source_ids, review=False,
                                      target_locales=["zh-Hans", "ko", "es"])
        self.assertEqual(list(result), ["zh-Hans", "ko", "es"])
        value["locales"].append({"targetLocale": "vi", "units": []})
        with self.assertRaisesRegex(ValueError, "Unexpected or duplicate locale"):
            subject.index_output(value, source_ids, review=False,
                                 target_locales=["zh-Hans", "ko", "es"])

    def test_mismatched_anchor_stops_before_secret_or_model_call(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "segments.json"
            write_segments(source)
            receipt = shadow.prepare_shadow(source, root / "shadow")
            anchor = Path(receipt["artifacts"]["anchorManifest"]["path"])

            def passing_judge(_api_key, payload):
                request = json.loads(payload["messages"][1]["content"])
                sentences = [{
                    "sourceSentenceId": item["sourceSentenceId"],
                    "sourceUnitIds": [unit["sourceUnitId"] for unit in item["units"]],
                    "verdict": "pass",
                    "risk": "low",
                    "checks": {check: "pass" for check in machine_judge.CHECKS},
                    "evidence": "Frozen English is complete, ordered, and bound to its word timing.",
                    "unresolvedIssues": [],
                } for item in request["sentences"]]
                return {
                    "id": "machine-judge-fixture",
                    "created": 1790000000,
                    "model": "gpt-6-astra-2026-09-01",
                    "choices": [{"finish_reason": "stop", "message": {"content": json.dumps({
                        "schemaVersion": machine_judge.BATCH_SCHEMA,
                        "sentences": sentences,
                    })}}],
                }

            judge_path = root / "judge" / "receipt.json"
            machine_judge.run(
                aligned_path=source, manifest_path=anchor, out=judge_path,
                api_key="fixture-key", caller=passing_judge,
            )
            receipt = shadow.prepare_shadow(
                source, root / "judged-shadow", machine_judge_path=judge_path,
            )
            package = Path(receipt["artifacts"]["englishSourcePackage"]["path"])
            anchor_value = json.loads(anchor.read_text(encoding="utf-8"))
            package_value = json.loads(package.read_text(encoding="utf-8"))
            subject.validate_source_inputs(anchor_value, package_value)
            package_value["anchors"]["artifact"]["jsonSha256"] = "0" * 64
            package.write_text(json.dumps(package_value), encoding="utf-8")
            source_id = anchor_value["sourceUnits"][0]["sourceUnitId"]
            argv = ["generate_multilingual_fragment_poc.py", "--anchor-manifest", str(anchor),
                    "--english-source-package", str(package), "--source-unit", source_id,
                    "--api-key-secret", "unused", "--out", str(root / "out")]
            with mock.patch.object(sys, "argv", argv), \
                 mock.patch.object(subject, "cloud_access_secret") as secret, \
                 mock.patch.object(subject, "request_json") as model:
                with self.assertRaisesRegex(ValueError, "different runs"):
                    subject.main()
                secret.assert_not_called()
                model.assert_not_called()

    def test_blocked_package_is_not_eligible_for_shadow_translation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "segments.json"
            write_segments(source)
            receipt = shadow.prepare_shadow(source, root / "shadow")
            anchors = json.loads(Path(receipt["artifacts"]["anchorManifest"]["path"]).read_text())
            package = json.loads(Path(receipt["artifacts"]["englishSourcePackage"]["path"]).read_text())
            with self.assertRaisesRegex(ValueError, "blocked"):
                subject.validate_source_inputs(anchors, package)


if __name__ == "__main__":
    unittest.main()
