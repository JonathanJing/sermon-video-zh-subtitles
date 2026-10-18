#!/usr/bin/env python3
"""Back-transcribe every formal Layer 3 unit without granting human approval.

The renderer's original manifest remains immutable. This command writes a
separate ASR receipt and a screened manifest only after binding every unit to
the exact approved speech job and audio bytes. Uncertain ASR output stays in a
review queue; it cannot be promoted to a machine pass by a coverage count.
"""
from __future__ import annotations

import argparse
import copy
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import unicodedata
import tempfile
from typing import Callable

from .. import path_aliases
from ..source import sentence_interpretation as identity
from . import backend as _audio
from . import dev_profile, dev_receipts
from . import speech_job as speech


# v2 records the ASR runtime settings behind every score (v1 receipts stay readable).
SCHEMA = "sermon-target-language-audio-screening-v2"
# How a recognized text is scored against the expected text; part of the recorded runtime.
# Scoring identities. A receipt records the one it was scored under; v3 is the original
# unfolded scoring and stays reproducible so old receipts rescore exactly as recorded.
SCORING_V3 = ("token-sequence-ratio-v3; short units (<4 tokens) must match exactly; "
              "no negation, number or protected name may differ; numbers and names keep their order")
SCORING_V4 = ("token-sequence-ratio-v4; readings a listener cannot tell apart are folded first "
           "(spelled numbers and digits, same-pinyin-same-tone Chinese characters in fixed contexts, "
           "Spanish diacritic function words, Korean spacing; digit strings are not positional numbers; "
           "a Korean native numeral before a Sino counter is not folded); "
           "short units (<4 tokens) must match exactly; "
           "no negation, number or protected name may differ; numbers and names keep their order")
SCORING_V5 = SCORING_V4.replace("token-sequence-ratio-v4", "token-sequence-ratio-v5") + (
    "; book-anchored Korean scripture range endpoints are folded together")
SCORING = SCORING_V5.replace("token-sequence-ratio-v5", "token-sequence-ratio-v6") + (
    "; a Spanish digit string grouped by thousands points (2.700) or by two or more comma groups (1,000,000) "
    "is one number; "
    "comma decimals and numbers starting with 0 stay as written, their fractional digits unfolded")
KNOWN_SCORINGS = (SCORING_V3, SCORING_V4, SCORING_V5, SCORING)
MODEL = "Qwen/Qwen3-ASR-0.6B"
BATCH_SIZES = (1, 2, 4, 8)


def write_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())
        stream.flush()
        os.fsync(stream.fileno())
    try:
        # Publish a new immutable cache receipt, never replace a concurrent one.
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"Expected JSON object: {path}")
    return value


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


SCORING_IMPLEMENTATION_FILES = (
    "scripts/screen_target_language_audio_units.py",
    "packages/production/src/tongxing_production/audio/hosted.py",
    "packages/production/src/tongxing_production/audio/backend.py",
    "scripts/tongxing_host.py",
    "scripts/ko_spoken_numerals.py",
    "scripts/language_review_plugins/auto_qc_text_common.py",
    "scripts/language_review_plugins/common.py",
)
SCORING_PHYSICAL_FILES = path_aliases.physical_closure_paths(SCORING_IMPLEMENTATION_FILES)


def implementation_sha256(root: Path | None = None) -> str:
    """Current scoring closure; v5 single-file receipts require explicit rescreening."""
    # Each key names the actual file read, including the executed facade and
    # package target when a legacy path moved.
    checkout = root or _audio.current().core.repo_root
    digest = hashlib.sha256()
    for name in SCORING_PHYSICAL_FILES:
        digest.update(name.encode() + b"\0" + (checkout / name).read_bytes() + b"\0")
    return digest.hexdigest()


def current_scoring_identity_problems(settings: dict) -> list[str]:
    if settings.get("scoring") == SCORING and settings.get("implementationSha256") != implementation_sha256():
        return ["screening scoring implementation differs; rescreen with the current dependency closure"]
    return []


def tokens(value: str, locale: str) -> list[str]:
    folded = unicodedata.normalize("NFKC", value).casefold()
    if locale in {"zh-Hans", "ko"}:
        return [char for char in folded if char.isalnum()]
    return re.findall(r"[^\W_]+", folded, flags=re.UNICODE)


# A dub that drops or changes one of these reverses or alters its claim while
# the token ratio stays high ("not" in 13 words still scores 0.96), so an ASR
# difference that touches one never passes on the ratio alone.
NEGATIONS = {"en": ("no", "not", "never", "neither", "nor", "without", "cannot"),
             "zh-Hans": ("不", "没", "沒", "别", "未", "非", "无", "勿", "否"),
             "ko": ("아니", "않", "안", "못", "없"),
             "es": ("no", "ni", "nunca", "jamás", "jamas", "tampoco", "nadie", "nada", "ningún", "ningun",
                    "ninguno", "ninguna", "sin")}
ZH_NUMERALS = "〇零一二两三四五六七八九十百千万亿"
ES_NUMBERS = frozenset((
    "cero", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez", "once", "doce",
    "trece", "catorce", "quince", "dieciséis", "dieciseis", "diecisiete", "dieciocho", "diecinueve", "veinte",
    "treinta", "cuarenta", "cincuenta", "sesenta", "setenta", "ochenta", "noventa", "cien", "ciento",
    "doscientos", "trescientos", "cuatrocientos", "quinientos", "seiscientos", "setecientos", "ochocientos",
    "novecientos", "mil", "millón", "millon", "millones"))


def key_word(tokens: list[str], locale: str) -> bool:
    """Whether these tokens hold a negation or a number (Korean spelled numbers are not covered)."""
    joined = "".join(tokens)
    if any(char.isdigit() for char in joined):
        return True
    if locale in {"zh-Hans", "ko"}:
        return (any(marker in joined for marker in NEGATIONS.get(locale, ()))
                or locale == "zh-Hans" and any(char in ZH_NUMERALS for char in joined))
    return any(token in NEGATIONS.get(locale, ()) or token in ES_NUMBERS
               or locale == "es" and token.startswith("veinti") for token in tokens)


