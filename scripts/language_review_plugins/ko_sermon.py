"""Source-bound Korean Layer 2 screens for the 2026-09-20 fragment."""
from __future__ import annotations

try:
    from scripts.language_review_plugins.common import review_scoped_locale_group
except ImportError:  # Direct scripts/produce_target_language_candidate.py execution.
    from language_review_plugins.common import review_scoped_locale_group

PLUGIN_ID = "ko-sermon-v1"
PLUGIN_VERSION = "2026-09-20-source-bound-v2"
REQUIRED = ["natural_korean", "honorific_consistency", "proper_name_transliteration",
            "scripture_edition", "number_reading", "tts_segmentation"]
EXCERPT_2 = ("너의 처음 사랑을 버렸느니라", "43e5f031c464ee9445a423d7e2f34111fd398da5e85d7d6552bd7c47ee3475cd")
EXCERPT_3 = ("그 옷을 더럽히지 아니한 자 몇 명이 네게 있어", "8d0b8ee99d6df509092a54fb6b6165dbf08a7e2663867b6bb40729155f73421e")
NUMBERS = {
    "three": ("세", "셋", "삼", "3"), "seven": ("일곱", "칠", "7"),
    "five": ("다섯", "오", "5"), "two": ("두", "둘", "이", "2"),
    "2": ("이", "두", "2"), "3": ("삼", "세", "3"),
    "4": ("사", "네", "4"), "44": ("마흔네", "사십사", "44"),
}
NAMES = {"Ephesus": "에베소", "Sardis": "사데", "Jesus": "예수",
         "Satan": "사탄"}


def review_group(policy: dict, english_units: list[dict], group: dict) -> list[dict[str, str]]:
    return review_scoped_locale_group(
        policy, english_units, group, locale="ko", required=REQUIRED,
        edition="NKRV-1998", excerpt_2=EXCERPT_2, excerpt_3=EXCERPT_3,
        few_pattern=r"몇|소수", not_many_pattern=r"많지|적은|소수",
        script_pattern=r"[가-힣]",
        register_forbidden=r"\b(?:너는|너희는|당신은)\b|하옵나이다|하겠사옵니다",
        names=NAMES, numbers=NUMBERS,
    )
