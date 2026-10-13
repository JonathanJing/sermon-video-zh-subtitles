"""Scoped QC and secondary-ASR paid calls use artifact-bound durable approval caps."""
import copy
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts import machine_qc_budget_authorization as auth
from scripts import run_machine_qc_clip_test as text
from scripts import run_machine_qc_audio_test as audio
from scripts import machine_qc_audio_transports as transports
from scripts import sermon_source_budget as budget
from scripts import sermon_workflow_jobs as jobs
from scripts import sermon_transcription_request as transcription
from tests.test_source_budget_settlement import AUTHORITY, BOUNDS
from tests.test_run_machine_qc_audio_test import OPENAI_ENV
from tests.auto_qc_fixtures import speech_wav

OPENAI_ROUTE={'schemaVersion':'sermon-openai-runtime-route-v1','environment':'dev',
              'projectId':OPENAI_ENV['OPENAI_PROJECT_ID'],'credentialAlias':'tongxing-dev-runtime',
              'identitySource':'configured_runtime'}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return path


@pytest.fixture
def scoped_paths(tmp_path):
    from tests.test_canonical_layer2_controller import CanonicalLayer2ControllerTests
    fixture = CanonicalLayer2ControllerTests(); fixture.setUp()
    try:
        values = fixture.fixture.fixture
        paths = {name: str(write(tmp_path / (name+'.json'), value))
                 for name, value in [('source', values.source), ('anchor', values.anchor), ('policy', values.policy)]}
        yield paths
    finally:
        fixture.doCleanups()


def authorization(tmp_path, paths=None, *, global_bounds=None):
    context = auth.context_from_paths(paths, 'zh-Hans', 'dev',route=OPENAI_ROUTE) if paths else None
    bounds = {'globalBounds': {**AUTHORITY['globalBounds'], **(global_bounds or {})}, 'requestLimits': AUTHORITY['requestLimits']}
    binding = {'budgetRoot': str(tmp_path/'budget'), **bounds}
    if context:
        binding['qcContext'] = context
    approval = {'schemaVersion': auth.APPROVAL_V3 if context else auth.APPROVAL_V1,
                'humanApproval': True, 'decision':'approved', 'binding':binding}
    if context:
        approval.update(reviewedBy='Fixture', reviewedAt='2026-10-13T00:00:00Z', operatorEvidence='Offline only')
    receipt = write(tmp_path/'approval.json', approval)
    value = {'schemaVersion': auth.AUTH_V3 if context else auth.AUTH_V1, 'budgetRoot':binding['budgetRoot'],
             'approvalReceipt':receipt.name, 'authority':{'approvalSha256':hashlib.sha256(receipt.read_bytes()).hexdigest(),
               'bounds':bounds, 'requestLimits':AUTHORITY['requestLimits']}}
    if context:
        value['qcContext'] = context
    return write(tmp_path/'authorization.json', value)


def source_store(root, send, *, bounds=None, reuse=()):
    authority = copy.deepcopy(AUTHORITY)
    if bounds:
        authority['globalBounds'].update(bounds)
    return budget.SourceBudget(root, authority, verify=lambda: None, transport=send, reuse_roots=reuse)


@pytest.mark.parametrize('wrong', ['locale', 'default_locales', 'environment', 'project', 'policy', 'source'])
def test_scoped_runtime_refuses_other_artifacts_or_default_three_locales(tmp_path, scoped_paths, wrong):
    path = authorization(tmp_path, scoped_paths)
    selected = {'zh-Hans':scoped_paths}
    requested = ['zh-Hans']
    environment = dict(OPENAI_ENV)
    if wrong == 'locale':
        selected = {'ko':scoped_paths}; requested = ['ko']
    elif wrong == 'default_locales':
        requested = ['zh-Hans','ko','es']
    elif wrong == 'project':
        environment.update(OPENAI_PROJECT_ID='proj_unapproved_fixture')
    elif wrong == 'environment':
        environment.update(SERMON_OPENAI_ENVIRONMENT='prod', SERMON_OPENAI_CREDENTIAL_ALIAS='tongxing-prod-runtime')
    else:
        target = Path(scoped_paths[wrong]); value = json.loads(target.read_text()); value['reviewProbe']='changed'
        write(target, value)
    with patch.dict('os.environ', environment), patch('urllib.request.urlopen', side_effect=AssertionError('paid dispatch')):
        with pytest.raises(ValueError):
            text.api_judge_for_resolved(path, selected, requested_locales=requested)


