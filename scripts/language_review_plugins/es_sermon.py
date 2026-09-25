"""Source-bound neutral LatAm Spanish Layer 2 screens for the Sep 20 clip."""
from __future__ import annotations

try:
    from scripts.language_review_plugins.common import review_scoped_locale_group
except ImportError:  # Direct scripts/produce_target_language_candidate.py execution.
    from language_review_plugins.common import review_scoped_locale_group

PLUGIN_ID = "es-sermon-v1"
PLUGIN_VERSION = "2026-09-20-source-bound-v2"
REQUIRED = ["natural_spanish", "register_consistency", "proper_name_rendering",
            "scripture_edition", "number_reading", "tts_segmentation"]
EXCERPT_2 = ("has dejado tu primer amor", "a09d53f67149bbe1ae14d1546a4e209769c020a8e59d0d983758c81300bbfdb1")
EXCERPT_3 = ("unas pocas personas en Sardis que no han manchado sus vestiduras", "5423fb1a0dd6e8dfc6ec91650002377cb2f7bbef0bda8bba1e9b78328d166e95")
NUMBERS = {
    "three": ("tres", "tercero", "tercera", "3"), "seven": ("siete", "7"),
    "five": ("cinco", "5"), "two": ("dos", "2"),
    "2": ("dos", "2"), "3": ("tres", "3"),
    "4": ("cuatro", "4"), "44": ("cuarenta y cuatro", "44"),
}
NAMES = {"Ephesus": "Éfeso", "Sardis": "Sardis", "Jesus": "Jesús",
         "Satan": "Satanás"}


def review_group(policy: dict, english_units: list[dict], group: dict) -> list[dict[str, str]]:
    return review_scoped_locale_group(
        policy, english_units, group, locale="es", required=REQUIRED,
        edition="RVR60-1960", excerpt_2=EXCERPT_2, excerpt_3=EXCERPT_3,
        few_pattern=r"pocos|pocas", not_many_pattern=r"no (?:hay|son) muchos|muy pocos",
        script_pattern=r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]",
        register_forbidden=r"\b(?:vosotros|vosotras|sois|tenéis|habéis|vos)\b",
        names=NAMES, numbers=NUMBERS,
    )
