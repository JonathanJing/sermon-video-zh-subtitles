"""Spanish machine screens bound to the 2026-10-17 Resi 15030286 source."""
from __future__ import annotations

try:
    from scripts.language_review_plugins.weekly_15030286_common import REQUIRED, review_15030286_group
except ImportError:
    from language_review_plugins.weekly_15030286_common import REQUIRED, review_15030286_group

PLUGIN_ID = "es-weekly-15030286-v3"
PLUGIN_VERSION = "2026-10-18-v3"
FORBIDDEN_REGISTER = (r"\b(?:vosotros|vosotras|os|sois|vais|vuestr[oa]s?)\b|\b\w+(?:áis|éis)\b"
                      r"|\b(?!(?:pa|par|an|lu)ís\b)\w+ís\b"
                      r"|\b[Uu]sted\b")  # this sermon uses tú/ustedes throughout (operator correction 2026-10-18)


def review_group(policy: dict, english_units: list[dict], group: dict) -> list[dict[str, str]]:
    return review_15030286_group(
        policy, english_units, group, locale="es", forbidden_register=FORBIDDEN_REGISTER)
