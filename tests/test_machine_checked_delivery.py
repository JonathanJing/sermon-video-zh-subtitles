"""Machine-checked Layer 4 delivery with real builders and synthetic waivers.

Waivers in, release v4 and catalog v4 out. A machine-checked locale is never shown
as human-reviewed, and the v3 catalog old clients read never contains it.
"""
import argparse
import copy
import hashlib
import json
import subprocess

import pytest

from scripts import build_full_video_app_release as builder
from scripts import delivery_contract as d
from scripts import machine_quality_release_basis as basis
from scripts import sermon_unified_delivery as delivery
from scripts import study_artifacts
from scripts.target_audio_auto_qc import THRESHOLDS
from tests.test_machine_quality_release_basis import (IMPLEMENTATION, SECONDARY_ASR, calibration, issue_audio,
                                                    issue_text, text_qc, track_check)
from tests.test_public_study_delivery import binding, prepared, save, seal_fixture  # noqa: F401 (fixture)

PAGE, LOCALE = 'synthetic-machine-page', 'ko'
ASR = {'model': 'Qwen3-ASR', 'modelRevision': 'r1'}
# The primary runtime recorded by the screening receipt this fixture binds.
SCREENING_ASR = {'protocol': 'formal-back-asr-batch-v1', **ASR, 'batchSize': 1, 'maxNewTokens': 2048,
                 'dtype': 'bfloat16', 'executionDevice': 'cuda:0', 'runtime': {}, 'implementationSha256': 'd' * 64,
                 'minSimilarity': 0.88, 'scoring': 'token-sequence-ratio-v1; short units (<4 tokens) must match exactly'}
PRIMARY_SETTINGS = basis.json_sha256(SCREENING_ASR)
ASR_SETTINGS = {'primary': PRIMARY_SETTINGS, 'secondary': basis.json_sha256({'backend': 'synthetic-secondary'})}


def spoken_calibration():
    """A calibration that also seeded errors into condensed spoken groups."""
    base = calibration(LOCALE, asrIdentity={'primary': ASR, 'secondary': SECONDARY_ASR},
                       asrSettingsSha256=ASR_SETTINGS)
    added = {f'spoken.{kind}': {'trials': 4, 'detected': 4, 'rate': 1.0} for kind in basis.waiver.SPOKEN_KINDS}
    return {**base, 'spokenIncluded': True, 'kinds': {**base['kinds'], **added},
            'trials': base['trials'] + 4 * len(added), 'detected': base['detected'] + 4 * len(added)}


