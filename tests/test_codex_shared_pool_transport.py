"""Shared business/supervisor admission with fake CLI only."""
import json
from pathlib import Path
import subprocess
from unittest.mock import patch

import pytest
from scripts import sermon_codex_transport as transport
from scripts import sermon_codex_supervisor as supervisor
from scripts import codex_layer2_resources as slots
from scripts.production_concurrency_profile import profile_v1
from scripts.sermon_unified import resources
from tests import test_sermon_codex_transport as cli_fixtures
from tests import test_sermon_codex_supervisor as supervisor_fixtures


@pytest.fixture
def cli():
    helper = cli_fixtures.ProductionCodexTransportTests()
    helper.setUp()
    try:
        yield helper
    finally:
        helper.doCleanups()


def policy(root):
    return {'schemaVersion': resources.POLICY_VERSION, 'brokerRoot': str(root / 'broker'),
        'capacities': {name: (24 if name == 'codex_cli' else 1) for name in resources.RESOURCE_LIMITS}}


def ledger(value):
    return json.loads((Path(value['brokerRoot']) / resources.BROKER_LOCK_ID / 'resources.json').read_text())


def reserve(value, number, role='business'):
    return slots.reserve_classified(value, operation_id='held-' + str(number), owner={'resourceClass': role},
        resource_class=role, profile=profile_v1())


def test_business_full_supervisor_reserved_slot_released_and_cached_without_call(cli):
    value = policy(cli.root)
    for index in range(23):
        assert reserve(value, index)
    def inspect(command, **kwargs):
        held = [r for r in ledger(value)['reservations'].values() if r['status'] == 'held']
        assert len(held) == 24
        assert sum(r['owner'].get('resourceClass') == 'supervisor' for r in held) == 1
        assert (cli.directory / 'started.json').exists()
        return cli.fake_run(command, **kwargs)
    cli.run.side_effect = inspect
    options = dict(model='gpt-6-luna', reasoning='medium', output_dir=cli.directory,
                   resource_policy=value, concurrency_profile=profile_v1())
    first = transport._call('Supervise frozen state', **options)
    assert len([r for r in ledger(value)['reservations'].values() if r['status'] == 'held']) == 23
    assert transport._call('Supervise frozen state', **options) == first
    assert cli.run.call_count == 1


def test_busy_before_started_is_proven_no_dispatch(cli):
    value = policy(cli.root)
    with patch.object(slots.Admission, 'reserve', side_effect=slots.contracts.ContractError('resource_broker_busy')):
        with pytest.raises(transport.CodexResourceBusy):
            cli.call(resource_policy=value, concurrency_profile=profile_v1())
    assert not (cli.directory / 'started.json').exists()
    assert json.loads((cli.directory / 'outcome.json').read_text())['status'] == 'not_dispatched_resource_busy'
    cli.run.assert_not_called()


def test_unknown_timeout_retains_business_slot_and_cannot_reissue(cli):
    value = policy(cli.root)
    cli.run.side_effect = subprocess.TimeoutExpired(['fake'], 1, output='partial')
    options = dict(resource_policy=value, concurrency_profile=profile_v1())
    with pytest.raises(subprocess.TimeoutExpired):
        cli.call(**options)
    assert len([r for r in ledger(value)['reservations'].values() if r['status'] == 'held']) == 1
    with pytest.raises(RuntimeError, match='reconciliation'):
        cli.call(**options)
    assert cli.run.call_count == 1


def test_explicit_failed_terminal_releases_but_does_not_retry(cli):
    value = policy(cli.root)
    def failed(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, json.dumps({'type': 'turn.failed'}), 'failure')
    cli.run.side_effect = failed
    options = dict(resource_policy=value, concurrency_profile=profile_v1())
    with pytest.raises(RuntimeError):
        cli.call(**options)
    assert all(r['status'] == 'released' for r in ledger(value)['reservations'].values())
    with pytest.raises(RuntimeError, match='reconciliation'):
        cli.call(**options)
    assert cli.run.call_count == 1


def test_profile_role_and_capacity_mismatch_never_dispatch(cli):
    value = policy(cli.root)
    with pytest.raises(ValueError, match='role_mismatch'):
        cli.call(resource_policy=value, concurrency_profile=profile_v1(), resource_class='supervisor')
    value['capacities']['codex_cli'] = 23
    with pytest.raises(ValueError, match='capacity_mismatch'):
        cli.call(resource_policy=value, concurrency_profile=profile_v1())
    cli.run.assert_not_called()


