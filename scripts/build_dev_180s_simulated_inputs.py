"""Build an explicitly simulated, zero-API beta/dev delivery fixture.

Two sources feed the same assembly:

- the fixed 180 s clip from the 2026-10-01 Dev rerun (the default);
- ``--clip-spec SPEC.json``: a contiguous run of English units cut from a weekly
  run's frozen artifacts (anchor manifest, aligned segments, per-locale candidate
  and audio package). The source media, the aligned segments and the anchors are
  cut and rebased to the clip; each locale keeps its candidate groups and unit
  audio for those units, and its track is the units' audio joined in order.

Approval-shaped data is test input authorized by the operator, never a real
content review. Original production artifacts are read-only. No publish action.
"""
from __future__ import annotations
import argparse
import ast
import copy
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from uuid import uuid4
import subprocess
from pathlib import Path
# Support both python -m scripts.<name> and direct script invocation.
if __package__ in (None, ''):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.source import english_source_package as source_builder
from tongxing_production.source import english_source_judge as source_judge
from scripts import build_full_video_app_release as release
from scripts import delivery_contract as contract
from scripts import produce_target_language_candidate as candidate_validator
from scripts import sermon_unified_delivery as delivery
from scripts import sermon_unified_reviews as reviews
from scripts import study_artifacts

ROOT = Path(__file__).resolve().parents[1]
SIM = 'simulation test only - not a real human approval'
STAMP = '2026-10-05T00:00:00Z'
LOCALES = ['zh-Hans', 'ko', 'es']
LEGACY_PAGE_ID = 'mockup-20261005-dev-180s'
TEST_ROOT = ROOT / 'artifacts/dev-180s-page-test-20261004'
CLIP_SPEC_SCHEMA = 'sermon-dev-clip-spec-v2'
CLIP_SPEC_SCHEMA_V1 = 'sermon-dev-clip-spec-v1'
MEDITATION_PROMPT = {
    'zh-Hans': '默想问题：这段文字怎样影响我对技术与盼望的理解？\n',
    'ko': '묵상 질문: 이 내용은 기술과 소망에 대한 나의 이해에 어떤 영향을 줍니까?\n',
    'es': 'Pregunta para meditar: ¿Cómo influye este texto en mi comprensión de la tecnología y la esperanza?\n'}
CLIP_MEDITATION_PROMPT = {
    'zh-Hans': '默想问题：这段经文和讲解对我今天有什么提醒？\n',
    'ko': '묵상 질문: 이 말씀과 설명은 오늘 나에게 무엇을 일깨워 줍니까?\n',
    'es': 'Pregunta para meditar: ¿Qué me recuerda hoy este pasaje y su explicación?\n'}


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n'
    path.write_text(data)
    return path


def ref(path, canonical=False):
    result = {'path': str(path.resolve()), 'sha256': sha(path)}
    if canonical:
        result['jsonSha256'] = contract.sha(read(path))
    return result


def duration(path):
    return float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries',
        'format=duration', '-of', 'default=nw=1:nk=1', str(path)], text=True))


