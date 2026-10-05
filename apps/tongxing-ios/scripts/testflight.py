#!/usr/bin/env python3
"""Configure local API-key metadata and run scoped Beta fastlane lanes."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import uuid
import zipfile
import fcntl

MODULE = Path(__file__).resolve().parents[1]
REPO = MODULE.parents[1]
DEFAULT_CONFIG = Path.home() / 'Library/Application Support/TongxingRelease/api-key.json'
BUNDLE = 'com.jonathanjing.tongxing.beta'


def in_git_worktree(path):
    directory = path if path.is_dir() else path.parent
    while not directory.exists():
        directory = directory.parent
    result = subprocess.run(['git', '-C', str(directory), 'rev-parse', '--is-inside-work-tree'],
                            capture_output=True, text=True)
    return result.returncode == 0 and result.stdout.strip() == 'true'


def private_file(path):
    path = path.expanduser().resolve(strict=True)
    if in_git_worktree(path):
        raise ValueError('API credentials must be outside this repository and any other Git worktree')
    if not path.is_file() or path.stat().st_mode & 0o077:
        raise ValueError('API credential file must be a regular file with mode 600')
    return path


def archive_digest(archive):
    entries = []
    for path in sorted(archive.rglob('*')):
        entry = {'path': path.relative_to(archive).as_posix()}
        if path.is_symlink():
            entry.update(kind='symlink', target=os.readlink(path))
        elif path.is_file():
            digest = hashlib.sha256()
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(block)
            entry.update(kind='file', sha256=digest.hexdigest())
        else:
            continue
        entries.append(entry)
    return hashlib.sha256(json.dumps(entries, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode()).hexdigest()


def validate_candidate(record_path, ipa=None):
    record = json.loads(record_path.read_text())
    if (record.get('schemaVersion'), record.get('channel'), record.get('bundleID'),
        record.get('status')) != (1, 'beta', BUNDLE, 'archive_succeeded'):
        raise ValueError('Requires a successful canonical Beta archive record')
    if not re.fullmatch(r'[0-9]+(?:\.[0-9]+){2}', record['version']) or not re.fullmatch(r'[0-9]+', record['build']):
        raise ValueError('Invalid candidate version/build')
    archive = Path(record['archivePath']).resolve(strict=True)
    if archive_digest(archive) != record['archiveManifestSHA256']:
        raise ValueError('Archive hash no longer matches its frozen record')
    if ipa:
        with zipfile.ZipFile(ipa) as package:
            names = package.namelist()
            apps = [n for n in names if n.startswith('Payload/') and n.count('/') == 2
                    and n.endswith('.app/Info.plist')]
            if len(apps) != 1:
                raise ValueError('IPA must contain exactly one app')
            app = plistlib.loads(package.read(apps[0]))
            root = apps[0].removesuffix('Info.plist')
            extensions = [n for n in names if n.startswith(root + 'PlugIns/')
                          and n.endswith('.appex/Info.plist') and n.count('/') == 4]
            if len(extensions) != 1:
                raise ValueError('IPA must contain exactly one activity extension')
            for name, expected_id in [(apps[0], BUNDLE), (extensions[0], BUNDLE + '.listening-activity')]:
                info = plistlib.loads(package.read(name))
                actual = tuple(str(info.get(k)) for k in ['CFBundleIdentifier', 'CFBundleShortVersionString', 'CFBundleVersion'])
                if actual != (expected_id, record['version'], record['build']):
                    raise ValueError('IPA identity/version/build differs from archive record')
            if app.get('TongxingContentOrigin') != record['contentOrigin']:
                raise ValueError('IPA content origin differs from archive record')
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['configure', 'status', 'upload', 'wait', 'distribute'])
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    parser.add_argument('--key-file', type=Path)
    parser.add_argument('--key-id')
    parser.add_argument('--issuer-id')
    parser.add_argument('--record', type=Path)
    parser.add_argument('--ipa', type=Path)
    parser.add_argument('--notes', type=Path)
    parser.add_argument('--group', default='Rooted')
    parser.add_argument('--retry-upload', action='store_true', help='Only after explicitly reconciling a prior unknown upload with Apple')
    parser.add_argument('--wait-seconds', type=int, default=900)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.wait_seconds <= 900:
        parser.error('--wait-seconds must be between 1 and 900')
    if args.retry_upload and args.action != 'upload':
        parser.error('--retry-upload is only valid for upload')
    record = None
    config_path = args.config.expanduser().resolve()
    if args.action == 'configure':
        if not all([args.key_file, args.key_id, args.issuer_id]):
            parser.error('configure requires --key-file, --key-id and --issuer-id')
        key_file = private_file(args.key_file)
        if in_git_worktree(config_path):
            raise ValueError('Configuration must be outside this repository and any other Git worktree')
        if config_path.exists():
            raise ValueError('Configuration already exists; preserve it or select --config explicitly')
        if args.dry_run:
            print('Configuration preflight passed; no credentials written')
            return
        config_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(config_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w') as stream:
            json.dump({'key_id': args.key_id, 'issuer_id': args.issuer_id,
                       'key_filepath': str(key_file)}, stream, indent=2)
            stream.write('\n')
        print('Private API-key metadata configured; no authentication request made')
        return
    if args.action in ['upload', 'wait', 'distribute']:
        if not args.record:
            parser.error('upload/wait/distribute requires --record')
        if args.action == 'upload' and not args.ipa:
            parser.error('upload requires --ipa')
        if args.action == 'distribute' and not args.notes:
            parser.error('distribute requires --notes')
        record = validate_candidate(args.record.resolve(), args.ipa.resolve() if args.ipa else None)
        if args.notes and not args.notes.read_text().strip():
            raise ValueError('What to Test is empty')
    if args.dry_run:
        print(f'Preflight passed: fastlane beta_{args.action}; no Apple requests made')
        return
    config_path = private_file(config_path)
    config = json.loads(config_path.read_text())
    private_file(Path(config['key_filepath']))
    if not config.get('key_id') or not config.get('issuer_id'):
        raise ValueError('API-key metadata is incomplete')
    if not shutil.which('fastlane'):
        raise ValueError('Install fastlane first: brew install fastlane')
    run_dir = REPO / 'artifacts/tongxing-ios/testflight' / (datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8])
    run_dir.mkdir(parents=True, mode=0o700)
    env = dict(os.environ, FASTLANE_SKIP_UPDATE_CHECK='1', FASTLANE_HIDE_CHANGELOG='1',
               FASTLANE_SKIP_DOCS='1', FASTLANE_OPT_OUT_USAGE='1',
               TONGXING_ASC_CONFIG=str(config_path),
               TONGXING_ASC_SNAPSHOT=str(run_dir / 'apple-state.json'))
    for option, variable in [('record', 'TONGXING_RELEASE_RECORD'), ('ipa', 'TONGXING_BETA_IPA'), ('notes', 'TONGXING_BETA_NOTES')]:
        value = getattr(args, option)
        if value:
            env[variable] = str(value.resolve())
    env['TONGXING_BETA_GROUP'] = args.group
    env['TONGXING_WAIT_SECONDS'] = str(args.wait_seconds)
    ipa_sha = None
    if args.ipa:
        with args.ipa.open('rb') as stream:
            digest = hashlib.sha256()
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
            ipa_sha = digest.hexdigest()
    # A shared lock coordinates mutations across worktrees using this credential config.
    with config_path.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == 'upload':
            intent_path = config_path.parent / 'upload-intents' / f'{BUNDLE}-{record["version"]}-{record["build"]}.json'
            intent_path.parent.mkdir(exist_ok=True, mode=0o700)
            if intent_path.exists():
                prior = json.loads(intent_path.read_text())
                if prior['ipaSHA256'] != ipa_sha or prior['archiveManifestSHA256'] != record['archiveManifestSHA256']:
                    raise ValueError('Prior upload intent uses a different IPA or archive; do not reuse this version/build')
                if not args.retry_upload:
                    raise ValueError('Prior upload attempt exists. Use status/wait to reconcile Apple; --retry-upload requires an explicit confirmed retry decision')
            intent = {k: record[k] for k in ['bundleID', 'version', 'build', 'sourceCommit', 'archiveManifestSHA256']}
            intent.update(phase='preflight_started', ipaSHA256=ipa_sha, evidenceDir=str(run_dir))
            (run_dir / 'upload-intent.json').write_text(json.dumps(intent, indent=2) + '\n')
            temp_intent = intent_path.with_suffix('.tmp')
            temp_intent.write_text(json.dumps(intent, indent=2) + '\n')
            temp_intent.chmod(0o600)
            temp_intent.replace(intent_path)
            env['TONGXING_UPLOAD_INTENT'] = str(intent_path)
        with (run_dir / 'fastlane.log').open('w') as log:
            result = subprocess.run(['fastlane', f'beta_{args.action}'], cwd=MODULE, env=env,
                                    stdout=log, stderr=subprocess.STDOUT)
    receipt = {'action': args.action, 'exitCode': result.returncode,
               'status': 'command_succeeded' if result.returncode == 0 else 'command_failed',
               'record': str(args.record.resolve()) if args.record else None,
               'ipaSHA256': ipa_sha}
    if record:
        receipt['candidate'] = {k: record[k] for k in ['bundleID', 'version', 'build', 'sourceCommit', 'archiveManifestSHA256']}
    if args.action == 'distribute':
        receipt.update(group=args.group, notesSHA256=hashlib.sha256(args.notes.read_bytes()).hexdigest())
    (run_dir / 'command-result.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(f'fastlane exit {result.returncode}; private evidence: {run_dir}')
    if result.returncode:
        print('Check the private fastlane.log; reconcile Apple state before retrying an upload')
    return result.returncode


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, OSError, KeyError, zipfile.BadZipFile, plistlib.InvalidFileException) as error:
        # Never print parsed config values, JWTs, private keys or raw Apple responses.
        print(f'Error: {error}', file=sys.stderr)
        sys.exit(1)
