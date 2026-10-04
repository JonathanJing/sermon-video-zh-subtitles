import json
from pathlib import Path
import tempfile
import unittest

from jsonschema import Draft202012Validator, FormatChecker

from scripts import build_english_source_package as layer1
from scripts import judge_english_source_for_translation as subject
from scripts import sermon_sentence_interpretation as anchors


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


class EnglishSourceMachineJudgeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.aligned_path = self.root / "segments.json"
        words = ["Your", "sin", "and", "your", "death", "faced", "its", "death", "on", "the", "cross."]
        word_times = []
        cursor = 0.0
        for word in words:
            word_times.append({"text": word, "start": cursor, "end": cursor + 0.7})
            cursor += 0.75
        self.segments = [{
            "id": 0,
            "referenceChunkId": "block-00",
            "text": " ".join(words),
            "start": word_times[0]["start"],
            "end": word_times[-1]["end"],
            "sentenceBoundarySource": "frozen_reference_punctuation",
            "wordTimes": word_times,
        }]
        write_json(self.aligned_path, self.segments)
        self.manifest = anchors.build_anchor_manifest(
            self.segments,
            source_path=self.aligned_path,
            unit_policy=anchors.UNIT_POLICY_V2,
            max_unit_seconds=4.0,
        )
        self.assertEqual(
            [issue["type"] for issue in self.manifest["issues"]],
            ["clause_unit_exceeds_target_without_safe_boundary"],
        )
        self.manifest_path = self.root / "anchor-manifest.json"
        write_json(self.manifest_path, self.manifest)

    def fake_caller(self, _api_key, payload):
        request = json.loads(payload["messages"][1]["content"])
        rows = []
        for sentence in request["sentences"]:
            rows.append({
                "sourceSentenceId": sentence["sourceSentenceId"],
                "sourceUnitIds": [unit["sourceUnitId"] for unit in sentence["units"]],
                "verdict": "pass",
                "risk": "medium",
                "checks": {name: "pass" for name in subject.CHECKS},
                "evidence": "All English words remain ordered; the long unit retains the complete claim and bound timing.",
                "unresolvedIssues": [],
            })
        return {
            "id": "judge-response-1",
            "created": 1790000000,
            "model": "gpt-6-astra-2026-09-01",
            "choices": [{
                "finish_reason": "stop",
                "message": {"content": json.dumps({
                    "schemaVersion": subject.BATCH_SCHEMA,
                    "sentences": rows,
                })},
            }],
        }

    def test_prewarm_and_final_share_canonical_cache_across_output_directories(self):
        calls = []
        def caller(key, payload):
            calls.append(payload)
            return self.fake_caller(key, payload)
        warm_out = self.root / "warm" / "judge.json"
        warm = subject.run(aligned_path=self.aligned_path, manifest_path=self.manifest_path,
                           out=warm_out, api_key="", caller=caller, workers=3, prewarm=True)
        self.assertFalse(warm_out.exists())
        final = subject.run(aligned_path=self.aligned_path, manifest_path=self.manifest_path,
                            out=self.root / "final" / "judge.json", api_key="", caller=caller)
        self.assertEqual(len(calls), 1)
        self.assertEqual(warm, final)
        self.assertFalse(final["humanApproval"])

    def test_deterministic_review_rebuilds_explicit_boundary_override(self):
        words = ["Alpha", "bravo", "charlie", "delta,", "echo", "foxtrot,",
                 "golf", "hotel", "india", "juliet."]
        timed = []
        cursor = 0.0
        for word in words:
            timed.append({"text": word, "start": cursor, "end": cursor + 0.4})
            cursor += 0.5
        aligned = [{"id": 0, "referenceChunkId": "block-00", "text": " ".join(words),
                    "start": 0.0, "end": timed[-1]["end"],
                    "sentenceBoundarySource": "frozen_reference_punctuation", "wordTimes": timed}]
        write_json(self.aligned_path, aligned)
        manifest = anchors.build_anchor_manifest(
            aligned, source_path=self.aligned_path, unit_policy=anchors.UNIT_POLICY_V2,
            max_unit_seconds=3.0,
            boundary_overrides={"block-00-s001": "block-00-w0004"},
        )
        self.assertEqual(subject.deterministic_review(self.aligned_path, manifest)["status"], "pass")
        changed = json.loads(json.dumps(manifest))
        changed["sourceUnits"][0]["english"] = "tampered"
        self.assertEqual(subject.deterministic_review(self.aligned_path, changed)["status"], "fail")

    def test_machine_judge_passes_reviewable_anchor_issue_for_layer2_shadow_only(self):
        receipt_path = self.root / "judge" / "receipt.json"
        receipt = subject.run(
            aligned_path=self.aligned_path,
            manifest_path=self.manifest_path,
            out=receipt_path,
            api_key="fixture-key",
            caller=self.fake_caller,
        )
        self.assertEqual(receipt["status"], "approved_for_layer2_shadow")
        self.assertTrue(receipt["layer2DevelopmentEligible"])
        self.assertFalse(receipt["productionTranslationEligible"])
        self.assertFalse(receipt["humanApproval"])
        self.assertEqual(receipt["counts"]["sentencePass"], 1)
        schema = json.loads((
            Path(__file__).parents[1] / "schemas" / "sermon-english-source-machine-judge-v1.schema.json"
        ).read_text())
        self.assertEqual(list(Draft202012Validator(
            schema, format_checker=FormatChecker(),
        ).iter_errors(receipt)), [])

        package = layer1.build_package(
            self.aligned_path,
            self.manifest_path,
            machine_judge_path=receipt_path,
            source_id="machine-judge-fixture",
        )
        self.assertEqual(package["status"], "candidate_ready_for_translation")
        self.assertTrue(package["candidateTranslationEligible"])
        self.assertFalse(package["translationEligible"])
        self.assertFalse(package["review"]["humanApproval"])
        self.assertIsNotNone(package["evidence"]["machineJudge"])

    def test_high_risk_or_failed_sentence_does_not_pass_gate(self):
        def failing_caller(_api_key, payload):
            response = self.fake_caller(_api_key, payload)
            result = json.loads(response["choices"][0]["message"]["content"])
            row = result["sentences"][0]
            row["verdict"] = "fail"
            row["risk"] = "high"
            row["checks"]["meaningPreserved"] = "fail"
            row["unresolvedIssues"] = ["The boundary may obscure the causal clause."]
            response["id"] = "judge-response-fail"
            response["choices"][0]["message"]["content"] = json.dumps(result)
            return response

        receipt = subject.run(
            aligned_path=self.aligned_path,
            manifest_path=self.manifest_path,
            out=self.root / "failed" / "receipt.json",
            api_key="fixture-key",
            caller=failing_caller,
        )
        self.assertEqual(receipt["status"], "rejected_for_layer2_shadow")
        self.assertFalse(receipt["layer2DevelopmentEligible"])
        self.assertTrue(receipt["unresolvedIssues"])

    def test_changed_anchor_cannot_reuse_machine_judge_receipt(self):
        receipt_path = self.root / "judge" / "receipt.json"
        subject.run(
            aligned_path=self.aligned_path,
            manifest_path=self.manifest_path,
            out=receipt_path,
            api_key="fixture-key",
            caller=self.fake_caller,
        )
        changed = json.loads(self.manifest_path.read_text())
        changed["policy"]["internalPauseSeconds"] = 0.4
        changed_path = self.root / "changed-anchor.json"
        write_json(changed_path, changed)
        with self.assertRaisesRegex(ValueError, "different anchor manifest"):
            layer1.build_package(
                self.aligned_path,
                changed_path,
                machine_judge_path=receipt_path,
            )

    def test_existing_receipt_cannot_be_reused_for_changed_judge_configuration(self):
        receipt_path = self.root / "judge" / "receipt.json"
        subject.run(
            aligned_path=self.aligned_path,
            manifest_path=self.manifest_path,
            out=receipt_path,
            api_key="fixture-key",
            caller=self.fake_caller,
        )
        with self.assertRaisesRegex(ValueError, "changed judge configuration"):
            subject.run(
                aligned_path=self.aligned_path,
                manifest_path=self.manifest_path,
                out=receipt_path,
                model="gpt-5.5",
                api_key="fixture-key",
                caller=self.fake_caller,
            )

    def test_tampered_pass_receipt_is_rejected_by_package_builder(self):
        receipt_path = self.root / "judge" / "receipt.json"
        receipt = subject.run(
            aligned_path=self.aligned_path,
            manifest_path=self.manifest_path,
            out=receipt_path,
            api_key="fixture-key",
            caller=self.fake_caller,
        )
        receipt["sentences"][0]["checks"] = {}
        tampered_path = self.root / "tampered.json"
        write_json(tampered_path, receipt)
        with self.assertRaisesRegex(ValueError, "internally inconsistent"):
            layer1.build_package(
                self.aligned_path,
                self.manifest_path,
                machine_judge_path=tampered_path,
            )


if __name__ == "__main__":
    unittest.main()
