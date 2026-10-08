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

VERSION = '2026-10-08-v3'
ROLE = 'machine_adjudicator'
BASIS_SCHEMA = 'sermon-scripture-machine-adjudication-basis-v1'
# A book mention stays in force for this many following units; sermons move on.
CONTEXT_WINDOW_UNITS = 12
# A reading signal may sit in the unit before the verse mention ("John says, verse 2 ...").
READING_LOOKBACK_UNITS = 1

_BOOKS = queue_module.BOOKS
# Spoken numbers may be compound ("twenty-three", "one hundred nineteen"); cuv_scripture parses them.
_NUMBER_WORD = cuv_scripture._EN_NUMBER_PATTERN
_NUM = rf'(?:\d+|(?:{_NUMBER_WORD})(?:(?:\s+|-)(?:{_NUMBER_WORD}))*)'
# "2 and 3" joins adjacent verses; "2 and 5" names two verses and is never a range.
_RANGE = rf'(?P<v1>{_NUM})(?:\s*(?P<join>-|–|to|through|and)\s*(?P<v2>{_NUM}))?'
# "First John", "1st John" and "1 John" all name the epistle; the gospel has no ordinal.
_ORDINAL = r'(?:[123]|1st|2nd|3rd|first|second|third)'
BOOK_MENTION = re.compile(
    rf'\b(?P<book>(?:{_ORDINAL}\s+)?(?:{_BOOKS}))\s+(?:chapter\s+)?(?P<chapter>{_NUM})\b'
    rf'(?P<more_chapters>\s+and\s+{_NUM}\b)?(?:\s*:\s*{_RANGE})?', re.I)
# "Now turn to Romans" moves the reading to another book without naming a chapter.
BOOK_TRANSITION = re.compile(
    rf'\b(?:turn(?:ing)?|open(?:ing)?|go(?:ing)?|com(?:e|ing)|back|look(?:ing)?)\s+(?:to|at|in)\s+'
    rf'(?:the\s+book\s+of\s+)?(?P<book>(?:{_ORDINAL}\s+)?(?:{_BOOKS}))\b', re.I)
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


def _number(value: str) -> int | None:
    """A spoken or written chapter or verse number, or None when the words do not form one."""
    try:
        return cuv_scripture._number(value)
    except cuv_scripture.CuvError:
        return None


def _edition(target_locale: str, library: Any = None) -> tuple[str, Any, str]:
    """The locale's pinned edition, its lookup object and its verification status.

    A third-party text still awaiting publisher comparison is loaded but not
    pinned scripture: adjudication still runs on its units, and only a whole
    reading that would be emitted as a quotation is withheld (``edition_not_verified``)."""
    _require(target_locale in adjudication.PINNED_EDITIONS, 'no_pinned_edition_for_locale')
    edition_id = adjudication.PINNED_EDITIONS[target_locale]
    if edition_id == 'CUV':
        return edition_id, (library or cuv_scripture.CuvLibrary.from_path()), scripture_editions.VERIFIED
    try:
        edition = scripture_editions.load(edition_id)
    except scripture_editions.EditionError as exc:
        raise MachineAdjudicationError('edition_unavailable') from exc
    return edition_id, edition, edition.verification


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


_QUOTE_MARK = re.compile(r'["“”「」『』]')
_QUOTE_SPAN = re.compile(r'["“「『]([^"“”「」『』]+)["”」』]')
QUOTED_SPAN = 'quotation_marks'
UNIT_REMAINDER = 'unit_remainder'


