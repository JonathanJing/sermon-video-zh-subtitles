"""TTS-only spoken forms that keep the written target unchanged (experiment helper)."""
from __future__ import annotations

# "撒但" is split by the Qwen3-TTS tokenizer/phonemizer: ASR heard "傻，但" / "洒，但"
# in 13 of 22 sentences. Speaking "魔鬼" fixed 22/22 recognitions while the subtitle keeps
# "撒但". Add further entries only with the same kind of before/after evidence.
DEFAULT_SPOKEN_FORMS = {"撒但": "魔鬼"}


def merge_spoken_forms(base: dict | None, targets: list[str]) -> dict[str, str]:
    """Apply a default only when at least one target contains the written form."""
    merged = dict(base or {})
    for written, spoken in DEFAULT_SPOKEN_FORMS.items():
        if any(written in target for target in targets):
            merged.setdefault(written, spoken)
    return merged
