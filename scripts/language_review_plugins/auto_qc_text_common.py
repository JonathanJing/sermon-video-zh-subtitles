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
# A lone "one" is often a pronoun, not a count: "the one who", "no one",
# "this one", "the Holy One", "one another", "one day", "one of them". Only those contexts
# are exempt; "you only have one life" is still screened.
_ONE_PRONOUN_BEFORE = {"no", "the", "this", "that", "which", "every", "any", "each", "some", "someone"}
_ONE_PRONOUN_AFTER = {"another", "who", "whom", "whose", "day", "of"}


def _idiomatic_one(tokens: list[str], index: int) -> bool:
    before = tokens[index - 1] if index > 0 else None
    before2 = tokens[index - 2] if index > 1 else None
    after = tokens[index + 1] if index + 1 < len(tokens) else None
    # "the Holy One", "the only one", "the loved one": an article two words back.
    return (before in _ONE_PRONOUN_BEFORE or after in _ONE_PRONOUN_AFTER
            or (before2 in {"the", "this", "that"} and before is not None and before.isalpha()))
_ENGLISH_FUNCTION_WORDS = {"the", "and", "of", "that", "you", "is", "we", "to", "in", "it",
                           "this", "are", "was", "have", "with", "for", "not", "be", "they"}


def _fold(value: str) -> str:
    text = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in text if not unicodedata.combining(char))


def _spelled_two_digit(tokens: list[str], index: int) -> tuple[int | None, int]:
    """10-99 spelled as one teen word, or a tens word with an optional unit."""
    if index < len(tokens) and 10 <= _UNITS.get(tokens[index], -1) <= 19:
        return _UNITS[tokens[index]], index + 1
    if index < len(tokens) and tokens[index] in _TENS:
        if index + 1 < len(tokens) and 1 <= _UNITS.get(tokens[index + 1], -1) <= 9:
            return _TENS[tokens[index]] + _UNITS[tokens[index + 1]], index + 2
        return _TENS[tokens[index]], index + 1
    return None, index


def _spoken_year(tokens: list[str], index: int) -> tuple[int | None, int]:
    """A year said in two halves: "nineteen ninety-nine", "twenty twenty-four", "twenty oh five"."""
    head, cursor = _spelled_two_digit(tokens, index)
    if head is None or not 14 <= head <= 20:
        return None, index
    if cursor + 1 < len(tokens) and tokens[cursor] == "oh" and 1 <= _UNITS.get(tokens[cursor + 1], -1) <= 9:
        tail, end = _UNITS[tokens[cursor + 1]], cursor + 2
    else:
        tail, end = _spelled_two_digit(tokens, cursor)
    if tail is None or (end < len(tokens) and tokens[end] in _SCALES):
        return None, index
    return head * 100 + tail, end


def english_numbers(text: str) -> list[int | str]:
    """Cardinal numbers said in English, as digits or words; order preserved.

    A decimal written with digits ("2.5") is kept as its digit string so a
    changed decimal ("25") is still a missing number.
    """
    # Keep punctuation as boundaries between spoken list items; hyphens still
    # join compound cardinals and years ("twenty-five", "ninety-nine").
    tokens = re.findall(r"\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?|[a-z]+|[^\w\s]",
                        text.casefold().replace("-", " "))
    found: list[int | str] = []
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
        year, end = _spoken_year(tokens, index)
        if year is not None:
            found.append(year)
            index = end
            continue
        start = index
        total, current, words = 0, 0, 0
        previous = None
        while index < len(tokens):
            word = tokens[index]
            if word in _UNITS:
                # A unit can complete a tens/scale expression, but another
                # standalone unit starts a new number ("two three four").
                if previous is not None and not (
                        previous in _SCALES or previous == "and" or
                        previous in _TENS and 1 <= _UNITS[word] <= 9):
                    break
                current += _UNITS[word]
            elif word in _TENS:
                if previous is not None and previous not in _SCALES and previous != "and":
                    break
                current += _TENS[word]
            elif word == "hundred":
                current = max(current, 1) * 100
            elif word == "thousand":
                total += max(current, 1) * 1000
                current = 0
            elif word == "and" and previous in _SCALES and index + 1 < len(tokens) and (
                    tokens[index + 1] in _UNITS or tokens[index + 1] in _TENS):
                previous = word
                index += 1
                continue
            else:
                break
            words += 1
            previous = word
            index += 1
        value = total + current
        if not (words == 1 and value == 1 and tokens[start] == "one" and _idiomatic_one(tokens, start)):
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
    forms = (korean_sino(value), *korean_native(value), *(("제로",) if value == 0 else ()))
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
_ZH_NUMBER_TOKEN = re.compile(r"[零〇一二两三四五六七八九十百千万亿壹贰叁肆伍陆柒捌玖拾佰仟萬億廿卅]+(?:点[零〇一二两三四五六七八九壹贰叁肆伍陆柒捌玖]+)?")


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
        return _decimal_present(text, {value}) or bool(
            {head + "点" + tail for head in heads} & set(_ZH_NUMBER_TOKEN.findall(text)))
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
    return bool(forms & set(_ZH_NUMBER_TOKEN.findall(text)))


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


