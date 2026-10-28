"""Apply an explicitly frozen, visually checked Chinese guide revision.

This module does not download or publish source material.  Corrections and
licensed illustration bytes remain in ignored local output; the existing v1
bundle and staging identities are never modified.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import re

SOURCE_SHA256 = 'd6c6064e8fab11ab012edd9535372a9f99b83cd5240b6014f5451795a9198f86'
ENGLISH_SHA256 = '3eb6cca50c898c8fcb82be73bcdce67deaad64267ad7041581e363aa39757708'
CUV_SHA256 = '363afb38148f150b30fee727f4818faa821a0d17b4888c16be3e05bd462503bb'
CORRECTIONS_SHA256 = 'df50f608d7a802052bdbf949aa3fb0988432c331a57a10c128160e9eb77c62de'
BUNDLE_CORRECTIONS_SHA256 = '0c327354029e9a92f22f03d07a11d153c825550c77f7cbf092edaa8c0b18d86a'
MAP_EVIDENCE_SHA256 = '054123c6365b64caf6c854225efcfea983036406e1c18e51aa2645167b7243ec'
REVISION_SCHEMA = 'tongxing-weekly-guide-rich-revision-v1'
PAGE = re.compile(r'^## PAGE (\d+)（印刷页 (\d+)，id ([^\n]+)）\s*$', re.MULTILINE)
TABLE_SEPARATOR = re.compile(r'^:?-{3,}:?$')
# Physical source pages and the private original-page capture used to check
# their layout. These captures are evidence, never delivered as product art.
CHECKED_PAGES = {
    36: (1, 'pages-036-037.jpg'), 47: (2, 'pages-046-047.jpg'),
    60: (3, 'pages-060-061.jpg'), 61: (3, 'pages-060-061.jpg'),
    71: (4, 'pages-070-071.jpg'), 72: (4, 'pages-072-073.jpg'),
    74: (4, 'pages-074-075.jpg'),
    83: (5, 'pages-082-083.jpg'), 92: (6, 'pages-092-093.jpg'),
    93: (6, 'pages-092-093.jpg'), 99: (7, 'pages-098-099.jpg'),
    105: (7, 'pages-104-105.jpg'), 115: (8, 'pages-114-115.jpg'),
    123: (9, 'pages-122-123.jpg'), 124: (9, 'pages-124-125.jpg'),
    125: (9, 'pages-124-125.jpg'), 127: (9, 'pages-126-127.jpg'),
    138: (10, 'pages-138-139.jpg'), 139: (10, 'pages-138-139.jpg'),
    140: (10, 'pages-140-141.jpg'),
    149: (11, 'pages-148-149.jpg'), 151: (11, 'pages-150-151.jpg'),
}
EVIDENCE_LIMITATION = ('browser capture, not original print-resolution file; layout and reference '
                       'relationships checked, not human translation approval')
ASSETS = {
    'weekly-guide-statue.jpg': {
        'source': 'statue.jpg',
        'sha256': 'f1d2f517120099a38614c7c560c1fbe054ec3ea4d741284fbcef496a7dab73b5',
        'creator': 'Renata Costa', 'sourcePage': 31,
        'alt': '尼布甲尼撒梦中巨像的插画，五个部位对应的解释见本页文字。',
        'caption': '原手册插画《巨像》 · Renata Costa 绘',
    },
    'weekly-guide-son-of-man.jpg': {
        'source': 'jesus-man.jpg',
        'sha256': '30c3e5b82c024bad3e40122f330f6606d022c91d8c77a82f06d6f1d5fc987f1f',
        'creator': 'Renata Costa', 'sourcePage': 37,
        'alt': '原手册中人子形象的插画。',
        'caption': '原手册插画《人子》 · Renata Costa 绘',
    },
}

# Pleiades representative points, not the exact sites of church buildings.
# Each stable source URL is shown with the CC BY 3.0 attribution in the App.
MAP_POINTS = [
    ('别迦摩',39.1325,27.184167,'550812'),
    ('推雅推喇',38.919999064160905,27.836209064855836,'550924'),
    ('撒狄',38.488314,28.040286,'550867'),
    ('士每拿',38.41719605,27.141387,'550893'),
    ('非拉铁非',38.35037355,28.516621,'550822'),
    ('以弗所',37.940164271971945,27.34240298195866,'599612'),
    ('老底嘉',37.835939323878684,29.107388778855608,'638955'),
    ('拔摩岛',37.328030107055355,26.559074265167897,'599872'),
]


def map_block(credits: dict[str, str]) -> dict:
    return {'type':'map','title':'七教会与拔摩岛',
        'points':[{'name':name,'latitude':latitude,'longitude':longitude,
                   'sourceURL':'https://pleiades.stoa.org/places/' + source,
                   'credit':credits[source]}
                  for name,latitude,longitude,source in MAP_POINTS],
        'caption':'地点约略位置示意，并非教会建筑精确位置。',
        'attribution':'独立绘制，地点代表坐标：Pleiades: A Gazetteer of Past Places（CC BY 3.0，https://pleiades.stoa.org/help/using-pleiades-data，访问于 2026-10-28）；原书地图改编自 Jen Wilkin, Revelation: Eternal King, Everlasting Kingdom (Lifeway Press, 2024)。'}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encoded(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def _text(value: object, *, allow_empty: bool = False) -> bool:
    return isinstance(value, str) and (allow_empty or bool(value.strip()))


def validate_blocks(blocks: object) -> None:
    """Fail a whole section, never silently discard an unsupported block."""
    if not isinstance(blocks, list) or not blocks:
        raise ValueError('rich blocks must be a nonempty list')
    for block in blocks:
        if not isinstance(block, dict):
            raise ValueError('invalid rich block')
        kind = block.get('type')
        if kind == 'paragraph':
            ok = set(block) == {'type', 'text'} and _text(block['text'])
        elif kind == 'table':
            columns, rows = block.get('columns'), block.get('rows')
            ok = (set(block) in ({'type', 'title', 'columns', 'rows'},
                                  {'type', 'title', 'columns', 'rows', 'footnote'})
                  and _text(block.get('title'), allow_empty=True)
                  and isinstance(columns, list) and len(columns) >= 2
                  and all(_text(x, allow_empty=True) for x in columns)
                  and isinstance(rows, list) and bool(rows)
                  and all(isinstance(row, list) and len(row) == len(columns)
                          and all(_text(x, allow_empty=True) for x in row) for row in rows)
                  and ('footnote' not in block or _text(block['footnote'], allow_empty=True)))
        elif kind in ('list', 'flow'):
            items = block.get('items')
            ok = (set(block) == {'type', 'title', 'items'}
                  and _text(block.get('title'), allow_empty=True)
                  and isinstance(items, list) and bool(items) and all(_text(x) for x in items))
        elif kind == 'image':
            ok = (set(block) == {'type', 'assetID', 'alt', 'caption'}
                  and block.get('assetID') in ASSETS and _text(block.get('alt'))
                  and _text(block.get('caption')))
        elif kind == 'map':
            points = block.get('points')
            ok = (set(block) == {'type','title','points','caption','attribution'}
                  and _text(block.get('title')) and _text(block.get('caption')) and _text(block.get('attribution'))
                  and isinstance(points,list) and len(points) >= 2
                  and all(isinstance(p,dict) and set(p)=={'name','latitude','longitude','sourceURL','credit'}
                          and _text(p['name']) and _text(p['credit']) and isinstance(p['latitude'],(int,float)) and not isinstance(p['latitude'],bool)
                          and isinstance(p['longitude'],(int,float)) and not isinstance(p['longitude'],bool)
                          and math.isfinite(p['latitude']) and math.isfinite(p['longitude'])
                          and -90 <= p['latitude'] <= 90 and -180 <= p['longitude'] <= 180
                          and isinstance(p['sourceURL'],str)
                          and re.fullmatch(r'https://pleiades\.stoa\.org/places/\d+',p['sourceURL']) is not None
                          for p in points)
                  and len({p['latitude'] for p in points}) > 1 and len({p['longitude'] for p in points}) > 1)
        else:
            ok = False
        if not ok:
            raise ValueError('invalid or unsupported rich block')


def source_pages(source: str) -> dict[int, tuple[int, str, str]]:
    headings = list(PAGE.finditer(source))
    pages = {}
    for index, match in enumerate(headings):
        number = int(match.group(1))
        if number in pages:
            raise ValueError('duplicate source page')
        end = headings[index + 1].start() if index + 1 < len(headings) else len(source)
        pages[number] = (int(match.group(2)), match.group(3), source[match.end():end].strip())
    return pages


def _cells(line: str) -> list[str] | None:
    line = line.strip()
    if not (line.startswith('|') and line.endswith('|')):
        return None
    return [item.strip().replace(r'\|', '|') for item in re.split(r'(?<!\\)\|', line[1:-1])]


def _page_blocks(body: str, page: int) -> list[dict]:
    """Parse tables only on the specific pages checked against original layout."""
    lines, blocks, paragraphs, index = body.splitlines(), [], [], 0
    def flush() -> None:
        if any(line.strip() for line in paragraphs):
            blocks.append({'type': 'paragraph', 'text': '\n'.join(paragraphs).strip()})
        paragraphs.clear()
    while index < len(lines):
        headers = _cells(lines[index])
        separators = _cells(lines[index + 1]) if index + 1 < len(lines) else None
        if headers and separators and len(headers) == len(separators) and all(TABLE_SEPARATOR.fullmatch(x) for x in separators):
            flush()
            index += 2
            rows = []
            while index < len(lines):
                row = _cells(lines[index])
                if row is None or len(row) != len(headers):
                    break
                rows.append(row)
                index += 1
            if not rows:
                raise ValueError('checked table has no rows')
            if page == 123:
                # The original final row spans both comparison columns.
                if len(headers) != 3 or len(rows) != 7:
                    raise ValueError('unexpected merged-row source shape')
                merged = rows.pop()
                blocks.append({'type': 'table', 'title': '', 'columns': headers, 'rows': rows})
                blocks.append({'type': 'paragraph', 'text': merged[0] + '：' + merged[1] + ' ' + merged[2]})
            else:
                blocks.append({'type': 'table', 'title': '', 'columns': headers, 'rows': rows})
        else:
            paragraphs.append(lines[index])
            index += 1
    flush()
    return blocks


def _curly_title(value: str) -> str:
    return re.sub(r'"([^"]+)"', r'“\1”', value)


def _fallback(blocks: list[dict]) -> str:
    chunks = []
    for block in blocks:
        kind = block['type']
        if kind == 'paragraph':
            chunks.append(block['text'])
        elif kind == 'table':
            chunks.append('\n\n'.join('\n'.join(f'{h}：{v}' if h else v for h, v in zip(block['columns'], row))
                                     for row in block['rows']))
        elif kind == 'list':
            chunks.append(block['title'] + '\n' + '\n'.join(block['items']))
        elif kind == 'flow':
            line = block['title'] + '：' + ' → '.join(block['items'])
            if chunks and previous_kind == 'flow':
                chunks[-1] += '\n' + line
            else:
                chunks.append(line)
        else:
            raise ValueError('unsupported fallback block')
        previous_kind = kind
    return '\n\n'.join(chunks)


def _page83(body: str) -> tuple[list[dict], str]:
    parsed = _page_blocks(body, 83)
    if len(parsed) != 5 or [b['type'] for b in parsed] != ['paragraph', 'table', 'paragraph', 'table', 'paragraph']:
        raise ValueError('unexpected checked page 83 shape')
    second = parsed[3]
    if len(second['columns']) != 4 or len(second['rows']) != 4 or second['columns'][1] or second['columns'][3]:
        raise ValueError('unexpected independent-list source shape')
    rows, headers = second['rows'], second['columns']
    tail = [line.strip() for line in parsed[4]['text'].splitlines() if line.strip()]
    if len(tail) != 2:
        raise ValueError('expected two independent direction arrows')
    flows = []
    for line in tail:
        if '：' not in line:
            raise ValueError('invalid direction arrow')
        title, text = line.split('：', 1)
        items = [x.strip() for x in text.split('→')]
        if len(items) < 2 or not all(items):
            raise ValueError('invalid direction sequence')
        flows.append({'type': 'flow', 'title': _curly_title(title.split('的次序')[0]) + '的次序', 'items': items})
    blocks = parsed[:3] + [
        {'type': 'list', 'title': _curly_title(headers[0]), 'items': [row[0] + '：' + row[1] for row in rows]},
        {'type': 'list', 'title': _curly_title(headers[2]), 'items': [row[2] + '：' + row[3] for row in rows]},
        *flows,
    ]
    # Original uses straight quotes in the heading but curly quotes in the
    # reader-facing list labels. Preserve all text, never pair the two lists.
    return blocks, _fallback(blocks)


def _page140(body: str) -> list[dict]:
    """Preserve the source's two independent groups, not false row pairings."""
    chunks = body.split('\n\n')
    if len(chunks) != 3:
        raise ValueError('unexpected page 140 source shape')
    groups = []
    for chunk, count in zip(chunks[1:], (3, 5)):
        lines = chunk.splitlines()
        if len(lines) != count + 1 or not lines[0].strip() or not all(line.startswith('- ') and line[2:].strip() for line in lines[1:]):
            raise ValueError('unexpected page 140 list shape')
        groups.append({'type':'list', 'title':lines[0], 'items':[line[2:] for line in lines[1:]]})
    return [{'type':'paragraph', 'text':chunks[0]}, *groups]


