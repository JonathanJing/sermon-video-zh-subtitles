"""Cutting a weekly run into a Dev clip fixture: offline, synthetic media, no model calls."""
import ast
import copy
import hashlib
import json
import shutil
import subprocess

import pytest
from scripts import build_dev_180s_simulated_inputs as fixture
from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.delivery import contract

pytestmark = pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='needs ffmpeg')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False))
    return path


def unit(n, start, end, group=None):
    return {'sourceUnitId': f'chunk-0000-u{n:03d}', 'sourceSentenceId': f'chunk-0000-s{n:03d}', 'start': start, 'end': end,
            'english': f'Sentence {n}.', 'sourceWordIds': [f'w{n}'],
            'words': [{'wordId': f'w{n}', 'text': f'Sentence{n}', 'start': start, 'end': end}]}


@pytest.fixture
def weekly(tmp_path):
    """A 20 s recording whose sermon starts at 2 s, six one-unit groups, three locales."""
    media = tmp_path / 'recording.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc=size=64x48:rate=10:duration=20',
                    '-f', 'lavfi', '-i', 'sine=frequency=440:duration=20', '-shortest', '-c:v', 'libx264',
                    '-c:a', 'aac', str(media)], check=True)
    units = [unit(n, 1.0 + 2 * n, 2.5 + 2 * n) for n in range(6)]
    segments = [{'id': str(n), 'start': repr(u['start']), 'end': repr(u['end']), 'text': u['english'],
                 'wordTimes': repr([{'start': u['start'], 'end': u['end'], 'phones': [{'start': u['start'], 'end': u['end']}]}])}
                for n, u in enumerate(units)]
    aligned = tmp_path / 'aligned-segments.json'
    aligned.write_text(json.dumps(segments))
    anchor = {'schemaVersion': 'sermon-sentence-anchor-manifest-v2', 'input': {'mfaSegmentsSha256': sha(aligned)},
              'counts': {'sourceUnits': 6}, 'issues': [{'sourceSentenceId': 'chunk-0000-s003', 'type': 'long'},
                                                       {'sourceSentenceId': 'chunk-0000-s005', 'type': 'long'}],
              'sourceUnits': units,
              'translationRequests': [{'translationGroupId': 'translation-' + u['sourceUnitId'], 'sourceUnitIds': [u['sourceUnitId']],
                                       'targetEnglish': u['english'], 'stableAtSeconds': repr(u['end'])} for u in units]}
    anchor_path = write(tmp_path / 'anchor.json', anchor)
    groups = [{'translationGroupId': 'translation-' + u['sourceUnitId'], 'sourceUnitIds': [u['sourceUnitId']],
               'targetText': f'译文{n}。'} for n, u in enumerate(units)]
    source = {'source': {'media': {'sha256': sha(media), 'durationSeconds': fixture.duration(media)},
                         'approvedWindow': {'startSeconds': 2.0}, 'serviceDate': '2026-10-11'},
              'anchors': {'artifact': {'jsonSha256': contract.sha(anchor)}},
              'transcript': {'artifact': {'sha256': sha(aligned)}}}
    source_path = write(tmp_path / 'source.json', source)
    candidate = {'anchorManifestSha256': contract.sha(anchor),
                 'englishSourcePackageJsonSha256': contract.sha(source), 'groups': groups, 'translationPolicySha256': 'p' * 64,
                 'modelReview': {'reviewedGroupIds': [g['translationGroupId'] for g in groups]}}
    candidate_path = write(tmp_path / 'candidate.json', candidate)
    package_units = []
    for n, group in enumerate(groups):
        wav = tmp_path / f'unit-{n:04d}.wav'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', f'sine=frequency={300 + 50 * n}:duration=0.5',
                        '-ar', '24000', '-ac', '1', str(wav)], check=True)
        package_units.append({'textGroupId': group['translationGroupId'], 'audio': {'path': str(wav), 'sha256': sha(wav)}})
    package = write(tmp_path / 'package.json', {'englishSourcePackageJsonSha256': contract.sha(source),
                 'targetLanguageCandidateJsonSha256': contract.sha(candidate), 'units': package_units})
    spec = {'schemaVersion': fixture.CLIP_SPEC_SCHEMA, 'pageId': 'week', 'serviceDate': '2026-10-11',
            'media': {'path': str(media), 'sha256': sha(media)},
            'englishSourceMedia': source['source']['media'],
            'englishSourcePackage': {'path': str(source_path), 'jsonSha256': contract.sha(source)},
            'alignedSegments': {'path': str(aligned)}, 'anchor': {'path': str(anchor_path), 'jsonSha256': contract.sha(anchor)},
            'approvedWindowStartSeconds': 2.0, 'unitRange': [2, 4], 'marginSeconds': {'before': 0.5, 'after': 0.5},
            'locales': {locale: {'candidate': str(candidate_path), 'audioPackage': str(package)} for locale in fixture.LOCALES}}
    return spec, tmp_path