def condense_first_group(source, anchor, candidate, cal):
    """A spoken candidate whose first group was condensed, its binding and its text waiver."""
    spoken = copy.deepcopy(candidate)
    group = spoken['groups'][0]
    short = group['targetText'][:max(1, len(group['targetText']) // 2)]
    group.update(targetText=short, targetUtterances=[short])
    group['coverage'][0]['targetText'] = short
    condensation = {'schemaVersion': basis.CONDENSATION_BINDING_SCHEMA, 'targetLocale': LOCALE, 'status': 'pass',
                    'issues': [], 'humanApproval': False, 'condensationRecordJsonSha256': 'e' * 64,
                    'fullCandidateJsonSha256': d.sha(candidate), 'spokenCandidateJsonSha256': d.sha(spoken),
                    'groups': [{'translationGroupId': group['translationGroupId'],
                                'finalSpokenTextSha256': hashlib.sha256(short.encode()).hexdigest()}]}
    qc = text_qc(spoken, anchor)
    qc['results'][0]['mode'] = 'spoken_condensed'
    qc['condensedGroupIds'] = [group['translationGroupId']]
    waiver = issue_text(source, anchor, spoken, qc, cal, condensation_binding=condensation,
                                     created_at='2026-10-07T01:30:00+00:00')
    return spoken, waiver, condensation


def machine_inputs(root, *, human_full_text=None, condense=False):
    """A week whose text and listening gates were both passed by machine waivers.

    ``condense`` dubs a spoken script whose first group was condensed."""
    from tests import test_produce_target_language_candidate as source_fixtures
    from tests import test_prepare_target_language_speech_job as speech_fixtures
    from tests import test_review_target_language_audio as audio_fixtures
    sf, tf = source_fixtures.ProduceTargetLanguageCandidateTests(), speech_fixtures.TargetLanguageSpeechJobTests()
    sf.setUp(); tf.setUp()
    source = sf.source
    candidate = copy.deepcopy(tf.candidate)
    candidate.update(englishSourcePackageJsonSha256=d.sha(source), anchorManifestSha256=d.sha(sf.anchor),
                     status=basis.MACHINE_PENDING_CANDIDATE,
                     humanReview={'translation': 'pending', 'reviewer': None, 'reviewedAt': None, 'reviewedGroupIds': []})
    for group, unit in zip(candidate['groups'], sf.anchor['sourceUnits']):
        group['sourceUnitIds'] = [unit['sourceUnitId']]
        group['coverage'] = [{'sourceUnitId': unit['sourceUnitId'], 'targetText': group['targetText']}]
    cal = (spoken_calibration() if condense
           else calibration(LOCALE, asrIdentity={'primary': ASR, 'secondary': SECONDARY_ASR},
                       asrSettingsSha256=ASR_SETTINGS))
    full_waiver = issue_text(source, sf.anchor, candidate, text_qc(candidate, sf.anchor), cal,
                                          created_at='2026-10-07T01:00:00+00:00')
    spoken, text_waiver, condensation = ((candidate, full_waiver, None) if not condense
                                         else condense_first_group(source, sf.anchor, candidate, cal))
    track = root / 'tone.mp3'
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=10',
                    '-y', str(track)], check=True)
    captions = {'cues': [{'textGroupId': g['translationGroupId'], 'start': i * 5, 'end': (i + 1) * 5,
                          'text': g['targetText']} for i, g in enumerate(spoken['groups'])]}
    cap_path = save(root, 'captions.json', captions)
    package, screening = audio_fixtures.fixture()
    unit_path = root / 'unit.wav'; unit_path.write_bytes(b'synthetic-unit')
    package.update(targetLocale=LOCALE, englishSourcePackageJsonSha256=d.sha(source),
                   targetLanguageCandidateJsonSha256=d.sha(spoken), track=binding(track), captions=binding(cap_path),
                   status='machine_screened', machineScreening={'status': 'pass', 'model': ASR['model'], 'coverage': 1.0},
                   units=[{'textGroupId': g['translationGroupId'],
                           'targetTextSha256': hashlib.sha256(g['targetText'].encode()).hexdigest(),
                           'audio': binding(unit_path), 'durationSeconds': 5.0} for g in spoken['groups']])
    schedule = save(root, 'schedule.json', {'synthetic': True})
    package['schedule'] = {**binding(schedule), 'jsonSha256': d.sha({'synthetic': True})}
    screening.update(schemaVersion='sermon-target-language-audio-screening-v2', asrSettings=dict(SCREENING_ASR),
                     asrSettingsSha256=PRIMARY_SETTINGS, minSimilarity=0.88,
                     targetLocale=LOCALE, trackSha256=builder.digest(track), status='pass', modelRevision=ASR['modelRevision'],
                     reviewedGroupIds=[u['textGroupId'] for u in package['units']],
                     unitAudioSha256s=[u['audio']['sha256'] for u in package['units']],
                     results=[{'textGroupId': u['textGroupId'], 'targetTextSha256': u['targetTextSha256'],
                               'audioSha256': u['audio']['sha256'], 'recognized': g['targetText'], 'similarity': 1.0,
                               'differences': [], 'status': 'pass'} for u, g in zip(package['units'], spoken['groups'])])
    spans = {u['sourceUnitId']: float(u['end']) - float(u['start']) for u in sf.anchor['sourceUnits']}
    audio_qc = {'schemaVersion': 'sermon-target-audio-auto-qc-v1', 'locale': LOCALE, 'status': 'pass',
                'implementationSha256': IMPLEMENTATION, 'thresholds': dict(THRESHOLDS),
                'humanApproval': False, 'mutatesAudio': False, 'subtitleOnlyGroupIds': [], 'repairGroupIds': [],
                'results': [{'groupId': u['textGroupId'], 'status': 'pass', 'issues': [], 'asrDecision': 'pass',
                             'asrPrimary': 1.0, 'asrSecondary': None, 'asrPrimaryRecognized': g['targetText'],
                             'asrSecondaryRecognized': None, 'asrPrimaryModel': ASR, 'asrSecondaryModel': None,
                             'asrPrimarySettingsSha256': PRIMARY_SETTINGS, 'asrSecondarySettingsSha256': None,
                             'audioSha256': u['audio']['sha256'], 'textSha256': u['targetTextSha256'],
                             'sourceSeconds': spans[g['sourceUnitIds'][0]], 'failedAttempts': 0, 'nextAction': 'keep',
                             'metrics': {}} for u, g in zip(package['units'], spoken['groups'])]}
    audio_waiver = issue_audio(package, screening, audio_qc, text_waiver, cal,
                                            anchor=sf.anchor, candidate=spoken, track_check=track_check(package),
                                            created_at='2026-10-07T02:00:00+00:00')
    fields = {'series': 'Synthetic series', 'title': 'Synthetic machine title', 'speaker': 'Synthetic speaker',
              'scripture': 'John 3:16', 'summary': 'Synthetic summary', 'outline': ['Legacy outline']}
    proposal = root / 'proposal.md'; proposal.write_text(' '.join(str(v) for v in fields.values()))
    metadata = {'schemaVersion': 'sermon-formal-dev-metadata-approval-v2', 'pageId': PAGE, 'date': '2026-10-04',
                'proposalFileSha256': builder.digest(proposal), 'approvedLocales': [LOCALE],
                'decision': 'approved_selected_locales', 'approvalText': '所列语言页面信息已批准', 'reviewer': 'user',
                'recordedAt': '2026-10-07T03:00:00Z', 'locales': {LOCALE: fields}}
    content = {'schemaVersion': 'sermon-full-video-text-content-v3', 'reviewMode': 'formal',
               'audioDurationSeconds': builder.stage.decode_audio(track, 'fixture duration'), 'pageId': PAGE,
               'targetLocale': LOCALE, 'sourceLocale': 'en', 'status': 'machine_checked',
               'disclosure': basis.disclosure(LOCALE), 'englishSourcePackageJsonSha256': d.sha(source),
               'targetLanguageCandidateJsonSha256': d.sha(candidate),
               'sourceMediaSha256': source['source']['media']['sha256'],
               'durationSeconds': source['source']['approvedWindow']['endSeconds'] - source['source']['approvedWindow']['startSeconds'],
               'sourceVideoUrl': f'/pages/{PAGE}/full-video-browser.mp4', **fields,
               'cues': [{**cue, 'text': g['targetText'], 'sourceUnitIds': g['sourceUnitIds']}
                        for cue, g in zip(captions['cues'], candidate['groups'])]}
    documents = {'source': source, 'metadata_approval': metadata, 'full_candidate': candidate, 'spoken_candidate': spoken,
                 'full_review_receipt': full_waiver, 'spoken_review_receipt': text_waiver, 'audio_package': package,
                 'audio_review_receipt': audio_waiver, 'audio_screening_receipt': screening, 'full_content': content}
    for kind in ('outline', 'meditation'):
        artifact = study_artifacts.produce(kind, [{'title': kind + ' title', 'body': 'Complete sentence.',
                                                   'sourceUnitIds': candidate['groups'][0]['sourceUnitIds']}],
                                           page_id=PAGE, locale=LOCALE, source_sha=d.sha(source), text_sha=d.sha(candidate),
                                           producer_identity='synthetic-v1')
        review = {'schemaVersion': 'sermon-study-review-v1',
                  **{k: artifact[k] for k in ('kind', 'pageId', 'locale', 'sourcePackageSha256', 'textCandidateSha256')},
                  'artifactSha256': d.sha(artifact), 'decision': 'approved', 'humanApproval': True, 'reviewedBy': 'synthetic',
                  'reviewedAt': '2026-10-07T03:00:00Z',
                  'checks': {k: 'pass' for k in ('faithfulness', 'scriptureIntegrity', 'localeReadability')}}
        documents[kind] = artifact; documents[kind + '_review'] = review
    if condensation is not None:
        documents['condensation_binding'] = condensation
    return documents, proposal, (sf, tf)


