#!/usr/bin/env python3
"""Pinned, offline CUV retrieval; quotation detection remains a separate stage.

The existing Bible index is deliberately reused. It is accepted only when its
entire canonical JSON matches the reviewed eBible edition, not merely when its
metadata says "CUV". No model-generated scripture or guessed verse splitting is
allowed through this interface.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from scripts.build_scripture_index import BOOKS, build_full_bible_payload
except ModuleNotFoundError:  # Direct script execution.
    from build_scripture_index import BOOKS, build_full_bible_payload

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LIBRARY_PATH = ROOT / "data/scripture/cmn-cu89s.json"
DEFAULT_PROVENANCE_PATH = ROOT / "data/scripture/cmn-cu89s.provenance.json"
SOURCE_URL = "https://ebible.org/Scriptures/cmn-cu89s_vpl.zip"
DETAILS_URL = "https://ebible.org/bible/details.php?id=cmn-cu89s"
EDITION_ID = "cmn-cu89s"
SOURCE_ARCHIVE_SHA256 = "8c9969ea5659835c132f9ce93101b948cd04edf298ca507ae50bbe77858d5027"
SOURCE_TEXT_SHA256 = "f9264d61e7abc7cda2e74ed465b0f99fa64038bcdc7e9af1d4dcc9e80e2db705"
LIBRARY_CONTENT_SHA256 = "9c43dacae44a16ce5fb56bb42ba3afde9f8facfe1eaf1b9ebba6a9b76c8cb80f"
NORMALIZED_VERSES_SHA256 = "0e73438c22372c7b65bef5215827c38d0ab7ada8f49551c09d6e9c97c354c49d"


class CuvError(ValueError):
    """Invalid reference, untrusted source, or non-exact scripture text."""


def sha256(value: bytes | str) -> str:
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def canonical_hash(value: Any) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _book_key(value: str) -> str:
    value = value.strip().casefold().replace("《", "").replace("》", "")
    value = re.sub(r"^(?:the\s+)?(?:book\s+of\s+)", "", value)
    for ordinal, number in (("first", "1"), ("second", "2"), ("third", "3")):
        value = re.sub(rf"^{ordinal}\s+", number, value)
    value = re.sub(r"^iii\s+", "3", value)
    value = re.sub(r"^ii\s+", "2", value)
    value = re.sub(r"^i\s+", "1", value)
    return re.sub(r"[\s_.-]+", "", value)


# All 66 names and eBible codes come from the existing index builder; these are
# aliases only and cannot add or modify text in the pinned Bible.
_EXTRA_ALIASES = {
    "GEN": "Gen 创 創世記 創", "EXO": "Exod Ex 出 出埃及記", "LEV": "Lev 利 利未記",
    "NUM": "Num 民 民數記", "DEU": "Deut Dt 申 申命記", "JOS": "Josh 书 書 約書亞記",
    "JDG": "Judg 士 士師記", "RUT": "Ruth 得 路得記", "1SA": "1Sam 撒上 撒母耳記上",
    "2SA": "2Sam 撒下 撒母耳記下", "1KI": "1Kgs 1King 王上 列王紀上",
    "2KI": "2Kgs 2King 王下 列王紀下", "1CH": "1Chron 1Chr 代上 歷代志上",
    "2CH": "2Chron 2Chr 代下 歷代志下", "EZR": "Ezra 拉 以斯拉記",
    "NEH": "Neh 尼 尼希米記", "EST": "Esth 斯 以斯帖記", "JOB": "Job 伯 約伯記",
    "PSA": "Psalm Ps 诗 詩 詩篇", "PRO": "Prov Pr 箴", "ECC": "Eccl Ec 传 傳 傳道書",
    "SOL": "Song Sng Cant 雅", "ISA": "Isa 赛 賽 以賽亞書", "JER": "Jer 耶 耶利米書",
    "LAM": "Lam 哀", "EZE": "Ezek Ezk 结 結 以西結書", "DAN": "Dan 但 但以理書",
    "HOS": "Hos 何 何西阿書", "JOE": "Joel 珥 約珥書", "AMO": "Amos 摩 阿摩司書",
    "OBA": "Obad Ob 俄 俄巴底亞書", "JON": "Jonah 拿 約拿書", "MIC": "Mic 弥 彌 彌迦書",
    "NAH": "Nah 鸿 鴻 那鴻書", "HAB": "Hab 哈 哈巴谷書", "ZEP": "Zeph Zph 番 西番雅書",
    "HAG": "Hag 该 該 哈該書", "ZEC": "Zech 撒 撒迦利亞書", "MAL": "Mal 玛 瑪 瑪拉基書",
    "MAT": "Matt Mt 太 馬太福音", "MAR": "Mark Mk MRK 可 馬可福音", "LUK": "Luke Lk 路",
    "JOH": "John Jn JHN 约 約 約翰福音", "ACT": "Acts 徒 使徒行傳", "ROM": "Rom 罗 羅 羅馬書",
    "1CO": "1Cor 林前 哥林多前書", "2CO": "2Cor 林后 林後 哥林多後書",
    "GAL": "Gal 加 加拉太書", "EPH": "Eph 弗 以弗所書", "PHI": "Phil Php 腓 腓立比書",
    "COL": "Col 西 歌羅西書", "1TH": "1Thess 帖前 帖撒羅尼迦前書",
    "2TH": "2Thess 帖后 帖後 帖撒羅尼迦後書", "1TI": "1Tim 提前 提摩太前書",
    "2TI": "2Tim 提后 提後 提摩太後書", "TIT": "Titus 多 提多書",
    "PHM": "Philem 门 門 腓利門書", "HEB": "Heb 来 來 希伯來書", "JAM": "James Jas 雅各 雅各書",
    "1PE": "1Pet 彼前 彼得前書", "2PE": "2Pet 彼后 彼後 彼得後書",
    "1JO": "1Jn 約翰一書 约一 約一", "2JO": "2Jn 約翰二書 约二 約二",
    "3JO": "3Jn 約翰三書 约三 約三", "JUD": "Jude 犹 猶 猶大書",
    "REV": "Rev Re 启 啟 啟示錄",
}
BOOK_ALIASES: dict[str, str] = {}
for _code, (_english, _chinese) in BOOKS.items():
    for _alias in [_code, _english, _chinese, *_EXTRA_ALIASES[_code].split()]:
        BOOK_ALIASES[_book_key(_alias)] = _code
BOOK_ALIASES.update({_book_key(x): "SOL" for x in ("Song of Solomon", "Song of Songs")})


def normalize_book(value: str) -> str:
    try:
        return BOOK_ALIASES[_book_key(value)]
    except KeyError as exc:
        raise CuvError(f"Unknown Bible book: {value!r}") from exc


@dataclass(frozen=True)
class Reference:
    book: str
    chapter: int
    start_verse: int
    end_verse: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "book", normalize_book(self.book))
        if self.end_verse is None:
            object.__setattr__(self, "end_verse", self.start_verse)
        values = (self.chapter, self.start_verse, self.end_verse)
        if any(type(x) is not int or x < 1 for x in values):
            raise CuvError("Chapter and verse numbers must be positive integers")
        if self.end_verse < self.start_verse:  # type: ignore[operator]
            raise CuvError("Reversed verse range")

    @property
    def suffix(self) -> str:
        return f"{self.chapter}:{self.start_verse}" + (
            f"-{self.end_verse}" if self.end_verse != self.start_verse else ""
        )

    @property
    def canonical_ref(self) -> str:
        return f"{self.book} {self.suffix}"

    @property
    def display_ref(self) -> str:
        return f"{BOOKS[self.book][1]} {self.suffix}"

    @property
    def key(self) -> str:
        return self.canonical_ref


_DIGITS = {ch: n for n, ch in enumerate("零一二三四五六七八九")}
_DIGITS.update({"〇": 0, "两": 2, "兩": 2})
_EN_NUMBERS = dict(zip(
    "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split(),
    range(1, 20),
))
_EN_TENS = dict(zip("twenty thirty forty fifty sixty seventy eighty ninety".split(), range(20, 100, 10)))
_EN_NUMBER_PATTERN = "|".join(sorted([*_EN_NUMBERS, *_EN_TENS, "hundred"], key=len, reverse=True))


def _number(value: str) -> int:
    value = value.strip().lower().replace("-", " ")
    if value.isascii() and value.isdigit():
        return int(value)
    if re.fullmatch(r"[零〇一二三四五六七八九十百两兩]+", value):
        if "十" not in value and "百" not in value:
            return int("".join(str(_DIGITS[x]) for x in value))
        result = current = 0
        for ch in value:
            if ch in _DIGITS:
                current = _DIGITS[ch]
            else:
                result += (current or 1) * {"十": 10, "百": 100}[ch]
                current = 0
        return result + current
    words = value.split()
    if len(words) == 1 and words[0] in _EN_NUMBERS:
        return _EN_NUMBERS[words[0]]
    if words and words[0] in _EN_TENS:
        if len(words) == 1:
            return _EN_TENS[words[0]]
        if len(words) == 2 and words[1] in _EN_NUMBERS and _EN_NUMBERS[words[1]] < 10:
            return _EN_TENS[words[0]] + _EN_NUMBERS[words[1]]
    if len(words) >= 2 and words[0] in _EN_NUMBERS and _EN_NUMBERS[words[0]] < 10 and words[1] == "hundred":
        return _EN_NUMBERS[words[0]] * 100 + (_number(" ".join(words[2:])) if len(words) > 2 else 0)
    raise CuvError(f"Unsupported number: {value!r}")


def _normalize_reference_words(value: str) -> str:
    value = value.strip().strip("。.")
    value = value.replace("：", ":").replace("—", "-").replace("–", "-")
    value = re.sub(r"[,，]\s*(?=(?:chapter|verse|第|\d))", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"[零〇一二三四五六七八九十百两兩]+(?=\s*[章节節篇])", lambda m: str(_number(m[0])), value)
    value = re.sub(r"[零〇一二三四五六七八九十百两兩]+(?=\s*(?:到|至))", lambda m: str(_number(m[0])), value)
    # English spoken numbers are bounded words: never edit a book name.
    number_phrase = rf"\b(?:{_EN_NUMBER_PATTERN})(?:(?:\s+|-)(?:{_EN_NUMBER_PATTERN}))*\b"
    value = re.sub(number_phrase, lambda m: str(_number(m[0])), value, flags=re.IGNORECASE)
    value = re.sub(r"\b(?:through|to)\b|到|至", "-", value, flags=re.IGNORECASE)
    value = re.sub(r"\bchapters?\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s*\bverses?\s*", ":", value, flags=re.IGNORECASE)
    value = re.sub(r"第(?=\s*\d)", "", value)
    value = re.sub(r"(?<=\d)[章篇]\s*", ":", value)
    value = re.sub(r"[节節]", "", value)
    return re.sub(r"\s+", " ", value).strip()


def parse_reference(value: str, *, context: Reference | str | None = None) -> Reference:
    """Parse a reference, not arbitrary prose; no reference or verse is guessed.

    Relative forms such as "verse nine" require an explicit prior reference.
    A chapter alone and a cross-chapter range are intentionally rejected.
    """
    prior = parse_reference(context) if isinstance(context, str) else context
    clean = _normalize_reference_words(value)
    match = re.fullmatch(r"(.+?)\s*[. ]?\s*(\d+)\s*:\s*(\d+)\s*(?:-\s*(\d+))?", clean)
    if match:
        book, chapter, start, end = match.groups()
        try:
            normalize_book(book)
        except CuvError:
            pass  # A contextual "12:9" must not be read as book 1, chapter 2.
        else:
            return Reference(book.strip(" ."), int(chapter), int(start), int(end) if end else None)
    if prior:
        match = re.fullmatch(r"(?:(\d+)\s*:|:)\s*(\d+)(?:\s*-\s*(\d+))?", clean)
        if not match and re.fullmatch(r"\d+(?:\s*-\s*\d+)?", clean):
            match = re.fullmatch(r"(?:(\d+)\s*:)?(\d+)(?:\s*-\s*(\d+))?", clean)
        if match:
            chapter, start, end = match.groups()
            return Reference(prior.book, int(chapter) if chapter else prior.chapter, int(start), int(end) if end else None)
    raise CuvError(f"Need an explicit book, chapter and verse (or context): {value!r}")


def parse_vpl_bytes(raw: bytes) -> list[Any]:
    """Strictly parse every VPL line, preserving characters except source whitespace."""
    try:
        from scripts.build_scripture_index import Verse
    except ModuleNotFoundError:
        from build_scripture_index import Verse
    verses, seen = [], set()
    for line_number, line in enumerate(raw.decode("utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        match = re.fullmatch(r"([1-3]?[A-Z]{2,3}) (\d+):(\d+) (.+)", line)
        if not match:
            raise CuvError(f"Unparsed VPL line {line_number}")
        book, chapter, verse, text = match.groups()
        key = book, int(chapter), int(verse)
        if book not in BOOKS or min(key[1:]) < 1 or key in seen:
            raise CuvError(f"Unknown, duplicate or invalid verse at line {line_number}")
        seen.add(key)
        text = re.sub(r"\s+", " ", text.replace("\u3000", " ")).strip()
        if not text:
            raise CuvError(f"Empty verse at line {line_number}")
        verses.append(Verse(book=book, chapter=key[1], verse=key[2], text=text))
    return verses


def verify_archive(path: Path) -> bytes:
    if sha256(path.read_bytes()) != SOURCE_ARCHIVE_SHA256:
        raise CuvError("Source archive hash differs from the fixed CUV edition; explicit source review required")
    with zipfile.ZipFile(path) as archive:
        raw = archive.read("cmn-cu89s_vpl.txt")
    if sha256(raw) != SOURCE_TEXT_SHA256:
        raise CuvError("Source VPL text hash mismatch")
    return raw


def build_library(archive_path: Path, out: Path) -> dict[str, Any]:
    raw = verify_archive(archive_path)
    payload = build_full_bible_payload(parse_vpl_bytes(raw), SOURCE_URL)
    if canonical_hash(payload) != LIBRARY_CONTENT_SHA256:
        raise CuvError("Rebuilt library differs from the pinned content")
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if out.exists() and out.read_bytes() != encoded:
        raise CuvError(f"Refusing to overwrite a different library: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(encoded)
    return {"status": "verified", "path": str(out), "fileSha256": sha256(encoded), "contentSha256": canonical_hash(payload)}


class CuvLibrary:
    def __init__(self, data: dict[str, Any], provenance: dict[str, Any]):
        if canonical_hash(data) != LIBRARY_CONTENT_SHA256:
            raise CuvError("Bible content hash mismatch; never substitute unverified scripture")
        expected = {
            "schemaVersion": 1, "editionId": EDITION_ID,
            "sourceUrl": SOURCE_URL, "archiveSha256": SOURCE_ARCHIVE_SHA256,
            "sourceTextSha256": SOURCE_TEXT_SHA256, "libraryContentSha256": LIBRARY_CONTENT_SHA256,
            "normalizedVersesSha256": NORMALIZED_VERSES_SHA256,
        }
        if any(provenance.get(k) != v for k, v in expected.items()):
            raise CuvError("CUV provenance does not match the pinned edition")
        # Callers may retain their input dictionaries. Freeze our validated
        # snapshot so later mutation cannot change already-verified scripture.
        self._data = json.loads(json.dumps(data, ensure_ascii=False))
        self._provenance = dict(provenance)

    @classmethod
    def from_path(cls, path: str | Path = DEFAULT_LIBRARY_PATH, *, provenance_path: str | Path = DEFAULT_PROVENANCE_PATH) -> "CuvLibrary":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")), json.loads(Path(provenance_path).read_text(encoding="utf-8")))

    @property
    def provenance(self) -> dict[str, Any]:
        return dict(self._provenance)

    def lookup(self, ref: Reference | str, *, excerpt: str | None = None) -> dict[str, Any]:
        reference = parse_reference(ref) if isinstance(ref, str) else ref
        if not isinstance(reference, Reference):
            raise CuvError("lookup requires a Reference or an explicit reference string")
        available = {item["verse"]: item["text"] for item in self._data["chapters"].get(reference.book, {}).get(str(reference.chapter), [])}
        if not available or reference.end_verse > max(available):
            raise CuvError(f"Missing verse(s) in pinned source: {reference.canonical_ref}")
        # A source may merge verse numbers. Missing numbers are a review issue,
        # not a license to silently omit a verse or split a neighbouring verse.
        missing = [v for v in range(reference.start_verse, reference.end_verse + 1) if v not in available]
        if missing:
            raise CuvError(f"Missing verse(s) in pinned source: {reference.book} {reference.chapter}:{','.join(map(str, missing))}; check source verse grouping")
        verses = [{"ref": f"{reference.book} {reference.chapter}:{v}", "verse": v, "text": available[v]} for v in range(reference.start_verse, reference.end_verse + 1)]
        full_text = "".join(v["text"] for v in verses)
        text, start, end = full_text, 0, len(full_text)
        if excerpt is not None:
            if not excerpt or excerpt not in full_text:
                raise CuvError("Excerpt must be an exact, non-empty contiguous substring of the source text")
            if full_text.count(excerpt) != 1:
                raise CuvError("Ambiguous excerpt: include more source words to identify one occurrence")
            start, end = full_text.index(excerpt), full_text.index(excerpt) + len(excerpt)
            text = excerpt
        return {
            "schemaVersion": 1, "canonicalRef": reference.canonical_ref, "displayRef": reference.display_ref,
            "book": reference.book, "chapter": reference.chapter, "startVerse": reference.start_verse, "endVerse": reference.end_verse,
            "edition": {"id": EDITION_ID, "nameZh": "新标点和合本（简体，神版）", "license": "Public Domain"},
            "source": {"url": SOURCE_URL, "detailsUrl": DETAILS_URL, "archiveSha256": SOURCE_ARCHIVE_SHA256, "libraryContentSha256": LIBRARY_CONTENT_SHA256},
            "verses": verses, "fullText": full_text, "text": text, "textSha256": sha256(text),
            "selection": {"kind": "exact_excerpt" if excerpt is not None else "whole_verses", "startChar": start, "endChar": end},
        }

    def verify_text(self, ref: Reference | str, text: str, *, excerpt: bool = False) -> dict[str, Any]:
        result = self.lookup(ref, excerpt=text if excerpt else None)
        if result["text"] != text:
            raise CuvError("Scripture text does not exactly match the pinned CUV source")
        return result


def prepare_spoken_input(text: str) -> dict[str, Any]:
    """Remove only silent editorial brackets/spacing; retain every spoken word.

    [圣]灵 therefore becomes 圣灵. This never removes bracket contents, changes
    神 to 上帝, paraphrases a word, or writes back to display text.
    """
    if not isinstance(text, str) or not text:
        raise CuvError("Spoken input needs non-empty canonical text")
    spoken = re.sub(r"\s+", "", text).replace("[", "").replace("]", "")
    return {"displayText": text, "displayTextSha256": sha256(text), "spokenText": spoken, "spokenTextSha256": sha256(spoken), "transforms": ["remove_whitespace", "remove_editorial_bracket_glyphs_keep_contents"], "schemaVersion": 1}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="Rebuild the fixed edition from a hash-checked ZIP")
    build.add_argument("--archive", type=Path, default=ROOT / "artifacts/cuv-scripture/cmn-cu89s_vpl.zip")
    build.add_argument("--download", action="store_true", help="Download the fixed source URL if ZIP is missing")
    build.add_argument("--out", type=Path, default=ROOT / "artifacts/cuv-scripture/cmn-cu89s.json")
    for command in ("query", "verify"):
        sub = commands.add_parser(command)
        sub.add_argument("--library", type=Path, default=DEFAULT_LIBRARY_PATH)
        sub.add_argument("--provenance", type=Path, default=DEFAULT_PROVENANCE_PATH)
        if command == "query":
            sub.add_argument("reference")
            sub.add_argument("--context")
            sub.add_argument("--excerpt")
            sub.add_argument("--spoken-input", action="store_true")
        else:
            sub.add_argument("--archive", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            if args.download and not args.archive.exists():
                with urllib.request.urlopen(SOURCE_URL, timeout=45) as response:
                    raw = response.read()
                if sha256(raw) != SOURCE_ARCHIVE_SHA256:
                    raise CuvError("Downloaded archive differs from the fixed edition; not saved")
                args.archive.parent.mkdir(parents=True, exist_ok=True)
                args.archive.write_bytes(raw)
            result = build_library(args.archive, args.out)
        else:
            library = CuvLibrary.from_path(args.library, provenance_path=args.provenance)
            if args.command == "verify":
                if args.archive:
                    verify_archive(args.archive)
                result = {"status": "verified", "editionId": EDITION_ID, "contentSha256": LIBRARY_CONTENT_SHA256, "bookCount": 66, "chapterCount": 1189, "verseEntryCount": 31021, "sourceArchiveVerifiedNow": bool(args.archive)}
            else:
                result = library.lookup(parse_reference(args.reference, context=args.context), excerpt=args.excerpt)
                if args.spoken_input:
                    result["speechInput"] = prepare_spoken_input(result["text"])
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (CuvError, OSError, KeyError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
