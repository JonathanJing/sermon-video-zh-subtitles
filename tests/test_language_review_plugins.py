"""Fail-closed checks for the source-bound Layer 2 locale screens."""
import copy
import hashlib
import json
from pathlib import Path
import runpy
import unittest
from unittest import mock

from scripts.language_review_plugins import es_sermon, ko_sermon, zh_hans_sermon
from scripts.language_review_plugins import common as locale_common
from scripts import target_language_policy
from scripts import produce_target_language_candidate as producer


ROOT = Path(__file__).resolve().parents[1]


def policy(locale):
    return json.loads((ROOT / f"config/target-language-policies/{locale}.json")
                      .read_text(encoding="utf-8"))


def group(source_id, text, *, english="", source_sha=zh_hans_sermon.SOURCE_SHA256):
    return ({"sourceUnitIds": [source_id], "targetUtterances": [text],
             "targetText": text, "englishSourcePackageJsonSha256": source_sha},
            [{"sourceUnitId": source_id, "english": english}])


class ChineseReviewTests(unittest.TestCase):
    def checks(self, source_id, text, *, english="", source_sha=zh_hans_sermon.SOURCE_SHA256):
        candidate, units = group(source_id, text, english=english, source_sha=source_sha)
        return {row["checkId"]: row["status"] for row in
                zh_hans_sermon.review_group(policy("zh-Hans"), units, candidate)}

    def test_exact_approved_quote_fragments_pass(self):
        for source_id, (english, exact) in zh_hans_sermon.QUOTED_UNITS.items():
            with self.subTest(source_id=source_id):
                self.assertEqual(self.checks(source_id, exact + "。", english=english)["cuv_exact_quote"], "pass")

    def test_quote_change_or_unapproved_source_fails(self):
        english, _ = zh_hans_sermon.QUOTED_UNITS["block-12-u002"]
        self.assertEqual(self.checks("block-12-u002", "你把起初的爱情离弃了。",
                                     english=english)["cuv_exact_quote"], "fail")
        self.assertEqual(self.checks("block-12-u002", "你把起初的爱心离弃了。",
                                     english=english, source_sha="0" * 64)["cuv_exact_quote"], "fail")
        self.assertEqual(self.checks("block-12-u002", "你把起初的爱心离弃了。",
                                     english="different English")["cuv_exact_quote"], "fail")

    def test_mixing_direct_quote_and_speaker_repetition_fails(self):
        candidate = {"sourceUnitIds": ["block-14-u001", "block-14-u002"],
                     "targetUtterances": ["人数不多。你还有几名。"],
                     "targetText": "人数不多。你还有几名。",
                     "englishSourcePackageJsonSha256": zh_hans_sermon.SOURCE_SHA256}
        units = [{"sourceUnitId": "block-14-u001", "english": "There's not many."},
                 {"sourceUnitId": "block-14-u002", "english": "There's just a few of you."}]
        reviews = zh_hans_sermon.review_group(policy("zh-Hans"), units, candidate)
        self.assertEqual(reviews[1]["status"], "fail")

    def test_paraphrase_not_automatically_exact_quote(self):
        self.assertEqual(self.checks("block-12-u004", "你曾经深爱他，如今却不同了。")
                         ["cuv_exact_quote"], "pass")
        self.assertEqual(self.checks("block-12-u004", "你把起初的爱心离弃了。")
                         ["cuv_exact_quote"], "fail")

    def test_number_series_and_tts_structure(self):
        self.assertEqual(self.checks("block-10-u002", "只有三样。", english="Only three.")
                         ["number_name_reading"], "pass")
        self.assertEqual(self.checks("block-10-u002", "只有两样。", english="Only three.")
                         ["number_name_reading"], "fail")
        self.assertEqual(self.checks("block-10-u001", "学者伊恩·杜古德说。",
                                     english="Ian Duguid is a scholar.")["number_name_reading"], "fail")
        explicit = "This series is called When Life Doesn’t Make Sense."
        self.assertEqual(self.checks("other", "这是《当生活令人费解》。", english=explicit)
                         ["spoken_chinese"], "pass")
        self.assertEqual(self.checks("other", "这是《生活没有意义》。", english=explicit)
                         ["spoken_chinese"], "fail")
        self.assertEqual(self.checks("other", "《启示录》第二章。", english="Revelation chapter two.")
                         ["spoken_chinese"], "pass")
        self.assertEqual(self.checks("other", "<break>三", english="Three.")
                         ["tts_segmentation"], "fail")


