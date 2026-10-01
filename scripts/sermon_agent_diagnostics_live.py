"""Explicit single-session diagnostic observer, isolated from business authority.

The monetary reservation is an observation/stop threshold, NOT a server-enforced
spend ceiling. Hosted turns can make multiple model calls and keep running after
the observer disconnects. Missing usage/cancellation stays unknown. No additional
session, user turn, tool, business write, retry or budget refund is permitted.
"""
from dataclasses import asdict
from contextlib import ExitStack
import json
from pathlib import Path
import time

from scripts import sermon_agent_diagnostics as diagnostic
from scripts import sermon_agent_diagnostics_contracts as c
from scripts import sermon_agents_api as api
from scripts import sermon_accounting as accounting
from scripts import sermon_provider_limits as pricing
from scripts import sermon_log_profile as profile
from scripts import sermon_strict_layer2 as immutable
from scripts import sermon_workflow_jobs as jobs
from scripts.sermon_release_workflow import _safe_path

SCHEMA = 'sermon-live-diagnostic-authorization-v1'


def observed_cost(model, usage):
    """Planning observation only; hosted usage is best effort, never invoice."""
    evidence = {'costStatus': 'unknown', 'estimatedMicrousd': None, 'invoiceVerified': False,
                'priceAssumptionVersion': pricing.PRICE_ASSUMPTION_VERSION,
                'priceBasis': 'default_tier_frozen_worst_case_assumption',
                'usageAggregation': 'root_turn_only_do_not_sum_session'}
    if model not in pricing.SUPPORTED_MODELS or type(usage) is not dict:
        return evidence
    counts = [usage.get(k) for k in ('input_tokens', 'output_tokens')]
    if any(type(n) is not int or not 0 <= n <= 10**12 for n in counts):
        return evidence
    return {**evidence, 'costStatus': 'observed_assumption_estimate',
            'estimatedMicrousd': pricing._cost(model, *counts)}


def validate_authorization(value):
    keys = {'schemaVersion', 'approvalSha256', 'manifestSha256', 'model', 'limits',
            'reservationMicrousd', 'maxSessions', 'maxRootTurns', 'maxTransportCalls',
            'budgetEnforcement', 'evidenceMode'}
    c.require(type(value) is dict and set(value) == keys and value['schemaVersion'] == SCHEMA,
              'invalid_live_diagnostic_authorization')
    for key in ('approvalSha256', 'manifestSha256'):
        c.require(type(value[key]) is str and len(value[key]) == 64 and
                  all(ch in '0123456789abcdef' for ch in value[key]), 'invalid_live_diagnostic_authorization')
    c.require(value['model'] == 'gpt-6-sol' and type(value['maxSessions']) is int and value['maxSessions'] == 1
              and type(value['maxRootTurns']) is int and value['maxRootTurns'] == 1
              and type(value['reservationMicrousd']) is int and 0 < value['reservationMicrousd'] <= 2_000_000
              and type(value['maxTransportCalls']) is int and 4 <= value['maxTransportCalls'] <= 44
              and value['budgetEnforcement'] == 'observer_stop_not_server_enforced'
              and value['evidenceMode'] in ('synthetic', 'current_execution'), 'invalid_live_diagnostic_authorization')
    c.require(type(value['limits']) is dict and set(value['limits']) == set(asdict(diagnostic.DiagnosticLimits())),
              'invalid_live_diagnostic_authorization')
    limits = diagnostic.DiagnosticLimits(**value['limits']); limits.validate()
    c.require(limits.max_steps <= 16 and limits.max_tool_reads <= 16 and limits.max_seconds <= 30,
              'invalid_live_diagnostic_authorization')
    return json.loads(c.bounded_json(value))


