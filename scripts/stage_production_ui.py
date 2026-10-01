#!/usr/bin/env python3
"""Stage and verify a UI-only overlay of the complete Production Hosting snapshot.

This tool never deploys. Catalogs, media, page readers, settings and the Hosting
configuration are preserved byte for byte; only the declared root UI can change.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

try:
    from scripts import assemble_multilingual_hosting as hosting
    from scripts import verify_multilingual_hosting as http
except ImportError:
    import assemble_multilingual_hosting as hosting
    import verify_multilingual_hosting as http

ROOT = Path(__file__).resolve().parents[1]
PROJECT = 'ai-for-god-caption-dev'
SITE = 'ai-for-god-sermon-audio'
ORIGIN = f'https://{SITE}.web.app'
SCHEMA = 'sermon-production-ui-overlay-v1'
UI_FILES = ('index.html', 'style.css', 'app.mjs', 'fingerprint-ui.mjs', 'theme.js',
            'locales-app.mjs', 'locales-interface.mjs', 'locales-ko.mjs', 'locales-es.mjs',
            'icons.svg', 'icons.mjs', 'brand-icon.svg', 'brand-icon-light.svg')
# Every deployable UI file must come from the selected release checkout.
DIRECT_SOURCE_FILES = UI_FILES


def require(ok, message):
    if not ok:
        raise ValueError(message)


def inventory(public: Path) -> list[dict]:
    return [{'path': name, 'sha256': hosting.digest(path), 'bytes': path.stat().st_size}
            for name, path in sorted(hosting.regular_files(public).items())]


def regular_file(path: Path):
    require(path.is_file() and not path.is_symlink(), f'Expected regular file: {path}')
    return path


def validate_config(config: dict, public: Path):
    site = config.get('hosting', {})
    require(isinstance(site, dict) and site.get('public') == 'public'
            and site.get('site') == SITE and 'target' not in site,
            'Production Hosting destination changed')
    require({'source': '/api/**', 'function': {
        'functionId': 'sermon-feedback-api', 'region': 'us-west1'}}
        in site.get('rewrites', []), 'Production API route changed')
    # The existing source-video redirect is part of content delivery, not UI.
    catalog = public / 'multilingual-v3.json'
    if catalog.is_file():
        for page in hosting.load(catalog).get('pages', []):
            video = page.get('videoDelivery')
            if video:
                require({'source': video['canonicalUrl'], 'destination': video['storageUrl'],
                         'type': 302} in site.get('redirects', []),
                        'Production video redirect differs from catalog')


def source_commit(root: Path) -> str:
    return subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'],
                                   text=True).strip()


def source_directory(root: Path) -> Path:
    source = root / 'experiments/sermon-dubbing-poc/web'
    require(all(path.is_dir() and not path.is_symlink() for path in
                (root, root / 'experiments', root / 'experiments/sermon-dubbing-poc', source)),
            'Linked or missing UI source directory')
    return source


def checked_inputs(base: Path, overlay: Path):
    require(not base.is_symlink() and not overlay.is_symlink(), 'Linked input directory')
    before, proposed = inventory(base / 'public'), inventory(overlay / 'public')
    before_map = {item['path']: item for item in before}
    proposed_map = {item['path']: item for item in proposed}
    require(set(before_map).issubset(proposed_map), 'Overlay removed a baseline file')
    require(set(UI_FILES).issubset(proposed_map), 'Overlay lacks a required UI file')
    added = set(proposed_map) - set(before_map)
    modified = {name for name in before_map if before_map[name] != proposed_map[name]}
    require((added | modified).issubset(UI_FILES), 'Overlay changed non-UI Production files')
    regular_file(base / 'firebase.json')
    regular_file(overlay / 'firebase.json')
    require(hosting.digest(base / 'firebase.json') == hosting.digest(overlay / 'firebase.json'),
            'Overlay changed Firebase configuration')
    validate_config(hosting.load(base / 'firebase.json'), base / 'public')
    return before, proposed, sorted(modified), sorted(added)


def stage(base: Path, overlay: Path, out: Path, *, source_root: Path = ROOT) -> dict:
    base, overlay, out, source_root = map(Path, (base, overlay, out, source_root))
    require(not out.exists() and not out.is_symlink(), 'Use a new candidate directory')
    require(not out.resolve().is_relative_to(base.resolve())
            and not out.resolve().is_relative_to(overlay.resolve()),
            'Candidate must be outside its inputs')
    before, proposed, modified, added = checked_inputs(base, overlay)
    source = source_directory(source_root)
    source_files = []
    for name in DIRECT_SOURCE_FILES:
        path = regular_file(source / name)
        require(hosting.digest(path) == hosting.digest(overlay / 'public' / name),
                f'Overlay UI differs from checked-in source: {name}')
        source_files.append({'path': name, 'sha256': hosting.digest(path), 'bytes': path.stat().st_size})
    commit = source_commit(source_root)
    require(bool(re.fullmatch(r'[a-f0-9]{40,64}', commit)), 'Invalid source code commit')
    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f'.{out.name}-', dir=out.parent))
    try:
        shutil.copytree(base / 'public', temporary / 'public')
        for name in UI_FILES:
            shutil.copyfile(overlay / 'public' / name, temporary / 'public' / name)
        shutil.copyfile(base / 'firebase.json', temporary / 'firebase.json')
        files = inventory(temporary / 'public')
        require(files == proposed, 'Candidate copy differs from selected overlay')
        report = {'schemaVersion': SCHEMA, 'status': 'validated_not_deployed',
                  'projectId': PROJECT, 'siteId': SITE, 'origin': ORIGIN,
                  'createdAt': datetime.now(timezone.utc).isoformat(),
                  'basePath': str(base.resolve()), 'overlayPath': str(overlay.resolve()),
                  'sourceRoot': str(source_root.resolve()), 'sourceCodeCommit': commit,
                  'sourceFiles': source_files, 'baseFiles': before,
                  'overlayFiles': [item for item in proposed if item['path'] in UI_FILES],
                  'files': files, 'modifiedFiles': modified, 'addedFiles': added,
                  'totalBytes': sum(item['bytes'] for item in files),
                  'firebaseConfigSha256': hosting.digest(temporary / 'firebase.json'),
                  'feedbackDeploymentStatus': 'unchanged',
                  'deviceAcceptance': 'not_run', 'venueAcceptance': 'not_run'}
        (temporary / 'build-report.json').write_text(
            json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + '\n')
        verify_candidate(temporary)
        temporary.rename(out)
        return report
    except Exception:
        shutil.rmtree(temporary)
        raise


def verify_candidate(candidate: Path) -> dict:
    candidate = Path(candidate)
    require(not candidate.is_symlink(), 'Linked candidate directory')
    regular_file(candidate / 'build-report.json')
    report = hosting.load(candidate / 'build-report.json')
    require(report.get('schemaVersion') == SCHEMA and report.get('status') == 'validated_not_deployed'
            and report.get('projectId') == PROJECT and report.get('siteId') == SITE
            and report.get('origin') == ORIGIN, 'Invalid Production UI candidate')
    require(bool(re.fullmatch(r'[a-f0-9]{40,64}', report.get('sourceCodeCommit', ''))),
            'Invalid source code commit')
    before, proposed, modified, added = checked_inputs(Path(report['basePath']), Path(report['overlayPath']))
    require(before == report['baseFiles'], 'Production baseline changed')
    require([item for item in proposed if item['path'] in UI_FILES] == report['overlayFiles'],
            'Selected overlay UI changed')
    require(modified == report['modifiedFiles'] and added == report['addedFiles'],
            'Overlay change manifest differs')
    actual = inventory(candidate / 'public')
    require(actual == report['files'] == proposed
            and report['totalBytes'] == sum(item['bytes'] for item in actual),
            'Candidate files changed')
    regular_file(candidate / 'firebase.json')
    config_sha = report['firebaseConfigSha256']
    require(hosting.digest(candidate / 'firebase.json') == config_sha
            == hosting.digest(Path(report['basePath']) / 'firebase.json'),
            'Candidate Firebase configuration changed')
    source = source_directory(Path(report['sourceRoot']))
    require([item['path'] for item in report['sourceFiles']] == list(DIRECT_SOURCE_FILES),
            'UI source manifest incomplete')
    for item in report['sourceFiles']:
        path = regular_file(source / item['path'])
        require(hosting.digest(path) == item['sha256'] and path.stat().st_size == item['bytes']
                and hosting.digest(candidate / 'public' / item['path']) == item['sha256'],
                f'UI source changed: {item["path"]}')
    validate_config(hosting.load(candidate / 'firebase.json'), candidate / 'public')
    return report


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def check_http(candidate: Path, *, baseline: bool, workers: int = 4,
               opener=urlopen, redirect_opener=None) -> dict:
    candidate = Path(candidate)
    report = verify_candidate(candidate)
    expected = report['baseFiles'] if baseline else report['files']
    public = Path(report['basePath']) / 'public' if baseline else candidate / 'public'
    def check(item):
        path = '/' + item['path']
        status, headers, size, digest = http.request_file(ORIGIN, path, opener=opener)
        require(status == 200 and size == item['bytes'] and digest == item['sha256'],
                f'Production file changed: {path}')
        mime = headers.get('content-type', '').split(';')[0].lower()
        if item['path'].endswith('.svg'):
            require(mime == 'image/svg+xml', f'Unexpected SVG Content-Type: {path}')
        result = {'path': path, 'sha256': digest, 'bytes': size, 'contentType': mime}
        if item['path'].lower().endswith(('.mp3', '.wav', '.m4a')):
            range_status, range_headers, range_size, range_sha = http.request_file(
                ORIGIN, path, opener=opener, request_headers={'Range': 'bytes=0-0'})
            with (public / item['path']).open('rb') as stream:
                first = stream.read(1)
            partial = (range_status == 206 and range_size == 1
                       and range_sha == hashlib.sha256(first).hexdigest()
                       and range_headers.get('content-range') == f'bytes 0-0/{item["bytes"]}')
            full = (range_status == 200 and range_size == item['bytes']
                    and range_sha == item['sha256'] and 'content-range' not in range_headers)
            require(partial or full, f'Audio Range check failed: {path}')
            result.update(range206=partial, fullBodyFallback=full)
        return result
    results = http.ordered_checks(expected, check, workers)
    redirect_open = redirect_opener or build_opener(NoRedirect).open
    redirects = hosting.load(candidate / 'firebase.json')['hosting'].get('redirects', [])
    for redirect in redirects:
        request = Request(ORIGIN + redirect['source'], method='GET')
        try:
            response = redirect_open(request, timeout=30)
        except HTTPError as error:
            response = error
        with response:
            require(response.code == redirect['type']
                    and response.headers.get('Location') == redirect['destination'],
                    f'Production video redirect changed: {redirect["source"]}')
        results.append({'path': redirect['source'], 'status': redirect['type'],
                        'redirect': redirect['destination']})
    return {'schemaVersion': 'sermon-production-ui-http-v1', 'status': 'pass', 'origin': ORIGIN,
            'phase': 'baseline' if baseline else 'published',
            'checkedAt': datetime.now(timezone.utc).isoformat(),
            'buildReportSha256': hosting.digest(candidate / 'build-report.json'),
            'checkedFiles': len(expected), 'results': results,
            'deviceAcceptance': 'not_run', 'venueAcceptance': 'not_run'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('stage')
    create.add_argument('--base', type=Path, required=True)
    create.add_argument('--overlay', type=Path, required=True)
    create.add_argument('--out', type=Path, required=True)
    for name in ('preflight', 'verify'):
        check = commands.add_parser(name)
        check.add_argument('--candidate', type=Path, required=True)
        check.add_argument('--out', type=Path, required=True)
        check.add_argument('--http-workers', type=int, default=4)
    args = parser.parse_args()
    if args.command == 'stage':
        report = stage(args.base, args.overlay, args.out)
    else:
        require(not args.out.exists() and not args.out.is_symlink(), 'Use a new HTTP receipt path')
        report = check_http(args.candidate, baseline=args.command == 'preflight', workers=args.http_workers)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + '\n')
    print(json.dumps({'status': report['status'], 'schemaVersion': report['schemaVersion']}))


if __name__ == '__main__':
    main()
