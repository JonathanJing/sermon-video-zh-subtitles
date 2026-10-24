"""Sentence-first Spark scripts: allocator setting, memory admission and per-batch memory log fields."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
LINE = ROOT / "experiments/sentence-first-agent"


def load_tts_sentences():
    spec = importlib.util.spec_from_file_location("sfa_tts_sentences", LINE / "tts_sentences.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TtsSentencesMemoryTests(unittest.TestCase):
    def test_memory_fields_without_cuda_are_explicit_nulls(self):
        tts = load_tts_sentences()
        fields = tts.memory_fields(SimpleNamespace(bfloat16="x"))
        self.assertEqual(set(fields), {"memAvailableBytes", "cudaAllocatedBytes", "cudaReservedBytes", "cudaMaxReservedBytes"})
        self.assertIsNone(fields["cudaReservedBytes"])
        self.assertIsNone(tts.release_cuda_cache(SimpleNamespace()))

    def test_memory_fields_and_release_use_the_cuda_allocator_counters(self):
        tts = load_tts_sentences()
        calls = []
        cuda = SimpleNamespace(is_available=lambda: True, memory_allocated=lambda: 3, memory_reserved=lambda: 5,
                               max_memory_reserved=lambda: 9, synchronize=lambda: calls.append("sync"),
                               empty_cache=lambda: calls.append("empty"))
        fields = tts.memory_fields(SimpleNamespace(cuda=cuda))
        self.assertEqual((fields["cudaAllocatedBytes"], fields["cudaReservedBytes"], fields["cudaMaxReservedBytes"]), (3, 5, 9))
        self.assertIsInstance(tts.release_cuda_cache(SimpleNamespace(cuda=cuda)), float)
        self.assertEqual(calls, ["sync", "empty"])


class SparkRunDryRunTests(unittest.TestCase):
    def test_dry_run_sets_the_allocator_and_reports_the_admission_budget(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tools, work, checkpoint = root / "tools", root / "work", root / "ckpt"
            tools.mkdir(); work.mkdir(); checkpoint.mkdir()
            for name in ("spark_run.sh", "tts_sentences.py", "tts_pool.py", "asr_check.py"):
                (tools / name).write_bytes((LINE / name).read_bytes())
            (work / "speech.jsonl").write_text(json.dumps({"id": "s1", "spokenText": "x", "language": "Chinese", "speaker": "k"}) + "\n")
            (checkpoint / "model.safetensors").write_bytes(b"fixture")
            common = ["bash", str(tools / "spark_run.sh"), "--work", str(work), "--locale", "zh-Hans", "--dry-run"]
            single = subprocess.run(common + ["--steps", "tts", "--checkpoint", str(checkpoint)],
                                    capture_output=True, text=True, check=True).stdout
            self.assertIn("PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True", single)
            self.assertIn("tts memory admission: need 33 GiB", single)
            pool = subprocess.run(common + ["--steps", "tts-pool", "--replicas", "8", "--batch-size", "8",
                                            "--voice", f"k={checkpoint}"], capture_output=True, text=True, check=True).stdout
            self.assertIn("tts-pool memory admission: need 96 GiB", pool)
            asr_env = {"SPEECH_RUNTIME": str(root), "ASR_SNAPSHOT": "ckpt", "CUDA_ALLOC_CONF": "max_split_size_mb:64", "MEM_ASR_GIB": "7"}
            asr = subprocess.run(common + ["--steps", "asr"], capture_output=True, text=True, check=True,
                                 env={**__import__("os").environ, **asr_env}).stdout
            self.assertIn("asr memory admission: need 7 GiB", asr)
            self.assertIn("PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:64", asr)


if __name__ == "__main__":
    unittest.main()
