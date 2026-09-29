#!/usr/bin/env python3
"""Bind analytics locales to verified published assets; retain prior API sources."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re

HASH = re.compile(r'[0-9a-f]{64}\Z')
LOCALES = {'zh-Hans', 'en', 'ko', 'es', 'vi'}


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def asset(public, name, expected=None):
    if not isinstance(name, str) or not name.startswith('/') or any(x in name.split('/') for x in ('.', '..')):
        raise ValueError('Unsafe public asset path')
    path = public / name.lstrip('/')
    if path.is_symlink() or not path.is_file() or public not in path.resolve().parents:
        raise ValueError('Public asset missing or outside root')
    if expected is not None and (not HASH.fullmatch(expected) or digest(path) != expected):
        raise ValueError('Published asset hash mismatch: ' + name)
    return path


def read(path):
    return json.loads(Path(path).read_text())


def key(row):
    return row['week'], row['trackId'], row['audioSha256']


def source(week, track_id, sha, duration, cues, page_id, locale):
    if locale not in LOCALES or not HASH.fullmatch(sha) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', week):
        raise ValueError('Invalid source locale or identity')
    previous = 0
    normalized = []
    for index, cue in enumerate(cues):
        start, end = cue['start'], cue['end']
        if not 0 <= previous <= start < end <= duration + .001:
            raise ValueError('Invalid published cue timing')
        block = cue.get('blockId')
        normalized.append(dict(id=str(index), start=start, end=end, blockId=str(block) if block is not None else None))
        previous = end
    if not normalized:
        raise ValueError('Published audio requires captions')
    return dict(week=week, trackId=track_id, audioSha256=sha, durationSeconds=duration,
                cueIds=[c['id'] for c in normalized], cues=normalized,
                blockIds=sorted({c['blockId'] for c in normalized if c['blockId'] is not None}),
                pageId=page_id, audioLocale=locale)


def build(public, previous_catalog, legacy_locale):
    public = Path(public).resolve()
    catalog = copy.deepcopy(previous_catalog)
    if catalog.get('schemaVersion') != 1 or not isinstance(catalog.get('sources'), list):
        raise ValueError('Expected existing feedback catalog v1')
    indexed = {key(s): s for s in catalog['sources']}
    if len(indexed) != len(catalog['sources']):
        raise ValueError('Duplicate existing API source')
    def add(row):
        old = indexed.get(key(row))
        if old:
            for field in ('week', 'trackId', 'audioSha256', 'durationSeconds', 'cueIds', 'blockIds', 'cues'):
                if old[field] != row[field]:
                    raise ValueError('Existing source identity or cue binding changed: ' + row['trackId'])
            for field in ('pageId', 'audioLocale'):
                if field in old and old[field] != row[field]:
                    raise ValueError('Existing locale metadata conflicts')
        indexed[key(row)] = row
    weekly = read(asset(public, '/weekly.json'))
    if weekly.get('schemaVersion') != 'sermon-weekly-catalog-v1' or legacy_locale not in LOCALES:
        raise ValueError('Explicit legacy locale and supported catalog required')
    for week in weekly['weeks']:
        for track in week['tracks']:
            asset(public, track['audioUrl'], track['sha256'])
            add(source(week.get('date', week['id']), track['id'], track['sha256'],
                       track['durationSeconds'], track['cues'], week['id'], legacy_locale))
    multilingual = read(asset(public, '/multilingual-v3.json'))
    if multilingual.get('schemaVersion') != 'sermon-multilingual-catalog-v3':
        raise ValueError('Expected multilingual catalog v3')
    for page in multilingual['pages']:
        for locale, target in page['targets'].items():
            if target.get('audioStatus') != 'human_reviewed':
                continue
            release = read(asset(public, target['releasePackageUrl'], target['releasePackageJsonSha256']))
            if (release.get('schemaVersion') != 'sermon-target-language-release-package-v2'
                    or release.get('status') != 'published_http_verified'
                    or release.get('pageId') != page['id'] or release.get('audioLocale') != locale
                    or release.get('targetLocale') != locale or release.get('contentLocale') != locale
                    or release.get('audioStatus') != 'human_reviewed' or release.get('contentStatus') != 'human_reviewed'):
                raise ValueError('Release is not a same-locale published reviewed package')
            assets = {a['role']: a for a in release['assets']}
            if len(assets) != len(release['assets']):
                raise ValueError('Duplicate release asset')
            verified = {role: asset(public, assets[role]['path'], assets[role]['sha256'])
                        for role in ('content', 'captions', 'audio')}
            content, captions = read(verified['content']), read(verified['captions'])
            if (content.get('pageId') != page['id'] or content.get('targetLocale') != locale
                    or content.get('status') != 'human_reviewed'
                    or content.get('englishSourcePackageJsonSha256') != page['sourceIdentitySha256']
                    or content.get('targetLanguageCandidateJsonSha256') != release['targetLanguageCandidateJsonSha256']):
                raise ValueError('Published content source mismatch')
            sha = assets['audio']['sha256']
            add(source(page['date'], f"{page['id']}-{locale}-{sha[:12]}", sha,
                       content['durationSeconds'], captions['cues'], page['id'], locale))
    catalog['sources'] = list(indexed.values())
    catalog['weekIds'] = sorted(set(catalog.get('weekIds', [])) | {s['week'] for s in indexed.values()})
    return catalog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--public', required=True, type=Path)
    parser.add_argument('--previous-catalog', required=True, type=Path)
    parser.add_argument('--legacy-locale', required=True, choices=sorted(LOCALES))
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    result = build(args.public, read(args.previous_catalog), args.legacy_locale)
    with args.out.open('x') as output:
        output.write(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'sources': len(result['sources']), 'localizedSources': sum('audioLocale' in s for s in result['sources']),
                      'catalogSha256': digest(args.out)}))


if __name__ == '__main__':
    main()
