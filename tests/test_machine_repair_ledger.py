"""The repair cap is counted in a durable ledger, never by the caller."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import machine_repair_ledger as ledger
from scripts import target_audio_auto_qc as audio_qc
from scripts import target_text_auto_qc as text_qc
from tests import auto_qc_fixtures as fixtures

LINEAGE = ledger.lineage("text", "ko", "1" * 64, "2" * 64)


def failing_groups():
    groups = [{**group, "sourceUnitIds": [f"u{index}"]} for index, group in enumerate(fixtures.groups("ko"), 1)]
    groups[3] = {**groups[3], "targetText": "은혜는 선물입니다."}
    return groups


class RepairLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.judge = fixtures.PerfectSemanticJudge("ko")

    def run_qc(self, groups, position):
        return text_qc.screen(groups, "ko", policy=fixtures.policy("ko"), call=self.judge,
                              identity=fixtures.SEMANTIC_IDENTITY, repair_position=position)

    def head(self):
        return ledger.position(LINEAGE, ledger.load(self.root, LINEAGE))

    def test_an_interrupted_append_leaves_no_partial_entry(self):
        qc = self.run_qc(failing_groups(), self.head())
        with patch.object(ledger.os, "link", side_effect=OSError("disk full")), self.assertRaises(OSError):
            ledger.append(self.root, LINEAGE, qc)
        self.assertEqual(ledger.load(self.root, LINEAGE), [])
        self.assertEqual([p.name for p in self.root.rglob("*") if p.is_file()], [])
        ledger.append(self.root, LINEAGE, qc)
        self.assertEqual(len(ledger.load(self.root, LINEAGE)), 1)

    def test_counts_survive_reruns_and_cannot_be_reset(self):
        groups = failing_groups()
        first = self.run_qc(groups, self.head())
        ledger.append(self.root, LINEAGE, first)
        second = self.run_qc(groups, self.head())
        self.assertEqual(second["results"][3]["failedAttempts"], 2)
        # A run that starts over from zero (no position, or the first one again) is refused.
        for stale in (self.run_qc(groups, None), self.run_qc(groups, ledger.position(LINEAGE, []))):
            with self.assertRaisesRegex(ValueError, "current repair ledger head"):
                ledger.append(self.root, LINEAGE, stale)
        # So is a receipt whose count was edited back down.
        edited = copy.deepcopy(second)
        edited["results"][3]["failedAttempts"] = 0
        with self.assertRaisesRegex(ValueError, "does not follow the repair ledger"):
            ledger.append(self.root, LINEAGE, edited)
        entry = ledger.append(self.root, LINEAGE, second)
        self.assertEqual(entry["failedAttempts"], {"u4": 2})
        # Two runs from the same head: only the first can claim the position.
        third, rival = self.run_qc(groups, self.head()), self.run_qc(groups[:3] + groups[4:], self.head())
        ledger.append(self.root, LINEAGE, third)
        with self.assertRaises(ValueError):
            ledger.append(self.root, LINEAGE, rival)

    def test_regrouped_or_renamed_groups_keep_the_count_of_their_english_units(self):
        groups = failing_groups()
        ledger.append(self.root, LINEAGE, self.run_qc(groups, self.head()))
        merged = groups[:2] + [{**groups[2], "groupId": "renamed", "english": groups[2]["english"] + " "
                                + groups[3]["english"], "targetText": groups[2]["targetText"] + " "
                                + groups[3]["targetText"], "sourceUnitIds": ["u3", "u4"]}] + groups[4:]
        rerun = self.run_qc(merged, self.head())
        self.assertEqual((rerun["results"][2]["status"], rerun["results"][2]["failedAttempts"]), ("fail", 2))

    def test_waiver_head_check_and_tampered_ledgers(self):
        groups = failing_groups()
        first = self.run_qc(groups, self.head())
        ledger.append(self.root, LINEAGE, first)
        fixed = fixtures.groups("ko")
        fixed = [{**group, "sourceUnitIds": [f"u{index}"]} for index, group in enumerate(fixed, 1)]
        final = self.run_qc(fixed, self.head())
        self.assertEqual(final["results"][3]["failedAttempts"], 1)
        ledger.append(self.root, LINEAGE, final)
        entries = ledger.load(self.root, LINEAGE)
        self.assertEqual(ledger.head_problems(LINEAGE, entries, final), [])
        self.assertTrue(ledger.head_problems(LINEAGE, entries, first))
        self.assertTrue(ledger.head_problems(ledger.lineage("text", "es", "1" * 64, "2" * 64), entries, final))
        forged = copy.deepcopy(entries)
        forged[0]["failedAttempts"] = {}
        self.assertTrue(ledger.head_problems(LINEAGE, forged, final))
        # A deleted or foreign entry breaks the durable chain.
        folder = ledger.directory(self.root, LINEAGE)
        (folder / "entry-000001.json").unlink()
        with self.assertRaisesRegex(ValueError, "gap"):
            ledger.load(self.root, LINEAGE)

    def test_audio_counts_come_from_the_ledger_only(self):
        unit = {"groupId": "g001", "text": "두려워하지 마십시오.", "sourceSeconds": 2.0,
                "wav": fixtures.speech_wav(2.0), "priorFailedAttempts": 0}
        with self.assertRaisesRegex(ValueError, "repair ledger"):
            audio_qc.screen([unit], "ko")
        del unit["priorFailedAttempts"]
        lineage = ledger.lineage("audio", "ko", "1" * 64, "2" * 64)
        with self.assertRaisesRegex(ValueError, "source unit ids"):
            audio_qc.screen([unit], "ko", repair_position=ledger.position(lineage, []))
        result = audio_qc.screen([{**unit, "sourceUnitIds": ["u1"]}], "ko",
                                 repair_position=ledger.position(lineage, []))
        self.assertEqual(ledger.append(self.root, lineage, result)["sequence"], 1)


if __name__ == "__main__":
    unittest.main()
