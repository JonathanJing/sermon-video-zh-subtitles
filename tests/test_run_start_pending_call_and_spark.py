"""Read-only run preflight follows the selected Spark host and runner call markers."""
import json
import os
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from scripts import check_run_start as check


class SparkSelectedHostTests(unittest.TestCase):
    def test_gpu_session_for_another_host_cannot_validate_selected_host(self):
        with patch.dict(os.environ,{'SPARK_EXCLUSIVE_SESSION_ID':'fixture-session','SPARK_EXCLUSIVE_SESSION_OWNER':'fixture-owner','SPARK_EXCLUSIVE_HOST':'host-a'},clear=True),patch.object(check,'ssh') as ssh,patch('tongxing_production.compute.spark_exclusive_session.Client.require_ready') as ready:
            result=check.check_spark('host-b',True,None)
        self.assertEqual(result['status'],'fail')
        self.assertIn('host',result['problems'][0]);ssh.assert_not_called();ready.assert_not_called()

    def test_same_selected_host_is_used_for_reachability_and_ready(self):
        hosts=[]
        def ready(client):hosts.append(client.host);return {'status':'ready'}
        with patch.dict(os.environ,{'SPARK_EXCLUSIVE_SESSION_ID':'fixture-session','SPARK_EXCLUSIVE_SESSION_OWNER':'fixture-owner','SPARK_EXCLUSIVE_HOST':'host-a'},clear=True),patch.object(check,'ssh',return_value=Mock(returncode=0,stdout='synthetic')) as ssh,patch('tongxing_production.compute.spark_exclusive_session.Client.require_ready',ready):
            result=check.check_spark('host-a',True,None)
        self.assertEqual(result['status'],'pass');self.assertEqual(hosts,['host-a'])
        ssh.assert_called_once_with('hostname','host-a')

    def test_api_only_reachability_does_not_require_session_host_match(self):
        with patch.dict(os.environ,{'SPARK_EXCLUSIVE_HOST':'host-a'},clear=True),patch.object(check,'ssh',return_value=Mock(returncode=0,stdout='synthetic')),patch('tongxing_production.compute.spark_exclusive_session.Client.require_ready') as ready:
            result=check.check_spark('host-b',False,None)
        self.assertEqual(result['status'],'pass');self.assertEqual(result['session'],'not_required_api_only');ready.assert_not_called()


