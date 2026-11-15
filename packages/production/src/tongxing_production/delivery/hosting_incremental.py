"""Incremental Hosting publication: clone the live version and upload only changed files.

``firebase deploy`` re-hashes and re-uploads the whole snapshot in one node process, with 200
concurrent uploads by default. On the 2026-11-15 snapshot (2.9 GB, 480 files, largest file
88 MB) that node process was charged about 305 GB of resident pages, macOS jetsam killed 1085
processes, and the operator saw the "out of application memory" dialog; the same signature
had already killed the 11-14 deploy. Cloning the live version and uploading only the files
whose gzip-encoded hash changed moves 163 MB instead of 2.9 GB for the same page.

The API hashes the *gzip-encoded* body the CLI uploads, not the raw file, so every digest here
is taken from ``gzip.compress`` with the same fixed mtime. Files are gzipped one at a time and
the payload is dropped after hashing: a ``dict`` of every payload would hold the whole site in
memory and bring the blow-up back.

``plan`` is read-only; ``deploy`` performs the clone, populate, upload, finalize and release and
returns the receipt the caller persists. Anything the snapshot cannot express incrementally
(no cloneable baseline, files removed from the site, a public directory without files) raises
``NotIncremental`` before the caller records an attempt, so the caller can fall back to the CLI
with the reason recorded instead of leaving an unknown deployment behind.
"""
from __future__ import annotations

import datetime
import gzip
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import quote

API = 'https://firebasehosting.googleapis.com/v1beta1'
METHOD = 'hosting_incremental_v1'
RECEIPT_SCHEMA = 'sermon-hosting-incremental-publish-v1'
SKIP_NAMES = {'.firebase', '.DS_Store'}
UPLOAD_TIMEOUT = 600
OPERATION_TIMEOUT = 600


class NotIncremental(ValueError):
    """The snapshot cannot be published by cloning the live version; use the CLI instead."""


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def ignore_matcher(patterns):
    """Match the `hosting.ignore` globs the CLI honours, so both routes serve the same files."""
    rules = []
    for pattern in patterns or ():
        regex, index = '', 0
        while index < len(pattern):
            if pattern.startswith('**/', index):
                regex += '(?:.*/)?'; index += 3
            elif pattern.startswith('**', index):
                regex += '.*'; index += 2
            elif pattern[index] == '*':
                regex += '[^/]*'; index += 1
            elif pattern[index] == '?':
                regex += '[^/]'; index += 1
            else:
                regex += re.escape(pattern[index]); index += 1
        rules.append(re.compile('^' + regex + '$'))
    return lambda path: any(rule.match(path) for rule in rules)


def local_files(public, ignore=()):
    """Every served path in ``public``, keyed by its absolute Hosting path."""
    public = Path(public)
    ignored = ignore_matcher(ignore)
    files = {}
    for path in sorted(public.rglob('*')):
        if not path.is_file():
            continue
        relative = path.relative_to(public)
        if any(part in SKIP_NAMES or part.startswith('.') for part in relative.parts):
            continue
        if ignored(relative.as_posix()):
            continue
        files['/' + relative.as_posix()] = path
    return files


def digest(path):
    """The Hosting file hash: sha256 of the gzip body the CLI would upload."""
    return hashlib.sha256(gzip.compress(Path(path).read_bytes(), mtime=0)).hexdigest()


def encoded_payload(path):
    return gzip.compress(Path(path).read_bytes(), mtime=0)


def remote_files(request, site, version):
    """The path -> hash listing of a version, read page by page.

    ``version`` may be a resource name (``sites/<site>/versions/<id>``); the listing endpoint
    addresses the bare version id.
    """
    version = version.rsplit('/', 1)[-1]
    files, token = {}, None
    while True:
        url = f'{API}/sites/{quote(site, safe="")}/versions/{quote(version, safe="")}/files?pageSize=1000'
        if token:
            url += '&pageToken=' + quote(token, safe='')
        body = request('GET', url)
        for row in body.get('files') or []:
            files[row['path']] = row['hash']
        token = body.get('nextPageToken')
        if not token:
            return files


