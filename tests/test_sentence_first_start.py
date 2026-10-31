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
                "--window-start", "0", "--units", "0:1", "--no-sync", "--no-publish"]
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
            a = sfa.build_parser().parse_args(
                ["start", "--run", "run-zh", "--locale", "zh-Hans", "--no-sync", "--no-publish"])
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
                 "--window-start", "0", "--units", "0:1", "--segments", str(root / "segments.json"),
                 "--no-sync", "--no-publish"])
            self.assertTrue(any("--speaker-map" in error for error in sfa.validate_start(a, False)))


class DecisionsTest(unittest.TestCase):
    def test_the_two_decisions_are_required(self):
        sfa = load("sfa")
        parser = sfa.build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["start", "--run", "r", "--locale", "zh-Hans"])
        args = parser.parse_args(["start", "--run", "r", "--locale", "zh-Hans",
                                  "--sync", "--no-publish", "--form", "clip"])
        self.assertTrue(args.sync)
        self.assertFalse(args.publish)
        self.assertEqual(args.form, "clip")

    def test_decisions_are_appended_to_run_md_once(self):
        sfa = load("sfa")
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            (run / "run.md").write_text("# 实验\n\n## 决定与改动\n", encoding="utf-8")
            decisions = {"form": "clip", "locales": ["zh-Hans", "ko"], "sync": False,
                         "publish": True, "title": "耶稣的应许", "windowStart": 5.5,
                         "units": "0:9", "sentences": 10}
            self.assertTrue(sfa.append_decisions_to_run_md(run, decisions))
            text = (run / "run.md").read_text(encoding="utf-8")
            self.assertIn("## 冻结决策", text)
            self.assertIn("不发" if not decisions["publish"] else "发布正式页面", text)
            self.assertIn("zh-Hans、ko", text)
            self.assertFalse(sfa.append_decisions_to_run_md(run, decisions))

    def test_build_decisions_records_the_frozen_values(self):
        sfa = load("sfa")
        args = sfa.build_parser().parse_args(
            ["start", "--run", "run-zh", "--locale", "zh-Hans", "--sync", "--publish",
             "--form", "full", "--title", "耶稣的应许", "--window-start", "5.5", "--units", "0:9"])
        decisions = sfa.build_decisions(args, Path("/repo/artifacts/sentence-first-agent/run-zh"),
                                       shares={"ko": Path("/repo/artifacts/sentence-first-agent/run-ko")},
                                       sentences=10, clip_seconds=12.5)
        self.assertEqual(decisions["schemaVersion"], "sentence-first-frozen-decisions-v1")
        self.assertEqual(decisions["locales"], ["zh-Hans", "ko"])
        self.assertTrue(decisions["sync"])
        self.assertTrue(decisions["publish"])
        self.assertEqual(decisions["form"], "full")
        self.assertEqual(decisions["title"], "耶稣的应许")
        self.assertEqual(decisions["sentences"], 10)
        self.assertEqual(decisions["clipSeconds"], 12.5)


class PreflightSingleSpeakerTest(unittest.TestCase):
    def _single_speaker_run(self, root: Path, speaker_key: str = "eric_pilot") -> Path:
        run = make_run(root, "run-zh", speaker_id=None)
        (run / "translations.jsonl").write_text('{"id": "s0001", "target": "你好"}\n{"id": "s0002", "target": "再见"}\n',
                                                encoding="utf-8")
        (run / "review.json").write_text(json.dumps({"locale": "zh-Hans", "speaker": speaker_key}), encoding="utf-8")
        (run / "speech.jsonl").write_text(
            "".join(json.dumps({"id": f"s{number:04d}", "speaker": speaker_key, "language": "Chinese",
                                "spokenText": "你好"}) + "\n" for number in (1, 2)), encoding="utf-8")
        (run / "decisions.json").write_text(json.dumps({
            "schemaVersion": "sentence-first-frozen-decisions-v1", "locales": ["zh-Hans"],
            "sync": False, "publish": False, "title": "测试", "form": "clip"}), encoding="utf-8")
        return run

    def test_single_speaker_review_key_resolves_through_the_registry(self):
        preflight = load("preflight")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = self._single_speaker_run(root)
            registry = make_registry(root)
            self.assertEqual(preflight.main(["--stage", "full", "--run", str(run),
                                             "--registry", str(registry), "--locale", "zh-Hans"]), 0)

    def test_unknown_single_speaker_key_fails(self):
        preflight = load("preflight")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = self._single_speaker_run(root, speaker_key="ghost_pilot")
            registry = make_registry(root)
            out = root / "preflight.json"
            self.assertEqual(preflight.main(["--stage", "full", "--run", str(run), "--registry", str(registry),
                                             "--locale", "zh-Hans", "--out", str(out)]), 1)
            result = json.loads(out.read_text())
            self.assertTrue(any("registry:single-speaker" == error["name"] for error in result["errors"]))


class PreflightDecisionsTest(unittest.TestCase):
    def _run_with_decisions(self, root: Path, decisions: dict | None):
        run = make_run(root, "run-zh")
        if decisions is not None:
            (run / "decisions.json").write_text(json.dumps(decisions), encoding="utf-8")
        return run

    def test_missing_decisions_is_a_warning_but_required_mode_fails(self):
        preflight = load("preflight")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = self._run_with_decisions(root, None)
            registry = make_registry(root)
            out = root / "preflight.json"
            self.assertEqual(preflight.main(["--stage", "setup", "--run", str(run),
                                             "--registry", str(registry), "--locale", "zh-Hans",
                                             "--out", str(out)]), 0)
            self.assertTrue(any(w["name"] == "decisions:file" for w in
                                json.loads(out.read_text(encoding="utf-8"))["warnings"]))
            self.assertEqual(preflight.main(["--stage", "setup", "--run", str(run),
                                             "--registry", str(registry), "--locale", "zh-Hans",
                                             "--require-decisions"]), 1)

    def test_complete_decisions_pass_and_publishing_needs_a_title(self):
        preflight = load("preflight")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            complete = {"schemaVersion": "sentence-first-frozen-decisions-v1",
                        "locales": ["zh-Hans", "ko"], "sync": False, "publish": True,
                        "title": "耶稣的应许", "form": "full"}
            run = self._run_with_decisions(root, complete)
            registry = make_registry(root)
            self.assertEqual(preflight.main(["--stage", "setup", "--require-decisions", "--run", str(run),
                                             "--registry", str(registry), "--locale", "zh-Hans"]), 0)
            broken = dict(complete, title="  ")
            (run / "decisions.json").write_text(json.dumps(broken), encoding="utf-8")
            self.assertEqual(preflight.main(["--stage", "setup", "--require-decisions", "--run", str(run),
                                             "--registry", str(registry), "--locale", "zh-Hans"]), 1)


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