class PendingLocalesTests(unittest.TestCase):
    def test_builtin_plugin_hash_includes_shared_rule_file(self):
        plugin = ROOT / "scripts/language_review_plugins/ko_sermon.py"
        sources = producer.plugin_implementation_sources(plugin)
        self.assertEqual([path.name for path in sources], ["ko_sermon.py", "common.py"])
        self.assertNotEqual(producer.plugin_implementation_sha256(plugin),
                            hashlib.sha256(plugin.read_bytes()).hexdigest())
        before = producer.plugin_implementation_sha256(plugin)
        original_read = Path.read_bytes

        def tampered_read(path):
            data = original_read(path)
            return data + b"\n# shared-rule drift\n" if path.name == "common.py" else data

        with mock.patch.object(Path, "read_bytes", tampered_read):
            after = producer.plugin_implementation_sha256(plugin)
        self.assertNotEqual(before, after)

    def test_plugins_load_through_producer_runpy_contract(self):
        for module, filename in ((zh_hans_sermon, "zh_hans_sermon.py"),
                                 (ko_sermon, "ko_sermon.py"),
                                 (es_sermon, "es_sermon.py")):
            with self.subTest(plugin=module.PLUGIN_ID):
                loaded = runpy.run_path(str(ROOT / "scripts/language_review_plugins" / filename))
                self.assertEqual(loaded["PLUGIN_ID"], module.PLUGIN_ID)
                self.assertTrue(callable(loaded["review_group"]))

    def test_policies_stay_pending(self):
        for locale in ("zh-Hans", "ko", "es"):
            with self.subTest(locale=locale):
                self.assertFalse(target_language_policy.validate_policy(policy(locale))
                                 ["productionPolicyReady"])

    def test_korean_and_spanish_cannot_pass_without_corpus_and_review(self):
        for locale, plugin, text in (("ko", ko_sermon, "사랑을 버렸다."),
                                     ("es", es_sermon, "Has abandonado el amor.")):
            with self.subTest(locale=locale):
                candidate, units = group("block-12-u002", text,
                                         english="You've abandoned the love you had at first.")
                checks = plugin.review_group(policy(locale), units, candidate)
                self.assertEqual([row["checkId"] for row in checks],
                                 policy(locale)["languageReview"]["requiredChecks"])
                self.assertEqual(next(row for row in checks if row["checkId"] == "scripture_edition")
                                 ["status"], "fail")
                self.assertEqual(next(row for row in checks if row["checkId"] == "tts_segmentation")
                                 ["status"], "pass")
                artificially_resolved = copy.deepcopy(policy(locale))
                artificially_resolved["scripture"]["citationUseStatus"] = "project_source_reviewed"
                artificially_resolved["scripture"]["quoteCheckPolicy"] = "source_bound_exact_quote"
                for kind in ("seriesNames", "properNames"):
                    for term in artificially_resolved["terminology"][kind]:
                        term["target"] = "reviewed term"
                        term["reviewStatus"] = "human_reviewed"
                still_blocked = plugin.review_group(artificially_resolved, units, candidate)
                self.assertEqual(next(row for row in still_blocked if row["checkId"] == "scripture_edition")
                                 ["status"], "fail")

    def test_approved_edition_excerpts_pass_only_at_source_bound_units(self):
        for locale, plugin, quote_2, quote_3, few, not_many in (
                ("ko", ko_sermon, ko_sermon.EXCERPT_2[0], ko_sermon.EXCERPT_3[0],
                 "몇 사람이 있습니다.", "많지는 않습니다."),
                ("es", es_sermon, es_sermon.EXCERPT_2[0], es_sermon.EXCERPT_3[0],
                 "Hay unos pocos.", "No hay muchos.")):
            with self.subTest(locale=locale):
                resolved = policy(locale)
                resolved["scripture"]["citationUseStatus"] = "project_source_reviewed"
                resolved["scripture"]["quoteCheckPolicy"] = "source_bound_exact_quote"

                def check(ids, target, source_sha=locale_common.SOURCE_SHA256):
                    rows = [{"sourceUnitId": id_, "english": locale_common.ENGLISH_QUOTES[id_]}
                            for id_ in ids]
                    candidate = {"sourceUnitIds": ids, "targetUtterances": [target],
                                 "targetText": target,
                                 "englishSourcePackageJsonSha256": source_sha}
                    result_rows = plugin.review_group(resolved, rows, candidate)
                    return next(row for row in result_rows if row["checkId"] == "scripture_edition")

                self.assertEqual(check(["block-12-u002"], quote_2 + ".")["status"], "pass")
                self.assertEqual(check(["block-13-u007"], few)["status"], "pass")
                self.assertEqual(check(["block-14-u001"], not_many)["status"], "pass")
                self.assertEqual(check(["block-14-u002", "block-14-u003"], quote_3 + ".")
                                 ["status"], "pass")
                self.assertEqual(check(["block-14-u002"], quote_3)["status"], "fail")
                self.assertEqual(check(["block-12-u002"], quote_2 + " extra")["status"], "fail")
                self.assertEqual(check(["block-12-u002"], quote_2,
                                       source_sha="0" * 64)["status"], "fail")
                resolved["scripture"]["citationUseStatus"] = "pending"
                self.assertEqual(check(["block-12-u002"], quote_2)["status"], "fail")

    def test_korean_and_spanish_machine_name_number_register_checks(self):
        for locale, plugin, good, bad_register in (
                ("ko", ko_sermon, "이언 두기드 학자는 무기가 세 가지라고 합니다.", "너는 이언 두기드야."),
                ("es", es_sermon, "Ian Duguid dice que hay tres armas.", "Vosotros tenéis tres armas.")):
            with self.subTest(locale=locale):
                configured = policy(locale)
                configured["terminology"]["properNames"].append({
                    "source": "Ian Duguid", "target": "이언 두기드" if locale == "ko" else "Ian Duguid",
                    "reviewStatus": "human_reviewed"})
                english = [{"sourceUnitId": "block-10-u001",
                            "english": "Ian Duguid is a scholar who says Satan only has three weapons."}]
                candidate = {"sourceUnitIds": ["block-10-u001"], "targetUtterances": [good],
                             "targetText": good,
                             "englishSourcePackageJsonSha256": locale_common.SOURCE_SHA256}
                results = {row["checkId"]: row["status"] for row in
                           plugin.review_group(configured, english, candidate)}
                self.assertEqual(results["number_reading"], "pass")
                self.assertEqual(results["proper_name_transliteration" if locale == "ko"
                                         else "proper_name_rendering"], "fail")  # Satan name omitted.
                candidate["targetUtterances"] = [bad_register]
                candidate["targetText"] = bad_register
                results = {row["checkId"]: row["status"] for row in
                           plugin.review_group(configured, english, candidate)}
                self.assertEqual(results["honorific_consistency" if locale == "ko"
                                         else "register_consistency"], "fail")


if __name__ == "__main__":
    unittest.main()
