"""Exercise the diagnostic entry offline, including its pre-GPU admission gates."""
import builtins
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from scripts.experiments import benchmark_back_asr as subject


class BenchmarkBackAsrTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.model_path = self.root / subject.MODEL_REVISION
        self.model_path.mkdir()
        (self.model_path / "config.json").write_text("{}")
        (self.model_path / "model.safetensors").write_bytes(b"offline model fixture")
        self.inputs_path = self.root / "inputs.json"
        self.result_path = self.root / "tts" / "result.json"
        self.result_path.parent.mkdir()
        self.out = self.root / "back-asr"
        cases = []
        for locale in subject.LANGUAGES:
            for length in ("short", "long"):
                cases.append(self.case(f"{locale}-{length}", locale, length))
        cases += [self.case("tail-0", "zh-Hans", "tail"),
                  self.case("tail-1", "es", "tail")]
        self.inputs = {"cases": cases}
        trials = []
        for locale in subject.LANGUAGES:
            for size in (1, 2):
                trials.append(self.trial(f"{locale}-b{size}",
                    [row for row in cases if row["targetLocale"] == locale
                     and row["lengthClass"] in ("short", "long")]))
        trials += [self.trial(f"mixed-b{size}", cases) for size in (4, 8)]
        self.result = {"status": "complete_diagnostic", "trials": trials}
        self.write_inputs()

    @staticmethod
    def case(case_id, locale, length):
        text = "frozen text " + case_id
        return {"caseId": case_id, "targetLocale": locale, "lengthClass": length,
                "text": text, "textSha256": hashlib.sha256(text.encode()).hexdigest()}

    def trial(self, condition, cases):
        units = []
        for index, case in enumerate(cases):
            name = f"{condition}-{index}.wav"
            path = self.result_path.parent / name
            path.write_bytes(case["text"].encode())
            units.append({"identity": {"caseId": case["caseId"],
                                       "textSha256": case["textSha256"]},
                          "audioPath": name, "audioSha256": subject.sha(path),
                          "sampleRate": 24000, "durationSeconds": 1.0})
        return {"condition": condition, "repetition": "warm-1", "units": units}

    def write_inputs(self):
        self.inputs_path.write_text(json.dumps(self.inputs))
        self.result["inputManifestSha256"] = subject.sha(self.inputs_path)

    def invoke(self):
        self.result_path.write_text(json.dumps(self.result))
        argv = ["benchmark_back_asr.py", "--tts-result", str(self.result_path),
                "--inputs", str(self.inputs_path), "--model-path", str(self.model_path),
                "--out", str(self.out), "--repeats", "1"]
        with patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()):
            subject.main()

    def reject_before_gpu(self):
        imported = []
        original_import = builtins.__import__

        def guarded_import(name, *args, **kwargs):
            if name in ("torch", "soundfile", "qwen_asr"):
                imported.append(name)
                raise RuntimeError("GPU/runtime import reached for invalid input")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", guarded_import), self.assertRaises(AssertionError):
            self.invoke()
        self.assertEqual(imported, [])
        self.assertFalse(self.out.exists(), "invalid inputs must not create a dispatch marker")

    def test_all_eight_conditions_cover_28_unique_condition_cases(self):
        trials = subject.validate_inputs(self.result, self.inputs, self.model_path)
        pairs = [(t["condition"], u["identity"]["caseId"])
                 for t in trials for u in t["units"]]
        self.assertEqual(len(pairs), 28)
        self.assertEqual(len(set(pairs)), 28)
        self.assertEqual([len(t["units"]) for t in trials], [2] * 6 + [8, 8])

    def test_missing_condition_rejected_before_gpu(self):
        self.result["trials"].pop()
        self.reject_before_gpu()

    def test_duplicate_condition_rejected_before_gpu(self):
        self.result["trials"][-1] = self.result["trials"][0]
        self.reject_before_gpu()

    def test_missing_mixed_tail_rejected_before_gpu(self):
        self.result["trials"][-1]["units"].pop()
        self.reject_before_gpu()

    def test_reordered_units_rejected_before_gpu(self):
        self.result["trials"][-1]["units"].reverse()
        self.reject_before_gpu()

    def test_duplicate_unit_rejected_before_gpu(self):
        self.result["trials"][-1]["units"][-1] = self.result["trials"][-1]["units"][0]
        self.reject_before_gpu()

    def test_duplicate_frozen_case_rejected_before_gpu(self):
        self.inputs["cases"][-1] = self.inputs["cases"][0]
        self.write_inputs()
        self.reject_before_gpu()

    def test_two_short_cases_cannot_replace_short_and_long_before_gpu(self):
        self.inputs["cases"][1]["lengthClass"] = "short"
        self.write_inputs()
        self.reject_before_gpu()

    def test_wrong_snapshot_rejected_before_gpu(self):
        wrong = self.root / "different-snapshot"
        self.model_path.rename(wrong)
        self.model_path = wrong
        self.reject_before_gpu()

    def test_incomplete_snapshot_rejected_before_gpu(self):
        (self.model_path / "model.safetensors").unlink()
        self.reject_before_gpu()

    def test_manifest_drift_rejected_before_gpu(self):
        self.inputs_path.write_text(self.inputs_path.read_text() + "\n")
        self.reject_before_gpu()

    def test_audio_hash_drift_rejected_before_gpu(self):
        unit = self.result["trials"][0]["units"][0]
        (self.result_path.parent / unit["audioPath"]).write_bytes(b"changed")
        self.reject_before_gpu()

    def test_text_identity_drift_rejected_before_gpu(self):
        self.result["trials"][0]["units"][0]["identity"]["textSha256"] = "0" * 64
        self.reject_before_gpu()

    def test_wrong_audio_rate_rejected_before_gpu(self):
        self.result["trials"][0]["units"][0]["sampleRate"] = 16000
        self.reject_before_gpu()

    def test_audio_path_escape_rejected_before_gpu(self):
        path = self.root / "outside.wav"
        path.write_bytes(b"outside")
        unit = self.result["trials"][0]["units"][0]
        unit.update(audioPath="../outside.wav", audioSha256=subject.sha(path))
        self.reject_before_gpu()

    def runtime(self, transform=None):
        batches = []

        def transcribe(*, audio, language):
            batches.append((len(audio), language))
            values = [SimpleNamespace(text=wave.text) for wave, _ in audio]
            return transform(values) if transform else values

        loader = Mock(return_value=SimpleNamespace(transcribe=transcribe))
        cuda = SimpleNamespace(is_available=Mock(return_value=True), synchronize=Mock(),
            reset_peak_memory_stats=Mock(), max_memory_allocated=Mock(return_value=123))
        modules = {
            "torch": SimpleNamespace(cuda=cuda, __version__="offline", bfloat16="bf16"),
            "soundfile": SimpleNamespace(read=lambda path, **_: (
                SimpleNamespace(ndim=1, text=Path(path).read_text()), 24000)),
            "qwen_asr": SimpleNamespace(Qwen3ASRModel=SimpleNamespace(from_pretrained=loader)),
            "scripts.screen_target_language_audio_units": SimpleNamespace(tokens=lambda text, _: text.split()),
        }
        return modules, loader, batches

    def test_real_entry_loads_once_and_processes_all_rows_including_short_tail(self):
        modules, loader, batches = self.runtime()
        with patch.dict(sys.modules, modules):
            self.invoke()
        loader.assert_called_once_with(str(self.model_path), dtype="bf16", device_map="cuda:0",
                                      max_inference_batch_size=8, max_new_tokens=2048)
        result = json.loads((self.out / "result.json").read_text())
        self.assertEqual(result["status"], "complete_diagnostic")
        self.assertFalse(result["releaseEligible"])
        self.assertEqual(result["humanListening"], "not_run")
        self.assertEqual(result["modelRevision"], subject.MODEL_REVISION)
        self.assertEqual(len(result["requests"]), 28)
        self.assertEqual(len(result["trials"]), 6)
        identities = [(r["condition"], r["caseId"]) for r in result["requests"]]
        for trial in result["trials"]:
            self.assertEqual([(r["condition"], r["caseId"]) for r in trial["rows"]], identities)
            self.assertTrue(all(row["status"] == "pass" for row in trial["rows"]))
        self.assertEqual([size for size, _ in batches], [1] * 56 + [4] * 14 + [8, 8, 8, 4] * 2)
        self.assertEqual(sum(size for size, _ in batches), 28 * 6)

    def test_output_cardinality_failure_never_publishes_complete_result(self):
        modules, loader, _ = self.runtime(transform=lambda _: [])
        with patch.dict(sys.modules, modules), self.assertRaisesRegex(AssertionError, "cardinality"):
            self.invoke()
        loader.assert_called_once()
        self.assertTrue((self.out / "started.json").exists())
        self.assertFalse((self.out / "result.json").exists())


if __name__ == "__main__":
    unittest.main()