def test_valid_scoped_runtime_rechecks_files_without_gpu_session(tmp_path, scoped_paths):
    path = authorization(tmp_path, scoped_paths)
    with patch.dict('os.environ', OPENAI_ENV), patch('scripts.production_spark_admission.require_session', side_effect=AssertionError('GPU')):
        judge = text.api_judge_for_resolved(path, {'zh-Hans':scoped_paths}, requested_locales=['zh-Hans'])
        assert judge.identity['settings']['qcContext'] == auth.context_from_paths(scoped_paths,'zh-Hans','dev',route=OPENAI_ROUTE)
        assert judge.ledger.qc_context == judge.identity['settings']['qcContext']
        value = json.loads(Path(scoped_paths['source']).read_text()); value['reviewProbe']='changed'
        write(Path(scoped_paths['source']),value)
        called=[]; judge.ledger.transport=lambda *args: called.append(1)
        with pytest.raises(ValueError):
            judge.ledger.call(operation='judge.'+'a'*64,identity={'model':'gpt-6.1-sol'},bounds=BOUNDS,
                              request=b'{}',api_key='fixture',content_type='application/json',endpoint='fixture')
        assert called == []


def test_old_v1_approval_keeps_original_minimal_contract(tmp_path):
    path = authorization(tmp_path)
    with patch.dict('os.environ', OPENAI_ENV), patch('scripts.production_spark_admission.require_session', side_effect=AssertionError('GPU')):
        judge = text.api_judge_for_resolved(path, {'zh-Hans':{},'ko':{},'es':{}})
        assert judge.ledger.qc_context is None


@pytest.mark.parametrize('cap', [{'costMicrousd':4499}, {'wallTimeMs':299999}])
def test_secondary_refuses_durable_dollar_or_wall_cap_before_provider(tmp_path, cap):
    sent=[]
    store = source_store(tmp_path/'budget', lambda *args: sent.append(args), bounds=cap)
    with patch.dict('os.environ', OPENAI_ENV):
        secondary = transports.OpenAiTranscribeSecondary('ko',cache=tmp_path/'cache',max_calls=10,budget=store)
        with pytest.raises(ValueError,match='source_budget_exhausted'):
            secondary.transcribe(speech_wav(1))
    assert sent == []


def test_chat_and_secondary_share_request_cap_and_returned_audio_replays_across_restart(tmp_path):
    sent=[]
    def send(*args):
        sent.append(args); return {'text':'본문'}
    root=tmp_path/'budget'
    store=source_store(root, send, bounds={'requests':1})
    wav=speech_wav(1)
    with patch.dict('os.environ', OPENAI_ENV):
        first=transports.OpenAiTranscribeSecondary('ko',cache=tmp_path/'cache',max_calls=1,budget=store)
        assert first.transcribe(wav)=='본문'
        again=transports.OpenAiTranscribeSecondary('ko',cache=tmp_path/'new-cache',max_calls=0,
                budget=source_store(root,send,bounds={'requests':1}))
        assert again.transcribe(wav)=='본문'
        with pytest.raises(ValueError,match='source_budget_exhausted'):
            store.call(operation='judge.'+'f'*64,identity={'model':'gpt-6.1-sol'},bounds=BOUNDS,
                       request=b'{}',api_key='fixture',content_type='application/json',endpoint='fixture')
    assert len(sent)==1
    body=sent[0][1]
    assert b'name="languages[]"\r\n\r\nko\r\n' in body
    assert b'name="language"\r\n\r\nen' not in body
    value=jobs._read(root/'source-budget.json')
    operation,row=next(iter(value['requests'].items()))
    assert operation.startswith('judge.') and len(operation)==70
    assert row['bounds']==transcription.build_request(wav,hashlib.sha256(wav).hexdigest())['budgetBounds']
    saved=jobs._read(next((root/'responses').iterdir()))
    identity=saved['requestIdentity']
    assert identity['requestBodySha256']==hashlib.sha256(body).hexdigest()
    assert identity['api']['languages']==['ko'] and 'language' not in identity['api']
    assert identity['audio']['decodedFrameCount']==8000


