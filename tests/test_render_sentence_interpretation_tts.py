import copy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from scripts import render_sentence_interpretation_tts as subject
from scripts import sermon_sentence_interpretation as interpretation


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


class SentenceInterpretationTtsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.anchor_path = self.root / "anchor.json"
        words = [{"wordId": "block-00-w0001", "text": "Hello.", "start": 0.0, "end": 0.8}]
        self.anchor = {
            "schemaVersion": interpretation.ANCHOR_SCHEMA,
            "issues": [],
            "policy": {
                "interUtteranceGapSeconds": 0.12,
                "reactionLagSeconds": 0.25,
                "maxEndLagSeconds": 8.0,
                "interpretationSchedule": "rolling_interpreter_v1",
            },
            "sourceUnits": [{
                "sourceUnitId": "block-00-u001", "sourceSentenceId": "block-00-s001",
                "referenceChunkId": "block-00", "english": "Hello.", "sourceWordIds": ["block-00-w0001"],
                "words": words, "start": 0.0, "end": 0.8,
                "boundary": {"pauseAfterSeconds": 0.2}, "requiresOperatorReview": True,
            }],
        }
        write_json(self.anchor_path, self.anchor)
        response = [{"responseId": "translate-1"}]
        self.semantic = {
            "schemaVersion": "sermon-sentence-semantic-candidate-v1",
            "status": "model_review_pass_tts_and_human_review_pending",
            "anchorManifestSha256": interpretation.json_sha256(self.anchor),
            "translator": {"model": "model", "promptVersion": interpretation.PROMPT_VERSION,
                           "batchReceipts": response},
            "reviewer": {"model": "model", "promptVersion": interpretation.REVIEW_PROMPT_VERSION,
                         "batchReceipts": [{"responseId": "review-1"}]},
            "groups": [{
                "translationGroupId": "translation-block-00-u001",
                "sourceUnitIds": ["block-00-u001"], "chineseUtterances": ["你好。"], "chinese": "你好。",
                "coverage": [{"sourceUnitId": "block-00-u001", "targetText": "你好。"}],
                "review": {"status": "pass", "sourceUnits": [{
                    "sourceUnitId": "block-00-u001",
                    "checks": {name: "pass" for name in interpretation.CHECKS},
                    "evidence": "完整对应。", "uncertainty": [], "issues": [],
                }]},
            }],
        }
        self.semantic_path = self.root / "semantic.json"
        write_json(self.semantic_path, self.semantic)
        self.checkpoint = self.root / "checkpoint"
        self.checkpoint.mkdir()
        (self.checkpoint / "model.safetensors").write_bytes(b"checkpoint")
        write_json(self.checkpoint / "config.json", {"talker_config": {"spk_id": {"eric_pilot": 1}}})

    def test_prepare_freezes_exact_reviewed_chinese_at_natural_rate(self):
        out = self.root / "job"
        job = subject.prepare_job(self.anchor_path, self.semantic_path, self.checkpoint, out)
        self.assertEqual(job["purposeSchemaVersion"], subject.JOB_SCHEMA)
        self.assertEqual(job["units"][0]["text"], "你好。")
        self.assertNotIn("spokenText", job["units"][0])
        self.assertEqual(job["renderContract"]["playbackRate"], 1.0)
        self.assertEqual(job["renderContract"]["ratePolicy"], interpretation.RATE_POLICY)
        with self.assertRaisesRegex(ValueError, "new TTS job directory"):
            subject.prepare_job(self.anchor_path, self.semantic_path, self.checkpoint, out)

    def test_prepare_rejects_semantic_text_that_skips_source_unit(self):
        changed = copy.deepcopy(self.semantic)
        changed["groups"][0]["sourceUnitIds"] = []
        write_json(self.semantic_path, changed)
        with self.assertRaisesRegex(ValueError, "every source unit"):
            subject.prepare_job(self.anchor_path, self.semantic_path, self.checkpoint, self.root / "job")

    def test_prepare_accepts_supported_v2_anchor(self):
        self.anchor["schemaVersion"] = interpretation.ANCHOR_SCHEMA_V2
        self.anchor["policy"]["unitPolicy"] = interpretation.UNIT_POLICY_V2
        self.anchor["sourceUnits"][0]["boundary"]["splitEvidence"] = {
            "kind": "source_sentence_end", "afterWordId": "block-00-w0001",
            "pauseSeconds": 0.2, "punctuation": None, "withinTargetSeconds": True,
        }
        self.semantic["anchorManifestSha256"] = interpretation.json_sha256(self.anchor)
        write_json(self.anchor_path, self.anchor)
        write_json(self.semantic_path, self.semantic)
        job = subject.prepare_job(
            self.anchor_path, self.semantic_path, self.checkpoint, self.root / "v2-job",
        )
        self.assertEqual(job["units"][0]["sourceUnitIds"], ["block-00-u001"])

    def test_finalize_binds_decoded_audio_and_reports_timing(self):
        job_dir = self.root / "job"
        job = subject.prepare_job(self.anchor_path, self.semantic_path, self.checkpoint, job_dir)
        job_path = job_dir / "job.json"
        render = self.root / "render"
        render.mkdir()
        identity = {"jobSha256": subject.sha256(job_path), "checkpointSha256": "checkpoint"}
        write_json(render / "identity.json", identity)
        wav = render / "unit-0000.wav"
        wav.write_bytes(b"fake-wave")
        renderer_receipt = {
            "unit": job["units"][0], "identity": identity,
            "sha256": subject.sha256(wav), "durationSeconds": 0.7,
        }
        write_json(wav.with_suffix(".json"), renderer_receipt)
        combined = render / "chinese.raw.wav"
        combined.write_bytes(b"fake-combined")
        write_json(render / "report.json", {
            "jobSha256": identity["jobSha256"], "status": "complete_candidate_render",
            "sha256": subject.sha256(combined),
        })

        def runner(argv, **kwargs):
            if argv[0] == "ffprobe":
                return SimpleNamespace(stdout=json.dumps({
                    "format": {"duration": "0.7"},
                    "streams": [{"codec_type": "audio", "codec_name": "pcm_s24le",
                                 "sample_rate": "24000", "channels": 1}],
                }))
            return SimpleNamespace(stdout="")

        candidate, report, metrics = subject.finalize(
            self.anchor_path, self.semantic_path, job_path, render, self.root / "final",
            process_runner=runner,
        )
        self.assertEqual(candidate["groups"][0]["audio"]["text"], "你好。")
        self.assertEqual(candidate["groups"][0]["audio"]["playbackRate"], 1.0)
        self.assertTrue(report["candidateReadyForHumanReview"])
        self.assertEqual(metrics["counts"]["fullyDecodedAudioFiles"], 1)
        self.assertEqual(metrics["audio"]["ratePolicy"], interpretation.RATE_POLICY)


if __name__ == "__main__":
    unittest.main()
