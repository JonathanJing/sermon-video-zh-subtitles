"""Hash-pinned verse libraries for ko and es editions, read-only.

The text itself is not stored in Git (it is copyrighted and large). The file
path, SHA-256 and provenance of each edition are recorded here, and every load
re-verifies the bytes. A verse index is built from the verified file; lookups
return exact verse text in the same shape as the CUV library.

Verification status is explicit. These editions come from third-party
repositories; the status stays third-party until the publisher comparison is
recorded. An adjudication receipt can cite an edition only when its status is
'verified_pinned_source'.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts import cuv_scripture

ROOT = Path(__file__).resolve().parents[1]
DOWNLOAD_DIR = ROOT / 'artifacts' / 'scripture-downloads'
VERIFIED = 'verified_pinned_source'
PENDING = 'third_party_claim_pending_publisher_comparison'

# Standard USFM book order. Both source files were checked to follow it exactly.
USFM_ORDER = ['GEN', 'EXO', 'LEV', 'NUM', 'DEU', 'JOS', 'JDG', 'RUT', '1SA', '2SA', '1KI', '2KI', '1CH', '2CH',
              'EZR', 'NEH', 'EST', 'JOB', 'PSA', 'PRO', 'ECC', 'SNG', 'ISA', 'JER', 'LAM', 'EZK', 'DAN', 'HOS',
              'JOL', 'AMO', 'OBA', 'JON', 'MIC', 'NAM', 'HAB', 'ZEP', 'HAG', 'ZEC', 'MAL', 'MAT', 'MRK', 'LUK',
              'JHN', 'ACT', 'ROM', '1CO', '2CO', 'GAL', 'EPH', 'PHP', 'COL', '1TH', '2TH', '1TI', '2TI', 'TIT',
              'PHM', 'HEB', 'JAS', '1PE', '2PE', '1JN', '2JN', '3JN', 'JUD', 'REV']
KO_BOOK_LABELS = ['창', '출', '레', '민', '신', '수', '삿', '룻', '삼상', '삼하', '왕상', '왕하', '대상', '대하', '스', '느',
                  '에', '욥', '시', '잠', '전', '아', '사', '렘', '애', '겔', '단', '호', '욜', '암', '옵', '욘', '미', '나',
                  '합', '습', '학', '슥', '말', '마', '막', '눅', '요', '행', '롬', '고전', '고후', '갈', '엡', '빌', '골',
                  '살전', '살후', '딤전', '딤후', '딛', '몬', '히', '약', '벧전', '벧후', '요일', '요이', '요삼', '유', '계']

EDITIONS: dict[str, dict[str, Any]] = {
    'NKRV-1998': {
        'locale': 'ko', 'file': 'NKRV-1998.json', 'format': 'flat_records',
        'sha256': 'fac2c2b42214faaf970c848d02c5ef87f5bc7fc157e93ae13713f97673f53c2c',
        'sourceRepository': 'https://github.com/stranger828/bibleAPI',
        'sourceCommit': '883e8f89b65710dd00a50f675b256cb2709cc90f',
        'verification': PENDING,
        'checks': {'books': 66, 'chapters': 1189, 'verses': 31077},
    },
    'RVR60-1960': {
        'locale': 'es', 'file': 'RVR60-1960.unique-chapters.json', 'format': 'chapter_items',
        'sha256': '31acde8a75cd44f33af35722df2c88c00be67c9f2f5b11246d49da9fe0ce0913',
        'sourceFile': 'RVR60-1960.json',
        'sourceSha256': '61e2f60ada8be94868e3db0b89102c8ad8b26dfef49e3fb03bc682f8b37ea778',
        'sourceRepository': 'https://github.com/mrk214/bible-data-es-spa',
        'sourceCommit': '998cf834afa3320fa1f24431c0802551f135351d',
        'verification': PENDING,
        'duplicateChaptersRemoved': 5,
        'checks': {'books': 66, 'chapters': 1189},
    },
}


class EditionError(cuv_scripture.CuvError):
    """A missing, changed, unverified or unknown edition or reference."""


@dataclass(frozen=True)
class Edition:
    edition_id: str
    verification: str
    verses: dict[tuple[str, int, int], str]
    ambiguous: frozenset = frozenset()

    def lookup(self, ref: cuv_scripture.Reference | str, *, excerpt: str | None = None) -> dict[str, Any]:
        reference = cuv_scripture.parse_reference(ref) if isinstance(ref, str) else ref
        texts = []
        for verse in range(reference.start_verse, reference.end_verse + 1):
            key = (reference.book, reference.chapter, verse)
            if key in self.ambiguous:
                raise EditionError(f'Verse is ambiguous in pinned {self.edition_id}: {reference.canonical_ref}')
            if key not in self.verses:
                raise EditionError(f'Missing verse in pinned {self.edition_id}: {reference.canonical_ref}')
            texts.append(self.verses[key])
        full_text = ' '.join(texts)
        text, start, end = full_text, 0, len(full_text)
        if excerpt is not None:
            if not excerpt or full_text.count(excerpt) != 1:
                raise EditionError('Excerpt must be one exact, non-empty occurrence in the pinned source text')
            start = full_text.index(excerpt)
            end = start + len(excerpt)
            text = excerpt
        return {'canonicalRef': reference.canonical_ref, 'editionId': self.edition_id, 'text': text,
                'textSha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
                'selection': {'kind': 'exact_excerpt' if excerpt is not None else 'whole_verses',
                              'startChar': start, 'endChar': end}}

    def verify_text(self, ref: cuv_scripture.Reference | str, text: str, *, excerpt: bool = False) -> dict[str, Any]:
        result = self.lookup(ref, excerpt=text if excerpt else None)
        if result['text'] != text:
            raise EditionError(f'Text does not exactly match the pinned {self.edition_id} source')
        return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _index_flat(records: list[dict[str, Any]]) -> dict[tuple[str, int, int], str]:
    index: dict[tuple[str, int, int], str] = {}
    for row in records:
        label = row['book']
        if label not in KO_BOOK_LABELS:
            raise EditionError('unknown book label in pinned NKRV source')
        book = USFM_ORDER[KO_BOOK_LABELS.index(label)]
        key = (book, int(row['chapter']), int(row['verse']))
        if key in index:
            raise EditionError('duplicate verse in pinned NKRV source')
        if not str(row['content']).strip():
            raise EditionError('empty verse in pinned NKRV source')
        index[key] = str(row['content']).strip()
    return index


def _index_chapters(data: dict[str, Any]) -> tuple[dict[tuple[str, int, int], str], frozenset]:
    """Return the verse index and the verses the source numbers ambiguously.

    A verse number that appears in two items cannot be joined or chosen without a
    publisher comparison, so those keys are excluded from exact lookup.
    """
    books = [book['usfm'] for book in data['books']]
    if books != USFM_ORDER:
        raise EditionError('pinned RVR60 book order differs from USFM order')
    parts: dict[tuple[str, int, int], list[str]] = {}
    for book in data['books']:
        for chapter in book['chapters']:
            chapter_number = int(chapter['usfm'].split('.')[1])
            for item in chapter['items']:
                if item.get('type') != 'verse':
                    continue
                text = ' '.join(line.strip() for line in item['lines'] if line.strip())
                for verse in item['verse_numbers']:
                    parts.setdefault((book['usfm'], chapter_number, int(verse)), []).append(text)
    index = {key: texts[0] for key, texts in parts.items() if len(texts) == 1}
    ambiguous = frozenset(key for key, texts in parts.items() if len(texts) > 1)
    return index, ambiguous


def load(edition_id: str, *, directory: Path = DOWNLOAD_DIR) -> Edition:
    """Verify the pinned file's bytes, then build the verse index."""
    if edition_id not in EDITIONS:
        raise EditionError('unknown pinned edition')
    spec = EDITIONS[edition_id]
    path = Path(directory) / spec['file']
    if not path.is_file():
        raise EditionError(f'pinned {edition_id} file is not available')
    if _sha256(path) != spec['sha256']:
        raise EditionError(f'pinned {edition_id} file hash differs from the registry')
    data = json.loads(path.read_text(encoding='utf-8'))
    if spec['format'] == 'flat_records':
        return Edition(edition_id=edition_id, verification=spec['verification'], verses=_index_flat(data))
    index, ambiguous = _index_chapters(data)
    return Edition(edition_id=edition_id, verification=spec['verification'], verses=index, ambiguous=ambiguous)



class LazyEdition:
    """A registered edition whose file is read on first use, not on construction.

    Adjudication and the receipt gate need the edition's verification status
    for every unit, but its verses only when a whole-verse quotation is emitted
    or verified; a locale whose file is absent from the checkout still settles
    paraphrase-only units and receipts."""

    def __init__(self, edition_id: str, *, directory: Path = DOWNLOAD_DIR) -> None:
        if edition_id not in EDITIONS:
            raise EditionError('unknown pinned edition')
        self.edition_id = edition_id
        self.verification = EDITIONS[edition_id]['verification']
        self._directory = directory
        self._edition: Edition | None = None

    def load(self) -> Edition:
        if self._edition is None:
            self._edition = load(self.edition_id, directory=self._directory)
        return self._edition

    def lookup(self, ref: cuv_scripture.Reference | str, *, excerpt: str | None = None) -> dict[str, Any]:
        return self.load().lookup(ref, excerpt=excerpt)

    def verify_text(self, ref: cuv_scripture.Reference | str, text: str, *, excerpt: bool = False) -> dict[str, Any]:
        return self.load().verify_text(ref, text, excerpt=excerpt)