def run_delivery(root, documents, proposal, **extra):
    paths = {name: save(root, name + '.json', value) for name, value in documents.items()}
    paths['metadata_proposal'] = proposal
    intent = {'schemaVersion': 'sermon-release-intent-v1', 'environment': 'dev', 'channel': 'dev', 'project': 'test',
              'site': 'test-dev', 'origin': 'https://test-dev.web.app'}
    config = {'schemaVersion': 'sermon-unified-delivery-v1', 'pageId': PAGE, 'date': '2026-10-04', 'locales': [LOCALE],
              'intent': intent, 'routes': {'dev': {k: intent[k] for k in ('channel', 'project', 'site', 'origin')}},
              'workRoot': str(root / 'work'), 'requiredEndpoints': ['dev', 'beta', 'production_ios', 'production_web'],
              'inputs': {name: binding(path) if name in ('source', 'metadata_approval', 'metadata_proposal')
                         else {LOCALE: binding(path)} for name, path in paths.items()}, **extra}
    config_path = save(root, 'config.json', config)
    frozen = root / 'frozen.json'
    state = delivery.freeze(config_path, frozen)
    return config, delivery.execute(frozen, state['planHash'])


@pytest.fixture
def machine(tmp_path):
    root = tmp_path / 'machine'; root.mkdir()
    documents, proposal, fixtures = machine_inputs(root)
    try:
        config, result = run_delivery(root, documents, proposal)
        yield {'root': root, 'config': config, 'result': result, 'documents': documents, 'proposal': proposal}
    finally:
        for fixture in fixtures:
            fixture.doCleanups()


