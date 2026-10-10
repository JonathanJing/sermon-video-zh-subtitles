"""Real JSON/source artifacts, synthetic offline ASR/judge, no external dispatch."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import sermon_unified_continuation as subject
from scripts import build_english_source_package as english
from scripts.sermon_unified import contracts as c, runtime
from tests import test_sermon_unified_source as source_fixture
from tests import test_sermon_unified_cli as cli_fixture


def token(kind, name, field='path'):
    return {'$'+kind: name, 'field': field}


def binding(kind, name):
    return {field: token(kind,name,field) for field in ('path','sha256')}


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.source = source_fixture.UnifiedSourceTests('test_inspect_is_read_only_and_has_bound_snapshot')
        self.source.setUp(); self.addCleanup(self.source.doCleanups)
        self.cli = cli_fixture.UnifiedCliTests('test_status_does_not_write_or_reconcile')
        self.cli.setUp(); self.addCleanup(self.cli.doCleanups)
        self.root = self.source.root / 'store'
        self.manifest = copy.deepcopy(self.cli.m)
        self.manifest.update(productionRunId=self.source.config['productionRunId'],jobRoot='continuation-fixture')
        self.manifest['source'] = {'sourceId':self.source.config['sourceId'],
            'sourceUrlHash':self.source.config['sourceUrlHash'],'mediaSha256':c.file_sha(self.source.media),
            'durationSeconds':181,'window':{**self.source.window,'timeBase':'source_media',
                                          'approvalReceiptSha256':c.file_sha(self.source.approval)}}
        self.manifest['budget']['limitMicroUsd'] = 10000000
        self.manifest['steps'] = [{'id':'source','stageId':'asr','adapter':'source.prepare',
            'configuration':'sourceConfig','budgetAuthorization':'budget','dependsOn':[],
            'scope':'english_ready_for_translation','maxCostMicroUsd':10000000}]
        self.manifest['bindings'] = {name:{'path':str(path),'sha256':c.file_sha(path)} for name,path in
            {'sourceConfig':self.source.path,'budget':self.source.root/'budget.json'}.items()}
        policy_placeholder = self.source.root/'not-yet-prepared-policy.json'
        policy_placeholder.write_text('{}')
        self.manifest['bindings']['futurePolicy'] = {'path':str(policy_placeholder), 'sha256':c.file_sha(policy_placeholder)}
        self.recipe_path = self.source.root/'recipe.json'
        self.ports = {name:{'stepId':'source','role':role} for name,role in
                      [('source','source_candidate'),('anchor','source_anchor'),('aligned','source_transcript')]}
        self.inputs = {name:token('port',port) for name,port in
                       [('source','source'),('anchor','anchor'),('aligned','aligned')]}
        first = {'id':'review-source','afterRunRevision':1,'ports':self.ports,'requiredEvidence':[],
            'configs':{'reviewConfig':{'adapter':'review.gate','template':{
                'schemaVersion':'sermon-unified-review-inputs-v1',
                'inputs':{'source':'sourceMachine','anchor':'anchor','aligned':'aligned'}}}},
            'manifestTemplate':{'activeScope':'english_ready_for_translation',
                'bindings':{'sourceMachine':binding('port','source'),'anchor':binding('port','anchor'),
                            'aligned':binding('port','aligned'),'reviewConfig':binding('config','reviewConfig')},
                'steps':[{'id':'english-review','adapter':'review.gate','reviewKind':'english',
                          'stageId':'english_source','dependsOn':['source'],
                          'scope':'english_ready_for_translation','configuration':'reviewConfig'}]}}
        second = {'id':'admit-reviewed-source','afterRunRevision':2,'ports':self.ports,
            'requiredEvidence':[
                {'binding':'englishReceipt','kind':'human_review','reviewKind':'english','inputs':self.inputs},
                {'binding':'approvedSource','kind':'approved_source','receiptBinding':'englishReceipt',
                 'inputs':{**self.inputs,'machine':token('port','source')}}],
            'configs':{'inspection':{'adapter':'canonical.inspect','template':{
                'schemaVersion':'sermon-canonical-package-inspection-config-v1',
                'source':token('binding','approvedSource'),'anchor':token('port','anchor'),
                'locales':{'zh-Hans':{'policy':token('binding','futurePolicy')}}}}},
            'manifestTemplate':{'bindings':{'approvedSource':binding('binding','approvedSource'),
                'englishReceipt':binding('binding','englishReceipt'),'inspection':binding('config','inspection')},
                'steps':[{'id':'source-admission','adapter':'canonical.inspect','stageId':'english_source',
                    'configuration':'inspection','dependsOn':['english-review'],'scope':'english_ready_for_translation'}]}}
        self.recipe = {'schemaVersion':subject.SCHEMA,'productionRunId':self.manifest['productionRunId'],
                       'jobRoot':self.manifest['jobRoot'],'stages':[first,second]}
        self.bind_recipe()
        self.state = {'runKey':runtime.run_key(self.manifest),'manifest':self.manifest,
            'planHash':c.plan_hash(self.manifest),'stateRevision':4,'steps':{
                'source':{'process':'not_started','artifact':'not_started'}},'reviews':{},'cancelRequested':False}

    def bind_recipe(self):
        self.recipe_path.write_text(json.dumps(self.recipe))
        self.manifest['bindings']['continuationRecipe']={'path':str(self.recipe_path),'sha256':c.file_sha(self.recipe_path)}

    def complete_source(self):
        result = self.source.execute()  # Synthetic transports, real producer JSON and ffmpeg.
        step = self.manifest['steps'][0]
        directory = runtime.folder(self.root,self.state['runKey']); directory.mkdir(parents=True,exist_ok=True)
        response = directory/('response-'+c.digest(c.job_identity(self.manifest,step))+'.json')
        response.write_text(json.dumps({'identity':c.job_identity(self.manifest,step),'result':result}))
        self.state['steps']['source']={'process':'succeeded','artifact':'verified','responseSha256':c.file_sha(response)}
        self.result = result
        return response

    def advance_locally(self, prepared):
        # Exercise materialization only. Actual owner-CAS rollover has separate
        # runtime tests; this fixture faithfully archives original response IDs.
        directory=runtime.folder(self.root,self.state['runKey'])
        (directory/'revision-1.json').write_text(json.dumps(self.state))
        self.state['manifest']=prepared['manifest'];self.state['planHash']=prepared['planHash']
        self.state['steps']['source']['reusedFromRevision']=1
        self.state['steps']['english-review']={'process':'not_started','artifact':'not_started'}
        self.state['stateRevision']+=1

    def external_review(self):
        package=c.read(self.result['candidatePath'])
        anchor=c.read(package['anchors']['artifact']['path'])
        receipt={'schemaVersion':'sermon-english-source-review-v1','humanApproval':True,
                 'reviewedBy':'offline fixture reviewer','reviewedAt':'2026-10-04T00:00:00Z',
                 'alignedSegmentsSha256':package['transcript']['artifact']['sha256'],
                 'anchorManifestJsonSha256':package['anchors']['artifact']['jsonSha256'],
                 'reviewedSourceUnitIds':[u['sourceUnitId'] for u in anchor['sourceUnits']],
                 'checks':{key:'approved' for key in english.APPROVED_CHECKS}}
        path=self.source.root/'human-review.json';path.write_text(json.dumps(receipt))
        out=self.source.root/'source'
        approved=english.build_package(Path(package['transcript']['artifact']['path']),
            Path(package['anchors']['artifact']['path']),summary_path=out/'summary.json',
            approval_evidence_path=self.source.approval,review_path=path,machine_judge_path=out/'machine-judge.json',
            source_id=self.source.config['sourceId'],source_url_hash=self.source.config['sourceUrlHash'],
            service_date=self.source.config['serviceDate'])
        target=self.source.root/'approved-source.json';target.write_text(json.dumps(approved))
        self.state['continuationEvidence']={name:{'path':str(p),'sha256':c.file_sha(p)} for name,p in
            [('englishReceipt',path),('approvedSource',target)]}
        return target

    def test_empty_outputs_then_two_materializations_with_human_wait(self):
        self.assertFalse((self.source.root/'source').exists())
        waiting=subject.prepare_next_revision(self.state,self.recipe_path,self.root)
        self.assertEqual(waiting['status'],'waiting')
        self.assertFalse(self.root.exists())
        self.complete_source()
        first=subject.prepare_next_revision(self.state,self.recipe_path,self.root)
        self.assertEqual(first['status'],'ready')
        self.assertTrue(Path(first['manifestPath']).is_file())
        self.advance_locally(first)
        waiting=subject.prepare_next_revision(self.state,self.recipe_path,self.root)
        self.assertEqual({x['binding'] for x in waiting['requiredEvidence']},{'englishReceipt','approvedSource'})
        self.assertIn('configurationDrafts',waiting['inputContext'])
        self.external_review()
        second=subject.prepare_next_revision(self.state,self.recipe_path,self.root)
        self.assertEqual(second['manifest']['runRevision'],3)
        self.assertEqual(second['manifest']['source'],self.manifest['source'])
        self.assertEqual(c.read(second['receiptPath'])['modelDispatches'],0)
        self.assertFalse(c.read(second['receiptPath'])['humanApprovalCreated'])
        from scripts import inspect_canonical_packages
        checked = inspect_canonical_packages.inspect(Path(second['manifest']['bindings']['inspection']['path']))
        self.assertEqual(checked['nodes']['source']['status'], 'validated')
        self.assertEqual(checked['nodes']['text.zh-Hans']['reasonCode'], 'policy_not_validated')

    def test_unknown_is_zero_write_and_zero_dispatch(self):
        self.state['steps']['source']['process']='waiting_reconciliation'
        with patch.object(self.source,'execute',side_effect=AssertionError('dispatch forbidden')):
            result=subject.prepare_next_revision(self.state,self.recipe_path,self.root)
        self.assertEqual(result['reason'],'reconciliation_required')
        self.assertFalse(self.root.exists())

    def test_bound_delivery_document_resolves_l3_package_and_review_references(self):
        package = self.source.root/'audio-package.json'; package.write_text('{"schemaVersion":"audio"}')
        review = self.source.root/'audio-review.json'; review.write_text('{"schemaVersion":"review"}')
        document = self.source.root/'delivery-draft.json'
        document.write_text(json.dumps({'endpoint':'https://delivery.example.invalid/weekly',
            'inputs':{'audioPackage':{'path':token('port','audio'), 'sha256':{'$port':'audio','field':'sha256'}},
                      'reviewReceipt':binding('binding','audioReview')}}))
        port_ref = {'path':str(package),'sha256':c.file_sha(package)}
        review_ref = {'path':str(review),'sha256':c.file_sha(review)}
        stage = {'id':'l4','ports':{'audio':{'stepId':'audio','role':'audio_package'}},'configs':{}}
        subject._template({'$document':'deliveryDraft'},stage)
        resolved = subject._resolve({'$document':'deliveryDraft'}, ports={'audio':port_ref},
            bindings={'deliveryDraft':{'path':str(document),'sha256':c.file_sha(document)},
                      'audioReview':review_ref}, configs={}, directory=self.source.root/'out')
        self.assertEqual(resolved['endpoint'],'https://delivery.example.invalid/weekly')
        self.assertEqual(resolved['inputs']['audioPackage'],port_ref)
        self.assertEqual(resolved['inputs']['reviewReceipt'],
                         {'path':str(review),'sha256':review_ref['sha256']})
        with self.assertRaisesRegex(ValueError,'document_reference_invalid'):
            subject._resolve({'$document':'deliveryDraft'}, ports={'audio':port_ref},
                bindings={'deliveryDraft':{'path':str(document),'sha256':c.file_sha(document)}},
                configs={}, directory=self.source.root/'out', in_document=True)

    def test_prepare_revision_materializes_bound_delivery_document_from_audio_receipt(self):
        package = self.source.root/'audio-package.json'; package.write_text('{"schemaVersion":"audio"}')
        review = self.source.root/'audio-review.json'; review.write_text('{"schemaVersion":"review"}')
        document = self.source.root/'delivery-draft.json'
        document.write_text(json.dumps({'endpoint':'https://delivery.example.invalid/weekly',
            'inputs':{'audioPackage':{'path':token('port','audio'), 'sha256':{'$port':'audio','field':'sha256'}},
                      'reviewReceipt':binding('binding','audioReview')}}))
        self.manifest['steps'].append({'id':'audio','stageId':'layer3_unit','adapter':'canonical.audio',
            'locale':'zh-Hans','dependsOn':['source'],'scope':'english_ready_for_translation'})
        self.manifest['bindings'].update({
            'deliveryDraft':{'path':str(document),'sha256':c.file_sha(document)},
            'audioReview':{'path':str(review),'sha256':c.file_sha(review)},
        })
        audio_step = self.manifest['steps'][-1]
        audio_response = runtime.folder(self.root,self.state['runKey'])/('response-'+
            c.digest(c.job_identity(self.manifest,audio_step))+'.json')
        audio_response.parent.mkdir(parents=True,exist_ok=True)
        audio_result = {'artifact':'verified','review':'human_pending','productionEligible':False,
            'audioPackage':{'path':str(package),'sha256':c.file_sha(package)}}
        audio_response.write_text(json.dumps({'identity':c.job_identity(self.manifest,audio_step),
                                              'result':audio_result}))
        self.state['steps']['audio']={'process':'succeeded','artifact':'verified','review':'human_pending',
            'responseSha256':c.file_sha(audio_response),'completionEventId':'audio-complete'}
        stage = copy.deepcopy(self.recipe['stages'][0])
        stage.update(id='l4-bound-delivery',ports={'audio':{'stepId':'audio','role':'audio_package'}},
            configs={'delivery':{'adapter':'app.delivery','template':{'$document':'deliveryDraft'}}},
            manifestTemplate={'bindings':{'deliveryConfig':binding('config','delivery')},
                'steps':[{'id':'release','adapter':'app.delivery','stageId':'publish_endpoint',
                    'locale':'zh-Hans','configuration':'deliveryConfig','dependsOn':['audio'],
                    'scope':'english_ready_for_translation'}]})
        stage['requiredEvidence']=[]
        self.recipe['stages']=[stage]
        self.bind_recipe()
        self.state['planHash']=c.plan_hash(self.manifest)
        # Recipe binding participates in the frozen job identity.
        audio_response=runtime.folder(self.root,self.state['runKey'])/('response-'+
            c.digest(c.job_identity(self.manifest,audio_step))+'.json')
        audio_response.write_text(json.dumps({'identity':c.job_identity(self.manifest,audio_step),
                                              'result':audio_result}))
        self.state['steps']['audio']['responseSha256']=c.file_sha(audio_response)
        with patch.object(subject.adapters,'inspect_step'), patch.object(subject.adapters,'verify_result'):
            prepared=subject.prepare_next_revision(self.state,self.recipe_path,self.root)
        self.assertEqual(prepared['status'],'ready')
        config_ref=prepared['manifest']['bindings']['deliveryConfig']
        config=c.read(config_ref['path'])
        self.assertEqual(config['endpoint'],'https://delivery.example.invalid/weekly')
        self.assertEqual(config['inputs']['audioPackage']['path'],str(package))
        self.assertEqual(config['inputs']['audioPackage']['sha256'],c.file_sha(package))
        self.assertEqual(config['inputs']['reviewReceipt']['path'],str(review))
        self.assertEqual(config['inputs']['reviewReceipt']['sha256'],c.file_sha(review))

    def test_changed_upstream_response_is_rejected(self):
        path=self.complete_source();path.write_text(path.read_text()+' ')
        with self.assertRaisesRegex(ValueError,'upstream_evidence_changed'):
            subject.prepare_next_revision(self.state,self.recipe_path,self.root)

    def test_restart_reuses_exact_files_after_interrupted_manifest_commit(self):
        self.complete_source();original=subject._write_once
        def stop(path,value):
            if path.name=='manifest.json': raise RuntimeError('simulated power loss')
            original(path,value)
        with patch.object(subject,'_write_once',side_effect=stop), self.assertRaisesRegex(RuntimeError,'power loss'):
            subject.prepare_next_revision(self.state,self.recipe_path,self.root)
        existing={p:(p.read_bytes(),p.stat().st_mtime_ns) for p in self.root.rglob('reviewConfig.json')}
        prepared=subject.prepare_next_revision(self.state,self.recipe_path,self.root)
        repeated=subject.prepare_next_revision(self.state,self.recipe_path,self.root)
        self.assertEqual(prepared,repeated)
        self.assertTrue(existing)
        self.assertTrue(all((p.read_bytes(),p.stat().st_mtime_ns)==value for p,value in existing.items()))

    def test_recipe_change_and_executable_or_arbitrary_path_are_rejected(self):
        for bad in ({'command':['echo','bad']},{'source':'../../outside'},{'source':'https://example.invalid'}):
            with self.subTest(template=bad):
                value=copy.deepcopy(self.recipe)
                value['stages'][0]['configs']['reviewConfig']['template']=bad
                path=self.source.root/'bad.json';path.write_text(json.dumps(value))
                with self.assertRaises(ValueError): subject.inspect_recipe(path)
        self.recipe_path.write_text(self.recipe_path.read_text()+' ')
        with self.assertRaisesRegex(ValueError,'binding_changed'):
            subject.prepare_next_revision(self.state,self.recipe_path,self.root)

    def test_reviewed_source_cannot_change_upstream_words(self):
        self.complete_source()
        first=subject.prepare_next_revision(self.state,self.recipe_path,self.root);self.advance_locally(first)
        target=self.external_review();value=c.read(target)
        value['source']['sourceId']='different-source';target.write_text(json.dumps(value))
        self.state['continuationEvidence']['approvedSource']['sha256']=c.file_sha(target)
        with self.assertRaisesRegex(ValueError,'approved_content_changed'):
            subject.prepare_next_revision(self.state,self.recipe_path,self.root)

    def test_trusted_ingest_validates_original_receipt_and_source_without_state_write(self):
        self.complete_source()
        first=subject.prepare_next_revision(self.state,self.recipe_path,self.root);self.advance_locally(first)
        self.external_review()
        supplied=self.state.pop('continuationEvidence')
        before=copy.deepcopy(self.state)
        receipt=subject.validate_evidence(self.state,self.recipe_path,self.root,'englishReceipt',supplied['englishReceipt']['path'])
        self.assertEqual(self.state,before)
        self.assertEqual(receipt['sha256'],supplied['englishReceipt']['sha256'])
        self.state['continuationEvidence']={'englishReceipt':receipt}
        approved=subject.validate_evidence(self.state,self.recipe_path,self.root,'approvedSource',supplied['approvedSource']['path'])
        self.assertEqual(approved['sha256'],supplied['approvedSource']['sha256'])
        self.assertEqual(approved['kind'],'approved_source')

    def test_normalized_review_is_not_exported_as_original_bytes(self):
        self.complete_source()
        first=subject.prepare_next_revision(self.state,self.recipe_path,self.root);self.advance_locally(first)
        self.external_review()
        ref=self.state['continuationEvidence']['englishReceipt']
        stored=runtime.folder(self.root,self.state['runKey'])/('review-'+ref['sha256']+'.json')
        stored.write_text(json.dumps(c.read(ref['path']),indent=2))
        self.state['steps']['english-review']={'process':'succeeded','artifact':'verified','review':'approved'}
        record={'originalSha256':ref['sha256'],'storedSha256':c.file_sha(stored),'kind':'english'}
        self.state['reviews']['english-review']=record
        port={'stepId':'english-review','role':'original_review_receipt'}
        with self.assertRaisesRegex(ValueError,'original_review_bytes_unavailable'):
            subject._port(self.state,port,self.root)
        record['originalPath']=ref['path']
        self.assertEqual(subject._port(self.state,port,self.root)['sha256'],ref['sha256'])

    def test_missing_budget_waits_with_input_drafts_and_no_dispatch(self):
        self.recipe['stages'][0]['requiredEvidence']=[{'kind':'budget_authorization','binding':'futureBudget'}]
        self.bind_recipe();self.state['planHash']=c.plan_hash(self.manifest)
        self.complete_source()
        with patch.object(subject.adapters,'execute',side_effect=AssertionError('must not dispatch')):
            waiting=subject.prepare_next_revision(self.state,self.recipe_path,self.root)
        self.assertEqual(waiting['requiredEvidence'][0]['binding'],'futureBudget')
        draft=waiting['inputContext']['configurationDrafts']['reviewConfig']
        self.assertEqual(c.digest(draft['value']),draft['jsonSha256'])
        self.assertFalse(Path(draft['path']).exists())

    def test_locale_scoped_layer2_budget_ingestion_and_invalid_scope(self):
        from tests import test_canonical_layer2_budget_shards as budget_fixture
        f = budget_fixture.LocaleLedgerTests('test_locale_authorization_shards_the_ledger_by_locale')
        f.setUp(); self.addCleanup(f.doCleanups)
        authorization = f.write_locale_authorization()
        self.manifest['productionRunId'] = f.base.config.run_id
        self.recipe['productionRunId'] = f.base.config.run_id
        self.manifest['bindings']['layer2Configuration'] = {
            'path': str(f.base.config.path), 'sha256': c.file_sha(f.base.config.path)}
        self.recipe['stages'][0]['requiredEvidence'] = [
            {'kind': 'budget_authorization', 'binding': 'localeBudget',
             'inputs': {'configuration': token('binding', 'layer2Configuration')}}]
        self.bind_recipe()
        before = copy.deepcopy(self.state)
        with patch.object(subject.adapters, 'execute', side_effect=AssertionError('dispatch forbidden')):
            admitted = subject.validate_evidence(
                self.state, self.recipe_path, self.root, 'localeBudget', authorization)
        self.assertEqual(admitted['sha256'], c.file_sha(authorization))
        self.assertEqual(admitted['kind'], 'budget_authorization')
        self.assertEqual(self.state, before)
        self.assertFalse(self.root.exists())
        # Additional manifest locales handled elsewhere do not enlarge this
        # one-lane controller's authorization or reject its valid budget.
        self.manifest['locales'] = ['zh-Hans', 'ko', 'es']
        template = self.manifest['policies'][0]
        self.manifest['policies'] = [{**template, 'locale': locale}
                                    for locale in self.manifest['locales']]
        before = copy.deepcopy(self.state)
        subject.validate_evidence(self.state, self.recipe_path, self.root, 'localeBudget', authorization)
        self.assertEqual(self.state, before)
        self.assertFalse(self.root.exists())

        # Conversely a one-locale manifest cannot reduce an authorization
        # bound to a controller registering three independently spendable lanes.
        from scripts import canonical_layer2_controller as controller
        for locale in ('ko', 'es'):
            f.base.fixture.config_data['locales'][locale] = {
                'outputDirectory': 'outputs/' + locale,
                'plugin': f.base.fixture.config_data['locales']['zh-Hans']['plugin']}
            f.base.fixture.fixture.config['locales'][locale] = copy.deepcopy(
                f.base.fixture.fixture.config['locales']['zh-Hans'])
        f.base.fixture.fixture.write('inspection.json', f.base.fixture.fixture.config)
        f.base.fixture.save_config()
        f.base.config = controller.load_configuration(f.base.fixture.path)
        for path in (f.base.receipt, f.base.auth_path):
            value = c.read(path)
            value.get('binding', value)['configurationSha256'] = f.base.config.sha256
            path.write_text(json.dumps(value))
        authorization = f.write_locale_authorization()
        self.manifest['bindings']['layer2Configuration']['sha256'] = c.file_sha(f.base.config.path)
        self.manifest['locales'] = ['zh-Hans']
        self.manifest['policies'] = [template]
        before = copy.deepcopy(self.state)
        with self.assertRaisesRegex(ValueError, 'budget_execution_binding_changed'):
            subject.validate_evidence(self.state, self.recipe_path, self.root, 'localeBudget', authorization)
        self.assertEqual(self.state, before)
        self.manifest['budget']['limitMicroUsd'] = 3 * c.read(authorization)['authority']['globalBounds']['costMicrousd']
        before = copy.deepcopy(self.state)
        subject.validate_evidence(self.state, self.recipe_path, self.root, 'localeBudget', authorization)
        self.assertEqual(self.state, before)

        value = c.read(authorization)
        value['ledgerScope'] = 'run'
        authorization.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'continuation_budget_schema_invalid'):
            subject.validate_evidence(
                self.state, self.recipe_path, self.root, 'localeBudget', authorization)
        self.assertEqual(self.state, before)

    def test_locale_scoped_budget_requires_verified_configuration_input(self):
        from tests import test_canonical_layer2_budget_shards as budget_fixture
        f = budget_fixture.LocaleLedgerTests('test_locale_authorization_shards_the_ledger_by_locale')
        f.setUp(); self.addCleanup(f.doCleanups)
        authorization = f.write_locale_authorization()
        self.manifest['productionRunId'] = f.base.config.run_id
        self.recipe['productionRunId'] = f.base.config.run_id
        self.recipe['stages'][0]['requiredEvidence'] = [
            {'kind': 'budget_authorization', 'binding': 'localeBudget'}]
        self.bind_recipe()
        with self.assertRaisesRegex(ValueError, 'budget_configuration_required'):
            subject.validate_evidence(self.state, self.recipe_path, self.root, 'localeBudget', authorization)
        self.manifest['bindings']['layer2Configuration'] = {
            'path': str(f.base.config.path), 'sha256': 'f' * 64}
        self.recipe['stages'][0]['requiredEvidence'][0]['inputs'] = {
            'configuration': token('binding', 'layer2Configuration')}
        self.bind_recipe()
        with self.assertRaisesRegex(ValueError, 'binding_changed'):
            subject.validate_evidence(self.state, self.recipe_path, self.root, 'localeBudget', authorization)

    def test_generated_bytes_cannot_be_overwritten_after_restart(self):
        self.complete_source()
        prepared=subject.prepare_next_revision(self.state,self.recipe_path,self.root)
        path=Path(prepared['manifest']['bindings']['reviewConfig']['path'])
        path.write_text(path.read_text()+' ')
        with self.assertRaisesRegex(ValueError,'immutable_output_changed'):
            subject.prepare_next_revision(self.state,self.recipe_path,self.root)

    def test_study_budget_slot_checks_receipt_code_root_cap_and_full_prepare(self):
        from tests import test_sermon_study_generation as study_fixture
        f=study_fixture.GenerationTests('test_generation_resume_human_pending_and_verify')
        f.setUp();self.addCleanup(f.doCleanups)
        manifest=copy.deepcopy(f.manifest);manifest['budget']={'limitMicroUsd':1000000}
        state={'manifest':manifest}
        slot={'binding':'studyBudget','kind':'budget_authorization'}
        ref=manifest['bindings']['budgetAuthorization']
        actual=subject.validate_evidence_slot(state,slot,ref,inputs={},references={})
        self.assertEqual(actual['sha256'],ref['sha256'])
        # Real authorization loader is called without executing a provider.
        study_fixture.g.prepare(manifest,f.root,f.config,f.step)
        for field,value in [('codeIdentitySha256','d'*64),('budgetRoot',str(f.root/'other-root'))]:
            with self.subTest(field=field):
                changed=c.read(ref['path']);changed['binding'][field]=value
                path=f.root/'altered-authorization.json';path.write_text(json.dumps(changed))
                with self.assertRaises(ValueError):
                    subject.validate_evidence_slot(state,slot,{'path':str(path),'sha256':c.file_sha(path)},inputs={},references={})
        state['manifest']['budget']['limitMicroUsd']=999999
        with self.assertRaisesRegex(ValueError,'budget_execution_binding_changed'):
            subject.validate_evidence_slot(state,slot,ref,inputs={},references={})
        # Even a coherent, independently supplied receipt for another execution
        # is rejected at the final producer admission, before any API call.
        state['manifest']['budget']['limitMicroUsd']=1000000
        changed=c.read(ref['path']);changed['binding']['executionSha256']='e'*64
        approval=c.read(f.root/'approval.json');approval['binding']=changed['binding']
        altered=f.root/'other-approval.json';altered.write_text(json.dumps(approval))
        changed['approvalReceipt']=str(altered)
        changed['approvalReceiptSha256']=c.file_sha(altered)
        changed['authority']['approvalSha256']=c.file_sha(altered)
        path=f.root/'other-authorization.json';path.write_text(json.dumps(changed))
        manifest['bindings']['budgetAuthorization']={'path':str(path),'sha256':c.file_sha(path)}
        with self.assertRaisesRegex(ValueError,'study_budget_binding_changed'):
            study_fixture.g.prepare(manifest,f.root,f.config,f.step)
        self.assertEqual(f.calls,[])
