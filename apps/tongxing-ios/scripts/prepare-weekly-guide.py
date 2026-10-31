#!/usr/bin/env python3
"""Create a local Beta guide payload from the verified existing translation.

The generated payload and receipt are ignored, never added to Git. A source
hash binds page numbering and content to the previously identified revision.
Adding a week requires a verified sermon page ID, page bounds, and metadata;
never guess a mapping from a date or title.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

# Resolve the delivery helper from this checkout, not an editable install in a
# different worktree. The legacy generator below remains byte-identical.
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / 'packages/production/src'))
from tongxing_production.delivery import weekly_guide_rich as rich
from tongxing_production.delivery import weekly_guide_staging as staging

SOURCE_SHA256 = "d6c6064e8fab11ab012edd9535372a9f99b83cd5240b6014f5451795a9198f86"
CUV_SHA256 = "363afb38148f150b30fee727f4818faa821a0d17b4888c16be3e05bd462503bb"
# md PAGE numbers are physical sequence identifiers, not printed page numbers.
WEEKS = [
    {"ids": ["2026-09-13-same_video-weekendlive-a9e91f52eb4c2484", "2026-09-13-live_archive-8JYwTq1xcBE"], "week": 1,
     "title": "耶稣与你同在", "scripture": "启示录 1 章", "first_page": 27, "last_page": 39},
    {"ids": ["2026-09-20-same_video-7c193fd4-bc90-4f3b-aa00-37dfe8423aa0"], "week": 2,
     "title": "耶稣应许", "scripture": "启示录 2–3 章", "first_page": 41, "last_page": 49},
    {"ids": ["2026-09-27-weekend-sermon-drive-530"], "week": 3,
     "title": "耶稣配得", "scripture": "启示录 4–5 章", "first_page": 51, "last_page": 63},
    {"ids": ["resi-20261004-69ba7a66"], "week": 4,
     "title": "耶稣审判并保守", "scripture": "启示录 6–8:1", "first_page": 65, "last_page": 77},
    {"ids": ["resi-20261011-54475d42"], "week": 5,
     "title": "耶稣警告", "scripture": "启示录 8–9 章", "first_page": 79, "last_page": 85},
    {"ids": ["resi-20261018-15030286", "resi-20261018-broadcast"], "week": 6,
     "title": "耶稣差遣并使属祂的人复活", "scripture": "启示录 10–11 章", "first_page": 87, "last_page": 95},
    {"ids": ["revelation-jesus-wins-20261025"], "week": 7,
     "title": "耶稣得胜", "scripture": "启示录 12–13 章", "first_page": 97, "last_page": 107},
]
# APPENDIX_TITLES in the source binds one appendix page to each of these
# seven weeks. Pages 164–170 are distinct sections, not continuation pages.
for item in WEEKS:
    item['appendix_page'] = 163 + item['week']
    item['scripture_first_page'] = {1: 28, 2: 42, 3: 52, 4: 66, 5: 80, 6: 88, 7: 100}[item['week']]
    item['scripture_start'], item['scripture_end'] = {
        1: ('1:1', '1:20'), 2: ('2:1', '3:22'), 3: ('4:1', '5:14'),
        4: ('6:1', '8:1'), 5: ('8:1', '9:21'), 6: ('10:1', '11:19'),
        7: ('12:1', '13:18'),
    }[item['week']]
PAGE = re.compile(r'^## PAGE (\d+)（印刷页 (\d+)，id [^\n]+）\s*$', re.MULTILINE)
TABLE_SEPARATOR = re.compile(r'^:?-{3,}:?$')


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verse_key(key: str) -> tuple[int, int]:
    chapter, verse = key.split(':')
    return int(chapter), int(verse)


def table_cells(line: str) -> list[str] | None:
    """Parse an outer-pipe table row without treating escaped pipes as columns."""
    line = line.strip()
    if not (line.startswith('|') and line.endswith('|')):
        return None
    return [cell.strip().replace(r'\|', '|') for cell in re.split(r'(?<!\\)\|', line[1:-1])]


def readable_tables(text: str) -> str:
    """Replace Markdown table syntax with labeled cells, preserving row order."""
    lines = text.split('\n')
    output = []
    index = 0
    while index < len(lines):
        headers = table_cells(lines[index])
        separators = table_cells(lines[index + 1]) if index + 1 < len(lines) else None
        if not (headers and separators and len(headers) > 1 and len(headers) == len(separators)
                and all(TABLE_SEPARATOR.fullmatch(cell) for cell in separators)):
            output.append(lines[index])
            index += 1
            continue
        rows = []
        next_index = index + 2
        while next_index < len(lines):
            cells = table_cells(lines[next_index])
            if cells is None or len(cells) != len(headers):
                break
            rows.append(cells)
            next_index += 1
        if not rows:
            # Do not discard a header-only table when there is no data row.
            output.append('\n'.join(headers))
        else:
            output.append('\n\n'.join('\n'.join(
                f'{header}：{cell}' if header else cell
                for header, cell in zip(headers, row)
            ) for row in rows))
        index = next_index
    return '\n'.join(output)


def build_guides(source: str, weeks: list[dict], cuv: dict[str, str]) -> dict:
    identifiers = [page_id for week in weeks for page_id in week['ids']]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError('duplicate weekly page ID')
    headings = list(PAGE.finditer(source))
    pages = {}
    for index, match in enumerate(headings):
        number = int(match.group(1))
        if number in pages:
            raise ValueError(f"duplicate page: {number}")
        end = headings[index + 1].start() if index + 1 < len(headings) else len(source)
        pages[number] = (int(match.group(2)), source[match.end():end].strip())
    guides = []
    for week in weeks:
        sections = []
        appendix = week['appendix_page']
        if week['first_page'] > week['last_page'] or appendix <= week['last_page']:
            raise ValueError('invalid week or appendix page range')
        for number in [*range(week['first_page'], week['last_page'] + 1), appendix]:
            if number == week['scripture_first_page']:
                start, end = week['scripture_start'], week['scripture_end']
                if start not in cuv or end not in cuv:
                    raise ValueError('missing scripture boundary')
                keys = [key for key in sorted(cuv, key=verse_key) if verse_key(start) <= verse_key(key) <= verse_key(end)]
                sections.append({'id': 'scripture-cuv1919', 'title': '完整经文 · 和合本（1919）',
                                 'subtitle': '另附经文；并非手册原刊 CSB 译文', 'symbol': 'book',
                                 'body': '\n\n'.join(f'{key} {cuv[key]}' for key in keys)})
            if number not in pages or not pages[number][1]:
                raise ValueError(f"missing or empty page: {number}")
            printed, body = pages[number]
            body = readable_tables(body)
            title = f'附录 · 手册第 {printed} 页' if number == appendix else f'手册第 {printed} 页'
            sections.append({'id': f'page-{number}', 'title': title,
                             'subtitle': f'原手册印刷页 {printed}',
                             'symbol': 'doc.text', 'body': body})
        for page_id in week['ids']:
            guides.append({'id': page_id, **{key: week[key] for key in ('week', 'title', 'scripture')},
                           'sections': sections})
    return {'guides': guides}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path, help='previously identified Chinese translation')
    parser.add_argument('--cuv', required=True, type=Path, help='previously identified CUV 1919 Revelation JSON')
    parser.add_argument('--rich', action='store_true', help='prepare a separately versioned rich bundle; never overwrite v1')
    parser.add_argument('--english', type=Path, help='frozen English source extraction for the rich revision')
    parser.add_argument('--evidence-dir', type=Path, help='private checked source-page screenshots')
    parser.add_argument('--asset-dir', type=Path, help='licensed original illustration directory')
    parser.add_argument('--map-evidence-dir', type=Path, help='frozen Pleiades map source evidence directory')
    parser.add_argument('--output', required=True, type=Path, help='fresh ignored artifacts directory; never the active bundle directory')
    args = parser.parse_args()
    if args.rich:
        if not all((args.english, args.evidence_dir, args.asset_dir, args.map_evidence_dir)):
            parser.error('--rich requires --english, --evidence-dir, --asset-dir, and --map-evidence-dir')
    elif any((args.english, args.evidence_dir, args.asset_dir, args.map_evidence_dir)):
        parser.error('rich options require --rich')
    output = staging.safe_output(args.output)
    if output.exists():
        raise ValueError('output must be a new directory')
    data = args.source.read_bytes()
    actual = sha256(data)
    if actual != SOURCE_SHA256:
        raise SystemExit(f'Source SHA-256 mismatch: {actual}; expected {SOURCE_SHA256}')
    cuv_data = args.cuv.read_bytes()
    actual_cuv = sha256(cuv_data)
    if actual_cuv != CUV_SHA256:
        raise SystemExit(f'CUV source SHA-256 mismatch: {actual_cuv}; expected {CUV_SHA256}')
    cuv = json.loads(cuv_data.decode('utf-8'))
    original = build_guides(data.decode('utf-8'), WEEKS, cuv)
    original_bytes = rich.encoded(original)
    if args.rich:
        future = staging.build_staged(data.decode('utf-8'), cuv)
        originals = {(guide['week'], int(section['id'][5:])): section['body']
                     for guide in original['guides'] + future for section in guide['sections']
                     if section['id'].startswith('page-')}
        corrections = rich.build_corrections(data, cuv_data, args.english.read_bytes(), originals, args.evidence_dir,
                                             exclude_pages=(138, 139))
        revision = rich.validate_revision(data, cuv_data, corrections, args.evidence_dir,
                                          expected_corrections_sha=rich.BUNDLE_CORRECTIONS_SHA256)
        assets = rich.validate_assets(args.asset_dir)
        map_evidence_sha, map_credits = rich.validate_map_evidence(args.map_evidence_dir)
        result = {'schemaVersion': 'tongxing-weekly-guide-rich-bundle-v1',
                  'richRevisionSHA256': revision['correctionsSHA256'],
                  'mapEvidenceSHA256': map_evidence_sha,
                  'guides': [rich.apply_revision(guide, revision, include_images=True, map_credits=map_credits) for guide in original['guides']]}
        payload = rich.encoded(result)
        output.mkdir(parents=True, exist_ok=False)
        (output / 'rich-corrections.json').write_bytes(corrections)
        for asset_id, asset_bytes in assets.items():
            (output / asset_id).write_bytes(asset_bytes)
    else:
        payload = original_bytes
        output.mkdir(parents=True, exist_ok=False)
    (output / 'weekly-guides.json').write_bytes(payload)
    digest = sha256(payload)
    (output / 'weekly-guides.sha256').write_text(digest + '\n', encoding='utf-8')
    receipt = {'sourceSHA256': actual, 'cuvSourceSHA256': actual_cuv,
               'payloadSHA256': digest, 'locale': 'zh-Hans',
               'review': 'machine_translation_not_human_reviewed',
               'weeks': [{'week': week['week'], 'pageIDs': week['ids'],
                          'pageRange': [week['first_page'], week['last_page']],
                          'appendixPage': week['appendix_page']} for week in WEEKS]}
    if args.rich:
        receipt.update({'schemaVersion': rich.REVISION_SCHEMA,
                        'englishSourceSHA256': rich.ENGLISH_SHA256,
                        'baseV1PayloadSHA256': sha256(original_bytes),
                        'richRevisionSHA256': revision['correctionsSHA256'],
                        'mapEvidenceSHA256': map_evidence_sha,
                        'humanApproval': False,
                        'assets': [{'assetID': asset_id, 'sha256': info['sha256'],
                                    'creator': info['creator'], 'sourcePage': info['sourcePage']}
                                   for asset_id, info in rich.ASSETS.items()],
                        'futureWeeks': 'not_in_bundle'})
    (output / 'weekly-guides.receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Prepared {len(WEEKS)} guide(s); source SHA-256 {actual}; payload SHA-256 {digest}')


if __name__ == '__main__':
    main()
