#!/usr/bin/env python3
"""Tests for the production WhisperX timeline revision producer."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "production" / "src"))
from tongxing_production.source import whisperx_timeline as timeline  # noqa: E402


def load_sfa():
    import importlib.util
    path = ROOT / "experiments" / "sentence-first-agent" / "sfa.py"
    spec = importlib.util.spec_from_file_location("sfa_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_fixture(root: Path) -> tuple[Path, Path, Path]:
    media = root / "media.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
                    "-t", "3", "-c:a", "pcm_s16le", str(media)], check=True)
    units = [
        {"sourceUnitId": "u0001", "english": "Hello.", "start": 0.0, "end": 1.0,
         "boundary": {"pauseAfterSeconds": 0.2, "clauseComplete": True},
         "words": [{"text": "Hello.", "start": 0.0, "end": 1.0}]},
        {"sourceUnitId": "u0002", "english": "World.", "start": 1.2, "end": 2.2,
         "boundary": {"pauseAfterSeconds": 0.8, "clauseComplete": True},
         "words": [{"text": "World.", "start": 1.2, "end": 2.2}]},
    ]
    manifest = {
        "schemaVersion": "sermon-sentence-anchor-manifest-v2",
        "status": "machine_anchor_candidate_requires_review", "releaseEligible": False,
        "humanReview": {"englishTranscriptCompleteness": "pending",
                        "sentenceAndPauseBoundaries": "pending"},
        "policy": {"unitPolicy": "clause_stable_v3"},
        "input": {"date": "2026-11-08", "mediaSha256": sha(media), "mediaDurationSeconds": 3.0},
        "counts": {"sourceUnits": 2, "sourceWords": 2}, "sourceUnits": units,
    }
    manifest_path = root / "anchor-manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    package = {
        "schemaVersion": "sermon-english-source-package-v1",
        "status": "ready_for_translation", "translationEligible": True,
        "source": {
            "sourceUrl": "https://example.test/source", "sourceUrlHash": "0" * 64,
            "date": "2026-11-08",
            "approvedWindow": {"schemaVersion": "sermon-source-window-approval-v1",
                               "humanApproval": True, "status": "approved", "start": 0.0, "end": 3.0},
            "media": {"sha256": sha(media), "durationSeconds": 3.0, "file": str(media.resolve())},
        },
        "transcript": {"model": "whisper-1", "textModel": "gpt-4o-transcribe",
                       "artifact": {"path": str(manifest_path.resolve()), "sha256": sha(manifest_path)}},
        "anchors": {"artifact": {"path": str(manifest_path.resolve()), "sha256": sha(manifest_path)},
                    "sourceUnitCount": 2, "policy": {"unitPolicy": "clause_stable_v3"}},
        "units": [{"sourceUnitId": unit["sourceUnitId"], "english": unit["english"],
                   "start": unit["start"], "end": unit["end"],
                   "pauseAfterSeconds": unit["boundary"]["pauseAfterSeconds"]} for unit in units],
        "review": {"schemaVersion": "sermon-english-source-review-v1", "humanApproval": True,
                   "reviewer": "test", "reviewedAt": "2026-11-08T04:02:23+00:00",
                   "checks": {"sourceIdentity": "approved", "transcriptCompleteness": "approved",
                              "wordAlignment": "approved", "sentenceAndPauseBoundaries": "approved"},
                   "reviewedSourceUnitIds": ["u0001", "u0002"]},
        "evidence": [],
    }
    package_path = root / "english-source.json"
    package_path.write_text(json.dumps(package, ensure_ascii=False), encoding="utf-8")
    return media, manifest_path, package_path


def fake_runtime(root: Path, *, mode: str = "ok") -> Path:
    script = root / f"fake-{mode}.py"
    body = f'''import argparse, json
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument("--request", type=Path); p.add_argument("--out", type=Path)
p.add_argument("--device"); p.add_argument("--language"); p.add_argument("--align-model")
a = p.parse_args(); request = json.loads(a.request.read_text())
mode = {mode!r}
chunks = []
t = 0.1
for chunk in request["chunks"]:
    chunk_words = []
    for position, token in enumerate(chunk["text"].split()):
        start, end = t, t + 0.8
        if mode == "missing" and position == 0:
            t += 1.0
            continue
        if mode == "zero":
            end = start
        if mode == "backwards":
            start, end = 2.0, 2.5
        chunk_words.append({{"text": token, "start": round(start, 3), "end": round(end, 3)}})
        t += 1.0
    chunks.append({{"id": chunk["id"], "words": chunk_words}})
out = {{"schemaVersion": "sermon-whisperx-alignment-result-v1",
       "model": {{"whisperxVersion": "fake", "alignmentModel": "fake"}},
       "elapsedSeconds": 0.01, "attemptCounts": {{"chunk_exact": len(request["chunks"])}},
       "chunks": chunks}}
a.out.write_text(json.dumps(out))
'''
    script.write_text(body, encoding="utf-8")
    return script


class TimelineTests(unittest.TestCase):
    def setUp(self):
        if shutil.which("ffmpeg") is None:
            self.skipTest("ffmpeg is required")
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.media, self.manifest, self.package = make_fixture(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def run_tool(self, *args: str) -> int:
        return timeline.main([
            "--english-source", str(self.package), "--out", str(self.root / "out"),
            "--runtime-python", sys.executable, "--adapter", str(fake_runtime(self.root)),
            "--no-review-snippets", *args,
        ])

    def test_candidate_preserves_text_and_updates_time(self):
        self.assertEqual(self.run_tool(), 0)
        out = self.root / "out"
        manifest = json.loads((out / "anchor-manifest.json").read_text())
        package = json.loads((out / "english-source.json").read_text())
        self.assertEqual([unit["english"] for unit in manifest["sourceUnits"]], ["Hello.", "World."])
        self.assertEqual([unit["sourceUnitId"] for unit in manifest["sourceUnits"]], ["u0001", "u0002"])
        self.assertEqual(manifest["sourceUnits"][0]["start"], 0.1)
        self.assertEqual(package["status"], "machine_candidate_requires_review")
        self.assertFalse(package["translationEligible"])
        self.assertFalse(package["review"]["humanApproval"])
        self.assertEqual(package["anchors"]["artifact"]["sha256"], sha(out / "anchor-manifest.json"))
        self.assertEqual(package["transcript"]["artifact"]["sha256"], sha(out / "whisperx-words.json"))

    def test_check_and_approve(self):
        self.assertEqual(self.run_tool(), 0)
        out = self.root / "out"
        self.assertEqual(timeline.main(["--out", str(out), "--check"]), 0)
        self.assertEqual(timeline.main([
            "--out", str(out), "--approve", "Tester", "--approved-at", "2026-11-28T06:00:00+00:00",
        ]), 0)
        approved = json.loads((out / "english-source.approved.json").read_text())
        self.assertEqual(approved["status"], "ready_for_translation")
        self.assertTrue(approved["translationEligible"])
        self.assertTrue(approved["review"]["humanApproval"])
        self.assertEqual(approved["review"]["reviewer"], "Tester")
        self.assertEqual(timeline.main(["--out", str(out), "--check"]), 0)

    def test_check_detects_tamper(self):
        self.assertEqual(self.run_tool(), 0)
        out = self.root / "out"
        manifest = json.loads((out / "anchor-manifest.json").read_text())
        manifest["sourceUnits"][0]["end"] += 0.01
        (out / "anchor-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        self.assertEqual(timeline.main(["--out", str(out), "--check"]), 1)

    def test_missing_word_fails_closed(self):
        with self.assertRaises(timeline.TimelineError) as caught:
            self.run_tool_with_mode("missing")
        self.assertEqual(caught.exception.code, "alignment_token_count_mismatch")

    def test_zero_duration_fails_closed(self):
        with self.assertRaises(timeline.TimelineError) as caught:
            self.run_tool_with_mode("zero")
        self.assertEqual(caught.exception.code, "alignment_time_out_of_bounds")

    def test_non_monotonic_fails_closed(self):
        with self.assertRaises(timeline.TimelineError) as caught:
            self.run_tool_with_mode("backwards")
        self.assertEqual(caught.exception.code, "alignment_non_monotonic")

    def run_tool_with_mode(self, mode: str) -> int:
        return timeline.main([
            "--english-source", str(self.package), "--out", str(self.root / f"out-{mode}"),
            "--runtime-python", sys.executable, "--adapter", str(fake_runtime(self.root, mode=mode)),
            "--no-review-snippets",
        ])

    def test_sfa_refuses_candidate_and_accepts_approved_package(self):
        self.assertEqual(self.run_tool(), 0)
        sfa = load_sfa()
        class Args:
            timeline_package = self.root / "out" / "english-source.json"
            window_start = None
            anchor = None
            media = None
            english_package = None
            margin_before = 1.0
            margin_after = 8.0
        with self.assertRaises(sfa.SetupError):
            sfa.apply_timeline_package(Args())
        self.assertEqual(timeline.main([
            "--out", str(self.root / "out"), "--approve", "Tester",
            "--approved-at", "2026-11-28T06:00:00+00:00",
        ]), 0)
        args = Args()
        args.timeline_package = self.root / "out" / "english-source.approved.json"
        sfa.apply_timeline_package(args)
        self.assertEqual(args.english_package, (self.root / "out" / "english-source.approved.json").resolve())
        self.assertEqual(args.window_start, 0.0)
        self.assertTrue(args.anchor.is_file())
        self.assertTrue(args.media.is_file())
        self.assertAlmostEqual(args.margin_before, 0.1)
        self.assertAlmostEqual(args.margin_after, 1.1)

    def test_default_timeline_resolution(self):
        sfa = load_sfa()
        from unittest.mock import patch
        parent = self.root / "layer1"
        parent.mkdir()
        package = parent / "english-source.json"
        package.write_text(json.dumps({"transcript": {"model": "openai"}}), encoding="utf-8")
        approved = self.root / "layer1-whisperx" / "english-source.approved.json"
        approved.parent.mkdir()
        approved.write_text("{}", encoding="utf-8")

        class Args:
            timeline_package = None
            allow_parent_timeline = False
            english_package = package
            anchor = None
            media = None
            window_start = None

        args = Args()
        with patch.object(sfa, "apply_timeline_package") as apply:
            sfa.resolve_timeline_package(args)
            self.assertEqual(args.timeline_package, approved)
            self.assertEqual(args.timeline_source, "default_sibling")
            apply.assert_called_once_with(args)

        missing = Args()
        missing.english_package = self.root / "other" / "english-source.json"
        missing.english_package.parent.mkdir()
        missing.english_package.write_text(json.dumps({"transcript": {"model": "openai"}}), encoding="utf-8")
        with self.assertRaises(sfa.SetupError):
            sfa.resolve_timeline_package(missing)

        parent_args = Args()
        parent_args.allow_parent_timeline = True
        parent_args.anchor = self.root / "parent-anchor.json"
        parent_args.media = self.root / "parent-media.mp4"
        parent_args.window_start = 0.0
        with patch.object(sfa, "apply_timeline_package") as apply:
            sfa.resolve_timeline_package(parent_args)
            self.assertEqual(parent_args.timeline_source, "parent_explicit")
            apply.assert_not_called()

        parent_package = Args()
        parent_package.allow_parent_timeline = True
        with patch.object(sfa, "apply_timeline_package") as apply:
            sfa.resolve_timeline_package(parent_package)
            self.assertEqual(parent_package.timeline_source, "parent_explicit")
            apply.assert_called_once_with(parent_package)

        explicit = Args()
        explicit.timeline_package = approved
        with patch.object(sfa, "apply_timeline_package") as apply:
            sfa.resolve_timeline_package(explicit)
            self.assertEqual(explicit.timeline_source, "explicit")
            apply.assert_called_once_with(explicit)

        both = Args()
        both.timeline_package = approved
        both.allow_parent_timeline = True
        with self.assertRaises(sfa.SetupError):
            sfa.resolve_timeline_package(both)

    def test_build_chunks_breaks_at_gap(self):
        units = [
            {"sourceUnitId": "u1", "english": "A.", "start": 0.0, "end": 1.0,
             "words": [{"text": "A.", "start": 0.0, "end": 1.0}]},
            {"sourceUnitId": "u2", "english": "B.", "start": 5.0, "end": 6.0,
             "words": [{"text": "B.", "start": 5.0, "end": 6.0}]},
        ]
        chunks = timeline.build_chunks(units, gap_seconds=1.0)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0]["text"], "A.")
        self.assertEqual(chunks[1]["text"], "B.")


if __name__ == "__main__":
    unittest.main()
