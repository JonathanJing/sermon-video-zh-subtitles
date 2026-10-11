"""Machine candidate queue for scripture adjudication: lists, never decides.

Every source unit with a surface signal of possible scripture (a book reference,
a verse or chapter mention, a speech verb, or quotation marks) becomes a
candidate with its neighbours, timing and the signals found. The queue carries
no classification and no approval. A human writes the adjudication receipt
from it. Missing a signal is possible, so the queue is a superset to review,
not proof that a unit contains no quotation.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from scripts import target_language_policy as policies

SCHEMA = 'sermon-scripture-candidate-queue-v1'
BOOKS = (
    'Genesis|Exodus|Leviticus|Numbers|Deuteronomy|Joshua|Judges|Ruth|Samuel|Kings|Chronicles|Ezra|Nehemiah|'
    'Esther|Job|Psalms?|Proverbs|Ecclesiastes|Song of (?:Songs|Solomon)|Isaiah|Jeremiah|Lamentations|Ezekiel|Daniel|Hosea|'
    'Joel|Amos|Obadiah|Jonah|Micah|Nahum|Habakkuk|Zephaniah|Haggai|Zechariah|Malachi|Matthew|Mark|Luke|John|'
    'Acts|Romans|Corinthians|Galatians|Ephesians|Philippians|Colossians|Thessalonians|Timothy|Titus|Philemon|'
    'Hebrews|James|Peter|Jude|Revelation'
)
SIGNALS = (
    # ASR punctuates "John, chapter 3, verse 16"; a comma after the book still names the reference.
    ('book_reference', re.compile(r'\b(?:' + BOOKS + r')[\s,]+(?:chapter\s+)?\d+(?::\d+(?:[-–]\d+)?)?', re.I)),
    ('chapter_verse', re.compile(r'\b(?:chapter|verse)s?\s+\d+', re.I)),
    ('speech_verb', re.compile(r'\b(?:says?|said|reads?|writes?|wrote|saying|written)\b', re.I)),
    ('quotation_marks', re.compile(r'["“”「」『』]')),
    ('scripture_word', re.compile(r'\b(?:scripture|bible|gospel|word of god|the lord)\b', re.I)),
)


def _sha(value: Any) -> str:
    return policies.canonical_sha256(value)


def _neighbour(units: list[dict[str, Any]], index: int) -> dict[str, Any] | None:
    if 0 <= index < len(units):
        return {'sourceUnitId': units[index]['sourceUnitId'], 'english': units[index]['english']}
    return None


def build_queue(source: dict[str, Any], anchor: dict[str, Any], plan: list[dict[str, Any]]) -> dict[str, Any]:
    """Return candidates plus a full review list. Never a classification or approval.

    Candidates are units with a surface signal and their immediate neighbours,
    because a quotation often continues into the next unit without a marker.
    reviewUnits lists every unit so a human can read the whole sermon; surface
    signals cannot find allusions or unmarked quotations.
    """
    units = anchor['sourceUnits']
    group_of = {unit_id: row['translationGroupId'] for row in plan for unit_id in row['sourceUnitIds']}
    signalled: dict[int, list[dict[str, Any]]] = {}
    for index, unit in enumerate(units):
        found = []
        for kind, pattern in SIGNALS:
            for match in pattern.finditer(unit['english']):
                found.append({'kind': kind, 'text': match.group(0), 'start': match.start(), 'end': match.end()})
        if found:
            signalled[index] = found
    selected = set(signalled)
    for index in list(signalled):
        selected.update(i for i in (index - 1, index + 1) if 0 <= i < len(units))
    candidates = []
    for index in sorted(selected):
        unit = units[index]
        signals = signalled.get(index, [])
        candidates.append({
            'candidateId': f'c{len(candidates) + 1:03d}',
            'sourceUnitIds': [unit['sourceUnitId']],
            'translationGroupId': group_of.get(unit['sourceUnitId']),
            'english': unit['english'],
            'start': unit.get('start'), 'end': unit.get('end'),
            'previous': _neighbour(units, index - 1), 'next': _neighbour(units, index + 1),
            'signals': signals,
            'kinds': sorted({signal['kind'] for signal in signals}) or ['adjacent_to_signal'],
            'machineClassification': None,
            'decisionStatus': 'not_decided',
        })
    review_units = [{'sourceUnitId': unit['sourceUnitId'], 'english': unit['english'],
                     'start': unit.get('start'), 'end': unit.get('end'),
                     'translationGroupId': group_of.get(unit['sourceUnitId']),
                     'suggested': index in selected} for index, unit in enumerate(units)]
    return {'schemaVersion': SCHEMA, 'bindings': {'source.json': _sha(source), 'anchor.json': _sha(anchor),
                                                   'group-plan.json': _sha(plan)},
            'sourceUnitCount': len(units), 'candidateCount': len(candidates),
            'candidates': candidates, 'reviewUnits': review_units,
            'notice': 'Machine candidates for human adjudication. No classification, approval or quotation claim. '
                      'Every unit is in reviewUnits; a human must read them all.'}


def build_from_fixture(directory: str | Path) -> dict[str, Any]:
    directory = Path(directory)
    source, anchor, plan = (json.loads((directory / name).read_text(encoding='utf-8'))
                            for name in ('source.json', 'anchor.json', 'group-plan.json'))
    return build_queue(source, anchor, plan)


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('fixture', type=Path, help='Directory with source.json, anchor.json and group-plan.json')
    parser.add_argument('--out', type=Path, required=True, help='New queue file; never overwritten')
    args = parser.parse_args(argv)
    if args.out.exists():
        raise SystemExit('queue file exists; choose a new path')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    queue = build_from_fixture(args.fixture)
    args.out.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'candidateCount': queue['candidateCount'], 'sourceUnitCount': queue['sourceUnitCount']}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
