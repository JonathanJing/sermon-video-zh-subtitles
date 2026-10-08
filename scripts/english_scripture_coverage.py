#!/usr/bin/env python3
"""Pinned public-domain English edition for quotation-boundary judgments only.

The machine scripture adjudicator must not admit a whole pinned verse when the
speaker quoted a fragment (decision of 2026-10-08: a fragment is translated as
the speaker's own words). Telling a fragment from a whole-verse reading needs an
English text to compare the spoken words with. This module pins the World
English Bible (public domain) from a hash-verified mirror of the eBible USFX
file and measures, per reference, how much of the verse's content words the
speaker said and how long the spoken stretch is relative to the verse.

The measure is a surface heuristic across translations (the speaker reads a
different edition), so it only decides *whether* the pinned target-language
verse may be admitted; it never supplies display text. Both numbers and the
thresholds are recorded in the adjudication basis so a human receipt can
override a wrong call.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path
import re
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import cuv_scripture  # noqa: E402
from scripts.build_scripture_index import BOOKS  # noqa: E402

EDITION_ID = 'eng-web'
EDITION_NAME = 'World English Bible (WEB)'
LICENSE = 'Public Domain'
UPSTREAM_DETAILS_URL = 'https://ebible.org/find/details.php?id=eng-web'
SOURCE_REPOSITORY = 'https://github.com/seven1m/open-bibles'
SOURCE_COMMIT = 'f257a3559025c3f873b48a75019f53a9354ed7de'
SOURCE_FILE = 'eng-web.usfx.xml'
SOURCE_URL = f'https://raw.githubusercontent.com/seven1m/open-bibles/{SOURCE_COMMIT}/{SOURCE_FILE}'
SOURCE_FILE_SHA256 = '5ffa2626f170a109a4a96afc90775c06f0821cb4ba81ed34e63663e085708d68'
# Canonical hash of the built library; refreshed only by a reviewed rebuild.
LIBRARY_CONTENT_SHA256 = 'c4f0f1aa5e8e462012441f5ded183d06c5ae8ae2cb397bdae40c9a5548bc03b5'
DATA_PATH = ROOT / 'data/scripture/eng-web.coverage.json'
PROVENANCE_PATH = ROOT / 'data/scripture/eng-web.coverage.provenance.json'
PURPOSE = 'quotation_boundary_coverage_only'

# The USFX file uses standard USFM codes; the repository's libraries use the eBible VPL codes.
USFX_TO_LIBRARY = {'SNG': 'SOL', 'EZK': 'EZE', 'JOL': 'JOE', 'NAM': 'NAH', 'MRK': 'MAR', 'JHN': 'JOH',
                   'PHP': 'PHI', 'JAS': 'JAM', '1JN': '1JO', '2JN': '2JO', '3JN': '3JO'}

# A whole-verse reading in another translation still shares most content words
# with the pinned edition and is about as long; a fragment is clearly shorter, and
# a span half again as long as the verse carries more than the verse.
WHOLE_VERSE_COVERAGE_MIN = 0.4
WHOLE_VERSE_LENGTH_MIN = 0.7
WHOLE_VERSE_LENGTH_MAX = 1.5

# Negation words are never function words: a reading that drops or adds one says the
# opposite of the verse, so they count as content and their number must match the verse.
NEGATIONS = frozenset('not no never nor neither none nothing nobody nowhere without'.split())
_CONTRACTION = re.compile(r"\b(won|can|shan|ain)'t\b|n't\b")
_CONTRACTED = {"won't": 'will not', "can't": 'can not', "shan't": 'shall not', "ain't": 'am not'}

STOPWORDS = frozenset("""
a an the and or but of to in on at by for with from that this these those is are was were be been being am
i you he she it we they me him her us them my your his its our their mine yours who whom whose which what there
here then than so as if do does did have has had will shall would should can could may might must let up
down out into unto upon over under all any some each every both very also too just now yet because when where
while how why own same other such only about after before again further once off through during against between
above below until more most behold o yes
""".split())

_SUFFIXES = ('ing', 'ed', 'es', 's', 'ly')


class CoverageError(cuv_scripture.CuvError):
    """A missing, changed or unknown coverage edition or reference."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------- source parsing

