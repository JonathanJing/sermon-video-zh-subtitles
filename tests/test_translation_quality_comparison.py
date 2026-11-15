"""Tests for the blinded translation quality comparison experiment."""

from __future__ import annotations

import csv
import importlib.util
import json
import sys
import tempfile
import unittest
from argparse import Namespace
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "experiments" / "translation-quality-comparison" / "compare.py"


def load_module():
    spec = importlib.util.spec_from_file_location("translation_quality_compare_under_test", SPEC)
    module = importlib.util.module_from_spec(spec)
    sys.modules["translation_quality_compare_under_test"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


compare = load_module()


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.capture = self.root / "capture"
        self.ours = self.root / "ours"
        self.capture.mkdir()
        self.ours.mkdir()
        self.start = datetime(2026, 11, 15, 18, 0, tzinfo=timezone.utc)
        self.stop = datetime(2026, 11, 15, 19, 0, tzinfo=timezone.utc)
        self.window_start = datetime(2026, 11, 15, 18, 10, tzinfo=timezone.utc)
        self.window_end = datetime(2026, 11, 15, 18, 20, tzinfo=timezone.utc)
        (self.capture / "capture.json").write_text(
            json.dumps(
                {
                    "schema": "live-translate-capture/v1",
                    "window": {"actual_start": iso(self.start), "actual_stop": iso(self.stop)},
                    "host": {"timezone": "America/Los_Angeles"},
                }
            ),
            encoding="utf-8",
        )
        capture_hash = compare.sha256_file(self.capture / "capture.json")
        (self.capture / "sermon.window.json").write_text(
            json.dumps(
                {
                    "schema": "live-translate-sermon-window/v1",
                    "capture": {"manifest_sha256": capture_hash},
                    "sermon_window": {"start": iso(self.window_start), "end": iso(self.window_end)},
                }
            ),
            encoding="utf-8",
        )
        english = []
        for index in range(20):
            english.append(
                {
                    "ts": iso(self.window_start + timedelta(seconds=30 * index)),
                    "text": f"Sentence {index + 1} explains chapter {index + 1}:3 and the number {100 + index}.",
                }
            )
        pastors = []
        for index in range(10):
            pastors.append(
                {
                    "ts": iso(self.window_start + timedelta(seconds=60 * index + 45)),
                    "text": f"第{index + 1}段中文，提到第{index + 1}:3章和数字{100 + index}。",
                }
            )
        write_jsonl(self.capture / "session.english.jsonl", english)
        write_jsonl(self.capture / "session.mandarin.jsonl", pastors)
        segments = [
            {
                "id": index,
                "start": 60 * index,
                "end": 60 * (index + 1),
                "text": f"English segment {index + 1}",
                "zh": f"我们的第{index + 1}段译文，提到第{index + 1}:3章和数字{100 + index}。",
            }
            for index in range(10)
        ]
        (self.ours / "segments_timed_zh.json").write_text(
            json.dumps(segments, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        self.prepare_args = Namespace(
            capture_dir=self.capture,
            ours_dir=self.ours,
            ours="layer2",
            outdir=self.root / "out",
            unit_seconds=60.0,
            unit_max_chars=400,
            sample_size=6,
            seed=7,
            raters=2,
            allow_medium=False,
        )

    def tearDown(self):
        self.temp.cleanup()

    def fill_ratings(self, outdir: Path, *, ours_wins: bool = True) -> None:
        sample = json.loads((outdir / "sample.json").read_text(encoding="utf-8"))
        for rater in (1, 2):
            path = outdir / f"ratings.rater{rater}.csv"
            with path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            for row in rows:
                item = next(entry for entry in sample["units"] if entry["unit_id"] == row["unit_id"])
                ours_first = item["order"] == "ours_first"
                ours_high = ours_wins
                row.update(
                    {
                        "a_adequacy": "5" if (ours_first == ours_high) else "3",
                        "a_fluency": "5" if (ours_first == ours_high) else "3",
                        "b_adequacy": "3" if (ours_first == ours_high) else "5",
                        "b_fluency": "3" if (ours_first == ours_high) else "5",
                        "preference": "A" if ours_first else "B",
                        "critical_a": "0",
                        "major_a": "0",
                        "minor_a": "0",
                        "critical_b": "0",
                        "major_b": "0",
                        "minor_b": "0",
                    }
                )
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)

    def test_prepare_builds_alignment_sample_and_blind_sheets(self):
        result = compare.prepare(self.prepare_args)
        self.assertEqual(result["counts"]["sampled"], 6)
        self.assertTrue((self.root / "out" / "alignment.jsonl").exists())
        self.assertTrue((self.root / "out" / "sample.json").exists())
        self.assertTrue((self.root / "out" / "review.packet.md").exists())
        with (self.root / "out" / "ratings.rater1.csv").open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 6)
        self.assertEqual(set(rows[0]), set(compare.RATING_COLUMNS))
        self.assertTrue(all(not row["preference"] for row in rows))
        packet = (self.root / "out" / "review.packet.md").read_text(encoding="utf-8")
        self.assertNotIn("pastors_first", packet)
        self.assertNotIn("ours_first", packet)

    def test_score_with_consistent_ratings(self):
        compare.prepare(self.prepare_args)
        self.fill_ratings(self.root / "out")
        summary = compare.score(Namespace(outdir=self.root / "out", ratings=None, bootstrap=200, seed=7))
        self.assertEqual(summary["preference"]["counts"]["ours"], 6)
        self.assertEqual(summary["preference"]["ours_win_rate"], 1.0)
        self.assertEqual(summary["scores"]["adequacy"]["difference_mean"], 2.0)
        self.assertEqual(summary["inter_rater"]["preference_agreement_rate"], 1.0)
        self.assertTrue((self.root / "out" / "report.md").exists())

    def test_disagreement_is_marked_disputed(self):
        compare.prepare(self.prepare_args)
        self.fill_ratings(self.root / "out")
        path = self.root / "out" / "ratings.rater2.csv"
        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        # Flip the first rater-2 preference while keeping its scores; this is a
        # deliberate disagreement used to test consensus, not a valid review.
        rows[0]["preference"] = "B" if rows[0]["preference"] == "A" else "A"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        summary = compare.score(Namespace(outdir=self.root / "out", ratings=None, bootstrap=200, seed=7))
        self.assertGreaterEqual(summary["preference"]["counts"]["disputed"], 1)

    def test_reading_candidate_is_supported(self):
        reading_dir = self.ours / "reading-edition-v2"
        reading_dir.mkdir()
        blocks = [
            {
                "id": index,
                "start": 60 * index,
                "end": 60 * (index + 1),
                "en": f"English block {index + 1}",
                "zh": f"阅读版第{index + 1}段，提到第{index + 1}:3章和数字{100 + index}。",
            }
            for index in range(10)
        ]
        (reading_dir / "reading_blocks.final.json").write_text(
            json.dumps(blocks, ensure_ascii=False), encoding="utf-8"
        )
        args = Namespace(**{**vars(self.prepare_args), "ours": "reading", "outdir": self.root / "reading-out"})
        compare.prepare(args)
        first = json.loads((self.root / "reading-out" / "alignment.jsonl").read_text(encoding="utf-8").splitlines()[0])
        self.assertIn("阅读版", first["ours_zh"])

    def test_low_confidence_unit_is_excluded_from_sampling(self):
        pastors = [json.loads(line) for line in (self.capture / "session.mandarin.jsonl").read_text(encoding="utf-8").splitlines()]
        write_jsonl(self.capture / "session.mandarin.jsonl", pastors[1:])
        args = Namespace(**{**vars(self.prepare_args), "outdir": self.root / "low-out"})
        compare.prepare(args)
        alignment = [json.loads(line) for line in (self.root / "low-out" / "alignment.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertTrue(any(unit["confidence"] == "low" for unit in alignment))
        sample = json.loads((self.root / "low-out" / "sample.json").read_text(encoding="utf-8"))
        sampled_ids = {unit["unit_id"] for unit in sample["units"]}
        self.assertFalse({unit["unit_id"] for unit in alignment if unit["confidence"] == "low"} & sampled_ids)

    def test_unbound_window_is_rejected(self):
        (self.capture / "capture.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(ValueError):
            compare.prepare(self.prepare_args)


if __name__ == "__main__":
    unittest.main()