def test_secondary_unknown_result_survives_process_and_cache_directory_change(tmp_path):
    sent=[]
    def timeout(*args):
        sent.append(1);raise TimeoutError('fixture')
    root=tmp_path/'budget';wav=speech_wav(1)
    with patch.dict('os.environ',OPENAI_ENV):
        first=transports.OpenAiTranscribeSecondary('ko',cache=tmp_path/'cache',max_calls=10,budget=source_store(root,timeout))
        with pytest.raises(TimeoutError):first.transcribe(wav)
        second=transports.OpenAiTranscribeSecondary('ko',cache=tmp_path/'other',max_calls=10,budget=source_store(root,timeout))
        with pytest.raises(ValueError,match='source_provider_outcome_unknown'):second.transcribe(wav)
        with pytest.raises(ValueError,match='source_provider_outcome_unknown'):second.transcribe(speech_wav(2))
    assert sent==[1]


def test_secondary_imports_paid_audio_without_using_zero_new_call_cap(tmp_path):
    sent=[]
    def send(*args):sent.append(1);return {'text':'본문'}
    source=tmp_path/'source';wav=speech_wav(1)
    with patch.dict('os.environ',OPENAI_ENV):
        first=transports.OpenAiTranscribeSecondary('ko',cache=tmp_path/'cache',max_calls=1,budget=source_store(source,send))
        first.transcribe(wav)
        second=transports.OpenAiTranscribeSecondary('ko',cache=tmp_path/'other',max_calls=0,
                budget=source_store(tmp_path/'dest',send,reuse=[source]))
        assert second.transcribe(wav)=='본문'
    assert sent==[1] and second.calls==0


def test_secondary_missing_ledger_and_invalid_pcm_refuse_without_provider(tmp_path):
    with patch.dict('os.environ',OPENAI_ENV):
        with pytest.raises(ValueError,match='approved SourceBudget'):
            transports.OpenAiTranscribeSecondary('ko',cache=tmp_path/'cache',max_calls=1)
        sent=[]
        secondary=transports.OpenAiTranscribeSecondary('ko',cache=tmp_path/'cache',max_calls=1,
                budget=source_store(tmp_path/'budget',lambda *args:sent.append(1)))
        with pytest.raises(ValueError,match='transcription_'):
            secondary.transcribe(b'not PCM')
    assert sent==[]


def test_real_transport_factory_requires_ledger_before_gpu_initialization(tmp_path):
    from types import SimpleNamespace
    args=SimpleNamespace(asr_model_path=tmp_path/'asr',max_api_calls=4,tts_checkpoint_map=tmp_path/'map.json',
                         tts_seed=42,tts_device='cuda:0',tts_dtype='bfloat16',tts_attention='none',tts_instruct='')
    with patch.object(transports,'QwenPrimaryAsr',side_effect=AssertionError('GPU before budget')):
        with pytest.raises(ValueError,match='approved SourceBudget'):
            audio.make_transports('real',args,tmp_path,locale='ko',screening={},job={},package={})