def test_a_unit_range_is_cut_and_rebased_with_its_text_and_audio(weekly):
    spec, root = weekly
    clip = fixture.weekly_clip(spec, root / 'clip')
    # Units 2 and 3 span 5.0-8.5 s of the sermon; with 0.5 s margins the clip is 4.5-9.0 s, i.e. 6.5-11.0 s of the recording.
    assert clip['scope']['sermonRelativeWindowSeconds'] == [4.5, 9.0]
    assert clip['scope']['originalSourceWindowSeconds'] == [6.5, 11.0]
    assert abs(fixture.duration(clip['media']) - 4.5) < 0.2
    units = clip['anchor']['sourceUnits']
    assert [u['sourceUnitId'] for u in units] == ['chunk-0000-u002', 'chunk-0000-u003']
    assert [(u['start'], u['end']) for u in units] == [(0.5, 2.0), (2.5, 4.0)]
    assert units[0]['words'][0]['start'] == 0.5
    assert [r['translationGroupId'] for r in clip['anchor']['translationRequests']] == [
        'translation-chunk-0000-u002', 'translation-chunk-0000-u003']
    assert clip['anchor']['translationRequests'][0]['stableAtSeconds'] == '2.0'
    assert clip['anchor']['issues'] == [{'sourceSentenceId': 'chunk-0000-s003', 'type': 'long'}]
    assert clip['anchor']['counts']['sourceUnits'] == 2
    # Aligned segments keep their string encoding, rebased the same way.
    assert [s['id'] for s in clip['segments']] == ['2', '3']
    assert (clip['segments'][0]['start'], clip['segments'][0]['end']) == ('0.5', '2.0')
    words = ast.literal_eval(clip['segments'][0]['wordTimes'])
    assert (words[0]['start'], words[0]['phones'][0]['end']) == (0.5, 2.0)
    zh = clip['locales']['zh-Hans']
    assert [g['translationGroupId'] for g in zh['candidate']['groups']] == ['translation-chunk-0000-u002', 'translation-chunk-0000-u003']
    assert zh['candidate']['modelReview']['reviewedGroupIds'] == ['translation-chunk-0000-u002', 'translation-chunk-0000-u003']
    assert [w.name for w in zh['wavs']] == ['unit-0002.wav', 'unit-0003.wav']
    assert abs(fixture.duration(zh['track']) - 1.0) < 0.1
    assert clip['window_media_bound'] is True  # the clip's window approval names its media for Layer 3


def test_the_inputs_must_be_the_ones_the_spec_and_the_anchor_name(weekly):
    spec, root = weekly
    cases = {
        'Source media differs': dict(spec, media=dict(spec['media'], sha256='0' * 64)),
        'English source media differs': dict(spec, englishSourceMedia=dict(spec['englishSourceMedia'], durationSeconds=99.0)),
        'Invalid unit range': dict(spec, unitRange=[4, 9]),
    }
    for n, (message, changed) in enumerate(cases.items()):
        with pytest.raises(ValueError, match=message):
            fixture.weekly_clip(changed, root / f'clip-{n}')
    package_path = root / 'package.json'
    package = json.loads(package_path.read_text())
    package_path.write_text(json.dumps(dict(package, targetLanguageCandidateJsonSha256='0' * 64)))
    with pytest.raises(ValueError, match='was not rendered from this candidate'):
        fixture.weekly_clip(spec, root / 'clip-candidate')


def test_a_group_straddling_the_clip_edge_is_refused(weekly):
    spec, root = weekly
    anchor = json.loads((root / 'anchor.json').read_text())
    anchor['translationRequests'][2]['sourceUnitIds'] = ['chunk-0000-u001', 'chunk-0000-u002']
    write(root / 'anchor.json', anchor)
    source = fixture.read(root / 'source.json')
    source['anchors']['artifact']['jsonSha256'] = contract.sha(anchor)
    write(root / 'source.json', source)
    spec['englishSourcePackage']['jsonSha256'] = contract.sha(source)
    with pytest.raises(ValueError, match='straddles the clip boundary'):
        fixture.weekly_clip(dict(spec, anchor=dict(spec['anchor'], jsonSha256=contract.sha(anchor))), root / 'clip')


