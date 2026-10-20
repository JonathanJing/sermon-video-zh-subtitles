import json
from pathlib import Path
import tempfile
import unittest

from tools.development import run_journal as journal


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

    def test_rework_excludes_the_repeat_rounds_own_waiting(self):
        # Review finding: a repeat that ran 10 min and then waited 30 min counted as 40 min of rework.
        self.event("audio-qc.es", "started", "2026-10-18T03:00:00+00:00")
        self.event("audio-qc.es", "failed", "2026-10-18T03:05:00+00:00")
        self.event("audio-qc.es", "started", "2026-10-18T03:05:00+00:00")
        self.event("audio-qc.es", "waiting", "2026-10-18T03:15:00+00:00", waiting_on="credential")
        self.event("audio-qc.es", "finished", "2026-10-18T03:45:00+00:00")
        stage = journal.summary(self.run)["stages"]["audio-qc.es"]
        self.assertEqual((stage["computeSeconds"], stage["waitingSeconds"], stage["reworkSeconds"]), (15 * 60, 30 * 60, 10 * 60))

    def test_an_open_stage_does_not_shrink_closed_compute(self):
        self.event("layer2.es", "started", "2026-10-18T03:00:00+00:00")
        self.event("layer2.es", "finished", "2026-10-18T03:20:00+00:00")
        self.event("layer2.es", "started", "2026-10-18T03:20:00+00:00")
        self.event("layer2.es", "waiting", "2026-10-18T03:21:00+00:00", waiting_on="quota")
        self.event("layer2.es", "resumed", "2026-10-18T04:21:00+00:00")  # still running when the summary is read
        stage = journal.summary(self.run)["stages"]["layer2.es"]
        self.assertEqual((stage["computeSeconds"], stage["waitingSeconds"], stage["status"]), (20 * 60, 3600, "running"))

    def test_rows_name_the_host_by_a_per_run_token_not_its_name(self):
        # Review finding: the journal is published, and a bare machine name can name a person.
        from unittest.mock import patch
        with patch.object(journal.socket, "gethostname", return_value="Jony-MacBook-Pro"):
            first = self.event("layer1", "started", "2026-10-18T03:00:00+00:00")
            second = self.event("layer1", "finished", "2026-10-18T03:01:00+00:00")
        with patch.object(journal.socket, "gethostname", return_value="spark-dgx"):
            other = self.event("layer3", "started", "2026-10-18T03:02:00+00:00")
        self.assertNotIn("host", first)
        self.assertRegex(first["hostId"], r"^host-[0-9a-f]{12}$")
        self.assertEqual(first["hostId"], second["hostId"])
        self.assertNotEqual(first["hostId"], other["hostId"])
        self.assertNotIn("Jony", (self.run / journal.FILE_NAME).read_text(encoding="utf-8"))
        # Another run gets another salt, so tokens do not link runs to each other or to a name.
        elsewhere = Path(self.temp.name) / "other-run"
        with patch.object(journal.socket, "gethostname", return_value="Jony-MacBook-Pro"):
            self.assertNotEqual(journal.append(elsewhere, "layer1", "started")["hostId"], first["hostId"])
        self.assertEqual(sorted(path.name for path in self.run.iterdir()), [journal.SALT_NAME, journal.FILE_NAME])

    def test_the_digest_exports_the_journal_but_not_its_salt(self):
        from tools.development import export_run_digest as digest
        self.event("layer1", "started", "2026-10-18T03:00:00+00:00")
        out = Path(self.temp.name) / "reports"
        self.assertEqual(digest.main([str(self.run), "--name", "20261018-journal", "--out", str(out)]), 0)
        report = out / "20261018-journal"
        exported = sorted(path.name for path in report.rglob("*") if path.is_file())
        self.assertIn(journal.FILE_NAME, exported)
        self.assertNotIn(journal.SALT_NAME, exported)
        # The host ID survives redaction, so the report can still tell hosts apart.
        row = json.loads(next(report.rglob(journal.FILE_NAME)).read_text(encoding="utf-8"))
        self.assertRegex(row["hostId"], r"^host-[0-9a-f]{12}$")

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
