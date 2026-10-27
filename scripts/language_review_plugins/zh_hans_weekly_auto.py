"""Week-independent Simplified Chinese Layer 2 screens (no source-bound unit rules)."""
from __future__ import annotations

try:
    from scripts.language_review_plugins.auto_qc_text_common import REQUIRED, review_auto_group
except ImportError:  # Direct scripts/produce_target_language_candidate.py execution.
    from language_review_plugins.auto_qc_text_common import REQUIRED, review_auto_group

PLUGIN_ID = "zh-Hans-weekly-auto-v1"
PLUGIN_VERSION = "2026-10-18-broadcast-v1"
FORBIDDEN_REGISTER = r"汝|尔等|尔们|吾辈"


def review_group(policy: dict, english_units: list[dict], group: dict) -> list[dict[str, str]]:
    return review_auto_group(policy, english_units, group, locale="zh-Hans",
                             forbidden_register=FORBIDDEN_REGISTER)
