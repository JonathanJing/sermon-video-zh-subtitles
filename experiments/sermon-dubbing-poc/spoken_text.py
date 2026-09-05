"""Deterministic pronunciation input; the reviewed display text is retained."""
import re

VERSION = "chinese-sermon-pronunciation-v1"
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


def spoken_text(text):
    # 祢 can be read as the surname mí by a general model. In this corpus it is
    # the second-person divine pronoun nǐ; 祂 and 他 are both tā.
    text = text.replace("祢", "你").replace("祂", "他")
    def replace(match):
        value = match.group()
        if len(value) == 4 and text[match.end():].startswith("年"):
            return "".join(DIGITS[int(d)] for d in value)
        return cardinal(value)
    return re.sub(r"(?<![A-Za-z0-9.])\d{1,4}(?![A-Za-z0-9.])", replace, text)
