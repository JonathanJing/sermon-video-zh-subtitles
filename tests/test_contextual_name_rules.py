import importlib.util
import sys
import unittest
import json
import tempfile
from unittest.mock import patch
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "review_sermon_subtitles_with_openai.py"
SPEC = importlib.util.spec_from_file_location("review_sermon_subtitles_with_openai", SCRIPT)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class ContextualNameRulesTest(unittest.TestCase):
    def test_generic_daughter_context_cannot_change_noah_identity(self):
        en = [{"id": 1, "text": "Noah's daughter-in-law was with him."}]
        zh = [{"id": 1, "zh": "挪亚的儿媳与他在一起。"}]
        self.assertEqual(mod.enforce_contextual_name_rules(en, zh), zh)

    def test_review_preserves_english_and_has_no_previous_sermon_context(self):
        source = [{"id": 223, "text": "Christine Kane mentioned a case in chapter 26."}]
        self.assertEqual(mod.corrected_english(source), source)
        payload = mod.batch_payload(source, source, 0, "fixture", "low")
        context = json.loads(payload["messages"][1]["content"])
        self.assertNotIn("authoritativeNames", context)
        self.assertNotIn("scriptureReferences", context)

    def test_cache_identity_changes_with_source_and_reuses_same_source(self):
        def response(_key, payload):
            cue = json.loads(payload["messages"][1]["content"])["segments"][0]
            return {"choices": [{"message": {"content": json.dumps({"segments": [{"id": cue["id"], "zh": cue["en"]}]})}}]}
        with tempfile.TemporaryDirectory() as temp, patch.object(mod, "chat_json", side_effect=response) as request:
            for text in ("First sermon", "First sermon", "Another sermon"):
                rows = [{"id": 8, "text": text}]
                result = mod.review_batch("fixture", rows, rows, 0, Path(temp), "fixture", "low")
                self.assertEqual(result["segments"][0]["zh"], text)
            self.assertEqual(request.call_count, 2)

    def test_invalid_response_does_not_poison_review_cache(self):
        rows = [{"id": 8, "text": "A different sermon"}]
        responses = [{"segments": []}, {"segments": [{"id": 8, "zh": "另一篇讲道"}]}]
        with tempfile.TemporaryDirectory() as temp, patch.object(mod, "chat_json") as request:
            request.side_effect = [{"choices": [{"message": {"content": json.dumps(result)}}]} for result in responses]
            with self.assertRaises(RuntimeError):
                mod.review_batch("fixture", rows, rows, 0, Path(temp), "fixture", "low")
            self.assertEqual(list(Path(temp).iterdir()), [])
            result = mod.review_batch("fixture", rows, rows, 0, Path(temp), "fixture", "low")
            self.assertEqual(result["segments"][0]["zh"], "另一篇讲道")
            self.assertEqual(len(list(Path(temp).iterdir())), 1)

    def test_hebrews_noah_is_nuo_ya(self):
        en = [{"id": 1, "text": "Hebrews 11 lists Noah, Abraham, Sarah and Moses."}]
        zh = [{"id": 1, "zh": "挪阿、亚伯拉罕、撒拉和摩西。"}]
        self.assertIn("挪亚", mod.enforce_contextual_name_rules(en, zh)[0]["zh"])

    def test_zelophehad_daughter_noah_is_nuo_e(self):
        en = [{"id": 1, "text": "The daughters of Zelophehad were Mahlah, Noah, Hoglah, Milcah and Tirzah."}]
        zh = [{"id": 1, "zh": "西罗非哈的女儿是玛拉、挪亚、曷拉、密迦、得撒。"}]
        self.assertIn("挪阿", mod.enforce_contextual_name_rules(en, zh)[0]["zh"])


if __name__ == "__main__":
    unittest.main()
