import json
from pathlib import Path
import tempfile
import unittest

from scripts import run_journal as journal


class Clock:
    def __init__(self, start="2026-10-18T03:00:00+00:00"):
        self.at = start
        self.rows = []

    def set(self, value):
        self.at = value
        return self.at

    def __call__(self):
        return self.at


class RunJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name) / "run"
        self.clock = Clock()

    def event(self, stage, event, at, **extra):
        self.clock.set(at)
        return journal.append(self.run, stage, event, now=self.clock, **extra)

    def test_events_append_as_one_json_line_each(self):
        row = self.event("layer3.render.ko", "started", "2026-10-18T03:00:00+00:00", refs=["render.log"])
        self.assertEqual((row["stage"], row["event"], row["refs"]), ("layer3.render.ko", "started", ["render.log"]))
        self.event("layer3.render.ko", "finished", "2026-10-18T03:40:00+00:00", cost_microusd=0, note="8x8 batch")
        lines = (self.run / journal.FILE_NAME).read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[1])["note"], "8x8 batch")
        self.assertEqual([row["event"] for row in journal.read(self.run)], ["started", "finished"])

    def test_invalid_events_are_refused(self):
        with self.assertRaisesRegex(ValueError, "event must be one of"):
            journal.append(self.run, "stage", "done")
        with self.assertRaisesRegex(ValueError, "short identifier"):
            journal.append(self.run, "bad stage name", "started")
        with self.assertRaisesRegex(ValueError, "waiting event names"):
            journal.append(self.run, "audio-qc.ko", "waiting")
        with self.assertRaisesRegex(ValueError, "micro-USD"):
            journal.append(self.run, "audio-qc.ko", "finished", cost_microusd=-1)
        self.assertEqual(journal.read(self.run), [])

    def test_summary_splits_compute_waiting_and_rework(self):
        self.event("layer2.ko", "started", "2026-10-18T03:00:00+00:00")
        self.event("layer2.ko", "finished", "2026-10-18T03:30:00+00:00", cost_microusd=1_200_000)
        self.event("audio-qc.ko", "started", "2026-10-18T03:30:00+00:00")
        self.event("audio-qc.ko", "waiting", "2026-10-18T03:40:00+00:00", waiting_on="human acceptance of 5 units")
        self.event("audio-qc.ko", "resumed", "2026-10-18T05:40:00+00:00")
        self.event("audio-qc.ko", "failed", "2026-10-18T05:50:00+00:00")
        self.event("audio-qc.ko", "started", "2026-10-18T05:50:00+00:00")  # rework after a fix
        self.event("audio-qc.ko", "finished", "2026-10-18T06:05:00+00:00", cost_microusd=300_000)
        self.event("layer4.publish", "started", "2026-10-18T06:05:00+00:00")
        result = journal.summary(self.run)
        self.assertEqual(result["events"], 9)
        self.assertEqual(result["wallSeconds"], 3 * 3600 + 5 * 60)
        qc = result["stages"]["audio-qc.ko"]
        self.assertEqual(qc["starts"], 2)
        self.assertEqual(qc["rework"], 1)
        self.assertEqual(qc["waitingSeconds"], 2 * 3600)
        # First round 20 min compute + 2 h waiting; second round 15 min compute.
        self.assertEqual(qc["computeSeconds"], 35 * 60)
        self.assertEqual(qc["reworkSeconds"], 15 * 60)
        self.assertEqual(qc["waitingOn"], ["human acceptance of 5 units"])
        self.assertEqual(qc["status"], "finished")
        self.assertEqual(result["stages"]["layer2.ko"]["computeSeconds"], 30 * 60)
        self.assertEqual(result["totals"]["costMicrousd"], 1_500_000)
        self.assertEqual(result["totals"]["waitingSeconds"], 2 * 3600)
        self.assertEqual(result["openStages"], ["layer4.publish"])

    def test_empty_journal_summarizes_to_nothing(self):
        result = journal.summary(self.run)
        self.assertEqual((result["events"], result["wallSeconds"], result["stages"], result["openStages"]), (0, 0.0, {}, []))

    def test_cli_round_trip(self):
        self.assertEqual(journal.main(["append", "--run-dir", str(self.run), "--stage", "layer1", "--event", "started"]), 0)
        self.assertEqual(journal.main(["append", "--run-dir", str(self.run), "--stage", "layer1", "--event", "finished",
                                       "--cost-microusd", "0", "--ref", "summary.json"]), 0)
        self.assertEqual(journal.main(["summary", "--run-dir", str(self.run)]), 0)
        self.assertEqual(journal.summary(self.run)["stages"]["layer1"]["status"], "finished")


if __name__ == "__main__":
    unittest.main()
