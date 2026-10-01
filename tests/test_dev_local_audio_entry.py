"""Dev CLI selection reaches real batching and immutable receipts; no model runtime."""
import contextlib
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from scripts import dev_audio_test_profile as profiles
from scripts import dev_audio_test_receipts as receipts
from scripts import render_formal_target_language_speech as tts
from scripts import screen_target_language_audio_units as asr
from scripts import run_dev_local_audio_test as entry
from tests import test_formal_audio_batching as fixtures


class TtsDevEntryTests(unittest.TestCase):
    setUp = fixtures.FormalTTSBatchTests.setUp
    setup_units = fixtures.FormalTTSBatchTests.setup_units

    def argv(self):
        args = []
        for name in ("source", "anchor", "candidate", "job", "adapter", "policy"):
            args += ["--" + name, str(self.paths[name])]
        for name in ("human-review-receipt", "speaker-registry", "clip-voice-authorization",
                     "clip-timeline-map", "checkpoint-map", "audio-operation-policies"):
            args += ["--" + name, str(self.root / (name + ".json"))]
        return args

    def render(self, paths, checkpoint, policies, **options):
        rows = tts.render_units(self.context, self.paths, self.root, checkpoint,
            batch_size=options["batch_size"], synth_factory=(fixtures.BatchEngine
                if options["batch_size"] != 1 else fixtures.render_fixtures.FakeSynth))
        manifest = {"targetLocale": "ko", "units": rows, "voice": {"model": "fixture"}}
        (self.paths["job"].parent / "render-manifest.json").write_text(json.dumps(manifest))
        return manifest

    def test_dev_entry_default_two_reaches_real_batches_and_receipt(self):
        self.setup_units()
        with patch.object(tts, "render_accounted", side_effect=self.render), contextlib.redirect_stdout(io.StringIO()):
            entry.main(["tts", *self.argv()])
        self.assertEqual([row[0] for row in fixtures.BatchEngine.calls], [[0, 1], [2, 3], [4]])
        path = self.paths["job"].parent / "dev-test-tts-b2.json"
        value = json.loads(path.read_text())
        self.assertEqual(value["batchSize"], 2)
        self.assertEqual(value["profile"]["sha256"], receipts.sha(profiles.DEFAULT_PROFILE))
        self.assertEqual(len(value["unitIntentWitnesses"]), 5)
        self.assertFalse(value["humanApproval"])
        self.assertFalse(value["freshModelInferenceClaimed"])

    def test_plain_production_cli_still_passes_one_without_dev_receipt(self):
        with patch.object(tts, "render_accounted", return_value={"targetLocale": "ko"}) as render:
            with contextlib.redirect_stdout(io.StringIO()):
                tts.main(self.argv())
        self.assertEqual(render.call_args.kwargs["batch_size"], 1)
        self.assertEqual(list(self.paths["job"].parent.glob("dev-test-tts-*.json")), [])

    def test_repeated_dev_selection_reuses_audio_and_preserves_consumption_bytes(self):
        self.setup_units()
        with patch.object(tts, "render_accounted", side_effect=self.render), contextlib.redirect_stdout(io.StringIO()):
            entry.main(["tts", *self.argv()])
            proof = self.paths["job"].parent / "dev-test-tts-b2.json"
            before = proof.read_bytes()
            fixtures.BatchEngine.calls.clear()
            entry.main(["tts", *self.argv()])
        self.assertEqual(fixtures.BatchEngine.calls, [])
        self.assertEqual(proof.read_bytes(), before)

    def test_explicit_baseline_one_overrides_dev_default(self):
        self.setup_units()
        with patch.object(tts, "render_accounted", side_effect=self.render), contextlib.redirect_stdout(io.StringIO()):
            entry.main(["tts", *self.argv(), "--batch-size", "1"])
        value = json.loads((self.paths["job"].parent / "dev-test-tts-b1.json").read_text())
        self.assertEqual(value["batchSize"], 1)
        self.assertTrue(value["profile"]["explicitBatchSize"])

    def test_bad_profile_never_enters_renderer(self):
        bad = self.root / "bad-profile.json"; bad.write_text("{}")
        with patch.object(tts, "render_accounted") as render:
            with self.assertRaises(ValueError):
                entry.main(["tts", *self.argv(), "--dev-test-profile", str(bad)])
        render.assert_not_called()

    def test_changed_consumption_destination_rejects_before_renderer(self):
        settings = profiles.resolve("tts", enabled=True)
        path = self.paths["job"].parent / "dev-test-tts-b2.json"
        path.write_text(json.dumps({"profile": {**settings["profile"], "sha256": "changed"}, "batchSize": 2}))
        with patch.object(tts, "render_accounted") as render:
            with self.assertRaisesRegex(ValueError, "different profile"):
                entry.main(["tts", *self.argv()])
        render.assert_not_called()

    def test_consumption_receipt_rejects_wrong_unit_batch_and_profile_drift(self):
        self.setup_units()
        self.render(self.paths, self.root / "checkpoint-map.json", None, batch_size=2)
        settings = profiles.resolve("tts", enabled=True)
        artifact = self.paths["job"].parent / "render-manifest.json"
        intent_path = artifact.parent / "receipts/unit-0004.intent.json"
        value = json.loads(intent_path.read_text()); value["batchSize"] = 1
        intent_path.write_text(json.dumps(value))
        output = self.root / "bad-consumption.json"
        with self.assertRaisesRegex(ValueError, "unit intent"):
            receipts.write(settings, artifact, output)
        self.assertFalse(output.exists())
        custom = self.root / "profile.json"; custom.write_bytes(profiles.DEFAULT_PROFILE.read_bytes())
        settings = profiles.resolve("tts", enabled=True, profile_path=custom)
        custom.write_bytes(custom.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "changed during"):
            receipts.write(settings, artifact, output)
        self.assertFalse(output.exists())


