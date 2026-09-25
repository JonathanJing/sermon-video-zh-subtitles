"""Source-bound Korean screens for the approved Laodicea clip."""
from __future__ import annotations

try:
    from scripts.language_review_plugins.laodicea_common import review_reference_group
except ImportError:
    from language_review_plugins.laodicea_common import review_reference_group

PLUGIN_ID = "ko-laodicea-v1"
PLUGIN_VERSION = "2026-09-20-blocks15-18-reference-only-v1"
REQUIRED = ["natural_korean", "honorific_consistency", "proper_name_transliteration",
            "scripture_edition", "number_reading", "tts_segmentation"]


def review_group(policy: dict, english_units: list[dict], group: dict) -> list[dict[str, str]]:
    return review_reference_group(
        policy, english_units, group, locale="ko", required=REQUIRED, edition="NKRV-1998",
        script_pattern=r"[가-힣]", register_forbidden=r"\b당신은\b|하옵나이다|하겠사옵니다",
        chapter_forms=("3장", "삼 장"), verse_forms=("16절", "십육 절"),
        names={"Laodicea": ("라오디게아",), "Starbucks": ("스타벅스",)},
    )