class Layer2CallMarkerTests(unittest.TestCase):
    def setUp(self):
        from tests.test_canonical_layer2_controller import CanonicalLayer2ControllerTests
        from scripts import tongxing_host  # noqa: F401  binds the production package ports
        from tongxing_production.review import review_budget as budget
        from scripts import tongxing_host  # noqa: F401  binds the production package ports
        from tongxing_production.text import controller
        from tests.test_sermon_review_budget import authority, identity, request, result
        fixture=CanonicalLayer2ControllerTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        self.config=controller.load_configuration(fixture.path)
        self.locale=next(iter(self.config.lanes));self.lane=self.config.lanes[self.locale]
        self.root=fixture.root/'settled-budget';self.authority=authority()
        store=budget.BudgetStore(self.root,self.authority)
        row=store.reserve(identity(),**request());store.mark_request(row['reservationId']);store.record_result(row['reservationId'],result())
        self.marker=self.lane['output']/'attempt-1'/'group-000-astra.started.json'
        self.marker.parent.mkdir(parents=True,exist_ok=True)
        self.marker.write_text(json.dumps({'role':'translator','payloadSha256':'a'*64,'status':'started_response_unconfirmed'}))
        self.raw=self.marker.with_name('group-000-astra.raw.json');self.cache=self.marker.with_name('group-000-astra.json')

    def snapshot(self):
        return {str(p):(p.read_bytes(),p.stat().st_mtime_ns) for base in [self.root,self.lane['output']] for p in Path(base).rglob('*') if p.is_file()}

    def test_returned_budget_result_does_not_make_an_unrestored_marker_ready(self):
        before=self.snapshot()
        check.inspect_layer2_root(self.root,self.authority,locale_scope=False)
        with self.assertRaisesRegex(ValueError,'requires reconciliation'):check.inspect_layer2_calls(self.config)
        self.assertEqual(self.snapshot(),before)

    def test_complete_payload_bound_raw_passes_read_only(self):
        self.raw.write_text(json.dumps({'payloadSha256':'a'*64,'response':{'id':'synthetic-paid-return','choices':[]}}))
        before=self.snapshot();check.inspect_layer2_calls(self.config)
        self.assertEqual(self.snapshot(),before)

    def test_mismatched_or_incomplete_raw_never_counts_as_recovery(self):
        for raw in [{'payloadSha256':'b'*64,'response':{}},{'payloadSha256':'a'*64}, {'payloadSha256':'a'*64,'response':'not a provider envelope'}]:
            with self.subTest(raw=raw):
                self.raw.write_text(json.dumps(raw));before=self.snapshot()
                with self.assertRaisesRegex(ValueError,'requires reconciliation'):check.inspect_layer2_calls(self.config)
                self.assertEqual(self.snapshot(),before)

    def test_validated_cache_passes_but_corrupt_cache_is_not_hidden_by_raw(self):
        policy=json.loads(Path(self.lane['policy']).read_text())
        valid={'payloadSha256':'a'*64,'model':policy['translator']['model'],'requestId':'synthetic-request','result':{}}
        self.cache.write_text(json.dumps(valid));before=self.snapshot();check.inspect_layer2_calls(self.config)
        self.assertEqual(self.snapshot(),before)
        self.raw.write_text(json.dumps({'payloadSha256':'a'*64,'response':{}}))
        self.cache.write_text(json.dumps({**valid,'payloadSha256':'b'*64}));before=self.snapshot()
        with self.assertRaisesRegex(ValueError,'requires reconciliation'):check.inspect_layer2_calls(self.config)
        self.assertEqual(self.snapshot(),before)

    def test_actual_plan_consumer_refuses_settled_ledger_with_unrestored_lane_marker(self):
        from tests.test_run_start_tools import PlanTests, run_plan
        from scripts import tongxing_host  # noqa: F401  binds the production package ports
        from tongxing_production.review import review_budget as budget
        from tongxing_production.text import budget as l2
        from scripts import tongxing_host  # noqa: F401  binds the production package ports
        from tongxing_production.text import controller
        from tests.test_sermon_review_budget import identity, request, result
        fixture=PlanTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        directory=fixture.base/'layer2-marker-plan'
        args=['--out',str(directory),'--scale','week','--locales',','.join(self.config.lanes),'--total-usd','100',
              '--approved-by','Fixture','--evidence','offline','--layer2-execution',str(self.config.path),'--stage','layer2']
        self.assertEqual(run_plan(*args)[0],0)
        stage=json.loads((directory/'plan.json').read_text())['stages'][0]
        approved=l2.load_authorization(self.config,stage['authorization'],controller.code_identity())
        root=l2.ledger_root(approved,self.locale) if approved['scope']=='locale' else approved['root']
        store=budget.BudgetStore(root,approved['value']['authority'],max_ledger_bytes=l2.LOCALE_LEDGER_MAX_BYTES if approved['scope']=='locale' else None)
        row=store.reserve(identity(),**request());store.mark_request(row['reservationId']);store.record_result(row['reservationId'],result())
        before={str(p):(p.read_bytes(),p.stat().st_mtime_ns) for base in [directory,self.lane['output']] for p in Path(base).rglob('*') if p.is_file()}
        checked=check.check_budget(directory)
        self.assertEqual(checked['status'],'fail');self.assertIn('call marker requires reconciliation',checked['problems'][0])
        self.assertEqual(before,{str(p):(p.read_bytes(),p.stat().st_mtime_ns) for base in [directory,self.lane['output']] for p in Path(base).rglob('*') if p.is_file()})
        self.raw.write_text(json.dumps({'payloadSha256':'a'*64,'response':{'id':'synthetic-paid-return'}}))
        self.assertEqual(check.check_budget(directory)['status'],'pass')
