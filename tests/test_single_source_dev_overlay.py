"""Offline preparation checks; no Hosting or deployment operations."""
import copy
import hashlib

import pytest
from scripts import tongxing_host  # noqa: F401
from tongxing_production.delivery import baseline, contract
from tongxing_production.delivery import single_source_dev_overlay as overlay


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write(path, obj):
    baseline.write(path, obj)
    return path.read_bytes()


def make_page(public, name):
    locale = 'zh-Hans'
    source, media = 'a' * 64, 'b' * 64
    assets = []
    for role in ('page', 'content', 'audio', 'captions', 'outline', 'meditation', 'product_manifest'):
        path = f'/{role}/{name}/{locale}.json'
        file = public / path.lstrip('/')
        file.parent.mkdir(parents=True, exist_ok=True)
        if role == 'content':
            data = write(file, {'pageId': name, 'targetLocale': locale,
                                'englishSourcePackageJsonSha256': source, 'sourceMediaSha256': media,
                                'cues': [{'textGroupId': 'group1', 'sourceUnitIds': ['unit1']}]})
        elif role == 'captions':
            data = write(file, {'cues': [{'textGroupId': 'group1', 'sourceUnitIds': ['unit1']}]})
        else:
            data = (role + name).encode(); file.write_bytes(data)
        assets.append({'role': role, 'path': path, 'sha256': digest(data)})
    release = {'schemaVersion': contract.RELEASE_V3, 'pageId': name, 'targetLocale': locale,
               'englishSourcePackageJsonSha256': source, 'sourceIdentity': {'mediaSha256': media},
               'assets': assets}
    release_path = f'/releases-v2/{name}/{locale}.json'
    raw = write(public / release_path.lstrip('/'), release)
    return {'id': name, 'date': '2026-10-25', 'title': name, 'sourceLocale': 'en',
            'sourceMode': 'single_source', 'sourceIdentitySha256': source, 'sourceMediaSha256': media,
            'defaultTargetLocale': locale, 'targets': {locale: {'releasePackageUrl': release_path,
            'releasePackageJsonSha256': digest(raw), 'contentStatus': 'human_reviewed',
            'audioStatus': 'human_reviewed', 'capabilities': ['text', 'captions', 'audio']}}}


def make_snapshot(root, name, *, dev):
    public = root / 'public'; public.mkdir(parents=True)
    page = make_page(public, name)
    v5 = {'schemaVersion': contract.CATALOG_V5, 'generatedAt': '2026-10-25T00:00:00Z',
          'defaultPageId': name, 'pages': [page]}
    v4 = contract.project_legacy_catalog_v4(v5)
    v3 = contract.project_human_catalog(v4)
    for version, value in ((contract.CATALOG_V5, v5), (contract.CATALOG_V4, v4), (contract.CATALOG_V3, v3)):
        write(public / contract.CATALOG_FILES[version], value)
    target = baseline.hosting_target('dev' if dev else 'production')
    write(root / 'firebase.json', {'hosting': {'site': target['site'], 'public': 'public'}})
    report = {**baseline.catalog_report(public), 'files': baseline.files_report(public)}
    write(root / 'seal-report.json', report)
    rows = [{'path': '/' + row['path'].lstrip('/'), 'rawSha256': row['sha256'],
             'rawBytes': row['bytes'], 'managed': False} for row in report['files']]
    rows.append({'path': '/__/firebase/init.js', 'rawSha256': digest(b'managed'),
                 'rawBytes': len(b'managed'), 'managed': True})
    write(root / 'baseline-receipt.json', {'status': 'complete_verified_not_deployed',
          'baselineVersion': 'sites/test/versions/initial', 'rows': rows,
          'catalogSha256': report['catalogSha256'], 'firebaseJsonSha256': baseline.digest(root / 'firebase.json'),
          **{k: target[k] for k in ('project', 'site', 'origin')}})
    return page


@pytest.fixture
def snapshots(tmp_path, monkeypatch):
    base, source = tmp_path / 'base', tmp_path / 'source'
    old = make_snapshot(base, 'existing', dev=True)
    incoming = make_snapshot(source, 'incoming', dev=False)
    # Asset and join checks below run for real; complete Hosting schema/snapshot
    # validation is covered by the contract's own tests.
    monkeypatch.setattr(contract, 'validate_catalog_snapshot', lambda root: None)
    monkeypatch.setattr(contract, 'validate_release_schema', lambda release: None)
    return base, source, old, incoming


