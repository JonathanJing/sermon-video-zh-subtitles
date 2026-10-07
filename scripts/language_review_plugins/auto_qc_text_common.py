"""Generic deterministic Layer 2 screens for machine-quality-waived locales.

These checks are week-independent: they read only the frozen English units,
the frozen policy terminology and the target text. They catch mechanical
failures (lost or invented numbers, added or dropped scripture references,
missing reviewed names, untranslated English, placeholders, unsafe speech
markup). They do not prove semantic fidelity; the back-translation check in
``scripts/target_text_auto_qc.py`` and the seeded-error calibration supply that
evidence for a machine quality waiver. No check here grants human approval.
"""
from __future__ import annotations

import re
import unicodedata

try:
    from scripts.language_review_plugins.common import has_unsafe_speech_markup, result
except ImportError:  # Direct scripts/produce_target_language_candidate.py execution.
    from language_review_plugins.common import has_unsafe_speech_markup, result


REQUIRED = ["target_script", "untranslated_source", "register", "proper_names",
            "scripture_references", "numbers", "tts_segmentation"]

_UNITS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
          "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
          "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
          "seventeen": 17, "eighteen": 18, "nineteen": 19}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
         "seventy": 70, "eighty": 80, "ninety": 90}
_SCALES = {"hundred": 100, "thousand": 1000}
# "one" and "zero" are idiomatic far more often than numeric in sermons
# ("the one who", "no one"); a lone spelled form is not screened.
_IDIOMATIC_ALONE = {0, 1}
_ENGLISH_FUNCTION_WORDS = {"the", "and", "of", "that", "you", "is", "we", "to", "in", "it",
                           "this", "are", "was", "have", "with", "for", "not", "be", "they"}


def _fold(value: str) -> str:
    text = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in text if not unicodedata.combining(char))


def english_numbers(text: str) -> list[int | str]:
    """Cardinal numbers said in English, as digits or words; order preserved.

    A decimal written with digits ("2.5") is kept as its digit string so a
    changed decimal ("25") is still a missing number.
    """
    tokens = re.findall(r"\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?|[a-z]+", text.casefold().replace("-", " "))
    found: list[int] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if re.fullmatch(r"\d{1,3}(?:,\d{3})+|\d+", token):
            found.append(int(token.replace(",", "")))
            index += 1
            continue
        if re.fullmatch(r"\d+\.\d+", token):
            found.append(token)
            index += 1
            continue
        if token not in _UNITS and token not in _TENS and token not in _SCALES:
            index += 1
            continue
        total, current, words = 0, 0, 0
        while index < len(tokens):
            word = tokens[index]
            if word in _UNITS:
                current += _UNITS[word]
            elif word in _TENS:
                current += _TENS[word]
            elif word == "hundred":
                current = max(current, 1) * 100
            elif word == "thousand":
                total += max(current, 1) * 1000
                current = 0
            elif word == "and" and words and index + 1 < len(tokens) and (
                    tokens[index + 1] in _UNITS or tokens[index + 1] in _TENS):
                index += 1
                continue
            else:
                break
            words += 1
            index += 1
        value = total + current
        if not (words == 1 and value in _IDIOMATIC_ALONE):
            found.append(value)
    return found


# --- Korean number forms -------------------------------------------------------
_KO_SINO_DIGITS = "영일이삼사오육칠팔구"
_KO_NATIVE_UNITS = {1: ("하나", "한"), 2: ("둘", "두"), 3: ("셋", "세", "석"), 4: ("넷", "네", "넉"),
                    5: ("다섯",), 6: ("여섯",), 7: ("일곱",), 8: ("여덟",), 9: ("아홉",)}
_KO_NATIVE_TENS = {10: ("열",), 20: ("스물", "스무"), 30: ("서른",), 40: ("마흔",), 50: ("쉰",),
                   60: ("예순",), 70: ("일흔",), 80: ("여든",), 90: ("아흔",)}
_KO_COUNTERS = ("장", "절", "년", "월", "일", "번", "명", "개", "분", "초", "시", "살", "세",
                "주", "권", "회", "층", "배", "가지", "사람", "퍼센트", "달", "날", "째")


