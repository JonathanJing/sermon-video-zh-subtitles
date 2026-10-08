"""Machine scripture adjudication: a deterministic receipt from explicit references.

Decision 2026-10-08 (Jony): scripture adjudication no longer waits for a human.
This module writes the receipt a human used to write, from what the English
source carries on its surface:

- an explicit book and chapter mention ("Revelation chapter 4", "John 3:16")
  sets the reference context for the units that follow;
- a verse mention ("Verse 2 and 3", "verses 7 through 9") together with a
  reading signal (a speech verb such as "says" or "reads", or quotation marks)
  opens a quotation at that unit;
- the pinned edition supplies the exact sentence for each verse.

It never guesses. A flagged unit whose reference cannot be resolved, or whose
verses are missing from the pinned edition, is recorded as speaker_paraphrase
with no edition and no sentence, which only tells the translator to render the
speaker's own words. The receipt keeps the v1 shape with
decidedByRole='machine_adjudicator'; a sidecar basis file records the evidence
behind every decision so a person can audit or overrule it with a human receipt.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import cuv_scripture  # noqa: E402
from scripts import english_scripture_coverage as coverage_module  # noqa: E402
from scripts import scripture_adjudication as adjudication  # noqa: E402
from scripts import scripture_candidate_queue as queue_module  # noqa: E402
from scripts import scripture_editions  # noqa: E402
from scripts import target_language_policy as policies  # noqa: E402

VERSION = '2026-10-08-v2'
ROLE = 'machine_adjudicator'
BASIS_SCHEMA = 'sermon-scripture-machine-adjudication-basis-v1'
# A book mention stays in force for this many following units; sermons move on.
CONTEXT_WINDOW_UNITS = 12
# A reading signal may sit in the unit before the verse mention ("John says, verse 2 ...").
READING_LOOKBACK_UNITS = 1

_BOOKS = queue_module.BOOKS
_NUMBER_WORDS = '|'.join(sorted(cuv_scripture._EN_NUMBERS, key=len, reverse=True))
_NUM = rf'(?:\d+|{_NUMBER_WORDS})'
# "2 and 3" joins adjacent verses; "2 and 5" names two verses and is never a range.
_RANGE = rf'(?P<v1>{_NUM})(?:\s*(?P<join>-|–|to|through|and)\s*(?P<v2>{_NUM}))?'
BOOK_MENTION = re.compile(
    rf'\b(?P<book>(?:[123]\s+)?(?:{_BOOKS}))\s+(?:chapter\s+)?(?P<chapter>{_NUM})\b'
    rf'(?P<more_chapters>\s+and\s+{_NUM}\b)?(?:\s*:\s*{_RANGE})?', re.I)
# "Now turn to Romans" moves the reading to another book without naming a chapter.
BOOK_TRANSITION = re.compile(
    rf'\b(?:turn(?:ing)?|open(?:ing)?|go(?:ing)?|com(?:e|ing)|back|look(?:ing)?)\s+(?:to|at|in)\s+'
    rf'(?:the\s+book\s+of\s+)?(?P<book>(?:[123]\s+)?(?:{_BOOKS}))\b', re.I)
CHAPTER_MENTION = re.compile(rf'\bchapter\s+(?P<chapter>{_NUM})\b', re.I)
VERSE_MENTION = re.compile(rf'\bverses?\s+{_RANGE}', re.I)
READING_SIGNALS = {'speech_verb', 'quotation_marks'}
# A reading signal borrowed from the unit before must come from a unit about scripture.
SCRIPTURE_SIGNALS = {'book_reference', 'chapter_verse', 'scripture_word'}
# Decision of 2026-10-08: a fragment is translated as the speaker's own words. The pinned
# target-language verse is admitted only when the spoken words cover the whole verse,
# measured against the pinned public-domain English edition (english_scripture_coverage).
QUOTE_BOUNDARY = 'whole_verse_by_english_coverage'
FRAGMENT_BOUNDARY = 'fragment_translated_as_spoken'
_SPEECH_VERB = dict(queue_module.SIGNALS)['speech_verb']


class MachineAdjudicationError(ValueError):
    """A reason code, never free text."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise MachineAdjudicationError(code)


