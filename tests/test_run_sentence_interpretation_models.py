import json
from pathlib import Path
import tempfile
import unittest

from scripts import run_sentence_interpretation_models as runner
from scripts import sermon_sentence_interpretation as contract


class SentenceInterpretationModelRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        segments = self.root / "segments.json"
        raw = [{
            "id": 0,
            "referenceChunkId": "block-00",
            "text": "Do not be afraid.",
            "start": 0.0,
            "end": 1.9,
            "sentenceBoundarySource": "frozen_reference_punctuation",
            "wordTimes": [
                {"text": "Do", "start": 0.0, "end": 0.3},
                {"text": "not", "start": 0.4, "end": 0.7},
                {"text": "be", "start": 0.8, "end": 1.1},
                {"text": "afraid.", "start": 1.2, "end": 1.9},
            ],
        }]
        segments.write_text(json.dumps(raw), encoding="utf-8")
        self.manifest = contract.build_anchor_manifest(raw, source_path=segments)
        self.manifest_path = self.root / "anchor.json"
        contract.write_json(self.manifest_path, self.manifest)
        self.calls = []

    def fake_call(self, api_key, payload):
        self.calls.append((api_key, payload))
        user = json.loads(payload["messages"][1]["content"])
        if "draftSha256" not in user:
            groups = []
            for request in user["requests"]:
                groups.append({
                    "translationGroupId": request["translationGroupId"],
                    "sourceUnitIds": request["sourceUnitIds"],
                    "chineseUtterances": ["不要害怕。"],
                    "chinese": "不要害怕。",
                    "coverage": [{"sourceUnitId": request["sourceUnitIds"][0], "targetText": "不要害怕。"}],
                })
            result = {"schemaVersion": contract.DRAFT_SCHEMA, "groups": groups, "issues": []}
        else:
            groups = []
            for source in user["groups"]:
                source_id = source["sourceUnitIds"][0]
                groups.append({
                    "translationGroupId": source["translationGroupId"],
                    "sourceUnitIds": source["sourceUnitIds"],
                    "chineseUtterances": ["不要害怕。"],
                    "chinese": "不要害怕。",
                    "coverage": [{"sourceUnitId": source_id, "targetText": "不要害怕。"}],
                    "review": {
                        "status": "pass",
                        "sourceUnits": [{
                            "sourceUnitId": source_id,
                            "checks": {name: "pass" for name in contract.CHECKS},
                            "evidence": "否定和完整含义均保留。",
                            "uncertainty": [],
                            "issues": [],
                        }],
                    },
                })
            result = {"schemaVersion": contract.REVIEW_SCHEMA, "groups": groups, "issues": []}
        return {
            "id": f"request-{len(self.calls)}",
            "model": "gpt-6-astra",
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result, ensure_ascii=False)}}],
        }

    def test_run_caches_separate_translation_and_review_and_never_writes_key(self):
        out = self.root / "out"
        result = runner.run(
            manifest_path=self.manifest_path,
            out=out,
            model="gpt-6-astra",
            effort="medium",
            batch_size=1,
            workers=1,
            api_key="test-secret-key",
            caller=self.fake_call,
        )
        self.assertEqual(result["status"], "model_review_pass_tts_and_human_review_pending")
        self.assertEqual(result["counts"]["machineSemanticReviewPass"], 1)
        self.assertEqual(len(self.calls), 2)
        self.assertNotIn("test-secret-key", "\n".join(
            path.read_text(encoding="utf-8") for path in out.rglob("*.json")
        ))

        def no_call(*_args, **_kwargs):
            raise AssertionError("cache should avoid a second model request")

        cached = runner.run(
            manifest_path=self.manifest_path,
            out=out,
            model="gpt-6-astra",
            effort="medium",
            batch_size=1,
            workers=1,
            api_key="different-secret",
            caller=no_call,
        )
        self.assertEqual(cached["independentReviewSha256"], result["independentReviewSha256"])

    def test_bad_review_fails_closed(self):
        def bad_call(api_key, payload):
            response = self.fake_call(api_key, payload)
            user = json.loads(payload["messages"][1]["content"])
            if "draftSha256" in user:
                parsed = json.loads(response["choices"][0]["message"]["content"])
                parsed["groups"][0]["review"]["sourceUnits"][0]["checks"]["completeMeaning"] = "fail"
                response["choices"][0]["message"]["content"] = json.dumps(parsed, ensure_ascii=False)
            return response

        result = runner.run(
            manifest_path=self.manifest_path,
            out=self.root / "bad",
            model="gpt-6-astra",
            effort="medium",
            batch_size=1,
            workers=1,
            api_key="test-secret-key",
            caller=bad_call,
        )
        self.assertEqual(result["status"], "model_review_requires_resolution")
        self.assertEqual(result["counts"]["machineSemanticReviewNeedsResolution"], 1)


if __name__ == "__main__":
    unittest.main()