def http_receipt(root, prepared_dir, origin):
    _, assets = builder.verified_assets(prepared_dir)
    return save(root, 'http.json', {'schemaVersion': 'sermon-app-assets-http-verification-v1', 'status': 'pass',
                                    'origin': origin, 'verifiedAt': '2026-10-07T04:00:00Z',
                                    'assets': [{**row, 'status': 'pass'} for row in assets]})


def test_waivers_produce_a_disclosed_v4_release_never_marked_human(machine):
    prepared_dir = machine['root'] / 'work/prepared'
    assert machine['result']['status'] == 'succeeded'
    path = prepared_dir / 'public/releases-v4' / PAGE / (LOCALE + '.json')
    release = builder.read(path)
    assert release['schemaVersion'] == d.RELEASE_V4
    assert (release['contentStatus'], release['audioStatus']) == ('machine_checked', 'machine_checked')
    assert {basis_row['kind'] for basis_row in release['reviewBasis'].values()} == {'machine_quality_waiver'}
    assert release['reviewBasis']['audio']['receiptSha256'] == d.sha(machine['documents']['audio_review_receipt'])
    assert release['disclosure'] == basis.disclosure(LOCALE)
    # The spoken script equals the full text, so the captions already show it.
    assert (release['captionText'], release['spokenCondensation']) == ('full_text', None)
    assert not (prepared_dir / 'public/releases-v2' / PAGE).exists()
    d.validate_public_study(release, reader=lambda url: (prepared_dir / 'public' / url.lstrip('/')).read_bytes())
    page = (prepared_dir / 'public/pages' / PAGE / LOCALE / 'index.html').read_text()
    assert basis.disclosure(LOCALE)['text'] in page and '机器质检' in page
    # The label beside the Korean disclosure is Korean too.
    assert '<p role="note" lang="ko"><strong>기계 품질 검사</strong> · ' in page
    for claim in ('已批准完整文稿', '已批准完整阅读稿', '已审核译文', '已审核短口播稿'):
        assert claim not in page
    # The waiver never turned into a human decision upstream.
    assert machine['documents']['full_candidate']['humanReview']['translation'] == 'pending'
    assert machine['documents']['audio_package']['humanReview']['humanApproval'] is False


def test_machine_only_seal_needs_a_human_baseline_for_old_clients(machine):
    prepared_dir = machine['root'] / 'work/prepared'
    receipt = http_receipt(machine['root'], prepared_dir, machine['config']['intent']['origin'])
    with pytest.raises(ValueError, match='human-only projection'):
        builder.seal(argparse.Namespace(prepared=prepared_dir, http_verification=receipt, out=machine['root'] / 'sealed'))