@pytest.mark.parametrize('binding', ['anchor', 'candidate_source', 'audio_source'])
def test_candidates_and_audio_from_another_source_run_are_rejected(weekly, binding):
    spec, root = weekly
    candidate = fixture.read(root / 'candidate.json')
    package = fixture.read(root / 'package.json')
    if binding == 'anchor':
        candidate['anchorManifestSha256'] = '0' * 64
    elif binding == 'candidate_source':
        candidate['englishSourcePackageJsonSha256'] = '0' * 64
    else:
        package['englishSourcePackageJsonSha256'] = '0' * 64
    # Still a mutually bound candidate/audio pair with overlapping group IDs.
    package['targetLanguageCandidateJsonSha256'] = contract.sha(candidate)
    write(root / 'candidate.json', candidate)
    write(root / 'package.json', package)
    with pytest.raises(ValueError, match='another (anchor manifest|English source package)'):
        fixture.weekly_clip(spec, root / 'clip')


@pytest.mark.parametrize('unit_range', [[2, 3], [3, 4]])
def test_a_split_sentence_cannot_be_cut_at_either_edge(weekly, unit_range):
    spec, root = weekly
    anchor = fixture.read(root / 'anchor.json')
    anchor['sourceUnits'][3]['sourceSentenceId'] = anchor['sourceUnits'][2]['sourceSentenceId']
    write(root / 'anchor.json', anchor)
    spec['anchor']['jsonSha256'] = contract.sha(anchor)
    source = fixture.read(root / 'source.json')
    source['anchors']['artifact']['jsonSha256'] = contract.sha(anchor)
    write(root / 'source.json', source)
    spec['englishSourcePackage']['jsonSha256'] = contract.sha(source)
    spec['unitRange'] = unit_range
    with pytest.raises(ValueError, match='complete source sentences'):
        fixture.weekly_clip(spec, root / 'clip')
    assert not (root / 'clip').exists()


def test_an_omitted_aligned_segment_cannot_be_rebound(weekly):
    spec, root = weekly
    segments = fixture.read(root / 'aligned-segments.json')
    segments[2]['start'] = '3.0'  # Outside the margin, despite covering unit 2.
    write(root / 'aligned-segments.json', segments)
    anchor = fixture.read(root / 'anchor.json')
    anchor['input']['mfaSegmentsSha256'] = sha(root / 'aligned-segments.json')
    write(root / 'anchor.json', anchor)
    spec['anchor']['jsonSha256'] = contract.sha(anchor)
    source = fixture.read(root / 'source.json')
    source['anchors']['artifact']['jsonSha256'] = contract.sha(anchor)
    source['transcript']['artifact']['sha256'] = sha(root / 'aligned-segments.json')
    write(root / 'source.json', source)
    spec['englishSourcePackage']['jsonSha256'] = contract.sha(source)
    with pytest.raises(ValueError, match='omits an aligned segment'):
        fixture.weekly_clip(spec, root / 'clip')


@pytest.mark.parametrize('locale', fixture.LOCALES + ['fr'])
def test_incomplete_or_extra_locale_sets_fail_before_media_work(weekly, locale, monkeypatch):
    spec, root = weekly
    if locale == 'fr':
        spec['locales'][locale] = spec['locales']['es']
    else:
        del spec['locales'][locale]
    monkeypatch.setattr(fixture.subprocess, 'run', lambda *a, **k: pytest.fail('must fail before ffmpeg'))
    with pytest.raises(ValueError, match='requires exactly'):
        fixture.weekly_clip(spec, root / 'clip')
    assert not (root / 'clip').exists()


def test_a_same_duration_recording_with_different_audio_is_rejected(weekly):
    spec, root = weekly
    wrong = root / 'wrong.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-i', spec['media']['path'], '-f', 'lavfi', '-i',
                    'sine=frequency=880:duration=20', '-map', '0:v', '-map', '1:a',
                    '-c:v', 'copy', '-c:a', 'aac', '-shortest', str(wrong)], check=True)
    spec['englishSourceMedia']['path'] = spec['media']['path']
    spec['media'] = {'path': str(wrong), 'sha256': sha(wrong)}
    with pytest.raises(ValueError, match='video audio differs'):
        fixture.weekly_clip(spec, root / 'clip')
    assert not (root / 'clip').exists()


def test_a_remux_with_identical_bound_audio_is_accepted(weekly):
    spec, root = weekly
    video = root / 'remux.mkv'
    subprocess.run(['ffmpeg', '-v', 'error', '-i', spec['media']['path'], '-c', 'copy', str(video)], check=True)
    spec['englishSourceMedia']['path'] = spec['media']['path']
    spec['media'] = {'path': str(video), 'sha256': sha(video)}
    clip = fixture.weekly_clip(spec, root / 'clip')
    assert set(clip['locales']) == set(fixture.LOCALES)


