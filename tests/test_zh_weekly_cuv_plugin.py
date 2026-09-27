"""Fail-closed checks for the Drive sermon Chinese CUV review plugin."""
from __future__ import annotations

import copy
import runpy
import unittest
from pathlib import Path

from scripts.cuv_scripture import CuvLibrary
from scripts.language_review_plugins import zh_hans_weekly_cuv as plugin
from scripts.produce_target_language_candidate import plugin_implementation_sources


ROOT = Path(__file__).resolve().parents[1]
ENGLISH = (
    "Verse 2 and 3, John says, Immediately I was in the Spirit, and there was a "
    "throne in heaven, and someone was seated on it."
)
UNIT = {"sourceUnitId": "0-u067", "english": ENGLISH}
SOURCE_HASH = "a" * 64
ANCHOR_HASH = "b" * 64


def policy() -> dict:
    return {
        "targetLocale": "zh-Hans",
        "sourceScope": {"englishSourcePackageJsonSha256": SOURCE_HASH,
                        "anchorManifestSha256": ANCHOR_HASH},
        "languageReview": {"requiredChecks": plugin.REQUIRED},
        "scripture": {"editionId": "cmn-cu89s",
                      "citationUseStatus": "project_source_reviewed",
                      "quoteCheckPolicy": "source_bound_exact_quote"},
        "terminology": {"seriesNames": [], "properNames": []},
    }


def group(text: str, *, source_hash: str = SOURCE_HASH) -> dict:
    return {"englishSourcePackageJsonSha256": source_hash,
            "sourceUnitIds": [UNIT["sourceUnitId"]],
            "targetText": text, "targetUtterances": [text]}


def simulated_review(excerpt: str, excerpt_hash: str) -> dict:
    """Test fixture only: no production approval is embedded in the plugin."""
    decisions = [{"candidateId": candidate, "classification": "speaker_paraphrase", "parts": []}
                 for candidate in plugin.CANDIDATE_VERSES]
    decisions[0] = {
        "candidateId": "rev-4-2-3", "classification": "partial_direct_quote",
        "parts": [{"sourceUnitId": UNIT["sourceUnitId"],
                   "englishStart": "Immediately I was in the Spirit",
                   "englishEnd": "someone was seated on it.",
                   "reference": "REV 4:2", "cuvExcerpt": excerpt,
                   "cuvExcerptSha256": excerpt_hash}],
    }
    return {"decision": "approved", "humanApproval": True, "approvedBy": "user",
            "englishSourcePackageJsonSha256": SOURCE_HASH,
            "anchorManifestJsonSha256": ANCHOR_HASH, "decisions": decisions}


class ChineseWeeklyCuvTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        selected = CuvLibrary.from_path().lookup("REV 4:2")
        cls.excerpt = selected["text"]
        cls.excerpt_hash = selected["textSha256"]

    def checks(self, text: str, receipt: dict | None, *, source_hash: str = SOURCE_HASH,
               english: str = ENGLISH) -> dict[str, str]:
        rows = plugin._review_group(policy(), [{"sourceUnitId": UNIT["sourceUnitId"],
                                               "english": english}],
                                    group(text, source_hash=source_hash), receipt)
        return {row["checkId"]: row["status"] for row in rows}

    def test_eight_candidate_references_do_not_grant_human_approval(self):
        self.assertEqual(len(plugin.CANDIDATE_VERSES), 8)
        library = CuvLibrary.from_path()
        for references in plugin.CANDIDATE_VERSES.values():
            for reference in references:
                self.assertEqual(library.lookup(reference)["edition"]["id"], "cmn-cu89s")
        self.assertIsNone(plugin.APPROVED_BOUNDARY_REVIEW)
        text = "约翰说：" + self.excerpt
        self.assertEqual(self.checks(text, None)["cuv_exact_quote"], "fail")
        self.assertEqual({row["checkId"] for row in plugin.review_group(
            policy(), [UNIT], group(text))}, set(plugin.REQUIRED))
        self.assertEqual(plugin.review_group(policy(), [UNIT], group(text))[1]["status"], "fail")

    def test_hypothetical_review_checks_mixed_unit_and_exact_cuv(self):
        receipt = simulated_review(self.excerpt, self.excerpt_hash)
        text = "第2、3节，约翰说：" + self.excerpt
        self.assertTrue(all(status == "pass" for status in self.checks(text, receipt).values()))
        self.assertEqual(self.checks("约翰说：我立刻被圣灵感动。", receipt)["cuv_exact_quote"], "fail")
        self.assertEqual(self.checks(text, receipt, english="different English")
                         ["cuv_exact_quote"], "fail")
        self.assertEqual(self.checks(text, receipt, source_hash="c" * 64)
                         ["cuv_exact_quote"], "fail")
        self.assertEqual(self.checks(text + "[pause]", receipt)["tts_segmentation"], "fail")

    def test_receipt_must_match_final_source_and_pinned_excerpt(self):
        text = "约翰说：" + self.excerpt
        receipt = simulated_review(self.excerpt, self.excerpt_hash)
        for change in ("humanApproval", "anchorManifestJsonSha256", "approvedBy"):
            damaged = copy.deepcopy(receipt)
            damaged[change] = False if change == "humanApproval" else "wrong"
            self.assertEqual(self.checks(text, damaged)["cuv_exact_quote"], "fail")
        damaged = copy.deepcopy(receipt)
        damaged["decisions"][0]["parts"][0]["cuvExcerptSha256"] = "0" * 64
        self.assertEqual(self.checks(text, damaged)["cuv_exact_quote"], "fail")
        damaged = copy.deepcopy(receipt)
        damaged["decisions"].pop()
        self.assertEqual(self.checks(text, damaged)["cuv_exact_quote"], "fail")

    def test_plugin_hash_includes_shared_and_pinned_library_code(self):
        path = ROOT / "scripts/language_review_plugins/zh_hans_weekly_cuv.py"
        self.assertEqual([item.name for item in plugin_implementation_sources(path)],
                         ["zh_hans_weekly_cuv.py", "common.py", "cuv_scripture.py",
                          "build_scripture_index.py"])
        loaded = runpy.run_path(str(path))
        self.assertEqual(loaded["PLUGIN_ID"], plugin.PLUGIN_ID)


if __name__ == "__main__":
    unittest.main()
