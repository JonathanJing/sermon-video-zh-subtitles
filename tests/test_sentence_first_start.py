"""Unit tests for ``sfa.py start`` (setup wrapper) and ``preflight.py --stage setup``."""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

EXPERIMENTS = Path(__file__).resolve().parents[1] / "experiments" / "sentence-first-agent"


def load(name: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, EXPERIMENTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def make_run(root: Path, name: str, *, sentences: int = 2, speaker_id: str | None = "eric_geiger") -> Path:
    run = root / "artifacts" / "sentence-first-agent" / name
    (run / "slices").mkdir(parents=True)
    (run / "clip.json").write_text(json.dumps({"locale": "zh-Hans", "mediaStart": 10.0, "mediaEnd": 20.0}) + "\n",
                                   encoding="utf-8")
    rows = []
    for number in range(1, sentences + 1):
        row = {"id": f"s{number:04d}", "english": f"line {number}", "start": number, "end": number + 1,
               "pauseAfter": 0.0, "sourceUnitId": f"u{number}", "words": []}
        if speaker_id:
            row["speakerId"] = speaker_id
        rows.append(row)
    (run / "sentences.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    for number in range(1, sentences + 1):
        (run / "slices" / f"s{number:04d}.wav").write_bytes(b"RIFF" + bytes([number]))
    (run / "slices" / "slices.json").write_text("[]\n", encoding="utf-8")
    return run


def make_registry(root: Path, *, purposes=("multilingual_dubbing",), capability="human_reviewed") -> Path:
    registry = root / "registry.json"
    registry.write_text(json.dumps({"speakers": [{
        "speakerId": "eric_geiger", "speakerKey": "eric_pilot",
        "authorization": {"status": "authorized", "purposes": list(purposes)},
        "localeCapabilities": [{"targetLocale": "zh-Hans", "status": capability}],
    }]}), encoding="utf-8")
    return registry


class ResolveRunTest(unittest.TestCase):
    def test_name_resolves_under_the_artifact_directory(self):
        sfa = load("sfa")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(sfa.resolve_run("20261102-z", repo=root),
                             (root / "artifacts" / "sentence-first-agent" / "20261102-z").resolve())

    def test_artifacts_prefix_is_accepted(self):
        sfa = load("sfa")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(sfa.resolve_run("artifacts/sentence-first-agent/x", repo=root),
                             (root / "artifacts" / "sentence-first-agent" / "x").resolve())

    def test_outside_the_artifact_directory_is_rejected(self):
        sfa = load("sfa")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for value in ("../elsewhere", str(root / "other")):
                with self.assertRaises(sfa.SetupError):
                    sfa.resolve_run(value, repo=root)


class ShareRunTest(unittest.TestCase):
    def test_share_copies_the_three_inputs_and_is_idempotent(self):
        sfa = load("sfa")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = make_run(root, "run-zh")
            target = root / "artifacts" / "sentence-first-agent" / "run-ko"
            first = sfa.share_run(source, target)
            self.assertEqual(first["status"], "shared")
            self.assertEqual(first["sentences"], 2)
            self.assertEqual((target / "sentences.jsonl").read_bytes(),
                             (source / "sentences.jsonl").read_bytes())
            self.assertEqual((target / "clip.json").read_bytes(), (source / "clip.json").read_bytes())
            self.assertEqual((target / "slices" / "s0002.wav").read_bytes(),
                             (source / "slices" / "s0002.wav").read_bytes())
            second = sfa.share_run(source, target)
            self.assertEqual(second["status"], "already-shared")

    def test_share_refuses_a_target_with_downstream_files(self):
        sfa = load("sfa")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = make_run(root, "run-zh")
            target = make_run(root, "run-ko")
            (target / "translations.jsonl").write_text('{"id": "s0001", "target": "x"}\n', encoding="utf-8")
            (target / "sentences.jsonl").write_text('{"id": "stale"}\n', encoding="utf-8")
            with self.assertRaises(sfa.SetupError):
                sfa.share_run(source, target)
            result = sfa.share_run(source, target, force=True)
            self.assertEqual(result["status"], "shared")
            self.assertTrue((target / "translations.jsonl").exists())
            self.assertEqual((target / "sentences.jsonl").read_bytes(),
                             (source / "sentences.jsonl").read_bytes())

    def test_share_refuses_a_conflicting_slice_without_force(self):
        sfa = load("sfa")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = make_run(root, "run-zh")
            target = make_run(root, "run-ko")
            (target / "slices" / "s0001.wav").write_bytes(b"RIFFdifferent")
            with self.assertRaises(sfa.SetupError):
                sfa.share_run(source, target)
            result = sfa.share_run(source, target, force=True)
            self.assertEqual(result["status"], "shared")
            self.assertEqual((target / "slices" / "s0001.wav").read_bytes(),
                             (source / "slices" / "s0001.wav").read_bytes())

    def test_share_rejects_a_target_that_is_a_file(self):
        sfa = load("sfa")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = make_run(root, "run-zh")
            target = root / "artifacts" / "sentence-first-agent" / "run-ko"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("not a directory", encoding="utf-8")
            with self.assertRaises(sfa.SetupError):
                sfa.share_run(source, target)

    def test_share_rejects_a_target_inside_the_source(self):
        sfa = load("sfa")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = make_run(root, "run-zh")
            with self.assertRaises(sfa.SetupError):
                sfa.share_run(source, source / "ko")

    def test_share_needs_the_three_inputs_on_the_source(self):
        sfa = load("sfa")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = make_run(root, "run-zh")
            (source / "slices" / "slices.json").unlink()
            target = root / "artifacts" / "sentence-first-agent" / "run-ko"
            with self.assertRaises(sfa.SetupError):
                sfa.share_run(source, target)


class ParseSharesTest(unittest.TestCase):
    def test_two_locales_cannot_share_one_target(self):
        sfa = load("sfa")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            primary = sfa.resolve_run("run-zh", repo=root)
            with self.assertRaises(sfa.SetupError):
                sfa.parse_shares(["ko=run-x", "es=run-x"], "zh-Hans", primary, repo=root)

    def test_primary_locale_cannot_be_a_share_target(self):
        sfa = load("sfa")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            primary = sfa.resolve_run("run-zh", repo=root)
            with self.assertRaises(sfa.SetupError):
                sfa.parse_shares(["zh-Hans=run-x"], "zh-Hans", primary, repo=root)


class PlanTest(unittest.TestCase):
    def _args(self, root: Path, *, share: bool = True):
        sfa = load("sfa")
        argv = ["start", "--run", "run-zh", "--locale", "zh-Hans",
                "--anchor", str(root / "anchor.json"), "--media", str(root / "media.mp4"),
                "--window-start", "0", "--units", "0:1"]
        if share:
            argv += ["--share-to", "ko=run-ko"]
        return sfa.build_parser().parse_args(argv)

    def test_plan_runs_prepare_when_the_run_is_empty(self):
        sfa = load("sfa")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = root / "artifacts" / "sentence-first-agent" / "run-zh"
            steps = sfa.build_plan(self._args(root), run, {"ko": root / "run-ko"}, True)
            self.assertEqual(steps[1]["step"], "prepare")
            self.assertEqual(steps[1]["action"], "run")
            self.assertIn("share", [step["step"] for step in steps])
            self.assertEqual(steps[-1]["step"], "receipt")

    def test_plan_skips_prepare_when_clip_and_sentences_exist(self):
        sfa = load("sfa")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = make_run(root, "run-zh")
            steps = sfa.build_plan(self._args(root), run, {"ko": root / "run-ko"}, False)
            prepare = next(step for step in steps if step["step"] == "prepare")
            self.assertEqual(prepare["action"], "skip")

    def test_missing_prepare_inputs_are_reported(self):
        sfa = load("sfa")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = sfa.build_parser().parse_args(["start", "--run", "run-zh", "--locale", "zh-Hans"])
            errors = sfa.validate_start(a, True)
            self.assertTrue(any("--anchor" in error for error in errors))
            self.assertTrue(any("--media" in error for error in errors))

    def test_half_a_speaker_pair_is_reported(self):
        sfa = load("sfa")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "anchor.json").write_text("{}")
            (root / "media.mp4").write_bytes(b"")
            a = sfa.build_parser().parse_args(
                ["start", "--run", "run-zh", "--locale", "zh-Hans",
                 "--anchor", str(root / "anchor.json"), "--media", str(root / "media.mp4"),
                 "--window-start", "0", "--units", "0:1", "--segments", str(root / "segments.json")])
            self.assertTrue(any("--speaker-map" in error for error in sfa.validate_start(a, False)))


class PreflightSetupStageTest(unittest.TestCase):
    def test_setup_stage_passes_before_translation_and_full_stage_fails(self):
        preflight = load("preflight")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = make_run(root, "run-zh")
            registry = make_registry(root)
            self.assertEqual(preflight.main(["--stage", "setup", "--run", str(run),
                                             "--registry", str(registry), "--locale", "zh-Hans"]), 0)
            journal = (run / "journal.ndjson").read_text(encoding="utf-8")
            self.assertIn("l1.preflight.setup", journal)
            self.assertNotIn('"stage": "l1.preflight"', journal)
            self.assertEqual(preflight.main(["--run", str(run), "--registry", str(registry),
                                             "--locale", "zh-Hans"]), 1)

    def test_setup_stage_reports_an_unregistered_speaker(self):
        preflight = load("preflight")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = make_run(root, "run-zh", speaker_id="ghost_speaker")
            registry = make_registry(root)
            out = root / "preflight.json"
            self.assertEqual(preflight.main(["--stage", "setup", "--run", str(run), "--registry", str(registry),
                                             "--locale", "zh-Hans", "--out", str(out)]), 1)
            result = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(result["stage"], "setup")
            self.assertTrue(any("registry:ghost_speaker" == error["name"] for error in result["errors"]))

    def test_setup_stage_accepts_a_single_voice_run_without_speaker_ids(self):
        preflight = load("preflight")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = make_run(root, "run-zh", speaker_id=None)
            registry = make_registry(root)
            self.assertEqual(preflight.main(["--stage", "setup", "--run", str(run),
                                             "--registry", str(registry), "--locale", "zh-Hans"]), 0)

    def test_setup_stage_warns_about_a_registry_status_that_is_not_human_reviewed(self):
        preflight = load("preflight")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = make_run(root, "run-zh")
            registry = make_registry(root, capability="machine_checked")
            out = root / "preflight.json"
            self.assertEqual(preflight.main(["--stage", "setup", "--run", str(run), "--registry", str(registry),
                                             "--locale", "zh-Hans", "--out", str(out)]), 0)
            result = json.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(any(w["name"].startswith("capability-status:") for w in result["warnings"]))


if __name__ == "__main__":
    unittest.main()
