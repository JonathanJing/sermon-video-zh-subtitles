import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "experiments" / "sentence-first-agent"))

import coherence_core as C  # noqa: E402


def write_events(run: Path, rows: list[dict]) -> None:
    (run / "events.jsonl").write_text(
        "".join(json.dumps({"label": "translate", "model": "deepseek-flash", "effort": "low", **row}) + "\n"
                for row in rows), encoding="utf-8")


def write_done(run: Path, windows: list[list[str]]) -> None:
    (run / "done.jsonl").write_text(
        "".join(json.dumps({"label": "translate", "context": f"w{number}",
                            "ids": ids}) + "\n" for number, ids in enumerate(windows)), encoding="utf-8")


class RebuildStateTest(unittest.TestCase):
    def test_counts_match_the_event_stream(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            write_events(run, [
                {"status": "ok", "attempt": 1, "promptTokens": 1000, "completionTokens": 2000},
                {"status": "ok", "attempt": 1, "promptTokens": 1000, "completionTokens": 2000},
                {"status": "hit"},
                {"status": "validation_failed", "failures": ["s1: empty target"]},
                {"status": "finished"},
            ])
            write_done(run, [["s1", "s2"], ["s3"], ["s4"]])
            state = C.rebuild_state(run)
            self.assertEqual(state["calls"], 2)
            self.assertEqual(state["hits"], 1)
            self.assertEqual(state["done"], 3)
            self.assertEqual(state["windowsDone"], 3)
            self.assertEqual(state["unitsDone"], 4)
            self.assertEqual(state["validationFailures"], 1)
            self.assertEqual(state["status"], "finished")
            self.assertAlmostEqual(state["costUsd"], 0.0054, places=4)

    def test_mismatch_is_reported_and_repairable(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            write_events(run, [{"status": "ok", "promptTokens": 10, "completionTokens": 10},
                               {"status": "finished"}])
            write_done(run, [["s1"]])
            rebuilt = C.rebuild_state(run)
            live = {**rebuilt, "windowsDone": 9, "unitsDone": 99}
            mismatches = C.state_mismatches(live, rebuilt)
            self.assertEqual(len(mismatches), 2)
            self.assertTrue(all("windowsDone" in line or "unitsDone" in line for line in mismatches))
            (run / "state-translate.json").write_text(json.dumps(live), encoding="utf-8")
            (run / "state-translate.json").write_text(json.dumps(rebuilt), encoding="utf-8")
            self.assertEqual(C.state_mismatches(json.loads((run / "state-translate.json").read_text()),
                                                C.rebuild_state(run)), [])

    def test_repair_entries_do_not_inflate_windows(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            write_events(run, [{"status": "ok", "promptTokens": 1, "completionTokens": 1},
                               {"status": "finished"}])
            (run / "done.jsonl").write_text(
                json.dumps({"label": "translate", "context": "w0", "kind": "window",
                            "ids": ["s1", "s2"]}) + "\n"
                + json.dumps({"label": "translate", "context": "repair:s3", "kind": "repair",
                              "ids": ["s3"]}) + "\n", encoding="utf-8")
            state = C.rebuild_state(run)
            self.assertEqual(state["windowsDone"], 1)
            self.assertEqual(state["unitsDone"], 3)

    def test_missing_units_lists_uncovered_sentences(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            (run / "sentences.jsonl").write_text(
                "".join(json.dumps({"id": f"s{number}", "english": "x"}) + "\n" for number in (1, 2, 3)),
                encoding="utf-8")
            write_done(run, [["s1", "s2"]])
            self.assertEqual(C.missing_units(run, run), ["s3"])

    def test_labels_keep_separate_states(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            (run / "events.jsonl").write_text(
                json.dumps({"label": "translate", "status": "ok", "promptTokens": 1, "completionTokens": 1}) + "\n"
                + json.dumps({"label": "audit", "status": "ok", "promptTokens": 1, "completionTokens": 1}) + "\n",
                encoding="utf-8")
            (run / "done.jsonl").write_text(
                json.dumps({"label": "translate", "context": "w0", "ids": ["s1"]}) + "\n"
                + json.dumps({"label": "audit", "context": "s1", "ids": ["s1", "s2"]}) + "\n",
                encoding="utf-8")
            self.assertEqual(C.rebuild_state(run, "translate")["unitsDone"], 1)
            self.assertEqual(C.rebuild_state(run, "audit")["unitsDone"], 2)
            self.assertEqual(C.rebuild_state(run, "audit")["calls"], 1)


if __name__ == "__main__":
    unittest.main()