def _page138_139(body: str, page: int) -> list[dict]:
    """Use only the source's explicit heading pair and exactly two paragraphs."""
    chunks = body.split('\n\n')
    prefix_count, pair_count = {138:(3,1), 139:(0,2)}[page]
    if len(chunks) != prefix_count + pair_count:
        raise ValueError('unexpected comparison page structure')
    blocks = [{'type':'paragraph', 'text':chunk} for chunk in chunks[:prefix_count]]
    for chunk in chunks[prefix_count:]:
        lines = chunk.splitlines()
        if len(lines) != 3 or not lines[0].startswith('• ') or lines[0].count(' vs. ') != 1 or not all(lines):
            raise ValueError('unexpected comparison grouping')
        columns = lines[0][2:].split(' vs. ')
        if not all(columns):
            raise ValueError('empty source comparison heading')
        blocks.append({'type':'table','title':'','columns':columns,'rows':[[lines[1],lines[2]]]})
    return blocks


def build_corrections(source: bytes, cuv: bytes, english: bytes, originals: dict,
                      evidence_dir: Path, *, exclude_pages: tuple[int, ...] = ()) -> bytes:
    """Rebuild audited layout data from pinned text and checked visual evidence."""
    if digest(source) != SOURCE_SHA256 or digest(cuv) != CUV_SHA256 or digest(english) != ENGLISH_SHA256:
        raise ValueError('frozen source identity mismatch')
    pages = source_pages(source.decode('utf-8'))
    entries = []
    for number, (week, filename) in CHECKED_PAGES.items():
        if number in exclude_pages:
            continue
        if number not in pages or (week, number) not in originals:
            raise ValueError('missing checked source page')
        printed, source_id, body = pages[number]
        original = originals[(week, number)]
        evidence = (Path(evidence_dir).resolve() / filename).resolve()
        if not evidence.is_relative_to(Path(evidence_dir).resolve()) or not evidence.is_file():
            raise ValueError('missing visual evidence')
        if number == 83:
            blocks, corrected = _page83(body)
        elif number == 140:
            blocks, corrected = _page140(body), None
        elif number in (138, 139):
            blocks, corrected = _page138_139(body, number), None
        else:
            blocks = _page_blocks(body, number)
            corrected = _fallback(blocks) if number == 123 else None
        validate_blocks(blocks)
        entry = {'week': week, 'sourcePage': number, 'printedPage': printed, 'sourcePageID': source_id,
                 'expectedOriginalBodySHA256': digest(original.encode('utf-8')),
                 'sourceChinesePageSHA256': digest(body.encode('utf-8')),
                 'visualEvidenceSHA256': digest(evidence.read_bytes()), 'visualEvidenceFilename': filename,
                 'visualEvidenceLimitations': EVIDENCE_LIMITATION,
                 'review': 'machine_translation_not_human_reviewed', 'humanApproval': False, 'blocks': blocks}
        if number == 83:
            entry.update({'correctedFallbackBody': corrected, 'correctedFallbackBodySHA256': digest(corrected.encode('utf-8')),
                          'correction': 'The creation-day and de-creation-trumpet lists are independent; retain each list and the two direction arrows without inventing row relationships.'})
        elif number == 123:
            entry.update({'correction': 'Original final New Moses row spans the two comparison columns; preserve its text in a separate paragraph rather than inventing a column relationship.',
                          'correctedFallbackBody': corrected, 'correctedFallbackBodySHA256': digest(corrected.encode('utf-8'))})
        entries.append(entry)
    return encoded({'schemaVersion': 'tongxing-private-guide-table-audit-v1', 'sourceTranslationSHA256': digest(source),
        'sourceEnglishExtractSHA256': digest(english), 'sourceBibleSHA256': digest(cuv),
        'sourceURL': 'https://www.flipsnack.com/57AF6AEEFB5/revelation-series-guide',
        'status': 'local_prepared_not_published', 'humanApproval': False, 'entries': entries})


