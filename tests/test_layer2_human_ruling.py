import json
from pathlib import Path
import tempfile
import unittest

from tongxing_production.text import auto_repair as repair
from tongxing_production.text import human_ruling as ruling
from scripts import source_meaning_machine_adjudication as source_meaning


SOURCE = {"source": {"sourceId": "s"}, "anchors": {}}
ANCHOR = {"sourceUnits": [{"sourceUnitId": "u4", "english": "Others of us, you've walked in here this whole week."},
                          {"sourceUnitId": "u5", "english": "You've walked in."}]}


def write(folder, **changes):
    value = ruling.build(source=SOURCE, anchor=ANCHOR, decided_by="Jony", decided_at="2026-10-11T07:00:00Z",
                         user_statement="同意", rulings={"u4": "Spoken restart; keep the trailing phrase open."})
    value.update(changes)
    path = Path(folder) / "meaning-notes.json"
    path.write_text(json.dumps(value, ensure_ascii=False))
    return path


def entries(reason):
    return [{"sequence": 1, "outcome": "stopped", "groups": [
                {"translationGroupId": "g4", "sourceUnitIds": ["u4"], "repaired": True, "decision": "repairable_content_failure",
                 "failureCodes": ["review_uncertainty"], "fingerprint": "f"}],
             "stopped": [{"translationGroupId": "g4", "sourceUnitIds": ["u4"], "reasonCode": reason}]}]


class HumanRulingTests(unittest.TestCase):
    def test_ruling_loads_through_the_meaning_note_loader_and_names_the_person(self):
        with tempfile.TemporaryDirectory() as folder:
            notes = source_meaning.load_meaning_notes(write(folder), source=SOURCE, anchor=ANCHOR)
        self.assertTrue(notes["u4"]["humanRuling"])
        self.assertIn("human ruling by Jony", source_meaning.repair_instruction(notes, ["u4"]))

    def test_ruling_reopens_a_human_review_stop_but_machine_notes_do_not(self):
        with tempfile.TemporaryDirectory() as folder:
            notes = source_meaning.load_meaning_notes(write(folder), source=SOURCE, anchor=ANCHOR)
        self.assertEqual(list(repair.reopenable_groups(entries("request_human_review"), notes)), ["g4"])
        machine = {"u4": {**notes["u4"], "humanRuling": False}}
        self.assertEqual(repair.reopenable_groups(entries("request_human_review"), machine), {})
        self.assertEqual(repair.reopenable_groups(entries("repeated_failure_without_progress"), notes), {})

    def test_changed_source_text_or_binding_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            path = write(folder)
            changed = {"sourceUnits": [{"sourceUnitId": "u4", "english": "Others of us walked in."}]}
            with self.assertRaisesRegex(ValueError, "human_ruling_binding_changed"):
                ruling.load(path, source=SOURCE, anchor=changed)
            with self.assertRaisesRegex(ValueError, "human_ruling_identity"):
                ruling.load(write(folder, humanApproval=False), source=SOURCE, anchor=ANCHOR)


if __name__ == "__main__":
    unittest.main()
