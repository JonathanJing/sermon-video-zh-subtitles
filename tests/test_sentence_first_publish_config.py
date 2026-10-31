"""Unit tests for the page-config publish driver (``sfa_publish.py``).

The asset parity check is opt-in because it needs the local production artifacts:
run it with ``SFA_PARITY=1 python -m pytest tests/test_sentence_first_publish_config.py``.
"""
from __future__ import annotations

import copy
import dataclasses
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENTS = ROOT / "experiments" / "sentence-first-agent"
PAGES = EXPERIMENTS / "pages"


def load(name: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, EXPERIMENTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def shipped(page_id: str) -> dict:
    return json.loads((PAGES / f"{page_id}.json").read_text(encoding="utf-8"))


def tree_hashes(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*")) if path.is_file()}


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.publish = load("sfa_publish")

    def load_mutated(self, page_id: str, mutate):
        data = shipped(page_id)
        mutate(data)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "page.json"
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            return self.publish.load_config(path, root=ROOT)

    def assert_invalid(self, page_id: str, mutate, needle: str):
        with self.assertRaises(ValueError) as caught:
            self.load_mutated(page_id, mutate)
        self.assertIn(needle, str(caught.exception))

    def test_shipped_configs_load_with_the_expected_identity(self):
        episode = self.publish.load_config(PAGES / "if-i-had-more-time-jesus-promises.json")
        self.assertEqual(episode.page_id, "if-i-had-more-time-jesus-promises")
        self.assertEqual(episode.environment, "production")
        self.assertEqual(episode.origin(), "https://ai-for-god-sermon-audio.web.app")
        self.assertEqual(episode.locales, ("zh-Hans", "ko", "es"))
        self.assertEqual(episode.sentences, 946)
        clip = self.publish.load_config(PAGES / "sentence-first-clip-20261023.json")
        self.assertEqual(clip.environment, "dev")
        self.assertEqual(clip.origin(), "https://ai-for-god-sermon-audio-dev.web.app")
        self.assertEqual(clip.locales, ("zh-Hans", "ko"))
        self.assertEqual(clip.english_reference_mode, "clip")

    def test_unknown_key_is_rejected(self):
        self.assert_invalid("if-i-had-more-time-jesus-promises",
                            lambda data: data.update({"environmnet": "dev"}),
                            "environmnet")

    def test_misspelled_nested_key_is_rejected(self):
        self.assert_invalid("if-i-had-more-time-jesus-promises",
                            lambda data: data["source"].update({"englishSourc": "x"}),
                            "englishSourc")

    def test_meta_must_cover_exactly_the_locales(self):
        def mutate(data):
            data["meta"].pop("ko")
        self.assert_invalid("if-i-had-more-time-jesus-promises", mutate, "meta must cover exactly the locales")

    def test_release_template_must_include_the_environment(self):
        self.assert_invalid("if-i-had-more-time-jesus-promises",
                            lambda data: data.update({"releasePackageId": "{pageId}-{locale}-v1"}),
                            "environment")

    def test_translation_basis_must_cover_each_locale_or_a_default(self):
        def mutate(data):
            data["candidate"]["translationBasis"] = {"ko": "ko: x"}
        self.assert_invalid("if-i-had-more-time-jesus-promises", mutate, "translationBasis needs")

    def test_default_target_locale_must_be_a_locale(self):
        self.assert_invalid("if-i-had-more-time-jesus-promises",
                            lambda data: data.update({"defaultTargetLocale": "fr"}),
                            "defaultTargetLocale")

    def test_window_must_be_ordered(self):
        def mutate(data):
            data["source"]["window"] = {"start": 10.0, "end": 5.0}
        self.assert_invalid("if-i-had-more-time-jesus-promises", mutate, "window")

    def test_approved_candidate_mode_resolves_its_path(self):
        def mutate(data):
            data["candidate"]["approved"] = {
                "zh-Hans": "artifacts/podcasts/x/layer2/zh-Hans/candidate-approved.json"}
        cfg = self.load_mutated("if-i-had-more-time-jesus-promises", mutate)
        self.assertEqual(cfg.approved_candidates["zh-Hans"],
                         ROOT / "artifacts/podcasts/x/layer2/zh-Hans/candidate-approved.json")

    def test_approved_candidate_locale_must_be_a_locale(self):
        def mutate(data):
            data["candidate"]["approved"] = {"fr": "artifacts/x.json"}
        self.assert_invalid("if-i-had-more-time-jesus-promises", mutate, "approved locale")

    def test_environment_selects_the_hosting_origin(self):
        def mutate(data):
            data["environment"] = "dev"
        dev = self.load_mutated("if-i-had-more-time-jesus-promises", mutate)
        prod = self.publish.load_config(PAGES / "if-i-had-more-time-jesus-promises.json")
        self.assertEqual(dev.origin(), "https://ai-for-god-sermon-audio-dev.web.app")
        self.assertEqual(prod.origin(), "https://ai-for-god-sermon-audio.web.app")

    def test_voices_from_speakers_are_sorted_and_explicit_lists_kept(self):
        cfg = self.publish.load_config(PAGES / "sentence-first-clip-20261023.json")
        sentences = [{"speakerId": "steve_bang_lee"}, {"speakerId": "john_thomas"}, {"speakerId": "steve_bang_lee"}]
        self.assertEqual(cfg.voices_for(sentences), ["john_thomas", "steve_bang_lee"])
        explicit = dataclasses.replace(cfg, voices=("steve_bang_lee", "john_thomas"))
        self.assertEqual(explicit.voices_for(sentences), ["steve_bang_lee", "john_thomas"])

    def test_release_id_uses_the_page_locale_and_environment(self):
        cfg = self.publish.load_config(PAGES / "if-i-had-more-time-jesus-promises.json")
        self.assertEqual(cfg.release_id("ko"),
                         "if-i-had-more-time-jesus-promises-ko-production-v1")

    def test_validate_reports_a_missing_input_before_any_write(self):
        cfg = self.publish.load_config(PAGES / "if-i-had-more-time-jesus-promises.json")
        missing = dataclasses.replace(cfg, english_source_path=Path("/nonexistent/english-source.json"))
        with self.assertRaises(ValueError) as caught:
            self.publish.cmd_validate(missing)
        self.assertIn("English source package missing", str(caught.exception))

    def test_assets_refuses_an_existing_output_directory(self):
        cfg = self.publish.load_config(PAGES / "if-i-had-more-time-jesus-promises.json")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError) as caught:
                self.publish.cmd_assets(cfg, Path(tmp))
        self.assertIn("Use a new assets directory", str(caught.exception))


class AssetsParityTest(unittest.TestCase):
    """The migrated config must reproduce the legacy driver's bytes exactly."""

    CASES = (("publish_jesus_promises_page.py", "if-i-had-more-time-jesus-promises"),
             ("publish_clip_page_dev.py", "sentence-first-clip-20261023"))

    def test_legacy_and_config_driven_assets_match(self):
        if os.environ.get("SFA_PARITY") != "1":
            self.skipTest("set SFA_PARITY=1 (and keep the local artifacts) to run the byte-parity check")
        for driver, page_id in self.CASES:
            with self.subTest(page=page_id), tempfile.TemporaryDirectory() as tmp:
                if not (ROOT / "artifacts/sentence-first-agent" / shipped(page_id)["runs"]
                        [shipped(page_id)["locales"][0]]).is_dir():
                    self.skipTest("local run artifacts are missing")
                old, new = Path(tmp) / "old", Path(tmp) / "new"
                env = dict(os.environ, PYTHONPATH=os.pathsep.join(
                    [str(ROOT / "packages/production/src"), str(ROOT)]))
                subprocess.run([sys.executable, str(EXPERIMENTS / driver), "assets", "--out", str(old)],
                               cwd=ROOT, env=env, check=True, capture_output=True)
                subprocess.run([sys.executable, str(EXPERIMENTS / "sfa_publish.py"),
                                "--config", str(PAGES / f"{page_id}.json"), "assets", "--out", str(new)],
                               cwd=ROOT, check=True, capture_output=True)
                self.assertEqual(tree_hashes(old), tree_hashes(new))


if __name__ == "__main__":
    unittest.main()
