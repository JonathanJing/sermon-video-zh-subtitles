"""Week-independent Korean Layer 2 screens for a machine quality waiver."""
from __future__ import annotations

try:
    from scripts.language_review_plugins.auto_qc_text_common import REQUIRED, review_auto_group
except ImportError:  # Direct scripts/produce_target_language_candidate.py execution.
    from language_review_plugins.auto_qc_text_common import REQUIRED, review_auto_group

PLUGIN_ID = "ko-weekly-auto-v1"
PLUGIN_VERSION = "2026-10-06-v1"
FORBIDDEN_REGISTER = r"\b(?:너는|너희는|당신은)\b|하옵나이다|하겠사옵니다"


def review_group(policy: dict, english_units: list[dict], group: dict) -> list[dict[str, str]]:
    return review_auto_group(policy, english_units, group, locale="ko",
                             forbidden_register=FORBIDDEN_REGISTER)