@pytest.mark.parametrize('field,message', [
    ('anchor', 'source package and anchor manifest differ'),
    ('transcript', 'source package and aligned segments differ'),
    ('media', 'source media differs from the bound source package'),
    ('window', 'window differs from the bound English source window'),
])
def test_source_package_cannot_be_replaced_by_an_unrelated_binding(weekly, field, message):
    spec, root = weekly
    source = fixture.read(root / 'source.json')
    if field == 'anchor':
        source['anchors']['artifact']['jsonSha256'] = '0' * 64
    elif field == 'transcript':
        source['transcript']['artifact']['sha256'] = '0' * 64
    elif field == 'media':
        source['source']['media']['sha256'] = '0' * 64
    else:
        source['source']['approvedWindow']['startSeconds'] = 3.0
    write(root / 'source.json', source)
    spec['englishSourcePackage']['jsonSha256'] = contract.sha(source)
    with pytest.raises(ValueError, match=message):
        fixture.weekly_clip(spec, root / 'clip')
    assert not (root / 'clip').exists()


def test_the_tail_margin_can_differ_from_the_head(weekly):
    spec, root = weekly
    clip = fixture.weekly_clip(dict(spec, marginSeconds={'before': 0.5, 'after': 1.0}), root / 'clip-asym')
    # Units 2 and 3 span 5.0-8.5 s of the sermon: 0.5 s before, 1.0 s after.
    assert clip['scope']['sermonRelativeWindowSeconds'] == [4.5, 9.5]
    assert clip['anchor']['sourceUnits'][0]['start'] == 0.5
    with pytest.raises(ValueError, match='exactly before and after'):
        fixture.weekly_clip(dict(spec, marginSeconds={'after': 1.0}), root / 'clip-bad')
    with pytest.raises(ValueError, match='must not be negative'):
        fixture.weekly_clip(dict(spec, marginSeconds={'before': -1, 'after': 1.0}), root / 'clip-neg')


def test_a_v1_spec_is_migrated_with_one_margin_for_both_ends(weekly):
    spec, root = weekly
    v1 = dict(spec, schemaVersion=fixture.CLIP_SPEC_SCHEMA_V1, marginSeconds=0.5)
    migrated = fixture.migrate_clip_spec(v1)
    assert migrated['schemaVersion'] == fixture.CLIP_SPEC_SCHEMA
    assert migrated['marginSeconds'] == {'before': 0.5, 'after': 0.5}
    assert fixture.migrate_clip_spec({k: v for k, v in v1.items() if k != 'marginSeconds'})['marginSeconds'] == {
        'before': 1.0, 'after': 1.0}
    clip = fixture.weekly_clip(v1, root / 'clip-v1')
    assert clip['scope']['sermonRelativeWindowSeconds'] == [4.5, 9.0]
    # The recorded hash is the spec as given, not its in-memory migration.
    assert clip['scope']['clipSpecSha256'] == contract.sha(v1)
    with pytest.raises(ValueError, match='use v2 for separate margins'):
        fixture.migrate_clip_spec(dict(v1, marginSeconds={'before': 0.5, 'after': 1.0}))
    with pytest.raises(ValueError, match='exactly before and after'):
        fixture.migrate_clip_spec(dict(spec, marginSeconds=0.5))


@pytest.mark.parametrize('bad', [False, True, '8', None, [], {}, float('nan'), float('inf'),
                               -float('inf'), 10 ** 400])
@pytest.mark.parametrize('side', ['before', 'after'])
def test_v2_rejects_malformed_margins_before_reading_inputs(tmp_path, bad, side):
    margin = {'before': 0.0, 'after': 8.0, side: bad}
    spec = {'schemaVersion': fixture.CLIP_SPEC_SCHEMA, 'marginSeconds': margin}
    with pytest.raises(ValueError, match='finite numbers'):
        fixture.weekly_clip(spec, tmp_path / 'clip')
    assert not (tmp_path / 'clip').exists()


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), -float('inf'), 10 ** 400])
def test_v1_rejects_nonfinite_margins(tmp_path, bad):
    spec = {'schemaVersion': fixture.CLIP_SPEC_SCHEMA_V1, 'marginSeconds': bad}
    with pytest.raises(ValueError, match='finite numbers'):
        fixture.weekly_clip(spec, tmp_path / 'clip')
    assert not (tmp_path / 'clip').exists()


@pytest.mark.parametrize('schema,margin', [
    (fixture.CLIP_SPEC_SCHEMA_V1, 0),
    (fixture.CLIP_SPEC_SCHEMA, {'before': 0, 'after': 8.5}),
])
def test_zero_and_finite_numeric_margins_remain_valid(schema, margin):
    migrated = fixture.migrate_clip_spec({'schemaVersion': schema, 'marginSeconds': margin})
    assert migrated['marginSeconds'] == ({'before': 0, 'after': 0} if schema == fixture.CLIP_SPEC_SCHEMA_V1 else margin)
