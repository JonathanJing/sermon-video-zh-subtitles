import json
import unittest

from tongxing_production.text import coherence as co


def unit(n, english, start, end):
    return {"sourceUnitId": f"asr-u{n:04d}", "english": english, "start": start, "end": end}


class ContinuationGroupsTest(unittest.TestCase):
    def test_merges_clauses_the_recogniser_split(self):
        units = [
            unit(196, "And so Revelation 12 and 13, it's intense to read, but you should not read Revelation 12 and 13.", 831.97, 837.71),
            unit(197, "With fear of what's happening.", 837.71, 840.07),
            unit(198, "No, you read Revelation 12 and 13, remembering that Jesus is victor.", 840.23, 845.87),
        ]
        groups = co.continuation_groups(units)
        self.assertEqual([g["sourceUnitIds"] for g in groups],
                         [["asr-u0196", "asr-u0197"], ["asr-u0198"]])
        self.assertEqual(groups[0]["translationGroupId"], "translation-asr-u0196+asr-u0197")

    def test_merges_bare_initials_and_lowercase_continuations(self):
        units = [unit(256, "D .A.", 1108.65, 1109.23),
                 unit(257, "Carson, a scholar, imagines one of the homes.", 1109.33, 1112.59),
                 unit(295, "She is nourished for a time,", 1242.61, 1253.51),
                 unit(296, "times and half a time.", 1253.97, 1256.47)]
        self.assertEqual([g["sourceUnitIds"] for g in co.continuation_groups(units)],
                         [["asr-u0256", "asr-u0257"], ["asr-u0295", "asr-u0296"]])

    def test_keeps_the_speakers_short_sentences_apart(self):
        units = [unit(6, "Somebody betrayed them.", 22.2, 23.22),
                 unit(7, "They were arrested.", 23.34, 24.16),
                 unit(282, "Both.", 1196.23, 1196.95),
                 unit(283, "Both.", 1198.15, 1198.87)]
        self.assertEqual(len(co.continuation_groups(units)), 4)

    def test_starter_after_a_long_pause_stays_separate(self):
        units = [unit(1, "That God will use anything.", 1367.69, 1370.73),
                 unit(2, "To care for you.", 1374.45, 1375.99)]
        self.assertEqual(len(co.continuation_groups(units)), 2)
        units[1]["start"] = 1371.0
        self.assertEqual(len(co.continuation_groups(units)), 1)

    def test_caps_group_size_and_duration(self):
        units = [unit(i, "and then,", i * 2.0, i * 2.0 + 1.5) for i in range(1, 8)]
        groups = co.continuation_groups(units, max_units=3, max_seconds=100)
        self.assertEqual([len(g["sourceUnitIds"]) for g in groups], [3, 3, 1])
        groups = co.continuation_groups(units, max_units=10, max_seconds=4)
        self.assertTrue(all(len(g["sourceUnitIds"]) <= 2 for g in groups))

    def test_every_unit_once_in_order(self):
        units = [unit(i, text, i, i + 0.9) for i, text in enumerate(
            ["One,", "two.", "Three.", "to four.", "Five"], start=1)]
        flat = [u for g in co.continuation_groups(units) for u in g["sourceUnitIds"]]
        self.assertEqual(flat, [u["sourceUnitId"] for u in units])


class ParsingTest(unittest.TestCase):
    groups = [{"translationGroupId": "translation-a+b", "sourceUnitIds": ["a", "b"]},
              {"translationGroupId": "translation-c", "sourceUnitIds": ["c"]}]

    def test_window_translation_requires_coverage_substrings(self):
        reply = {"groups": [
            {"translationGroupId": "translation-a+b", "chinese": "但你读的时候，不该带着恐惧。",
             "coverage": [{"sourceUnitId": "a", "targetText": "但你读的时候"},
                          {"sourceUnitId": "b", "targetText": "不该带着恐惧"}]},
            {"translationGroupId": "translation-c", "chinese": "要记住耶稣是得胜者。",
             "coverage": [{"sourceUnitId": "c", "targetText": "耶稣是得胜者"}]}]}
        parsed = co.parse_window_translation("```json\n" + json.dumps(reply, ensure_ascii=False) + "\n```", self.groups)
        self.assertEqual(parsed["translation-c"]["chinese"], "要记住耶稣是得胜者。")
        reply["groups"][1]["coverage"][0]["targetText"] = "不在译文里"
        with self.assertRaises(ValueError):
            co.parse_window_translation(json.dumps(reply, ensure_ascii=False), self.groups)
        with self.assertRaises(ValueError):
            co.parse_window_translation(json.dumps({"groups": reply["groups"][:1]}), self.groups)

    def test_review_edits_apply_only_to_known_cues(self):
        rows = [{"id": "x", "english": "To care for you.", "chinese": "为要照顾你。"}]
        edits = co.parse_passage_review(json.dumps({"edits": [
            {"id": "x", "type": "fragment", "chinese": "神这样做，是为了照顾你。", "reason": "悬空"}]},
            ensure_ascii=False), rows)
        self.assertEqual(co.apply_review(rows, edits)[0]["chinese"], "神这样做，是为了照顾你。")
        self.assertEqual(rows[0]["chinese"], "为要照顾你。")
        with self.assertRaises(ValueError):
            co.parse_passage_review(json.dumps({"edits": [{"id": "y", "type": "fragment", "chinese": "z"}]}), rows)
        with self.assertRaises(ValueError):
            co.parse_passage_review(json.dumps({"edits": [{"id": "x", "type": "style", "chinese": "z"}]}), rows)

    def test_reading_edition_keeps_coverage(self):
        rows = [{"id": "p1", "english": "A.", "chinese": "甲。"}, {"id": "p2", "english": "B.", "chinese": "乙。"}]
        self.assertEqual(co.parse_reading('{"paragraph": "甲乙。", "sourceUnitIds": ["p1", "p2"]}', rows)["paragraph"],
                         "甲乙。")
        with self.assertRaises(ValueError):
            co.parse_reading('{"paragraph": "甲。", "sourceUnitIds": ["p1"]}', rows)

    def test_glossary_defaults_and_shape(self):
        glossary = co.parse_glossary('{"people": [{"source": "Betsie", "target": "贝茜", "note": "姐姐"}]}')
        self.assertEqual(glossary["schemaVersion"], co.GLOSSARY_SCHEMA)
        self.assertEqual(glossary["recurringPhrases"], [])
        with self.assertRaises(ValueError):
            co.parse_glossary('{"people": {}}')


class ParagraphPlanTest(unittest.TestCase):
    def test_breaks_at_long_pauses_after_sentence_ends(self):
        rows = [{"id": str(i), "english": "Sentence.", "chinese": "句。", "start": i * 3.0,
                 "end": i * 3.0 + 2.8 if i != 4 else i * 3.0 + 0.5} for i in range(10)]
        paragraphs = co.paragraph_plan(rows, min_pause=1.5, min_rows=4, max_rows=14)
        self.assertEqual([len(p) for p in paragraphs], [5, 5])
        self.assertEqual([r["id"] for p in paragraphs for r in p], [r["id"] for r in rows])


if __name__ == "__main__":
    unittest.main()
