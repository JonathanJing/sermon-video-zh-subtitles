from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BIBLE_PATH = REPO_ROOT / "data" / "scripture" / "cmn-cu89s.json"


class ScriptureNotFoundError(KeyError):
    pass


@dataclass(frozen=True)
class ScriptureReference:
    book_code: str
    chapter: int


class ScriptureService:
    def __init__(self, bible_path: Path = DEFAULT_BIBLE_PATH):
        self.bible_path = bible_path
        self._data: dict[str, Any] | None = None
        self._book_aliases: dict[str, str] | None = None

    def metadata(self) -> dict[str, Any]:
        data = self._load()
        return {
            "schemaVersion": data.get("schemaVersion", 1),
            "translation": data["translation"],
            "bookCount": len(data.get("books", [])),
            "verseCount": data.get("verseCount"),
        }

    def books(self) -> dict[str, Any]:
        data = self._load()
        return {
            "schemaVersion": data.get("schemaVersion", 1),
            "translation": data["translation"],
            "books": data.get("books", []),
        }

    def chapter(self, book: str, chapter: str | int) -> dict[str, Any]:
        data = self._load()
        ref = self._parse_reference(book, chapter)
        chapters = data.get("chapters", {}).get(ref.book_code, {})
        verses = chapters.get(str(ref.chapter))
        if not verses:
            raise ScriptureNotFoundError(f"{book} {chapter}")
        book_info = self._book_info(ref.book_code)
        return {
            "schemaVersion": data.get("schemaVersion", 1),
            "translation": data["translation"],
            "source": "cloud-run-local-bible-index",
            "reference": {
                "canonicalRef": f"{book_info['nameEn']} {ref.chapter}",
                "book": book_info["nameEn"],
                "bookZh": book_info["nameZh"],
                "bookCode": ref.book_code,
                "chapter": ref.chapter,
                "title": f"{book_info['nameZh']} {ref.chapter}",
            },
            "verses": [
                {"verse": f"{ref.chapter}:{verse['verse']}", "text": verse["text"]}
                for verse in verses
            ],
        }

    def _load(self) -> dict[str, Any]:
        if self._data is None:
            self._data = json.loads(self.bible_path.read_text(encoding="utf-8"))
        return self._data

    def _book_info(self, book_code: str) -> dict[str, Any]:
        for book in self._load().get("books", []):
            if book.get("code") == book_code:
                return book
        raise ScriptureNotFoundError(book_code)

    def _parse_reference(self, book: str, chapter: str | int) -> ScriptureReference:
        book_code = self._resolve_book(book)
        try:
            parsed_chapter = int(chapter)
        except (TypeError, ValueError) as exc:
            raise ScriptureNotFoundError(f"{book} {chapter}") from exc
        if parsed_chapter < 1:
            raise ScriptureNotFoundError(f"{book} {chapter}")
        return ScriptureReference(book_code=book_code, chapter=parsed_chapter)

    def _resolve_book(self, book: str) -> str:
        aliases = self._aliases()
        key = normalize_book_key(book)
        if key in aliases:
            return aliases[key]
        raise ScriptureNotFoundError(book)

    def _aliases(self) -> dict[str, str]:
        if self._book_aliases is not None:
            return self._book_aliases
        aliases = {}
        for book in self._load().get("books", []):
            code = str(book["code"])
            for candidate in [code, book.get("nameEn", ""), book.get("nameZh", "")]:
                if candidate:
                    aliases[normalize_book_key(str(candidate))] = code
        aliases.update(
            {
                "num": "NUM",
                "numbers": "NUM",
                "民数记": "NUM",
                "minshuj": "NUM",
            }
        )
        self._book_aliases = aliases
        return aliases


def normalize_book_key(value: str) -> str:
    return re.sub(r"[\s_\-.]+", "", value.strip().lower())