_DROP = re.compile(r'<(f|x|vp)\b[^>]*>.*?</\1>', re.S)
_TAG = re.compile(r'<[^>]+>')
_BOOK = re.compile(r'<book id="([A-Z0-9]+)">(.*?)</book>', re.S)
_CHAPTER = re.compile(r'<c id="(\d+)"\s*/>')
_VERSE = re.compile(r'<v id="(\d+)[^"]*"\s*/>(.*?)<ve\s*/>', re.S)


def _plain(fragment: str) -> str:
    text = _TAG.sub(' ', _DROP.sub(' ', fragment))
    return re.sub(r'\s+', ' ', html.unescape(text)).strip()


def parse_usfx(raw: str) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Verse text of the 66 canonical books from eBible USFX, footnotes and references removed."""
    chapters: dict[str, dict[str, list[dict[str, Any]]]] = {}
    empty: list[str] = []
    for code, body in _BOOK.findall(raw):
        book = USFX_TO_LIBRARY.get(code, code)
        if book not in BOOKS:
            continue  # front matter, glossary, deuterocanon
        pieces = _CHAPTER.split(body)
        for chapter, content in zip(pieces[1::2], pieces[2::2]):
            rows = chapters.setdefault(book, {}).setdefault(chapter, [])
            seen = {row['verse'] for row in rows}
            for number, fragment in _VERSE.findall(content):
                verse = int(number)
                text = _plain(fragment)
                if verse in seen:
                    raise CoverageError(f'duplicate verse {book} {chapter}:{verse}')
                seen.add(verse)
                if not text:
                    # A verse this edition carries only as a footnote (e.g. LUK 17:36):
                    # absent from the index, so a reference to it fails closed.
                    empty.append(f'{book} {chapter}:{verse}')
                    continue
                rows.append({'verse': verse, 'text': text})
    if set(chapters) != set(BOOKS):
        raise CoverageError('source does not carry exactly the 66 canonical books')
    chapters['_emptyVerses'] = empty  # type: ignore[assignment]
    return chapters


def build(source: Path, out: Path = DATA_PATH, provenance_out: Path = PROVENANCE_PATH) -> dict[str, Any]:
    """Build the library from the hash-verified source file; refuse to overwrite a different library."""
    raw_bytes = Path(source).read_bytes()
    if sha256(raw_bytes) != SOURCE_FILE_SHA256:
        raise CoverageError('source file hash differs from the pinned mirror file; explicit source review required')
    chapters = parse_usfx(raw_bytes.decode('utf-8'))
    empty = chapters.pop('_emptyVerses')
    payload = {'schemaVersion': 1, 'purpose': PURPOSE,
               'edition': {'id': EDITION_ID, 'name': EDITION_NAME, 'license': LICENSE,
                           'upstreamDetailsUrl': UPSTREAM_DETAILS_URL, 'sourceRepository': SOURCE_REPOSITORY,
                           'sourceCommit': SOURCE_COMMIT, 'sourceUrl': SOURCE_URL,
                           'sourceFileSha256': SOURCE_FILE_SHA256},
               'books': [code for code in BOOKS if code in chapters],
               'chapters': chapters, 'footnoteOnlyVerses': empty,
               'verseCount': sum(len(rows) for book in chapters.values() for rows in book.values())}
    content_sha = cuv_scripture.canonical_hash(payload)
    encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')
    out = Path(out)
    if out.exists() and out.read_bytes() != encoded:
        raise CoverageError(f'Refusing to overwrite a different library: {out}')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(encoded)
    provenance = {'schemaVersion': 1, 'editionId': EDITION_ID, 'name': EDITION_NAME, 'license': LICENSE,
                  'purpose': PURPOSE, 'upstreamDetailsUrl': UPSTREAM_DETAILS_URL,
                  'sourceRepository': SOURCE_REPOSITORY, 'sourceCommit': SOURCE_COMMIT, 'sourceUrl': SOURCE_URL,
                  'sourceFile': SOURCE_FILE, 'sourceFileSha256': SOURCE_FILE_SHA256,
                  'libraryPath': str(out.relative_to(ROOT)) if out.is_relative_to(ROOT) else str(out),
                  'libraryFileSha256': sha256(encoded), 'libraryContentSha256': content_sha,
                  'bookCount': len(payload['books']), 'verseEntryCount': payload['verseCount'],
                  'normalization': 'Footnotes (<f>), cross references (<x>) and published verse numbers (<vp>) '
                                   'removed; every other tag dropped and its text kept; entities unescaped; '
                                   'whitespace collapsed to one space and trimmed. Canonical JSON hash uses UTF-8, '
                                   'ensure_ascii=false, sort_keys=true and compact separators.',
                  'notice': 'Used only to judge whether a spoken quotation covers a whole verse. Never displayed, '
                            'dubbed or translated; the mirror file is not publisher-verified.'}
    Path(provenance_out).write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return {'status': 'built', 'libraryContentSha256': content_sha, 'verseCount': payload['verseCount'],
            'path': str(out)}


# ---------------------------------------------------------------- library

class CoverageEdition:
    """The pinned English verses, verified against the content hash on load."""

    def __init__(self, data: dict[str, Any], *, expected_content_sha256: str | None = LIBRARY_CONTENT_SHA256):
        if expected_content_sha256 is not None and cuv_scripture.canonical_hash(data) != expected_content_sha256:
            raise CoverageError('English coverage edition content hash mismatch; never substitute unverified scripture')
        if data.get('schemaVersion') != 1 or data.get('purpose') != PURPOSE or not isinstance(data.get('chapters'), dict):
            raise CoverageError('English coverage edition has an unexpected shape')
        self.edition_id = str(data.get('edition', {}).get('id') or EDITION_ID)
        self._chapters = data['chapters']

    @classmethod
    def from_path(cls, path: str | Path | None = None) -> 'CoverageEdition':
        try:
            data = json.loads(Path(DATA_PATH if path is None else path).read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise CoverageError('English coverage edition is unavailable') from exc
        return cls(data)

    def lookup(self, ref: cuv_scripture.Reference | str) -> dict[str, Any]:
        reference = cuv_scripture.parse_reference(ref) if isinstance(ref, str) else ref
        available = {row['verse']: row['text']
                     for row in self._chapters.get(reference.book, {}).get(str(reference.chapter), [])}
        missing = [v for v in range(reference.start_verse, reference.end_verse + 1) if v not in available]
        if not available or missing:
            raise CoverageError(f'Missing verse(s) in pinned {self.edition_id}: {reference.canonical_ref}')
        text = ' '.join(available[v] for v in range(reference.start_verse, reference.end_verse + 1))
        return {'canonicalRef': reference.canonical_ref, 'editionId': self.edition_id, 'text': text,
                'textSha256': sha256(text.encode('utf-8'))}


# ---------------------------------------------------------------- measure

def _stem(word: str) -> str:
    word = word.removesuffix("'s")
    if len(word) > 4 and word.endswith('ies'):
        return word[:-3] + 'y'
    for suffix in _SUFFIXES:
        if len(word) - len(suffix) >= 3 and word.endswith(suffix):
            stem = word[:-len(suffix)]
            if suffix in ('ing', 'ed') and len(stem) > 3 and stem[-1] == stem[-2] and stem[-1] not in 'lsz':
                stem = stem[:-1]  # sitting -> sit, stopped -> stop
            return stem
    return word


def _expand_negations(text: str) -> str:
    """"didn't" reads as "did not" so a contracted negation counts like a spoken one."""
    return _CONTRACTION.sub(lambda m: _CONTRACTED.get(m.group(0), ' not'), text)


def content_tokens(text: str) -> list[str]:
    """Lower-cased, lightly stemmed content words; function words and punctuation dropped."""
    words = re.findall(r"[a-z0-9]+(?:'[a-z]+)?", _expand_negations(text.lower().replace('’', "'")))
    return [_stem(word) for word in words if word not in STOPWORDS and len(word) > 1]


def negation_count(tokens: list[str]) -> int:
    return sum(token in NEGATIONS for token in tokens)


def _same(a: str, b: str) -> bool:
    if a == b:
        return True
    return (len(a) >= 4 and len(b) >= 4 and abs(len(a) - len(b)) <= 2
            and (a.startswith(b) or b.startswith(a)))


def coverage(edition: CoverageEdition, ref: cuv_scripture.Reference | str, spoken: str) -> dict[str, Any]:
    """How much of the verse the speaker said, and the boundary verdict with its evidence."""
    found = edition.lookup(ref)
    verse_tokens, spoken_tokens = content_tokens(found['text']), content_tokens(spoken)
    unique_verse = sorted(set(verse_tokens))
    if not unique_verse:
        raise CoverageError(f'pinned verse has no content words: {found["canonicalRef"]}')
    covered = [token for token in unique_verse if any(_same(token, heard) for heard in spoken_tokens)]
    verse_coverage = round(len(covered) / len(unique_verse), 4)
    length_ratio = round(len(spoken_tokens) / len(verse_tokens), 4)
    # A whole verse with a negation missing, added or doubled says the opposite; it is never pinned.
    negations = {'verse': negation_count(verse_tokens), 'spoken': negation_count(spoken_tokens)}
    negation_mismatch = negations['verse'] != negations['spoken']
    whole_by_measure = (verse_coverage >= WHOLE_VERSE_COVERAGE_MIN
                        and WHOLE_VERSE_LENGTH_MIN <= length_ratio <= WHOLE_VERSE_LENGTH_MAX)
    whole = whole_by_measure and not negation_mismatch
    return {'editionId': found['editionId'], 'canonicalRef': found['canonicalRef'],
            'verseTextSha256': found['textSha256'], 'verseContentWords': len(unique_verse),
            'coveredContentWords': len(covered), 'spokenContentWords': len(spoken_tokens),
            'verseCoverage': verse_coverage, 'lengthRatio': length_ratio,
            'negations': negations, 'negationMismatch': negation_mismatch,
            'wholeByMeasure': whole_by_measure, 'wholeVerse': whole,
            'thresholds': {'verseCoverageMin': WHOLE_VERSE_COVERAGE_MIN, 'lengthRatioMin': WHOLE_VERSE_LENGTH_MIN,
                           'lengthRatioMax': WHOLE_VERSE_LENGTH_MAX}}


# ---------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    build_cmd = commands.add_parser('build', help='Build the library from the hash-verified mirror file')
    build_cmd.add_argument('--source', type=Path, required=True, help=f'{SOURCE_FILE} downloaded from {SOURCE_URL}')
    build_cmd.add_argument('--out', type=Path, default=DATA_PATH)
    build_cmd.add_argument('--provenance-out', type=Path, default=PROVENANCE_PATH)
    check = commands.add_parser('check', help='Measure a spoken quotation against a reference')
    check.add_argument('reference')
    check.add_argument('spoken')
    commands.add_parser('verify', help='Verify the pinned library loads with the pinned content hash')
    args = parser.parse_args(argv)
    try:
        if args.command == 'build':
            result = build(args.source, args.out, args.provenance_out)
        elif args.command == 'check':
            result = coverage(CoverageEdition.from_path(), args.reference, args.spoken)
        else:
            CoverageEdition.from_path()
            result = {'status': 'verified', 'editionId': EDITION_ID, 'libraryContentSha256': LIBRARY_CONTENT_SHA256}
    except cuv_scripture.CuvError as exc:
        raise SystemExit(f'refused: {exc}')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