def _spoken_text(english: list[str]) -> tuple[str, str]:
    """The words measured against the verse, and which boundary bounds them.

    When the transcript marks the quotation, only the quoted spans are the
    quotation: commentary outside the marks never counts towards the verse.
    Unbalanced marks leave the boundary unknown and the quotation is refused.
    Without marks, the units' words minus the reference and reading phrases
    that introduce the quotation are the quotation, bounded by the units."""
    joined = ' '.join(english)
    if _QUOTE_MARK.search(joined):
        spans = _QUOTE_SPAN.findall(joined)
        _require(len(_QUOTE_MARK.findall(joined)) == 2 * len(spans) and spans, 'quotation_boundary_unknown')
        return re.sub(r'\s+', ' ', ' '.join(spans)).strip(), QUOTED_SPAN
    pieces = []
    for text in english:
        for pattern in (BOOK_MENTION, BOOK_TRANSITION, CHAPTER_MENTION, VERSE_MENTION, _SPEECH_VERB):
            text = pattern.sub(' ', text)
        pieces.append(text)
    return re.sub(r'\s+', ' ', ' '.join(pieces)).strip(), UNIT_REMAINDER


def _measure(english_edition: Any, english: list[str], ref: cuv_scripture.Reference) -> dict[str, Any]:
    """Coverage of ``ref`` by the units' quotation; raises when no boundary or no English text bounds it."""
    spoken, span = _spoken_text(english)
    return coverage_module.coverage(english_edition, ref, spoken) | {'spokenSpan': span}


def _per_unit_layout(rows: list[dict[str, Any]], run: list[int], reference: cuv_scripture.Reference,
                     english_edition: Any) -> tuple[list[tuple[list[str], Any, dict[str, Any]]] | None, str]:
    """One verse per unit, only when the coverage measure establishes each unit's verse boundary.

    Unit boundaries are not verse boundaries: a unit may end mid-verse. Each
    unit must cover its own verse as a whole and must not also cover a
    neighbouring verse of the range; otherwise the range stays jointly bound."""
    verses = list(range(reference.start_verse, reference.end_verse + 1))
    pairs = []
    for i, verse in zip(run, verses):
        unit, english = rows[i]['sourceUnitId'], [rows[i]['english']]
        own = cuv_scripture.Reference(reference.book, reference.chapter, verse)
        try:
            measure = _measure(english_edition, english, own)
            if not measure['wholeVerse']:
                return None, f'{unit} does not read the whole of {own.canonical_ref}'
            spoken, _ = _spoken_text(english)
            for neighbour in (verse - 1, verse + 1):
                if neighbour in verses:
                    other = cuv_scripture.Reference(reference.book, reference.chapter, neighbour)
                    overlap = coverage_module.coverage(english_edition, other, spoken)
                    if overlap['verseCoverage'] >= coverage_module.WHOLE_VERSE_COVERAGE_MIN:
                        return None, (f'{unit} also covers {other.canonical_ref} (coverage '
                                      f"{overlap['verseCoverage']}): unit boundaries are not verse boundaries")
        except (coverage_module.CoverageError, MachineAdjudicationError) as exc:
            return None, f'{unit} against {own.canonical_ref}: {exc}'
        pairs.append(([unit], own, measure))
    return pairs, 'each unit covers its own verse as a whole and no neighbouring verse of the range'


def _book(name: str) -> str | None:
    name = re.sub(r'^([123])(?:st|nd|rd)\s+', r'\1 ', name.strip(), flags=re.I)  # "1st John" -> "1 John"
    try:
        return cuv_scripture.normalize_book(name)
    except cuv_scripture.CuvError:
        return None


def _verse_range(match: re.Match) -> tuple[int, int] | None:
    """The verses a mention names, or None when "and" joins verses that are not adjacent or a number fails."""
    v1 = _number(match['v1'])
    if v1 is None:
        return None
    if not match['v2']:
        return v1, v1
    v2 = _number(match['v2'])
    if v2 is None or (match['join'].casefold() == 'and' and v2 != v1 + 1):
        return None
    return v1, v2


SEVERAL_REFERENCES = 'several scripture references in one unit: no verse range is bound to it'


