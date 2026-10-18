import unittest
from pathlib import Path

from scripts import produce_target_language_candidate as candidate
from scripts.language_review_plugins import es_weekly_15030286 as plugin
from scripts.language_review_plugins import ko_weekly_15030286 as ko_plugin
from scripts.language_review_plugins import weekly_15030286_common as common


def policy():
    return {
        "targetLocale": "es",
        "languageReview": {"requiredChecks": list(plugin.REQUIRED)},
        "terminology": {"properNames": [], "seriesNames": []},
        "scripture": {},
    }


def group(unit_id, target, *, source=common.SOURCE_SHA256):
    return {
        "translationGroupId": "translation-" + unit_id,
        "sourceUnitIds": [unit_id],
        "englishSourcePackageJsonSha256": source,
        "targetText": target,
        "targetUtterances": [target],
    }


def status(rows, check):
    return next(row for row in rows if row["checkId"] == check)["status"]


class Weekly15030286PluginTests(unittest.TestCase):
    def review(self, unit_id, english, target):
        return plugin.review_group(
            policy(), [{"sourceUnitId": unit_id, "english": english}], group(unit_id, target))

    def test_amount_is_complete_in_lead_and_absent_from_tail(self):
        lead_id, lead_english = common.AMOUNT_LEAD
        tail_id, tail_english = common.AMOUNT_TAIL
        self.assertEqual(status(self.review(
            lead_id, lead_english,
            "Y, de hecho, los informes indicaron que Calendly gastó 1,5 millones de dólares."), "numbers"), "pass")
        self.assertEqual(status(self.review(
            lead_id, lead_english,
            "Y, de hecho, los informes indicaron que Calendly gastó $1."), "numbers"), "fail")
        self.assertEqual(status(self.review(
            tail_id, tail_english,
            "en una empresa externa para diseñar ese logotipo."), "numbers"), "pass")
        self.assertEqual(status(self.review(
            tail_id, tail_english,
            "cinco millones en una empresa externa para diseñar ese logotipo."), "numbers"), "fail")

    def test_official_seek_the_good_title_is_masked_only_in_bound_units(self):
        unit_id, english = next(iter(common.SEEK_THE_GOOD.items()))
        target = ("La vara está baja y esta es otra razón por la que me encanta "
                  "la temporada de Seek the Good.")
        self.assertEqual(status(self.review(unit_id, english, target), "untranslated_source"), "pass")
        self.assertEqual(status(self.review(unit_id, english, target.replace("Seek the Good", "")),
                                "untranslated_source"), "fail")

    def test_plugin_is_bound_to_the_exact_source_package(self):
        unit_id, english = common.AMOUNT_LEAD
        with self.assertRaisesRegex(ValueError, "source package differs"):
            plugin.review_group(policy(), [{"sourceUnitId": unit_id, "english": english}],
                                group(unit_id, "gastó 1,5 millones de dólares", source="f" * 64))

    def test_plugin_hash_closes_over_both_shared_rule_modules(self):
        root = Path(__file__).resolve().parents[1] / "scripts/language_review_plugins"
        sources = candidate.plugin_implementation_sources(root / "es_weekly_15030286.py")
        self.assertEqual([path.name for path in sources], [
            "es_weekly_15030286.py", "common.py", "auto_qc_text_common.py",
            "weekly_15030286_common.py"])


class KoreanWeekly15030286PluginTests(unittest.TestCase):
    @staticmethod
    def policy():
        return {
            "targetLocale": "ko",
            "languageReview": {"requiredChecks": list(ko_plugin.REQUIRED)},
            "terminology": {"properNames": [], "seriesNames": []},
            "scripture": {},
        }

    def review(self, unit_id, english, target):
        return ko_plugin.review_group(
            self.policy(), [{"sourceUnitId": unit_id, "english": english}],
            group(unit_id, target))

    def test_new_one_is_a_pronoun_not_the_number_one(self):
        rows = self.review(
            "chunk-0000-u010",
            "They went from their old logo, which looked like this, to their new one here.",
            "그 회사는 이렇게 생겼던 예전 로고를 여기 보이는 새 로고로 바꿨습니다.")
        self.assertEqual(status(rows, "numbers"), "pass")

    def test_split_amount_is_spoken_once_in_the_lead_unit(self):
        lead_id, lead_english = common.AMOUNT_LEAD
        tail_id, tail_english = common.AMOUNT_TAIL
        self.assertEqual(status(self.review(
            lead_id, lead_english,
            "그리고 실제로 보도에 따르면, 캘린들리는 150만 달러를 지출했다고 합니다."), "numbers"), "pass")
        self.assertEqual(status(self.review(
            lead_id, lead_english,
            "그리고 실제로 보도에 따르면, 캘린들리는 1달러를 지출했다고 합니다."), "numbers"), "fail")
        self.assertEqual(status(self.review(
            tail_id, tail_english,
            "그 로고 디자인을 외부 업체에 맡겼다는 겁니다."), "numbers"), "pass")
        self.assertEqual(status(self.review(
            tail_id, tail_english,
            "그 로고 디자인을 외부 업체에 맡기는 데 150만 달러를 썼다는 겁니다."), "numbers"), "fail")

    def test_trilogy_may_be_rendered_as_an_explicit_three_part_work(self):
        rows = self.review(
            "chunk-0008-u019",
            "So if you have a nerd friend in your life, they probably love the Lord of the Rings trilogy.",
            "그래서 여러분 주변에 덕후 친구가 있다면, 그 친구는 아마 《반지의 제왕》 3부작을 무척 좋아할 겁니다.")
        self.assertEqual(status(rows, "numbers"), "pass")

    def test_korean_plugin_is_bound_to_the_exact_source_package(self):
        unit_id, english = common.AMOUNT_LEAD
        with self.assertRaisesRegex(ValueError, "source package differs"):
            ko_plugin.review_group(
                self.policy(), [{"sourceUnitId": unit_id, "english": english}],
                group(unit_id, "150만 달러를 지출했습니다.", source="f" * 64))

    def test_korean_plugin_hash_closes_over_both_shared_rule_modules(self):
        root = Path(__file__).resolve().parents[1] / "scripts/language_review_plugins"
        sources = candidate.plugin_implementation_sources(root / "ko_weekly_15030286.py")
        self.assertEqual([path.name for path in sources], [
            "ko_weekly_15030286.py", "common.py", "auto_qc_text_common.py",
            "weekly_15030286_common.py"])


if __name__ == "__main__":
    unittest.main()
