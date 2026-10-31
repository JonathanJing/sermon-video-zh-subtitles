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


class TitleTableTest(unittest.TestCase):
    def setUp(self):
        self.publish = load("sfa_publish")

    def test_parses_the_repository_title_table(self):
        table = self.publish.parse_title_table(ROOT / "docs/series-sermon-titles.zh.md")
        self.assertIn("revelation-comfort-and-hope", table)
        section = table["revelation-comfort-and-hope"]
        week6 = next(row for row in section["rows"] if row["week"] == 6)
        self.assertEqual(week6["english"], "Jesus sends and resurrects His own")
        self.assertEqual(week6["zh"], "耶稣差遣属祂的人，并使他们复活")
        self.assertEqual(week6["ko"], "예수님은 자기 백성을 보내시고 다시 살리십니다")
        self.assertEqual(section["differences"][6]["published"], "耶稣差遣并使属祂的人复活")

    def test_shipped_configs_pass_their_title_check(self):
        for page_id in ("if-i-had-more-time-jesus-promises", "sentence-first-clip-20261023"):
            with self.subTest(page=page_id):
                cfg = self.publish.load_config(PAGES / f"{page_id}.json")
                result = self.publish.cmd_check_title(cfg)
                self.assertTrue(result["ok"], result["problems"])
                self.assertEqual(result["expected"], result["actual"])
                self.assertEqual(result["mode"], "published")

    def _table_config(self, root: Path, mutate=None):
        table = root / "titles.zh.md"
        table.write_text("# 测试标题表\n\n## 测试系列（`test-series`）\n\n"
                         "| 周次 | 日期 | 英文原标题 | 经文 | 讲员 | 中文 | 韩文 | 西班牙语 |\n"
                         "|---|---|---|---|---|---|---|---|\n"
                         "| 1 | 2026-11-01 | Test episode | 约 1 | Tester | 测试标题 | 테스트 제목 | Título |\n",
                         encoding="utf-8")
        config = minimal_config(root)
        data = json.loads(config.read_text(encoding="utf-8"))
        data["meta"]["zh-Hans"] = {"title": "测试系列 · 测试标题", "series": "测试系列", "scripture": "约 1",
                                   "badge": "b", "source": "s", "note": "n"}
        data["title"] = "测试系列 · 测试标题"
        data["titleCheck"] = {"englishTitle": "Test episode", "mode": "table", "table": "titles.zh.md"}
        if mutate:
            mutate(data)
        config.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return self.publish.load_config(config, root=root)

    def test_table_mode_passes_when_the_page_titles_come_from_the_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._table_config(Path(tmp))
            result = self.publish.cmd_check_title(cfg)
            self.assertTrue(result["ok"], result["problems"])
            self.assertEqual(result["expected"]["zh-Hans"], "测试系列 · 测试标题")

    def test_table_mode_reports_a_title_that_was_not_taken_from_the_table(self):
        def mutate(data):
            data["meta"]["zh-Hans"]["title"] = "测试系列 · 自造标题"
            data["title"] = "测试系列 · 自造标题"
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._table_config(Path(tmp), mutate)
            result = self.publish.cmd_check_title(cfg)
            self.assertFalse(result["ok"])
            self.assertIn("自造标题", result["problems"][0]["detail"])

    def test_approved_exception_needs_a_reason_and_an_approver(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = minimal_config(root)
            data = json.loads(config.read_text(encoding="utf-8"))
            data["titleCheck"] = {"englishTitle": "Test episode", "mode": "approved_exception",
                                  "publishedTitles": {"zh-Hans": "测试页"}, "reason": "custom title",
                                  "table": "titles.zh.md"}
            config.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            cfg = self.publish.load_config(config, root=root)
            with self.assertRaises(ValueError) as caught:
                self.publish.cmd_check_title(cfg)
            self.assertIn("approvedBy", str(caught.exception))
            data["titleCheck"]["approvedBy"] = "user (chat, 2026-10-31)"
            config.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            cfg = self.publish.load_config(config, root=root)
            self.assertTrue(self.publish.cmd_check_title(cfg)["ok"])

    def test_unknown_english_title_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = minimal_config(root)
            data = json.loads(config.read_text(encoding="utf-8"))
            data["titleCheck"]["englishTitle"] = "No such episode"
            config.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            cfg = self.publish.load_config(config, root=root)
            with self.assertRaises(ValueError) as caught:
                self.publish.cmd_check_title(cfg)
            self.assertIn("matches 0 rows", str(caught.exception))

    def test_unknown_title_check_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = minimal_config(root)
            data = json.loads(config.read_text(encoding="utf-8"))
            data["titleCheck"]["tabel"] = "titles.zh.md"
            config.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(ValueError) as caught:
                self.publish.load_config(config, root=root)
            self.assertIn("tabel", str(caught.exception))

    def test_preflight_requires_a_title_check_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            minimal_inputs(root)
            config = minimal_config(root)
            data = json.loads(config.read_text(encoding="utf-8"))
            data.pop("titleCheck")
            config.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            cfg = self.publish.load_config(config, root=root)
            with self.assertRaises(ValueError) as caught:
                self.publish.cmd_preflight(cfg, allow_missing_decisions=True)
            self.assertIn("titleCheck", str(caught.exception))
            result = self.publish.cmd_preflight(cfg, allow_missing_decisions=True,
                                                allow_missing_title_check=True)
            self.assertTrue(result["ok"])
            self.assertIn("skipped", result["titleCheck"])


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

def minimal_config(root: Path, *, page_id: str = "test-page", locale: str = "zh-Hans",
                   english_source: Path | None = None, verdict: Path | None = None) -> Path:
    english_source = english_source or (root / "english-source.json")
    verdict = verdict or (root / "verdict.json")
    config = {
        "schemaVersion": "sentence-first-page-config-v1",
        "pageId": page_id,
        "environment": "dev",
        "locales": [locale],
        "defaultTargetLocale": locale,
        "runsRoot": "runs",
        "runs": {locale: "run"},
        "source": {"url": "https://example.test/sermon", "date": "2026-10-31",
                   "window": {"start": 0.0, "end": 10.0},
                   "englishSource": str(english_source.relative_to(root))},
        "sentences": 1,
        "speakers": "Tester",
        "category": {"schemaVersion": "sermon-page-display-category-v1", "labels": {"zh-Hans": "测试"}},
        "title": "测试页",
        "meta": {locale: {"title": "测试页", "series": "系列", "scripture": "经文",
                          "badge": "徽章", "source": "来源", "note": "备注"}},
        "verdict": str(verdict.relative_to(root)),
        "candidate": {"schemaVersion": "sentence-first-episode-candidate-v1",
                      "translationBasis": {"default": "{locale}: test"}},
        "audioPackage": {"schemaVersion": "sentence-first-episode-audio-package-v1",
                         "voices": "from-speakers", "synchronization": "test"},
        "releasePackageId": "{pageId}-{locale}-{environment}-v1",
        "verify": {"schemaVersion": "sentence-first-episode-http-verification-v1"},
        "englishReference": {"mode": "full"},
    }
    table = root / "titles.zh.md"
    if not table.exists():
        table.write_text("# 测试标题表\n\n## 测试系列（`test-series`）\n\n"
                         "| 周次 | 日期 | 英文原标题 | 经文 | 讲员 | 中文 | 韩文 | 西班牙语 |\n"
                         "|---|---|---|---|---|---|---|---|\n"
                         "| 1 | 2026-11-01 | Test episode | 约 1 | Tester | 测试页 | 테스트 | Prueba |\n",
                         encoding="utf-8")
    config["titleCheck"] = {"englishTitle": "Test episode", "mode": "published",
                            "publishedTitles": {locale: "测试页"}, "reason": "test fixture",
                            "table": "titles.zh.md"}
    path = root / "pages" / f"{page_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    return path


def minimal_inputs(root: Path, *, page_id: str = "test-page", locale: str = "zh-Hans") -> tuple[Path, Path]:
    """An english source package, a verdict and one run dir, enough for the publish preflight."""
    english = root / "english-source.json"
    english.write_text(json.dumps({
        "schemaVersion": "sermon-english-source-package-v1",
        "status": "ready_for_translation", "translationEligible": True,
        "source": {"sourceUrl": "https://example.test/sermon",
                   "sourceUrlHash": hashlib.sha256(b"https://example.test/sermon").hexdigest(),
                   "media": {"sha256": "a" * 64},
                   "approvedWindow": {"humanApproval": True, "status": "approved"}},
        "review": {"humanApproval": True},
    }), encoding="utf-8")
    run = root / "runs" / "run"
    (run / "tts").mkdir(parents=True)
    for name, text in (("sentences.jsonl", '{"id": "s0001", "sourceUnitId": "u1", "start": 0, "end": 1}\n'),
                       ("translations.jsonl", '{"id": "s0001", "target": "测试"}\n'),
                       ("speech.jsonl", '{"id": "s0001", "spokenText": "测试"}\n'),
                       ("schedule.json", '{"sentences": [{"id": "s0001", "actualStart": 0, "dubSeconds": 1}]}\n')):
        (run / name).write_text(text, encoding="utf-8")
    (run / "track.wav").write_bytes(b"RIFF-track")
    track_sha = hashlib.sha256(b"RIFF-track").hexdigest()
    verdict = root / "verdict.json"
    verdict.write_text(json.dumps({
        "schemaVersion": "sentence-first-human-review-verdict-v1", "pageId": page_id,
        "verdict": "approved", "reviewer": "tester", "reviewedAt": "2026-10-30T00:00:00+00:00",
        "locales": {locale: {"trackWavSha256": track_sha, "trackSeconds": 1.0}},
    }), encoding="utf-8")
    return english, verdict


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json_sha(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def make_publish_snapshot(root: Path, *, page_id: str = "test-page", locale: str = "zh-Hans",
                          english_sha: str, release_status: str = "published_http_verified",
                          english_reference: bool = True, announcement_release_sha: str | None = None,
                          cue_text: str = "x") -> Path:
    public = root / "public"
    content_bytes = json.dumps({"pageId": page_id, "locale": locale, "targetLocale": locale,
                                "status": "human_reviewed", "durationSeconds": 10.0,
                                "englishSourcePackageJsonSha256": english_sha,
                                "targetLanguageCandidateJsonSha256": "c" * 64,
                                "cues": [{"start": 0, "end": 1, "sourceUnitIds": ["u1"],
                                          "text": cue_text, "textGroupId": "t1"}]}, ensure_ascii=False).encode()
    captions_bytes = json.dumps({"pageId": page_id, "locale": locale, "audioPackageJsonSha256": "d" * 64,
                                 "cues": [{"start": 0, "end": 1, "sourceUnitIds": ["u1"],
                                           "text": cue_text, "textGroupId": "t1"}]}, ensure_ascii=False).encode()
    page_bytes = b"<html>page</html>"
    audio_bytes = b"mp3-bytes"
    paths = {"page": f"/pages/{page_id}/{locale}/index.html",
             "content": f"/content/{page_id}/{locale}.json",
             "captions": f"/captions/{page_id}/{locale}.json",
             "audio": f"/media/{page_id}/{locale}.mp3"}
    payloads = {"page": page_bytes, "content": content_bytes, "captions": captions_bytes, "audio": audio_bytes}
    assets = []
    for role, path in paths.items():
        target = public / path.lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payloads[role])
        assets.append({"role": role, "path": path, "sha256": sha256_bytes(payloads[role])})
    release = {"pageId": page_id, "targetLocale": locale, "status": release_status,
               "targetLanguageCandidateJsonSha256": "c" * 64,
               "targetLanguageAudioPackageJsonSha256": "d" * 64, "assets": assets}
    release_path = public / "releases-v2" / page_id / f"{locale}.json"
    release_path.parent.mkdir(parents=True, exist_ok=True)
    release_path.write_bytes(json.dumps(release, ensure_ascii=False).encode())
    release_sha = sha256_bytes(release_path.read_bytes())
    catalog = {"schemaVersion": "sermon-multilingual-catalog-v3", "pages": [{
        "id": page_id, "sourceIdentitySha256": english_sha,
        "targets": {locale: {"releasePackageUrl": f"/releases-v2/{page_id}/{locale}.json",
                             "releasePackageJsonSha256": release_sha}}}]}
    (public / "multilingual-v3.json").write_text(json.dumps(catalog), encoding="utf-8")
    if english_reference:
        reference = {"pageId": page_id, "targets": {locale: {
            "contentSha256": sha256_bytes(content_bytes), "captionsSha256": sha256_bytes(captions_bytes),
            "releasePackageJsonSha256": release_sha,
            "blocks": [{"textGroupId": "t1", "sourceUnitIds": ["u1"], "english": cue_text}]}}}
        ref_path = public / "english-reference" / f"{page_id}.json"
        ref_path.parent.mkdir(parents=True, exist_ok=True)
        ref_path.write_text(json.dumps(reference), encoding="utf-8")
    announcements = {"schemaVersion": "tongxing-weekly-announcements-v1", "announcements": [
        {"pageID": page_id, "locale": locale,
         "releaseSHA256": announcement_release_sha or release_sha, "sourceIdentitySHA256": english_sha}]}
    (public / "weekly-announcements-v1.json").write_text(json.dumps(announcements), encoding="utf-8")
    return root


class PublishGateTest(unittest.TestCase):
    def setUp(self):
        self.publish = load("sfa_publish")

    def test_preflight_passes_with_complete_inputs_and_decisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _ = minimal_inputs(root)
            config = minimal_config(root)
            run = root / "runs" / "run"
            (run / "decisions.json").write_text(json.dumps({
                "schemaVersion": "sentence-first-frozen-decisions-v1", "locales": ["zh-Hans"],
                "sync": False, "publish": True, "title": "测试页", "form": "clip"}), encoding="utf-8")
            cfg = self.publish.load_config(config, root=root)
            result = self.publish.cmd_preflight(cfg)
            self.assertTrue(result["ok"])
            self.assertEqual(result["decisions"]["zh-Hans"]["title"], "测试页")

    def test_preflight_fails_on_a_track_that_changed_after_the_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            minimal_inputs(root)
            cfg = self.publish.load_config(minimal_config(root), root=root)
            (root / "runs/run/track.wav").write_bytes(b"changed-after-review")
            with self.assertRaises(ValueError) as caught:
                self.publish.cmd_preflight(cfg, allow_missing_decisions=True)
            self.assertIn("changed after the review", str(caught.exception))

    def test_publish_check_passes_on_a_consistent_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            english, _ = minimal_inputs(root)
            cfg = self.publish.load_config(minimal_config(root), root=root)
            english_sha = canonical_json_sha(json.loads(english.read_text(encoding="utf-8")))
            snapshot = make_publish_snapshot(root / "snap", english_sha=english_sha)
            result = self.publish.cmd_publish_check(cfg, snapshot, require_english_reference=True,
                                                    require_announcements=True)
            self.assertTrue(result["ok"])
            self.assertEqual(result["problems"], [])
            self.assertEqual(result["checked"]["englishReference"]["locales"], ["zh-Hans"])

    def test_publish_check_rejects_a_reference_that_binds_older_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            english, _ = minimal_inputs(root)
            cfg = self.publish.load_config(minimal_config(root), root=root)
            english_sha = canonical_json_sha(json.loads(english.read_text(encoding="utf-8")))
            snapshot = make_publish_snapshot(root / "snap", english_sha=english_sha)
            reference = snapshot / "public/english-reference/test-page.json"
            data = json.loads(reference.read_text())
            data["targets"]["zh-Hans"]["contentSha256"] = "0" * 64
            reference.write_text(json.dumps(data), encoding="utf-8")
            result = self.publish.cmd_publish_check(cfg, snapshot)
            self.assertFalse(result["ok"])
            self.assertTrue(any("older content" in problem["detail"] for problem in result["problems"]))

    def test_publish_check_detects_a_stale_announcement_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            english, _ = minimal_inputs(root)
            cfg = self.publish.load_config(minimal_config(root), root=root)
            old_snapshot = make_publish_snapshot(root / "old", english_sha="0" * 64, cue_text="old")
            old_release = hashlib.sha256((old_snapshot / "public/releases-v2/test-page/zh-Hans.json").read_bytes()).hexdigest()
            current = make_publish_snapshot(root / "new", english_sha="0" * 64,
                                            announcement_release_sha=old_release, cue_text="new")
            result = self.publish.cmd_publish_check(cfg, current, baseline=old_snapshot)
            self.assertFalse(result["ok"])
            self.assertTrue(any("announcement binds an older release" in problem["detail"]
                                for problem in result["problems"]))
            self.assertTrue(result["staleReferences"])
            self.assertTrue(any(item["path"].endswith("weekly-announcements-v1.json")
                                for item in result["staleReferences"]))

    def test_publish_check_requires_the_english_reference_when_asked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            english, _ = minimal_inputs(root)
            cfg = self.publish.load_config(minimal_config(root), root=root)
            snapshot = make_publish_snapshot(root / "snap", english_sha="0" * 64, english_reference=False)
            result = self.publish.cmd_publish_check(cfg, snapshot, require_english_reference=True)
            self.assertFalse(result["ok"])
            self.assertTrue(any("required but missing" in problem["detail"] for problem in result["problems"]))


if __name__ == "__main__":
    unittest.main()