def _events(english: str) -> list[tuple[str, re.Match]]:
    """Every reference event in the unit, in textual order.

    A book mention claims its whole span: "turn to Romans chapter 8" is one
    mention, not a transition to Romans and then a mention, and the "chapter 8"
    inside it is not a second chapter mention."""
    found = [(m.start(), m.end(), 'book', m) for m in BOOK_MENTION.finditer(english)]
    claimed = [(start, end) for start, end, _, _ in found]
    for kind, pattern in (('transition', BOOK_TRANSITION), ('chapter', CHAPTER_MENTION), ('verse', VERSE_MENTION)):
        found.extend((m.start(), m.end(), kind, m) for m in pattern.finditer(english)
                     if not any(m.start() < end and start < m.end() for start, end in claimed))
    return [(kind, match) for _, _, kind, match in sorted(found, key=lambda item: item[0])]


def _scan(units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per unit: the reference context in force and any verse mention, with its evidence.

    Events are applied in the order they are spoken, so the context carried to
    the next unit is the last one named. A unit's own verse range is bound only
    when it names verses once and names no other context after them: "We
    compared John 3:16, then turn to Romans chapter 8" leaves Romans 8 in force
    and binds no verse of its own."""
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
        verse_range: tuple[int, int] | None = None
        verse_mentions = 0
        context_after_verse = False
        for kind, match in _events(english):
            if kind == 'book':
                book, since_book = _book(match['book']), 0
                if match['more_chapters']:
                    chapter = None  # "Revelation 4 and 5": two chapters, no single context.
                    evidence.append(f'book mention with several chapters: {match.group(0)!r}')
                else:
                    chapter = _number(match['chapter'])
                    evidence.append(f'book and chapter mention: {match.group(0)!r}')
                if match['v1']:
                    verse_mentions += 1
                    verse_range = _verse_range(match)
                    continue  # the mention names its own verses; it is not a context after them
            elif kind == 'transition':
                book, chapter, since_book = _book(match['book']), None, 0
                evidence.append(f'book transition without a chapter: {match.group(0)!r}')
            elif kind == 'chapter':
                if not book:
                    continue
                chapter = _number(match['chapter'])
                evidence.append(f'chapter mention: {match.group(0)!r}')
            else:
                verse_mentions += 1
                verse_range = _verse_range(match)
                evidence.append(f'verse mention: {match.group(0)!r}')
                continue
            if verse_mentions:
                context_after_verse = True
        verses_named = verse_mentions > 0
        if verse_mentions > 1 or context_after_verse:
            verse_range = None  # ambiguous: never the first reference, never the last context's verse
            evidence.append(SEVERAL_REFERENCES)
        elif verses_named and verse_range is None:
            evidence.append('the verse mention does not resolve to a range (numbers unparsed or not adjacent)')
        signals = _signals(english)
        rows.append({'sourceUnitId': unit['sourceUnitId'], 'english': english, 'book': book, 'chapter': chapter,
                     'verseRange': verse_range, 'versesNamed': verses_named,
                     'reading': bool(signals & READING_SIGNALS),
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
        # A unit naming its own verses, resolvable or not, opens a new quotation even right after another.
        if runs and runs[-1][-1] == i - 1 and not rows[i]['versesNamed']:
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
    if any(rows[i]['versesNamed'] for i in run):
        return None, None  # the run names verses that do not resolve; nothing is borrowed
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
    edition_id, edition, verification = _edition(target_locale, library)
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
        if reference is None:
            for unit in run_units:
                candidate, why = _paraphrase(f'm{len(candidates) + 1:03d}', [unit],
                                             'no book, chapter and verse reference resolves for this unit')
                candidates.append(candidate)
                row = rows[run[run_units.index(unit)]]
                basis_rows.append(why | {'evidence': row['evidence'], 'english': row['english']})
            continue
        verses = list(range(reference.start_verse, reference.end_verse + 1))
        pairs, boundary = (None, 'the units and verses do not pair one to one')
        if len(run) == len(verses):
            pairs, boundary = _per_unit_layout(rows, run, reference, english_edition)
        if pairs is not None:
            layout = 'one verse per unit'
        else:
            # The range stays jointly bound to the run; several units must share one group.
            if len(run) > 1 and len({group_of.get(unit) for unit in run_units}) != 1:
                reason = (f'{reference.canonical_ref} is read across several translation groups; the pinned '
                          "wording cannot be bound to one group, so the speaker's words are translated")
                for unit in run_units:
                    candidate, why = _paraphrase(f'm{len(candidates) + 1:03d}', [unit], reason)
                    candidates.append(candidate)
                    basis_rows.append(why | {'reference': reference.canonical_ref, 'boundaryEvidence': boundary,
                                             'english': rows[run[run_units.index(unit)]]['english']})
                continue
            layout = ('one unit carries the whole range' if len(run) == 1
                      else 'several units in one translation group share the whole range')
            try:
                pairs = [(run_units, reference, _measure(english_edition, [rows[i]['english'] for i in run], reference))]
            except (coverage_module.CoverageError, MachineAdjudicationError) as exc:
                candidate, why = _paraphrase(f'm{len(candidates) + 1:03d}', run_units,
                                             f'no English text bounds the quotation of {reference.canonical_ref}: {exc}')
                candidates.append(candidate)
                basis_rows.append(why | {'reference': reference.canonical_ref, 'boundaryEvidence': boundary,
                                         'english': [rows[i]['english'] for i in run]})
                continue
            boundary = f'the range is bound to the run as a whole ({boundary})'
        for units_here, ref, measure in pairs:
            candidate_id = f'm{len(candidates) + 1:03d}'
            english_here = [rows[i]['english'] for i in run if rows[i]['sourceUnitId'] in units_here]
            # The pinned verse is admitted only when the speaker's quotation covers the whole verse.
            if not measure['wholeVerse']:
                candidate, why = _paraphrase(
                    candidate_id, units_here,
                    f"fragment of {ref.canonical_ref}: the speaker said {measure['coveredContentWords']} of "
                    f"{measure['verseContentWords']} content words (coverage {measure['verseCoverage']}, length "
                    f"{measure['lengthRatio']}); translated as the speaker's own words (decision 2026-10-08)")
                candidates.append(candidate)
                basis_rows.append(why | {'reference': ref.canonical_ref, 'quoteBoundary': FRAGMENT_BOUNDARY,
                                         'coverage': measure, 'boundaryEvidence': boundary, 'english': english_here})
                continue
            # A whole reading is pinned only from a verified edition; a pending one withholds the quotation.
            if verification != scripture_editions.VERIFIED:
                candidate, why = _paraphrase(
                    candidate_id, units_here,
                    f'edition_not_verified: {edition_id} is {verification}; the whole reading of '
                    f"{ref.canonical_ref} is translated as the speaker's words until the edition is verified")
                candidates.append(candidate)
                basis_rows.append(why | {'reference': ref.canonical_ref, 'editionVerification': verification,
                                         'quoteBoundary': QUOTE_BOUNDARY, 'coverage': measure,
                                         'boundaryEvidence': boundary, 'english': english_here})
                continue
            try:
                found = edition.lookup(ref)
            except (cuv_scripture.CuvError, scripture_editions.EditionError) as exc:
                candidate, why = _paraphrase(candidate_id, units_here,
                                             f'edition lookup failed for {ref.canonical_ref}: {exc}')
                candidates.append(candidate)
                basis_rows.append(why | {'reference': ref.canonical_ref, 'english': english_here})
                continue
            candidates.append({'candidateId': candidate_id, 'sourceUnitIds': units_here,
                               'classification': 'direct_quote', 'reference': ref.canonical_ref,
                               'editionId': edition_id, 'exactSentence': found['text']})
            basis_rows.append({'candidateId': candidate_id, 'sourceUnitIds': units_here, 'decision': 'direct_quote',
                               'reference': ref.canonical_ref, 'textSha256': found['textSha256'], 'layout': layout,
                               'boundaryEvidence': boundary, 'quoteBoundary': QUOTE_BOUNDARY, 'coverage': measure,
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
             'editionId': edition_id, 'editionVerification': verification,
             'coverageEditionId': english_edition.edition_id,
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
