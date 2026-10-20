"""New production role defaults and API dispatch; no model executions."""
import json
import os
import tempfile
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

from tongxing_production.compute import legacy_openai  # C4: the remote-call group lives here
from tests.legacy_pipeline_patches import patch_both  # W3b: Layer 1 names live in two modules
from scripts import generate_notes_with_openai as notes
from tongxing_production.workflows.dual_pdf import pipeline as sermon_pipeline
from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.workflows.dual_pdf import post_live as post_live
from scripts import sermon_production_supervisor as supervisor
from tongxing_production.source import text_review as source_review


class TextRoleDefaultTests(unittest.TestCase):
    def test_post_live_defaults_all_text_roles_to_sol_high_api(self):
        with patch.object(sys, 'argv', ['post-live', '--sunday', '2026-10-04', '--state-file', 'unused.json']):
            args = post_live.parse_args()
        for model in (args.zh_model, args.en_correction_model, args.reading_edition_model, args.interpretation_model):
            self.assertEqual(model, 'gpt-6.1-sol')
        for effort in (args.reasoning_effort, args.reading_edition_reasoning_effort, args.interpretation_reasoning_effort):
            self.assertEqual(effort, 'high')
        self.assertEqual(args.reading_edition_provider, 'openai')
        self.assertEqual(supervisor.SupervisorConfig.__dataclass_fields__['reading_model'].default, 'gpt-6.1-sol')
        self.assertEqual(notes.DEFAULT_MODEL, 'gpt-6.1-sol')
        self.assertEqual(notes.DEFAULT_REASONING_EFFORT, 'high')
        self.assertEqual(source_review.SUPPORTED_MODELS, {'gpt-6-astra', 'gpt-6.1-sol'})

    def test_subtitle_reviewer_defaults_to_current_independent_review_policy(self):
        from scripts import review_sermon_subtitles_with_openai as review
        with patch.object(sys, 'argv', ['review', '--outdir', 'unused']):
            args = review.parse_args()
        self.assertEqual(args.model, 'gpt-6.1-sol')
        self.assertEqual(args.reasoning_effort, 'medium')
        rows=[{'id':0,'text':'Hello.','zh':'你好。'}]
        response={'choices':[{'message':{'content':json.dumps({'segments':[{'id':0,'zh':'您好。'}]})}}]}
        with tempfile.TemporaryDirectory() as tmp,patch.object(review,'chat_json',return_value=response) as transport:
            review.review_batch('synthetic',rows,rows,0,Path(tmp),args.model,args.reasoning_effort)
            sent=transport.call_args.args[1]
            self.assertEqual(sent['model'],'gpt-6.1-sol')
            self.assertEqual(sent['reasoning_effort'],'medium')
            self.assertEqual(sent['service_tier'],'default')
            with self.assertRaisesRegex(ValueError,'unsupported_bounded_provider_model'):
                review.review_batch('synthetic',rows,rows,0,Path(tmp),'gpt-5.6','medium')
            transport.assert_called_once()

    def test_migrated_legacy_chat_caps_valid_copy_without_mutating_input(self):
        from scripts import tongxing_host  # noqa: F401  binds the production package ports
        from tongxing_production.compute.provider_limits import DEFAULT_REQUEST_LIMITS
        payload={'model':'gpt-6.1-sol','reasoning_effort':'high',
                 'messages':[{'role':'user','content':'synthetic'}], 'response_format':{'type':'json_object'}}
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'SERMON_ACCOUNTING_DIR':tmp}), patch.object(legacy_openai,'json_request',return_value={'ok':True}) as api:
            sermon_pipeline.chat_json('synthetic-key',payload)
        self.assertNotIn('max_completion_tokens',payload)
        sent=api.call_args.args[2]
        self.assertEqual(sent['max_completion_tokens'],DEFAULT_REQUEST_LIMITS['maxCompletionTokens'])
        self.assertEqual(sent['service_tier'],'default')
        self.assertEqual(sent['messages'],payload['messages'])

    def test_already_supplied_cap_is_not_increased_or_silently_changed(self):
        from scripts import tongxing_host  # noqa: F401  binds the production package ports
        from tongxing_production.compute.provider_limits import DEFAULT_REQUEST_LIMITS
        payload={'model':'gpt-6.1-sol','reasoning_effort':'high',
                 'messages':[{'role':'user','content':'synthetic'}], 'response_format':{'type':'json_object'},
                 'max_completion_tokens':DEFAULT_REQUEST_LIMITS['maxCompletionTokens']-1}
        with patch.object(legacy_openai,'json_request') as api:
            with self.assertRaises(ValueError):sermon_pipeline.chat_json('synthetic-key',payload)
        api.assert_not_called()

    def test_supervisor_defaults_cli_and_preserves_explicit_historical_api(self):
        from scripts import run_sermon_production_supervisor_agent as agent
        argv = ['supervisor', '--sunday', '2026-10-04', '--state-file', 'unused.json']
        with patch.object(sys, 'argv', argv):
            self.assertEqual(agent.parse_args().agent_backend, 'codex-cli')
        with patch.object(sys, 'argv', argv + ['--agent-backend', 'agents-api']):
            self.assertEqual(agent.parse_args().agent_backend, 'agents-api')

    def test_notes_api_preserves_response_shape(self):
        envelope = {'model': 'gpt-6.1-sol', 'output_text': '{"summaryZh":"sample"}', 'usage': {'total_tokens': 12}}
        response = Mock(status_code=200, content=json.dumps(envelope).encode())
        response.json.return_value = envelope
        payload = {'model': 'gpt-6.1-sol', 'reasoning': {'effort': 'high'}, 'input': [{'role': 'user', 'content': [{'type': 'input_text', 'text': 'source'}]}]}
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'SERMON_ACCOUNTING_DIR':tmp}), patch.object(notes.requests, 'post', return_value=response) as api, patch('tongxing_production.compute.openai_runtime.project_headers', return_value={}):
            result = notes.request_openai_notes(payload, 'synthetic-key', session_verifier=lambda: {'status':'offline_test'})
        api.assert_called_once()
        self.assertEqual(json.loads(notes.extract_response_text(result)), {'summaryZh': 'sample'})
        self.assertEqual(api.call_args.kwargs['json']['reasoning']['effort'], 'high')

    def test_actual_legacy_builders_pass_validated_caps_to_offline_transport(self):
        from scripts import build_sermon_reading_edition_with_openai as reading
        from scripts import tongxing_host  # noqa: F401  binds the production package ports
        from tongxing_production.compute.provider_limits import DEFAULT_REQUEST_LIMITS
        sent=[]
        def respond(url,key,payload,**kwargs):
            sent.append(payload)
            user=payload['messages'][1]['content']
            if '<timed_segments>' in user:result={'segments':[{'id':0,'text':'Hello.'}]}
            elif '<context>' in user:result={'id':0,'zh':'您好。'}
            else:result={'blocks':[{'id':0,'zh':'您好。'}]}
            return {'model':payload['model'],'choices':[{'message':{'content':json.dumps(result)}}]}
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'SERMON_ACCOUNTING_DIR':tmp}),patch.object(legacy_openai,'json_request',side_effect=respond):
            root=Path(tmp);segments=[{'id':0,'start':0.0,'end':1.0,'text':'Hello.'}]
            sermon_pipeline.correct_english('synthetic-key',segments,[],root/'correct','gpt-6.1-sol',{},30)
            sermon_pipeline.translate_chinese('synthetic-key',segments,root/'translate','gpt-6.1-sol',{})
            blocks=[{'id':0,'start':0.0,'end':1.0,'en':'Hello.','zh':'您好。'}]
            for qa in (False,True):
                reading.edit_batch('synthetic-key',blocks,blocks,0,root/'reading',model='gpt-6.1-sol',
                    reasoning_effort='high',qa_pass=qa,provider='openai',codex_cli=Path('unused'),schema_path=Path('unused'))
        self.assertEqual(len(sent),4)
        for payload in sent:
            self.assertEqual(payload['max_completion_tokens'],DEFAULT_REQUEST_LIMITS['maxCompletionTokens'])
            self.assertEqual(payload['service_tier'],'default')
            self.assertEqual(payload['reasoning_effort'],'high')


