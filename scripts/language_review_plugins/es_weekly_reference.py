"""Source-scoped Spanish reference-only Layer 2 structural checks."""
from __future__ import annotations

try:
    from scripts.language_review_plugins.weekly_reference_common import review_reference_only_group
except ImportError:
    from language_review_plugins.weekly_reference_common import review_reference_only_group

PLUGIN_ID = "es-weekly-reference-v1"
PLUGIN_VERSION = "2026-09-27-v1"
REQUIRED = ["natural_spanish", "register_consistency", "proper_name_rendering",
            "scripture_reference_only", "number_reading", "tts_segmentation"]


def review_group(policy: dict, english_units: list[dict], group: dict) -> list[dict[str, str]]:
    return review_reference_only_group(
        policy, english_units, group, locale="es", required=REQUIRED,
        script_pattern=r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]",
        forbidden_register=r"\b(?:vosotros|vosotras|sois|tenéis|habéis|vos)\b",
        forbidden_edition_claim=r"RVR\s*1960|RVR60|Reina[ -]Valera\s*1960",
    )
