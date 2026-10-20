"""Legacy real entry shapes with fake transport; canonical bounds stay narrow."""
import base64
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
from tongxing_production.compute import legacy_openai  # C4: the remote-call group lives here
from scripts import sermon_pipeline as pipeline
from scripts import sermon_provider_limits as limits
from scripts import api_cli_outcomes as outcomes


def image_content(size=(1,1)):
    raw=io.BytesIO();Image.new('RGB',size).save(raw,format='PNG')
    return [{'type':'text','text':'Synthetic source frame'},
            {'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(raw.getvalue()).decode(),'detail':'high'}}]


def payload(content='synthetic'):
    return {'model':'gpt-6.1-sol','reasoning_effort':'high','response_format':{'type':'json_object'},
            'messages':[{'role':'user','content':content}]}


class LegacyChatShapeTests(unittest.TestCase):
    def test_actual_standalone_source_judge_strict_schema_reaches_transport(self):
        from tongxing_production.source import english_source_judge as judge
        from tests.test_judge_english_source_for_translation import EnglishSourceMachineJudgeTests
        fixture=EnglishSourceMachineJudgeTests();fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        with patch.dict(os.environ,{},clear=True),patch.object(legacy_openai,'json_request',side_effect=lambda url,key,body,**kw:fixture.fake_caller(key,body)) as network:
            result=judge.run(aligned_path=fixture.aligned_path,manifest_path=fixture.manifest_path,
                out=fixture.root/'shape-review.json',cache_root=fixture.root/'cache',api_key='synthetic-key')
        self.assertEqual(result['status'],'approved_for_layer2_shadow')
        self.assertEqual(network.call_count,1)
        self.assertEqual(network.call_args.args[2]['response_format']['type'],'json_schema')
        self.assertEqual(network.call_args.args[2]['max_completion_tokens'],4096)

    def test_actual_cuv_image_audit_entry_reaches_fake_transport(self):
        from tongxing_production.text import cuv_translation as cuv
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'SERMON_ACCOUNTING_DIR':tmp,'OPENAI_API_KEY':'synthetic-key'}),patch.object(cuv,'audit_user_content',return_value=image_content((1920,1080))),patch.object(legacy_openai,'json_request',return_value={'model':cuv.MODEL,'choices':[{'finish_reason':'stop','message':{'content':'{"ok":true}'}}]}) as network:
            result,_=cuv.cached_call(Path(tmp)/'cuv','audit-quotes',cuv.AUDIT_QUOTES,{},{} )
        self.assertEqual(result,{'ok':True});self.assertEqual(network.call_count,1)
        self.assertEqual(network.call_args.args[2]['messages'][1]['content'][1]['type'],'image_url')
        self.assertEqual(network.call_args.args[2]['max_completion_tokens'],4096)

    def test_full_schema_data_url_pixels_and_existing_cap_are_checked_before_dispatch(self):
        examples=[]
        bigschema=payload();bigschema['response_format']={'type':'json_schema','json_schema':{'name':'test','strict':True,'schema':{'type':'object','description':'x'*9000}}};examples.append(bigschema)
        examples.append(payload([image_content()[1]]*13))
        remote=payload([{'type':'image_url','image_url':{'url':'https://example.invalid/image.png'}}]);examples.append(remote)
        malformed=payload(image_content());malformed['messages'][0]['content'][1]['image_url']['url']='data:image/png;base64,notvalid';examples.append(malformed)
        wrongcap=payload();wrongcap['max_completion_tokens']=1;examples.append(wrongcap)
        text=payload('x'*9000);examples.append(text)
        tools=payload();tools['tools']=[];examples.append(tools)
        for body in examples:
            with self.subTest(body=str(body)[:50]),patch.object(legacy_openai,'json_request') as send:
                with self.assertRaises(ValueError):pipeline.chat_json('synthetic-key',body)
                send.assert_not_called()
        with self.assertRaises(ValueError):limits.bounded_payload(payload(image_content()),limits.DEFAULT_REQUEST_LIMITS)
        with patch.object(limits,'LEGACY_MAX_IMAGE_BYTES',8),patch.object(legacy_openai,'json_request') as send:
            with self.assertRaises(ValueError):pipeline.chat_json('synthetic-key',payload(image_content()))
            send.assert_not_called()

    def test_pipeline_aggregate_cache_cannot_bypass_unknown_sibling(self):
        for role in ('translation','correction'):
            with self.subTest(role=role),tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'SERMON_ACCOUNTING_DIR':tmp}):
                root=Path(tmp);segments=[{'id':0,'start':0.0,'end':1.0,'text':'Hello.'}]
                response={'choices':[{'message':{'content':json.dumps({'id':0,'zh':'您好。'} if role=='translation' else {'segments':[{'id':0,'text':'Hello.'}]})}}]}
                def run():
                    if role=='translation':return pipeline.translate_chinese('synthetic-key',segments,root/'out','gpt-6.1-sol',{})
                    return pipeline.correct_english('synthetic-key',segments,[],root/'out','gpt-6.1-sol',{},30)
                with patch.object(legacy_openai,'json_request',return_value=response) as network:
                    run();run();self.assertEqual(network.call_count,1)
                    def unknown():raise TimeoutError('unknown sibling')
                    with self.assertRaises(TimeoutError):outcomes.call(unknown,(),{},purpose='sibling')
                    with self.assertRaisesRegex(ValueError,'reconciliation_required'):run()
                    self.assertEqual(network.call_count,1)

    def test_pipeline_aggregate_and_item_caches_freeze_route_key_and_caller(self):
        route={'environment':'dev','projectId':'proj_original','credentialAlias':'tongxing-dev-runtime'}
        for role in ('translation','correction'):
            for changed in ('project','key','caller'):
                with self.subTest(role=role,changed=changed),tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'SERMON_ACCOUNTING_DIR':tmp}),patch('tongxing_production.compute.openai_runtime.selected_route',return_value=route) as selected:
                    root=Path(tmp);segments=[{'id':0,'start':0.0,'end':1.0,'text':'Hello.'}]
                    response={'choices':[{'message':{'content':json.dumps({'id':0,'zh':'您好。'} if role=='translation' else {'segments':[{'id':0,'text':'Hello.'}]})}}]}
                    def run(key='synthetic-key'):
                        if role=='translation':return pipeline.translate_chinese(key,segments,root/'out','gpt-6.1-sol',{})
                        return pipeline.correct_english(key,segments,[],root/'out','gpt-6.1-sol',{},30)
                    with patch.object(legacy_openai,'json_request',return_value=response) as network:
                        run();run();self.assertEqual(network.call_count,1)
                        if changed=='project':selected.return_value={**route,'projectId':'proj_changed'}
                        if changed=='caller':
                            with patch.object(legacy_openai,'_chat_json',side_effect=AssertionError('new caller dispatched')):
                                with self.assertRaisesRegex(ValueError,'frozen_execution_binding_changed'):run()
                        else:
                            with self.assertRaisesRegex(ValueError,'frozen_execution_binding_changed'):
                                run('changed-key' if changed=='key' else 'synthetic-key')
                        self.assertEqual(network.call_count,1)