def test_api_transport_has_one_attempt_and_audio_response_byte_bound(tmp_path):
    import io
    import urllib.error
    path=authorization(tmp_path)
    with patch.dict('os.environ',OPENAI_ENV):
        judge=text.api_judge_for_resolved(path,{'ko':{}})
        with patch('urllib.request.urlopen',side_effect=urllib.error.HTTPError('fixture',503,'fixture',{},None)) as opened:
            with pytest.raises(urllib.error.HTTPError):
                judge.ledger.transport('https://api.openai.com/v1/chat/completions',b'{}','application/json',OPENAI_ENV['OPENAI_API_KEY'])
            assert opened.call_count==1
        with patch('urllib.request.urlopen',return_value=io.BytesIO(b'x'*(transcription.MAX_RESPONSE_BYTES+1))) as opened:
            with pytest.raises(ValueError,match='secondary_asr_response_size_exceeded'):
                judge.ledger.transport(transports.TRANSCRIBE_URL,b'fixture','multipart/form-data',OPENAI_ENV['OPENAI_API_KEY'])
            assert opened.call_args.kwargs['timeout']==transcription.WALL_TIME_MS/1000


def test_scoped_judge_and_secondary_share_one_bound_ledger_and_locale(tmp_path, scoped_paths):
    path=authorization(tmp_path,scoped_paths,global_bounds={'requests':1})
    called=[]
    with patch.dict('os.environ',OPENAI_ENV), patch('scripts.production_spark_admission.require_session',side_effect=AssertionError('GPU')):
        judge=text.api_judge_for_resolved(path,{'zh-Hans':scoped_paths},requested_locales=['zh-Hans'])
        judge.ledger.transport=lambda *args: called.append(args) or {'choices':[{'finish_reason':'stop','message':{'content':'{}'}}]}
        assert judge('semantic','fixture','fixture',{'type':'object'})=={}
        with pytest.raises(ValueError,match='budget context does not match'):
            transports.OpenAiTranscribeSecondary('ko',cache=tmp_path/'wrong',max_calls=10,budget=judge.ledger)
        secondary=transports.OpenAiTranscribeSecondary('zh-Hans',cache=tmp_path/'cache',max_calls=10,budget=judge.ledger)
        with pytest.raises(ValueError,match='another locale'):
            secondary.opinion(speech_wav(1),'fixture','ko')
        with pytest.raises(ValueError,match='source_budget_exhausted'):
            secondary.transcribe(speech_wav(1))
    assert len(called)==1


def test_current_qc_implementation_change_invalidates_scoped_runtime_approval(tmp_path, scoped_paths):
    from scripts import machine_quality_waiver as waiver
    path=authorization(tmp_path,scoped_paths)
    with patch.dict('os.environ',OPENAI_ENV):
        judge=text.api_judge_for_resolved(path,{'zh-Hans':scoped_paths},requested_locales=['zh-Hans'])
        with patch.object(waiver,'implementation_sha256',return_value='0'*64):
            with pytest.raises(ValueError,match='qc_budget_context_changed'):
                judge.ledger.verify()


def test_judge_request_identity_separates_selected_projects(tmp_path, scoped_paths):
    path=authorization(tmp_path,scoped_paths)
    with patch.dict('os.environ',OPENAI_ENV):
        first=text.api_judge_for_resolved(path,{'zh-Hans':scoped_paths},requested_locales=['zh-Hans'])
    with patch.dict('os.environ',{**OPENAI_ENV,'OPENAI_PROJECT_ID':'proj_another_fixture'}), \
            patch('urllib.request.urlopen',side_effect=AssertionError('paid dispatch')):
        with pytest.raises(ValueError,match='qc_budget_context_changed'):
            text.api_judge_for_resolved(path,{'zh-Hans':scoped_paths},requested_locales=['zh-Hans'])


def test_older_scoped_version_cannot_acquire_new_route_binding_implicitly(tmp_path,scoped_paths):
    path=authorization(tmp_path,scoped_paths)
    value=json.loads(path.read_text());value['schemaVersion']=auth.AUTH_V2;write(path,value)
    with patch.dict('os.environ',OPENAI_ENV),patch('urllib.request.urlopen',side_effect=AssertionError('paid dispatch')):
        with pytest.raises(ValueError):text.api_judge_for_resolved(path,{'zh-Hans':scoped_paths},requested_locales=['zh-Hans'])