def implementation_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _number(value: str) -> int:
    return int(value) if value.isdigit() else cuv_scripture._EN_NUMBERS[value.casefold()]


def _edition(target_locale: str, library: Any = None) -> Any:
    _require(target_locale in adjudication.PINNED_EDITIONS, 'no_pinned_edition_for_locale')
    edition_id = adjudication.PINNED_EDITIONS[target_locale]
    if edition_id == 'CUV':
        return edition_id, (library or cuv_scripture.CuvLibrary.from_path())
    try:
        return edition_id, scripture_editions.load(edition_id)
    except scripture_editions.EditionError as exc:
        raise MachineAdjudicationError('edition_unavailable') from exc


def _signals(english: str) -> set[str]:
    return {kind for kind, pattern in queue_module.SIGNALS if pattern.search(english)}


_DEFAULT_COVERAGE: list[Any] = []


def _coverage_edition(edition: Any = None) -> Any:
    """The pinned English coverage edition, loaded and hash-verified once per process."""
    if edition is not None:
        return edition
    if not _DEFAULT_COVERAGE:
        try:
            _DEFAULT_COVERAGE.append(coverage_module.CoverageEdition.from_path())
        except coverage_module.CoverageError as exc:
            raise MachineAdjudicationError('english_edition_unavailable') from exc
    return _DEFAULT_COVERAGE[0]


def _spoken_text(english: list[str]) -> str:
    """The units' words without the reference and reading phrases that introduce the quotation."""
    pieces = []
    for text in english:
        for pattern in (BOOK_MENTION, BOOK_TRANSITION, CHAPTER_MENTION, VERSE_MENTION, _SPEECH_VERB):
            text = pattern.sub(' ', text)
        pieces.append(text)
    return re.sub(r'\s+', ' ', ' '.join(pieces)).strip()


def _book(name: str) -> str | None:
    try:
        return cuv_scripture.normalize_book(name)
    except cuv_scripture.CuvError:
        return None


def _verse_range(match: re.Match) -> tuple[int, int] | None:
    """The verses a mention names, or None when "and" joins verses that are not adjacent."""
    v1 = _number(match['v1'])
    if not match['v2']:
        return v1, v1
    v2 = _number(match['v2'])
    if match['join'].casefold() == 'and' and v2 != v1 + 1:
        return None
    return v1, v2


