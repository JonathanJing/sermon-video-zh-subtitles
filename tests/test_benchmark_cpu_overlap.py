"""Offline checks of the real renderer adapter; no model or speed claims."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts.experiments import benchmark_cpu_overlap as subject

sys.path.insert(0, str(subject.LEGACY))
import test_cpu_render_pipeline as renderer_fixtures  # noqa: E402


class BenchmarkCpuOverlapTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.fixture = renderer_fixtures.RendererPipelineTests()
        self.job, self.checkpoint, _ = self.fixture.fixture(self.root, 8)
        self.manifest = self.root / "manifest.json"
        subject.save(self.manifest, {"schemaVersion": subject.SCHEMA, "experimentOnly": True,
            "job": "job.json", "jobSha256": subject.digest(self.job),
            "voice": subject.read(self.job)["voice"],
            "adapter": {"configSha256": "a" * 64},
            "checkpointConfigSha256": subject.digest(self.checkpoint / "config.json"),
            "producerFiles": {name: subject.digest(subject.LEGACY / name) for name in subject.FILES}})
        self.out = self.root / "matrix"
        self.calls = []

    def renderer_process(self, argv, **options):
        self.calls.append(argv)
        workers = int(argv[argv.index("--cpu-workers") + 1])
        self.assertEqual(argv[1], str(subject.LEGACY / "render_weekly_audio.py"))
        self.assertEqual(argv[argv.index("--batch-size") + 1], "4")
        self.assertEqual(argv[argv.index("--cpu-queue-batches") + 1], "2")
        # Invoke the actual entry, with only numpy/model IO replaced by the
        # existing finite PCM fixture. It is not a runtime benchmark.
        from test_cpu_render_pipeline import NP, SF
        from types import SimpleNamespace
        import render_weekly_audio as renderer
        model = self.fixture.model()
        modules = {"numpy": NP, "soundfile": SF,
            "torch": SimpleNamespace(bfloat16="bf16", float32="fp32", manual_seed=lambda _: None),
            "qwen_tts": SimpleNamespace(Qwen3TTSModel=SimpleNamespace(from_pretrained=lambda *_, **__: model))}
        with patch("sys.argv", argv[1:]), patch.dict("sys.modules", modules), contextlib.redirect_stdout(io.StringIO()):
            renderer.main()
        return subprocess.CompletedProcess(argv, 0)

    def test_three_fresh_real_entry_runs_and_measured_pcm_cues(self):
        with patch.object(subject.subprocess, "run", self.renderer_process):
            result = subject.run(self.manifest, self.checkpoint,
                subject.LEGACY / "render_weekly_audio.py", Path(sys.executable), "cuda:0", self.out)
        self.assertEqual(len(self.calls), 3)
        self.assertEqual([row["cpuWorkers"] for row in result["runs"]], [0, 1, 2])
        self.assertTrue(result["sameTrackPcm"] and result["sameUnitPcm"] and result["sameCues"])
        self.assertTrue(all(row["wallSeconds"] > 0 and row["track"]["decode"] == "pass" for row in result["runs"]))
        self.assertEqual(result["humanListening"], "not_run")
        self.assertTrue((self.out / "comparison.json").is_file())
        with self.assertRaisesRegex(ValueError, "new directory"), patch.object(subject.subprocess, "run", side_effect=AssertionError("cache must not rerun")):
            subject.run(self.manifest, self.checkpoint, subject.LEGACY / "render_weekly_audio.py",
                        Path(sys.executable), "cuda:0", self.out)

    def test_pcm_difference_is_reported_without_pretending_quality_acceptance(self):
        with patch.object(subject.subprocess, "run", self.renderer_process):
            subject.run(self.manifest, self.checkpoint, subject.LEGACY / "render_weekly_audio.py",
                        Path(sys.executable), "cuda:0", self.out)
        path = self.out / "cpu-2/measurement.json"
        value = subject.read(path)
        value["track"]["pcmSha256"] = "0" * 64
        path.write_text(json.dumps(value))
        result = subject.summarize(self.out)
        self.assertFalse(result["sameTrackPcm"])
        self.assertEqual(result["qualityAcceptance"], "not_evaluated")

    def test_failed_process_preserves_log_and_stops_remaining_gpu_runs(self):
        with patch.object(subject.subprocess, "run", return_value=subprocess.CompletedProcess([], 75)) as call:
            with self.assertRaisesRegex(ValueError, "failed.*75"):
                subject.run(self.manifest, self.checkpoint, subject.LEGACY / "render_weekly_audio.py",
                            Path(sys.executable), "cuda:0", self.out)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(subject.read(self.out / "cpu-0/measurement.json")["exitCode"], 75)
        self.assertTrue((self.out / "cpu-0/renderer.log").exists())
        self.assertFalse((self.out / "comparison.json").exists())

    def test_timeout_is_recorded_and_checkpoint_drift_blocks_before_model(self):
        with patch.object(subject.subprocess, "run", side_effect=subprocess.TimeoutExpired([], 1)):
            with self.assertRaisesRegex(ValueError, "failed.*124"):
                subject.run(self.manifest, self.checkpoint, subject.LEGACY / "render_weekly_audio.py",
                            Path(sys.executable), "cuda:0", self.out)
        self.assertEqual(subject.read(self.out / "cpu-0/measurement.json")["exitCode"], 124)
        (self.checkpoint / "model.safetensors").write_bytes(b"wrong")
        with self.assertRaisesRegex(ValueError, "Wrong formal checkpoint"), patch.object(subject.subprocess, "run", side_effect=AssertionError("invalid checkpoint started GPU")):
            subject.run(self.manifest, self.checkpoint, subject.LEGACY / "render_weekly_audio.py",
                        Path(sys.executable), "cuda:0", self.root / "new-matrix")

    def test_settings_drift_cannot_be_compared(self):
        with patch.object(subject.subprocess, "run", self.renderer_process):
            subject.run(self.manifest, self.checkpoint, subject.LEGACY / "render_weekly_audio.py",
                        Path(sys.executable), "cuda:0", self.out)
        path = self.out / "cpu-1/measurement.json"
        value = subject.read(path)
        value["renderIdentity"]["seed"] = 99
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "generation identities differ"):
            subject.summarize(self.out)

    def test_flat_staged_entry_does_not_require_repository_parents(self):
        flat = self.root / "benchmark_cpu_overlap.py"
        flat.write_bytes(subject.SCRIPT.read_bytes())
        result = subprocess.run([sys.executable, str(flat), "--help"], capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_actual_checkpoint_config_is_bound_independently_of_adapter(self):
        (self.checkpoint / "config.json").write_text("{}\n")
        with self.assertRaisesRegex(ValueError, "config identity changed"), patch.object(
                subject.subprocess, "run", side_effect=AssertionError("config drift started GPU")):
            subject.run(self.manifest, self.checkpoint, subject.LEGACY / "render_weekly_audio.py",
                        Path(sys.executable), "cuda:0", self.out)


if __name__ == "__main__":
    unittest.main()