def test_seal_over_human_baseline_publishes_v4_and_keeps_v3_human_only(prepared, machine):
    baseline = seal_fixture(prepared)
    baseline_v3 = d.validate_catalog_snapshot(baseline)
    plan = save(machine['root'], 'plan.json', {
        'schemaVersion': 'sermon-locale-release-plan-v1', 'pageId': PAGE, 'locales': [LOCALE], 'requiredLocales': [LOCALE],
        'mode': 'incremental', 'baselineCatalogSha256': d.sha(baseline_v3), 'baselineVersion': 'sites/test-dev/versions/1',
        'parentGeneration': 0})
    prepared_dir = machine['root'] / 'work/prepared'
    receipt = http_receipt(machine['root'], prepared_dir, machine['config']['intent']['origin'])
    sealed = machine['root'] / 'sealed'
    report = builder.seal(argparse.Namespace(prepared=prepared_dir, http_verification=receipt, out=sealed,
                                             baseline=baseline, release_plan=plan))
    v3 = d.validate_catalog_snapshot(sealed)
    v4 = builder.read(sealed / 'public/multilingual-v4.json')
    assert report['catalogV4Sha256'] == builder.digest(sealed / 'public/multilingual-v4.json')
    # Old clients see exactly the baseline pages; new clients also see the machine-checked week.
    assert {**v3, 'generatedAt': None} == {**baseline_v3, 'generatedAt': None}
    assert [page['id'] for page in v4['pages']] == [prepared['page'], PAGE]
    target = v4['pages'][1]['targets'][LOCALE]
    assert target['releasePackageUrl'] == f'/releases-v4/{PAGE}/{LOCALE}.json'
    assert (target['contentStatus'], target['audioStatus']) == ('machine_checked', 'machine_checked')
    assert d.project_human_catalog(v4) == v3
    # The baseline's human releases and assets survive byte for byte.
    for row in builder.read(baseline / 'seal-report.json')['files']:
        if row['path'].lstrip('/') not in d.CATALOG_FILES.values():
            assert builder.digest(sealed / 'public' / row['path'].lstrip('/')) == row['sha256']
    # The next week's overlay starts from this v4 snapshot and still validates it.
    assert d.snapshot_catalog_v4(sealed) == v4
    tampered = copy.deepcopy(v3); tampered['pages'].append(copy.deepcopy(v4['pages'][1])); tampered['pages'][1]['targets'] = {}
    (sealed / 'public/multilingual-v3.json').write_text(json.dumps(tampered))
    with pytest.raises(ValueError):
        d.validate_catalog_snapshot(sealed)


def test_mixed_review_bases_set_each_status_independently(tmp_path):
    root = tmp_path / 'mixed'; root.mkdir()
    documents, proposal, fixtures = machine_inputs(root)
    try:
        # A machine-waived full text never reads as human-reviewed reading content.
        documents['full_content'] = dict(documents['full_content'], status='human_reviewed', schemaVersion='sermon-full-video-text-content-v2')
        documents['full_content'].pop('disclosure')
        with pytest.raises(ValueError, match='content v3 with its disclosure'):
            run_delivery(root, documents, proposal)
    finally:
        for fixture in fixtures:
            fixture.doCleanups()
    assert builder.release_statuses({'fullText': {'kind': 'human_review'}, 'spokenText': {'kind': 'human_review'},
                                     'audio': {'kind': 'machine_quality_waiver'}}) == ('human_reviewed', 'machine_checked')
    assert builder.release_statuses({'fullText': {'kind': 'human_review'}, 'spokenText': {'kind': 'machine_quality_waiver'},
                                     'audio': {'kind': 'human_review'}}) == ('human_reviewed', 'machine_checked')
    assert builder.release_statuses({'fullText': {'kind': 'machine_quality_waiver'}, 'spokenText': {'kind': 'human_review'},
                                     'audio': {'kind': 'human_review'}}) == ('machine_checked', 'human_reviewed')


def test_audio_waiver_must_bind_the_spoken_script_waiver(tmp_path):
    root = tmp_path / 'unbound'; root.mkdir()
    documents, proposal, fixtures = machine_inputs(root)
    try:
        documents['audio_review_receipt'] = dict(documents['audio_review_receipt'], textWaiverJsonSha256='0' * 64)
        with pytest.raises(ValueError):
            run_delivery(root, documents, proposal)
    finally:
        for fixture in fixtures:
            fixture.doCleanups()


def test_full_and_spoken_scripts_must_share_group_ids():
    # Clients pair dub cues with the full text by group id; a renamed spoken script would not load.
    full = {'groups': [{'translationGroupId': 'g1', 'targetText': 'A'}, {'translationGroupId': 'g2', 'targetText': 'B'}]}
    spoken = copy.deepcopy(full)
    assert builder.caption_text(full, 'f', spoken, 's', {}, None, LOCALE) == ('full_text', None)
    for group in spoken['groups']:
        group['translationGroupId'] += '-spoken'
    with pytest.raises(ValueError, match='different group ids'):
        builder.caption_text(full, 'f', spoken, 's', {}, None, LOCALE)