def korean_sino(value: int) -> str:
    if value == 0:
        return "영"
    parts = []
    for unit_value, unit_name in ((100_000_000, "억"), (10_000, "만")):
        if value >= unit_value:
            head, value = divmod(value, unit_value)
            parts.append((korean_sino(head) if head > 1 or unit_name == "억" else "") + unit_name)
    for unit_value, unit_name in ((1000, "천"), (100, "백"), (10, "십")):
        head, value = divmod(value, unit_value)
        if head:
            parts.append(("" if head == 1 else _KO_SINO_DIGITS[head]) + unit_name)
    if value:
        parts.append(_KO_SINO_DIGITS[value])
    return "".join(parts)


def korean_native(value: int) -> tuple[str, ...]:
    if not 1 <= value <= 99:
        return ()
    tens, unit = divmod(value, 10)
    heads = _KO_NATIVE_TENS.get(tens * 10, ("",)) if tens else ("",)
    tails = _KO_NATIVE_UNITS.get(unit, ("",)) if unit else ("",)
    if tens == 2 and unit:
        heads = ("스물",)
    return tuple(dict.fromkeys(head + tail for head in heads for tail in tails if head + tail))


def _ko_pattern(form: str) -> str:
    left = r"(?<![가-힣])"
    if len(form) == 1:
        # One syllable (이, 두, 세 …) is far too common inside words; require a
        # counter or a following space before treating it as a number.
        return left + re.escape(form) + r"(?=\s*(?:" + "|".join(_KO_COUNTERS) + r")|\s)"
    return left + re.escape(form)


def _decimal_digit_forms(value: str, *, comma: bool = False) -> set[str]:
    forms = {value}
    if comma:
        forms.add(value.replace(".", ","))
    return forms


def _decimal_present(text: str, forms: set[str]) -> bool:
    return any(re.search(r"(?<![\d.,])" + re.escape(form) + r"(?![\d])", text) for form in forms)


def korean_number_present(text: str, value: int | str) -> bool:
    if isinstance(value, str):  # Decimal: "2.5" or "이 점 오".
        whole, fraction = value.split(".")
        spoken = korean_sino(int(whole)) + "점" + "".join(_KO_SINO_DIGITS[int(d)] for d in fraction)
        return _decimal_present(text, {value}) or spoken in re.sub(r"\s+", "", text)
    digits = {str(value), f"{value:,}"}
    if any(re.search(r"(?<!\d)" + re.escape(form) + r"(?!\d)", text) for form in digits):
        return True
    forms = (korean_sino(value), *korean_native(value))
    return any(re.search(_ko_pattern(form), text) for form in forms)


# --- Spanish number forms ------------------------------------------------------
_ES_UNITS = ["cero", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve",
             "diez", "once", "doce", "trece", "catorce", "quince", "dieciseis", "diecisiete",
             "dieciocho", "diecinueve", "veinte", "veintiuno", "veintidos", "veintitres",
             "veinticuatro", "veinticinco", "veintiseis", "veintisiete", "veintiocho", "veintinueve"]
_ES_TENS = {30: "treinta", 40: "cuarenta", 50: "cincuenta", 60: "sesenta", 70: "setenta",
            80: "ochenta", 90: "noventa"}
_ES_HUNDREDS = {1: "ciento", 2: "doscientos", 3: "trescientos", 4: "cuatrocientos", 5: "quinientos",
                6: "seiscientos", 7: "setecientos", 8: "ochocientos", 9: "novecientos"}


def spanish_words(value: int) -> str:
    """Accent-folded Spanish cardinal (masculine) for 0–999,999."""
    if value < 30:
        return _ES_UNITS[value]
    if value < 100:
        tens, unit = divmod(value, 10)
        return _ES_TENS[tens * 10] + ("" if not unit else " y " + _ES_UNITS[unit])
    if value < 1000:
        hundreds, rest = divmod(value, 100)
        if value == 100:
            return "cien"
        return _ES_HUNDREDS[hundreds] + ("" if not rest else " " + spanish_words(rest))
    if value < 1_000_000:
        thousands, rest = divmod(value, 1000)
        head = "mil" if thousands == 1 else spanish_words(thousands) + " mil"
        return head + ("" if not rest else " " + spanish_words(rest))
    return str(value)