def _scan(units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per unit: the reference context in force and any verse mention, with its evidence."""
    rows: list[dict[str, Any]] = []
    book: str | None = None
    chapter: int | None = None
    since_book = 0
    for unit in units:
        english = unit['english']
        evidence: list[str] = []
        since_book += 1
        if since_book > CONTEXT_WINDOW_UNITS:
            book = chapter = None
        mention = BOOK_MENTION.search(english)
        transition = None if mention else BOOK_TRANSITION.search(english)
        verse_range: tuple[int, int] | None = None
        verses_named = False
        if mention:
            book = _book(mention['book'])
            since_book = 0
            if mention['more_chapters']:
                chapter = None  # "Revelation 4 and 5": two chapters, no single context.
                evidence.append(f'book mention with several chapters: {mention.group(0)!r}')
            else:
                chapter = _number(mention['chapter'])
                evidence.append(f'book and chapter mention: {mention.group(0)!r}')
            if mention['v1']:
                verses_named = True
                verse_range = _verse_range(mention)
        elif transition:
            book, chapter, since_book = _book(transition['book']), None, 0
            evidence.append(f'book transition without a chapter: {transition.group(0)!r}')
        else:
            chapter_mention = CHAPTER_MENTION.search(english)
            if chapter_mention and book:
                chapter = _number(chapter_mention['chapter'])
                evidence.append(f'chapter mention: {chapter_mention.group(0)!r}')
        verse_mention = VERSE_MENTION.search(english)
        if verse_mention and not verses_named:
            verses_named = True
            verse_range = _verse_range(verse_mention)
            evidence.append(f'verse mention: {verse_mention.group(0)!r}')
        if verses_named and verse_range is None:
            evidence.append('verses joined by "and" are not adjacent: not a range')
        signals = _signals(english)
        rows.append({'sourceUnitId': unit['sourceUnitId'], 'english': english, 'book': book, 'chapter': chapter,
                     'verseRange': verse_range, 'reading': bool(signals & READING_SIGNALS),
                     'signals': sorted(signals), 'evidence': evidence})
    return rows


def _reference(row: dict[str, Any]) -> cuv_scripture.Reference | None:
    if row['book'] and row['chapter'] and row['verseRange']:
        v1, v2 = row['verseRange']
        if v2 >= v1:
            return cuv_scripture.Reference(row['book'], row['chapter'], v1, v2)
    return None


def _reading_near(rows: list[dict[str, Any]], index: int) -> bool:
    """A reading signal in the unit, or in the unit before when that unit is itself about scripture."""
    if rows[index]['reading']:
        return True
    return any(rows[i]['reading'] and (rows[i]['evidence'] or set(rows[i]['signals']) & SCRIPTURE_SIGNALS)
               for i in range(max(0, index - READING_LOOKBACK_UNITS), index))


def discover_flagged_units(rows: list[dict[str, Any]]) -> list[str]:
    """Units that open a quotation: a resolvable reference with a reading signal.

    Only the opening unit is claimed. Where the reading runs on into later
    units, the surface text gives no boundary evidence (the opening unit may
    already hold the whole range, and a following unit may be commentary or
    prayer), so the whole range stays on the opening unit and the continuation
    units are supplied explicitly when known."""
    return [row['sourceUnitId'] for i, row in enumerate(rows)
            if _reference(row) is not None and _reading_near(rows, i)]


def _runs(rows: list[dict[str, Any]], flagged: list[str]) -> list[list[int]]:
    position = {row['sourceUnitId']: i for i, row in enumerate(rows)}
    _require(all(unit in position for unit in flagged), 'flagged_unit_unknown')
    indexes = sorted(position[unit] for unit in flagged)
    runs: list[list[int]] = []
    for i in indexes:
        # A unit naming its own verses opens a new quotation even right after another.
        if runs and runs[-1][-1] == i - 1 and rows[i]['verseRange'] is None:
            runs[-1].append(i)
        else:
            runs.append([i])
    return runs


def _resolve_run(rows: list[dict[str, Any]], run: list[int]) -> tuple[cuv_scripture.Reference | None, int | None]:
    """The reference that opens this run: inside it, or in the unit just before it."""
    for i in run:
        reference = _reference(rows[i])
        if reference is not None:
            return reference, i
    before = run[0] - 1
    if before >= 0 and rows[before]['verseRange'] is not None:
        reference = _reference(rows[before])
        if reference is not None:
            return reference, before
    return None, None


def _paraphrase(candidate_id: str, units: list[str], reason: str) -> tuple[dict[str, Any], dict[str, Any]]:
    candidate = {'candidateId': candidate_id, 'sourceUnitIds': units, 'classification': 'speaker_paraphrase',
                 'reference': None, 'editionId': None, 'exactSentence': None}
    return candidate, {'candidateId': candidate_id, 'sourceUnitIds': units, 'decision': 'speaker_paraphrase',
                       'reason': reason}


def adjudicate(source: dict[str, Any], anchor: dict[str, Any], plan: list[dict[str, Any]], *, target_locale: str,
               flagged_units: list[str] | None = None, library: Any = None, coverage_edition: Any = None,
               now: datetime | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (receipt, basis). The receipt has the v1 shape with the machine role."""
    edition_id, edition = _edition(target_locale, library)
    english_edition = _coverage_edition(coverage_edition)
    units = anchor['sourceUnits']
    rows = _scan(units)
    discovered = discover_flagged_units(rows)
    flagged = list(flagged_units) if flagged_units is not None else discovered
    _require(len(flagged) == len(set(flagged)), 'flagged_unit_repeated')
    group_of = {unit: group['translationGroupId'] for group in plan for unit in group['sourceUnitIds']}
    candidates: list[dict[str, Any]] = []
    basis_rows: list[dict[str, Any]] = []
    for run in _runs(rows, flagged):
        run_units = [rows[i]['sourceUnitId'] for i in run]
        reference, at = _resolve_run(rows, run)
        verses = [] if reference is None else list(range(reference.start_verse, reference.end_verse + 1))
        shared = len(run) > 1 and len(run) != len(verses)
        if reference is None or (shared and len({group_of.get(unit) for unit in run_units}) != 1):
            reason = ('no book, chapter and verse reference resolves for this unit' if reference is None
                      else f'{reference.canonical_ref} is read across several translation groups; the pinned '
                           'wording cannot be bound to one group, so the speaker\'s words are translated')
            for unit in run_units:
                candidate, why = _paraphrase(f'm{len(candidates) + 1:03d}', [unit], reason)
                candidates.append(candidate)
                basis_rows.append(why | {'english': rows[run[run_units.index(unit)]]['english']})
            continue
        if len(run) == len(verses):
            pairs = [([rows[i]['sourceUnitId']], cuv_scripture.Reference(reference.book, reference.chapter, v))
                     for i, v in zip(run, verses)]
            layout = 'one verse per unit'
        else:
            pairs = [(run_units, reference)]
            layout = ('one unit carries the whole range' if len(run) == 1
                      else 'several units in one translation group share the whole range')
        for units_here, ref in pairs:
            candidate_id = f'm{len(candidates) + 1:03d}'
            english_here = [rows[i]['english'] for i in run if rows[i]['sourceUnitId'] in units_here]
            try:
                found = edition.lookup(ref)
            except (cuv_scripture.CuvError, scripture_editions.EditionError) as exc:
                candidate, why = _paraphrase(candidate_id, units_here,
                                             f'edition lookup failed for {ref.canonical_ref}: {exc}')
                candidates.append(candidate)
                basis_rows.append(why | {'reference': ref.canonical_ref, 'english': english_here})
                continue
            # The pinned verse is admitted only when the speaker's words cover the whole verse.
            try:
                measure = coverage_module.coverage(english_edition, ref, _spoken_text(english_here))
            except coverage_module.CoverageError as exc:
                candidate, why = _paraphrase(candidate_id, units_here,
                                             f'no English text bounds the quotation of {ref.canonical_ref}: {exc}')
                candidates.append(candidate)
                basis_rows.append(why | {'reference': ref.canonical_ref, 'english': english_here})
                continue
            if not measure['wholeVerse']:
                candidate, why = _paraphrase(
                    candidate_id, units_here,
                    f"fragment of {ref.canonical_ref}: the speaker said {measure['coveredContentWords']} of "
                    f"{measure['verseContentWords']} content words (coverage {measure['verseCoverage']}, length "
                    f"{measure['lengthRatio']}); translated as the speaker's own words (decision 2026-10-08)")
                candidates.append(candidate)
                basis_rows.append(why | {'reference': ref.canonical_ref, 'quoteBoundary': FRAGMENT_BOUNDARY,
                                         'coverage': measure, 'english': english_here})
                continue
            candidates.append({'candidateId': candidate_id, 'sourceUnitIds': units_here,
                               'classification': 'direct_quote', 'reference': ref.canonical_ref,
                               'editionId': edition_id, 'exactSentence': found['text']})
            basis_rows.append({'candidateId': candidate_id, 'sourceUnitIds': units_here, 'decision': 'direct_quote',
                               'reference': ref.canonical_ref, 'textSha256': found['textSha256'], 'layout': layout,
                               'quoteBoundary': QUOTE_BOUNDARY, 'coverage': measure,
                               'openedAt': rows[at]['sourceUnitId'], 'evidence': rows[at]['evidence'],
                               'readingSignals': sorted({s for i in range(max(0, at - READING_LOOKBACK_UNITS), at + 1)
                                                         for s in rows[i]['signals'] if s in READING_SIGNALS}),
                               'english': english_here})
    _require(bool(candidates), 'no_flagged_units')
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    sha = implementation_sha256()
    receipt = {'schemaVersion': adjudication.SCHEMA, 'targetLocale': target_locale,
               'bindings': {'source.json': policies.canonical_sha256(source),
                            'anchor.json': policies.canonical_sha256(anchor),
                            'group-plan.json': policies.canonical_sha256(plan)},
               'decision': 'approved', 'decidedBy': f'scripture_machine_adjudication {VERSION} {sha[:16]}',
               'decidedByRole': ROLE, 'reviewedAt': stamp, 'candidates': candidates}
    _require(set(receipt) == adjudication.TOP_KEYS
             and all(set(row) == adjudication.CANDIDATE_KEYS for row in candidates), 'receipt_shape')
    basis = {'schemaVersion': BASIS_SCHEMA, 'implementationSha256': sha, 'version': VERSION,
             'receiptSha256': adjudication.receipt_sha256(receipt), 'targetLocale': target_locale,
             'editionId': edition_id, 'coverageEditionId': english_edition.edition_id,
             'flaggedUnits': flagged, 'flaggedUnitsSource':
             'supplied' if flagged_units is not None else 'discovered', 'discoveredUnits': discovered,
             'humanApproval': False, 'candidates': basis_rows,
             'notice': 'Deterministic surface-signal adjudication. A human receipt for the same bindings '
                       'overrides this one. Not a translation or edition approval. A quotation is admitted as '
                       'the whole pinned verse only when the spoken words cover the whole verse by the English '
                       'coverage measure; a fragment is translated as the speaker\'s own words (2026-10-08). '
                       'Discovery claims only the unit that opens a quotation and keeps the whole range on it; '
                       'units that continue a reading are flagged explicitly, since the text gives no boundary.'}
    return receipt, basis


def adjudicate_fixture(directory: str | Path, *, target_locale: str, flagged_units: list[str] | None = None,
                       discover: bool = False, library: Any = None,
                       coverage_edition: Any = None) -> tuple[dict[str, Any], dict[str, Any]]:
    directory = Path(directory)
    source, anchor, plan = (json.loads((directory / name).read_text(encoding='utf-8'))
                            for name in ('source.json', 'anchor.json', 'group-plan.json'))
    manifest_path = directory / 'fixture-manifest.json'
    if flagged_units is None and not discover and manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        listed = manifest.get('sourceQuotationUnits')
        if isinstance(listed, list):
            flagged_units = list(listed)  # an explicit empty list means none, not discovery
    return adjudicate(source, anchor, plan, target_locale=target_locale, flagged_units=flagged_units, library=library,
                      coverage_edition=coverage_edition)


def _write_new(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('fixture', type=Path, help='Directory with source.json, anchor.json and group-plan.json')
    parser.add_argument('--target-locale', default='zh-Hans', choices=sorted(adjudication.PINNED_EDITIONS))
    parser.add_argument('--out', type=Path, required=True, help='New receipt file; never overwritten')
    parser.add_argument('--basis-out', type=Path, default=None, help='Defaults to <out>.basis.json')
    parser.add_argument('--flagged-unit', action='append', default=None,
                        help='Unit to adjudicate; defaults to the fixture manifest, else discovery')
    parser.add_argument('--discover', action='store_true', help='Ignore the manifest and discover flagged units')
    args = parser.parse_args(argv)
    basis_path = args.basis_out or args.out.with_suffix('.basis.json')
    if args.out.exists() or basis_path.exists():
        raise SystemExit('receipt or basis file exists; choose a new path')
    try:
        receipt, basis = adjudicate_fixture(args.fixture, target_locale=args.target_locale,
                                            flagged_units=args.flagged_unit, discover=args.discover)
    except MachineAdjudicationError as exc:
        raise SystemExit(f'refused: {exc}') from exc
    _write_new(args.out, receipt)
    _write_new(basis_path, basis)
    print(json.dumps({'receiptSha256': basis['receiptSha256'], 'flaggedUnits': basis['flaggedUnits'],
                      'decisions': [(row['candidateId'], row['decision']) for row in basis['candidates']]},
                     ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