class LiveDiagnosticClient:
    offline = False

    def __init__(self, root, authorization, *, key=None, fixture_transport=None, clock=time.time):
        self.authorization = validate_authorization(authorization)
        self.root = _safe_path(Path(root), recursive=True)
        c.require(self.root.is_absolute(), 'live_diagnostic_absolute_directory_required')
        c.require((fixture_transport is None and type(key) is str and bool(key) and
                   self.authorization['evidenceMode'] == 'current_execution') or
                  (fixture_transport is not None and key is None and self.authorization['evidenceMode'] == 'synthetic'),
                  'live_diagnostic_transport_mode_changed')
        self.synthetic_fixture = fixture_transport is not None
        self.clock = clock
        self.client = fixture_transport if self.synthetic_fixture else api.AgentsAPIClient(
            api_key=key, timeout=30, max_response_bytes=self.authorization['limits']['max_transport_bytes'], max_pages=4)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        immutable.save_once(self.root / 'authorization.json', self.authorization)
        self.created_session = None
        self.poll_at = 0
        self._poll_sequence = 0
        self._session_snapshot = None
        self._turns_snapshot = None

    def validate_scope(self, manifest, limits, model):
        c.validate_manifest(manifest)
        c.require(c.fingerprint(manifest) == self.authorization['manifestSha256'] and
                  asdict(limits) == self.authorization['limits'] and model == self.authorization['model'],
                  'live_diagnostic_scope_changed')
        self._bundle = diagnostic.build_context_bundle(manifest)
        self._limits = limits
        self.payload_sha256 = c.fingerprint(diagnostic.build_session_payload(self._bundle, limits, model))

    def save_checkpoint(self, state):
        # Hash-named append-only checkpoints retain create/submission intent even
        # if the process exits before its result is returned to the caller.
        raw = c.bounded_json(state, 256 * 1024)
        immutable.save_once(self.root / 'checkpoints' / (c.fingerprint(state) + '.json'), state)
        jobs._sync_directory_ancestry(self.root / 'checkpoints')
        return raw

    def _invoke(self, method, args, timeout_seconds, *, cleanup=False):
        c.require(type(timeout_seconds) in (float, int) and 0 < timeout_seconds <= 30,
                  'diagnostic_deadline_exceeded')
        bound = self.root / 'observer.json'
        if bound.exists():
            observer = json.loads(bound.read_text())
        else:
            observer = {'schemaVersion': 'sermon-live-diagnostic-observer-v1',
                        'authorizationSha256': c.fingerprint(self.authorization),
                        'deadlineAt': self.clock() + self.authorization['limits']['max_seconds']}
            immutable.save_once(bound, observer)
        c.require(observer['authorizationSha256'] == c.fingerprint(self.authorization), 'live_diagnostic_scope_changed')
        remaining = timeout_seconds if cleanup else min(timeout_seconds, observer['deadlineAt'] - self.clock())
        c.require(remaining > 0, 'diagnostic_deadline_exceeded')
        intents = list((self.root / 'transport').glob('*.intent.json'))
        c.require(len(intents) < self.authorization['maxTransportCalls'] - (0 if cleanup else 3),
                  'transport_call_limit')
        sequence = len(intents) + 1
        intent = {'schemaVersion': 'sermon-live-diagnostic-call-v1', 'sequence': sequence,
                  'method': method, 'inputSha256': c.fingerprint(list(args)), 'outcome': 'unknown',
                  'authorizationSha256': c.fingerprint(self.authorization)}
        path = self.root / 'transport' / f'{sequence:04d}'
        immutable.save_once(path.with_suffix('.intent.json'), intent)
        jobs._sync_directory_ancestry(path.parent)
        self.client.timeout = remaining
        if hasattr(self.client, 'set_deadline'):
            self.client.set_deadline(self.clock() + remaining)
        try:
            value = getattr(self.client, method)(*args)
            c.bounded_json(value, self.authorization['limits']['max_transport_bytes'])
        except Exception:
            # No provider/error body is persisted. Intent remains unresolved.
            raise c.DiagnosticContractError('transport_outcome_unknown') from None
        immutable.save_once(path.with_suffix('.returned.json'), {**intent, 'outcome': 'returned',
            'responseSha256': c.fingerprint(value)})
        jobs._sync_directory_ancestry(path.parent)
        self._last_transport = {'method':method,'sequence':sequence,'responseSha256':c.fingerprint(value)}
        return value

    def create_session(self, payload, *, timeout_seconds):
        c.require(not (self.root / 'session-create-intent.json').exists(), 'creation_outcome_requires_reconciliation')
        c.require(c.fingerprint(payload) == getattr(self, 'payload_sha256', None), 'live_diagnostic_scope_changed')
        c.require(payload['agent']['model'] == self.authorization['model'] and
                  payload['agent']['reasoning'] == {'effort': 'medium'} and
                  payload['agent']['multi_agent'] == {'enabled': False} and
                  payload['environment'] == {'type': 'none'} and
                  payload['agent']['tools'] == diagnostic.diagnostic_tools(), 'live_diagnostic_scope_changed')
        intent = {'schemaVersion': 'sermon-live-diagnostic-session-intent-v1',
                  'payloadSha256': c.fingerprint(payload), 'authorizationSha256': c.fingerprint(self.authorization),
                  'reservationMicrousd': self.authorization['reservationMicrousd'],
                  'budgetEnforcement': self.authorization['budgetEnforcement'], 'sessionCount': 1, 'rootTurnCount': 1}
        immutable.save_once(self.root / 'session-create-intent.json', intent)
        jobs._sync_directory_ancestry(self.root)
        value = self._invoke('create_session', (payload,), timeout_seconds)
        self.created_session = diagnostic._remote_identifier(value.get('id'), 'sess_')
        immutable.save_once(self.root / 'session-created.json', {'sessionId': self.created_session,
            'payloadSha256': intent['payloadSha256']})
        return value

    def retrieve_session(self, session_id, *, timeout_seconds):
        self._session_scope(session_id)
        # A fresh poll invalidates the previous pair even if its GET fails.
        self._poll_sequence += 1
        self._session_snapshot = None
        self._turns_snapshot = None
        if not self.synthetic_fixture and self.clock() < self.poll_at:
            delay = min(self.poll_at - self.clock(), timeout_seconds)
            time.sleep(delay)
            timeout_seconds -= delay
        self.poll_at = self.clock() + 2
        value = self._invoke('retrieve_session', (session_id,), timeout_seconds)
        self._session_snapshot = self._snapshot(value, session_id)
        return value

    def _snapshot(self, value, session_id):
        return {'value':c.decode_json(c.bounded_json(value,self.authorization['limits']['max_transport_bytes'])),
                'sessionId':session_id,'pollSequence':self._poll_sequence,
                'transportSequence':self._last_transport['sequence'],
                'responseSha256':self._last_transport['responseSha256'],'observedAt':self.clock()}

    def _session_scope(self, session_id):
        saved = json.loads((self.root / 'session-created.json').read_text())
        c.require(session_id == saved['sessionId'], 'session_identity_mismatch')

    def list_turns(self, session_id, *, timeout_seconds):
        self._session_scope(session_id)
        self._turns_snapshot = None
        rows = self._invoke('list_turns', (session_id,), timeout_seconds)
        for row in rows if type(rows) is list else []:
            if type(row) is dict and row.get('subagent_id') is None and type(row.get('usage')) is dict:
                amount = observed_cost(row.get('model'), row['usage'])['estimatedMicrousd']
                if amount is not None and amount >= self.authorization['reservationMicrousd']:
                    raise c.DiagnosticContractError('diagnostic_cost_observation_threshold')
        self._turns_snapshot = self._snapshot(rows, session_id)
        return rows

    def list_items(self, session_id, *, timeout_seconds):
        self._session_scope(session_id)
        return self._invoke('list_items', (session_id,), timeout_seconds)

    def submit_tool_result(self, session_id, action, output, *, timeout_seconds):
        self._session_scope(session_id)
        # Pending function calls need not yet appear in list_items. The actual
        # current required_actions and same-poll unique root turn are the wire
        # authority, retained separately from old call-item-binding-v1 evidence.
        c.require(type(action) is dict and set(action) == {'type','turn_id','call_id','name','arguments'}
                  and action['type'] == 'function_call', 'unsupported_required_action')
        call_id = diagnostic._identifier(action['call_id'])
        turn_id = diagnostic._remote_identifier(action['turn_id'], 'turn_')
        c.require(action['name'] in diagnostic.READ_TOOLS and type(action['arguments']) is dict,
                  'unsupported_required_action')
        session_snapshot,turns_snapshot = self._session_snapshot,self._turns_snapshot
        c.require(session_snapshot is not None and turns_snapshot is not None,'diagnostic_action_snapshot_missing')
        observer = c.decode_json((self.root/'observer.json').read_bytes())
        c.require(type(observer) is dict and set(observer)=={'schemaVersion','authorizationSha256','deadlineAt'} and
                  observer['schemaVersion']=='sermon-live-diagnostic-observer-v1' and
                  observer['authorizationSha256']==c.fingerprint(self.authorization) and
                  type(observer['deadlineAt']) in (int,float) and 0<observer['deadlineAt']<float('inf'),
                  'live_diagnostic_scope_changed')
        current = self.clock()
        c.require(session_snapshot['sessionId']==turns_snapshot['sessionId']==session_id and
                  session_snapshot['pollSequence']==turns_snapshot['pollSequence']==self._poll_sequence and
                  session_snapshot['transportSequence'] < turns_snapshot['transportSequence'] and
                  session_snapshot['observedAt'] <= turns_snapshot['observedAt'] <= current < observer['deadlineAt'],
                  'diagnostic_action_snapshot_stale')
        session,rows=session_snapshot['value'],turns_snapshot['value']
        c.require(c.fingerprint(session)==session_snapshot['responseSha256'] and
                  c.fingerprint(rows)==turns_snapshot['responseSha256'],'diagnostic_action_snapshot_changed')
        for snapshot,method in ((session_snapshot,'retrieve_session'),(turns_snapshot,'list_turns')):
            receipt=c.decode_json((self.root/'transport'/f"{snapshot['transportSequence']:04d}.returned.json").read_bytes())
            c.require(type(receipt) is dict and set(receipt)=={'schemaVersion','sequence','method','inputSha256',
                      'outcome','authorizationSha256','responseSha256'} and
                      receipt['schemaVersion']=='sermon-live-diagnostic-call-v1' and receipt['method']==method and
                      receipt['sequence']==snapshot['transportSequence'] and receipt['outcome']=='returned' and
                      receipt['authorizationSha256']==c.fingerprint(self.authorization) and
                      receipt['inputSha256']==c.fingerprint([session_id]) and
                      receipt['responseSha256']==snapshot['responseSha256'],'diagnostic_action_snapshot_changed')
        c.require(type(session) is dict and session.get('id')==session_id and
                  type(session.get('status')) is str and
                  session.get('status') in diagnostic.SESSION_STATUSES-{'failed'},'session_identity_mismatch')
        c.require(type(rows) is list and len(rows)==1 and type(rows[0]) is dict and
                  'subagent_id' in rows[0] and rows[0]['subagent_id'] is None,'diagnostic_action_root_mismatch')
        root=rows[0]
        c.require(diagnostic._remote_identifier(root.get('id'),'turn_')==turn_id and
                  root.get('session_id',session_id)==session_id and
                  type(root.get('status')) is str and
                  root.get('status') in diagnostic.TURN_STATUSES-{'completed','failed','cancelled'},
                  'diagnostic_action_root_mismatch')
        actions=session.get('required_actions')
        c.require(type(actions) is list and len(actions)<=self._limits.max_tool_reads,'invalid_required_actions')
        seen=set();matches=[]
        for pending in actions:
            c.require(type(pending) is dict and set(pending)=={'type','turn_id','call_id','name','arguments'} and
                      pending['type']=='function_call' and pending['turn_id']==turn_id and
                      pending['name'] in diagnostic.READ_TOOLS and type(pending['arguments']) is dict,
                      'unsupported_required_action')
            pending_id=diagnostic._identifier(pending['call_id'])
            c.require(pending_id not in seen,'diagnostic_action_duplicate_call')
            seen.add(pending_id)
            diagnostic.read_diagnostic_tool(self._bundle,pending['name'],pending['arguments'],self._limits)
            if pending_id==call_id:matches.append(pending)
        c.require(len(matches)==1 and matches[0]==action,'diagnostic_action_binding_mismatch')
        c.require(output==diagnostic.read_diagnostic_tool(self._bundle,action['name'],action['arguments'],self._limits),
                  'diagnostic_tool_output_mismatch')
        binding = {'schemaVersion':'sermon-live-diagnostic-required-action-binding-v2',
                   'authorizationSha256':c.fingerprint(self.authorization),
                   'sessionId':session_id,'turnId':turn_id,'callId':call_id,'name':action['name'],
                   'actionSha256':c.fingerprint(action),
                   'argumentsSha256':c.fingerprint(action['arguments']),
                   'sessionResponseSha256':session_snapshot['responseSha256'],
                   'turnsResponseSha256':turns_snapshot['responseSha256'],
                   'sessionTransportSequence':session_snapshot['transportSequence'],
                   'turnsTransportSequence':turns_snapshot['transportSequence'],
                   'pollSequence':self._poll_sequence,'observerDeadlineAt':observer['deadlineAt']}
        immutable.save_once(self.root/'required-action-bindings'/(c.fingerprint(binding)+'.json'),binding)
        jobs._sync_directory_ancestry(self.root/'required-action-bindings')
        return self._invoke('submit_tool_result', (session_id, action, output), timeout_seconds)

    def cancel_once(self, session_id):
        self._session_scope(session_id)
        path = self.root / 'cancel-intent.json'
        c.require(not path.exists(), 'cancel_outcome_requires_reconciliation')
        immutable.save_once(path, {'sessionId': session_id, 'attempts': 1})
        value = self._invoke('cancel', (session_id,), 5.0, cleanup=True)
        immutable.save_once(self.root / 'cancel-returned.json', {'sessionId': session_id,
            'responseSha256': c.fingerprint(value), 'status': 'acknowledged_terminal_not_confirmed'})
        return {'status': 'acknowledged_terminal_not_confirmed', 'sessionId': session_id}


