import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from scripts import sermon_cuv_translation as mod
from scripts.cuv_scripture import CuvLibrary


class OffsetTests(unittest.TestCase):
    def test_exact_offsets_are_bounded_codepoints(self):
        full='你既[如]温[水]，也不冷也不热，所以我必从我口中把你吐出去。'
        self.assertEqual(mod.selected_part_span({'text':'你','start':0,'end':1},full,explicit_offsets=True),(0,1))
        for p in [{'text':'你'}, {'text':'你','start':1,'end':2}, {'text':'你','start':False,'end':1}, {'text':'你','start':0}, {'text':'你','start':-1,'end':0}]:
            with self.subTest(p=p),self.assertRaises(ValueError):mod.selected_part_span(p,full,explicit_offsets=True)
        with self.assertRaises(ValueError):mod.selected_part_span({'text':'你','start':0,'end':1},full)
        self.assertEqual(mod.selected_part_span({'text':'吐出去。'},full),(27,31))

    def fixture(self,root):
        old=root/'prior';new=root/'new';old.mkdir()
        for name in ['parent','library','provenance']:(root/name).write_text(name)
        prior={'schemaVersion':mod.VERSION,'model':mod.MODEL,'reasoningEffort':'medium','batchSize':6,
            'parentJob':mod.bind(root/'parent'),'library':mod.bind(root/'library'),'provenance':mod.bind(root/'provenance'),'timingReport':None}
        mod.save_frozen(old/'cuv-manifest.json',prior)
        blocks=[{'id':15,'en':'You are','zh':'你'}]
        quote={'quoteId':'q015-01','sourceText':'You are','reference':'REV 3:16','evidence':'interrupted subject','uncertainty':[]}
        mapping={'blocks':[{'id':15,'quotes':[quote],'speakerReferences':[],'uncertainty':[]}]}
        lookup=CuvLibrary.from_path().lookup(mod.parse_reference('REV 3:16'))
        candidates=[{**quote,'reference':lookup['canonicalRef'],'verses':lookup['verses']}]
        data={'block':blocks[0],'quotations':candidates}
        payload={'model':mod.MODEL,'reasoning_effort':'medium','response_format':{'type':'json_object'},
            'messages':[{'role':'system','content':mod.SYSTEM+mod.SELECT},{'role':'user','content':json.dumps(data,ensure_ascii=False)}]}
        request={'version':mod.VERSION,'identity':mod.digest(prior),'stage':'select-0','payload':payload}
        part={'reference':'REV 3:16','text':'你'}
        selected={'issues':[],'quotes':[{'quoteId':'q015-01','parts':[part],'evidence':'Subject interrupted before predicate','editionDifference':'','uncertainty':[]}]}
        response={'model':mod.MODEL,'choices':[{'finish_reason':'stop','message':{'content':json.dumps(selected)}}]}
        rp=old/'cache'/('select-0-'+mod.digest(request)+'.json')
        receipt={'request':request,'requestSha256':mod.digest(request),'response':response,'responseSha256':mod.digest(response)}
        mod.save_frozen(rp,receipt)
        repair={'schemaVersion':mod.SELECTION_OFFSETS_POLICY,'priorManifest':mod.bind(old/'cuv-manifest.json'),
            'repairs':[{'stage':'select-0','quoteId':'q015-01','partIndex':0,'receipt':mod.bind(rp),'originalPart':part,'start':0,'end':1,'evidence':'English subject is verse opening, not later object.'}]}
        mod.save_frozen(root/'repair.json',repair)
        manifest={**prior,'reuseFrom':mod.bind(old/'cuv-manifest.json'),'selectionPolicy':mod.SELECTION_OFFSETS_POLICY,'selectionOffsetRepair':mod.bind(root/'repair.json')}
        return new,manifest,blocks,mapping,rp,repair

    def test_reuse_original_receipt_without_api_and_offline_replay(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t).resolve();new,m,blocks,mapping,rp,repair=self.fixture(root)
            original=rp.read_bytes()
            with mock.patch.object(mod,'chat_json',side_effect=AssertionError('No API allowed')):
                result,receipts=mod.selections(mapping,blocks,CuvLibrary.from_path(),new,mod.digest(m),manifest=m)
                replay=mod.selections(mapping,blocks,CuvLibrary.from_path(),new,mod.digest(m),manifest=m,offline=True)
            self.assertEqual((result,receipts),replay)
            self.assertEqual(rp.read_bytes(),original)
            part=result[0]['quotes'][0]['parts'][0]
            self.assertEqual((part['text'],part['start'],part['end']),('你',0,1))
            self.assertEqual(part['offsetRepairEvidence'],m['selectionOffsetRepair'])
            self.assertEqual(mod.read(receipts[0]['path'])['response'],mod.read(rp)['response'])
            with self.assertRaises(ValueError):mod.selections(mapping,blocks,CuvLibrary.from_path(),rp.parent.parent,mod.digest({k:v for k,v in m.items() if k not in ['reuseFrom','selectionPolicy','selectionOffsetRepair']}),offline=True)

    def test_repair_cannot_change_selected_text_or_bypass_exactness(self):
        for edit in [lambda r:r['repairs'][0].update(start=1,end=2),lambda r:r['repairs'][0]['originalPart'].update(text='改写'),lambda r:r['repairs'][0].update(evidence='')]:
            with tempfile.TemporaryDirectory() as t:
                root=Path(t).resolve();new,m,blocks,mapping,rp,r=self.fixture(root)
                edit(r);(root/'repair.json').write_text(json.dumps(r));m['selectionOffsetRepair']=mod.bind(root/'repair.json')
                with self.assertRaises(ValueError):mod.selection_offset_repairs(m)

    def test_offset_repair_reuses_bound_ancestor_but_not_unrelated_manifest(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t).resolve();new,m,blocks,mapping,rp,repair=self.fixture(root)
            mod.save_frozen(new/'cuv-manifest.json',m)
            derived={**m,'reuseFrom':mod.bind(new/'cuv-manifest.json')}
            self.assertEqual(list(mod.selection_offset_repairs(derived)),[('select-0','q015-01',0)])
            unrelated={**m,'reuseFrom':mod.bind(new/'cuv-manifest.json'),'batchSize':7}
            with self.assertRaises(ValueError):mod.selection_offset_repairs(unrelated)

    def test_discovery_map_revision_is_narrow_and_hash_bound(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t).resolve();old=root/'old';old.mkdir()
            blocks=[{'id':40,'en':'You are, You are.','zh':'旧译文'}, {'id':41,'en':'Explanation.','zh':'解说'}]
            parent=root/'job.json';mod.save_frozen(parent,{'blocks':blocks})
            mapping={'schemaVersion':mod.MAP_SCHEMA,'parentJobSha256':mod.file_hash(parent),'issues':[],
                'blocks':[{'id':40,'quotes':[{'quoteId':'q40','sourceText':blocks[0]['en'],'reference':'REV 3:16','evidence':'Repeated source phrase','uncertainty':[]}],'speakerReferences':[],'uncertainty':[]},
                          {'id':41,'quotes':[],'speakerReferences':[],'uncertainty':[]}]}
            prior={'schemaVersion':mod.VERSION,'model':mod.MODEL,'reasoningEffort':'medium','batchSize':6,'parentJob':mod.bind(parent),'library':None,'provenance':None,'timingReport':None,'referenceMap':None}
            mod.save_frozen(old/'cuv-manifest.json',prior)
            data={'parentJobSha256':mod.file_hash(parent),'blocks':[{'id':b['id'],'en':b['en']} for b in blocks]}
            payload={'model':mod.MODEL,'reasoning_effort':'medium','response_format':{'type':'json_object'},'messages':[{'role':'system','content':mod.SYSTEM+mod.DISCOVER},{'role':'user','content':json.dumps(data,ensure_ascii=False)}]}
            request={'version':mod.VERSION,'identity':mod.digest(prior),'stage':'discover','payload':payload}
            response={'model':mod.MODEL,'choices':[{'finish_reason':'stop','message':{'content':json.dumps(mapping)}}]}
            rp=old/'cache'/('discover-'+mod.digest(request)+'.json')
            mod.save_frozen(rp,{'request':request,'requestSha256':mod.digest(request),'response':response,'responseSha256':mod.digest(response)})
            revised=copy.deepcopy(mapping)
            revised['blocks'][0]['quotes']=[{**mapping['blocks'][0]['quotes'][0],'quoteId':'q40a','sourceText':'You are','start':0,'end':7},
                                          {**mapping['blocks'][0]['quotes'][0],'quoteId':'q40b','sourceText':'You are','start':9,'end':16}]
            new_map=root/'map.json';mod.save_frozen(new_map,revised)
            revision={'schemaVersion':mod.REFERENCE_MAP_REVISION,'priorManifest':mod.bind(old/'cuv-manifest.json'),
                'sourceEvidence':{'kind':'discover_receipt',**mod.bind(rp)},'revisedMap':mod.bind(new_map),'changedBlockIds':[40],'evidence':'Split each original occurrence using exact source offsets.'}
            revision_path=root/'revision.json';mod.save_frozen(revision_path,revision)
            manifest={**prior,'reuseFrom':mod.bind(old/'cuv-manifest.json'),'referenceMap':mod.bind(new_map),'referenceMapRevision':mod.bind(revision_path)}
            with mock.patch.object(mod,'chat_json',side_effect=AssertionError('No API')):
                self.assertEqual(mod.validate_reference_map_revision(manifest)['changedBlockIds'],[40])
            # Even with deliberately refreshed map bindings, an undeclared second block edit fails.
            revised['blocks'][1]['uncertainty']=['new concern'];new_map.write_text(json.dumps(revised))
            revision['revisedMap']=mod.bind(new_map);revision_path.write_text(json.dumps(revision))
            manifest.update(referenceMap=mod.bind(new_map),referenceMapRevision=mod.bind(revision_path))
            with self.assertRaisesRegex(ValueError,'undeclared blocks'):mod.validate_reference_map_revision(manifest)

    def test_independent_selection_review_keeps_failure_and_all_gates(self):
        for resolved in [True,False]:
            with self.subTest(resolved=resolved),tempfile.TemporaryDirectory() as t:
                root=Path(t).resolve();new,m,blocks,mapping,rp,repair=self.fixture(root)
                original=mod.read(rp)
                failed=json.loads(original['response']['choices'][0]['message']['content'])
                failed['quotes'][0]['uncertainty']=['Possible version/person wording difference']
                original['response']['choices'][0]['message']['content']=json.dumps(failed)
                original['responseSha256']=mod.digest(original['response']);rp.write_text(json.dumps(original))
                repair['repairs'][0]['receipt']=mod.bind(rp)
                (root/'repair.json').write_text(json.dumps(repair));m['selectionOffsetRepair']=mod.bind(root/'repair.json')
                m['selectionReview']={'schemaVersion':mod.SELECTION_REVIEW_POLICY,'priorManifest':repair['priorManifest'],'receipts':[mod.bind(rp)]}
                context=mod.selection_review_contexts(m)
                self.assertEqual(context[0]['previousSelection'],failed)
                answer=copy.deepcopy(failed)
                if resolved:answer['quotes'][0]['uncertainty']=[]
                def respond(key,payload):
                    self.assertIn(mod.SELECT_REVIEW,payload['messages'][0]['content'])
                    data=json.loads(payload['messages'][1]['content'])
                    self.assertEqual(data['selectionReviewContext']['previousSelection'],failed)
                    return {'model':mod.MODEL,'choices':[{'finish_reason':'stop','message':{'content':json.dumps(answer)}}]}
                before=rp.read_bytes()
                with mock.patch.dict('os.environ',{'OPENAI_API_KEY':'fixture'}),mock.patch.object(mod,'chat_json',side_effect=respond) as api:
                    if resolved:
                        value=mod.selections(mapping,blocks,CuvLibrary.from_path(),new,mod.digest(m),manifest=m)
                        with mock.patch.object(mod,'chat_json',side_effect=AssertionError('offline')):
                            self.assertEqual(value,mod.selections(mapping,blocks,CuvLibrary.from_path(),new,mod.digest(m),manifest=m,offline=True))
                    else:
                        with self.assertRaisesRegex(ValueError,'lacks resolved evidence'):
                            mod.selections(mapping,blocks,CuvLibrary.from_path(),new,mod.digest(m),manifest=m)
                    self.assertEqual(api.call_count,1)
                self.assertEqual(rp.read_bytes(),before)

    def test_successful_selection_is_never_a_review_target(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t).resolve();new,m,blocks,mapping,rp,repair=self.fixture(root)
            m['selectionReview']={'schemaVersion':mod.SELECTION_REVIEW_POLICY,'priorManifest':repair['priorManifest'],'receipts':[mod.bind(rp)]}
            with self.assertRaisesRegex(ValueError,'successful'):mod.selection_review_contexts(m)
            m['selectionReview']['receipts']=[]
            with self.assertRaisesRegex(ValueError,'no bound failure'):mod.selection_review_contexts(m)

    def test_selection_review_subset_is_explicit_nonempty_and_failed_only(self):
        targets=[(46,{'path':'failed46'}),(47,{'path':'failed47'})]
        self.assertEqual(mod.select_review_targets(targets),[x[1] for x in targets])
        self.assertEqual(mod.select_review_targets(targets,[46]),[{'path':'failed46'}])
        for subset in [[],[46,46],[45],[-1],[True],['46']]:
            with self.subTest(subset=subset),self.assertRaises(ValueError):mod.select_review_targets(targets,subset)

    def inherited_fixture(self,root):
        new,m,blocks,mapping,rp,repair=self.fixture(root)
        receipt=mod.read(rp);failed=json.loads(receipt['response']['choices'][0]['message']['content'])
        failed['quotes'][0]['uncertainty']=['Requires review']
        receipt['response']['choices'][0]['message']['content']=json.dumps(failed)
        receipt['responseSha256']=mod.digest(receipt['response']);rp.write_text(json.dumps(receipt))
        repair['repairs'][0]['receipt']=mod.bind(rp)
        (root/'repair.json').write_text(json.dumps(repair));m['selectionOffsetRepair']=mod.bind(root/'repair.json')
        m['selectionReview']={'schemaVersion':mod.SELECTION_REVIEW_POLICY,'priorManifest':repair['priorManifest'],'receipts':[mod.bind(rp)]}
        mod.save_frozen(new/'cuv-manifest.json',m)
        derived={**m,'reuseFrom':mod.bind(new/'cuv-manifest.json'),'inheritSelectionReview':mod.bind(new/'cuv-manifest.json')}
        return new,m,derived,blocks,mapping,rp

    def test_inherited_review_same_duplicate_is_retained_and_source_change_fails(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t).resolve();new,m,derived,blocks,mapping,rp=self.inherited_fixture(root)
            expected=mod.selection_review_contexts(m)
            self.assertEqual(mod.selection_review_contexts(derived),expected)
            del derived['selectionReview']
            self.assertEqual(mod.selection_review_contexts(derived),expected)
            blocks[0]['zh']='Changed current source data'
            with mock.patch.object(mod,'chat_json',side_effect=AssertionError('No API')):
                with self.assertRaisesRegex(ValueError,'source block/candidates changed'):
                    mod.selections(mapping,blocks,CuvLibrary.from_path(),root/'out',mod.digest(derived),manifest=derived)

    def test_inherited_review_conflicting_duplicate_is_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t).resolve();new,m,derived,blocks,mapping,rp=self.inherited_fixture(root)
            receipt=mod.read(rp);receipt['request']['identity']=mod.digest(m)
            receipt['requestSha256']=mod.digest(receipt['request'])
            other=new/'cache'/('select-0-'+mod.digest(receipt['request'])+'.json');mod.save_frozen(other,receipt)
            derived['selectionReview']={'schemaVersion':mod.SELECTION_REVIEW_POLICY,'priorManifest':mod.bind(new/'cuv-manifest.json'),'receipts':[mod.bind(other)]}
            with self.assertRaisesRegex(ValueError,'Conflicting inherited'):mod.selection_review_contexts(derived)

    def test_inherited_review_cycle_is_rejected(self):
        manifest={'inheritSelectionReview':{'path':'fixture','sha256':'fixture'}}
        with mock.patch.object(mod,'reuse_ancestor',return_value=manifest):
            with self.assertRaisesRegex(ValueError,'Cyclic inherited'):mod.selection_review_contexts(manifest)