# Bible books: (code, number, English names, Korean, Spanish names folded, Simplified Chinese).
# Codes follow scripts/build_scripture_index.py. A numbered book shares its
# English and Spanish base name ("1 John", "1 Juan") and is told apart by the number.
_BIBLE_BOOKS = (
    ("GEN", None, "Genesis|Gen", "창세기", "genesis", "创世记"),
    ("EXO", None, "Exodus|Exod|Ex", "출애굽기", "exodo", "出埃及记"),
    ("LEV", None, "Leviticus|Lev", "레위기", "levitico", "利未记"),
    ("NUM", None, "Numbers|Num", "민수기", "numeros", "民数记"),
    ("DEU", None, "Deuteronomy|Deut", "신명기", "deuteronomio", "申命记"),
    ("JOS", None, "Joshua|Josh", "여호수아", "josue", "约书亚记"),
    ("JDG", None, "Judges|Judg", "사사기", "jueces", "士师记"),
    ("RUT", None, "Ruth", "룻기", "rut", "路得记"),
    ("1SA", 1, "Samuel|Sam", "사무엘상", "samuel", "撒母耳记上"),
    ("2SA", 2, "Samuel|Sam", "사무엘하", "samuel", "撒母耳记下"),
    ("1KI", 1, "Kings|Kgs", "열왕기상", "reyes", "列王纪上"),
    ("2KI", 2, "Kings|Kgs", "열왕기하", "reyes", "列王纪下"),
    ("1CH", 1, "Chronicles|Chron", "역대상", "cronicas", "历代志上"),
    ("2CH", 2, "Chronicles|Chron", "역대하", "cronicas", "历代志下"),
    ("EZR", None, "Ezra", "에스라", "esdras", "以斯拉记"),
    ("NEH", None, "Nehemiah|Neh", "느헤미야", "nehemias", "尼希米记"),
    ("EST", None, "Esther|Esth", "에스더", "ester", "以斯帖记"),
    ("JOB", None, "Job", "욥기", "job", "约伯记"),
    ("PSA", None, "Psalms|Psalm|Psa|Ps", "시편", "salmos|salmo", "诗篇"),
    ("PRO", None, "Proverbs|Prov", "잠언", "proverbios", "箴言"),
    ("ECC", None, "Ecclesiastes|Eccl", "전도서", "eclesiastes", "传道书"),
    ("SOL", None, "Song of Solomon|Song of Songs|Songs|Song|Solomon", "아가", "cantar de los cantares|cantares", "雅歌"),
    ("ISA", None, "Isaiah|Isa", "이사야", "isaias", "以赛亚书"),
    ("JER", None, "Jeremiah|Jer", "예레미야", "jeremias", "耶利米书"),
    ("LAM", None, "Lamentations|Lam", "예레미야애가|애가", "lamentaciones", "耶利米哀歌"),
    ("EZE", None, "Ezekiel|Ezek", "에스겔", "ezequiel", "以西结书"),
    ("DAN", None, "Daniel|Dan", "다니엘", "daniel", "但以理书"),
    ("HOS", None, "Hosea|Hos", "호세아", "oseas", "何西阿书"),
    ("JOE", None, "Joel", "요엘", "joel", "约珥书"),
    ("AMO", None, "Amos", "아모스", "amos", "阿摩司书"),
    ("OBA", None, "Obadiah|Obad", "오바댜", "abdias", "俄巴底亚书"),
    ("JON", None, "Jonah", "요나", "jonas", "约拿书"),
    ("MIC", None, "Micah|Mic", "미가", "miqueas", "弥迦书"),
    ("NAH", None, "Nahum|Nah", "나훔", "nahum", "那鸿书"),
    ("HAB", None, "Habakkuk|Hab", "하박국", "habacuc", "哈巴谷书"),
    ("ZEP", None, "Zephaniah|Zeph", "스바냐", "sofonias", "西番雅书"),
    ("HAG", None, "Haggai|Hag", "학개", "hageo", "哈该书"),
    ("ZEC", None, "Zechariah|Zech", "스가랴", "zacarias", "撒迦利亚书"),
    ("MAL", None, "Malachi|Mal", "말라기", "malaquias", "玛拉基书"),
    ("MAT", None, "Matthew|Matt|Mt", "마태복음", "mateo", "马太福音"),
    ("MAR", None, "Mark|Mk", "마가복음", "marcos", "马可福音"),
    ("LUK", None, "Luke|Lk", "누가복음", "lucas", "路加福音"),
    ("JOH", None, "John|Jn", "요한복음", "juan", "约翰福音"),
    ("ACT", None, "Acts", "사도행전", "hechos", "使徒行传"),
    ("ROM", None, "Romans|Rom", "로마서", "romanos", "罗马书"),
    ("1CO", 1, "Corinthians|Cor", "고린도전서", "corintios", "哥林多前书"),
    ("2CO", 2, "Corinthians|Cor", "고린도후서", "corintios", "哥林多后书"),
    ("GAL", None, "Galatians|Gal", "갈라디아서", "galatas", "加拉太书"),
    ("EPH", None, "Ephesians|Eph", "에베소서", "efesios", "以弗所书"),
    ("PHI", None, "Philippians|Phil", "빌립보서", "filipenses", "腓立比书"),
    ("COL", None, "Colossians|Col", "골로새서", "colosenses", "歌罗西书"),
    ("1TH", 1, "Thessalonians|Thess", "데살로니가전서", "tesalonicenses", "帖撒罗尼迦前书"),
    ("2TH", 2, "Thessalonians|Thess", "데살로니가후서", "tesalonicenses", "帖撒罗尼迦后书"),
    ("1TI", 1, "Timothy|Tim", "디모데전서", "timoteo", "提摩太前书"),
    ("2TI", 2, "Timothy|Tim", "디모데후서", "timoteo", "提摩太后书"),
    ("TIT", None, "Titus", "디도서", "tito", "提多书"),
    ("PHM", None, "Philemon|Phlm", "빌레몬서", "filemon", "腓利门书"),
    ("HEB", None, "Hebrews|Heb", "히브리서", "hebreos", "希伯来书"),
    ("JAM", None, "James|Jas", "야고보서", "santiago", "雅各书"),
    ("1PE", 1, "Peter|Pet", "베드로전서", "pedro", "彼得前书"),
    ("2PE", 2, "Peter|Pet", "베드로후서", "pedro", "彼得后书"),
    ("1JO", 1, "John|Jn", "요한일서", "juan", "约翰一书"),
    ("2JO", 2, "John|Jn", "요한이서", "juan", "约翰二书"),
    ("3JO", 3, "John|Jn", "요한삼서", "juan", "约翰三书"),
    ("JUD", None, "Jude", "유다서", "judas", "犹大书"),
    ("REV", None, "Revelation|Revelations|Rev", "요한계시록|계시록", "apocalipsis", "启示录"),
)


