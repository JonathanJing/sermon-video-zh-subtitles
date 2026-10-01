"""Live wire protocol through fake transport; never credentials or network."""
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import sermon_agent_diagnostics as diagnostic
from scripts import sermon_agent_diagnostics_contracts as c
from scripts import sermon_agent_diagnostics_live as live
from tests.test_sermon_agent_diagnostics import fixture, frame, final_item


class WireReplay:
    def __init__(self, frames, items):
        self.fake = diagnostic.OfflineReplayClient(frames, items)
        self.calls = []; self.timeout = None; self.fail_create = False; self.fail_submit = False

    def set_deadline(self, deadline): self.deadline = deadline
    def create_session(self, payload):
        self.calls.append('create_session')
        if self.fail_create: raise OSError('private credential/body must not escape')
        return self.fake.create_session(payload, timeout_seconds=self.timeout)
    def retrieve_session(self, session):
        self.calls.append('retrieve_session')
        return self.fake.retrieve_session(session, timeout_seconds=self.timeout)
    def list_turns(self, session):
        self.calls.append('list_turns')
        return self.fake.list_turns(session, timeout_seconds=self.timeout)
    def list_items(self, session):
        self.calls.append('list_items')
        items=self.fake.list_items(session, timeout_seconds=self.timeout)
        # Replay the actual required function_call item alongside any messages.
        actions=self.fake.frames[self.fake.index]['session'].get('required_actions',[]) if self.fake.index>=0 else []
        return items+[{'id':action['call_id'],**action,'status':'in_progress'} for action in actions]
    def submit_tool_result(self, session, action, output):
        self.calls.append('submit_tool_result')
        if self.fail_submit: raise OSError('private')
        return self.fake.submit_tool_result(session, action, output, timeout_seconds=self.timeout)
    def cancel(self, session):
        self.calls.append('cancel')
        return {}


class LiveDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'observer'
        self.manifest = fixture('manifest.json')
        self.report = fixture('diagnosis.json')
        self.authorization = dict(schemaVersion=live.SCHEMA, approvalSha256='a'*64,
            manifestSha256=c.fingerprint(self.manifest), model='gpt-6-sol',
            limits=asdict(diagnostic.DiagnosticLimits()), reservationMicrousd=2_000_000,
            maxSessions=1, maxRootTurns=1, maxTransportCalls=44,
            budgetEnforcement='observer_stop_not_server_enforced', evidenceMode='synthetic')
        self.transport = WireReplay([frame(status='completed')], [final_item(self.report)])
        self.network = self.enterContext(patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('network forbidden')))

    def run_diagnostic(self, **kwargs):
        return live.run_live_diagnostic(self.manifest, root=self.root, authorization=self.authorization,
            current_identity=kwargs.pop('current_identity', self.manifest['identity']),
            fixture_transport=self.transport, **kwargs)

    def test_one_root_turn_metadata_only_checkpoint_before_creation_and_no_refund(self):
        original = self.transport.create_session
        def create(payload):
            states = [json.loads(path.read_text()) for path in (self.root/'checkpoints').glob('*.json')]
            self.assertTrue(any(state['creationAttempted'] and state['sessionId'] is None for state in states))
            return original(payload)
        self.transport.create_session = create
        result = self.run_diagnostic()
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['provenance']['transportMode'], 'synthetic_live_protocol')
        self.assertEqual(result['provenance']['costStatus'], 'unknown')
        self.assertFalse(result['provenance']['reservationRefunded'])
        payload = self.transport.fake.created_payloads[0]
        self.assertEqual(payload['agent']['reasoning'], {'effort':'medium'})
        self.assertEqual(payload['agent']['tools'], diagnostic.diagnostic_tools())
        self.assertEqual(payload['environment'], {'type':'none'})
        self.assertEqual(self.transport.calls.count('create_session'), 1)
        with self.assertRaises(c.DiagnosticContractError):
            live.LiveDiagnosticClient(self.root,self.authorization,fixture_transport=self.transport).create_session(payload,timeout_seconds=30)
        self.assertEqual(self.transport.calls.count('create_session'), 1); self.network.assert_not_called()

    def test_unknown_creation_is_durable_and_never_recreated(self):
        self.transport.fail_create = True
        first = self.run_diagnostic()
        self.assertEqual(first['status'], 'outcome_unknown')
        self.assertIsNone(first['checkpoint']['sessionId'])
        self.assertTrue((self.root/'session-create-intent.json').exists())
        again = self.run_diagnostic()
        self.assertEqual(again['status'], 'blocked')
        self.assertEqual(self.transport.calls, ['create_session'])
        for path in self.root.rglob('*.json'):
            self.assertNotIn('private credential', path.read_text())

    def test_pure_tool_result_saved_before_submission_unknown_cancel_not_terminal(self):
        bundle = diagnostic.build_context_bundle(self.manifest)
        action = dict(type='function_call',turn_id='turn_offline',call_id='call_read',
            name=diagnostic.READ_TOOLS[1],arguments=dict(snapshotId=bundle['snapshotId'],evidenceId=bundle['manifest']['events'][0]['evidenceId']))
        self.transport = WireReplay([frame(actions=[action])], [])
        self.transport.fail_submit = True
        result = self.run_diagnostic()
        self.assertEqual(result['status'], 'outcome_unknown')
        saved = [json.loads(path.read_text()) for path in (self.root/'checkpoints').glob('*.json')]
        self.assertTrue(any(state['toolResults'] for state in saved))
        self.assertEqual(result['provenance']['cancellation']['status'], 'acknowledged_terminal_not_confirmed')
        self.assertEqual(self.transport.calls.count('cancel'), 1)

    def test_opaque_wire_call_identifier_binds_actual_item_and_survives_checkpoint(self):
        bundle=diagnostic.build_context_bundle(self.manifest)
        # Real safe projection: length 55, bounded charset, item.id == call_id,
        # no guaranteed call_ prefix. This is synthetic and contains no real ID.
        opaque='opaque_'+('a'*48)
        action=dict(type='function_call',turn_id='turn_offline',call_id=opaque,
            name=diagnostic.READ_TOOLS[0],arguments={'snapshotId':bundle['snapshotId']})
        self.transport=WireReplay([frame(actions=[action]),frame(status='completed')],[final_item(self.report)])
        result=self.run_diagnostic()
        self.assertEqual(result['status'],'completed');self.assertEqual(len(opaque),55)
        self.assertEqual(result['checkpoint']['toolResults'][0]['callId'],opaque)
        self.assertEqual(diagnostic._validate_checkpoint(result['checkpoint'],result['provenance']['payloadSha256'],
            bundle,diagnostic.DiagnosticLimits()),result['checkpoint'])
        saved=list((self.root/'call-item-bindings').glob('*.json'));self.assertEqual(len(saved),1)
        binding=json.loads(saved[0].read_text())
        self.assertEqual(binding['callId'],opaque);self.assertEqual(binding['itemId'],opaque)
        self.assertEqual(binding['actionSha256'],c.fingerprint(action))
        self.assertEqual(self.transport.calls.count('submit_tool_result'),1)
        self.assertEqual(self.transport.calls.count('create_session'),1);self.network.assert_not_called()

    def test_opaque_call_requires_unique_actual_item_with_same_turn_name_arguments(self):
        bundle=diagnostic.build_context_bundle(self.manifest)
        action=dict(type='function_call',turn_id='turn_offline',call_id='opaque_'+('b'*48),
            name=diagnostic.READ_TOOLS[0],arguments={'snapshotId':bundle['snapshotId']})
        base=self.root
        for case in ('missing','duplicate','call_id','turn','name','arguments','session','item_id'):
            with self.subTest(case=case):
                self.root=base/case;self.transport=WireReplay([frame(actions=[action])],[])
                original=self.transport.list_items
                def items(session,case=case,original=original):
                    value=original(session)
                    if case=='missing':return []
                    if case=='duplicate':return value+value
                    field={'call_id':'call_id','turn':'turn_id','name':'name','arguments':'arguments',
                           'session':'session_id','item_id':'id'}[case]
                    value[0][field]={'snapshotId':'other'} if case=='arguments' else '../invalid' if case=='item_id' else 'other'
                    return value
                self.transport.list_items=items
                result=self.run_diagnostic()
                self.assertEqual(result['status'],'blocked')
                self.assertNotIn('submit_tool_result',self.transport.calls)
                self.assertFalse((self.root/'call-item-bindings').exists())
        self.network.assert_not_called()

    def test_item_arguments_json_representation_is_strict_and_semantically_bound(self):
        bundle=diagnostic.build_context_bundle(self.manifest)
        action=dict(type='function_call',turn_id='turn_offline',call_id='opaque_'+('c'*48),
            name=diagnostic.READ_TOOLS[0],arguments={'snapshotId':bundle['snapshotId']})
        self.transport=WireReplay([frame(actions=[action]),frame(status='completed')],[final_item(self.report)])
        original=self.transport.list_items
        def items(session):
            rows=original(session)
            for row in rows:
                if row.get('type')=='function_call':row['arguments']=json.dumps(row['arguments'])
            return rows
        self.transport.list_items=items
        self.assertEqual(self.run_diagnostic()['status'],'completed')
        self.assertEqual(self.transport.calls.count('submit_tool_result'),1)

    def test_opaque_call_identifier_keeps_original_charset_and_length_bounds(self):
        bundle=diagnostic.build_context_bundle(self.manifest);base=self.root
        for index,invalid in enumerate(('opaque_'+('d'*74),'../opaque','opaque:bad','opaque bad','',None,{})):
            with self.subTest(invalid=invalid):
                self.root=base/str(index)
                action=dict(type='function_call',turn_id='turn_offline',call_id=invalid,
                    name=diagnostic.READ_TOOLS[0],arguments={'snapshotId':bundle['snapshotId']})
                self.transport=WireReplay([frame(actions=[action])],[])
                result=self.run_diagnostic()
                self.assertEqual(result['reasonCode'],'invalid_remote_identifier')
                self.assertNotIn('submit_tool_result',self.transport.calls)
                self.assertFalse((self.root/'call-item-bindings').exists())

    def test_duplicate_json_keys_in_item_arguments_do_not_reach_submission(self):
        bundle=diagnostic.build_context_bundle(self.manifest)
        action=dict(type='function_call',turn_id='turn_offline',call_id='opaque_'+('e'*48),
            name=diagnostic.READ_TOOLS[0],arguments={'snapshotId':bundle['snapshotId']})
        self.transport=WireReplay([frame(actions=[action])],[]);original=self.transport.list_items
        def items(session):
            rows=original(session)
            rows[0]['arguments']='{"snapshotId":"one","snapshotId":"two"}'
            return rows
        self.transport.list_items=items
        self.assertEqual(self.run_diagnostic()['status'],'blocked')
        self.assertNotIn('submit_tool_result',self.transport.calls)

    def test_stale_or_unapproved_scope_cannot_dispatch(self):
        changed = {**self.manifest['identity'], 'stateRevision':99}
        with self.assertRaisesRegex(ValueError,'stale_diagnostic'):
            self.run_diagnostic(current_identity=changed)
        self.assertFalse(self.root.exists()); self.assertFalse(self.transport.calls)
        self.authorization['manifestSha256'] = '0'*64
        with self.assertRaisesRegex(ValueError,'scope_changed'): self.run_diagnostic()
        self.assertFalse(self.transport.calls)

    def test_current_identity_rechecked_after_result_and_tools_cannot_publish(self):
        values = iter([self.manifest['identity'], {**self.manifest['identity'], 'stateRevision':99}])
        with self.assertRaisesRegex(ValueError,'stale_diagnostic'):
            self.run_diagnostic(current_identity=lambda: next(values))
        self.assertFalse((self.root/'results').exists())
        self.assertNotIn('submit_tool_result',self.transport.calls)

    def test_wrong_live_fixture_mode_or_budget_authority_rejected(self):
        self.authorization['evidenceMode']='current_execution'
        with self.assertRaises(ValueError): self.run_diagnostic()
        self.authorization['budgetEnforcement']='server_hard_cap'
        with self.assertRaises(ValueError): self.run_diagnostic()
        self.assertFalse(self.transport.calls)

    def test_observed_cost_threshold_stops_and_missing_usage_is_not_zero(self):
        self.assertEqual(live.observed_cost('gpt-6-sol', None)['costStatus'], 'unknown')
        self.assertIsNone(live.observed_cost('gpt-6-sol', {'input_tokens':1})['estimatedMicrousd'])
        original = self.transport.list_turns
        def turns(session):
            rows = original(session)
            for row in rows:
                row.update(model='gpt-6-sol', usage={'input_tokens':1_000_000,'output_tokens':1})
            return rows
        self.transport.list_turns = turns
        result = self.run_diagnostic()
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['reasonCode'], 'diagnostic_cost_observation_threshold')
        self.assertEqual(result['provenance']['budgetEnforcement'], 'observer_stop_not_server_enforced')
        self.assertEqual(self.transport.calls.count('cancel'),1)
        again = self.run_diagnostic()
        self.assertEqual(again['status'],'blocked')
        self.assertEqual(self.transport.calls.count('create_session'),1)

    def test_cancel_unknown_has_durable_intent_and_no_retry(self):
        self.transport = WireReplay([frame(actions=[])], [])
        self.authorization['limits']['max_steps'] = 1
        def cancel(session):
            self.transport.calls.append('cancel')
            raise TimeoutError('private provider cancellation details')
        self.transport.cancel = cancel
        result = self.run_diagnostic()
        self.assertEqual(result['provenance']['cancellation']['status'],'outcome_unknown')
        self.assertTrue((self.root/'cancel-intent.json').exists())
        again = self.run_diagnostic()
        self.assertEqual(again['status'],'blocked')
        self.assertEqual(self.transport.calls.count('cancel'),1)
        self.assertEqual(self.transport.calls.count('create_session'),1)
        for path in self.root.rglob('*.json'):
            self.assertNotIn('private provider', path.read_text())