def validate_revision(source: bytes, cuv: bytes, corrections: bytes, evidence_dir: Path,
                      *, expected_corrections_sha: str = CORRECTIONS_SHA256) -> dict:
    """Bind each change to the original source page, screenshot and frozen input."""
    if digest(source) != SOURCE_SHA256 or digest(cuv) != CUV_SHA256:
        raise ValueError('Chinese source or Bible source hash mismatch')
    if digest(corrections) != expected_corrections_sha:
        raise ValueError('rich correction file hash mismatch')
    value = json.loads(corrections)
    if (not isinstance(value, dict) or value.get('schemaVersion') != 'tongxing-private-guide-table-audit-v1'
        or value.get('sourceTranslationSHA256') != SOURCE_SHA256
        or value.get('sourceEnglishExtractSHA256') != ENGLISH_SHA256
        or value.get('sourceBibleSHA256') != CUV_SHA256 or value.get('humanApproval') is not False
        or not isinstance(value.get('entries'), list) or not value['entries']):
        raise ValueError('invalid rich revision provenance')
    pages = source_pages(source.decode('utf-8'))
    entries = {}
    evidence = Path(evidence_dir).resolve()
    for entry in value['entries']:
        if not isinstance(entry, dict):
            raise ValueError('invalid correction entry')
        week, number = entry.get('week'), entry.get('sourcePage')
        if (not isinstance(week, int) or isinstance(week, bool) or not 1 <= week <= 12
            or not isinstance(number, int) or isinstance(number, bool) or number in entries
            or entry.get('humanApproval') is not False
            or entry.get('review') != 'machine_translation_not_human_reviewed'):
            raise ValueError('invalid or duplicate correction identity')
        original = pages.get(number)
        if (not original or original[0] != entry.get('printedPage') or original[1] != entry.get('sourcePageID')
            or digest(original[2].encode('utf-8')) != entry.get('sourceChinesePageSHA256')):
            raise ValueError('correction source page differs from frozen translation')
        filename = entry.get('visualEvidenceFilename')
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise ValueError('invalid visual evidence path')
        file = (evidence / filename).resolve()
        if not file.is_relative_to(evidence) or not file.is_file() or digest(file.read_bytes()) != entry.get('visualEvidenceSHA256'):
            raise ValueError('visual evidence hash mismatch')
        validate_blocks(entry.get('blocks'))
        corrected = entry.get('correctedFallbackBody')
        if corrected is not None and (not _text(corrected) or digest(corrected.encode('utf-8')) != entry.get('correctedFallbackBodySHA256')):
            raise ValueError('corrected fallback hash mismatch')
        entries[number] = entry
    return {'entries': entries, 'correctionsSHA256': digest(corrections), 'sourceSHA256': digest(source),
            'cuvSHA256': digest(cuv), 'schemaVersion': REVISION_SCHEMA, 'humanApproval': False}