def _alternation(names) -> str:
    return "|".join(re.escape(name) for name in sorted(set(names), key=len, reverse=True))


_EN_BOOK_CODES = {(number, name): code for code, number, english, *_ in _BIBLE_BOOKS
                  for name in english.split("|")}
_ES_BOOK_CODES = {(number, name): code for code, number, _, _, spanish, _ in _BIBLE_BOOKS
                  for name in spanish.split("|")}
_KO_BOOK_CODES = {name: code for code, _, _, korean, _, _ in _BIBLE_BOOKS for name in korean.split("|")}
_ZH_BOOK_CODES = {chinese: code for code, *_, chinese in _BIBLE_BOOKS}
# Book names are matched as written (capitalized), so "song 3:45" is not a citation.
_BOOKS = _alternation(name for code, _, english, *_ in _BIBLE_BOOKS for name in english.split("|"))
_ENGLISH_REFERENCE = re.compile(r"\b(?:" + _BOOKS + r")\.?\s+(\d{1,3}):(\d{1,3})(?![\d:])")
_EN_ORDINAL = {"1": 1, "2": 2, "3": 3, "i": 1, "ii": 2, "iii": 3, "first": 1, "second": 2, "third": 3}
_EN_NUMBER_WORD = _alternation((*_UNITS, *_TENS, *_SCALES))
_ENGLISH_CITATION = re.compile(r"(?:\b(?i:(1|2|3|iii|ii|i|first|second|third))\s*)?\b(" + _BOOKS
                               + r")\.?\s+(?:chapter\s+)?(\d{1,3}|(?:" + _EN_NUMBER_WORD
                               + r")(?:[ -](?:" + _EN_NUMBER_WORD + r"))*)"
                               + r"(?:\s*:\s*(\d{1,3})(?![\d:]))?(?!\d)")


