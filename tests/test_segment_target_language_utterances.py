import unittest

from scripts.segment_target_language_utterances import segment_evidence


class SegmentTargetLanguageUtterancesTest(unittest.TestCase):
    def test_preserves_every_character_and_original_model_evidence(self):
        long_text = ("Esta es una frase larga sobre la esperanza, " * 6).strip()
        original = {
            "groups": [{"translationGroupId": "translation-0-u001",
                        "sourceUnitIds": ["0-u001"],
                        "targetUtterances": [long_text],
                        "coverage": [{"sourceUnitId": "0-u001", "targetText": long_text}]}]
        }
        output, changes = segment_evidence(original)
        parts = output["groups"][0]["targetUtterances"]
        self.assertEqual("".join(parts), long_text)
        self.assertTrue(all(len(part) <= 180 and part.strip() for part in parts))
        self.assertEqual(original["groups"][0]["targetUtterances"], [long_text])
        self.assertEqual(output["groups"][0]["coverage"], original["groups"][0]["coverage"])
        self.assertEqual(changes[0]["beforeLengths"], [len(long_text)])
        self.assertEqual(changes[0]["sourceUnitIds"], ["0-u001"])


if __name__ == "__main__":
    unittest.main()