def plan(request, *, site, public, baseline_version, ignore=()):
    """Read-only plan: the baseline version, the changed files and their bytes.

    Raises ``NotIncremental`` when the snapshot cannot be published by cloning: no baseline
    version, no served files, or files the live version has and this snapshot drops.
    """
    if not baseline_version:
        raise NotIncremental('no live version to clone')
    local = local_files(public, ignore)
    if not local:
        raise NotIncremental('the snapshot has no served files')
    try:
        remote = remote_files(request, site, baseline_version)
    except ValueError as error:
        raise NotIncremental(f'the live version cannot be listed: {error}') from error
    if not remote:
        raise NotIncremental('the live version lists no files to clone')
    digests = {path: digest(file) for path, file in local.items()}
    changed = sorted(path for path, value in digests.items() if remote.get(path) != value)
    removed = sorted(path for path in remote if path not in digests and not path.startswith('/__/'))
    if removed:
        raise NotIncremental('the snapshot removes published files: ' + ', '.join(removed[:5]))
    return {'site': site, 'baselineVersion': baseline_version, 'localFiles': len(local),
            'remoteFiles': len(remote), 'changed': changed,
            'changedBytes': sum(local[path].stat().st_size for path in changed),
            'digests': digests, 'paths': local, 'startedAt': now()}


def _poll(request, name, timeout=OPERATION_TIMEOUT):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = request('GET', f'{API}/{name}')
        if body.get('done'):
            if body.get('error'):
                raise ValueError('Hosting operation failed: ' + json.dumps(body['error'])[:300])
            return body.get('response') or {}
        time.sleep(2)
    raise ValueError('Hosting operation did not finish in time')


def _json_body(value):
    return json.dumps(value).encode()


def deploy(request, *, plan, out, release=True):
    """Clone, populate, upload the changed files, finalize, release, and write the receipt.

    The caller has already verified that the live version is ``plan['baselineVersion']``; the
    clone is pinned to that exact version, so a concurrent publisher changing the live head is
    caught by the readback rather than silently overwritten here.
    """
    site = plan['site']
    receipt = {'schemaVersion': RECEIPT_SCHEMA, 'site': site, 'baselineVersion': plan['baselineVersion'],
               'method': METHOD, 'localFiles': plan['localFiles'], 'remoteFiles': plan['remoteFiles'],
               'changed': plan['changed'], 'changedBytes': plan['changedBytes'], 'startedAt': now()}
    operation = request('POST', f'{API}/sites/{quote(site, safe="")}/versions:clone',
                        data=_json_body({'sourceVersion': plan['baselineVersion'], 'finalize': False}),
                        headers={'Content-Type': 'application/json'})
    version = _poll(request, operation['name']).get('name', '')
    if not version.startswith(f'sites/{site}/versions/'):
        raise ValueError('Hosting clone returned no version')
    receipt['clonedVersion'] = version
    uploaded = []
    if plan['changed']:
        populated = request('POST', f'{API}/{version}:populateFiles',
                            data=_json_body({'files': {path: plan['digests'][path] for path in plan['changed']}}),
                            headers={'Content-Type': 'application/json'})
        by_hash = {plan['digests'][path]: path for path in plan['changed']}
        upload_url = str(populated['uploadUrl']).rstrip('/')
        for value in populated.get('uploadRequiredHashes') or []:
            path = by_hash.get(value)
            if path is None:
                raise ValueError('Hosting asked for a hash this snapshot does not produce')
            payload = encoded_payload(plan['paths'][path])
            request('POST', f'{upload_url}/{value}', data=payload,
                    headers={'Content-Type': 'application/octet-stream'}, timeout=UPLOAD_TIMEOUT)
            uploaded.append({'path': path, 'encodedBytes': len(payload),
                             'rawBytes': plan['paths'][path].stat().st_size})
    receipt['uploaded'] = uploaded
    request('PATCH', f'{API}/{version}?updateMask=status', data=_json_body({'status': 'FINALIZED'}),
            headers={'Content-Type': 'application/json'})
    receipt['release'] = None
    if release:
        released = request('POST', f'{API}/sites/{quote(site, safe="")}/releases?versionName=' + quote(version, safe=''))
        receipt['release'] = {'name': released.get('name'), 'version': (released.get('version') or {}).get('name')}
    receipt['finishedAt'] = now()
    Path(out).write_text(json.dumps(receipt, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    return receipt


def receipt_version(path, *, site, baseline_version):
    """The deployed version named by an incremental receipt, validated against the attempt."""
    try:
        receipt = json.loads(Path(path).read_text())
    except (OSError, ValueError) as error:
        raise ValueError('Incremental deployment receipt unavailable; explicit reconciliation required') from error
    prefix = f'sites/{site}/versions/'
    version = receipt.get('clonedVersion') if isinstance(receipt, dict) else None
    valid = (receipt.get('schemaVersion') == RECEIPT_SCHEMA and receipt.get('site') == site
             and isinstance(version, str) and version.startswith(prefix)
             and bool(version[len(prefix):]) and '/' not in version[len(prefix):]
             and version != baseline_version
             and (receipt.get('release') or {}).get('version') == version)
    if not valid:
        raise ValueError('Incremental deployment receipt differs from intended site, baseline or release')
    return version