def validate_assets(directory: Path) -> dict[str, bytes]:
    directory = Path(directory).resolve()
    result = {}
    for asset_id, info in ASSETS.items():
        path = (directory / info['source']).resolve()
        if not path.is_relative_to(directory) or not path.is_file():
            raise ValueError('licensed image source missing or outside image directory')
        data = path.read_bytes()
        if digest(data) != info['sha256']:
            raise ValueError('licensed image source hash mismatch')
        result[asset_id] = data
    return result


def validate_map_evidence(directory: Path) -> tuple[str, dict[str, str]]:
    """Bind every displayed representative point to frozen Pleiades bytes."""
    directory = Path(directory).resolve()
    manifest = (directory / 'map-points.json').read_bytes()
    if digest(manifest) != MAP_EVIDENCE_SHA256:
        raise ValueError('Pleiades map evidence hash mismatch')
    value = json.loads(manifest)
    if (value.get('schemaVersion') != 'tongxing-pleiades-map-research-v1'
        or value.get('license') != 'CC BY 3.0' or not isinstance(value.get('points'), list)
        or len(value['points']) != len(MAP_POINTS)):
        raise ValueError('invalid Pleiades map evidence')
    records = {item.get('uri'): item for item in value['points'] if isinstance(item,dict)}
    if len(records) != len(MAP_POINTS):
        raise ValueError('duplicate Pleiades source')
    credits = {}
    for name,latitude,longitude,source in MAP_POINTS:
        uri='https://pleiades.stoa.org/places/' + source
        item=records.get(uri)
        if (not item or item.get('chinese')!=name or item.get('latitude')!=latitude
            or item.get('longitude')!=longitude or item.get('jsonURL')!=uri+'/json'):
            raise ValueError('Pleiades representative point mismatch')
        path=(directory/'pleiades'/f'{source}.json').resolve()
        if not path.is_relative_to(directory) or not path.is_file():
            raise ValueError('Pleiades source missing or outside evidence directory')
        raw=path.read_bytes()
        data = json.loads(raw)
        if digest(raw)!=item.get('sourceJSONSHA256') or data.get('reprPoint')!=[longitude,latitude]:
            raise ValueError('Pleiades source content mismatch')
        def names(key):
            values = data.get(key)
            if not isinstance(values, list) or not values or not all(isinstance(v,dict) and _text(v.get('name')) for v in values):
                raise ValueError('Pleiades authorship missing')
            return ', '.join(v['name'] for v in values)
        credits[source] = '作者：' + names('creators') + '；贡献者：' + names('contributors')
    return digest(manifest), credits