def test_busy_supervisor_clears_pending_and_resume_new_attempt(tmp_path):
    args, config = supervisor_fixtures.setup(tmp_path)
    directories = []
    def busy(prompt, **kwargs):
        folder = kwargs['output_dir']; folder.mkdir()
        identity = {'test': True}
        (folder / 'identity.json').write_text(json.dumps(identity))
        (folder / 'outcome.json').write_text(json.dumps({'status': 'not_dispatched_resource_busy',
                                                       'identitySha256': transport._hash(identity)}))
        directories.append(folder)
        raise transport.CodexResourceBusy('resource_broker_busy')
    with patch.object(supervisor.workflow, 'snapshot', return_value=supervisor_fixtures.state('request_window_approval', True)):
        failed = supervisor_fixtures.run(args, config, busy)
        directory = Path(failed['agentSession']['runDirectory'])
        state = json.loads((directory / 'codex-state.json').read_text())
        assert not state['pending'] and state['turns'] == 0 and state['dispatchAttempts'] == 1
        args.resume_agent_session = True; args.agent_run_dir = directory
        def completed(prompt, **kwargs):
            directories.append(kwargs['output_dir'])
            return supervisor_fixtures.decision('request_window_approval', True)
        result = supervisor_fixtures.run(args, config, completed)
    assert result['agentSession']['status'] == 'completed'
    assert directories[0].name == 'turn-001'
    assert directories[1].name == 'turn-001-attempt-002'


@pytest.mark.parametrize('started,typed', [(True, True), (False, False)])
def test_started_or_unproven_busy_supervisor_stays_unknown(tmp_path, started, typed):
    args, config = supervisor_fixtures.setup(tmp_path)
    def busy(prompt, **kwargs):
        folder = kwargs['output_dir']; folder.mkdir()
        identity = {'test': True}
        (folder / 'identity.json').write_text(json.dumps(identity))
        (folder / 'outcome.json').write_text(json.dumps({'status': 'not_dispatched_resource_busy',
                                                       'identitySha256': transport._hash(identity)}))
        if started: (folder / 'started.json').write_text('{}')
        raise (transport.CodexResourceBusy('resource_broker_busy') if typed else RuntimeError('resource_broker_busy'))
    with patch.object(supervisor.workflow, 'snapshot', return_value=supervisor_fixtures.state('request_window_approval', True)):
        result = supervisor_fixtures.run(args, config, busy)
    directory = Path(result['agentSession']['runDirectory'])
    assert json.loads((directory / 'codex-state.json').read_text())['pending'] is True


@pytest.mark.parametrize('wait', [25, 61])
def test_capacity_wait_consumes_call_budget_and_never_starts_after_expiry(cli, wait):
    value = policy(cli.root)
    now = [0]
    original = slots.Admission.reserve
    def delayed(permit, *, wait_timeout_seconds=None):
        assert wait_timeout_seconds == 60
        result = original(permit, wait_timeout_seconds=wait_timeout_seconds)
        now[0] = wait
        return result
    with patch.object(transport.time, 'monotonic', side_effect=lambda: now[0]), \
         patch.object(slots.Admission, 'reserve', autospec=True, side_effect=delayed):
        if wait < 60:
            cli.call(resource_policy=value, concurrency_profile=profile_v1(), timeout_seconds=60)
            assert cli.executions[0][1]['timeout'] == 35
        else:
            with pytest.raises(transport.CodexResourceBusy):
                cli.call(resource_policy=value, concurrency_profile=profile_v1(), timeout_seconds=60)
            assert not (cli.directory / 'started.json').exists()
            cli.run.assert_not_called()
    assert all(row['status'] == 'released' for row in ledger(value)['reservations'].values())


def test_chat_json_accepts_explicit_profile_and_uses_business_pool(cli):
    value = policy(cli.root)
    original = transport._call
    def private(prompt, **kwargs):
        return original(prompt, output_dir=cli.directory, **kwargs)
    payload = {'model': 'gpt-6.1-sol', 'reasoning_effort': 'high',
        'messages': [{'role': 'user', 'content': 'Bound source'}], 'response_format': {'type': 'json_object'}}
    with patch.object(transport, '_call', side_effect=private):
        result = transport.chat_json('', payload, resource_policy=value, concurrency_profile=profile_v1())
    assert result['modelIdentityKind'] == 'requested'
    rows = list(ledger(value)['reservations'].values())
    assert len(rows) == 1 and rows[0]['owner']['resourceClass'] == 'business' and rows[0]['status'] == 'released'
