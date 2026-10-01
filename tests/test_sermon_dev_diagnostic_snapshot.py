"""Local snapshot contract and fake publish/HTTP boundaries; no remote calls."""
from copy import deepcopy
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import sermon_dev_diagnostic_snapshot as dev
from scripts import sermon_diagnostic_dag_session as sessions
from scripts import sermon_accounting as accounting
from scripts import sermon_log_profile as profile
from scripts import sermon_review_contracts as c
from scripts import sermon_strict_layer2 as immutable
from tests.diagnostic_dag_fixture import DiagnosticDAGFixture


class DevSnapshotTests(unittest.TestCase):
    def setUp(self):
        f=DiagnosticDAGFixture();f.setUp();self.addCleanup(f.doCleanups);self.f=f
        self.enterContext(patch.object(accounting,'execution_identity',return_value=f.execution_identity))
        self.session=sessions.DiagnosticSession(f.plan,f.continuation,offline_transport=f.transport)
        immutable.save_once(f.root/'source.json',f.source)
        self.base=f.root/'baseline';(self.base/'public').mkdir(parents=True)
        immutable.save_once(self.base/'firebase.json',{'hosting':{'site':dev.PROJECT,'public':'public'}})
        (self.base/'public/multilingual-v3.json').write_text('{"formal":"unchanged"}')
        (self.base/'public/published-weeks.mjs').write_text('export async function loadPublishedWeeks(){return {weeks:[],errors:[]}}')
        # A preceding diagnostic adapter must not be overwritten into a self import.
        (self.base/'public/published-weeks-before-diagnostic.mjs').write_text('original formal catalog loader')
        self.out=f.root/'dev-snapshot'
        self.no_network=self.enterContext(patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('network forbidden')))

    def build(self,nodes=None):
        stages={'schemaVersion':'sermon-dev-diagnostic-stage-results-v1','runId':self.session.subject.config['runId'],
                'diagnosticContextSha256':c.canonical_sha256(self.session.context),'nodes':nodes or {}}
        with self.f.session():
            return dev.build_snapshot(self.session,baseline=self.base,out=self.out,page_id='fixture-fresh',preview_receipts={},stage_results=stages,depends_on=[])

    def test_absent_candidates_have_typed_blocked_state_current_ui_and_formal_catalog_unchanged(self):
        before=dev._files(self.base)
        with patch.object(dev,'_decode'),patch.object(dev,'_probe',return_value=180.):
            result=self.build()
        public=self.out/'hosting/public';payload=dev._read(public/'diagnostic/fixture-fresh/latest.json')
        self.assertEqual(dev._files(self.base),before)
        self.assertEqual(dev._sha(public/'multilingual-v3.json'),dev._sha(self.base/'public/multilingual-v3.json'))
        for locale,row in payload['week']['contentVariants'].items():
            self.assertEqual(row['diagnosticState']['status'],'pending')
            self.assertFalse(row['diagnosticState']['machineCandidateAvailable'])
            self.assertEqual(row['fullTranscript'],[]);self.assertEqual(row['tracks'],[]);self.assertEqual(row['outline'],[])
            self.assertEqual(row['diagnosticInputSha256'],row['diagnosticState']['inputBindingSha256'])
        for name in dev.UI:self.assertEqual(dev._sha(public/name),dev._sha(dev.REPO/'experiments/sermon-dubbing-poc/web'/name))
        self.assertEqual((public/'published-weeks-before-diagnostic.mjs').read_text(),'original formal catalog loader')
        self.assertIn('published-weeks-parent-',(public/'published-weeks.mjs').read_text())
        self.assertFalse(result['publicationAuthorized']);self.no_network.assert_not_called()

    def test_real_candidate_text_binding_no_audio_is_pending_and_never_formal(self):
        with self.f.session():
            self.session.run_locale('zh-Hans',self.f.locale_specs['zh-Hans'],depends_on=[])
        with patch.object(dev,'_decode'),patch.object(dev,'_probe',return_value=180.):result=self.build()
        payload=dev._read(self.out/'hosting/public/diagnostic/fixture-fresh/latest.json')
        row=payload['week']['contentVariants']['zh-Hans']
        self.assertTrue(row['fullTranscript']);self.assertTrue(all(x['text'].strip() for x in row['fullTranscript']))
        self.assertTrue(row['diagnosticState']['machineCandidateAvailable']);self.assertEqual(row['diagnosticState']['status'],'pending')
        self.assertEqual(row['diagnosticState']['reasonCode'],'preview_audio_unavailable')
        self.assertFalse(result['manifest']['formalReleasePackageCreated'])

    def test_exact_snapshot_and_flow_contract_reasons_survive_public_projection(self):
        reasons=('invalid_snapshot_file','diagnostic_flow_plan_changed','diagnostic_flow_frozen_inputs_changed')
        nodes={f'text.{locale}':dict(nodeId=f'text.{locale}',executionStatus='failed',processed=False,
            readyForDownstream=False,reason=reason) for locale,reason in zip(('zh-Hans','ko','es'),reasons)}
        with patch.object(dev,'_decode'),patch.object(dev,'_probe',return_value=180.):self.build(nodes)
        variants=dev._read(self.out/'hosting/public/diagnostic/fixture-fresh/latest.json')['week']['contentVariants']
        for locale,reason in zip(('zh-Hans','ko','es'),reasons):
            row=variants[locale]
            self.assertEqual(row['diagnosticState']['status'],'failed')
            self.assertEqual(row['diagnosticState']['reasonCode'],reason)
            self.assertFalse(row['diagnosticState']['machineCandidateAvailable'])
            self.assertEqual(row['tracks'],[]);self.assertEqual(row['outline'],[])
            self.assertTrue(row['diagnosticOnly']);self.assertEqual(row['humanContentReview'],'pending')
        self.no_network.assert_not_called()

    def test_exact_pre_provider_identity_reason_survives_snapshot_without_private_fields(self):
        from scripts import sermon_historical_identity as identity
        reason='historical_current_code_changed'
        nodes={'text.es':dict(nodeId='text.es',executionStatus='blocked',processed=False,
            readyForDownstream=False,reason=reason,failurePhase='before_locale_provider_dispatch',
            providerDispatchOccurred=False,errorType=identity.HistoricalIdentityPreDispatchRejected.__name__,
            privateMessage='/private/operator/identity/body')}
        with patch.object(dev,'_decode'),patch.object(dev,'_probe',return_value=180.):self.build(nodes)
        payload=dev._read(self.out/'hosting/public/diagnostic/fixture-fresh/latest.json')
        row=payload['week']['contentVariants']['es']
        self.assertEqual(row['diagnosticState']['status'],'blocked')
        self.assertEqual(row['diagnosticState']['reasonCode'],reason)
        self.assertFalse(row['diagnosticState']['machineCandidateAvailable'])
        self.assertEqual(row['tracks'],[])
        self.assertNotIn('/private/operator/identity/body',json.dumps(payload))
        self.assertNotIn('failurePhase',row['diagnosticState'])  # Existing public schema stays fixed.
        self.no_network.assert_not_called()

    def test_original_guard_reason_projects_exactly_without_rewriting_unknown_receipt(self):
        reason='diagnostic_unbounded_subprocess_forbidden'
        node=dict(reason=reason,executionStatus='outcome_unknown',processed=None,readyForDownstream=False)
        before=deepcopy(node)
        self.assertEqual(dev.stage_presentation(node,candidate=False,preview=False),('blocked',reason))
        self.assertEqual(node,before)
        self.assertNotIn('providerDispatchOccurred',node)
        node['reason']=reason+': /private/operator/command'
        self.assertEqual(dev.stage_presentation(node,candidate=False,preview=False),('blocked','unclassified_failure'))

    def test_identity_reason_catalog_is_exact_no_prefix_or_message_projection(self):
        from scripts import sermon_historical_identity as identity
        for reason in identity.PRE_PROVIDER_CODES:
            with self.subTest(reason=reason):
                node=dict(reason=reason,executionStatus='blocked',readyForDownstream=False)
                self.assertEqual(dev.stage_presentation(node,candidate=False,preview=False),('blocked',reason))
                node['reason']=reason+': /private/operator/body'
                self.assertEqual(dev.stage_presentation(node,candidate=False,preview=False),('blocked','unclassified_failure'))

    def test_known_reason_prefixes_and_private_freeform_errors_remain_unclassified(self):
        for reason in ('invalid_snapshot_file: /private/operator/large-plan.json',
                       'diagnostic_flow_plan_changed /private/operator/plan.json',
                       'diagnostic_flow_frozen_inputs_changed: private-hash-value',
                       'unknown_failure',None,{'message':'private'}):
            with self.subTest(reason=reason):
                self.assertEqual(dev.stage_presentation(dict(reason=reason,executionStatus='failed',
                    readyForDownstream=False),candidate=False,preview=False),('failed',
                    'unclassified_failure' if reason else 'strict_locale_group_not_passed'))

    def test_non_dev_target_is_rejected_before_copy(self):
        (self.base/'firebase.json').write_text(json.dumps({'hosting':{'site':'formal-site'}}))
        with self.assertRaisesRegex(ValueError,'target_invalid'):self.build()
        self.assertFalse(self.out.exists());self.no_network.assert_not_called()

    def test_known_worker_failure_with_candidate_and_failed_locale_preserve_public_state(self):
        with self.f.session():self.session.run_locale('zh-Hans',self.f.locale_specs['zh-Hans'],depends_on=[])
        nodes={'preview.zh-Hans':{'nodeId':'preview.zh-Hans','executionStatus':'outcome_unknown','processed':None,
            'readyForDownstream':False,'reason':'preview_worker_failed_requires_reconciliation'},
            'text.ko':{'nodeId':'text.ko','executionStatus':'completed','processed':True,'readyForDownstream':False,
                'reasonCode':'strict_bridge_plugin_rejected'}}
        with patch.object(dev,'_decode'),patch.object(dev,'_probe',return_value=180.):self.build(nodes)
        variants=dev._read(self.out/'hosting/public/diagnostic/fixture-fresh/latest.json')['week']['contentVariants']
        self.assertEqual(variants['zh-Hans']['diagnosticState']['status'],'failed')
        self.assertTrue(variants['zh-Hans']['diagnosticState']['machineCandidateAvailable'])
        self.assertEqual(variants['zh-Hans']['diagnosticState']['reasonCode'],'preview_worker_failed_requires_reconciliation')
        self.assertEqual(variants['ko']['diagnosticState']['status'],'failed')
        self.assertEqual(variants['ko']['diagnosticState']['reasonCode'],'strict_bridge_plugin_rejected')
        self.assertFalse(variants['ko']['diagnosticState']['machineCandidateAvailable'])


class DevPublishTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve()
        f=DiagnosticDAGFixture();f.setUp();self.addCleanup(f.doCleanups)
        for name,value in (('source.json',f.source),('anchor-manifest.json',f.anchor),('diagnostic-context.json',f.context)):
            immutable.save_once(self.root/name,value)
        self.out=self.root/'snapshot';public=self.out/'hosting/public';public.mkdir(parents=True)
        video=public/'media/fresh/source.mp4';video.parent.mkdir(parents=True);video.write_bytes(b'v'*2048)
        (public/'app.mjs').write_bytes(b'app')
        immutable.save_once(self.out/'hosting/firebase.json',{'hosting':{'site':dev.PROJECT}})
        self.manifest={'schemaVersion':dev.SCHEMA,'runId':f.config['runId'],'contextSha256':c.canonical_sha256(f.context),
            'target':{'project':dev.PROJECT,'site':dev.PROJECT,'origin':dev.ORIGIN},
            'evidenceMode':'current_execution','productionEligible':False,'pageId':'fresh','publicFiles':dev._files(public)}
        immutable.save_once(self.out/'snapshot-manifest.json',self.manifest)
        self.snapshot={'out':str(self.out),'manifest':self.manifest}
        self.authorization={'schemaVersion':'sermon-dev-diagnostic-publication-authorization-v1','manifestSha256':c.canonical_sha256(self.manifest),
            'project':dev.PROJECT,'site':dev.PROJECT,'origin':dev.ORIGIN,'publicationScope':'diagnostic_preview_only',
            'productionEligible':False,'approvalSha256':'b'*64}
        from contextlib import contextmanager
        @contextmanager
        def locked():yield None,{'startedMonotonic':10,'requests':{'call':{'state':'returned'}}}
        self.subject=SimpleNamespace(config=f.config,store=SimpleNamespace(store_sha256=f.store.store_sha256),
            _locked=locked,_remaining=lambda state:5400,monotonic=lambda:20.)
        identity=accounting.execution_identity()
        self.enterContext(patch.object(accounting,'execution_identity',return_value=identity))
        self.enterContext(patch.object(dev.bounded,'prepare_plan',return_value=(self.root,self.subject)))
        self.deploy=self.enterContext(patch.object(dev.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=b'success',stderr=b'')))
        def response(request,timeout):
            relative=request.full_url.split(dev.ORIGIN+'/')[1];data=(public/relative).read_bytes()
            result=io.BytesIO(data[:1024] if request.get_header('Range') else data)
            result.status=206 if request.get_header('Range') else 200
            result.headers={'Content-Range':'bytes 0-1023/2048'}
            return result
        self.http=self.enterContext(patch.object(dev,'urlopen',side_effect=response))

    def publish(self,**kwargs):
        with profile.session(self.root/'logs','dev-publish-fixture',work_kind='engineering',evidence_mode='synthetic'):
            return dev.publish_and_verify(self.snapshot,plan={},authorization=self.authorization,execute=True,depends_on=[],**kwargs)

    def test_exact_dev_command_hash_http_range_and_resume_no_second_deploy(self):
        result=self.publish()
        self.assertEqual(result['status'],'published_http_verified');self.assertTrue(result['rangeVerified'])
        command=self.deploy.call_args.args[0]
        self.assertEqual(command,['firebase','deploy','--project',dev.PROJECT,'--only','hosting','--non-interactive'])
        self.assertEqual(self.deploy.call_count,1)
        before={name:(self.out/name).read_bytes() for name in
                ('publish-intent.json','publish-returned.json','http-receipt.json')}
        self.http.reset_mock()
        self.assertEqual(self.publish()['status'],'published_http_verified')
        self.assertEqual(self.deploy.call_count,1);self.assertEqual(self.http.call_count,3)
        self.assertTrue(all((self.out/name).read_bytes()==data for name,data in before.items()))
        events=[json.loads(line) for line in (self.root/'logs/events.jsonl').read_text().splitlines()]
        started=[row for row in events if row['event']=='stage_started']
        self.assertEqual(len([row for row in started if row['stage']=='diagnostic.dev_publish']),1)
        replay=[row for row in started if row['stage']=='diagnostic.dev_publish_replay']
        self.assertEqual(len(replay),1);self.assertTrue(replay[0]['cacheHit'])
        self.assertEqual(replay[0]['executorType'],'deterministic_program')
        current_http=[row for row in started if row['stage']=='diagnostic.dev_http'][-1]
        self.assertEqual(current_http['dependsOn'],[replay[0]['spanId']])
        binding=[row['metrics'] for row in events if row.get('stage')=='diagnostic.dev_publish_replay_binding']
        self.assertEqual(binding,[dict(manifestSha256=c.canonical_sha256(self.manifest),
            intentSha256=c.bytes_sha256(before['publish-intent.json']),
            returnedSha256=c.bytes_sha256(before['publish-returned.json']))])

    def test_known_deploy_partial_http_failure_rechecks_without_second_deploy(self):
        original=self.http.side_effect;failed=list(self.manifest['publicFiles'])[1]
        def partial(request,timeout):
            if request.full_url.endswith('/'+failed) and not request.get_header('Range'):
                raise OSError('fixture interrupted HTTP')
            return original(request,timeout)
        self.http.side_effect=partial
        with self.assertRaises(OSError):self.publish()
        self.assertEqual(self.deploy.call_count,1)
        self.assertFalse((self.out/'http-receipt.json').exists())
        before={name:(self.out/name).read_bytes() for name in ('publish-intent.json','publish-returned.json')}
        self.http.side_effect=original;self.http.reset_mock()
        result=self.publish()
        self.assertEqual(result['status'],'published_http_verified')
        self.assertEqual(self.deploy.call_count,1);self.assertEqual(self.http.call_count,3)
        self.assertTrue(all((self.out/name).read_bytes()==data for name,data in before.items()))
        events=[json.loads(line) for line in (self.root/'logs/events.jsonl').read_text().splitlines()]
        http=[row for row in events if row['event']=='stage_finished' and row['stage']=='diagnostic.dev_http']
        self.assertEqual([row['status'] for row in http],['failed','completed'])

    def test_replay_authority_manifest_receipt_hashes_and_orphan_reject_before_http(self):
        self.publish();self.http.reset_mock()
        paths={name:self.out/name for name in ('publish-intent.json','publish-returned.json')}
        originals={name:path.read_bytes() for name,path in paths.items()}
        mutations=(('publish-intent.json','manifestSha256','0'*64),
                   ('publish-intent.json','status','completed'),
                   ('publish-returned.json','manifestSha256','0'*64),
                   ('publish-returned.json','stdoutSha256','not-a-hash'),
                   ('publish-returned.json','exitCode',False))
        for name,key,value in mutations:
            with self.subTest(name=name,key=key):
                invalid=dev._read(paths[name]);invalid[key]=value;dev._write(paths[name],invalid)
                with self.assertRaisesRegex(ValueError,'dev_publication_replay_changed'):self.publish()
                self.http.assert_not_called();self.assertEqual(self.deploy.call_count,1)
                paths[name].write_bytes(originals[name])
        previous=self.authorization['approvalSha256'];self.authorization['approvalSha256']='c'*64
        with self.assertRaisesRegex(ValueError,'dev_publication_replay_changed'):self.publish()
        self.authorization['approvalSha256']=previous
        paths['publish-intent.json'].unlink()
        with self.assertRaisesRegex(ValueError,'dev_publication_replay_changed'):self.publish()
        self.assertFalse(paths['publish-intent.json'].exists())
        self.http.assert_not_called();self.assertEqual(self.deploy.call_count,1)

    def test_replay_preserves_original_deadline_and_local_input_guard(self):
        self.publish();self.http.reset_mock()
        app=self.out/'hosting/public/app.mjs';before=app.read_bytes();app.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'dev_publish_snapshot_changed'):self.publish()
        app.write_bytes(before)
        self.subject.monotonic=lambda:10+self.subject.config['totalWallSeconds']+1
        with self.assertRaisesRegex(ValueError,'dev_publish_original_deadline_reached'):self.publish()
        self.http.assert_not_called();self.assertEqual(self.deploy.call_count,1)

    def add_progress_assets(self):
        public=self.out/'hosting/public'
        for index in range(20):(public/f'progress-{index:02d}.bin').write_bytes(bytes([index])*3)
        self.manifest['publicFiles']=dev._files(public)
        dev._write(self.out/'snapshot-manifest.json',self.manifest)
        self.authorization['manifestSha256']=c.canonical_sha256(self.manifest)

    def progress_events(self):
        rows=[json.loads(line) for line in (self.root/'logs/events.jsonl').read_text().splitlines()]
        return [row['metrics'] for row in rows if row.get('event')=='workload' and
                row.get('stage')=='diagnostic.dev_http_progress']

    def test_actual_http_progress_counts_only_verified_assets_and_final_after_range(self):
        self.add_progress_assets();result=self.publish();rows=self.progress_events()
        self.assertEqual([row['verifiedAssets'] for row in rows],[10,20,22])
        self.assertEqual([row['verificationComplete'] for row in rows],[0,0,1])
        self.assertEqual(rows[-1]['verifiedBytes'],sum(p.stat().st_size for p in (self.out/'hosting/public').rglob('*') if p.is_file()))
        self.assertTrue(result['rangeVerified'])
        events=[json.loads(line) for line in (self.root/'logs/events.jsonl').read_text().splitlines()]
        streamed=[row['metrics'] for row in events if row.get('stage')=='diagnostic.dev_http_download_progress']
        self.assertEqual(len(streamed),22)
        self.assertEqual([row['assetIndex'] for row in streamed],list(range(1,23)))
        self.assertTrue(all(row['verificationComplete']==0 for row in streamed))
        self.assertEqual(sum(row['currentDownloadedBytes'] for row in streamed),rows[-1]['verifiedBytes'])
        for row in rows:
            self.assertEqual(set(row),{'manifestSha256','verifiedAssets','totalAssets','verifiedBytes','verificationComplete'})
            self.assertEqual(row['manifestSha256'],self.authorization['manifestSha256'])
            self.assertEqual(row['totalAssets'],22)
            self.assertTrue(all(type(v) is int for k,v in row.items() if k!='manifestSha256'))

    def test_actual_http_failed_asset_not_counted_and_never_records_final_success(self):
        self.add_progress_assets();response=self.http.side_effect
        failed=list(self.manifest['publicFiles'])[10]
        def corrupt(request,timeout):
            result=response(request,timeout)
            if request.full_url.endswith('/'+failed):
                data=result.read();result.close();result=io.BytesIO(bytes(v^255 for v in data));result.status=200
            return result
        self.http.side_effect=corrupt
        with self.assertRaisesRegex(ValueError,'dev_http_asset_changed'):self.publish()
        rows=self.progress_events()
        self.assertEqual([row['verifiedAssets'] for row in rows],[10])
        self.assertEqual(rows[0]['verificationComplete'],0)
        expected=sum((self.out/'hosting/public'/name).stat().st_size for name in list(self.manifest['publicFiles'])[:10])
        self.assertEqual(rows[0]['verifiedBytes'],expected)
        self.assertFalse((self.out/'http-receipt.json').exists())

    def test_large_http_stream_failure_records_unverified_bytes_without_verified_success(self):
        public=self.out/'hosting/public';path=public/'000-large.bin'
        path.write_bytes(b'z'*(17*1024*1024))
        self.manifest['publicFiles']=dev._files(public)
        dev._write(self.out/'snapshot-manifest.json',self.manifest)
        self.authorization['manifestSha256']=c.canonical_sha256(self.manifest)
        original=self.http.side_effect
        class InterruptedStream(io.BytesIO):
            def read(self,count=-1):
                if self.tell()>=16*1024*1024:raise OSError('fixture private stream failure')
                return super().read(count)
        def interrupted(request,timeout):
            if request.full_url.endswith('/000-large.bin'):
                result=InterruptedStream(path.read_bytes());result.status=200;return result
            return original(request,timeout)
        self.http.side_effect=interrupted
        with self.assertRaises(OSError):self.publish()
        log=(self.root/'logs/events.jsonl').read_text()
        rows=[json.loads(line) for line in log.splitlines()]
        streamed=[row['metrics'] for row in rows if row.get('event')=='workload' and
                  row.get('stage')=='diagnostic.dev_http_download_progress']
        self.assertEqual(streamed,[dict(manifestSha256=self.authorization['manifestSha256'],assetIndex=1,
            currentDownloadedBytes=16*1024*1024,verificationComplete=0)])
        self.assertEqual(self.progress_events(),[])
        self.assertFalse((self.out/'http-receipt.json').exists())
        self.assertNotIn('fixture private stream failure',log)

    def test_actual_http_failed_range_cannot_record_final_success(self):
        self.add_progress_assets();response=self.http.side_effect
        def bad_range(request,timeout):
            result=response(request,timeout)
            if request.get_header('Range'):result.headers={'Content-Range':'bytes 0-1023/999999'}
            return result
        self.http.side_effect=bad_range
        with self.assertRaisesRegex(ValueError,'dev_http_range_changed'):self.publish()
        self.assertEqual([row['verifiedAssets'] for row in self.progress_events()],[10,20])
        self.assertTrue(all(row['verificationComplete']==0 for row in self.progress_events()))
        self.assertFalse((self.out/'http-receipt.json').exists())

    def test_unknown_deploy_is_not_repeated_and_raw_body_not_saved(self):
        self.deploy.side_effect=TimeoutError('private CLI credential body')
        with self.assertRaises(TimeoutError):self.publish()
        self.assertTrue((self.out/'publish-intent.json').exists());self.http.assert_not_called()
        with self.assertRaisesRegex(ValueError,'reconciliation'):self.publish()
        self.assertEqual(self.deploy.call_count,1)
        for path in self.out.glob('publish-*.json'):self.assertNotIn('private CLI',path.read_text())

    def test_bad_target_fixture_and_changed_assets_cannot_dispatch(self):
        self.authorization['project']='formal-site'
        with self.assertRaisesRegex(ValueError,'authorization_required'):self.publish()
        self.deploy.assert_not_called();self.http.assert_not_called()