class LegacyBoundedCacheIdentityTests(unittest.TestCase):
    """Seed the actual pre-cap cache names, then exercise production readers."""
    def test_old_uncapped_cache_is_not_relabelled_and_new_caps_are_reusable(self):
        import hashlib
        from scripts import build_sermon_reading_edition_with_openai as reading
        from scripts import review_sermon_subtitles_with_openai as review
        from tongxing_production.source import sentence_interpretation_models as sentence
        from scripts import tongxing_host  # noqa: F401  binds the production package ports
        from tongxing_production.compute import provider_limits as limits
        segment={'id':0,'start':0.,'end':1.,'text':'Hello.'}
        block={**segment,'en':'Hello.','zh':'你好。'}
        glossary={}
        def digest(v):return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        def seed(p,v):sermon_pipeline.write_json(p,v);return p
        def reply(value):return {'model':'gpt-6.1-sol','choices':[{'finish_reason':'stop','message':{'content':json.dumps(value)}}]}
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); model='gpt-6.1-sol';effort='high'
            for role in ('correction','translation','subtitle','sentence','reading-edit','reading-qa'):
                with self.subTest(role=role):
                    out=root/role;out.mkdir()
                    if role in ('correction','translation'):
                        correction=role=='correction'
                        prompt=(sermon_pipeline.review_prompts.ENGLISH_CORRECTION_PROMPT_VERSION if correction else sermon_pipeline.review_prompts.CHINESE_TRANSLATION_PROMPT_VERSION)
                        old_identity=hashlib.sha256(f'{prompt}|{model}|{effort}'.encode()).hexdigest()[:12]
                        old_input=({'batch':[segment],'reference':'','glossary':glossary} if correction else {'segment':segment,'previous':'','next':'','glossary':glossary})
                        old_path=out/('correction_windows' if correction else 'translation_segments')/((f'window_0000_0000.{old_identity}.' if correction else f'seg_0000.{old_identity}.')+sermon_pipeline.json_sha256(old_input)[:12]+'.json')
                        seed(old_path,{'segments':[{'id':0,'text':'OLD'}]} if correction else {'id':0,'zh':'旧'})
                        version={'promptVersion':prompt,'model':model,'reasoningEffort':effort,'inputSha256':sermon_pipeline.json_sha256({'segments':[segment],'referenceChunks':[],'glossary':glossary} if correction else {'segments':[segment],'glossary':glossary})}
                        seed(out/('english_correction_prompt.json' if correction else 'chinese_translation_prompt.json'),version)
                        seed(out/('segments_timed_en_corrected.json' if correction else 'segments_timed_zh.json'),[{'id':0,'text':'OLD','zh':'旧'}])
                        response=reply({'segments':[{'id':0,'text':'NEW'}]} if correction else {'id':0,'zh':'新'})
                        invoke=(lambda:sermon_pipeline.correct_english('synthetic',[segment],[],out,model,glossary,30)) if correction else (lambda:sermon_pipeline.translate_chinese('synthetic',[segment],out,model,glossary))
                        module=sermon_pipeline
                    elif role=='subtitle':
                        payload=review.batch_payload([block],[block],0,model,effort)
                        old_identity=digest({'promptVersion':review.PROMPT_VERSION,'payload':payload})
                        old_path=seed(out/f'review_0000_0000.{old_identity}.json',{'segments':[{'id':0,'zh':'旧'}]})
                        response=reply({'segments':[{'id':0,'zh':'新'}]})
                        invoke=lambda:review.review_batch('synthetic',[block],[block],0,out,model,effort)
                        module=review
                    elif role=='sentence':
                        payload={'model':model,'reasoning_effort':effort,'messages':[{'role':'user','content':'synthetic'}],'response_format':{'type':'json_object'}}
                        request={'schemaVersion':sentence.RUN_SCHEMA,'stage':'test','payload':payload};old_hash=sentence.contract.json_sha256(request)
                        old_path=seed(out/'cache'/f'test-{old_hash}.json',{'request':request,'requestSha256':old_hash,'response':reply({'text':'OLD'})})
                        response=reply({'text':'NEW'})
                        invoke=lambda:sentence.cached_call(out=out,stage='test',payload=payload,api_key='synthetic',requested_model=model,caller=api)
                        module=None
                    else:
                        qa=role=='reading-qa';payload=reading.request_payload([block],[block],0,model=model,reasoning_effort=effort,qa_pass=qa)
                        prompt=reading.QA_PROMPT_VERSION if qa else reading.PROMPT_VERSION
                        old_identity=hashlib.sha256(f'{prompt}|openai|{model}|{effort}'.encode()).hexdigest()[:12]
                        old_path=seed(out/f'{"qa" if qa else "edit"}_000_000.{old_identity}.{digest(payload)[:12]}.json',{'blocks':[{'id':0,'zh':'旧'}]})
                        response=reply({'blocks':[{'id':0,'zh':'新'}]})
                        invoke=lambda:reading.edit_batch('synthetic',[block],[block],0,out,model=model,reasoning_effort=effort,qa_pass=qa,provider='openai',codex_cli=Path('unused'),schema_path=Path('unused'))
                        module=reading
                    before=old_path.read_bytes()
                    api=Mock(return_value=response)
                    with ((patch_both('chat_json',api) if module is sermon_pipeline else patch.object(module,'chat_json',api)) if module else patch.object(sentence,'RUN_SCHEMA',sentence.RUN_SCHEMA)):
                        first=invoke();second=invoke()
                        self.assertEqual(first,second)
                        self.assertEqual(api.call_count,1)
                        self.assertEqual(api.call_args.args[1]['max_completion_tokens'],limits.DEFAULT_REQUEST_LIMITS['maxCompletionTokens'])
                        self.assertEqual(api.call_args.args[1]['service_tier'],'default')
                        changed={**limits.DEFAULT_REQUEST_LIMITS,'maxCompletionTokens':2048}
                        with patch.object(limits,'DEFAULT_REQUEST_LIMITS',changed):invoke()
                        self.assertEqual(api.call_count,2)
                        self.assertEqual(api.call_args.args[1]['max_completion_tokens'],2048)
                    self.assertEqual(old_path.read_bytes(),before)

    def test_new_cache_miss_keeps_directory_unknown_gate(self):
        from scripts import build_sermon_reading_edition_with_openai as reading
        payload={'model':'gpt-6.1-sol','reasoning_effort':'high','messages':[{'role':'user','content':'synthetic'}],'response_format':{'type':'json_object'}}
        block={'id':0,'start':0.,'end':1.,'en':'Hello.','zh':'你好。'}
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'SERMON_ACCOUNTING_DIR':tmp}),patch.object(legacy_openai,'json_request',side_effect=TimeoutError('synthetic unknown')) as api:
            with self.assertRaises(TimeoutError):sermon_pipeline.chat_json('synthetic',payload)
            with self.assertRaisesRegex(ValueError,'api_cli_outcome_reconciliation_required'):
                reading.edit_batch('synthetic',[block],[block],0,Path(tmp)/'reading',model='gpt-6.1-sol',reasoning_effort='high',qa_pass=False,provider='openai',codex_cli=Path('unused'),schema_path=Path('unused'))
            api.assert_called_once()


