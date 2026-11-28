#!/usr/bin/env python3
"""Focused tests for the WhisperX timeline A/B experiment helpers."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / "experiments" / "whisperx-timeline-ab"


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, EXPERIMENT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class PrepareCaseTests(unittest.TestCase):
    def test_gap_splits_chunks_and_keeps_word_sources(self):
        prepare = load("prepare_case")
        manifest = {
            "input": {"date": "2026-11-08", "sourceUrl": "https://example.test/source"},
            "policy": {"unitPolicy": "test"},
            "sourceUnits": [
                {"sourceUnitId": "u1", "english": "Hello.", "start": 0.0, "end": 1.0,
                 "words": [{"text": "Hello.", "start": 0.0, "end": 1.0}]},
                {"sourceUnitId": "u2", "english": "World.", "start": 5.0, "end": 6.0,
                 "words": [{"text": "World.", "start": 5.0, "end": 6.0}]},
                {"sourceUnitId": "u3", "english": "Again.", "start": 6.2, "end": 7.0,
                 "words": [{"text": "Again.", "start": 6.2, "end": 7.0}]},
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "raw.json"
            raw.write_text(json.dumps({
                "text": "Hello. World. Again.",
                "words": [{"word": "Hello.", "start": 0.0, "end": 1.0},
                          {"word": "World.", "start": 5.0, "end": 6.0},
                          {"word": "Again.", "start": 6.2, "end": 7.0}],
            }))
            case = prepare.build_case(manifest, 10.0, raw, 18.0, 24.0, 1.0, 1)
        self.assertEqual(case["counts"]["words"], 3)
        self.assertEqual(case["counts"]["whisperMatchedWords"], 3)
        self.assertEqual(case["counts"]["syntheticWords"], 0)
        self.assertGreaterEqual(case["counts"]["chunks"], 2)
        self.assertTrue(all(chunk["start"] < chunk["end"] for chunk in case["chunks"]))

    def test_zero_duration_word_is_preserved_not_repaired(self):
        prepare = load("prepare_case")
        manifest = {
            "input": {"date": "2026-11-08"},
            "sourceUnits": [
                {"sourceUnitId": "u1", "english": "justice.", "start": 1.0, "end": 1.0,
                 "words": [{"text": "justice.", "start": 1.0, "end": 1.0}]},
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "raw.json"
            raw.write_text(json.dumps({"text": "justice.", "words": [
                {"word": "justice.", "start": 1.0, "end": 1.0}]}))
            case = prepare.build_case(manifest, 2.0, raw, 18.0, 24.0, 1.0, 1)
        self.assertEqual(case["counts"]["zeroDurationWords"], 1)
        self.assertEqual(case["tokens"][0]["start"], case["tokens"][0]["end"])


class ScoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.score = load("score_ab")

    def test_levenshtein_substitution(self):
        result = self.score.levenshtein_counts(["a", "b", "c"], ["a", "x", "c"])
        self.assertEqual(result["substitutions"], 1)
        self.assertEqual(result["deletions"], 0)
        self.assertEqual(result["insertions"], 0)
        self.assertEqual(result["distance"], 1)
        self.assertAlmostEqual(result["wer"], 1 / 3, places=5)

    def test_levenshtein_deletion_and_insertion(self):
        deletion = self.score.levenshtein_counts(["a", "b"], ["a"])
        self.assertEqual(deletion["deletions"], 1)
        insertion = self.score.levenshtein_counts(["a"], ["a", "b"])
        self.assertEqual(insertion["insertions"], 1)

    def test_structure_counts_zero_and_overlap(self):
        times = {
            0: {"start": 0.0, "end": 0.0},
            1: {"start": 0.5, "end": 1.0},
            2: {"start": 0.9, "end": 1.4},
        }
        result = self.score.structure(times, 2.0, 3)
        self.assertEqual(result["zeroOrNegativeDuration"], 1)
        self.assertEqual(result["overlappingAdjacentPairs"], 1)
        self.assertEqual(result["presentWords"], 3)


if __name__ == "__main__":
    unittest.main()