def clock(seconds):
    whole, fraction = divmod(seconds, 1)
    hours, rest = divmod(int(whole), 3600)
    return '%02d:%02d:%09.6f' % (hours, rest // 60, rest % 60 + fraction)


def fixture_identity(run_id=None, page_id=None, prefix='mockup-dev-180s-'):
    """Fresh runs get immutable paths; explicit legacy IDs remain available."""
    if run_id is None:
        run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:12]
    contract.require(isinstance(run_id, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', run_id), 'Unsafe run ID')
    if page_id is None:
        page_id = prefix + run_id
    contract.require(isinstance(page_id, str) and re.fullmatch(r'(?:mockup|dryrun|dev)-[A-Za-z0-9][A-Za-z0-9_-]{0,139}', page_id), 'Unsafe simulation page ID')
    return run_id, page_id


def fixture_output(out, run_id):
    out = Path(out if out is not None else TEST_ROOT / run_id / 'simulated-inputs').resolve()
    contract.require(out.is_relative_to(TEST_ROOT.resolve()) and out != TEST_ROOT.resolve(),
                     'Simulated inputs must remain inside the dedicated ignored test root')
    contract.require(not out.exists(), 'Use a new simulated input output directory')
    return out


def build(out=None, *, run_id=None, page_id=None, clip_spec=None):
    if clip_spec is not None:
        run_id, page_id = fixture_identity(run_id, page_id, prefix='mockup-dev-clip-')
        out = fixture_output(out, run_id)
        out.mkdir(parents=True, exist_ok=False)
        return assemble(out, run_id, page_id, **weekly_clip(read(clip_spec), out / 'clip'))
    run_id, page_id = fixture_identity(run_id, page_id)
    out = fixture_output(out, run_id)
    out.mkdir(parents=True, exist_ok=False)
    return assemble(out, run_id, page_id, **fixed_180s())


def fixed_180s():
    """The 2026-10-01 Dev rerun's fixed 180 s clip, unchanged."""
    old = ROOT / 'artifacts/dev-full-rerun-20261001'
    media_root = old / 'dev-candidate/hosting/public/media/dryrun-20261001-dev-full-180s'
    media = media_root / 'source.mp4'
    assert sha(media) == '79bada8f2e960adb470a146f183449db433308b53c20d03ea9c7e2e0a66e906b'
    anchor = read(old / 'anchor-manifest.json')
    assert len(anchor['sourceUnits']) == 39
    locales = {}
    for locale in LOCALES:
        preview = old / 'diagnostic-previews' / locale / 'native-1'
        candidate = read(preview / 'candidate.json')
        assert len(candidate['groups']) == 13
        locales[locale] = {'candidate': candidate, 'track': next(media_root.glob(locale + '-*.mp3')),
                           'wavs': [preview / 'units' / ('unit-%04d.wav' % i) for i in range(len(candidate['groups']))]}
    return {'media': media, 'segments': read(old / 'aligned-segments.json'), 'anchor': anchor, 'locales': locales,
            'source_url': 'https://simulation-test-only.invalid/unverified-original-url/fixed-180s',
            'source_id': 'simulation-test-only-fixed-180s', 'service_date': '2026-09-27', 'label': '固定三分钟',
            'proposal_title': '固定 180 秒', 'title': '技术与人的盼望', 'scripture': '三分钟片段无独立经文标注',
            'outline': '技术许诺与人的问题', 'summary': '沿用历史译文和音轨', 'meditation': MEDITATION_PROMPT,
            'scope': {'originalSourceWindowSeconds': [60, 240]}}


def _shift(value, offset):
    """Rebase a time that may be a number or a numeric string, keeping its type."""
    if isinstance(value, str):
        return repr(round(float(value) - offset, 6))
    return round(value - offset, 6)


def _shift_times(rows, offset):
    for row in rows:
        for key in ('start', 'end'):
            if key in row:
                row[key] = round(row[key] - offset, 6)
        for nested in ('phones',):
            if isinstance(row.get(nested), list):
                _shift_times(row[nested], offset)
    return rows


def _shift_segment(segment, offset):
    segment = copy.deepcopy(segment)
    for key in ('start', 'end'):
        segment[key] = _shift(segment[key], offset)
    for key in ('wordTimes', 'phones'):
        value = segment.get(key)
        if isinstance(value, str) and value.startswith('['):
            segment[key] = repr(_shift_times(ast.literal_eval(value), offset))
        elif isinstance(value, list):
            segment[key] = _shift_times(copy.deepcopy(value), offset)
    return segment


def _audio_digest(path):
    """Compare the full recording's decoded audio on a common PCM clock."""
    return subprocess.check_output([
        'ffmpeg', '-v', 'error', '-i', str(path), '-map', '0:a:0',
        '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le',
        '-f', 'hash', '-hash', 'sha256', '-'], text=True).strip()


def migrate_clip_spec(spec):
    """Return a v2 clip spec. v1 has one number for both margins (default 1 s); v2 needs {"before", "after"}."""
    version = spec.get('schemaVersion')
    if version == CLIP_SPEC_SCHEMA:
        margin = spec.get('marginSeconds')
        contract.require(isinstance(margin, dict) and set(margin) == {'before', 'after'},
                         'marginSeconds needs exactly before and after')
        migrated = spec
    else:
        contract.require(version == CLIP_SPEC_SCHEMA_V1, 'Unsupported clip spec')
        margin = spec.get('marginSeconds', 1.0)
        contract.require(isinstance(margin, (int, float)) and not isinstance(margin, bool),
                         'A v1 clip spec takes one number for marginSeconds; use v2 for separate margins')
        migrated = dict(spec, schemaVersion=CLIP_SPEC_SCHEMA, marginSeconds={'before': margin, 'after': margin})
    for margin in migrated['marginSeconds'].values():
        contract.require(isinstance(margin, (int, float)) and not isinstance(margin, bool),
                         'Clip margins must be finite numbers')
        try:
            finite = math.isfinite(float(margin))
        except OverflowError:
            finite = False
        contract.require(finite, 'Clip margins must be finite numbers')
        contract.require(margin >= 0, 'Clip margins must not be negative')
    return migrated


def weekly_clip(spec, clip_dir):
    """Cut a contiguous run of English units, with each locale's text and unit audio, from a weekly run."""
    original_sha = contract.sha(spec)
    spec = migrate_clip_spec(spec)
    contract.require(set(spec.get('locales', {})) == set(LOCALES),
                     'Clip rehearsal requires exactly zh-Hans, ko and es')
    lo, hi = spec['unitRange']
    anchor_full = read(spec['anchor']['path'])
    contract.require(contract.sha(anchor_full) == spec['anchor']['jsonSha256'], 'Anchor manifest differs from the clip spec')
    contract.require(sha(spec['alignedSegments']['path']) == anchor_full['input']['mfaSegmentsSha256'],
                     'Aligned segments are not the ones the anchor manifest binds')
    contract.require(sha(spec['media']['path']) == spec['media']['sha256'], 'Source media differs from the clip spec')
    source_full = read(spec['englishSourcePackage']['path'])
    source_sha = contract.sha(source_full)
    contract.require(source_sha == spec['englishSourcePackage']['jsonSha256'], 'English source package differs from the clip spec')
    contract.require(source_full['anchors']['artifact']['jsonSha256'] == contract.sha(anchor_full),
                     'English source package and anchor manifest differ')
    contract.require(source_full['transcript']['artifact']['sha256'] == sha(spec['alignedSegments']['path']),
                     'English source package and aligned segments differ')
    source_media = source_full['source']['media']
    contract.require(spec['englishSourceMedia']['sha256'] == source_media['sha256']
                     and spec['englishSourceMedia']['durationSeconds'] == source_media['durationSeconds'],
                     'English source media differs from the bound source package')
    contract.require(float(spec['approvedWindowStartSeconds']) == source_full['source']['approvedWindow']['startSeconds'],
                     'Clip window differs from the bound English source window')
    contract.require(spec['serviceDate'] == source_full['source']['serviceDate'],
                     'Clip service date differs from the bound English source')
    if spec['media']['sha256'] != source_media['sha256']:
        source_audio = spec['englishSourceMedia'].get('path')
        contract.require(source_audio is not None and sha(source_audio) == source_media['sha256'],
                         'A different video requires the hash-bound English source media file')
        contract.require(_audio_digest(spec['media']['path']) == _audio_digest(source_audio),
                         'Clip video audio differs from the bound English source media')
    # Audio identity alone is insufficient if the recording clocks differ.
    contract.require(abs(duration(spec['media']['path']) - float(spec['englishSourceMedia']['durationSeconds'])) <= 0.1,
                     'The clip video and the English source media are not the same recording timeline')
    units = anchor_full['sourceUnits']
    contract.require(isinstance(lo, int) and isinstance(hi, int) and 0 <= lo < hi <= len(units), 'Invalid unit range')
    sentences = {unit['sourceSentenceId'] for unit in units[lo:hi]}
    contract.require(not any(unit['sourceSentenceId'] in sentences for unit in units[:lo] + units[hi:]),
                     'Clip unit range must retain complete source sentences')
    # A dub usually runs longer than its English, so the tail needs room the head does not
    # (2026-10-12 Korean clip: 3 s past a 1 s tail).
    before, after = float(spec['marginSeconds']['before']), float(spec['marginSeconds']['after'])
    start = max(0.0, units[lo]['start'] - before)
    end = units[hi - 1]['end'] + after
    window_start = float(spec['approvedWindowStartSeconds'])
    clip_dir.mkdir(parents=True)
    media = clip_dir / 'source.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-ss', '%.3f' % (window_start + start), '-i', spec['media']['path'],
                    '-t', '%.3f' % (end - start), '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '28',
                    '-c:a', 'aac', '-b:a', '96k', '-movflags', '+faststart', str(media)], check=True)
    selected = [copy.deepcopy(unit) for unit in units[lo:hi]]
    ids = {unit['sourceUnitId'] for unit in selected}
    sentences = {unit['sourceSentenceId'] for unit in selected}
    for unit in selected:
        unit['start'], unit['end'] = round(unit['start'] - start, 6), round(unit['end'] - start, 6)
        _shift_times(unit.get('words', []), start)
    requests = []
    for row in anchor_full['translationRequests']:
        if set(row['sourceUnitIds']) <= ids:
            row = copy.deepcopy(row)
            if 'stableAtSeconds' in row:
                row['stableAtSeconds'] = _shift(row['stableAtSeconds'], start)
            requests.append(row)
        else:
            contract.require(not set(row['sourceUnitIds']) & ids, 'A translation group straddles the clip boundary')
    anchor = copy.deepcopy(anchor_full)
    anchor['sourceUnits'] = selected
    anchor['translationRequests'] = requests
    anchor['issues'] = [issue for issue in anchor_full.get('issues', []) if issue.get('sourceSentenceId') in sentences]
    per_sentence = {}
    for unit in selected:
        per_sentence[unit['sourceSentenceId']] = per_sentence.get(unit['sourceSentenceId'], 0) + 1
    anchor['counts'] = dict(anchor_full.get('counts', {}), sourceUnits=len(selected), sourceSentences=len(sentences),
                            sourceWords=sum(len(unit.get('sourceWordIds', [])) for unit in selected),
                            longSentencesSplit=sum(count > 1 for count in per_sentence.values()))
    segments = [_shift_segment(segment, start) for segment in read(spec['alignedSegments']['path'])
                if float(segment['start']) >= start - 1e-6 and float(segment['end']) <= end + 1e-6]
    contract.require(segments, 'No aligned segment lies inside the clip')
    contract.require(all(any(float(segment['start']) <= unit['start'] + 1e-6
                                 and float(segment['end']) >= unit['end'] - 1e-6
                                 for segment in segments) for unit in selected),
                     'Clip margin omits an aligned segment for a retained source unit')
    groups_wanted = [row['translationGroupId'] for row in requests]
    locales = {}
    for locale, paths in spec['locales'].items():
        candidate = read(paths['candidate'])
        package = read(paths['audioPackage'])
        contract.require(candidate.get('anchorManifestSha256') == contract.sha(anchor_full),
                         locale + ': candidate belongs to another anchor manifest')
        contract.require(candidate.get('englishSourcePackageJsonSha256') == source_sha
                         and package.get('englishSourcePackageJsonSha256') == source_sha,
                         locale + ': candidate or audio belongs to another English source package')
        contract.require(contract.sha(candidate) == package['targetLanguageCandidateJsonSha256'],
                         locale + ': the audio package was not rendered from this candidate')
        by_group = {group['translationGroupId']: group for group in candidate['groups']}
        audio = {unit['textGroupId']: unit for unit in package['units']}
        contract.require(all(gid in by_group and gid in audio for gid in groups_wanted), locale + ': clip groups missing')
        kept = set(groups_wanted)
        candidate['groups'] = [by_group[gid] for gid in groups_wanted]
        for section in ('modelReview', 'humanReview'):
            if isinstance(candidate.get(section), dict) and isinstance(candidate[section].get('reviewedGroupIds'), list):
                candidate[section]['reviewedGroupIds'] = [g for g in candidate[section]['reviewedGroupIds'] if g in kept]
        wavs = []
        for gid in groups_wanted:
            wav = Path(audio[gid]['audio']['path'])
            contract.require(sha(wav) == audio[gid]['audio']['sha256'], locale + ': unit audio changed for ' + gid)
            wavs.append(wav)
        listing = clip_dir / (locale + '-units.txt')
        listing.write_text(''.join("file '%s'\n" % str(wav).replace("'", "'\\''") for wav in wavs))
        track = clip_dir / (locale + '-clip.mp3')
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'concat', '-safe', '0', '-i', str(listing),
                        '-c:a', 'libmp3lame', '-b:a', '128k', str(track)], check=True)
        locales[locale] = {'candidate': candidate, 'wavs': wavs, 'track': track}
    title = spec.get('title', '本周片段')
    return {'media': media, 'segments': segments, 'anchor': anchor, 'locales': locales,
            'source_url': 'https://simulation-test-only.invalid/weekly-clip/' + spec.get('pageId', 'unknown'),
            'source_id': 'simulation-test-only-weekly-clip', 'service_date': spec['serviceDate'],
            'label': '本周片段', 'proposal_title': '本周片段 %d 句' % len(selected), 'title': title,
            'scripture': spec.get('scripture', '片段经文未单独标注'), 'outline': spec.get('outline', title),
            'summary': '沿用本周已发布的译文和单句音频', 'meditation': CLIP_MEDITATION_PROMPT,
            # Layer 3's clip timeline map requires the window approval to name the media it approves.
            'window_media_bound': True,
            'scope': {'originalSourceWindowSeconds': [round(window_start + start, 3), round(window_start + end, 3)],
                      'sermonRelativeWindowSeconds': [round(start, 3), round(end, 3)], 'unitRange': [lo, hi],
                      'clipSpecSha256': original_sha, 'sourcePageId': spec.get('pageId'),
                      'englishSourceMediaSha256': spec['englishSourceMedia']['sha256']}}


