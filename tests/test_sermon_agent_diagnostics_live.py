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
        return self.fake.list_items(session, timeout_seconds=self.timeout)
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

    def test_opaque_wire_call_binds_actual_required_action_without_pending_items(self):
        bundle=diagnostic.build_context_bundle(self.manifest)
        # Real safe projection: length 55, bounded charset, opaque prefix,
        # required_action exists before a pending function_call item is listed.
        opaque='opaque_'+('a'*48)
        action=dict(type='function_call',turn_id='turn_offline',call_id=opaque,
            name=diagnostic.READ_TOOLS[0],arguments={'snapshotId':bundle['snapshotId']})
        self.transport=WireReplay([frame(actions=[action]),frame(status='completed')],[final_item(self.report)])
        result=self.run_diagnostic()
        self.assertEqual(result['status'],'completed');self.assertEqual(len(opaque),55)
        self.assertEqual(result['checkpoint']['toolResults'][0]['callId'],opaque)
        self.assertEqual(diagnostic._validate_checkpoint(result['checkpoint'],result['provenance']['payloadSha256'],
            bundle,diagnostic.DiagnosticLimits()),result['checkpoint'])
        saved=list((self.root/'required-action-bindings').glob('*.json'));self.assertEqual(len(saved),1)
        binding=json.loads(saved[0].read_text())
        self.assertEqual(binding['schemaVersion'],'sermon-live-diagnostic-required-action-binding-v2')
        self.assertEqual(binding['callId'],opaque)
        self.assertEqual(binding['actionSha256'],c.fingerprint(action))
        for method,key,sequence in [('retrieve_session','sessionResponseSha256','sessionTransportSequence'),
                                    ('list_turns','turnsResponseSha256','turnsTransportSequence')]:
            receipt=json.loads((self.root/'transport'/f"{binding[sequence]:04d}.returned.json").read_text())
            self.assertEqual(receipt['method'],method);self.assertEqual(receipt['responseSha256'],binding[key])
        self.assertEqual(self.transport.calls.count('list_items'),1) # final diagnosis only
        self.assertEqual(self.transport.calls.count('submit_tool_result'),1)
        self.assertEqual(self.transport.calls.count('create_session'),1);self.network.assert_not_called()

    def test_submission_requires_current_unique_required_action_and_unique_active_root(self):
        bundle=diagnostic.build_context_bundle(self.manifest)
        action=dict(type='function_call',turn_id='turn_offline',call_id='opaque_'+('b'*48),
            name=diagnostic.READ_TOOLS[0],arguments={'snapshotId':bundle['snapshotId']})
        base=self.root
        for case in ('missing_session','missing_turns','missing_actions','duplicate','call_id','turn','name',
                     'arguments','session','root','subagent','missing_subagent','duplicate_root',
                     'terminal_session','terminal_root','stale_poll','stale_deadline','unknown_action','output',
                     'snapshot_hash','receipt_hash'):
            with self.subTest(case=case):
                self.root=base/case;self.transport=WireReplay([frame(actions=[action])],[])
                client=live.LiveDiagnosticClient(self.root,self.authorization,fixture_transport=self.transport)
                limits=diagnostic.DiagnosticLimits();client.validate_scope(self.manifest,limits,'gpt-6-sol')
                client.create_session(diagnostic.build_session_payload(bundle),timeout_seconds=30)
                wire=self.transport.fake.frames[0]
                if case=='missing_actions':wire['session'].pop('required_actions')
                if case=='duplicate':wire['session']['required_actions'].append(dict(action))
                if case=='session':wire['session']['id']='sess_other'
                if case=='root':wire['turns'][0]['id']='turn_other'
                if case=='subagent':wire['turns'][0]['subagent_id']='other'
                if case=='missing_subagent':wire['turns'][0].pop('subagent_id')
                if case=='duplicate_root':wire['turns'].append(dict(wire['turns'][0]))
                if case=='terminal_session':wire['session']['status']='failed'
                if case=='terminal_root':wire['turns'][0]['status']='completed'
                if case=='unknown_action':wire['session']['required_actions'].append({**action,'call_id':'other','name':'publish'})
                if case!='missing_session':client.retrieve_session('sess_offline',timeout_seconds=30)
                if case!='missing_turns':client.list_turns('sess_offline',timeout_seconds=30)
                if case=='stale_poll':client.retrieve_session('sess_offline',timeout_seconds=30)
                if case=='stale_deadline':client.clock=lambda:json.loads((self.root/'observer.json').read_text())['deadlineAt']+1
                if case=='snapshot_hash':client._session_snapshot['value']['usage']={}
                if case=='receipt_hash':
                    path=self.root/'transport'/f"{client._turns_snapshot['transportSequence']:04d}.returned.json"
                    receipt=json.loads(path.read_text());receipt['responseSha256']='0'*64;path.write_text(json.dumps(receipt))
                submitted=dict(action)
                if case=='call_id':submitted['call_id']='other'
                if case=='turn':submitted['turn_id']='turn_other'
                if case=='name':submitted['name']=diagnostic.READ_TOOLS[1]
                if case=='arguments':submitted['arguments']={'snapshotId':'other'}
                output=diagnostic.read_diagnostic_tool(bundle,action['name'],action['arguments'])
                if case=='output':output={}
                with self.assertRaises(c.DiagnosticContractError):
                    client.submit_tool_result('sess_offline',submitted,output,timeout_seconds=30)
                self.assertNotIn('submit_tool_result',self.transport.calls)
                self.assertFalse((self.root/'required-action-bindings').exists())
        self.network.assert_not_called()

    def test_repeated_action_keeps_v1_history_and_append_only_v2_response_bindings(self):
        bundle=diagnostic.build_context_bundle(self.manifest)
        action=dict(type='function_call',turn_id='turn_offline',call_id='opaque_'+('c'*48),
            name=diagnostic.READ_TOOLS[0],arguments={'snapshotId':bundle['snapshotId']})
        old=self.root/'call-item-bindings/legacy.json';old.parent.mkdir(parents=True)
        old.write_text('{"schemaVersion":"sermon-live-diagnostic-call-item-binding-v1"}')
        original=old.read_bytes()
        self.transport=WireReplay([frame(actions=[action]),frame(actions=[action]),frame(status='completed')],[final_item(self.report)])
        self.assertEqual(self.run_diagnostic()['status'],'completed')
        self.assertEqual(self.transport.calls.count('submit_tool_result'),2)
        self.assertEqual(len(list((self.root/'required-action-bindings').glob('*.json'))),2)
        self.assertEqual(old.read_bytes(),original)

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
                self.assertFalse((self.root/'required-action-bindings').exists())

    def test_snapshot_is_detached_from_returned_data_mutation(self):
        bundle=diagnostic.build_context_bundle(self.manifest)
        action=dict(type='function_call',turn_id='turn_offline',call_id='opaque_'+('e'*48),
            name=diagnostic.READ_TOOLS[0],arguments={'snapshotId':bundle['snapshotId']})
        self.transport=WireReplay([frame(actions=[action])],[])
        client=live.LiveDiagnosticClient(self.root,self.authorization,fixture_transport=self.transport)
        client.validate_scope(self.manifest,diagnostic.DiagnosticLimits(),'gpt-6-sol')
        client.create_session(diagnostic.build_session_payload(bundle),timeout_seconds=30)
        session=client.retrieve_session('sess_offline',timeout_seconds=30)
        turns=client.list_turns('sess_offline',timeout_seconds=30)
        session['required_actions'][0]['call_id']='tampered';turns[0]['id']='turn_tampered'
        output=diagnostic.read_diagnostic_tool(bundle,action['name'],action['arguments'])
        client.submit_tool_result('sess_offline',action,output,timeout_seconds=30)
        self.assertEqual(self.transport.calls.count('submit_tool_result'),1)

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

    def test_poll16_authorization_preserves_default8_and_other_scope_bounds(self):
        self.assertEqual(diagnostic.DiagnosticLimits().max_steps, 8)
        for steps in (8, 16):
            with self.subTest(accepted_steps=steps):
                value=json.loads(json.dumps(self.authorization))
                value['limits']['max_steps']=steps
                self.assertEqual(live.validate_authorization(value),value)
        for key,value in (('max_steps',17),('max_tool_reads',17),('max_seconds',31),
                          ('maxTransportCalls',45),('reservationMicrousd',2_000_001),
                          ('maxSessions',2),('maxRootTurns',2)):
            with self.subTest(rejected_scope=key):
                authorization=json.loads(json.dumps(self.authorization))
                authorization['limits']['max_steps']=16
                target=authorization['limits'] if key in authorization['limits'] else authorization
                target[key]=value
                with self.assertRaises(c.DiagnosticContractError):
                    live.validate_authorization(authorization)
        self.assertFalse(self.transport.calls);self.network.assert_not_called()

    def test_late_action_at8_can_complete_on_poll9_with_explicit_poll16(self):
        bundle=diagnostic.build_context_bundle(self.manifest)
        action=dict(type='function_call',turn_id='turn_offline',call_id='opaque_late',
            name=diagnostic.READ_TOOLS[0],arguments={'snapshotId':bundle['snapshotId']})
        base=self.root
        for steps,reason,polls,calls,cancels in ((8,'diagnostic_step_limit',8,19,1),
                                                (16,'diagnosis_validated',9,21,0)):
            with self.subTest(max_steps=steps):
                self.root=base/str(steps);self.authorization['limits']['max_steps']=steps
                self.transport=WireReplay([frame() for _ in range(7)]+
                    [frame(actions=[action]),frame(status='completed')],[final_item(self.report)])
                result=self.run_diagnostic()
                self.assertEqual(result['reasonCode'],reason)
                self.assertEqual(result['checkpoint']['steps'],polls)
                self.assertEqual(self.transport.calls.count('retrieve_session'),polls)
                self.assertEqual(len(list((self.root/'transport').glob('*.intent.json'))),calls)
                self.assertEqual(self.transport.calls.count('submit_tool_result'),1)
                self.assertEqual(self.transport.calls.count('create_session'),1)
                self.assertEqual(self.transport.calls.count('cancel'),cancels)
                self.assertEqual(len(list((self.root/'required-action-bindings').glob('*.json'))),1)
                self.assertEqual(result['provenance']['reservationMicrousd'],2_000_000)
                self.assertFalse(result['provenance']['reservationRefunded'])
                self.assertFalse(result['provenance']['executionAuthorized'])
                self.assertIsNone(result['provenance']['actualModel'])
        self.network.assert_not_called()

    def test_poll16_stops_without_actions_and_transport_limit_still_precedes_steps(self):
        bundle=diagnostic.build_context_bundle(self.manifest)
        action=dict(type='function_call',turn_id='turn_offline',call_id='opaque_repeated',
            name=diagnostic.READ_TOOLS[0],arguments={'snapshotId':bundle['snapshotId']})
        self.authorization['limits']['max_steps']=16;base=self.root
        for name,actions,reason,steps,calls,submits in (
                ('no_actions',[],'diagnostic_step_limit',16,34,0),
                ('transport_cap',[action],'transport_call_limit',14,42,13)):
            with self.subTest(case=name):
                self.root=base/name;self.transport=WireReplay([frame(actions=actions)],[])
                result=self.run_diagnostic()
                self.assertEqual(result['reasonCode'],reason)
                self.assertEqual(result['checkpoint']['steps'],steps)
                self.assertEqual(len(list((self.root/'transport').glob('*.intent.json'))),calls)
                self.assertLessEqual(calls,self.authorization['maxTransportCalls'])
                self.assertEqual(self.transport.calls.count('submit_tool_result'),submits)
                self.assertEqual(self.transport.calls.count('cancel'),1)
                self.assertEqual(self.transport.calls.count('create_session'),1)
                self.assertFalse(result['provenance']['reservationRefunded'])
                self.assertFalse(result['provenance']['executionAuthorized'])
                again=self.run_diagnostic()
                self.assertEqual(again['status'],'blocked')
                self.assertEqual(len(self.transport.calls),calls)
        self.network.assert_not_called()

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

    def extended_authorization(self):
        return {**self.authorization,'schemaVersion':live.EXTENDED_SCHEMA,
            'limits':asdict(diagnostic.DiagnosticLimits(max_steps=60,max_seconds=120)),
            'maxTransportCalls':132}

    def test_extended_authorization_requires_v2_keeps_v1_and_default_scope(self):
        self.assertEqual(diagnostic.DiagnosticLimits().max_steps,8)
        self.assertEqual(diagnostic.DiagnosticLimits().max_seconds,30)
        extended=self.extended_authorization()
        self.assertEqual(live.validate_authorization(extended),extended)
        for name,value in (('max_steps',61),('max_seconds',121),('max_tool_reads',17),
                           ('maxTransportCalls',133),('maxSessions',2),('maxRootTurns',2),
                           ('reservationMicrousd',2_000_001)):
            with self.subTest(bound=name):
                auth=json.loads(json.dumps(extended))
                target=auth['limits'] if name in auth['limits'] else auth
                target[name]=value
                with self.assertRaises(c.DiagnosticContractError):live.validate_authorization(auth)
        for name,value in (('max_steps',60),('max_seconds',120),('maxTransportCalls',132)):
            with self.subTest(old_schema_bound=name):
                auth=json.loads(json.dumps(self.authorization))
                target=auth['limits'] if name in auth['limits'] else auth
                target[name]=value
                with self.assertRaises(c.DiagnosticContractError):live.validate_authorization(auth)
        self.network.assert_not_called()

    def test_extended_observer_deadline_keeps_single_io30_cleanup5(self):
        self.authorization=self.extended_authorization()
        client=live.LiveDiagnosticClient(self.root,self.authorization,fixture_transport=self.transport,clock=lambda:1000)
        limits=diagnostic.DiagnosticLimits(**self.authorization['limits'])
        client.validate_scope(self.manifest,limits,'gpt-6-sol')
        payload=diagnostic.build_session_payload(diagnostic.build_context_bundle(self.manifest),limits)
        client.create_session(payload,timeout_seconds=120)
        self.assertEqual(self.transport.timeout,30)
        self.assertEqual(json.loads((self.root/'observer.json').read_text())['deadlineAt'],1120)
        client.retrieve_session('sess_offline',timeout_seconds=120)
        self.assertEqual(self.transport.timeout,30)
        client.cancel_once('sess_offline')
        self.assertEqual(self.transport.timeout,5)
        self.assertEqual(self.transport.calls.count('create_session'),1)
        self.assertEqual(self.transport.calls.count('cancel'),1)
        self.network.assert_not_called()

    def test_extended_observer_bounded_no_action_and_transport_exhaustion(self):
        self.authorization=self.extended_authorization();base=self.root
        bundle=diagnostic.build_context_bundle(self.manifest)
        action=dict(type='function_call',turn_id='turn_offline',call_id='opaque_extended',
            name=diagnostic.READ_TOOLS[0],arguments={'snapshotId':bundle['snapshotId']})
        for name,actions,reason,steps,calls,submits in (
                ('no_actions',[],'diagnostic_step_limit',60,122,0),
                ('transport_cap',[action],'transport_call_limit',43,130,42)):
            with self.subTest(case=name):
                self.root=base/name;self.transport=WireReplay([frame(actions=actions)],[])
                result=self.run_diagnostic()
                self.assertEqual(result['reasonCode'],reason)
                self.assertEqual(result['checkpoint']['steps'],steps)
                self.assertEqual(len(self.transport.calls),calls)
                self.assertLessEqual(calls,132)
                self.assertEqual(self.transport.calls.count('submit_tool_result'),submits)
                self.assertEqual(self.transport.calls.count('create_session'),1)
                self.assertEqual(self.transport.calls.count('cancel'),1)
                self.assertEqual(result['provenance']['reservationMicrousd'],2_000_000)
                self.assertFalse(result['provenance']['reservationRefunded'])
                self.assertFalse(result['provenance']['executionAuthorized'])
                self.assertIsNone(result['provenance']['actualModel'])
                self.assertEqual(self.run_diagnostic()['status'],'blocked')
                self.assertEqual(len(self.transport.calls),calls)
        self.network.assert_not_called()

    def test_exhausted_live_checkpoint_read_does_not_poll_submit_cancel_or_recreate(self):
        self.authorization=self.extended_authorization()
        result=self.run_diagnostic();before=list(self.transport.calls)
        checkpoint=result['checkpoint'];checkpoint['elapsedSeconds']=120.17549
        result=self.run_diagnostic(checkpoint=checkpoint)
        self.assertEqual(result['reasonCode'],'diagnostic_deadline_exceeded')
        self.assertGreaterEqual(result['checkpoint']['elapsedSeconds'],120.17549)
        self.assertEqual(result['provenance']['cancellation']['status'],
            'not_attempted_exhausted_checkpoint_requires_reconciliation')
        self.assertEqual(self.transport.calls,before)
        self.assertFalse((self.root/'cancel-intent.json').exists())
        self.network.assert_not_called()

    def test_extended_late_action_after_original_transport_bound_completes(self):
        self.authorization=self.extended_authorization()
        bundle=diagnostic.build_context_bundle(self.manifest)
        action=dict(type='function_call',turn_id='turn_offline',call_id='opaque_poll20',
            name=diagnostic.READ_TOOLS[0],arguments={'snapshotId':bundle['snapshotId']})
        self.transport=WireReplay([frame() for _ in range(19)]+
            [frame(actions=[action]),frame(status='completed')],[final_item(self.report)])
        result=self.run_diagnostic()
        self.assertEqual(result['status'],'completed')
        self.assertEqual(result['checkpoint']['steps'],21)
        self.assertEqual(len(self.transport.calls),45)
        self.assertEqual(self.transport.calls.count('submit_tool_result'),1)
        self.assertEqual(self.transport.calls.count('create_session'),1)
        self.assertEqual(self.transport.calls.count('cancel'),0)
        self.network.assert_not_called()