def _book_code(codes: dict, number: int | None, name: str) -> str | None:
    """Resolve a (number, base name) pair; an unnumbered base of numbered books is unknown."""
    return codes.get((number, name)) or (codes.get((None, name)) if number is None else None)


def english_book_chapters(text: str) -> set[int]:
    """Chapters anchored to a recognized English book name."""
    return {chapter for _, chapter, _ in english_book_citations(text)}


def english_book_citations(text: str) -> list[tuple[str | None, int, int | None]]:
    """Book-bound chapter and chapter:verse citations (None for unknown books)."""
    found = []
    for match in _ENGLISH_CITATION.finditer(text):
        ordinal, name, chapter, verse = match.groups()
        number = _EN_ORDINAL.get(ordinal.casefold()) if ordinal else None
        value = _number_token(chapter, "en")
        if value is not None:
            found.append((_book_code(_EN_BOOK_CODES, number, name), value, int(verse) if verse else None))
    return found


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
    chapters |= {c for c, _ in pairs} | english_book_chapters(text)
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


_KO_NUMERAL = r"(\d{1,3}|[영일이삼사오육칠팔구십백]+)"
_ZH_NUMERAL = r"(\d{1,3}|[零一二三四五六七八九十百]+)"
_ES_NUMERAL = r"(\d{1,3}|" + _alternation(_ES_WORD_VALUES) + r")"
_KO_CITATION = re.compile(r"(?<![가-힣])(" + _alternation(_KO_BOOK_CODES) + r")\s*" + _KO_NUMERAL
                          + r"\s*(?:장(?:\s*" + _KO_NUMERAL + r"\s*절)?|:\s*" + _KO_NUMERAL + r")")
_ZH_CITATION = re.compile("(" + _alternation(_ZH_BOOK_CODES) + r")\s*(?:第\s*)?" + _ZH_NUMERAL
                          + r"\s*(?:章(?:\s*(?:第\s*)?" + _ZH_NUMERAL + r"\s*节)?|[:：]\s*" + _ZH_NUMERAL + ")")
# Spanish names are also given names (Juan, Pedro, Santiago), so a citation needs
# "c:v" or "capítulo"; folded text keeps character offsets for Latin letters.
_ES_ORDINAL = {"1": 1, "2": 2, "3": 3, "i": 1, "ii": 2, "iii": 3, "primera": 1, "primero": 1, "primer": 1,
               "segunda": 2, "segundo": 2, "tercera": 3, "tercero": 3, "tercer": 3}
_ES_CITATION = re.compile(r"(?:\b(" + _alternation(_ES_ORDINAL) + r")\s+(?:de\s+)?)?\b("
                          + _alternation(name for _, name in _ES_BOOK_CODES) + r")\s+(?:"
                          + r"(\d{1,3})\s*:\s*(\d{1,3})|capitulo\s+" + _ES_NUMERAL
                          + r"(?:\s*,?\s*(?:y\s+|el\s+)?versiculos?\s+" + _ES_NUMERAL + r")?)")


