"""Build an explicitly simulated, zero-API 180s beta/dev delivery fixture.

Approval-shaped data is test input authorized by the operator, never a real
content review. Original production artifacts are read-only. No publish action.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from uuid import uuid4
import subprocess
from pathlib import Path
# Support both python -m scripts.<name> and direct script invocation.
if __package__ in (None, ''):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import build_english_source_package as source_builder
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


def fixture_identity(run_id=None, page_id=None):
    """Fresh runs get immutable paths; explicit legacy IDs remain available."""
    if run_id is None:
        run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:12]
    contract.require(isinstance(run_id, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', run_id), 'Unsafe run ID')
    if page_id is None:
        page_id = 'mockup-dev-180s-' + run_id
    contract.require(isinstance(page_id, str) and re.fullmatch(r'(?:mockup|dryrun|dev)-[A-Za-z0-9][A-Za-z0-9_-]{0,139}', page_id), 'Unsafe simulation page ID')
    return run_id, page_id


def fixture_output(out, run_id):
    out = Path(out if out is not None else TEST_ROOT / run_id / 'simulated-inputs').resolve()
    contract.require(out.is_relative_to(TEST_ROOT.resolve()) and out != TEST_ROOT.resolve(),
                     'Simulated inputs must remain inside the dedicated ignored test root')
    contract.require(not out.exists(), 'Use a new simulated input output directory')
    return out


def build(out=None, *, run_id=None, page_id=None):
    run_id, page_id = fixture_identity(run_id, page_id)
    out = fixture_output(out, run_id)
    out.mkdir(parents=True, exist_ok=False)
    old = ROOT / 'artifacts/dev-full-rerun-20261001'
    template = ROOT / 'artifacts/unified-cli-acceptance/native-four-product-fixture-v2'
    media_root = old / 'dev-candidate/hosting/public/media/dryrun-20261001-dev-full-180s'
    media = media_root / 'source.mp4'
    media_duration = duration(media)
    assert sha(media) == '79bada8f2e960adb470a146f183449db433308b53c20d03ea9c7e2e0a66e906b'
    segments = read(old / 'aligned-segments.json')
    aligned = save(out / 'aligned-segments.json', segments)
    anchor = read(old / 'anchor-manifest.json')
    anchor['input']['mfaSegmentsSha256'] = sha(aligned)
    anchor_path = save(out / 'anchor.json', anchor)
    unit_ids = [x['sourceUnitId'] for x in anchor['sourceUnits']]
    assert len(unit_ids) == 39
    url = 'https://simulation-test-only.invalid/unverified-original-url/fixed-180s'
    url_sha = hashlib.sha256(url.encode()).hexdigest()
    summary = save(out / 'summary.json', {
        'sourceUrl': url, 'sourceDurationSeconds': media_duration,
        'sermonStartSeconds': 0, 'sermonEndSeconds': media_duration, 'readingAligner': 'mfa',
        'models': {'referenceAsr': 'gpt-transcribe (historical cache)'},
        'pipelineInputIdentity': {'sourceAudio': {'sha256': sha(media), 'sizeBytes': media.stat().st_size}}})
    approval = save(out / 'window-review.json', {'status': 'approved', 'humanApproval': True,
        'sourceUrlHash': url_sha, 'approvedBy': SIM, 'approvalText': SIM,
        'startTime': '00:00:00', 'endTime': '00:03:00.013167'})
    english_review = save(out / 'english-review.json', {
        'schemaVersion': 'sermon-english-source-review-v1', 'alignedSegmentsSha256': sha(aligned),
        'anchorManifestJsonSha256': contract.sha(anchor), 'humanApproval': True,
        'reviewedBy': SIM, 'reviewedAt': STAMP, 'reviewedSourceUnitIds': unit_ids,
        'checks': {x: 'approved' for x in source_builder.APPROVED_CHECKS}, 'notes': SIM})
    sentence_ids = list(dict.fromkeys(x['sourceSentenceId'] for x in anchor['sourceUnits']))
    judge = save(out / 'simulated-machine-review.json', {
        'schemaVersion': source_builder.MACHINE_JUDGE_SCHEMA_VERSION, 'reviewType': 'model',
        'humanApproval': False, 'implementationSha256': sha(ROOT / 'scripts/judge_english_source_for_translation.py'),
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
    source = source_builder.build_package(aligned, anchor_path, summary_path=summary,
        approval_evidence_path=approval, review_path=english_review, machine_judge_path=judge,
        source_id='simulation-test-only-fixed-180s', source_url_hash=url_sha, service_date='2026-09-27')
    source_builder.validate_ready_package(source)
    candidate_validator.validate_source_for_translation(source, anchor)
    source_path = save(out / 'source.json', source)
    source_sha = contract.sha(source)
    config = copy.deepcopy(read(template / 'config.json'))
    config.update(pageId=page_id, date='2026-09-27', locales=LOCALES, requiredEndpoints=['dev', 'beta', 'production_ios', 'production_web'],
        workRoot=str(out / 'work'), action='prepare')
    route = {'channel': 'dev', 'project': 'ai-for-god-sermon-audio-dev', 'site': 'ai-for-god-sermon-audio-dev',
             'origin': 'https://ai-for-god-sermon-audio-dev.web.app'}
    config['intent'] = dict(route, schemaVersion='sermon-release-intent-v1', environment='dev')
    config['routes'] = {'dev': route}
    config['inputs'] = {'source': ref(source_path)}
    for name in delivery.MAPS:
        config['inputs'][name] = {}
    metadata = read(template / 'metadata_approval.json')
    metadata.update(pageId=page_id, date='2026-09-27', approvedLocales=LOCALES,
        schemaVersion='sermon-dev-simulated-metadata-v1', decision='simulated_test_only',
        releaseIntent=config['intent'], approvalText=SIM, reviewer='simulation-test-only', recordedAt=STAMP, locales={})
    for locale in LOCALES:
        loc = out / locale
        preview = old / 'diagnostic-previews' / locale / 'native-1'
        candidate = read(preview / 'candidate.json')
        candidate.update(englishSourcePackageJsonSha256=source_sha,
            anchorManifestSha256=contract.sha(anchor), status='human_translation_approved', releaseEligible=False)
        ids = [g['translationGroupId'] for g in candidate['groups']]
        assert len(ids) == 13
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
        track = next(media_root.glob(locale + '-*.mp3'))
        audio.update(packageId=page_id + '-' + locale, targetLocale=locale,
            englishSourcePackageJsonSha256=source_sha, targetLanguageCandidateJsonSha256=candidate_sha,
            track=ref(track), units=[])
        audio['humanReview'].update(reviewedBy=SIM, reviewedAt=STAMP)
        cues = []
        audio_cues = []
        elapsed = 0
        for i, group in enumerate(candidate['groups']):
            wav = preview / 'units' / ('unit-%04d.wav' % i)
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
        display = {'series': '[模拟审核测试] 固定三分钟', 'title': '[模拟审核测试] 技术与人的盼望 — ' + locale,
            'speaker': '原录音讲员（测试身份未核验）', 'scripture': '三分钟片段无独立经文标注',
            'summary': '[模拟审核测试] simulation test only；沿用历史译文和音轨；真实内容、听审与同步未批准。',
            'outline': ['[模拟审核测试] 技术许诺与人的问题']}
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
                'body': group['targetText'] if kind == 'outline' else {
                    'zh-Hans': '默想问题：这段文字怎样影响我对技术与盼望的理解？\n',
                    'ko': '묵상 질문: 이 내용은 기술과 소망에 대한 나의 이해에 어떤 영향을 줍니까?\n',
                    'es': 'Pregunta para meditar: ¿Cómo influye este texto en mi comprensión de la tecnología y la esperanza?\n'
                }[locale] + group['targetText'], 'sourceUnitIds': group['sourceUnitIds']}
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
    proposal.write_text('# [模拟审核测试] 固定 180 秒\n\n' + SIM + '\n' + json.dumps(metadata['locales'], ensure_ascii=False, indent=2))
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
        'originalSourceWindowSeconds': [60, 240], 'testMediaWindowSeconds': [0, media_duration],
        'originalAnchorIssues': anchor['issues'], 'sourceUnitCount': 39, 'groupsPerLocale': 13,
        'audioDurations': {loc: duration(next(media_root.glob(loc + '-*.mp3'))) for loc in LOCALES},
        'result': result, 'frozenConfig': ref(frozen_path)}
    save(out / 'simulation-scope-report.json', report)
    print(json.dumps({'config': str(frozen_path), 'status': result['status'],
        'runId': run_id, 'pageId': page_id, 'fourProducts': result['fourProducts'], 'productionEligible': False,
        'scopeReport': str(out / 'simulation-scope-report.json')}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--run-id')
    parser.add_argument('--page-id')
    args = parser.parse_args()
    build(args.out, run_id=args.run_id, page_id=args.page_id)