def test_import_preserves_dev_catalog_entries_defaults_and_bytes(snapshots, tmp_path):
    base, source, old, incoming = snapshots
    output = tmp_path / 'candidate'
    result = overlay.prepare(base, source, 'incoming', output)
    assert result['status'] == 'prepared_not_deployed'
    assert result['importedFiles'] == 8
    for version, name in contract.CATALOG_FILES.items():
        before, after = baseline.read(base / 'public' / name), baseline.read(output / 'public' / name)
        assert after['defaultPageId'] == before['defaultPageId'] == 'existing'
        assert [p for p in after['pages'] if p['id'] != 'incoming'] == before['pages']
    timestamps = [baseline.read(output / 'public' / name)['generatedAt'] for name in contract.CATALOG_FILES.values()]
    assert len(set(timestamps)) == 1 and timestamps[0] != '2026-10-25T00:00:00Z'
    assert (output / 'public/audio/incoming/zh-Hans.json').read_bytes() == (source / 'public/audio/incoming/zh-Hans.json').read_bytes()
    assert (output / 'public/audio/existing/zh-Hans.json').read_bytes() == (base / 'public/audio/existing/zh-Hans.json').read_bytes()
    plan = baseline.read(output / 'single-source-dev-overlay-plan.json')
    assert plan['devHttpVerification'] == 'not_run'
    assert plan['sourceIdentitySha256'] == incoming['sourceIdentitySha256']
    assert baseline.read(output / 'publish-config.json')['intent']['environment'] == 'dev'


def test_corrupt_source_and_existing_asset_collision_are_refused(snapshots, tmp_path):
    base, source, _, _ = snapshots
    source_asset = source / 'public/audio/incoming/zh-Hans.json'
    original = source_asset.read_bytes(); source_asset.write_bytes(b'tampered')
    with pytest.raises(ValueError, match='asset hash differs'):
        overlay.prepare(base, source, 'incoming', tmp_path / 'bad')
    assert not (tmp_path / 'bad').exists()
    source_asset.write_bytes(original)
    collision = base / 'public/audio/incoming/zh-Hans.json'
    collision.parent.mkdir(parents=True); collision.write_bytes(b'unrelated')
    report_path = base / 'seal-report.json'; report_path.unlink()
    report = {**baseline.catalog_report(base / 'public'), 'files': baseline.files_report(base / 'public')}
    baseline.write(report_path, report)
    receipt_path = base / 'baseline-receipt.json'; receipt = baseline.read(receipt_path)
    receipt['rows'].append({'path': '/audio/incoming/zh-Hans.json', 'rawSha256': digest(b'unrelated'),
                            'rawBytes': len(b'unrelated'), 'managed': False})
    receipt_path.unlink(); baseline.write(receipt_path, receipt)
    with pytest.raises(ValueError, match='collision'):
        overlay.prepare(base, source, 'incoming', tmp_path / 'collision')
    assert collision.read_bytes() == b'unrelated'


def test_refuses_wrong_baseline_reused_page_and_video_redirect(snapshots, tmp_path):
    base, source, _, incoming = snapshots
    catalog = source / 'public/multilingual-v5.json'
    value = baseline.read(catalog)
    duplicate = copy.deepcopy(value); duplicate['pages'][0]['id'] = 'existing'
    catalog.unlink(); baseline.write(catalog, duplicate)
    with pytest.raises(ValueError, match='already exists'):
        overlay.prepare(base, source, 'existing', tmp_path / 'same')
    value['pages'][0]['videoDelivery'] = {'storageUrl': 'https://example.org/video'}
    catalog.unlink(); baseline.write(catalog, value)
    with pytest.raises(ValueError, match='Video delivery'):
        overlay.prepare(base, source, 'incoming', tmp_path / 'video')
    with pytest.raises(ValueError, match='Dev baseline'):
        overlay.prepare(source, base, 'existing', tmp_path / 'wrong')