def spanish_number_present(text: str, value: int | str) -> bool:
    if isinstance(value, str):  # Decimal: "2,5", "2.5" or "dos coma cinco".
        whole, fraction = value.split(".")
        folded = _fold(text)
        tail = " ".join(_ES_UNITS[int(d)] for d in fraction)
        spoken = {f"{spanish_words(int(whole))} {word} {tail}" for word in ("coma", "punto")}
        return _decimal_present(text, _decimal_digit_forms(value, comma=True)) or any(
            re.search(r"\b" + re.escape(form) + r"\b", folded) for form in spoken)
    folded = _fold(text)
    digits = {str(value), f"{value:,}", f"{value:,}".replace(",", ".")}
    if any(re.search(r"(?<!\d)" + re.escape(form) + r"(?!\d)", folded) for form in digits):
        return True
    words = spanish_words(value)
    forms = {words}
    if words.endswith("uno"):
        forms |= {words[:-3] + "un", words[:-3] + "una"}
    if words.endswith("ientos"):
        forms.add(words[:-2] + "as")
    return any(re.search(r"\b" + re.escape(form) + r"\b", folded) for form in forms)


# --- Chinese number forms -----------------------------------------------------
_ZH_DIGITS = "零一二三四五六七八九"


def chinese_numeral(value: int) -> str:
    if value < 10:
        return _ZH_DIGITS[value]
    if value < 20:
        return "十" + (_ZH_DIGITS[value - 10] if value > 10 else "")
    if value >= 100_000_000:
        return str(value)
    parts, zero_pending = [], False
    for unit_value, unit_name in ((10_000, "万"), (1000, "千"), (100, "百"), (10, "十")):
        head, value = divmod(value, unit_value)
        if head:
            if zero_pending:
                parts.append("零")
            parts.append((chinese_numeral(head) if unit_value == 10_000 else _ZH_DIGITS[head]) + unit_name)
            zero_pending = False
        elif parts:
            zero_pending = True
    if value:
        parts.append(("零" if zero_pending else "") + _ZH_DIGITS[value])
    return "".join(parts)


def chinese_number_present(text: str, value: int | str) -> bool:
    if isinstance(value, str):  # Decimal: "2.5" or "二点五" / "两点五".
        whole, fraction = value.split(".")
        heads = {chinese_numeral(int(whole))} | ({"两"} if whole == "2" else set())
        tail = "".join(_ZH_DIGITS[int(d)] for d in fraction)
        return _decimal_present(text, {value}) or any(head + "点" + tail in text for head in heads)
    if any(re.search(r"(?<!\d)" + re.escape(form) + r"(?!\d)", text) for form in {str(value), f"{value:,}"}):
        return True
    forms = {chinese_numeral(value)}
    if value == 2:
        forms.add("两")
    if 1000 <= value <= 2100:  # Years are often read digit by digit.
        forms |= {"".join(_ZH_DIGITS[int(d)] for d in str(value)),
                  "".join("〇" if d == "0" else _ZH_DIGITS[int(d)] for d in str(value))}
    standard = chinese_numeral(value)
    if standard[0] == "二" and len(standard) > 1 and standard[1] in "百千万":
        forms.add("两" + standard[1:])
    return any(form in text for form in forms)


# --- Scripture references -----------------------------------------------------
def _number_token(token: str, locale: str) -> int | None:
    token = _fold(token).strip(" ,.;")
    if token.isdigit():
        return int(token)
    if locale == "en":
        values = english_numbers(token)
        return values[0] if len(values) == 1 else (_UNITS.get(token) if token in _UNITS else None)
    if locale == "es":
        for value in range(1, 200):
            if spanish_words(value) == token:
                return value
    if locale == "ko":
        for value in range(1, 200):
            if korean_sino(value) == token:
                return value
    if locale == "zh-Hans":
        for value in range(1, 200):
            if chinese_numeral(value) == token:
                return value
    return None