def assemble(out, run_id, page_id, *, media, segments, anchor, locales, source_url, source_id, service_date, label,
             proposal_title, title, scripture, outline, summary, meditation, scope, window_media_bound=False):
    contract.require(set(locales) == set(LOCALES), 'Rehearsal requires exactly zh-Hans, ko and es')
    template = ROOT / 'artifacts/unified-cli-acceptance/native-four-product-fixture-v2'
    media_duration = duration(media)
    aligned = save(out / 'aligned-segments.json', segments)
    anchor = copy.deepcopy(anchor)
    anchor['input']['mfaSegmentsSha256'] = sha(aligned)
    anchor_path = save(out / 'anchor.json', anchor)
    unit_ids = [x['sourceUnitId'] for x in anchor['sourceUnits']]
    url_sha = hashlib.sha256(source_url.encode()).hexdigest()
    summary_path = save(out / 'summary.json', {
        'sourceUrl': source_url, 'sourceDurationSeconds': media_duration,
        'sermonStartSeconds': 0, 'sermonEndSeconds': media_duration, 'readingAligner': 'mfa',
        'models': {'referenceAsr': 'gpt-transcribe (historical cache)'},
        'pipelineInputIdentity': {'sourceAudio': {'sha256': sha(media), 'sizeBytes': media.stat().st_size}}})
    approval = save(out / 'window-review.json', {'status': 'approved', 'humanApproval': True,
        'sourceUrlHash': url_sha, 'approvedBy': SIM, 'approvalText': SIM,
        'startTime': '00:00:00', 'endTime': clock(media_duration),
        **({'sourceMediaSha256': sha(media)} if window_media_bound else {})})
    english_review = save(out / 'english-review.json', {
        'schemaVersion': 'sermon-english-source-review-v1', 'alignedSegmentsSha256': sha(aligned),
        'anchorManifestJsonSha256': contract.sha(anchor), 'humanApproval': True,
        'reviewedBy': SIM, 'reviewedAt': STAMP, 'reviewedSourceUnitIds': unit_ids,
        'checks': {x: 'approved' for x in source_builder.APPROVED_CHECKS}, 'notes': SIM})
    sentence_ids = list(dict.fromkeys(x['sourceSentenceId'] for x in anchor['sourceUnits']))
    judge = save(out / 'simulated-machine-review.json', {
        'schemaVersion': source_builder.MACHINE_JUDGE_SCHEMA_VERSION, 'reviewType': 'model',
        'humanApproval': False, 'implementationSha256': sha(Path(source_judge.__file__)),
        'model': source_builder.MACHINE_JUDGE_MODEL, 'reasoningEffort': source_builder.MACHINE_JUDGE_REASONING_EFFORT,
        'promptVersion': source_builder.MACHINE_JUDGE_SCHEMA_VERSION, 'thresholds': source_builder.MACHINE_JUDGE_THRESHOLDS,
        'alignedSegmentsSha256': sha(aligned), 'anchorManifestJsonSha256': contract.sha(anchor),
        'reviewedSourceSentenceIds': sentence_ids,
        'reviewedManifestIssueJsonSha256s': [contract.sha(x) for x in anchor['issues']],
        'status': 'approved_for_layer2_shadow', 'layer2DevelopmentEligible': True,
        'productionTranslationEligible': False, 'deterministicReview': {'status': 'pass', 'checks': [
            {'status': 'pass', 'evidence': SIM}], 'issues': []},
        'sentences': [{'sourceSentenceId': x, 'verdict': 'pass', 'risk': 'low',
            'checks': {k: 'pass' for k in source_builder.MACHINE_JUDGE_CHECKS},
            'unresolvedIssues': [], 'evidence': SIM} for x in sentence_ids],
        'counts': {'sourceSentences': len(sentence_ids), 'sourceUnits': len(unit_ids),
            'manifestIssues': len(anchor['issues']), 'sentencePass': len(sentence_ids), 'sentenceFail': 0, 'highRiskSentences': 0},
        'requestIds': ['simulation-test-only-no-api'], 'unresolvedIssues': [], 'simulationNotice': SIM})
    source = source_builder.build_package(aligned, anchor_path, summary_path=summary_path,
        approval_evidence_path=approval, review_path=english_review, machine_judge_path=judge,
        source_id=source_id, source_url_hash=url_sha, service_date=service_date)
    source_builder.validate_ready_package(source)
    candidate_validator.validate_source_for_translation(source, anchor)
    source_path = save(out / 'source.json', source)
    source_sha = contract.sha(source)
    config = copy.deepcopy(read(template / 'config.json'))
    config.update(pageId=page_id, date=service_date, locales=list(locales), requiredEndpoints=['dev', 'beta', 'production_ios', 'production_web'],
        workRoot=str(out / 'work'), action='prepare')
    route = {'channel': 'dev', 'project': 'ai-for-god-sermon-audio-dev', 'site': 'ai-for-god-sermon-audio-dev',
             'origin': 'https://ai-for-god-sermon-audio-dev.web.app'}
    config['intent'] = dict(route, schemaVersion='sermon-release-intent-v1', environment='dev')
    config['routes'] = {'dev': route}
    config['inputs'] = {'source': ref(source_path)}
    for name in delivery.MAPS:
        config['inputs'][name] = {}
    metadata = read(template / 'metadata_approval.json')
    metadata.update(pageId=page_id, date=service_date, approvedLocales=list(locales),
        schemaVersion='sermon-dev-simulated-metadata-v1', decision='simulated_test_only',
        releaseIntent=config['intent'], approvalText=SIM, reviewer='simulation-test-only', recordedAt=STAMP, locales={})
    for locale, inputs in locales.items():
        loc = out / locale
        candidate = copy.deepcopy(inputs['candidate'])
        candidate.update(englishSourcePackageJsonSha256=source_sha,
            anchorManifestSha256=contract.sha(anchor), status='human_translation_approved', releaseEligible=False)
        ids = [g['translationGroupId'] for g in candidate['groups']]
        candidate['humanReview'] = {'translation': 'approved', 'reviewer': SIM,
            'reviewedAt': STAMP, 'reviewedGroupIds': ids}
        candidate_path = save(loc / 'candidate.json', candidate)
        release.stage.read_package(candidate_path, 'sermon-target-language-candidate-v2.schema.json')
        candidate_sha = contract.sha(candidate)
        text_review = read(template / 'full_review_receipt.json')
        text_review.update(targetLocale=locale, englishSourcePackageJsonSha256=source_sha,
            anchorManifestJsonSha256=contract.sha(anchor), translationPolicySha256=candidate['translationPolicySha256'],
            candidateJsonSha256=candidate_sha, reviewer=SIM, reviewedAt=STAMP, reviewedGroupIds=ids,
            groupReviews=[{'translationGroupId': gid, 'decision': 'approved', 'evidence': SIM} for gid in ids])
        text_review_path = save(loc / 'translation-review.json', text_review)
        reviews.validate_review('translation', text_review_path,
            inputs={'source': source_path, 'anchor': anchor_path, 'candidate': candidate_path})
        audio = read(template / 'audio_package.json')
        track = inputs['track']
        audio.update(packageId=page_id + '-' + locale, targetLocale=locale,
            englishSourcePackageJsonSha256=source_sha, targetLanguageCandidateJsonSha256=candidate_sha,
            track=ref(track), units=[])
        audio['humanReview'].update(reviewedBy=SIM, reviewedAt=STAMP)
        cues = []
        audio_cues = []
        elapsed = 0
        for i, group in enumerate(candidate['groups']):
            wav = inputs['wavs'][i]
            seconds = duration(wav)
            audio['units'].append({'textGroupId': ids[i], 'targetTextSha256': hashlib.sha256(group['targetText'].encode()).hexdigest(),
                'audio': ref(wav), 'durationSeconds': seconds})
            matched = [x for x in anchor['sourceUnits'] if x['sourceUnitId'] in group['sourceUnitIds']]
            cues.append({'textGroupId': ids[i], 'start': min(x['start'] for x in matched),
                'end': max(x['end'] for x in matched), 'text': group['targetText'], 'sourceUnitIds': group['sourceUnitIds']})
            audio_cues.append({'textGroupId': ids[i], 'start': elapsed, 'end': elapsed + seconds, 'text': group['targetText']})
            elapsed += seconds
        audio['captions'] = ref(save(loc / 'captions.json', {'cues': audio_cues}))
        audio['schedule'] = ref(save(loc / 'schedule.json', {'simulationNotice': SIM,
            'synchronizationAcceptedForTestOnly': True, 'audioDurationSeconds': duration(track),
            'sourceDurationSeconds': media_duration, 'cues': audio_cues}), True)
        audio['machineScreening']['model'] = SIM
        audio_path = save(loc / 'audio-package.json', audio)
        screening = read(template / 'audio_screening_receipt.json')
        screening.update(targetLocale=locale, trackSha256=sha(track), model=SIM, reviewedGroupIds=ids,
            unitAudioSha256s=[u['audio']['sha256'] for u in audio['units']], results=[])
        for unit, group in zip(audio['units'], candidate['groups']):
            screening['results'].append({'textGroupId': unit['textGroupId'], 'targetTextSha256': unit['targetTextSha256'],
                'audioSha256': unit['audio']['sha256'], 'recognized': SIM, 'similarity': 1,
                'differences': [], 'status': 'pass'})
        screening_path = save(loc / 'audio-screening.json', screening)
        audio_review = read(template / 'audio_review_receipt.json')
        audio_review.update(targetLocale=locale, englishSourcePackageJsonSha256=source_sha,
            targetLanguageCandidateJsonSha256=candidate_sha, targetLanguageAudioPackageJsonSha256=contract.sha(audio),
            trackSha256=sha(track), machineScreeningReceiptJsonSha256=contract.sha(screening),
            reviewedBy=SIM, reviewedAt=STAMP, reviewedUnitIds=ids)
        audio_review_path = save(loc / 'audio-review.json', audio_review)
        reviews.validate_review('audio', audio_review_path, inputs={'source': source_path,
            'package': audio_path, 'screening': screening_path})
        display = {'series': '[模拟审核测试] ' + label, 'title': '[模拟审核测试] ' + title + ' — ' + locale,
            'speaker': '原录音讲员（测试身份未核验）', 'scripture': scripture,
            'summary': '[模拟审核测试] simulation test only；' + summary + '；真实内容、听审与同步未批准。',
            'outline': ['[模拟审核测试] ' + outline]}
        metadata['locales'][locale] = display
        content = dict(display, schemaVersion='sermon-full-video-text-content-v2', pageId=page_id,
            targetLocale=locale, sourceLocale='en', status='human_reviewed',
            englishSourcePackageJsonSha256=source_sha, targetLanguageCandidateJsonSha256=candidate_sha,
            sourceMediaSha256=sha(media), durationSeconds=media_duration,
            audioDurationSeconds=release.stage.decode_audio(track, locale + ' measured audio clock'), reviewMode='simulation',
            sourceVideoUrl='/media/' + page_id + '/source.mp4', cues=cues,
            sourceWindow={'schemaVersion': 'sermon-original-recording-window-v1', 'mediaSha256': sha(media),
                'startSeconds': 0, 'endSeconds': media_duration})
        content_path = save(loc / 'full-content.json', content)
        names = {'full_candidate': candidate_path, 'spoken_candidate': candidate_path,
            'full_review_receipt': text_review_path, 'spoken_review_receipt': text_review_path,
            'audio_package': audio_path, 'audio_review_receipt': audio_review_path,
            'audio_screening_receipt': screening_path, 'full_content': content_path}
        for kind in ('outline', 'meditation'):
            sections = [{'title': '[模拟审核测试] ' + kind + ' ' + str(i + 1),
                'body': group['targetText'] if kind == 'outline' else meditation[locale] + group['targetText'],
                'sourceUnitIds': group['sourceUnitIds']}
                for i, group in enumerate(candidate['groups'])]
            artifact = study_artifacts.produce(kind, sections, page_id=page_id, locale=locale,
                source_sha=source_sha, text_sha=candidate_sha, producer_identity=SIM)
            artifact_path = save(loc / (kind + '.json'), artifact)
            review = read(template / 'outline_review.json')
            review.update(kind=kind, pageId=page_id, locale=locale, sourcePackageSha256=source_sha,
                textCandidateSha256=candidate_sha, artifactSha256=contract.sha(artifact),
                reviewedBy=SIM, reviewedAt=STAMP)
            study_artifacts.ingest_review(artifact, review)
            names[kind] = artifact_path
            names[kind + '_review'] = save(loc / (kind + '-review.json'), review)
        for name, path in names.items():
            config['inputs'][name][locale] = ref(path)
    proposal = out / 'metadata-proposal.md'
    proposal.write_text('# [模拟审核测试] ' + proposal_title + '\n\n' + SIM + '\n' + json.dumps(metadata['locales'], ensure_ascii=False, indent=2))
    metadata['proposalFileSha256'] = sha(proposal)
    config['inputs']['metadata_approval'] = ref(save(out / 'metadata-approval.json', metadata))
    config['inputs']['metadata_proposal'] = ref(proposal)
    config_path = save(out / 'delivery-draft.json', config)
    frozen_path = out / 'delivery.json'
    plan = delivery.freeze(config_path, frozen_path)
    result = delivery.execute(frozen_path, plan['planHash'])
    save(out / 'prepare-result.json', result)
    # The normal builder does not copy original video URLs; add a separate bound
    # media artifact for the caller to include in test deployment, never replace.
    report = {'simulationOnly': True, 'productionEligible': False, 'actualHumanApproval': False,
        'notice': SIM, 'runId': run_id, 'pageId': page_id, 'newApiCalls': 0, 'sourceUrlVerified': False,
        'sourceMedia': ref(media), 'sourceMediaPublicPath': '/media/' + page_id + '/source.mp4',
        **scope, 'testMediaWindowSeconds': [0, media_duration],
        'originalAnchorIssues': anchor['issues'], 'sourceUnitCount': len(unit_ids),
        'groupsPerLocale': len(next(iter(locales.values()))['candidate']['groups']),
        'audioDurations': {loc: duration(inputs['track']) for loc, inputs in locales.items()},
        'result': result, 'frozenConfig': ref(frozen_path)}
    save(out / 'simulation-scope-report.json', report)
    print(json.dumps({'config': str(frozen_path), 'status': result['status'],
        'runId': run_id, 'pageId': page_id, 'fourProducts': result['fourProducts'], 'productionEligible': False,
        'sourceVideo': str(media), 'scopeReport': str(out / 'simulation-scope-report.json')}, ensure_ascii=False))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--run-id')
    parser.add_argument('--page-id')
    parser.add_argument('--clip-spec', type=Path, help=CLIP_SPEC_SCHEMA + ' JSON naming a weekly run and a unit range')
    args = parser.parse_args()
    build(args.out, run_id=args.run_id, page_id=args.page_id, clip_spec=args.clip_spec)