def book_citations(text: str, locale: str) -> list[tuple[str | None, int, int | None, tuple[int, int]]]:
    """Target citations anchored to a book name: ``(code, chapter, verse, book name span)``."""
    found = []
    if locale == "ko":
        for match in _KO_CITATION.finditer(text):
            name, chapter, verse_a, verse_b = match.groups()
            verse = verse_a or verse_b
            values = (_number_token(chapter, "ko"), _number_token(verse, "ko") if verse else None)
            if values[0] is not None:
                found.append((_KO_BOOK_CODES[name], values[0], values[1], match.span(1)))
    elif locale == "zh-Hans":
        for match in _ZH_CITATION.finditer(text):
            name, chapter, verse_a, verse_b = match.groups()
            verse = verse_a or verse_b
            values = (_number_token(chapter, "zh-Hans"), _number_token(verse, "zh-Hans") if verse else None)
            if values[0] is not None:
                found.append((_ZH_BOOK_CODES[name], values[0], values[1], match.span(1)))
    elif locale == "es":
        # Fold one character at a time so match offsets still index the original text.
        folded = "".join(_fold(char)[:1] or " " for char in text)
        for match in _ES_CITATION.finditer(folded):
            ordinal, name, chapter, verse, word_chapter, word_verse = match.groups()
            number = _ES_ORDINAL.get(ordinal) if ordinal else None
            if chapter is not None:
                values = (int(chapter), int(verse))
            else:
                values = (_ES_WORD_VALUES.get(word_chapter, _number_token(word_chapter, "es")),
                          _ES_WORD_VALUES.get(word_verse, _number_token(word_verse, "es")) if word_verse else None)
            if values[0] is not None:
                found.append((_book_code(_ES_BOOK_CODES, number, name), values[0], values[1], match.span(2)))
    return found


def english_spoken_clock_pairs(text: str) -> set[tuple[int, int]]:
    """Unambiguous spoken clock forms that can naturally become colon times."""
    pairs = set()
    hour_words = _alternation((*_UNITS, *map(str, range(1, 25))))
    for match in re.finditer(r"\b(half|quarter)\s+(past|to)\s+(" + hour_words + r")\b", text.casefold()):
        fraction, direction, token = match.groups()
        hour = int(token) if token.isdigit() else _UNITS[token]
        if 1 <= hour <= 24:
            minutes = 30 if fraction == "half" else 15
            if direction == "to":
                hour = (hour - 1) % 12 or 12
                minutes = 60 - minutes
            pairs.add((hour, minutes))
    return pairs


def target_colon_references(text: str, locale: str, spoken_clocks: set[tuple[int, int]]) -> set[tuple[int, int]]:
    """Keep bare citation pairs, excluding clocks with positive time evidence."""
    book_pairs = {(chapter, verse) for _, chapter, verse, _ in book_citations(text, locale)
                  if verse is not None}
    clock_prefix = {
        "es": r"(?:a\s+las|son\s+las|a\s+la|es\s+la|hora[s]?|mañana|tarde|noche)\s*$",
        "ko": r"(?:오전|오후|아침|저녁|밤|시간)\s*$",
        "zh-Hans": r"(?:上午|下午|早上|晚上|中午|凌晨|时间|时刻)(?:是|为|在)?\s*$",
    }[locale]
    clock_suffix = {"es": r"^\s*(?:a\.?m\.?|p\.?m\.?|horas?|de\s+la\s+(?:mañana|tarde|noche))\b",
                    "ko": r"^\s*(?:시|분)", "zh-Hans": r"^\s*(?:点|分)"}[locale]
    pairs = set()
    for match in re.finditer(_COLON_PAIR, text):
        pair = tuple(map(int, match.groups()))
        clock_shaped = 0 <= pair[0] <= 23 and 0 <= pair[1] <= 59
        is_clock = clock_shaped and (pair in spoken_clocks
            or re.search(clock_prefix, text[max(0, match.start() - 40):match.start()], re.I)
            or re.search(clock_suffix, text[match.end():match.end() + 40], re.I))
        if pair in book_pairs or not is_clock:
            pairs.add(pair)
    return pairs


