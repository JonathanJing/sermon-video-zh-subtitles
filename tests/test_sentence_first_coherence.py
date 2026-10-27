import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "experiments" / "sentence-first-agent"))

import audit_deepseek  # noqa: E402
import coherence_check  # noqa: E402,F401
import coherence_core as C  # noqa: E402
import spoken_forms  # noqa: E402


class ChainPlanTests(unittest.TestCase):
    def test_prefers_a_non_continuation_boundary(self):
        units = [{"id": f"s{i:04d}", "english": "This is a sentence."} for i in range(1, 11)]
        units[4]["english"] = "and this one continues,"
        units[5]["english"] = "this finishes here."
        plan, notes = C.chain_plan(units, 2)
        self.assertEqual([row for chain in plan for row in chain], list(range(1, 11)))
        self.assertNotEqual(notes[0]["index"], 5)
        self.assertFalse(notes[0]["fallback"])

    def test_chains_cover_every_unit_once(self):
        units = [{"id": f"s{i:04d}", "english": "Sentence."} for i in range(1, 24)]
        plan, _ = C.chain_plan(units, 4)
        self.assertEqual([row for chain in plan for row in chain], list(range(1, 24)))


class GlossaryTests(unittest.TestCase):
    def test_first_entry_and_pronoun_win(self):
        known = C.merge_glossary(C.empty_glossary(), {
            "people": [{"source": "Corrie", "target": "彭柯丽"}],
            "pronouns": {"jesus": "祂"}})
        merged = C.merge_glossary(known, {
            "people": [{"source": "corrie", "target": "柯丽"}, {"source": "Betsy", "target": "贝茜"}],
            "pronouns": {"jesus": "他"}})
        self.assertEqual([row["target"] for row in merged["people"]], ["彭柯丽", "贝茜"])
        self.assertEqual(merged["pronouns"]["jesus"], "祂")

    def test_glossary_is_bounded(self):
        glossary = C.empty_glossary()
        glossary["culturalReferences"] = [{"source": f"x{i}", "target": "y" * 40} for i in range(100)]
        bounded, dropped = C.bounded_glossary(glossary, max_chars=1000)
        self.assertLessEqual(len(__import__("json").dumps(bounded, ensure_ascii=False)), 1000)
        self.assertGreater(dropped, 0)


class ValidationTests(unittest.TestCase):
    def test_coverage_mismatch_is_rejected(self):
        unit = {"id": "s0001", "sourceUnitId": "asr-u0001", "english": "Hello."}
        rows = [{"id": "s0001", "target": "你好。", "coverage": [
            {"sourceUnitId": "asr-u9999", "targetText": "你好"}]}]
        self.assertTrue(C.validate_sentences(rows, [unit], "test"))

    def test_budget_overflow_is_rejected(self):
        unit = {"id": "s0001", "sourceUnitId": "asr-u0001", "english": "Hello."}
        rows = [{"id": "s0001", "target": "这是一个非常非常长的句子，用来超过预算上限。",
                 "coverage": [{"sourceUnitId": "asr-u0001", "targetText": "这是一个非常非常长的句子，用来超过预算上限。"}]}]
        self.assertTrue(C.validate_sentences(rows, [unit], "test", {"s0001": 2}))

    def test_number_helpers(self):
        self.assertEqual(C.number_tokens("Revelation 12 and 13"), ["12", "13"])
        self.assertTrue(C.target_has_number("启示录 12 章", "12"))
        self.assertTrue(C.target_has_number("十二章", "12"))


class SpokenFormTests(unittest.TestCase):
    def test_satan_only_when_present(self):
        self.assertEqual(spoken_forms.merge_spoken_forms(None, ["耶稣是得胜者。"]), {})
        self.assertEqual(spoken_forms.merge_spoken_forms(None, ["撒但被摔下去。"]),
                         {"撒但": "魔鬼"})

    def test_explicit_mapping_wins(self):
        self.assertEqual(spoken_forms.merge_spoken_forms({"撒但": "撒旦"}, ["撒但"]),
                         {"撒但": "撒旦"})


class DiffGateTests(unittest.TestCase):
    def row(self, target):
        return {"id": "s0001", "target": target}

    def test_accepts_a_number_preserving_fix(self):
        issue = {"id": "s0001", "code": "meaning", "suggestion": "神爱世人。"}
        ok, _ = audit_deepseek.acceptable(issue, self.row("神爱世界。"), None)
        self.assertTrue(ok)

    def test_rejects_dropping_a_connective(self):
        issue = {"id": "s0001", "code": "meaning", "suggestion": "我们要读经。"}
        ok, reason = audit_deepseek.acceptable(issue, self.row("但我们要读经。"), {"id": "s0000"})
        self.assertFalse(ok)
        self.assertIn("connective", reason)

    def test_rejects_dropping_a_number(self):
        issue = {"id": "s0001", "code": "meaning", "suggestion": "他们被杀了。"}
        ok, reason = audit_deepseek.acceptable(issue, self.row("12 个人被杀。"), None)
        self.assertFalse(ok)
        self.assertIn("number", reason)


if __name__ == "__main__":
    unittest.main()
