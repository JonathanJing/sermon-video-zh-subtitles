import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts import record_decision as decisions


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
        self.assertEqual((row["question"], row["choice"], row["appliesTo"]), ("q", "c", "layer4"))


if __name__ == "__main__":
    unittest.main()