def target_references(text: str, locale: str, *, spoken_clocks: set[tuple[int, int]] | None = None) -> tuple[set[tuple[int, int]], set[int]]:
    pairs = target_colon_references(text, locale, spoken_clocks or set())
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
    target_pairs, target_chapters = target_references(
        target, locale, spoken_clocks=english_spoken_clock_pairs(english))
    problems = [f"missing reference {c}:{v}" for c, v in sorted(english_pairs - target_pairs)]
    problems += [f"missing chapter {c}" for c in sorted(english_chapters - target_chapters)
                 if not any(pair[0] == c for pair in english_pairs)]
    # The speaker's words decide which references exist; a reference the
    # English did not say is an editorial addition (the 2026-10-04 ko issue).
    colon_pairs = english_colon_pairs(english)
    citations = book_citations(target, locale)
    book_pairs = {(chapter, verse) for _, chapter, verse, _ in citations if verse is not None}
    # A numeric clock match can excuse a bare target time, never a passage
    # explicitly attached to a Bible book, even if its numbers coincide.
    added_pairs = (target_pairs - english_pairs - colon_pairs) | (book_pairs - english_pairs)
    problems += [f"added reference {c}:{v}" for c, v in sorted(added_pairs)]
    # The book must survive translation: "Revelation 3:4" is not "Juan 3:4".
    # When only one side spells the verse with the book ("John chapter three
    # verse sixteen" vs "Romanos 3:16"), compare the books by chapter.
    english_books: dict[tuple[int, int | None], set[str]] = {}
    english_chapter_books: dict[int, set[str]] = {}
    for code, chapter, verse in english_book_citations(english):
        if code is not None:
            english_books.setdefault((chapter, verse), set()).add(code)
            english_chapter_books.setdefault(chapter, set()).add(code)

    def book_changed(code: str, chapter: int, verse: int | None) -> bool:
        books = english_books.get((chapter, verse)) or english_chapter_books.get(chapter)
        return books is not None and code not in books
    problems += [f"book changed for {chapter}" + (f":{verse}" if verse is not None else "")
                 for code, chapter, verse, _ in citations
                 if code is not None and book_changed(code, chapter, verse)]
    # A chapter-only citation the English never said ("요한복음 3장"). Without a
    # book name, a number the English said for another reason ("three sheets",
    # 종이 3장; "three chapters", 三章) is a counter, not a citation.
    said = {value for value in english_numbers(english) if isinstance(value, int)}
    said |= {value for pair in colon_pairs for value in pair}
    book_chapters = {chapter for _, chapter, _, _ in citations}
    unsaid = (target_chapters - english_chapters - english_book_chapters(english)
              - {c for c, _ in colon_pairs} - {c for c, _ in added_pairs})
    problems += [f"added chapter {c}" for c in sorted(unsaid) if c in book_chapters or c not in said]
    return problems


# --- Remaining screens ---------------------------------------------------------
# Frequent Traditional-only characters: none occurs in the pinned Simplified CUV
# (data/scripture/cmn-cu89s.json), which a test checks.
_TRADITIONAL_ONLY = frozenset(
    "們這個為說來會時國學與對過還從經發現關點開問間頭樣種實體讓應當認識禱聖榮愛義靈讀聽見長門東車書"
    "馬魚鳥話語誰請謝證記該給錢錯難電頁題顏願風飛飯黨齊龍歲歷氣決處傳價優億兒內兩冊劃動務勝勞區協單"
    "參雙變號嗎嚴圖園圓團壞壓夢奪婦寫寶將專尋導屬層島師帶幫幾廣張彈後復態戰戶歡歸殺漢準滿燈爭爾狀獨"
    "環產畫異盡監確禮稱竊筆簡糧紀紅純紙級細終結統絕網線練總罰羅習聯聲職腦臉舊艱華萬葉藝蘇蟲術衛裝製"
    "複規視親覺觀計訂訴診評試詩詳誠誤課調談論譯議貝負財貨貧責貴買費資賣質贏趕趙跡輕輸轉辦農進連運達"
    "違遠選遺邊郵鄉醫釋針鐵銀鋼鏡閉閱陳陽隊階際隨險隱雖雜離雲靜響項順須預領類顯館驗髮鬥魯鮮麗黃麼沒"
    "裡裏臺隻爺賜惡")


