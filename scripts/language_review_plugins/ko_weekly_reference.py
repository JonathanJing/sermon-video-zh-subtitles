"""Source-scoped Korean reference-only Layer 2 structural checks."""
from __future__ import annotations

try:
    from scripts.language_review_plugins.weekly_reference_common import review_reference_only_group
except ImportError:
    from language_review_plugins.weekly_reference_common import review_reference_only_group

PLUGIN_ID = "ko-weekly-reference-v1"
PLUGIN_VERSION = "2026-09-27-v1"
REQUIRED = ["natural_korean", "honorific_consistency", "proper_name_transliteration",
            "scripture_reference_only", "number_reading", "tts_segmentation"]


def review_group(policy: dict, english_units: list[dict], group: dict) -> list[dict[str, str]]:
    return review_reference_only_group(
        policy, english_units, group, locale="ko", required=REQUIRED,
        script_pattern=r"[가-힣]",
        forbidden_register=r"\b(?:너는|너희는|당신은)\b|하옵나이다|하겠사옵니다",
        forbidden_edition_claim=r"개역개정|NKRV(?:-1998)?",
    )