def test_rejects_fingerprint_bound_to_different_audio(snapshots, tmp_path):
    base, source, _, incoming = snapshots
    catalog = source / 'public/multilingual-v5.json'
    value = baseline.read(catalog)
    value['pages'][0]['targets']['zh-Hans']['audioFingerprint'] = {
        'schemaVersion': 'sermon-audio-fingerprint-binding-v1',
        'algorithmVersion': 'spectral-landmarks-v1', 'captureSeconds': 10,
        'sourceStartSeconds': 0, 'sourceEndSeconds': 100,
        'pageId': 'incoming', 'sourceSha256': incoming['sourceMediaSha256'],
        'trackSha256': 'f' * 64, 'indexUrl': '/fingerprints/1bc04b5291c26a46-landmarks.json',
        'indexSha256': digest(b'index')}
    catalog.unlink(); baseline.write(catalog, value)
    index = source / 'public/fingerprints/1bc04b5291c26a46-landmarks.json'
    index.parent.mkdir(); index.write_bytes(b'index')
    report = source / 'seal-report.json'
    report.unlink(); baseline.write(report, {**baseline.catalog_report(source / 'public'),
                                             'files': baseline.files_report(source / 'public')})
    with pytest.raises(ValueError, match='Fingerprint differs'):
        overlay.prepare(base, source, 'incoming', tmp_path / 'bad-fingerprint')


def test_failed_staging_removes_only_new_candidate(snapshots, tmp_path, monkeypatch):
    base, source, _, _ = snapshots
    def fail(*args, **kwargs):
        raise ValueError('simulated config error')
    monkeypatch.setattr(baseline, 'publication_config', fail)
    candidate = tmp_path / 'failed'
    with pytest.raises(ValueError, match='simulated config error'):
        overlay.prepare(base, source, 'incoming', candidate)
    assert not candidate.exists()
    assert (base / 'public/audio/existing/zh-Hans.json').exists()
    assert (source / 'public/audio/incoming/zh-Hans.json').exists()


def test_baseline_resealed_after_tampering_cannot_claim_live_bytes(snapshots, tmp_path):
    base, source, _, _ = snapshots
    audio = base / 'public/audio/existing/zh-Hans.json'
    audio.write_bytes(b'tampered and resealed')
    report_path = base / 'seal-report.json'
    report_path.unlink()
    baseline.write(report_path, {**baseline.catalog_report(base / 'public'),
                                'files': baseline.files_report(base / 'public')})
    with pytest.raises(ValueError, match='public bytes differ from live receipt'):
        overlay.prepare(base, source, 'incoming', tmp_path / 'bad-reseal')
    assert audio.read_bytes() == b'tampered and resealed'


def test_firebase_managed_classification_cannot_hide_public_inventory(snapshots, tmp_path):
    base, source, _, _ = snapshots
    receipt_path = base / 'baseline-receipt.json'
    receipt = baseline.read(receipt_path)
    row = next(r for r in receipt['rows'] if r['path'] == '/audio/existing/zh-Hans.json')
    row['managed'] = True
    receipt_path.unlink(); baseline.write(receipt_path, receipt)
    with pytest.raises(ValueError, match='managed classification'):
        overlay.prepare(base, source, 'incoming', tmp_path / 'bad-managed')


@pytest.mark.parametrize('markup', [
    '<audio src="https://ai-for-god-sermon-audio.web.app/media/a.mp3"></audio>',
    '<a href="https://ai-for-god-sermon-audio.web.app/pages/example">source</a>',
    '<script>fetch("/content/other")</script>',
    '<style>body {background: url(/untracked.png)}</style>',
    '<img srcset="/a.png 1x, /b.png 2x">',
])
def test_rejects_dynamic_or_cross_environment_html_dependencies(markup):
    with pytest.raises(ValueError):
        overlay._PageDependencies().feed(markup)


def test_html_dependencies_require_included_release_assets():
    parser = overlay._PageDependencies(source_url="https://youtube.com/watch?v=x")
    parser.feed('<audio src="/media/sermon.mp3"></audio><a href="https://youtube.com/watch?v=x">source</a>')
    assert parser.paths == {baseline.safe_relative('/media/sermon.mp3')}


def test_reference_binds_source_and_every_locale(snapshots):
    _, source, _, page = snapshots
    target = page['targets']['zh-Hans']
    release = baseline.read(source / 'public' / target['releasePackageUrl'].lstrip('/'))
    assets = {a['role']: a for a in release['assets']}
    ref = {'schemaVersion': 'sermon-published-english-reference-v1', 'pageId': page['id'],
           'sourceIdentitySha256': page['sourceIdentitySha256'], 'sourceMediaSha256': page['sourceMediaSha256'],
           'reviewState': 'human_approved', 'targets': {'zh-Hans': {
               'releasePackageJsonSha256': target['releasePackageJsonSha256'],
               'contentSha256': assets['content']['sha256'], 'captionsSha256': assets['captions']['sha256'],
               'blocks': [{'textGroupId': 'group1', 'sourceUnitIds': ['unit1'], 'english': 'Text'}]}}}
    overlay.verify_english_reference(ref, page, {'zh-Hans': release}, source / 'public')
    ref['targets']['zh-Hans']['contentSha256'] = 'f' * 64
    with pytest.raises(ValueError, match='locale binding'):
        overlay.verify_english_reference(ref, page, {'zh-Hans': release}, source / 'public')