def run_live_diagnostic(manifest, *, root, authorization, current_identity, key=None, fixture_transport=None,
                        checkpoint=None, depends_on=None):
    """One explicit diagnostic; writes only its dedicated observer directory."""
    authorization = validate_authorization(authorization)
    identity = current_identity() if callable(current_identity) else current_identity
    c.require(identity == manifest['identity'], 'stale_diagnostic_snapshot')
    bundle = diagnostic.build_context_bundle(manifest)
    client = LiveDiagnosticClient(root, authorization, key=key, fixture_transport=fixture_transport)
    limits = diagnostic.DiagnosticLimits(**authorization['limits'])
    with ExitStack() as trace, jobs._lock(client.root, c.fingerprint(['live-diagnostic-observer', authorization])) as (_, _, held):
        c.require(held, 'live_diagnostic_observer_busy')
        sdk_receipt={}
        if profile.current() is not None:
            trace.enter_context(accounting.stage('diagnostic.agent_observer',executor_type='decision_agent',depends_on=depends_on))
            sdk_receipt=trace.enter_context(accounting.sdk_invocation(authorization['model'],backend='agents-api'))
        result = diagnostic.diagnose(manifest, client=client, limits=limits, model=authorization['model'],
                                     checkpoint=checkpoint, checkpoint_writer=client.save_checkpoint)
        sdk_receipt['usage']=result['checkpoint']['turnUsage'] or {}
        if result['diagnosis'] is not None:
            identity = current_identity() if callable(current_identity) else current_identity
            diagnostic.validate_recommendation(result['diagnosis'], bundle, current_identity=identity)
        cancellation = {'status': 'not_required'}
        if result['status'] != 'completed' and result['checkpoint']['sessionId'] is not None:
            try:
                cancellation = client.cancel_once(result['checkpoint']['sessionId'])
            except (ValueError, OSError):
                cancellation = {'status': 'outcome_unknown'}
        cost = observed_cost(result['checkpoint']['actualModel'], result['checkpoint']['turnUsage'])
        result['provenance'].update(transportMode='synthetic_live_protocol' if client.synthetic_fixture else 'live',
            budgetEnforcement=authorization['budgetEnforcement'], reservationMicrousd=authorization['reservationMicrousd'],
            costStatus=cost['costStatus'], costObservation=cost, reservationRefunded=False, cancellation=cancellation,
            authorizationSha256=c.fingerprint(authorization))
        immutable.save_once(client.root / 'results' / (c.fingerprint(result) + '.json'), result)
        jobs._sync_directory_ancestry(client.root)
        return result