def _take_number(tokens: list[str], index: int) -> tuple[int | None, int]:
    """Read one digit token or one spelled cardinal starting at ``index``."""
    if index < len(tokens) and tokens[index].isdigit():
        return int(tokens[index]), index + 1
    stop = index
    while stop < len(tokens) and (tokens[stop] in _UNITS or tokens[stop] in _TENS
                                  or tokens[stop] in _SCALES):
        stop += 1
    if stop == index:
        return None, index
    values = english_numbers(" ".join(tokens[index:stop]) + " x")
    if not values:  # A lone "one" is idiomatic elsewhere, but numeric after "chapter".
        values = [_UNITS[tokens[index]]] if tokens[index] in _UNITS else []
    return (values[0] if len(values) == 1 else None), stop


_COLON_PAIR = r"(?<![\d:])(\d{1,3})\s*:\s*(\d{1,3})(?![\d:])"


def english_colon_pairs(text: str) -> set[tuple[int, int]]:
    """Every ``a:b`` in the English, including clock times."""
    return {(int(c), int(v)) for c, v in re.findall(_COLON_PAIR, text)}


_BOOKS = (
    "Genesis|Gen|Exodus|Exod|Ex|Leviticus|Lev|Numbers|Num|Deuteronomy|Deut|Joshua|Josh|Judges|Judg|"
    "Ruth|Samuel|Sam|Kings|Kgs|Chronicles|Chron|Ezra|Nehemiah|Neh|Esther|Esth|Job|Psalms?|Psa?|"
    "Proverbs|Prov|Ecclesiastes|Eccl|Songs?|Solomon|Isaiah|Isa|Jeremiah|Jer|Lamentations|Lam|"
    "Ezekiel|Ezek|Daniel|Dan|Hosea|Hos|Joel|Amos|Obadiah|Obad|Jonah|Micah|Mic|Nahum|Nah|"
    "Habakkuk|Hab|Zephaniah|Zeph|Haggai|Hag|Zechariah|Zech|Malachi|Mal|Matthew|Matt|Mt|Mark|Mk|"
    "Luke|Lk|John|Jn|Acts|Romans|Rom|Corinthians|Cor|Galatians|Gal|Ephesians|Eph|Philippians|Phil|"
    "Colossians|Col|Thessalonians|Thess|Timothy|Tim|Titus|Philemon|Phlm|Hebrews|Heb|James|Jas|"
    "Peter|Pet|Jude|Revelations?|Rev")
_ENGLISH_REFERENCE = re.compile(r"\b(?:" + _BOOKS + r")\.?\s+(\d{1,3}):(\d{1,3})(?![\d:])")


def english_references(text: str) -> tuple[set[tuple[int, int]], set[int]]:
    # A written reference follows a recognized book name ("Revelation 3:4",
    # "1 John 4:8"); "At 10:30" is a clock time and is not required in the target.
    pairs = {(int(c), int(v)) for c, v in _ENGLISH_REFERENCE.findall(text)}
    chapters = set()
    tokens = re.findall(r"\d+|[a-z]+", text.casefold().replace("-", " "))
    for index, token in enumerate(tokens):
        if token != "chapter":
            continue
        chapter, cursor = _take_number(tokens, index + 1)
        if chapter is None:
            continue
        chapters.add(chapter)
        if cursor < len(tokens) and tokens[cursor] == "and":
            cursor += 1
        if cursor < len(tokens) and tokens[cursor] in {"verse", "verses"}:
            verse, _ = _take_number(tokens, cursor + 1)
            if verse is not None:
                pairs.add((chapter, verse))
    chapters |= {c for c, _ in pairs}
    return pairs, chapters


_ES_WORD_VALUES = {spanish_words(value): value for value in range(1, 200)}
_KO_PARTICLES = ("(?:에서|에게|에는|에도|에|을|은|의|이|과|와|도|부터|까지|으로|만|입니다|이다|이며|이고|이라|처럼)"
                 "(?![가-힣])|(?:에서|에|을|은|의|이|과|와|도|부터|까지|으로|만)(?=[가-힣])")


def _take_spanish_number(tokens: list[str], index: int) -> tuple[int | None, int]:
    if index < len(tokens) and tokens[index].isdigit():
        return int(tokens[index]), index + 1
    for width in (4, 3, 2, 1):  # Longest spelled cardinal first ("treinta y uno").
        phrase = " ".join(tokens[index:index + width])
        if len(tokens[index:index + width]) == width and phrase in _ES_WORD_VALUES:
            return _ES_WORD_VALUES[phrase], index + width
    return None, index


