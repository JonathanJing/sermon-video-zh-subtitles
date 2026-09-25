"""Source-bound Simplified Chinese screens for the approved Laodicea clip."""
from __future__ import annotations

try:
    from scripts.language_review_plugins.laodicea_common import review_reference_group
except ImportError:
    from language_review_plugins.laodicea_common import review_reference_group

PLUGIN_ID = "zh-Hans-laodicea-v1"
PLUGIN_VERSION = "2026-09-20-blocks15-18-reference-only-v1"
REQUIRED = ["spoken_chinese", "cuv_exact_quote", "number_name_reading", "tts_segmentation"]


def review_group(policy: dict, english_units: list[dict], group: dict) -> list[dict[str, str]]:
    checks = review_reference_group(
        policy, english_units, group, locale="zh-Hans", required=REQUIRED, edition="CUV",
        script_pattern=r"[\u3400-\u9fff]", register_forbidden=r"\b(?:TODO|TBD|PLACEHOLDER)\b",
        chapter_forms=("第3章", "第三章", "3章"), verse_forms=("第16节", "第十六节", "16节"),
        names={"Laodicea": ("老底嘉",), "Starbucks": ("星巴克",)},
    )
    return checks
