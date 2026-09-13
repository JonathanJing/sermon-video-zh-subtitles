"""Deterministic pronunciation input; the reviewed display text is retained."""
import re

LEGACY_VERSION = "chinese-sermon-pronunciation-v1"
NUMBER_VERSION = "chinese-sermon-pronunciation-v2"
VERSION = "chinese-sermon-pronunciation-v3"
SUPPORTED_VERSIONS = frozenset({LEGACY_VERSION, NUMBER_VERSION, VERSION})
DIGITS = "零一二三四五六七八九"


def cardinal(number):
    n = int(number)
    if not 0 <= n < 10000:
        raise ValueError("Only bounded integer pronunciation is supported")
    if n == 0:
        return DIGITS[0]
    parts, zero = [], False
    for divisor, unit in [(1000, "千"), (100, "百"), (10, "十"), (1, "")]:
        digit, n = divmod(n, divisor)
        if digit:
            if zero:
                parts.append("零")
            if not (divisor == 10 and digit == 1 and not parts):
                parts.append(DIGITS[digit])
            parts.append(unit)
            zero = False
        elif parts and n:
            zero = True
    return "".join(parts)


def _spoken_text_v1(text):
    # Frozen jobs must retain the original behavior, including comma handling.
    # 祢 can be read as the surname mí by a general model. In this corpus it is
    # the second-person divine pronoun nǐ; 祂 and 他 are both tā.
    text = text.replace("祢", "你").replace("祂", "他")
    def replace(match):
        value = match.group()
        if len(value) == 4 and text[match.end():].startswith("年"):
            return "".join(DIGITS[int(d)] for d in value)
        return cardinal(value)
    return re.sub(r"(?<![A-Za-z0-9.])\d{1,4}(?![A-Za-z0-9.])", replace, text)


def _spoken_text_v2(text):
    text = text.replace("祢", "你").replace("祂", "他")

    def replace(match):
        value = match.group()
        grouped = "," in value
        if grouped and not re.fullmatch(r"[1-9][0-9]{0,2}(?:,[0-9]{3})+", value):
            return value
        digits = value.replace(",", "")
        # Consume the whole token before deciding whether its format/range is
        # supported. Never turn 10,000 or 5,300.50 into separately spoken parts.
        if not re.fullmatch(r"[0-9]{1,4}", digits):
            return value
        if not grouped and len(digits) == 4 and text[match.end():].startswith("年"):
            return "".join(DIGITS[int(d)] for d in digits)
        return cardinal(digits)

    return re.sub(r"(?<![A-Za-z\d_.,])\d+(?:,\d+)*(?:\.\d+)?(?![A-Za-z\d_.,])", replace, text)


def spoken_text(text, *, version=VERSION):
    """Normalize new speech or reproduce a frozen job's explicit rule version."""
    if version == LEGACY_VERSION:
        return _spoken_text_v1(text)
    if version == NUMBER_VERSION:
        return _spoken_text_v2(text)
    if version == VERSION:
        # CUV editorial brackets are silent; retain the words inside them.
        return _spoken_text_v2(text).replace("[", "").replace("]", "")
    raise ValueError("Unsupported pronunciation rule version")