def section_title(section: dict) -> str:
    """Use a short source heading when one is present; never invent one."""
    body = section['body']
    lines = [line.strip().lstrip('#').strip() for line in body.splitlines() if line.strip()]
    if not lines:
        return section['title']
    title = lines[0].lstrip('•- ').strip()
    if title in ('讲道笔记', '深入研读') and len(lines) > 1:
        title = lines[1].lstrip('•- ').strip()
    if title.startswith(('［', '[', '【', '|')) or len(title) > 60 or title.endswith(('。', '？', '！')):
        return section['title']
    return title


def apply_revision(guide: dict, revision: dict, *, include_images: bool = False,
                   map_credits: dict[str, str] | None = None) -> dict:
    """Apply only approved page identities; baseline bodies must match exactly."""
    result = copy.deepcopy(guide)
    week = result.get('week')
    sections = result.get('sections')
    if not isinstance(week, int) or not isinstance(sections, list):
        raise ValueError('invalid guide')
    seen = set()
    for section in sections:
        if not isinstance(section, dict) or not isinstance(section.get('id'), str) or not isinstance(section.get('body'), str):
            raise ValueError('invalid guide section')
        match = re.fullmatch(r'page-(\d+)', section['id'])
        if not match:
            continue
        section['title'] = section_title(section)
        number = int(match.group(1))
        if number in seen:
            raise ValueError('duplicate guide source page')
        seen.add(number)
        entry = revision['entries'].get(number)
        if entry:
            if entry['week'] != week or digest(section['body'].encode('utf-8')) != entry.get('expectedOriginalBodySHA256'):
                raise ValueError('correction does not bind the original guide body')
            section['body'] = entry.get('correctedFallbackBody', section['body'])
            section['blocks'] = copy.deepcopy(entry['blocks'])
        if include_images:
            for asset_id, info in ASSETS.items():
                if week == 1 and number == info['sourcePage']:
                    if number == 37:
                        section['title'] = '人子的形象'
                    section['blocks'] = [{'type': 'paragraph', 'text': section['body']},
                        {'type': 'image', 'assetID': asset_id, 'alt': info['alt'], 'caption': info['caption']}]
            if week == 1 and number == 33:
                if map_credits is None:
                    raise ValueError('map author credits are required')
                section['blocks'] = [map_block(map_credits), {'type':'paragraph', 'text':section['body']}]
        if 'blocks' in section:
            validate_blocks(section['blocks'])
    return result