@pytest.mark.parametrize('href', [
    'https://ai-for-god-sermon-audio.firebaseapp.com/pages/other',
    'https://storage.googleapis.com/ai-for-god-sermon-media-prod/weekly/x.mp4',
    'https://youtube.com/watch?v=wrong',
    '//ai-for-god-sermon-audio.firebaseapp.com/page',
    'javascript:alert(1)',
])
def test_only_bound_source_url_may_be_external(href):
    parser = overlay._PageDependencies(source_url='https://youtube.com/watch?v=allowed')
    with pytest.raises(ValueError, match='External page link'):
        parser.feed(f'<a href="{href}">link</a>')


def test_internal_navigation_must_resolve_to_candidate_files():
    parser = overlay._PageDependencies(page_path=baseline.safe_relative('/pages/sermon/zh/index.html'))
    parser.feed('<a href="/missing-local-page">missing</a><a href="notes.html#part">notes</a>')
    notes = baseline.safe_relative('/pages/sermon/zh/notes.html')
    with pytest.raises(ValueError, match='no file in the candidate'):
        overlay.verify_page_links(parser, {notes})
    overlay.verify_page_links(parser, {notes, baseline.safe_relative('/missing-local-page')})


def test_detects_import_changed_during_copy(snapshots, tmp_path, monkeypatch):
    base, source, _, _ = snapshots
    original = overlay.shutil.copyfile
    def copy_with_mutation(src, dst, *args, **kwargs):
        result = original(src, dst, *args, **kwargs)
        if str(src).endswith('/audio/incoming/zh-Hans.json'):
            from pathlib import Path
            Path(dst).write_bytes(b'changed during copy')
        return result
    monkeypatch.setattr(overlay.shutil, 'copyfile', copy_with_mutation)
    with pytest.raises(ValueError, match='Copied imported asset differs'):
        overlay.prepare(base, source, 'incoming', tmp_path / 'copy-race')
    assert not (tmp_path / 'copy-race').exists()


def test_detects_baseline_changed_during_copy(snapshots, tmp_path, monkeypatch):
    base, source, _, _ = snapshots
    original = overlay.shutil.copytree
    def copy_with_mutation(src, dst, *args, **kwargs):
        result = original(src, dst, *args, **kwargs)
        from pathlib import Path
        if Path(src) == base / 'public':
            (Path(dst) / 'audio/existing/zh-Hans.json').write_bytes(b'changed during copy')
        return result
    monkeypatch.setattr(overlay.shutil, 'copytree', copy_with_mutation)
    with pytest.raises(ValueError, match='Copied baseline asset differs'):
        overlay.prepare(base, source, 'incoming', tmp_path / 'base-race')
    assert not (tmp_path / 'base-race').exists()


def test_reference_rejects_incorrect_source_group_mapping(snapshots):
    _, source, _, page = snapshots
    target = page['targets']['zh-Hans']
    release = baseline.read(source / 'public' / target['releasePackageUrl'].lstrip('/'))
    assets = {a['role']: a for a in release['assets']}
    ref = {'schemaVersion': 'sermon-published-english-reference-v1', 'pageId': page['id'],
           'sourceIdentitySha256': page['sourceIdentitySha256'], 'sourceMediaSha256': page['sourceMediaSha256'],
           'reviewState': 'human_approved', 'targets': {'zh-Hans': {
               'releasePackageJsonSha256': target['releasePackageJsonSha256'],
               'contentSha256': assets['content']['sha256'], 'captionsSha256': assets['captions']['sha256'],
               'blocks': [{'textGroupId': 'group1', 'sourceUnitIds': ['wrong'], 'english': 'Text'}]}}}
    with pytest.raises(ValueError, match='group mapping differs'):
        overlay.verify_english_reference(ref, page, {'zh-Hans': release}, source / 'public')
