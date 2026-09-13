"""Repair admission uses fake media and models; no GPU or model imports."""
import builtins
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from render_weekly_audio import render_identity
from run_qwen_training_smoke import sha256
import retry_weekly_unit as retry


class ModelBoundaryReached(RuntimeError):
    pass


class RetryIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.out = self.root / "render"
        self.out.mkdir()
        self.checkpoint = self.root / "checkpoint"
        self.checkpoint.mkdir()
        (self.checkpoint / "model.safetensors").write_bytes(b"fake checkpoint")
        self.checkpoint_hash = sha256(self.checkpoint / "model.safetensors")
        self.job = self.root / "job.json"
        self.job.write_text(json.dumps({"units": [{"text": "fixture text"}],
            "voice": {"speakerKey": "fixture", "checkpointSha256": self.checkpoint_hash}}))
        (self.out / "unit-0000.wav").write_bytes(b"preserved original failed WAV")
        (self.out / "failure.json").write_text(json.dumps({"unit": 0, "reason": "duration_or_signal"}))
        self.identity = render_identity(self.job, self.checkpoint_hash)
        self.model = Mock(side_effect=ModelBoundaryReached("mock model boundary; no real initialization"))
        self.modules = {
            "numpy": SimpleNamespace(), "soundfile": SimpleNamespace(),
            "torch": SimpleNamespace(bfloat16="fake"),
            "qwen_tts": SimpleNamespace(Qwen3TTSModel=SimpleNamespace(from_pretrained=self.model)),
        }

    def invoke(self, identity):
        (self.out / "identity.json").write_text(json.dumps(identity))
        argv = ["retry_weekly_unit.py", "--job", str(self.job), "--checkpoint", str(self.checkpoint),
            "--out", str(self.out), "--unit", "0"]
        original_import = builtins.__import__
        self.model_imports = []
        def track_import(name, *args, **kwargs):
            if name in self.modules:
                self.model_imports.append(name)
            return original_import(name, *args, **kwargs)
        with patch.object(sys, "argv", argv), patch.dict(sys.modules, self.modules), patch.object(builtins, "__import__", side_effect=track_import):
            retry.main()

    def assert_rejected_unchanged(self, identity):
        (self.out / "identity.json").write_text(json.dumps(identity))
        before = {str(p.relative_to(self.out)): p.read_bytes() for p in self.out.rglob("*") if p.is_file()}
        with self.assertRaises(ValueError):
            self.invoke(identity)
        after = {str(p.relative_to(self.out)): p.read_bytes() for p in self.out.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertFalse((self.out / "diagnostics").exists())
        self.assertEqual(self.model_imports, [])
        self.model.assert_not_called()

    def test_stale_renderer_never_initializes_model_or_changes_output(self):
        self.assert_rejected_unchanged({**self.identity, "rendererSha256": "old-renderer"})

    def test_changed_job_checkpoint_or_sampling_never_initializes_model(self):
        for key, value in (("jobSha256", "old-job"), ("checkpointSha256", "old-checkpoint"),
                           ("seed", 99), ("temperature", .2), ("seedPolicy", "changed"),
                           ("repetitionPenalty", 1.5), ("maxNewTokens", 32)):
            with self.subTest(field=key):
                self.assert_rejected_unchanged({**self.identity, key: value})

    def test_unsupported_or_boolean_batch_size_is_rejected(self):
        for size in (0, 3, 8, True, "4", None):
            with self.subTest(batch_size=size):
                self.assert_rejected_unchanged({**self.identity, "batchSize": size})

    def test_all_supported_original_batch_sizes_reach_only_fake_model(self):
        for size in (1, 2, 4):
            with self.subTest(batch_size=size), self.assertRaises(ModelBoundaryReached):
                self.invoke(render_identity(self.job, self.checkpoint_hash, size))
        self.assertEqual(self.model.call_count, 3)
        self.assertEqual((self.out / "unit-0000.wav").read_bytes(), b"preserved original failed WAV")
        self.assertFalse((self.out / "unit-0000.json").exists())

    def test_actual_checkpoint_must_also_match_frozen_job(self):
        job = json.loads(self.job.read_text())
        job["voice"]["checkpointSha256"] = "different-frozen-checkpoint"
        self.job.write_text(json.dumps(job))
        self.assert_rejected_unchanged(render_identity(self.job, self.checkpoint_hash))


if __name__ == "__main__":
    unittest.main()