def test_condensed_dub_binds_its_condensation_and_captions_show_the_full_text(tmp_path):
    root = tmp_path / 'condensed'; root.mkdir()
    documents, proposal, fixtures = machine_inputs(root, condense=True)
    try:
        for name, change, message in (
                ('condensation_binding', None, 'needs its condensation binding'),
                ('condensation_binding', {'fullCandidateJsonSha256': '0' * 64}, 'does not bind'),
        ):
            broken = copy.deepcopy(documents)
            if change is None:
                broken.pop(name)
            else:
                broken[name].update(change)
            with pytest.raises(ValueError, match=message):
                run_delivery(root / message.replace(' ', '-'), broken, proposal)
        _, result = run_delivery(root, documents, proposal)
        assert result['status'] == 'succeeded'
        prepared_dir = root / 'work/prepared'
        release = builder.read(prepared_dir / 'public/releases-v4' / PAGE / (LOCALE + '.json'))
        group_id = documents['full_candidate']['groups'][0]['translationGroupId']
        assert release['captionText'] == 'full_text'
        assert release['spokenCondensation'] == {
            'condensationRecordJsonSha256': 'e' * 64, 'condensedGroupIds': [group_id],
            'condensationBindingJsonSha256': d.sha(documents['condensation_binding'])}
        # The captions asset is still the audio package's spoken-script captions.
        captions = builder.read(prepared_dir / 'public/captions' / PAGE / (LOCALE + '.json'))
        assert captions['cues'][0]['text'] == documents['spoken_candidate']['groups'][0]['targetText']
        page = (prepared_dir / 'public/pages' / PAGE / LOCALE / 'index.html').read_text()
        assert '同传式精简口播' in page and '配音字幕显示完整译文' in page
    finally:
        for fixture in fixtures:
            fixture.doCleanups()
    # A binding without condensed groups is refused rather than ignored.
    full = {'groups': [{'translationGroupId': 'g1', 'targetText': 'a'}]}
    with pytest.raises(ValueError, match='without condensed groups'):
        builder.caption_text(full, '1' * 64, full, '1' * 64, {}, tmp_path / 'binding.json', LOCALE)
    shortened = {'groups': [{'translationGroupId': 'g1', 'targetText': 'b'}]}
    assert builder.caption_text(full, '1' * 64, shortened, '2' * 64, {}, None, LOCALE) == ('spoken_text', None)


def test_projection_moves_removed_defaults_and_refuses_an_empty_catalog():
    def target(locale, machine):
        return {'releasePackageUrl': f"/releases-v{'4' if machine else '2'}/p/{locale}.json",
                'releasePackageJsonSha256': 'a' * 64, 'contentStatus': 'machine_checked' if machine else 'human_reviewed',
                'audioStatus': 'machine_checked' if machine else 'human_reviewed', 'capabilities': ['text', 'captions', 'audio']}
    page = lambda page_id, date, targets, default: {'id': page_id, 'date': date, 'title': 'T', 'sourceLocale': 'en',
                                                    'sourceIdentitySha256': 'b' * 64, 'defaultTargetLocale': default,
                                                    'targets': targets}
    v4 = {'schemaVersion': d.CATALOG_V4, 'generatedAt': '2026-10-07T00:00:00Z', 'defaultPageId': 'new',
          'pages': [page('old', '2026-09-27', {'ko': target('ko', False)}, 'ko'),
                    page('mid', '2026-09-28', {'zh-Hans': target('zh-Hans', True), 'es': target('es', False)}, 'zh-Hans'),
                    page('new', '2026-10-04', {'ko': target('ko', True)}, 'ko')]}
    v3 = d.project_human_catalog(v4)
    assert v3['schemaVersion'] == d.CATALOG_V3
    assert [p['id'] for p in v3['pages']] == ['old', 'mid']
    assert v3['defaultPageId'] == 'mid'
    assert v3['pages'][1]['defaultTargetLocale'] == 'es' and set(v3['pages'][1]['targets']) == {'es'}
    assert d.project_human_catalog(d.upgrade_catalog(v3)) == v3
    with pytest.raises(ValueError, match='human-only projection'):
        d.project_human_catalog({**v4, 'pages': [v4['pages'][2]]})
