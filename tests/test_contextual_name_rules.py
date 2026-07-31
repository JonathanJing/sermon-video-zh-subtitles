import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "review_sermon_subtitles_with_openai.py"
SPEC = importlib.util.spec_from_file_location("review_sermon_subtitles_with_openai", SCRIPT)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class ContextualNameRulesTest(unittest.TestCase):
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
