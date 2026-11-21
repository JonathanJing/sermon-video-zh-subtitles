"""Sentence-first local (mbp14) TTS: host-memory gate, MPS fields and dry-run planning."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
LINE = ROOT / "experiments/sentence-first-agent"


def load_tts_sentences():
    spec = importlib.util.spec_from_file_location("sfa_tts_sentences_local", LINE / "tts_sentences.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def vm_stat_output(free: int, inactive: int, speculative: int, page: int = 16384) -> str:
    lines = [f"Mach Virtual Memory Statistics: (page size of {page} bytes)"]
    lines.append(f"Pages free:                               {free}.")
    lines.append(f"Pages active:                             10.")
    lines.append(f"Pages inactive:                           {inactive}.")
    lines.append(f"Pages speculative:                        {speculative}.")
    lines.append(f"Pages wired down:                         20.")
    return "\n".join(lines) + "\n"


def speech_rows(count: int) -> str:
    return "\n".join(json.dumps({"id": f"s{index:04d}", "spokenText": f"第{index}句。",
                                 "language": "Chinese", "speaker": "eric_pilot"})
                     for index in range(1, count + 1)) + "\n"


def run_main(module, argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.object(sys, "argv", ["tts_sentences.py"] + argv):
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = module.main()
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 1
                if not isinstance(exc.code, int) and exc.code:
                    err.write(str(exc.code) + "\n")
    return code, out.getvalue(), err.getvalue()


class DarwinMemoryReadingTests(unittest.TestCase):
    def test_darwin_available_counts_free_inactive_speculative(self):
        tts = load_tts_sentences()
        completed = SimpleNamespace(stdout=vm_stat_output(100, 200, 300))
        with mock.patch("subprocess.run", return_value=completed):
            self.assertEqual(tts._darwin_available_bytes(), (100 + 200 + 300) * 16384)

    def test_darwin_unavailable_returns_none(self):
        tts = load_tts_sentences()
        with mock.patch("subprocess.run", side_effect=OSError("no vm_stat")):
            self.assertIsNone(tts._darwin_available_bytes())
        with mock.patch("subprocess.run", return_value=SimpleNamespace(stdout="no header")):
            self.assertIsNone(tts._darwin_available_bytes())

    def test_mem_available_prefers_proc_meminfo(self):
        tts = load_tts_sentences()
        with mock.patch("pathlib.Path.read_text", return_value="MemTotal: 1 kB\nMemAvailable: 4096 kB\n"):
            self.assertEqual(tts.mem_available_bytes(), 4096 * 1024)


class MemoryGateTests(unittest.TestCase):
    def test_mps_gates_by_default_and_cuda_does_not(self):
        tts = load_tts_sentences()
        self.assertEqual(tts.device_gate_gib("mps", None, tts.DEFAULT_MPS_MIN_AVAILABLE_GIB), 15.0)
        self.assertEqual(tts.device_gate_gib("cuda:0", None, tts.DEFAULT_MPS_MIN_AVAILABLE_GIB), 0.0)
        self.assertEqual(tts.device_gate_gib("mps", 12.5, tts.DEFAULT_MPS_MIN_AVAILABLE_GIB), 12.5)

    def test_admission_reports_numbers_and_fails_short(self):
        tts = load_tts_sentences()
        with mock.patch.object(tts, "mem_available_bytes", return_value=12 * 2**30):
            short = tts.admission("mps", 20.0)
        self.assertEqual(short["pass"], False)
        self.assertEqual(short["availableGiB"], 12.0)
        self.assertEqual(short["requiredGiB"], 20.0)
        with mock.patch.object(tts, "mem_available_bytes", return_value=23 * 2**30):
            ok = tts.admission("mps", 20.0)
        self.assertEqual(ok["pass"], True)
        with mock.patch.object(tts, "mem_available_bytes", return_value=None):
            unknown = tts.admission("mps", 20.0)
        self.assertIsNone(unknown["pass"])


class MpsAllocatorTests(unittest.TestCase):
    def test_mps_fields_and_release(self):
        tts = load_tts_sentences()
        calls = []
        mps = SimpleNamespace(is_available=lambda: True, current_allocated_memory=lambda: 7,
                              driver_allocated_memory=lambda: 9,
                              synchronize=lambda: calls.append("sync"),
                              empty_cache=lambda: calls.append("empty"))
        fields = tts.memory_fields(SimpleNamespace(mps=mps))
        self.assertEqual((fields["mpsAllocatedBytes"], fields["mpsDriverAllocatedBytes"]), (7, 9))
        self.assertIsInstance(tts.release_device_cache(SimpleNamespace(mps=mps)), float)
        self.assertEqual(calls, ["sync", "empty"])

    def test_no_device_yields_nulls(self):
        tts = load_tts_sentences()
        fields = tts.memory_fields(SimpleNamespace())
        self.assertEqual(set(fields), {"memAvailableBytes", "cudaAllocatedBytes", "cudaReservedBytes",
                                       "cudaMaxReservedBytes"})
        self.assertIsNone(tts.release_device_cache(SimpleNamespace()))


class CheckpointIdentityTests(unittest.TestCase):
    def setUp(self):
        self.module = load_tts_sentences()
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.checkpoint = self.dir / "ckpt"
        self.checkpoint.mkdir()
        (self.checkpoint / "model.safetensors").write_bytes(b"weights")
        (self.dir / "speech.jsonl").write_text(speech_rows(1), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def argv(self, *extra: str) -> list[str]:
        return ["--speech", str(self.dir / "speech.jsonl"), "--checkpoint", str(self.checkpoint),
                "--out", str(self.dir / "tts"), "--device", "mps", "--dtype", "float32",
                "--dry-run", "--min-available-gib", "0", *extra]

    def test_matching_hash_is_reported(self):
        import hashlib
        expected = hashlib.sha256(b"weights").hexdigest()
        code, out, err = run_main(self.module, self.argv("--expect-checkpoint-sha256", expected))
        self.assertEqual(code, 0, err)
        self.assertIn(expected, out)

    def test_mismatch_refuses_before_loading(self):
        code, out, err = run_main(self.module, self.argv("--expect-checkpoint-sha256", "0" * 64))
        self.assertEqual(code, 1)
        self.assertIn("checkpoint weights differ", err)

    def test_missing_weights_refuses(self):
        (self.checkpoint / "model.safetensors").unlink()
        code, out, err = run_main(self.module, self.argv("--expect-checkpoint-sha256", "0" * 64))
        self.assertEqual(code, 1)
        self.assertIn("no model.safetensors", err)


class DryRunTests(unittest.TestCase):
    def setUp(self):
        self.module = load_tts_sentences()
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "speech.jsonl").write_text(speech_rows(3), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def argv(self, *extra: str) -> list[str]:
        return ["--speech", str(self.dir / "speech.jsonl"), "--checkpoint", str(self.dir / "ckpt"),
                "--out", str(self.dir / "tts"), "--device", "mps", "--dtype", "float32",
                "--seed", "7", "--batch-size", "8", *extra]

    def test_dry_run_plans_windows_without_loading_the_model(self):
        code, out, err = run_main(self.module, self.argv("--dry-run", "--min-available-gib", "0"))
        self.assertEqual(code, 0, err)
        plan = json.loads([line for line in out.splitlines() if '"plan"' in line][-1])["plan"]
        self.assertEqual((plan["sentences"], plan["pending"], plan["batches"]), (3, 3, 1))
        self.assertEqual((plan["seed"], plan["batchSize"], plan["device"]), (7, 8, "mps"))
        self.assertEqual(plan["abortBelowGiB"], 6.0)

    def test_dry_run_refuses_below_the_gate(self):
        code, out, err = run_main(self.module, self.argv("--dry-run", "--min-available-gib", "100000"))
        self.assertEqual(code, 1)
        self.assertIn("memory admission failed", err)
        admission = json.loads([line for line in out.splitlines() if '"memoryAdmission"' in line][-1])
        self.assertEqual(admission["memoryAdmission"]["requiredGiB"], 100000.0)
        self.assertFalse(admission["memoryAdmission"]["pass"])

    def test_complete_output_short_circuits_without_torch(self):
        units = self.dir / "tts"
        units.mkdir()
        for index in range(1, 4):
            (units / f"s{index:04d}.wav").write_bytes(b"")
        code, out, err = run_main(self.module, self.argv("--min-available-gib", "0"))
        self.assertEqual(code, 0, err)
        self.assertIn('"pending": 0', out)

    def test_only_ids_file_selects_and_rejects_unknown(self):
        ids = self.dir / "ids.json"
        ids.write_text(json.dumps(["s0002"]), encoding="utf-8")
        code, out, err = run_main(self.module, self.argv("--dry-run", "--min-available-gib", "0",
                                                         "--only-ids-file", str(ids)))
        self.assertEqual(code, 0, err)
        plan = json.loads([line for line in out.splitlines() if '"plan"' in line][-1])["plan"]
        self.assertEqual((plan["sentences"], plan["pending"]), (1, 1))

        ids.write_text(json.dumps(["s9999"]), encoding="utf-8")
        code, out, err = run_main(self.module, self.argv("--dry-run", "--min-available-gib", "0",
                                                         "--only-ids-file", str(ids)))
        self.assertEqual(code, 1)
        self.assertIn("unknown ids", err)


if __name__ == "__main__":
    unittest.main()