def script_problems(text: str, locale: str) -> list[str]:
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return ["no target-language letters"]
    hangul = sum("가" <= char <= "힣" or "ᄀ" <= char <= "ᇿ" for char in letters)
    kana = sum("぀" <= char <= "ヿ" for char in letters)
    han = sum("一" <= char <= "鿿" or "㐀" <= char <= "䶿" for char in letters)
    cjk = han + kana
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
    if locale == "zh-Hans":
        if han / len(letters) < 0.6:
            problems.append(f"Han share {han / len(letters):.2f} < 0.60")
        if kana or hangul:
            problems.append("Japanese kana or Hangul in Simplified Chinese text")
        traditional = sum(char in _TRADITIONAL_ONLY for char in letters)
        if traditional >= 2 or (traditional and traditional / max(han, 1) >= 0.1):
            problems.append(f"{traditional} Traditional-only characters in Simplified Chinese text")
    return problems


# One-word groups that legitimately read the same in Spanish and English.
_SHARED_SINGLE_WORDS = frozenset({"no", "amen", "hallelujah", "hosanna", "selah", "maranatha", "shalom", "ok"})


def untranslated_problems(english: str, text: str, locale: str,
                          shared_terms: frozenset[str] = frozenset()) -> list[str]:
    """``shared_terms``: folded glossary names that may stay as in English."""
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
    # Exact multiword copies are untranslated even without a function word.
    # A single name/amen, or an honorific plus a name, can legitimately survive.
    target_words, size = re.findall(r"[a-z']+", _fold(text)), len(english_words)
    name_only = bool(re.fullmatch(r"(?:Pastor|Dr|Mr|Mrs|Ms)\.?\s+[A-Z][a-z]+[.!?]?", english.strip()))
    if size >= 2 and not name_only and any(
            target_words[start:start + size] == english_words for start in range(len(target_words) - size + 1)):
        return ["English source text copied into target"]
    # A one-word group copied as is ("Repent." -> "Repent."). A deliberate
    # Spanish spelling (Amén, Jesús) differs before folding, so it is kept.
    if (size == 1 and target_words == [_fold(english_words[0])]
            and re.findall(r"[^\W\d_]+", text.casefold()) == [english_words[0]]
            and english_words[0] not in _SHARED_SINGLE_WORDS | shared_terms):
        return ["English source text copied into target"]
    return []


def shared_terms(policy: dict | None) -> frozenset[str]:
    """Glossary names whose source and target spellings may coincide."""
    if not policy:
        return frozenset()
    return frozenset(_fold(word) for kind in ("properNames", "seriesNames")
                     for term in policy.get("terminology", {}).get(kind, [])
                     for value in (term.get("source"), term.get("target")) if value
                     for word in re.findall(r"[a-zA-Z']+", _fold(value)))


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


# "1 John", "2 Peter": the digit is part of the book name, rendered as 요한일서,
# Primera de Juan or 约翰一书 rather than as a cardinal.
_ENGLISH_BOOK_ORDINAL = re.compile(r"\b([123])\s*(?:" + _alternation(
    name for number, name in _EN_BOOK_CODES if number is not None) + r")\b")


def number_problems(english: str, text: str, locale: str, references: set[tuple[int, int]]) -> list[str]:
    present = {"ko": korean_number_present, "es": spanish_number_present,
               "zh-Hans": chinese_number_present}[locale]
    reference_numbers = {value for pair in references for value in pair}
    said = english_numbers(english)
    ordinals = [int(value) for value in _ENGLISH_BOOK_ORDINAL.findall(english)]
    missing = [value for value in dict.fromkeys(said)
               if value not in reference_numbers and said.count(value) > ordinals.count(value)
               and not present(text, value)]
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
        ("untranslated_source", untranslated_problems(english, text, locale, shared_terms(policy)),
         "Untranslated English screen"),
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
