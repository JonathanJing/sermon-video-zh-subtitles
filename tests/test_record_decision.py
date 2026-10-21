import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools.ops import record_decision as decisions


class RecordDecisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root / "run"

    def test_decision_binds_file_evidence_by_hash_and_keeps_quotes_as_text(self):
        schedule = self.root / "schedule.json"
        schedule.write_text('{"maxEndLagSeconds": 120}')
        row = decisions.record(self.run, question="zh 片尾超出批准窗口 0.74 s，怎么处理", choice="允许片尾容差 ≤ 1 s",
                               decided_by="Jony (chat)", evidence=["用户原话：允许片尾容差≤1 s", "schedule.json"],
                               applies_to="layer3.zh-Hans", root=self.root, now=lambda: "2026-10-11T07:10:00+00:00")
        self.assertEqual(row["evidence"][0], {"text": "用户原话：允许片尾容差≤1 s"})
        self.assertEqual(row["evidence"][1], {"path": "schedule.json", "bytes": schedule.stat().st_size,
                                              "sha256": hashlib.sha256(schedule.read_bytes()).hexdigest()})
        self.assertEqual((row["channel"], row["appliesTo"], row["at"]), ("chat", "layer3.zh-Hans", "2026-10-11T07:10:00+00:00"))
        decisions.record(self.run, question="Ko 用现有读音发布？", choice="是，不做新的合成", decided_by="Jony (chat)")
        rows = decisions.read(self.run)
        self.assertEqual([r["choice"] for r in rows], ["允许片尾容差 ≤ 1 s", "是，不做新的合成"])
        self.assertEqual(len((self.run / decisions.FILE_NAME).read_text(encoding="utf-8").splitlines()), 2)

    def test_a_decision_governing_an_artifact_is_bound_to_its_bytes_and_goes_stale_when_they_change(self):
        # Review finding: without a bound artifact, a decision reads as still applicable after its inputs change.
        candidate = self.root / "ko-candidate.json"
        candidate.write_text('{"revision": 3}')
        row = decisions.record(self.run, question="接受 ko 第 3 版？", choice="接受", decided_by="Jony (chat)",
                               governs=["ko-candidate.json"], evidence=["用户原话：可以"], root=self.root)
        self.assertEqual(row["authority"], "artifact_bound")
        self.assertEqual(row["governs"], [{"path": "ko-candidate.json", "bytes": candidate.stat().st_size,
                                           "sha256": hashlib.sha256(candidate.read_bytes()).hexdigest()}])
        note = decisions.record(self.run, question="今晚先停？", choice="停", decided_by="Jony (chat)",
                                evidence=["用户原话：先停"], applies_to="layer3.ko", root=self.root)
        self.assertEqual((note["authority"], note["governs"]), ("unbound_note", []))
        self.assertEqual([r["status"] for r in decisions.check(self.run, self.root)], ["applies", "unbound"])
        candidate.write_text('{"revision": 4}')
        self.assertEqual(decisions.check(self.run, self.root)[0], {
            "at": row["at"], "question": "接受 ko 第 3 版？", "choice": "接受", "status": "stale",
            "changed": ["ko-candidate.json"]})
        candidate.unlink()
        self.assertEqual(decisions.check(self.run, self.root)[0]["status"], "stale")

    def test_a_governed_artifact_must_exist(self):
        with self.assertRaisesRegex(ValueError, "--governs must name an existing regular file: missing.json"):
            decisions.record(self.run, question="q", choice="c", decided_by="y", governs=["missing.json"], root=self.root)
        self.assertFalse((self.run / decisions.FILE_NAME).exists())

    def test_a_row_claiming_authority_without_a_bound_artifact_is_not_a_record(self):
        self.run.mkdir()
        forged = {"at": "t", "question": "q", "choice": "c", "decidedBy": "y", "authority": "artifact_bound", "governs": []}
        (self.run / decisions.FILE_NAME).write_text(json.dumps(forged) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "not a decision record"):
            decisions.read(self.run)

    def test_required_fields_and_channels(self):
        with self.assertRaisesRegex(ValueError, "--question is required"):
            decisions.record(self.run, question=" ", choice="x", decided_by="y")
        with self.assertRaisesRegex(ValueError, "--decided-by is required"):
            decisions.record(self.run, question="q", choice="x", decided_by="")
        with self.assertRaisesRegex(ValueError, "channel must be"):
            decisions.record(self.run, question="q", choice="x", decided_by="y", channel="telepathy")
        self.assertFalse((self.run / decisions.FILE_NAME).exists())

    def test_cli_writes_one_line(self):
        code = decisions.main(["--run-dir", str(self.run), "--question", "q", "--choice", "c", "--decided-by", "Jony (chat)",
                               "--evidence", "said so", "--applies-to", "layer4"])
        self.assertEqual(code, 0)
        row = json.loads((self.run / decisions.FILE_NAME).read_text(encoding="utf-8"))
        self.assertEqual((row["question"], row["choice"], row["appliesTo"], row["authority"]), ("q", "c", "layer4", "unbound_note"))
        self.assertEqual(decisions.main(["--run-dir", str(self.run), "--check"]), 0)
        with self.assertRaises(SystemExit):
            decisions.main(["--run-dir", str(self.run), "--question", "q"])  # recording needs a choice and a decider


if __name__ == "__main__":
    unittest.main()
