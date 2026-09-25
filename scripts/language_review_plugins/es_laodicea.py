"""Source-bound neutral Latin American Spanish screens for Laodicea."""
from __future__ import annotations

try:
    from scripts.language_review_plugins.laodicea_common import review_reference_group
except ImportError:
    from language_review_plugins.laodicea_common import review_reference_group

PLUGIN_ID = "es-laodicea-v1"
PLUGIN_VERSION = "2026-09-20-blocks15-18-reference-only-v1"
REQUIRED = ["natural_spanish", "register_consistency", "proper_name_rendering",
            "scripture_edition", "number_reading", "tts_segmentation"]


def review_group(policy: dict, english_units: list[dict], group: dict) -> list[dict[str, str]]:
    return review_reference_group(
        policy, english_units, group, locale="es", required=REQUIRED, edition="RVR60-1960",
        script_pattern=r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]",
        register_forbidden=r"\b(?:vosotros|vosotras|sois|tenéis|habéis|vos)\b",
        chapter_forms=("capítulo 3", "capitulo 3", "3:"),
        verse_forms=("versículo 16", "versiculo 16", ":16"),
        names={"Laodicea": ("Laodicea",), "Starbucks": ("Starbucks",)},
    )
