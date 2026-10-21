#!/usr/bin/env python3
"""Bind analytics locales to verified published assets; retain prior API sources.

Reads the v5 multilingual catalog when published (including per-target source
editions), otherwise v4 and then its human-only v3 projection."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re

HASH = re.compile(r'[0-9a-f]{64}\Z')
LOCALES = {'zh-Hans', 'en', 'ko', 'es', 'vi'}
PLAYABLE = {'human_reviewed', 'machine_checked'}
# v2 and the four-product v3 are human-reviewed releases under /releases-v2/; v4 adds machine-checked ones.
RELEASES = {'sermon-target-language-release-package-v2', 'sermon-target-language-release-package-v3',
            'sermon-target-language-release-package-v4'}
CLOCKED_CONTENT = {'sermon-full-video-text-content-v2', 'sermon-full-video-text-content-v3'}


def track_duration(content):
    """The duration the clients send for this track: the dub's own clock when it has one."""
    separate = content.get('schemaVersion') in CLOCKED_CONTENT or 'audioDurationSeconds' in content
    return content['audioDurationSeconds'] if separate else content['durationSeconds']


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
    # v5 lists presentation families with target-bound source editions; v4/v3
    # remain the exact legacy fallback when v5 is absent.
    catalog_name = next((name for name in ('multilingual-v5.json', 'multilingual-v4.json', 'multilingual-v3.json')
                         if (public / name).is_file()), 'multilingual-v3.json')
    multilingual = read(asset(public, '/' + catalog_name))
    if multilingual.get('schemaVersion') not in {'sermon-multilingual-catalog-v3', 'sermon-multilingual-catalog-v4',
                                                  'sermon-multilingual-catalog-v5'}:
        raise ValueError('Expected multilingual catalog v3, v4 or v5')
    for page in multilingual['pages']:
        for locale, target in page['targets'].items():
            if target.get('audioStatus') not in PLAYABLE:
                continue
            per_target = multilingual['schemaVersion'] == 'sermon-multilingual-catalog-v5' and page.get('sourceMode') == 'per_target'
            edition = target.get('editionId') if per_target else page['id']
            source_identity = target.get('sourceIdentitySha256') if per_target else page['sourceIdentitySha256']
            source_media = target.get('sourceMediaSha256') if per_target else page.get('sourceMediaSha256')
            if per_target:
                video = target.get('videoDelivery')
                if (not isinstance(edition, str) or not HASH.fullmatch(source_identity or '')
                        or not HASH.fullmatch(source_media or '') or not isinstance(video, dict)
                        or video.get('canonicalUrl') != f'/pages/{edition}/full-video-browser.mp4'
                        or video.get('sha256') != source_media):
                    raise ValueError('Target source/video identity mismatch')
            release = read(asset(public, target['releasePackageUrl'], target['releasePackageJsonSha256']))
            machine = release.get('schemaVersion') == 'sermon-target-language-release-package-v4'
            expected_release = f"/releases-v{4 if machine else 2}/{edition}/{locale}.json"
            if (release.get('schemaVersion') not in RELEASES or release.get('status') != 'published_http_verified'
                    or (per_target and target.get('releasePackageUrl') != expected_release)
                    or release.get('pageId') != edition or release.get('audioLocale') != locale
                    or release.get('targetLocale') != locale or release.get('contentLocale') != locale
                    or release.get('audioStatus') != target['audioStatus']
                    or release.get('contentStatus') != target.get('contentStatus', 'human_reviewed')
                    or (not machine and (release['audioStatus'], release['contentStatus'])
                        != ('human_reviewed', 'human_reviewed'))
                    or (machine and (multilingual['schemaVersion'] not in {'sermon-multilingual-catalog-v4', 'sermon-multilingual-catalog-v5'}
                                     or not target['releasePackageUrl'].startswith('/releases-v4/')
                                     or release.get('englishSourcePackageJsonSha256') != source_identity
                                     or (per_target and release.get('sourceIdentity', {}).get('mediaSha256') != source_media)))):
                raise ValueError('Release is not a same-locale published package of its catalog status')
            assets = {a['role']: a for a in release['assets']}
            if len(assets) != len(release['assets']):
                raise ValueError('Duplicate release asset')
            verified = {role: asset(public, assets[role]['path'], assets[role]['sha256'])
                        for role in ('content', 'captions', 'audio')}
            if per_target:
                expected_assets = {'content': f'/content/{edition}/{locale}.json',
                                   'captions': f'/captions/{edition}/{locale}.json',
                                   'audio': f'/media/{edition}/{locale}.mp3'}
                if any(assets[role].get('path') != path for role, path in expected_assets.items()):
                    raise ValueError('Release assets differ from target edition')
            content, captions = read(verified['content']), read(verified['captions'])
            if (content.get('pageId') != edition or content.get('targetLocale') != locale
                    or content.get('status') != release['contentStatus']
                    or content.get('englishSourcePackageJsonSha256') != source_identity
                    or (per_target and content.get('sourceMediaSha256') != source_media)
                    or content.get('targetLanguageCandidateJsonSha256') != release['targetLanguageCandidateJsonSha256']):
                raise ValueError('Published content source mismatch')
            sha = assets['audio']['sha256']
            # The duration the clients report for this track, whatever the release version: a v2
            # podcast page (2026-10-02) also runs its dub on its own clock.
            add(source(page['date'], f"{page['id']}-{locale}-{sha[:12]}", sha, track_duration(content),
                       captions['cues'], page['id'], locale))
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
