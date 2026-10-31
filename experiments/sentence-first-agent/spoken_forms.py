"""TTS-only spoken forms that keep the written target unchanged (experiment helper).

2026-10-30: adds the number/verse/page reader the rehearsal showed was missing.
`build_spoken_forms` turns Arabic digits into each locale's reading and returns the
minimal {written: spoken} pairs for review.json `spokenForms`; `merge_spoken_forms`
still applies the 撒但→撒旦 default.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# "撒但" is split by the Qwen3-TTS tokenizer/phonemizer: ASR heard "傻，但" / "洒，但"
# in 13 of 22 sentences. Speaking "魔鬼" fixed 22/22 recognitions, but the product
# decision on 2026-10-26 is to speak "撒旦" and keep the written "撒但"; the ASR split
# risk is accepted. Explicit review.json mappings still win over this default.
DEFAULT_SPOKEN_FORMS = {"撒但": "撒旦"}

ZH = "零一二三四五六七八九"
KO = ["영", "일", "이", "삼", "사", "오", "육", "칠", "팔", "구"]
ES_SMALL = ["cero", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve",
            "diez", "once", "doce", "trece", "catorce", "quince", "dieciséis", "diecisiete",
            "dieciocho", "diecinueve", "veinte"]
ES_TENS = {30: "treinta", 40: "cuarenta", 50: "cincuenta", 60: "sesenta", 70: "setenta",
           80: "ochenta", 90: "noventa"}
ES_HUNDREDS = {100: "ciento", 200: "doscientos", 300: "trescientos", 400: "cuatrocientos",
               500: "quinientos", 600: "seiscientos", 700: "setecientos", 800: "ochocientos",
               900: "novecientos"}


def zh_number(n: int) -> str:
    if n > 9999:
        return "".join(ZH[int(d)] for d in str(n))
    if n >= 1000:
        thousands, rest = divmod(n, 1000)
        head = ZH[thousands] + "千"
        return head + (zh_number(rest) if rest else "")
    if n < 10:
        return ZH[n]
    if n < 20:
        return "十" + (ZH[n - 10] if n > 10 else "")
    if n < 100:
        tens, ones = divmod(n, 10)
        return ZH[tens] + "十" + (ZH[ones] if ones else "")
    hundreds, rest = divmod(n, 100)
    if not rest:
        return ZH[hundreds] + "百"
    return ZH[hundreds] + "百" + ("零" + zh_number(rest) if rest < 10 else zh_number(rest))


def ko_number(n: int) -> str:
    if n > 9999:
        return "".join(KO[int(d)] for d in str(n))
    if n >= 1000:
        thousands, rest = divmod(n, 1000)
        head = ("" if thousands == 1 else KO[thousands]) + "천"
        return head + (ko_number(rest) if rest else "")
    if n < 10:
        return KO[n]
    if n < 100:
        tens, ones = divmod(n, 10)
        return ("" if tens == 1 else KO[tens]) + "십" + (KO[ones] if ones else "")
    hundreds, rest = divmod(n, 100)
    head = ("" if hundreds == 1 else KO[hundreds]) + "백"
    if not rest:
        return head
    if rest < 10:
        return head + KO[rest]
    tens, ones = divmod(rest, 10)
    return head + ("" if tens == 1 else KO[tens]) + "십" + (KO[ones] if ones else "")


def es_number(n: int) -> str:
    if n > 9999:
        return " ".join(ES_SMALL[int(d)] for d in str(n))
    if n >= 1000:
        thousands, rest = divmod(n, 1000)
        head = "mil" if thousands == 1 else f"{es_number(thousands)} mil"
        return head + (f" {es_number(rest)}" if rest else "")
    if n <= 20:
        return ES_SMALL[n]
    if n < 30:
        return "veinti" + {1: "uno", 2: "dós", 3: "trés", 4: "cuatro", 5: "cinco", 6: "séis",
                           7: "siete", 8: "ocho", 9: "nueve"}[n - 20]
    if n < 100:
        tens, ones = divmod(n, 10)
        return ES_TENS[tens * 10] + (f" y {ES_SMALL[ones]}" if ones else "")
    hundreds = (n // 100) * 100
    rest = n % 100
    head = "cien" if n == 100 else ES_HUNDREDS[hundreds]
    return head + (f" {es_number(rest)}" if rest else "")


NUMBER = {"zh-Hans": zh_number, "ko": ko_number, "es": es_number}

VERSE = {
    "zh-Hans": lambda c, v, e=None: f"{zh_number(c)}章{zh_number(v)}节" + (f"到{zh_number(e)}节" if e else ""),
    "ko": lambda c, v, e=None: f"{ko_number(c)}장 {ko_number(v)}절" + (f"부터 {ko_number(e)}절까지" if e else ""),
    "es": lambda c, v, e=None: (f"capítulo {es_number(c)}, versículo {es_number(v)}"
                                + (f" al {es_number(e)}" if e else "")),
}
CHAPTER = {"zh-Hans": lambda n: f"{zh_number(n)}章", "ko": lambda n: f"{ko_number(n)}장",
           "es": lambda n: f"capítulo {es_number(n)}"}
VERSE_ONLY = {"zh-Hans": lambda n: f"{zh_number(n)}节", "ko": lambda n: f"{ko_number(n)}절",
              "es": lambda n: f"versículo {es_number(n)}"}
PAGE = {"zh-Hans": lambda n: f"第{zh_number(n)}页", "ko": lambda n: f"{ko_number(n)}쪽",
        "es": lambda n: f"página {es_number(n)}"}
SCORE = {"zh-Hans": lambda a, b: f"{zh_number(a)}胜{zh_number(b)}负",
         "ko": lambda a, b: f"{ko_number(a)}승 {ko_number(b)}패",
         "es": lambda a, b: f"{es_number(a)} victorias y {es_number(b)} derrotas"}

PATTERNS = {
    "zh-Hans": [
        (re.compile(r"(\d+)\s*胜\s*(\d+)\s*负"), lambda m: SCORE["zh-Hans"](int(m[1]), int(m[2]))),
        (re.compile(r"(\d+):(\d+)-(\d+)"), lambda m: VERSE["zh-Hans"](int(m[1]), int(m[2]), int(m[3]))),
        (re.compile(r"(\d+):(\d+)"), lambda m: VERSE["zh-Hans"](int(m[1]), int(m[2]))),
        (re.compile(r"第\s*(\d+)\s*页"), lambda m: PAGE["zh-Hans"](int(m[1]))),
        (re.compile(r"(\d+)\s*章\s*(\d+)\s*节"), lambda m: VERSE["zh-Hans"](int(m[1]), int(m[2]))),
        (re.compile(r"(\d+)\s*章"), lambda m: CHAPTER["zh-Hans"](int(m[1]))),
        (re.compile(r"(\d+)\s*节"), lambda m: VERSE_ONLY["zh-Hans"](int(m[1]))),
    ],
    "ko": [
        (re.compile(r"(\d+)\s*승\s*(\d+)\s*패"), lambda m: SCORE["ko"](int(m[1]), int(m[2]))),
        (re.compile(r"(\d+):(\d+)-(\d+)"), lambda m: VERSE["ko"](int(m[1]), int(m[2]), int(m[3]))),
        (re.compile(r"(\d+):(\d+)"), lambda m: VERSE["ko"](int(m[1]), int(m[2]))),
        (re.compile(r"(\d+)\s*장\s*(\d+)\s*절"), lambda m: VERSE["ko"](int(m[1]), int(m[2]))),
        (re.compile(r"(\d+)\s*쪽"), lambda m: PAGE["ko"](int(m[1]))),
        (re.compile(r"(\d+)\s*장"), lambda m: CHAPTER["ko"](int(m[1]))),
        (re.compile(r"(\d+)\s*절"), lambda m: VERSE_ONLY["ko"](int(m[1]))),
    ],
    "es": [
        (re.compile(r"(\d+)\s*victorias?.{0,25}?(\d+)\s*derrotas?", re.I),
         lambda m: SCORE["es"](int(m[1]), int(m[2]))),
        (re.compile(r"(\d+):(\d+)-(\d+)"), lambda m: VERSE["es"](int(m[1]), int(m[2]), int(m[3]))),
        (re.compile(r"(\d+):(\d+)"), lambda m: VERSE["es"](int(m[1]), int(m[2]))),
        (re.compile(r"cap[ií]tulo\s+(\d+)\s*(?:,|:)\s*(\d+)", re.I),
         lambda m: VERSE["es"](int(m[1]), int(m[2]))),
        (re.compile(r"p[aá]gina\s+(\d+)", re.I), lambda m: PAGE["es"](int(m[1]))),
        (re.compile(r"cap[ií]tulo\s+(\d+)", re.I), lambda m: CHAPTER["es"](int(m[1]))),
        (re.compile(r"vers[ií]culo\s+(\d+)", re.I), lambda m: VERSE_ONLY["es"](int(m[1]))),
    ],
}


def forms_for_text(text: str, locale: str = "zh-Hans") -> dict[str, str]:
    """One sentence: minimal substring replacements, else the whole line."""
    pairs: dict[str, str] = {}
    for pattern, build in PATTERNS[locale]:
        for match in pattern.finditer(text):
            pairs[match.group(0)] = build(match)
    for match in re.finditer(r"\d+", text):
        pairs.setdefault(match.group(0), NUMBER[locale](int(match.group(0))))
    written, kept = text, {}
    for key in sorted(pairs, key=len, reverse=True):
        if key in written:
            kept[key] = pairs[key]
            written = written.replace(key, pairs[key])
    if re.search(r"\d", written):  # pattern gaps: convert the whole line instead
        whole = text
        for match in re.finditer(r"\d+", text):
            whole = whole.replace(match.group(0), NUMBER[locale](int(match.group(0))))
        return {text: whole}
    return kept


def build_spoken_forms(targets: list[str], locale: str = "zh-Hans") -> dict[str, str]:
    forms: dict[str, str] = {}
    for target in targets:
        if not re.search(r"\d", target):
            continue
        for key, value in forms_for_text(target, locale).items():
            forms.setdefault(key, value)
    return dict(sorted(forms.items(), key=lambda item: -len(item[0])))


def merge_spoken_forms(base: dict | None, targets: list[str]) -> dict[str, str]:
    """Apply a default only when at least one target contains the written form."""
    merged = {written: spoken for written, spoken in (base or {}).items()
              if any(written in target for target in targets)}
    for written, spoken in DEFAULT_SPOKEN_FORMS.items():
        if any(written in target for target in targets):
            merged.setdefault(written, spoken)
    return merged


def main() -> int:
    parser = argparse.ArgumentParser(description="build review.json spokenForms from digit text")
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--locale", choices=tuple(NUMBER), default="zh-Hans")
    parser.add_argument("--check", action="store_true", help="report only, do not write review.json")
    args = parser.parse_args()
    sentences = [json.loads(line) for line in
                 (args.run / "sentences.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    translations = [json.loads(line) for line in
                    (args.run / "translations.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    forms = build_spoken_forms([row["target"] for row in translations], args.locale)
    left = [row["id"] for row in translations
            if re.search(r"\d", row["target"])
            and not any(key in row["target"] for key in forms)]
    review_path = args.run / "review.json"
    review = json.loads(review_path.read_text(encoding="utf-8")) if review_path.is_file() else {}
    review["spokenForms"] = merge_spoken_forms(forms, [row["target"] for row in translations])
    if not args.check:
        review_path.write_text(json.dumps(review, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"sentences": len(sentences), "forms": len(forms), "uncovered": left,
                      "written": not args.check}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
