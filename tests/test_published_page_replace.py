import hashlib
import json
from pathlib import Path

import pytest

from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.delivery import baseline as bl
from tongxing_production.delivery import contract
from tongxing_production.delivery.published_page_replace import finish_replace, replace_assets

PAGE = 'week'
LOCALE = 'ko'


def digest(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_snapshot(tmp_path: Path, *, content: bytes = b'{"pageId":"week","targetLocale":"ko"}') -> Path:
    """A minimal live snapshot: one page, one locale, one verified v2 release, seal report."""
    root = tmp_path / 'live'
    public = root / 'public'
    public.mkdir(parents=True)
    files = {
        f'content/{PAGE}/{LOCALE}.json': content,
        f'captions/{PAGE}/{LOCALE}.json': b'{"cues":[]}',
        f'media/{PAGE}/{LOCALE}.mp3': b'audio-bytes',
        f'pages/{PAGE}/{LOCALE}/index.html': b'<html></html>',
    }
    for rel, data in files.items():
        path = public / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    assets = [{'role': role, 'path': '/' + rel, 'sha256': digest(public / rel)}
              for role, rel in (('page', f'pages/{PAGE}/{LOCALE}/index.html'),
                                ('content', f'content/{PAGE}/{LOCALE}.json'),
                                ('audio', f'media/{PAGE}/{LOCALE}.mp3'),
                                ('captions', f'captions/{PAGE}/{LOCALE}.json'))]
    release = {
        'schemaVersion': 'sermon-target-language-release-package-v2', 'packageId': f'{PAGE}-{LOCALE}-v1',
        'pageId': PAGE, 'sourceLocale': 'en', 'targetLocale': LOCALE, 'interfaceLocale': LOCALE,
        'contentLocale': LOCALE, 'audioLocale': LOCALE,
        'targetLanguageCandidateJsonSha256': 'c' * 64, 'spokenTargetLanguageCandidateJsonSha256': 'c' * 64,
        'targetLanguageAudioPackageJsonSha256': 'd' * 64, 'status': 'published_http_verified',
        'contentStatus': 'human_reviewed', 'audioStatus': 'human_reviewed', 'assets': assets,
        'httpVerification': {'status': 'pass', 'evidenceSha256': 'e' * 64},
        'deviceAcceptance': {'status': 'not_run', 'evidenceSha256': None},
        'venueAcceptance': {'status': 'not_run', 'evidenceSha256': None}, 'issues': [],
    }
    data = (json.dumps(release, ensure_ascii=False, indent=1, sort_keys=True) + '\n').encode()
    (public / 'releases-v2' / PAGE / f'{LOCALE}.json').parent.mkdir(parents=True)
    (public / 'releases-v2' / PAGE / f'{LOCALE}.json').write_bytes(data)
    catalog = {
        'schemaVersion': 'sermon-multilingual-catalog-v3',
        'generatedAt': '2026-10-25T00:00:00Z',
        'defaultPageId': PAGE,
        'pages': [{'id': PAGE, 'date': '2026-10-25', 'title': 'Week', 'sourceLocale': 'en',
                   'sourceIdentitySha256': 'a' * 64, 'sourceMediaSha256': 'b' * 64,
                   'defaultTargetLocale': LOCALE,
                   'targets': {LOCALE: {'releasePackageUrl': f'/releases-v2/{PAGE}/{LOCALE}.json',
                                        'releasePackageJsonSha256': hashlib.sha256(data).hexdigest(),
                                        'contentStatus': 'human_reviewed', 'audioStatus': 'human_reviewed',
                                        'capabilities': ['text', 'captions', 'audio']}}}],
    }
    (public / 'multilingual-v3.json').write_text(json.dumps(catalog))
    (root / 'firebase.json').write_text('{"hosting": {}}')
    report = {**bl.catalog_report(public), 'files': bl.files_report(public)}
    (root / 'seal-report.json').write_text(json.dumps(report))
    return root


def replacement_release(root: Path, content: bytes, evidence_sha: str = 'f' * 64) -> bytes:
    """The release as it reads after the content bytes are replaced and verified."""
    release = json.loads((root / 'public/releases-v2' / PAGE / f'{LOCALE}.json').read_text())
    for asset in release['assets']:
        if asset['role'] == 'content':
            asset['sha256'] = hashlib.sha256(content).hexdigest()
    release['httpVerification'] = {'status': 'pass', 'evidenceSha256': evidence_sha}
    return (json.dumps(release, ensure_ascii=False, indent=1, sort_keys=True) + '\n').encode()


def test_live_snapshot_is_strictly_valid(tmp_path):
    contract.validate_catalog_snapshot(write_snapshot(tmp_path))


def test_replace_assets_is_pending_until_the_release_is_published(tmp_path):
    live = write_snapshot(tmp_path)
    changed = b'{"pageId":"week","targetLocale":"ko","text":"corrected"}'
    staged = tmp_path / 'stage-a'
    result = replace_assets(live, staged, PAGE, {f'content/{PAGE}/{LOCALE}.json': changed})
    assert result['pendingReplacements'] == [PAGE]
    assert (staged / 'public' / f'content/{PAGE}/{LOCALE}.json').read_bytes() == changed
    # The intermediate snapshot is deliberately inconsistent and only the named page is skipped.
    with pytest.raises(ValueError, match='Missing baseline release asset'):
        contract.validate_catalog_snapshot(staged)
    contract.validate_catalog_snapshot(staged, allow_pending_replacements=frozenset({PAGE}))
    with pytest.raises(ValueError, match='Missing baseline release asset'):
        contract.validate_catalog_snapshot(staged, allow_pending_replacements=frozenset({'other'}))


def test_finish_republishes_the_release_and_validates_strictly(tmp_path):
    live = write_snapshot(tmp_path)
    changed = b'{"pageId":"week","targetLocale":"ko","text":"corrected"}'
    staged = tmp_path / 'stage-a'
    replace_assets(live, staged, PAGE, {f'content/{PAGE}/{LOCALE}.json': changed})
    evidence = tmp_path / 'verify.json'
    evidence.write_text(json.dumps({'status': 'pass', 'checks': []}))
    evidence_sha = hashlib.sha256(evidence.read_bytes()).hexdigest()
    release_bytes = replacement_release(live, changed, evidence_sha)
    final = tmp_path / 'stage-b'
    result = finish_replace(staged, final, PAGE, {LOCALE: release_bytes}, evidence_sha)
    assert result['releases'] == [LOCALE]
    contract.validate_catalog_snapshot(final)
    catalog = json.loads((final / 'public/multilingual-v3.json').read_text())
    target = catalog['pages'][0]['targets'][LOCALE]
    assert target['releasePackageJsonSha256'] == hashlib.sha256(release_bytes).hexdigest()
    release = json.loads((final / 'public/releases-v2' / PAGE / f'{LOCALE}.json').read_text())
    content = next(asset for asset in release['assets'] if asset['role'] == 'content')
    assert content['sha256'] == hashlib.sha256(changed).hexdigest()
    # the pending marker is gone from the finished snapshot
    assert json.loads((final / 'staged-changes.json').read_text())['pendingReplacements'] == []


def test_replace_assets_refuses_new_paths_and_unknown_pages(tmp_path):
    live = write_snapshot(tmp_path)
    with pytest.raises(ValueError, match='existing published file'):
        replace_assets(live, tmp_path / 'a', PAGE, {f'content/{PAGE}/new.json': b'{}'})
    with pytest.raises(ValueError, match='exactly once'):
        replace_assets(live, tmp_path / 'b', 'missing', {f'content/{PAGE}/{LOCALE}.json': b'{}'})


def test_finish_requires_verified_releases(tmp_path):
    live = write_snapshot(tmp_path)
    staged = tmp_path / 'stage-a'
    changed = b'{"pageId":"week","targetLocale":"ko","text":"corrected"}'
    replace_assets(live, staged, PAGE, {f'content/{PAGE}/{LOCALE}.json': changed})
    release = json.loads(replacement_release(live, changed))
    release['httpVerification'] = {'status': 'not_run', 'evidenceSha256': None}
    data = (json.dumps(release, ensure_ascii=False, indent=1, sort_keys=True) + '\n').encode()
    with pytest.raises(ValueError, match='not http-verified'):
        finish_replace(staged, tmp_path / 'b', PAGE, {LOCALE: data}, 'f' * 64)