class AsrDevEntryTests(unittest.TestCase):
    setUp = fixtures.FormalASRBatchTests.setUp
    setup_units = fixtures.FormalASRBatchTests.setup_units

    def prepare(self):
        self.setup_units()
        job, manifest = self.root / "job.json", self.root / "manifest.json"
        job.write_text(json.dumps(self.job)); manifest.write_text(json.dumps(self.manifest))
        weights = self.root / "model/model.safetensors"
        weights.parent.mkdir(); weights.write_bytes(b"fixture-weights")
        self.model_type, self.engine = MagicMock(), MagicMock()
        self.model_type.from_pretrained.return_value = self.engine
        self.engine.transcribe.side_effect = lambda **kw: [SimpleNamespace(text=self.job["units"][0]["text"])
            for _ in range(1 if isinstance(kw["audio"], tuple) else len(kw["audio"]))]
        self.modules = {"torch": SimpleNamespace(bfloat16="fixture-bf16"),
            "soundfile": SimpleNamespace(read=lambda *a, **kw: ([.02], 16000)),
            "qwen_asr": SimpleNamespace(Qwen3ASRModel=self.model_type)}
        self.args = ["--job", str(job), "--render-manifest", str(manifest),
            "--artifact-root", str(self.root), "--model-path", str(weights.parent),
            "--model-revision", "model.safetensors:sha256:" + asr.file_sha(weights)]

    def run_arm(self, name, *extra, dev=True):
        args = [*self.args, "--out-receipt", str(self.root / (name + ".json")),
                "--out-manifest", str(self.root / (name + "-screened.json")),
                "--unit-cache", str(self.root / (name + "-cache")), *extra]
        with patch.dict(sys.modules, self.modules), contextlib.redirect_stdout(io.StringIO()):
            if dev:
                entry.main(["back-asr", *args])
            else:
                asr.main(args)

    def test_dev_default_four_reaches_resident_model_short_tail_and_proof(self):
        self.prepare(); self.run_arm("b4")
        self.model_type.from_pretrained.assert_called_once()
        self.assertEqual(self.model_type.from_pretrained.call_args.kwargs["max_inference_batch_size"], 4)
        self.assertEqual([len(c.kwargs["audio"]) for c in self.engine.transcribe.call_args_list], [4, 1])
        proof = json.loads((self.root / "b4.dev-test.json").read_text())
        self.assertEqual(proof["batchSize"], 4)
        self.assertEqual(proof["producerArtifact"]["sha256"], asr.file_sha(self.root / "b4.json"))
        self.assertEqual(asr.load(self.root / "b4.json")["humanListeningStatus"], "pending")

    def test_explicit_eight_uses_same_wavs_and_preserves_previous_arm(self):
        self.prepare(); self.run_arm("b4")
        old = (self.root / "b4.json").read_bytes()
        self.engine.transcribe.reset_mock(); self.run_arm("b8", "--batch-size", "8")
        self.assertEqual([len(c.kwargs["audio"]) for c in self.engine.transcribe.call_args_list], [5])
        self.assertEqual(asr.load(self.root / "b8.json")["unitAudioSha256s"], asr.load(self.root / "b4.json")["unitAudioSha256s"])
        self.assertEqual((self.root / "b4.json").read_bytes(), old)
        self.assertTrue(asr.load(self.root / "b8.dev-test.json")["profile"]["explicitBatchSize"])

    def test_plain_production_remains_one_and_has_no_proof(self):
        self.prepare(); self.run_arm("prod", dev=False)
        self.assertEqual(self.model_type.from_pretrained.call_args.kwargs["max_inference_batch_size"], 1)
        self.assertEqual(len(self.engine.transcribe.call_args_list), 5)
        self.assertFalse((self.root / "prod.dev-test.json").exists())

    def test_passing_comparison_preserves_existing_flagged_arm(self):
        self.prepare()
        self.engine.transcribe.side_effect = lambda **kw: [SimpleNamespace(text="") for _ in kw["audio"]]
        self.run_arm("flagged")
        old = (self.root / "flagged.json").read_bytes()
        self.assertEqual(asr.load(self.root / "flagged.json")["status"], "requires_review")
        self.engine.transcribe.side_effect = lambda **kw: [SimpleNamespace(text=self.job["units"][0]["text"]) for _ in kw["audio"]]
        self.run_arm("passing", "--batch-size", "8")
        self.assertEqual(asr.load(self.root / "passing.json")["status"], "pass")
        self.assertEqual((self.root / "flagged.json").read_bytes(), old)
        self.assertEqual(asr.load(self.root / "passing.json")["humanListeningStatus"], "pending")

    def test_bad_profile_and_wrong_weights_never_load_model(self):
        self.prepare()
        bad = self.root / "bad-profile.json"; bad.write_text("{}")
        with self.assertRaises(ValueError):
            self.run_arm("bad", "--dev-test-profile", str(bad))
        with self.assertRaisesRegex(ValueError, "deployed weights"):
            self.run_arm("wrong", "--model-revision", "model.safetensors:sha256:wrong")
        self.model_type.from_pretrained.assert_not_called()

    def test_failure_has_no_verified_consumption_receipt_and_no_retry(self):
        self.prepare(); self.engine.transcribe.side_effect = RuntimeError("fixture failure")
        with self.assertRaisesRegex(RuntimeError, "fixture failure"):
            self.run_arm("failed")
        self.assertEqual(self.engine.transcribe.call_count, 1)
        self.assertFalse((self.root / "failed.dev-test.json").exists())


if __name__ == "__main__":
    unittest.main()
