import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "finalize_multilingual_fragment_poc", ROOT / "scripts/finalize_multilingual_fragment_poc.py"
)
subject = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(subject)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class FinalizeMultilingualFragmentPocTest(unittest.TestCase):
    def make_fixture(self, root: Path) -> tuple[Path, Path, Path]:
        layer2 = root / "layer2"
        layer3 = root / "layer3"
        candidates = []
        standard_tracks = []
        vietnamese_tracks = []
        results = []
        receipt_tracks = []
        for index, locale in enumerate(subject.LOCALES):
            target_text = f"target text {locale}"
            candidate = {
                "targetLocale": locale,
                "status": "machine_review_pass_human_review_pending",
                "groups": [{"targetText": target_text}],
            }
            candidate_hash = subject.canonical_sha(candidate)
            write_json(layer2 / locale / "target-language-candidate.json", candidate)
            candidates.append({
                "targetLocale": locale,
                "path": f"{locale}/target-language-candidate.json",
                "jsonSha256": candidate_hash,
                "status": candidate["status"],
            })

            renderer_audio = f"renderer-{locale}".encode()
            renderer_path = layer3 / "renderer" / f"{locale}.wav"
            renderer_path.parent.mkdir(parents=True, exist_ok=True)
            renderer_path.write_bytes(renderer_audio)
            renderer_track = {
                "targetLocale": locale,
                "file": str(renderer_path.relative_to(layer3)),
                "audioSha256": hashlib.sha256(renderer_audio).hexdigest(),
            }
            (vietnamese_tracks if locale == "vi" else standard_tracks).append(renderer_track)

            mp3 = layer3 / locale / "audio.mp3"
            mp3.parent.mkdir(parents=True, exist_ok=True)
            mp3.write_bytes(f"mp3-{locale}".encode())
            package = {
                "targetLanguageCandidateJsonSha256": candidate_hash,
                "track": {"path": "audio.mp3", "sha256": subject.file_sha(mp3)},
                "units": [{"durationSeconds": 1.25}],
                "machineScreening": {"status": "not_run", "model": None, "coverage": 0},
                "issues": ["machine_asr_screening_not_run", "human_listening_pending"],
            }
            write_json(layer3 / locale / "target-language-audio-package.json", package)
            receipt_tracks.append({
                "targetLocale": locale,
                "durationSeconds": 1.25,
                "audioSha256": subject.file_sha(mp3),
                "packageJsonSha256": subject.canonical_sha(package),
                "humanListeningStatus": "pending",
            })
            results.append({
                "speakerId": "eric_geiger",
                "targetLocale": locale,
                "audioSha256": renderer_track["audioSha256"],
                "expectedTextSha256": hashlib.sha256(target_text.encode()).hexdigest(),
                "similarity": 0.2 if locale == "vi" else 0.9 + index / 100,
            })

        write_json(layer2 / "layer2-receipt.json", {
            "allMachineChecksPass": True,
            "candidates": candidates,
        })
        write_json(layer3 / "manifest.json", {"tracks": standard_tracks})
        write_json(layer3 / "vietnamese-manifest.json", {"tracks": vietnamese_tracks})
        write_json(layer3 / "layer3-receipt.json", {
            "status": "encoded_and_fully_decoded",
            "tracks": receipt_tracks,
        })
        screening_path = layer3 / "asr-screening.json"
        write_json(screening_path, {
            "model": "Qwen/Qwen3-ASR-0.6B",
            "coverage": 1,
            "trackCount": 4,
            "reviewPriorityThreshold": 0.85,
            "results": results,
        })
        return layer2, layer3, screening_path

    def test_screening_state_is_review_priority_not_human_approval(self):
        state = subject.screening_state({"similarity": 0.2}, 0.85, "asr")
        self.assertEqual(state["status"], "requires_review")
        self.assertEqual(state, {"status": "requires_review", "model": "asr", "coverage": 1})

    def test_finalize_writes_bound_receipts_then_check_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            layer2, layer3, screening = self.make_fixture(Path(directory))
            result = subject.finalize(layer2, layer3, screening, write=True)
            self.assertEqual(result["reviewPriorityLocales"], ["vi"])
            self.assertFalse(result["productionEligible"])
            checked = subject.finalize(layer2, layer3, screening, write=False)
            self.assertEqual(checked["reviewPriorityLocales"], ["vi"])
            vi = json.loads((layer3 / "vi/target-language-audio-package.json").read_text())
            self.assertEqual(vi["machineScreening"]["status"], "requires_review")
            self.assertIn("machine_asr_screening_below_threshold_requires_human_review", vi["issues"])

    def test_check_fails_on_stale_layer2_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            layer2, layer3, screening = self.make_fixture(Path(directory))
            subject.finalize(layer2, layer3, screening, write=True)
            receipt_path = layer2 / "layer2-receipt.json"
            receipt = json.loads(receipt_path.read_text())
            receipt["candidates"][0]["jsonSha256"] = "0" * 64
            write_json(receipt_path, receipt)
            with self.assertRaisesRegex(ValueError, "Stale Layer 2 receipt hash"):
                subject.finalize(layer2, layer3, screening, write=False)


if __name__ == "__main__":
    unittest.main()