class LegacyExecutionCacheIdentityTests(unittest.TestCase):
    def test_all_api_cache_readers_bind_project_credential_and_transport_before_lookup(self):
        from scripts import build_sermon_reading_edition_with_openai as reading
        from scripts import review_sermon_subtitles_with_openai as review
        from tongxing_production.source import sentence_interpretation_models as sentence
        segment={'id':0,'start':0.,'end':1.,'text':'Hello.'}
        block={**segment,'en':'Hello.','zh':'你好。'}
        route={'environment':'dev','projectId':'proj_a','credentialAlias':'tongxing-dev-runtime','identitySource':'configured_runtime'}
        with tempfile.TemporaryDirectory() as tmp:
            for role in ('correction','translation','subtitle','sentence','reading-edit','reading-qa'):
                with self.subTest(role=role):
                    root=Path(tmp)/role;calls=[]
                    def fake(api_key,payload):
                        calls.append(payload)
                        if role=='correction':result={'segments':[{'id':0,'text':'NEW'}]}
                        elif role=='translation':result={'id':0,'zh':'新'}
                        elif role=='subtitle':result={'segments':[{'id':0,'zh':'新'}]}
                        elif role=='sentence':result={'text':'NEW'}
                        else:result={'blocks':[{'id':0,'zh':'新'}]}
                        return {'model':'gpt-6.1-sol','choices':[{'finish_reason':'stop','message':{'content':json.dumps(result)}}]}
                    def run(key):
                        if role=='correction':return sermon_pipeline.correct_english(key,[segment],[],root,'gpt-6.1-sol',{},30)
                        if role=='translation':return sermon_pipeline.translate_chinese(key,[segment],root,'gpt-6.1-sol',{})
                        if role=='subtitle':return review.review_batch(key,[block],[block],0,root,'gpt-6.1-sol','medium')
                        if role=='sentence':return sentence.cached_call(out=root,stage='test',payload={'model':'gpt-6.1-sol','reasoning_effort':'high','messages':[{'role':'user','content':'synthetic'}],'response_format':{'type':'json_object'}},api_key=key,requested_model='gpt-6.1-sol',caller=fake)
                        return reading.edit_batch(key,[block],[block],0,root,model='gpt-6.1-sol',reasoning_effort='high',qa_pass=role=='reading-qa',provider='openai',codex_cli=Path('unused'),schema_path=Path('unused'))
                    with patch('tongxing_production.compute.openai_runtime.selected_route',return_value=route),patch_both("chat_json", side_effect=fake),patch.object(review,'chat_json',side_effect=fake),patch.object(reading,'chat_json',side_effect=fake):
                        run('synthetic-key-a');run('synthetic-key-a');self.assertEqual(len(calls),1)
                        run('synthetic-key-b');self.assertEqual(len(calls),2)
                        with patch('tongxing_production.compute.openai_runtime.selected_route',return_value={**route,'projectId':'proj_b'}):run('synthetic-key-a')
                        self.assertEqual(len(calls),3)
                        fake.execution_identity={'revision':'changed'}
                        with patch.object(sermon_pipeline._chat_json,'execution_identity',{'revision':'changed'},create=True):run('synthetic-key-a')
                        self.assertEqual(len(calls),4)
                        # The key contains non-secret hashes, never the raw credential.
                        for path in root.rglob('*.json'):
                            self.assertNotIn('synthetic-key-a',path.read_text())
                            self.assertNotIn('synthetic-key-b',path.read_text())

    def test_existing_derived_cache_cannot_hide_unrelated_unknown_outcome(self):
        from scripts import build_sermon_reading_edition_with_openai as reading
        block={'id':0,'start':0.,'end':1.,'en':'Hello.','zh':'你好。'}
        response={'model':'gpt-6.1-sol','choices':[{'message':{'content':json.dumps({'blocks':[{'id':0,'zh':'您好。'}]})}}]}
        payload={'model':'gpt-6.1-sol','reasoning_effort':'high','messages':[{'role':'user','content':'other synthetic request'}],'response_format':{'type':'json_object'}}
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'SERMON_ACCOUNTING_DIR':tmp}),patch.object(legacy_openai,'json_request',side_effect=[response,TimeoutError('synthetic unknown')]) as provider:
            kwargs=dict(model='gpt-6.1-sol',reasoning_effort='high',qa_pass=False,provider='openai',codex_cli=Path('unused'),schema_path=Path('unused'))
            reading.edit_batch('synthetic',[block],[block],0,Path(tmp)/'reading',**kwargs)
            self.assertEqual(len(list((Path(tmp)/'reading').glob('*.json'))),1)
            with self.assertRaises(TimeoutError):sermon_pipeline.chat_json('synthetic',payload)
            with self.assertRaisesRegex(ValueError,'api_cli_outcome_reconciliation_required'):
                reading.edit_batch('synthetic',[block],[block],0,Path(tmp)/'reading',**kwargs)
            self.assertEqual(provider.call_count,2)

    def test_subtitle_and_sentence_outer_callers_use_actual_stage_identity_and_defaults(self):
        from scripts import tongxing_host  # noqa: F401  binds the production package ports
        from tongxing_production.compute import outcomes
        from tongxing_production.compute.spark_admission import SessionBoundCaller
        from scripts import review_sermon_subtitles_with_openai as review
        from tongxing_production.source import sentence_interpretation_models as sentence
        rows=[{'id':0,'text':'Hello.','zh':'你好。'}]
        with tempfile.TemporaryDirectory() as tmp:
            for role,purpose in [('subtitle','subtitle-review'),('sentence','sentence-interpretation')]:
                with self.subTest(role=role):
                    root=Path(tmp)/role;calls=[]
                    def actual(api_key,payload,retries=1):
                        calls.append(payload)
                        result={'segments':[{'id':0,'zh':'您好。'}]} if role=='subtitle' else {'text':'NEW'}
                        return {'model':'gpt-6.1-sol','choices':[{'finish_reason':'stop','message':{'content':json.dumps(result)}}]}
                    caller=SessionBoundCaller(actual,purpose=purpose,requires_spark=False,outcome_directory=root/'outcomes')
                    payload=(review.batch_payload(rows,rows,0,'gpt-6.1-sol','medium') if role=='subtitle' else {'model':'gpt-6.1-sol','reasoning_effort':'high','messages':[{'role':'user','content':'synthetic'}],'response_format':{'type':'json_object'}})
                    bounded=sermon_pipeline.bounded_legacy_chat_payload(payload)
                    identity=sermon_pipeline.legacy_text_execution_identity('synthetic',bounded,caller=caller)
                    self.assertEqual(identity['outcomeRequestSha256'],outcomes.request_identity(actual,('synthetic',bounded),{},purpose))
                    def run():
                        if role=='subtitle':return review.review_batch('synthetic',rows,rows,0,root/'cache','gpt-6.1-sol','medium',caller=caller)
                        return sentence.cached_call(out=root,stage='test',payload=payload,api_key='synthetic',requested_model='gpt-6.1-sol',caller=caller)
                    run();run();self.assertEqual(len(calls),1)
                    receipt=root/'outcomes'/identity['outcomeRequestSha256']/'outcome.json'
                    self.assertTrue(receipt.is_file())
                    self.assertEqual(json.loads(receipt.read_text())['purpose'],purpose)
                    actual.execution_identity={'transport':'changed'}
                    with self.assertRaisesRegex(ValueError,'api_cli_frozen_execution_binding_changed'):run()
                    self.assertEqual(len(calls),1)