def _korean_spans(text: str, forms, *, sino: bool = False) -> list[tuple[int, int]]:
    from .hosted import rules
    found = sorted((match.start(), -len(form)) for form in forms
                   for match in re.finditer(rules._ko_pattern(form, sino=sino), text))
    spans, end = [], -1
    for start, negative_length in found:
        if start >= end:  # The longest form wins where two overlap.
            end = start - negative_length
            spans.append((start, end))
    return spans


def _korean_native_forms() -> list[str]:
    from .hosted import rules
    return [form for number in range(1, 100) for form in rules.korean_native(number)]


def korean_native_numbers(text: str) -> list[str]:
    """The native-number forms in ``text``, in reading order."""
    return [text[start:end] for start, end in _korean_spans(text, _korean_native_forms())]


def korean_number_spans(text: str) -> list[tuple[int, int]]:
    """Spoken Korean quantities in ``text``, in reading order, read as text QC reads them:
    native forms (두 사람, 스무 살) and Sino forms up to 999 (이십 년, 삼장). A bare
    one-syllable Sino form counts only attached to its counter, so 이 사람 is not a number."""
    from .hosted import rules
    native = _korean_spans(text, _korean_native_forms())
    sino = _korean_spans(text, {rules.korean_sino(number) for number in range(1, 1000)}, sino=True)
    return sorted({*native, *(span for span in sino
                              if not any(start < span[1] and span[0] < end for start, end in native))})


def protected_text_agrees(expected: str, recognized: str, locale: str, *, strip_punctuation: bool = False) -> bool:
    """Check whole numeral forms and names that cannot be identified from a partial diff."""
    from .hosted import rules
    # Scoring v4 turns punctuation into a space (apostrophes stay for can't / won't): ASR drops
    # commas, and a Sino numeral check that sees "일 그" on one side and "일, 그" on the other
    # would otherwise disagree. v3 receipts are rescored without it.
    left, right = (unicodedata.normalize("NFC", re.sub(r"[^\w\s'’]", " ", rules._fold(text)) if strip_punctuation
                                         else rules._fold(text)) for text in (expected, recognized))
    if locale == "en" and len(re.findall(r"\b[a-z]+n['’]t\b", left)) != len(re.findall(r"\b[a-z]+n['’]t\b", right)):
        return False
    if locale in {"zh-Hans", "ko", "es"}:
        def citations(text):
            if locale == "ko":
                # Keep raw Sino numeral groups: accent folding decomposes Hangul.
                return [match.groups() for match in rules._KO_CITATION.finditer(text)]
            return [(book, chapter, verse) for book, chapter, verse, _ in rules.book_citations(text, locale)]
        if citations(expected) != citations(recognized):
            return False
    if locale == "en" and rules.english_numbers(expected) != rules.english_numbers(recognized):
        return False
    if locale == "ko":
        counters = "|".join(rules._KO_COUNTERS)
        pattern = r"(?<![가-힣])[영공일이삼사오육칠팔구십백천만억]+(?=\s*(?:" + counters + r")|\s|$)"
        if re.findall(pattern, left) != re.findall(pattern, right):
            return False
        # In order: 두 아들과 세 딸 heard as 세 아들과 두 딸 keeps every count.
        if korean_native_numbers(left) != korean_native_numbers(right):
            return False
    if locale == "es":
        # Un and una are usually articles, so a changed form (un/una) is ASR
        # noise; losing or gaining one can still drop the quantity "one".
        ones = r"(?<!\w)(?:uno|una|un)(?!\w)"
        if len(re.findall(ones, left)) != len(re.findall(ones, right)):
            return False
    books = (rules._EN_BOOK_CODES if locale == "en" else rules._ES_BOOK_CODES if locale == "es"
             else rules._KO_BOOK_CODES if locale == "ko" else rules._ZH_BOOK_CODES)
    names = {key[-1] if isinstance(key, tuple) else key for key in books}
    names.update({"en": ("Jesus", "God"), "es": ("Jesús", "Dios"),
                  "ko": ("예수", "하나님"), "zh-Hans": ("耶稣", "神")}.get(locale, ()))
    if locale in {"en", "es"}:
        # The approved script supplies names; ASR capitalization is irrelevant.
        names.update(term for term in re.findall(r"\b[A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ]+", expected)
                     if term.casefold() not in {"the", "he", "she", "we", "you", "they", "it", "this", "that",
                                                "some", "let", "in", "on", "for", "during", "when", "if",
                                                "el", "la", "los", "las", "un", "una", "él", "ella", "hoy", "en"})
    pattern = "|".join(re.escape(unicodedata.normalize("NFC", rules._fold(name)))
                       for name in sorted(names, key=len, reverse=True))
    if locale in {"en", "es"}:
        pattern = r"(?<!\w)(?:" + pattern + r")(?!\w)"
    # Order matters too: exchanging two names preserves counts but changes who did what.
    return re.findall(pattern, left) == re.findall(pattern, right)


# --- Reading-equivalent folding ----------------------------------------------------
# An ASR transcript is compared with what a listener hears, so spellings a listener
# cannot tell apart are folded to one form before scoring: spelled numbers and digits
# (二十七亿 / 27亿, 삼분의 일 / 3분의 1, diez / 10), Chinese characters that share
# pinyin and tone, Spanish diacritic function words (él / el) and Korean spacing.
#
# The rule for every fold is the same: it must never merge two readings a listener can
# tell apart. So a fold applies only where the reading is unambiguous:
#   - Chinese 地/得/的 are not folded (土地 and 得到 are dì and dé);
#   - 只 becomes 支 only as a measure word after a numeral (七只号角), not in 只是;
#   - Spanish accents are removed only on the function-word pairs that differ only by
#     the diacritic tilde, never on stress accents (practicó / práctico stay apart);
#   - Spanish and Chinese scales nest by multiplication (dos mil millones, 万亿);
#   - a run of digit syllables is never read as a positional number (십일 vs 일일);
#   - a Korean native numeral before a Sino-read counter (여덟 장 for 8장) is a misread
#     chapter, not a spelling, and stays as the ASR heard it.

