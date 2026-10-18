"""Korean machine screens bound to the 2026-10-17 Resi 15030286 source."""
from __future__ import annotations

try:
    from scripts.language_review_plugins.weekly_15030286_common import REQUIRED, review_15030286_group
except ImportError:
    from language_review_plugins.weekly_15030286_common import REQUIRED, review_15030286_group

PLUGIN_ID = "ko-weekly-15030286-v1"
PLUGIN_VERSION = "2026-10-17-v1"
FORBIDDEN_REGISTER = r"\b(?:너는|너희는|당신은)\b|하옵나이다|하겠사옵니다"


def review_group(policy: dict, english_units: list[dict], group: dict) -> list[dict[str, str]]:
    return review_15030286_group(
        policy, english_units, group, locale="ko", forbidden_register=FORBIDDEN_REGISTER)
