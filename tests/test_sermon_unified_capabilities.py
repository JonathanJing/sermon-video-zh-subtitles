import copy
import hashlib
import json
import shutil
import pytest
from scripts import sermon_unified_capabilities as c
from scripts.sermon_production_supervisor import stable_hash, json_digest


def save(root, name, obj):
    path = root / (name + '.json')
    path.write_text(json.dumps(obj))
    return {'path': path.name, 'sha256': c.file_sha(path)}


@pytest.fixture
def config(tmp_path):
    from test_prepare_target_language_speech_job import TargetLanguageSpeechJobTests
    fixture = TargetLanguageSpeechJobTests()
    fixture.setUp()
    try:
        url = 'https://www.youtube.com/watch?v=example'
        timeline = {'schemaVersion': 2, 'stage': 'source_media_verified', 'boundaryMethod': 'operator_supplied',
            'status': 'requires_operator_review', 'sourceUrl': url, 'sunday': '2026-10-04',
            'durationSeconds': 60, 'audioSha256': 'a' * 64, 'audioSizeBytes': 100}
        receipt = {'status': 'approved', 'humanApproval': True, 'sunday': '2026-10-04', 'sourceUrlHash': stable_hash(url),
            'startTime': '00:00:00', 'endTime': '00:01:00', 'approvedBy': 'operator', 'timelineReportSha256': json_digest(timeline)}
        descriptor = {'sourceUrl': url, 'sourceId': 'example', 'mediaSha256': 'a' * 64, 'sunday': '2026-10-04'}
        bindings = {key: save(tmp_path,key,obj) for key,obj in [('windowApproval',receipt),('timelineReport',timeline),('sourceDescriptor',descriptor)]}
        source = {'sourceId': 'example', 'sourceUrlHash': hashlib.sha256(url.encode()).hexdigest(), 'mediaSha256': 'a' * 64,
            'durationSeconds':60, 'window':{'startSeconds':0,'endSeconds':60,'approvalReceiptSha256':bindings['windowApproval']['sha256']}}
        adapter, registry = copy.deepcopy(fixture.adapter), copy.deepcopy(fixture.registry)
        speaker = registry['speakers'][0]
        capability = next(row for row in speaker['localeCapabilities'] if row['targetLocale']=='ko')
        capability['status']='human_reviewed'; capability['reviewEvidence']=['synthetic test review']
        adapter.update(capabilityStatus='verified', registryJsonSha256=c.d.sha(registry), capabilityEvidenceSha256=c.d.sha(capability['reviewEvidence']))
        attestation = {'schemaVersion':'sermon-source-user-voice-attestation-v2','scope':'source_approved_window_formal_audio_only',
            'sourceId':'example','sourceMediaSha256':'a'*64,'approvedWindow':{'startSeconds':0,'endSeconds':60},
            'targetLocales':['ko'],'speakerId':adapter['speakerId'],'voiceCheckpointSha256':adapter['conditioningSha256'],
            'authorizedUses':['formal_audio_generation'],'permissionClaimed':True,'userStatement':'Synthetic test authorization only',
            'recordedAt':'2026-10-04T20:00:00Z','mediaDurationSeconds':60}
        locales = {'ko': {key:save(tmp_path,key,obj)['path'] for key,obj in [('adapter',adapter),('registry',registry),('policy',fixture.policy),('voiceAttestation',attestation)]}}
        intents = {env:{'schemaVersion':'sermon-release-intent-v1','environment':env,'channel':env,'project':env,
            'site':'test-'+env,'origin':'https://test-'+env+'.web.app'} for env in ['dev','production']}
        routes = {env:{key:value for key,value in intent.items() if key not in ['schemaVersion','environment']} for env,intent in intents.items()}
        value = {'schemaVersion':c.VERSION,'source':source,'bindings':bindings,'locales':locales,
            'terminology':str(c.policies.SERIES_TABLE),'releaseIntents':intents,'routes':routes,'targetSchemaVersions':c.SCHEMAS}
        path=tmp_path/'config.json';path.write_text(json.dumps(value))
        yield path
    finally:
        fixture.doCleanups()


def test_real_pipe_roundtrip():
    if not shutil.which('ffmpeg'): pytest.skip('ffmpeg absent')
    assert c.pcm_roundtrip()['frames']==16000


def test_freeze_revalidates_all_inputs_and_never_approves_future(config):
    output=config.parent/'frozen.json'
    result=c.freeze(config,output)
    assert result['snapshotBound'] and result['modelCalls']==0 and not result['futureArtifactsValidated']
    assert not result['locales']['ko']['candidateBoundAuthorizationValidated']
    voice=config.parent/'voiceAttestation.json'
    value=json.loads(voice.read_text());value['userStatement']+=' changed';voice.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='snapshot_changed'):c.inspect(output)


@pytest.mark.parametrize('change,match', [('missing','No such file'),('wrong_source','attestation_binding'),('unverified','not_verified'),('route','route mismatch'),('schema','schema_versions')])
def test_capabilities_fail_closed(config,change,match):
    value=json.loads(config.read_text())
    if change=='missing': value['locales']['ko']['voiceAttestation']='missing.json'
    elif change=='wrong_source':
        path=config.parent/'voiceAttestation.json';att=json.loads(path.read_text());att['sourceId']='other';path.write_text(json.dumps(att))
    elif change=='unverified':
        path=config.parent/'adapter.json';att=json.loads(path.read_text());att['capabilityStatus']='candidate';path.write_text(json.dumps(att))
    elif change=='route':value['releaseIntents']['production']['site']='wrong'
    else:value['targetSchemaVersions']['candidate']='unsupported'
    config.write_text(json.dumps(value))
    with pytest.raises((ValueError,FileNotFoundError),match=match):c.inspect(config)