_ZH_DIGIT_VALUES = {"〇": 0, "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
                    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_ZH_SMALL_UNITS = {"十": 10, "百": 100, "千": 1000}
_ZH_BIG_UNITS = {"万": 10_000, "亿": 100_000_000}
_ZH_NUMERAL_CHARS = "".join(_ZH_DIGIT_VALUES) + "".join(_ZH_SMALL_UNITS) + "".join(_ZH_BIG_UNITS)
_ZH_NUMERAL_RUN = re.compile("[" + _ZH_NUMERAL_CHARS + "]+")
_ZH_DIGITS_WITH_UNIT = re.compile(r"(\d+)([万亿])")
# Same pinyin and tone, no polyphone among them: a dub cannot voice the difference.
_ZH_HOMOPHONES = str.maketrans({"她": "他", "它": "他", "祂": "他", "牠": "他", "忿": "愤", "再": "在"})
# Context-bound folds: 作出/做出 (zuò), and 只 as the measure word zhī after a numeral.
_ZH_CONTEXT_FOLDS = ((re.compile("作出"), "做出"), (re.compile(r"(?<=[0-9])只"), "支"))

_KO_SINO_VALUES = {"영": 0, "공": 0, "일": 1, "이": 2, "삼": 3, "사": 4, "오": 5,
                   "육": 6, "칠": 7, "팔": 8, "구": 9}
_KO_SINO_SMALL = {"십": 10, "백": 100, "천": 1000}
_KO_SINO_BIG = {"만": 10_000, "억": 100_000_000}
_KO_SINO_CHARS = "".join(_KO_SINO_VALUES) + "".join(_KO_SINO_SMALL) + "".join(_KO_SINO_BIG)
_KO_SINO_RUN = re.compile("[" + _KO_SINO_CHARS + "]+")
# Counters read with Sino numerals (삼장, 일 년, 이억 명); a native numeral before one of
# these is a misreading and is never folded.
_KO_SINO_COUNTERS = ("장", "절", "년", "월", "일", "분", "초", "층", "배", "회", "퍼센트", "주", "권", "세",
                     "억", "만", "학년", "교시", "원", "도", "호", "편", "항")
# 이 is also "this", so it counts only before a counter that cannot follow 이-the-word.
_KO_I_COUNTERS = ("년", "월", "장", "절", "층", "배", "초", "회", "퍼센트", "억", "만", "학년", "교시", "호", "편", "항")
# What may follow a complete Sino number besides a counter or a space: a particle.
_KO_PARTICLES = ("은", "는", "을", "를", "의", "에", "도", "만", "로", "으로", "부터", "까지", "과", "와", "이나", "이면")
# Counters read with native numerals (두 명, 세 사람, 네 번째, 열 가지).
_KO_NATIVE_COUNTERS = ("명", "개", "사람", "가지", "살", "시", "번", "달", "마리", "잔", "병",
                       "송이", "켤레", "그릇", "조각", "군데", "차례", "줄", "통")
_KO_NATIVE_VALUES = {"하나": 1, "한": 1, "둘": 2, "두": 2, "셋": 3, "세": 3, "석": 3, "넷": 4, "네": 4, "넉": 4,
                     "다섯": 5, "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9}
_KO_NATIVE_TENS_VALUES = {"열": 10, "스물": 20, "스무": 20, "서른": 30, "마흔": 40, "쉰": 50,
                          "예순": 60, "일흔": 70, "여든": 80, "아흔": 90}
_KO_FRACTION = re.compile(r"(\d+|[" + _KO_SINO_CHARS + r"]+?)\s*분의\s*(\d+|[영일이삼사오육칠팔구](?:십[영일이삼사오육칠팔구]?)?|십[영일이삼사오육칠팔구]?)")
_KO_DIGITS_WITH_UNIT = re.compile(r"(\d+)\s*([만억])")

_ES_UNIT_VALUES = {"cero": 0, "uno": 1, "un": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
                   "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12,
                   "trece": 13, "catorce": 14, "quince": 15, "dieciseis": 16, "diecisiete": 17,
                   "dieciocho": 18, "diecinueve": 19, "veinte": 20, "veintiuno": 21, "veintiun": 21,
                   "veintiuna": 21, "veintidos": 22, "veintitres": 23, "veinticuatro": 24,
                   "veinticinco": 25, "veintiseis": 26, "veintisiete": 27, "veintiocho": 28, "veintinueve": 29}
_ES_TENS_VALUES = {"treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60, "setenta": 70,
                   "ochenta": 80, "noventa": 90}
_ES_HUNDREDS_VALUES = {"cien": 100, "ciento": 100, "doscientos": 200, "doscientas": 200, "trescientos": 300,
                       "trescientas": 300, "cuatrocientos": 400, "cuatrocientas": 400, "quinientos": 500,
                       "quinientas": 500, "seiscientos": 600, "seiscientas": 600, "setecientos": 700,
                       "setecientas": 700, "ochocientos": 800, "ochocientas": 800, "novecientos": 900,
                       "novecientas": 900}
# Words that differ from their unaccented twin only by the diacritic tilde. ASR spells the
# tilde inconsistently and the segments are the same. Stress accents (practicó / práctico,
# está / esta) are not here: they change the word a listener hears.
_ES_DIACRITIC_PAIRS = {"él": "el", "tú": "tu", "mí": "mi", "sí": "si", "té": "te", "dé": "de", "sé": "se",
                       "más": "mas", "aún": "aun", "qué": "que", "quién": "quien", "quiénes": "quienes",
                       "cuál": "cual", "cuáles": "cuales", "cómo": "como", "cuándo": "cuando",
                       "cuánto": "cuanto", "cuánta": "cuanta", "cuántos": "cuantos", "cuántas": "cuantas",
                       "dónde": "donde", "adónde": "adonde"}


def _unaccent(word: str) -> str:
    return "".join(char for char in unicodedata.normalize("NFKD", word) if not unicodedata.combining(char))


def _positional_value(run: str, digit_values: dict, small_units: dict, big_units: dict, *,
                      nested_big: bool = False) -> int | None:
    """Value of a Chinese or Sino-Korean numeral run (二十七亿, 八十一, 삼백), or ``None``
    when the run is not one positional number.

    A run of two or more digit syllables with no unit (一一, 일일) is a digit string, not a
    positional number, and is refused so it can never equal 十一 / 십일. A big unit applies
    to the digits before it; written directly after another big unit with no digits it
    multiplies what came before (万亿 = 10¹²) when ``nested_big`` allows it. Big units must
    descend (一亿一万), and a run may not start with one.
    """
    total = section = 0
    digits = ""
    last_big = None
    has_unit = False
    previous_big = False
    for char in run:
        if char in digit_values:
            if digit_values[char] == 0 and (total or section):
                continue  # 零 inside a positional number only marks a skipped place (一百零五).
            digits += str(digit_values[char])
            previous_big = False
        elif char in small_units:
            if len(digits) > 1:
                return None
            section += (int(digits) if digits else 1) * small_units[char]
            digits, has_unit, previous_big = "", True, False
        else:
            unit = big_units[char]
            has_unit = True
            if digits or section:
                if len(digits) > 1 and not section:
                    return None
                section += int(digits) if digits else 0
                if last_big is not None and unit >= last_big:
                    return None
                total += section * unit
                section, digits, last_big, previous_big = 0, "", unit, True
            elif nested_big and previous_big and last_big is not None and unit > last_big:
                total *= unit
                last_big = unit
            else:
                return None
    if not has_unit:
        return int(digits) if len(digits) == 1 else None
    return total + section + (int(digits) if digits else 0)


def _fold_chinese(text: str) -> str:
    from .hosted import rules
    text = _ZH_DIGITS_WITH_UNIT.sub(lambda m: str(int(m.group(1)) * _ZH_BIG_UNITS[m.group(2)]), text)

    def numeral(match: re.Match) -> str:
        run, rest = match.group(), text[match.end():]
        if len(run) == 1 and run not in _ZH_DIGIT_VALUES:
            return run  # A lone unit (十分, 万一) is a word, not a number.
        if len(run) == 1 and not re.match(rules._ZH_MEASURE_WORDS, rest):
            return run  # A lone digit is a number only before a measure word (一名, 两个).
        if len(run) == 4 and rest.startswith("年") and run[0] in "二一" and all(c in _ZH_DIGIT_VALUES for c in run):
            return "".join(str(_ZH_DIGIT_VALUES[c]) for c in run)  # 二〇二六年: years are read digit by digit.
        value = _positional_value(run, _ZH_DIGIT_VALUES, _ZH_SMALL_UNITS, _ZH_BIG_UNITS, nested_big=True)
        return run if value is None else str(value)
    text = _ZH_NUMERAL_RUN.sub(numeral, text).translate(_ZH_HOMOPHONES)
    for pattern, replacement in _ZH_CONTEXT_FOLDS:
        text = pattern.sub(replacement, text)
    return text


def _ko_followed_by(text: str, end: int, counters) -> bool:
    rest = text[end:].lstrip()
    return any(rest.startswith(counter) for counter in counters)


def _ko_native_pattern() -> re.Pattern:
    units = "|".join(sorted(_KO_NATIVE_VALUES, key=len, reverse=True))
    tens = "|".join(sorted(_KO_NATIVE_TENS_VALUES, key=len, reverse=True))
    # 열다섯, 열 다섯, 스무, 마흔네: a tens form, a unit form, or both, then a native counter.
    return re.compile(r"(?<![가-힣])(?:(" + tens + r")\s*(" + units + r")?|(" + units + r"))"
                      r"(?=\s*(?:" + "|".join(_KO_NATIVE_COUNTERS) + "))")


def _fold_korean(text: str, *, citation_ranges: bool = True) -> str:
    def sino_value(part: str) -> str | None:
        if part.isdigit():
            return part
        value = _positional_value(part, _KO_SINO_VALUES, _KO_SINO_SMALL, _KO_SINO_BIG)
        return None if value is None else str(value)

    def fraction(match: re.Match) -> str:
        parts = [sino_value(match.group(1)), sino_value(match.group(2))]
        return match.group() if None in parts else f"{parts[0]}분의 {parts[1]}"
    if citation_ranges:
        # Fold only a complete, book-anchored citation chain. In a single-counter
        # range 삼-사장 the first one-syllable endpoint has no counter of its own.
        # Do not grant that interpretation to bare words or ordinary counters.
        from .hosted import rules
        from .hosted import ko_spoken_numerals as _ko
        _PARTICLES, _CONNECTOR, _RANGE_PARTICLE, _DELIMITERS, bare_context_allowed, _NUMERIC_TOKEN = (
            _ko._PARTICLES, _ko._CONNECTOR, _ko._RANGE_PARTICLE, _ko._DELIMITERS, _ko.bare_context_allowed, _ko._NUMERIC_TOKEN)
        # ASR may space an already registered compound connector internally.
        asr_connector = re.sub(r"(?<=[가-힣])(?=[가-힣])", lambda _: r"\s*", _CONNECTOR)
        asr_terminal = re.sub(r"(?<=[가-힣])(?=[가-힣])", lambda _: r"\s*", _RANGE_PARTICLE)
        def asr_book(name):
            return r"\s*".join(re.escape(char) for char in name)
        books = "|".join(asr_book(name) for name in sorted(rules._KO_BOOK_CODES, key=len, reverse=True))
        number = r"(?:\d{1,3}|[" + _KO_SINO_CHARS + r"]+(?:\s+[" + _KO_SINO_CHARS + r"]+)*)"
        def citation_pattern(book, counter, opening="", closing=""):
            boundary = (r"(?=$|[^가-힣A-Za-z0-9]|" + _PARTICLES + r"|" + asr_connector + r"?\s*"
                        + number + r"(?:\s*[-~–]\s*" + number + r")?\s*" + counter + r")")
            reference = number + r"(?:\s*[-~–]\s*" + number + r")?\s*" + counter + boundary
            return re.compile(r"(?<![가-힣A-Za-z0-9])(" + book + r")" + ((r"\s*" + re.escape(opening)) if opening else "") + r"(\s*" + reference
                              + r"(?:\s*" + asr_connector + r"?\s*" + reference + r")*)"
                              + r"(\s*" + asr_terminal + r")?" + ((r"\s*" + re.escape(closing)) if closing else ""))
        citation_number = re.compile(r"(" + number + r")(?:(\s*[-~–]\s*)(" + number + r"))?(\s*)(장|절|편)")
        def fold_number(match):
            first, dash, second, space, counter = match.groups()
            def spaced_value(part):
                compact = re.sub(r"\s+", "", part)
                value = str(int(compact)) if compact.isdigit() else sino_value(compact)
                # New spaced spellings must be one canonical positional number,
                # never additive malformed units or a sequence of endpoints.
                if value is not None and compact != part and not compact.isdigit():
                    if rules.korean_sino(int(value)) != compact:
                        return None
                return value
            left = spaced_value(first)
            right = spaced_value(second) if second else None
            if left is None or second and right is None:
                return match.group()
            return left + ((dash + right) if second else "") + space + counter
        citation_atom = re.compile(asr_connector + "|" + citation_number.pattern)
        def fold_citation(match, opening="", closing=""):
            # Consume complete connectors before numeric atoms: 이나/이든 and
            # 부터만 must not turn their 이/만 syllables into numbers.
            return re.sub(r"\s+", "", match.group(1)) + opening + citation_atom.sub(
                lambda atom: re.sub(r"\s+", "", atom.group()) if atom.group(1) is None else fold_number(atom), match.group(2)) + re.sub(r"\s+", "", match.group(3) or "") + closing
        for opening, closing in _DELIMITERS:
            for book, counter in ((books, r"(?:장|절)"), (asr_book("시편"), r"(?:장|절|편)")):
                text = citation_pattern(book, counter, opening, closing).sub(
                    lambda match: fold_citation(match, opening, closing), text)
        # v3 spoken rules also emit bare chapter/verse ranges. Fold their first
        # endpoint under the same conservative context, never arbitrary counters.
        protected = [match.span() for match in _NUMERIC_TOKEN.finditer(text)]
        text = citation_pattern("", r"(?:장|절)").sub(
            lambda match: fold_citation(match)
            if bare_context_allowed(text, match.start(), match.end())
            and not any(start <= match.start() < end for start, end in protected)
            else match.group(), text)

    text = _KO_FRACTION.sub(fraction, text)
    text = _KO_DIGITS_WITH_UNIT.sub(lambda m: str(int(m.group(1)) * _KO_SINO_BIG[m.group(2)]), text)

    def sino(match: re.Match) -> str:
        run, start, end = match.group(), match.start(), match.end()
        if start and "가" <= text[start - 1] <= "힣":
            return run  # Inside a word (사람이, 위의): not a numeral.
        has_unit = any(char in _KO_SINO_SMALL or char in _KO_SINO_BIG for char in run)
        counters = _KO_I_COUNTERS if run == "이" else _KO_SINO_COUNTERS
        following = text[end:end + 1]
        inside_word = bool(following) and "가" <= following <= "힣" and not _ko_followed_by(
            text, end, _KO_SINO_COUNTERS + _KO_PARTICLES)
        if inside_word:
            return run  # 천사 (angel) is not 1004; 사람 is not 4람.
        if (has_unit and len(run) > 1) or _ko_followed_by(text, end, counters):
            value = sino_value(run)
            return run if value is None else value
        return run
    text = _KO_SINO_RUN.sub(sino, text)

    def native(match: re.Match) -> str:
        tens, unit, lone = match.groups()
        return str(_KO_NATIVE_TENS_VALUES.get(tens, 0) + _KO_NATIVE_VALUES.get(unit or lone or "", 0))
    return _ko_native_pattern().sub(native, text)


def _take_spanish_cardinal(pieces: list[str], index: int) -> tuple[int | None, int]:
    """``(value, stop)`` for the digits or spelled cardinal starting at ``pieces[index]``
    (doscientos millones, treinta y uno, 10, una), or ``(None, index)``.

    Scales nest the Spanish way: ``mil`` multiplies the hundreds before it, and
    ``millón/millones`` multiplies everything counted before it in that group, so
    ``dos mil millones`` is 2 000 000 000 and ``un millón dos mil`` is 1 002 000.
    ``stop`` follows the last number word, never a trailing space or a dangling ``y``.
    """
    i, total, thousands, section = index, 0, 0, 0
    consumed = after_y = thousands_used = millions_used = False
    stop = index
    while i < len(pieces):
        piece = pieces[i]
        word = _unaccent(piece.casefold())
        if consumed and re.fullmatch(r"\s+", piece):
            i += 1
            continue
        if word.isdigit() and not consumed:
            section = int(word)
        elif word in _ES_HUNDREDS_VALUES and section == 0 and not after_y:
            section = _ES_HUNDREDS_VALUES[word]
        elif word in _ES_TENS_VALUES and section % 100 == 0 and not after_y:
            section += _ES_TENS_VALUES[word]
        elif word in _ES_UNIT_VALUES and (after_y and 1 <= _ES_UNIT_VALUES[word] <= 9
                                          or not after_y and section % 100 == 0):
            section += _ES_UNIT_VALUES[word]
            after_y = False
        elif word == "y" and consumed and not after_y and section % 10 == 0 and 30 <= section % 100 <= 90:
            after_y = True
            i += 1
            continue
        elif word == "mil" and not after_y and not thousands_used:
            thousands, section, thousands_used = (section or 1) * 1000, 0, True
        elif word in ("millon", "millones") and not after_y and not millions_used and (consumed or word == "millon"):
            total += ((thousands + section) or 1) * 1_000_000
            thousands = section = 0
            thousands_used, millions_used = False, True
        else:
            break
        consumed = True
        i += 1
        stop = i
    if not consumed:
        return None, index
    return total + thousands + section, stop


# ASR writes 2 700 000 000 as "2.700 millones" (Spanish thousands point) or "2,700 millones";
# a spelled "dos mil setecientos millones" folds to the same value only if the groups join.
# Spanish writes decimals with a comma (0,001 %, 1,500 millones = 1.5 million), so a single
# comma group is never joined, even before a scale word: only a point-grouped number (2.700,
# 1.000.000) or a comma-grouped one with two or more groups (1,000,000) is. A number starting
# with 0 never joins (0.001), and neither does an incomplete group (2,7, 3,14, 1,234,56).
# A unit whose primary ASR wrote "2,700 millones" is then settled by the secondary ASR.
_ES_POINT_GROUPS = re.compile(r"(?<![\d.,])[1-9]\d{0,2}(?:\.\d{3})+(?![\d]|[.,]\d)")
_ES_COMMA_GROUPS = re.compile(r"(?<![\d.,])[1-9]\d{0,2}(?:,\d{3}){2,}(?![\d]|[.,]\d)")


def _join_spanish_groups(text: str) -> str:
    join = lambda match: re.sub(r"[.,]", "", match.group())
    for pattern in (_ES_POINT_GROUPS, _ES_COMMA_GROUPS):
        text = pattern.sub(join, text)
    return text


def _fold_spanish(text: str, *, grouped_digits: bool = True) -> str:
    if grouped_digits:
        text = _join_spanish_groups(text)
    text = re.sub(r"(\d+)\s*%", r"\1 por 100", text)  # 10% is read "diez por ciento".
    pieces = re.findall(r"[^\W_]+|[\W_]+", text)
    index, out = 0, []
    while index < len(pieces):
        # v6: the digits after a decimal comma or point are a fraction, not a cardinal; folding
        # "001" to 1 would make 0,001 equal 0,1.
        fraction = (grouped_digits and index >= 2 and pieces[index].isdigit() and pieces[index - 1] in (",", ".")
                    and pieces[index - 2][-1:].isdigit())
        value, stop = (None, index) if fraction else _take_spanish_cardinal(pieces, index)
        if value is None:
            piece = pieces[index]
            out.append(_ES_DIACRITIC_PAIRS.get(piece.casefold(), piece))
            index += 1
        else:
            out.append(str(value))
            index = stop
    return "".join(out)


def fold_transcript(text: str, locale: str, *, citation_ranges: bool = True, grouped_digits: bool = True) -> str:
    """One spelling for readings a listener cannot tell apart; see the notes above."""
    text = unicodedata.normalize("NFKC", text)
    if locale == "zh-Hans":
        return _fold_chinese(text)
    if locale == "ko":
        return _fold_korean(text, citation_ranges=citation_ranges)
    if locale == "es":
        return _fold_spanish(text, grouped_digits=grouped_digits)
    return text


def score(expected: str, recognized: str, locale: str, min_similarity: float,
          scoring: str | None = None) -> tuple[float, list[dict], bool]:
    """``(similarity, differences, passed)`` for one unit, as recorded in the receipt.

    ``scoring`` names the scoring identity of the receipt being reproduced; the default
    is the current one. A receipt recorded under an earlier identity is rescored by that
    identity, so reading old evidence never silently applies newer folding.
    """
    scoring = SCORING if scoring is None else scoring
    if scoring not in KNOWN_SCORINGS:
        raise ValueError("Unknown ASR scoring identity: " + str(scoring))
    folded = scoring != SCORING_V3
    if folded:
        expected, recognized = (fold_transcript(text, locale, citation_ranges=scoring in (SCORING_V5, SCORING),
                                                grouped_digits=scoring == SCORING)
                                for text in (expected, recognized))
    expected_tokens, actual_tokens = tokens(expected, locale), tokens(recognized, locale)
    matcher = difflib.SequenceMatcher(None, expected_tokens, actual_tokens, autojunk=False)
    similarity = round(matcher.ratio(), 6)
    differences = [{"kind": kind,
                    "expected": expected_tokens[left_start:left_end],
                    "recognized": actual_tokens[right_start:right_end]}
                   for kind, left_start, left_end, right_start, right_end
                   in matcher.get_opcodes() if kind != "equal"]
    # Short units are more vulnerable to a high score hiding one material
    # missing word, so require exact normalized ASR for them.
    # Character tokens cannot distinguish 12-3 from 1-23. New Korean scoring
    # preserves complete digit runs and range structure only inside anchored citations.
    def number_structure(text):
        from .hosted import ko_spoken_numerals as _ko
        _CITATIONS, _CONNECTOR, _RANGE_PARTICLE, bare_citation_matches = (
            _ko._CITATIONS, _ko._CONNECTOR, _ko._RANGE_PARTICLE, _ko.bare_citation_matches)
        def with_terminal_marker(match):
            marker = re.match(r"\s*(" + _RANGE_PARTICLE + r")", text[match.end():])
            return match.group() + (re.sub(r"\s+", "", marker.group(1)) if marker else "")
        anchored = [match for pattern in _CITATIONS for match in pattern.finditer(text)]
        bare = [match for match in bare_citation_matches(text)
                if not any(book.start() <= match.start() < book.end() for book in anchored)]
        spans = sorted((match.start(), with_terminal_marker(match)) for match in anchored + bare)
        return [["-" if item in "-~–" else item
                 for item in re.findall(r"\d+|" + _RANGE_PARTICLE + "|" + _CONNECTOR + r"|장|절|편", citation) if item != ","]
                for _, citation in spans]
    structure_agrees = (scoring not in (SCORING_V5, SCORING) or locale != "ko"
                        or number_structure(expected) == number_structure(recognized))
    passed = (structure_agrees and similarity >= min_similarity and (len(expected_tokens) >= 4 or not differences)
              and not any(key_word(row["expected"], locale) or key_word(row["recognized"], locale)
                          for row in differences)
              and protected_text_agrees(expected, recognized, locale, strip_punctuation=folded))
    return similarity, differences, passed


def screen(job: dict, manifest: dict, artifact_root: Path,
           transcribe: Callable[[Path, str], str] | None, *, model: str,
           model_revision: str, min_similarity: float = 0.88,
           batch_size: int = 1, transcribe_batch: Callable | None = None,
           unit_cache: Path | None = None,
           inference_identity: dict | None = None) -> tuple[dict, dict]:
    require(0 < min_similarity <= 1, "Invalid ASR similarity threshold")
    require(type(batch_size) is int and batch_size in BATCH_SIZES,
            "ASR batch size must be 1, 2, 4 or 8")
    require(callable(transcribe_batch) or (batch_size == 1 and callable(transcribe)),
            "ASR batching requires a batch transcriber")
    job_hash, manifest_hash = identity.json_sha256(job), identity.json_sha256(manifest)
    original_job, original_manifest = job, manifest
    job, manifest = copy.deepcopy(job), copy.deepcopy(manifest)
    require(job.get("schemaVersion") in speech.SPEECH_JOB_SCHEMAS
            and job.get("status") == "prepared_for_target_language_speech"
            and job.get("synthesisEligible") is True,
            "Formal synthesis-eligible speech job required")
    locale = job["targetLocale"]
    require(manifest.get("schemaVersion") == "sermon-target-language-render-manifest-v1"
            and manifest.get("targetLocale") == locale
            and manifest.get("targetLanguageSpeechJobJsonSha256") == identity.json_sha256(job)
            and manifest.get("englishSourcePackageJsonSha256")
            == job["inputs"]["englishSourcePackage"]["jsonSha256"]
            and manifest.get("targetLanguageCandidateJsonSha256")
            == job["inputs"]["targetLanguageCandidate"]["jsonSha256"],
            "Render manifest differs from formal speech job")
    require(manifest.get("machineScreening", {}).get("status") == "not_run"
            and "machineScreeningReceipt" not in manifest,
            "Screen only an unmodified renderer manifest")
    rows = manifest.get("units")
    require(isinstance(rows, list) and rows and len(rows) == len(job["units"]),
            "Render manifest does not cover all job units")
    track = manifest.get("track", {})
    track_path = (artifact_root / track.get("path", "")).resolve()
    require(track_path.is_relative_to(artifact_root.resolve())
            and track_path.is_file() and file_sha(track_path) == track.get("sha256"),
            "Rendered track hash mismatch")
    requests, recognized_units = [], {}
    for index, (unit, row) in enumerate(zip(job["units"], rows)):
        group_id = unit["translationGroupId"]
        expected_hash = hashlib.sha256(unit["text"].encode("utf-8")).hexdigest()
        audio = row.get("audio", {})
        expected_path = (artifact_root / unit["outputRelativePath"]).resolve()
        require(row.get("textGroupId") == group_id
                and row.get("targetTextSha256") == expected_hash
                and audio.get("path") == unit["outputRelativePath"]
                and expected_path.is_relative_to(artifact_root.resolve())
                and expected_path.is_file() and file_sha(expected_path) == audio.get("sha256"),
                f"ASR unit identity or audio hash mismatch: {index}")
        requests.append({"path": expected_path, "identity": {
            "unitIndex": index, "textGroupId": group_id, "targetLocale": locale,
            "targetTextSha256": expected_hash, "audioSha256": audio["sha256"],
            "speechJobJsonSha256": job_hash, "model": model, "modelRevision": model_revision,
            "batchSize": batch_size, "maxNewTokens": 2048,
            "dtype": "bfloat16", "executionDevice": "cuda:0",
            "implementationSha256": implementation_sha256(),
            "runtime": copy.deepcopy(inference_identity or {}),
            "protocol": "formal-back-asr-batch-v1"}})
    require(len({row["identity"]["textGroupId"] for row in requests}) == len(requests),
            "ASR units contain duplicate groups")
    if unit_cache is not None:
        require(unit_cache.resolve().is_relative_to(artifact_root.resolve()),
                "ASR unit cache must live inside the artifact root")
        for request in requests:
            index = request["identity"]["unitIndex"]
            path = unit_cache / f"unit-{index:04d}.json"
            if path.exists():
                saved = load(path)
                require(saved.get("identity") == request["identity"]
                        and isinstance(saved.get("recognized"), str)
                        and saved.get("recognizedSha256") == hashlib.sha256(saved["recognized"].encode()).hexdigest(),
                        "ASR cached unit identity or result hash differs")
                recognized_units[index] = saved["recognized"]
    for start in range(0, len(requests), batch_size):
        batch = [row for row in requests[start:start + batch_size]
                 if row["identity"]["unitIndex"] not in recognized_units]
        if not batch:
            continue
        require(all(file_sha(row["path"]) == row["identity"]["audioSha256"] for row in batch),
                "ASR batch audio changed before transcription")
        if transcribe_batch is not None:
            values = transcribe_batch(copy.deepcopy(batch))
            require(isinstance(values, list) and len(values) == len(batch),
                    "ASR batch output cardinality differs")
            require(all(isinstance(value, dict) and value.get("identity") == request["identity"]
                        and isinstance(value.get("recognized"), str)
                        for value, request in zip(values, batch)),
                    "ASR batch output identity/order differs")
        else:
            text = transcribe(batch[0]["path"], locale)
            require(isinstance(text, str), "ASR transcription must be text")
            values = [{"identity": batch[0]["identity"], "recognized": text}]
        require(all(file_sha(row["path"]) == row["identity"]["audioSha256"] for row in batch)
                and identity.json_sha256(original_job) == job_hash
                and identity.json_sha256(original_manifest) == manifest_hash,
                "Frozen ASR batch inputs changed during transcription")
        for value in values:
            index = value["identity"]["unitIndex"]
            recognized_units[index] = value["recognized"]
            if unit_cache is not None:
                path = unit_cache / f"unit-{index:04d}.json"
                require(not path.exists(), "ASR unit cache cannot overwrite a receipt")
                write_atomic(path, {**value, "recognizedSha256": hashlib.sha256(value["recognized"].encode()).hexdigest()})
    require(len(recognized_units) == len(requests)
            and identity.json_sha256(original_job) == job_hash
            and identity.json_sha256(original_manifest) == manifest_hash
            and file_sha(track_path) == track["sha256"]
            and all(file_sha(row["path"]) == row["identity"]["audioSha256"] for row in requests),
            "ASR unit coverage or final audio hashes differ")
    results = []
    for index, (unit, row) in enumerate(zip(job["units"], rows)):
        group_id = unit["translationGroupId"]
        expected_hash = hashlib.sha256(unit["text"].encode("utf-8")).hexdigest()
        audio = row["audio"]
        recognized = recognized_units[index].strip()
        require(tokens(unit["text"], locale), f"Empty expected text: {group_id}")
        similarity, differences, passed = score(unit["text"], recognized, locale, min_similarity)
        results.append({
            "textGroupId": group_id,
            "targetTextSha256": expected_hash,
            "audioSha256": audio["sha256"],
            "recognized": recognized,
            "similarity": similarity,
            "differences": differences,
            "status": "pass" if passed else "requires_review",
        })
    status = "pass" if all(row["status"] == "pass" for row in results) else "requires_review"
    # The normalized runtime behind every score, so a machine waiver can require the
    # same primary ASR its calibration measured (the request identities stay unchanged).
    asr_settings = {"protocol": "formal-back-asr-batch-v1", "model": model, "modelRevision": model_revision,
                    "language": locale, "batchSize": batch_size, "maxNewTokens": 2048, "dtype": "bfloat16",
                    "executionDevice": "cuda:0", "runtime": copy.deepcopy(inference_identity or {}),
                    "implementationSha256": implementation_sha256(), "minSimilarity": min_similarity,
                    "scoring": SCORING}
    receipt = {
        "schemaVersion": SCHEMA,
        "targetLocale": locale,
        "targetLanguageSpeechJobJsonSha256": identity.json_sha256(job),
        "trackSha256": track["sha256"],
        "status": status,
        "model": model,
        "modelRevision": model_revision,
        "minSimilarity": min_similarity,
        "coverage": 1.0,
        "reviewedGroupIds": [row["textGroupId"] for row in results],
        "unitAudioSha256s": [row["audioSha256"] for row in results],
        "results": results,
        "humanListeningStatus": "pending",
        "asrSettings": asr_settings,
        "asrSettingsSha256": identity.json_sha256(asr_settings),
    }
    if batch_size != 1:
        receipt["transcriptionBatchSize"] = batch_size
    screened = copy.deepcopy(manifest)
    screened["machineScreening"] = {"status": status, "model": model, "coverage": 1.0}
    return receipt, screened


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--render-manifest", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--model-revision", required=True)
    parser.add_argument("--min-similarity", type=float, default=0.88)
    parser.add_argument("--batch-size", type=int, choices=BATCH_SIZES, default=None,
                        help="Production default1; Dev profile default4; explicit8 selects a comparison")
    dev_profile.add_arguments(parser)
    parser.add_argument("--unit-cache", type=Path,
                        help="Immutable per-unit ASR cache within the artifact root")
    parser.add_argument("--out-receipt", type=Path, required=True)
    parser.add_argument("--out-manifest", type=Path, required=True)
    args = parser.parse_args(argv)
    dev_settings = dev_profile.resolve("back-asr", enabled=args.dev_test,
        profile_path=args.dev_test_profile, batch_size=args.batch_size)
    args.batch_size = dev_settings["batchSize"]
    dev_receipt_path = args.out_receipt.with_suffix(".dev-test.json")
    if dev_settings["profile"] is not None:
        dev_receipts.check_destination(dev_receipt_path, dev_settings)
    require(not args.out_receipt.exists() and not args.out_manifest.exists(),
            "ASR receipt and screened manifest are immutable")
    require(args.out_receipt.resolve().is_relative_to(args.artifact_root.resolve()),
            "ASR receipt must live inside the renderer artifact root")
    weights = args.model_path.resolve() / "model.safetensors"
    require(weights.is_file()
            and args.model_revision == f"model.safetensors:sha256:{file_sha(weights)}",
            "ASR model revision differs from deployed weights")
    import soundfile as sf
    import torch
    from qwen_asr import Qwen3ASRModel
    import importlib.metadata

    try:
        asr_version = importlib.metadata.version("qwen-asr")
    except importlib.metadata.PackageNotFoundError:
        asr_version = "unavailable"
    inference_identity = {
        "backend": "qwen-asr-local",
        "torchVersion": getattr(torch, "__version__", "unavailable"),
        "qwenAsrVersion": asr_version,
        "modelMetadataSha256s": {str(path.relative_to(args.model_path.resolve())): file_sha(path)
            for path in sorted(args.model_path.resolve().rglob("*.json"))},
    }

    model = None
    languages = {"zh-Hans": "Chinese", "ko": "Korean", "es": "Spanish"}

    def resident_model():
        nonlocal model
        if model is None:
            model = Qwen3ASRModel.from_pretrained(
                str(args.model_path.resolve()), dtype=torch.bfloat16,
                device_map="cuda:0", max_inference_batch_size=args.batch_size, max_new_tokens=2048)
        return model

    def transcribe(path: Path, locale: str) -> str:
        audio, sample_rate = sf.read(path, dtype="float32")
        values = resident_model().transcribe(audio=(audio, sample_rate), language=languages[locale])
        require(len(values) == 1 and isinstance(values[0].text, str), "ASR scalar output cardinality differs")
        return values[0].text

    def transcribe_batch(requests: list[dict]) -> list[dict]:
        audio = [sf.read(row["path"], dtype="float32") for row in requests]
        values = resident_model().transcribe(
            audio=audio, language=[languages[row["identity"]["targetLocale"]] for row in requests])
        require(len(values) == len(requests) and all(isinstance(value.text, str) for value in values),
                "ASR batch output cardinality differs")
        return [{"identity": row["identity"], "recognized": value.text}
                for row, value in zip(requests, values)]

    receipt, screened = screen(load(args.job), load(args.render_manifest),
                               args.artifact_root.resolve(), transcribe,
                               model=MODEL, model_revision=args.model_revision,
                               min_similarity=args.min_similarity, batch_size=args.batch_size,
                               transcribe_batch=transcribe_batch if args.batch_size != 1 else None,
                               unit_cache=args.unit_cache, inference_identity=inference_identity)
    args.out_receipt.parent.mkdir(parents=True, exist_ok=True)
    args.out_receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    # The manifest's evidence path is relative to the renderer artifact root.
    relative = args.out_receipt.resolve().relative_to(args.artifact_root.resolve())
    screened["machineScreeningReceipt"] = {
        "path": str(relative), "sha256": file_sha(args.out_receipt),
        "jsonSha256": identity.json_sha256(receipt),
    }
    args.out_manifest.parent.mkdir(parents=True, exist_ok=True)
    args.out_manifest.write_text(json.dumps(screened, ensure_ascii=False, indent=2) + "\n")
    if dev_settings["profile"] is not None:
        dev_receipts.write(dev_settings, args.out_receipt, dev_receipt_path)
    print(json.dumps({"status": receipt["status"], "groups": len(receipt["results"]),
                      "reviewQueue": [row["textGroupId"] for row in receipt["results"]
                                      if row["status"] != "pass"],
                      **({"devTestConsumptionReceipt": str(dev_receipt_path.resolve())}
                         if dev_settings["profile"] is not None else {})}, ensure_ascii=False))


if __name__ == "__main__":
    main()
