"""Week-independent Spanish Layer 2 screens for a machine quality waiver."""
from __future__ import annotations

try:
    from scripts.language_review_plugins.auto_qc_text_common import REQUIRED, review_auto_group
except ImportError:  # Direct scripts/produce_target_language_candidate.py execution.
    from language_review_plugins.auto_qc_text_common import REQUIRED, review_auto_group

PLUGIN_ID = "es-weekly-auto-v1"
PLUGIN_VERSION = "2026-10-06-v1"
# Neutral Latin American public-sermon register: no vosotros forms.
FORBIDDEN_REGISTER = r"\b(?:vosotros|vosotras|os)\b|\b\w+(?:áis|éis)\b"


def review_group(policy: dict, english_units: list[dict], group: dict) -> list[dict[str, str]]:
    return review_auto_group(policy, english_units, group, locale="es",
                             forbidden_register=FORBIDDEN_REGISTER)
