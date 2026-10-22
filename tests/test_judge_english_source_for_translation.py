import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator, FormatChecker

from tongxing_production.source import english_source_package as layer1
from tongxing_production.source import english_source_judge as subject
from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.source import sentence_interpretation as anchors


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

    def test_standalone_real_caller_binds_durable_directory_without_accounting_env(self):
        import os
        from unittest.mock import patch
        with patch.dict(os.environ,{},clear=True), patch.object(subject,'chat_json',side_effect=self.fake_caller) as call:
            result=subject.run(aligned_path=self.aligned_path,manifest_path=self.manifest_path,
                out=self.root/'review.json',cache_root=self.root/'cache',api_key='test-only')
        self.assertEqual(result['status'],'approved_for_layer2_shadow')
        self.assertEqual(call.call_count,1)
        rows=list((self.root/'cache'/'api-cli-outcomes').glob('*/outcome.json'))
        self.assertEqual(len(rows),1)
        self.assertEqual(json.loads(rows[0].read_text())['status'],'returned')

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
            "model": payload["model"],
            "choices": [{
                "finish_reason": "stop",
                "message": {"content": json.dumps({
                    "schemaVersion": subject.BATCH_SCHEMA,
                    "sentences": rows,
                })},
            }],
        }

    def test_oversized_judge_batch_is_split_until_each_request_fits_the_cap(self):
        # Two sentences, forced into one batch, with the payload builder refusing
        # anything larger than one sentence: the judge must split, not fail.
        words = ["Your", "sin", "faced", "death."]
        second = ["He", "rose", "on", "day", "three."]
        segments = []
        cursor = 0.0
        for index, text in enumerate((" ".join(words), " ".join(second))):
            timed = []
            for word in text.split():
                timed.append({"text": word, "start": cursor, "end": cursor + 0.4})
                cursor += 0.5
            segments.append({"id": index, "referenceChunkId": "block-00", "text": text,
                             "start": timed[0]["start"], "end": timed[-1]["end"],
                             "sentenceBoundarySource": "frozen_reference_punctuation",
                             "wordTimes": timed})
        aligned_path = self.root / "split-segments.json"
        write_json(aligned_path, segments)
        manifest = anchors.build_anchor_manifest(
            segments, source_path=aligned_path, unit_policy=anchors.UNIT_POLICY_V2,
            max_unit_seconds=4.0)
        manifest_path = self.root / "split-manifest.json"
        write_json(manifest_path, manifest)

        original_payload = subject._payload
        calls = []
        def payload_or_refuse(batch, **kwargs):
            calls.append(len(batch))
            if len(batch) > 1:
                raise ValueError("source_judge_input_bound_exceeded")
            return original_payload(batch, **kwargs)
        def one_batch(sentences, _size):
            return [sentences]
        with patch.object(subject, "_payload", side_effect=payload_or_refuse), \
                patch.object(subject, "_batches", side_effect=one_batch):
            result = subject.run(aligned_path=aligned_path, manifest_path=manifest_path,
                                 out=self.root / "split-judge.json",
                                 cache_root=self.root / "split-cache", api_key="",
                                 caller=self.fake_caller)
        self.assertEqual(calls[0], 2)
        self.assertEqual(sorted(calls[1:]), [1, 1])
        self.assertEqual(len(result["sentences"]), 2)

    def test_shared_cache_root_replays_unchanged_batches_after_a_boundary_rebuild(self):
        # Three one-sentence batches; the rebuild adds a boundary in the middle sentence. The
        # first batch replays from the shared cache. Under clause_stable_v2 the last is paid again
        # only because unit IDs were numbered in chunk order, so the extra unit renumbered every
        # later unit in the chunk; under clause_stable_v3 a unit is numbered by its first word and
        # the last batch replays too.
        self.unit_policy = getattr(self, "unit_policy", anchors.UNIT_POLICY_V2)
        def segments_for(middle_words):
            out, cursor = [], 0.0
            for index, text in enumerate(("Your sin faced death.", middle_words, "He rose on day three.")):
                timed = []
                for word in text.split():
                    timed.append({"text": word, "start": cursor, "end": cursor + 0.4})
                    cursor += 0.5
                out.append({"id": index, "referenceChunkId": "block-00", "text": text,
                            "start": timed[0]["start"], "end": timed[-1]["end"],
                            "sentenceBoundarySource": "frozen_reference_punctuation", "wordTimes": timed})
            return out
        calls = []
        def caller(key, payload):
            calls.append([row["sourceSentenceId"] for row in json.loads(payload["messages"][1]["content"])["sentences"]])
            return self.fake_caller(key, payload)
        shared = self.root / "shared-cache"
        results = []
        for label, overrides in (("first", None), ("second", {"block-00-s002": ["block-00-w0008", "block-00-w0012"]})):
            aligned_path = self.root / f"{label}-segments.json"
            segments = segments_for("He spoke so slowly, and then he left, but the end was near today.")
            write_json(aligned_path, segments)
            manifest = anchors.build_anchor_manifest(
                segments, source_path=aligned_path, unit_policy=self.unit_policy,
                max_unit_seconds=4.0, boundary_overrides=overrides)
            manifest_path = self.root / f"{label}-manifest.json"
            write_json(manifest_path, manifest)
            results.append(subject.run(aligned_path=aligned_path, manifest_path=manifest_path,
                                       out=self.root / label / "judge.json", cache_root=shared,
                                       api_key="", caller=caller, batch_size=1))
        first_units = [row["sourceUnitIds"] for row in results[0]["sentences"]]
        second_units = [row["sourceUnitIds"] for row in results[1]["sentences"]]
        self.assertNotEqual(first_units[1], second_units[1])
        self.assertEqual(calls[:3], [["block-00-s001"], ["block-00-s002"], ["block-00-s003"]])
        expected = ([["block-00-s002"], ["block-00-s003"]] if self.unit_policy == anchors.UNIT_POLICY_V2
                    else [["block-00-s002"]])
        self.assertEqual(calls[3:], expected)
        receipts = [path for path in shared.glob("cache/english-source-judge-*.json")
                    if not path.name.endswith(".started.json")]
        self.assertEqual(len(receipts), 3 + len(expected))

    def test_shared_cache_root_with_v3_numbering_replays_every_untouched_sentence(self):
        self.unit_policy = anchors.UNIT_POLICY_V3
        self.test_shared_cache_root_replays_unchanged_batches_after_a_boundary_rebuild()

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

    def test_deterministic_rebuild_accepts_stable_ids_from_a_cropped_source(self):
        manifest = anchors.build_anchor_manifest(
            self.segments, source_path=self.aligned_path, unit_policy=anchors.UNIT_POLICY_V2,
            max_unit_seconds=4.0,
            identity_offsets={"block-00": {"sentence": 11, "word": 209, "unit": 14}},
        )
        result = subject.deterministic_review(self.aligned_path, manifest)
        check = next(row for row in result["checks"] if row["checkId"] == "manifestDeterministicRebuild")
        self.assertEqual(check["status"], "pass")

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