def target_references(text: str, locale: str) -> tuple[set[tuple[int, int]], set[int]]:
    pairs = {(int(c), int(v)) for c, v in re.findall(_COLON_PAIR, text)}
    chapters = set()
    if locale == "ko":
        for c, v in re.findall(r"(\d{1,3}|[영일이삼사오육칠팔구십백]+)\s*장\s*(\d{1,3}|[영일이삼사오육칠팔구십백]+)\s*절", text):
            c_value, v_value = _number_token(c, "ko"), _number_token(v, "ko")
            if c_value is not None and v_value is not None:
                pairs.add((c_value, v_value))
        # A particle usually follows: 3장에서, 3장을, 3장의, 3장입니다.
        for c in re.findall(r"(\d{1,3}|[영일이삼사오육칠팔구십백]+)\s*장"
                            r"(?![가-힣])|(\d{1,3}|[영일이삼사오육칠팔구십백]+)\s*장(?=" + _KO_PARTICLES + r")", text):
            c = c[0] or c[1]
            value = _number_token(c, "ko")
            if value is not None:
                chapters.add(value)
    if locale == "zh-Hans":
        numeral = r"(\d{1,3}|[零一二三四五六七八九十百]+)"
        for c, v in re.findall(numeral + r"\s*章\s*(?:第\s*)?" + numeral + r"\s*节", text):
            c_value, v_value = _number_token(c, "zh-Hans"), _number_token(v, "zh-Hans")
            if c_value is not None and v_value is not None:
                pairs.add((c_value, v_value))
        for c in re.findall(numeral + r"\s*章", text):
            value = _number_token(c, "zh-Hans")
            if value is not None:
                chapters.add(value)
    if locale == "es":
        tokens = re.findall(r"\d+|[a-z]+", _fold(text))
        for index, token in enumerate(tokens):
            if token != "capitulo":
                continue
            chapter, cursor = _take_spanish_number(tokens, index + 1)
            if chapter is None:
                continue
            chapters.add(chapter)
            while cursor < len(tokens) and tokens[cursor] in {"y", "el", "al"}:
                cursor += 1
            if cursor < len(tokens) and tokens[cursor] in {"versiculo", "versiculos"}:
                verse, _ = _take_spanish_number(tokens, cursor + 1)
                if verse is not None:
                    pairs.add((chapter, verse))
    chapters |= {c for c, _ in pairs}
    return pairs, chapters


def scripture_reference_problems(english: str, target: str, locale: str) -> list[str]:
    english_pairs, english_chapters = english_references(english)
    target_pairs, target_chapters = target_references(target, locale)
    problems = [f"missing reference {c}:{v}" for c, v in sorted(english_pairs - target_pairs)]
    problems += [f"missing chapter {c}" for c in sorted(english_chapters - target_chapters)
                 if not any(pair[0] == c for pair in english_pairs)]
    # The speaker's words decide which references exist; a reference the
    # English did not say is an editorial addition (the 2026-10-04 ko issue).
    colon_pairs = english_colon_pairs(english)
    added_pairs = target_pairs - english_pairs - colon_pairs
    problems += [f"added reference {c}:{v}" for c, v in sorted(added_pairs)]
    # A chapter-only citation the English never said ("요한복음 3장"). A number
    # the English said for another reason (three sheets, chapter-like counters)
    # is not treated as added.
    said = {value for value in english_numbers(english) if isinstance(value, int)}
    said |= {value for pair in colon_pairs for value in pair}
    problems += [f"added chapter {c}" for c in sorted(target_chapters - english_chapters - said
                                                       - {c for c, _ in added_pairs})]
    return problems


