"""Synthetic selection batch failures and locally stable scripture locks."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts import sermon_cuv_translation as m
from scripts.cuv_scripture import CuvLibrary

class SelectionBatchTests(unittest.TestCase):
    def fixture(self):
        blocks=[{'id':i,'en':'You are','zh':'你'} for i in range(3)]
        rows=[{'id':i,'quotes':[{'quoteId':f'q{i}','reference':'REV 3:16','sourceText':'You are','start':0,'end':7,'uncertainty':[],'evidence':'source'}],'speakerReferences':[],'uncertainty':[]} for i in range(3)]
        manifest={'preflightPolicy':m.PREFLIGHT_POLICY,**{k:{'sha256':k} for k in ('parentJob','library','provenance')}}
        return blocks,{'blocks':rows},manifest

    def test_all_selection_defects_collected_with_stable_stage_indexes(self):
        blocks,mapping,manifest=self.fixture();stages=[]
        def call(out,name,*args,**kwargs):
            stages.append(name)
            return {'issues':['unresolved'],'quotes':[]},{'path':name,'sha256':name}
        with tempfile.TemporaryDirectory() as tmp,patch.object(m,'cached_call',side_effect=call):
            with self.assertRaises(m.EvidenceBlocked) as exc:
                m.selections(mapping,blocks,CuvLibrary.from_path(),Path(tmp),'identity',manifest=manifest)
            self.assertEqual([x['blockIndex'] for x in exc.exception.findings],[0,1,2])
            self.assertEqual(stages,['select-0','select-1','select-2'])
            self.assertEqual(len(m.read(Path(tmp)/'selection-blocked.json')['receipts']),3)

    def test_runtime_error_does_not_become_evidence_block(self):
        blocks,mapping,manifest=self.fixture()
        with tempfile.TemporaryDirectory() as tmp,patch.object(m,'cached_call',side_effect=RuntimeError('provider offline')) as call:
            with self.assertRaisesRegex(RuntimeError,'provider offline'):
                m.selections(mapping,blocks,CuvLibrary.from_path(),Path(tmp),'identity',manifest=manifest)
            self.assertEqual(call.call_count,1)

    def test_lock_local_dependency_and_legacy_identity(self):
        blocks,mapping,manifest=self.fixture();q=mapping['blocks'][0]['quotes'][0]
        parts=[{'reference':'REV 3:16','text':'你','start':0,'end':1,'joinBefore':'','verseTextSha256':'verse'}]
        a=m.quotation_token('run-one',manifest,blocks[0],q,parts)
        other={**manifest,'referenceMap':{'sha256':'changed unrelated block'}}
        self.assertEqual(a,m.quotation_token('run-two',other,blocks[0],q,parts))
        changed=copy.deepcopy(parts);changed[0]['start']=2
        self.assertNotEqual(a,m.quotation_token('run-two',manifest,blocks[0],q,changed))
        self.assertNotEqual(m.quotation_token('run-one',{},blocks[0],q,parts),m.quotation_token('run-two',{},blocks[0],q,parts))

    def test_fresh_repeated_word_uses_explicit_offset_without_repair(self):
        blocks,mapping,manifest=self.fixture()
        manifest['selectionPolicy']=m.SELECTION_OFFSETS_POLICY
        def call(out,name,instruction,*args,**kwargs):
            self.assertIn(m.SELECT_OFFSETS,instruction)
            return {'issues':[],'quotes':[{'quoteId':'q0','parts':[{'reference':'REV 3:16','text':'你','start':0,'end':1}],'uncertainty':[],'evidence':'Opening subject in complete source context'}]},{'path':'synthetic','sha256':'synthetic'}
        with tempfile.TemporaryDirectory() as tmp,patch.object(m,'cached_call',side_effect=call):
            rows,_=m.selections({'blocks':mapping['blocks'][:1]},blocks[:1],CuvLibrary.from_path(),Path(tmp),'identity',manifest=manifest)
            part=rows[0]['quotes'][0]['parts'][0]
            self.assertEqual(('你',0,1),(part['text'],part['start'],part['end']))