# --- Remaining screens ---------------------------------------------------------
def script_problems(text: str, locale: str) -> list[str]:
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return ["no target-language letters"]
    hangul = sum("가" <= char <= "힣" or "ᄀ" <= char <= "ᇿ" for char in letters)
    cjk = sum("一" <= char <= "鿿" or "぀" <= char <= "ヿ" for char in letters)
    problems = []
    if re.search(r"\b(?:TODO|TBD|PLACEHOLDER|FIXME)\b|\?\?\?", text, re.I):
        problems.append("placeholder marker")
    if locale == "ko" and hangul / len(letters) < 0.6:
        problems.append(f"Hangul share {hangul / len(letters):.2f} < 0.60")
    if locale == "es":
        latin = sum(unicodedata.name(char, "").startswith("LATIN") for char in letters)
        if hangul or cjk:
            problems.append("non-Latin CJK/Hangul characters in Spanish text")
        if latin / len(letters) < 0.6:
            problems.append(f"Latin share {latin / len(letters):.2f} < 0.60")
    if locale == "zh-Hans" and cjk / len(letters) < 0.6:
        problems.append(f"Han share {cjk / len(letters):.2f} < 0.60")
    return problems


def untranslated_problems(english: str, text: str, locale: str) -> list[str]:
    words = re.findall(r"[a-zA-Z']+", text)
    if locale in {"ko", "zh-Hans"}:
        latin_letters = sum(len(word) for word in words)
        letters = sum(char.isalpha() for char in text)
        return [] if not letters or latin_letters / letters <= 0.3 else ["Latin-script share above 0.30"]
    function_words = [word for word in words if word.casefold() in _ENGLISH_FUNCTION_WORDS]
    if len(words) >= 6 and len(function_words) / len(words) > 0.15:
        return [f"English function words {len(function_words)}/{len(words)}"]
    english_words = re.findall(r"[a-z']+", english.casefold())
    if len(english_words) >= 6 and _fold(" ".join(english_words)) in _fold(text):
        return ["English source text copied into target"]
    return []


def name_problems(policy: dict, english: str, text: str) -> list[str]:
    folded_text = _fold(text)
    problems = []
    for kind in ("properNames", "seriesNames"):
        for term in policy["terminology"][kind]:
            source = term["source"]
            if not re.search(r"(?<!\w)" + re.escape(source) + r"(?!\w)", english, re.I):
                continue
            if term.get("reviewStatus") == "pending" or not term.get("target"):
                problems.append(f"{source}: terminology unresolved")
            elif _fold(term["target"]) not in folded_text:
                problems.append(f"{source}: expected {term['target']}")
    return problems


def number_problems(english: str, text: str, locale: str, references: set[tuple[int, int]]) -> list[str]:
    present = {"ko": korean_number_present, "es": spanish_number_present,
               "zh-Hans": chinese_number_present}[locale]
    reference_numbers = {value for pair in references for value in pair}
    missing = [value for value in dict.fromkeys(english_numbers(english))
               if value not in reference_numbers and not present(text, value)]
    return [f"missing number {value}" for value in missing]


def review_auto_group(policy: dict, english_units: list[dict], group: dict, *,
                      locale: str, forbidden_register: str) -> list[dict[str, str]]:
    if (policy.get("targetLocale") != locale
            or policy.get("languageReview", {}).get("requiredChecks") != REQUIRED):
        raise ValueError(f"{locale} machine-QC policy checks differ from plugin")
    text = group["targetText"]
    english = " ".join(unit["english"] for unit in english_units)
    english_pairs, _ = english_references(english)
    checks = [
        ("target_script", script_problems(text, locale), "Target script share and placeholder screen"),
        ("untranslated_source", untranslated_problems(english, text, locale), "Untranslated English screen"),
        ("register", ["forbidden register form"] if re.search(forbidden_register, text, re.I) else [],
         "Forbidden register pattern screen"),
        ("proper_names", name_problems(policy, english, text), "Policy terminology mentioned in English"),
        ("scripture_references", scripture_reference_problems(english, text, locale),
         "Chapter:verse references said vs written; additions fail"),
        ("numbers", number_problems(english, text, locale, english_pairs),
         "English cardinals as digits or target-language words"),
        ("tts_segmentation", ["unsafe utterance markup or length"]
         if has_unsafe_speech_markup(group["targetUtterances"]) else [], "Utterance structure screen"),
    ]
    return [result(check_id, not problems,
                   label + ("; " + "; ".join(problems) if problems else "; pass"))
            for check_id, problems, label in checks]
