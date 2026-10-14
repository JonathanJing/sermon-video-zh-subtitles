"""No second payment after damaged/unknown evidence; v4 reuse is explicitly bound."""
import copy
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts import sermon_source_budget as budget
from scripts import sermon_workflow_jobs as jobs
from tests.test_source_budget_reuse import store, JudgeAuthorizationTests
from tests.test_source_budget_settlement import AUTHORITY, BOUNDS, IDENTITY, OPERATION, call, ledger


def snapshot(root):
    return {str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in root.rglob('*') if path.is_file()}


@pytest.mark.parametrize('damage', ['missing', 'unreadable', 'tampered', 'identity', 'reservation'])
def test_matching_paid_response_damage_blocks_without_payment_or_source_writes(tmp_path, damage):
    source, dest = tmp_path/'source', tmp_path/'dest'
    call(store(source))
    response = next((source/'responses').iterdir())
    if damage == 'missing':
        response.unlink()
    elif damage in ('tampered', 'identity', 'reservation'):
        value = jobs._read(response)
        value[{'tampered':'response', 'identity':'requestIdentity', 'reservation':'reservationBounds'}[damage]] = {}
        jobs._persist(response, value)
    before = snapshot(source)
    dispatched = []
    original = jobs._read
    def read(path):
        if damage == 'unreadable' and Path(path) == response:
            raise PermissionError('fixture')
        return original(path)
    with patch.object(jobs, '_read', side_effect=read), pytest.raises(ValueError, match='source_reuse_response_reconciliation_required'):
        call(store(dest, reuse=[source], transport=lambda *args: dispatched.append(1)))
    assert dispatched == []
    assert snapshot(source) == before
    assert not (dest/'source-budget.json').exists()


@pytest.mark.parametrize('status', ['live_started', 'started_response_unconfirmed'])
@pytest.mark.parametrize('unknown_first', [True, False])
def test_matching_unknown_in_any_root_blocks_even_when_another_root_returned(tmp_path, status, unknown_first):
    good, unknown, dest = (tmp_path/name for name in ['good', 'unknown', 'dest'])
    call(store(good)); call(store(unknown))
    value = ledger(unknown)
    row = value['requests'][OPERATION]
    row.update(status=status)
    row.pop('settlement'); row.pop('responseSha256')
    if status == 'live_started':
        row['dispatchOwner'] = {'token':'a'*32, 'pid':1}
    jobs._persist(unknown/'source-budget.json', value)
    before = {str(root): snapshot(root) for root in (good, unknown)}
    roots = [unknown, good] if unknown_first else [good, unknown]
    dispatched = []
    with pytest.raises(ValueError, match='source_provider_outcome_unknown'):
        call(store(dest, reuse=roots, transport=lambda *args: dispatched.append(1)))
    assert dispatched == []
    assert before == {str(root): snapshot(root) for root in (good, unknown)}


@pytest.mark.parametrize('version', [budget.LEDGER_V2, budget.LEDGER_V3])
def test_legacy_ledgers_keep_their_contract_and_require_explicit_reuse_upgrade(tmp_path, version):
    source, dest = tmp_path/'source', tmp_path/'dest'
    call(store(source))
    legacy = {'schemaVersion':version, 'authority':AUTHORITY, 'requests':{}, 'maxConcurrent':1, 'resourcePolicySha256':None}
    dest.mkdir()
    jobs._persist(dest/'source-budget.json', legacy)
    reader = store(dest, reuse=[source])
    with pytest.raises(ValueError, match='source_budget_v4_explicit_migration_required'):
        call(reader)
    assert ledger(dest) == legacy
    migrated = reader.migrate_to_v4()
    assert migrated['from'] == version and migrated['to'] == budget.LEDGER_V4 and migrated['modelCalls'] == 0
    call(reader)
    result = ledger(dest)
    assert result['schemaVersion'] == budget.LEDGER_V4
    assert result['reuseBudgetRoots'] == [str(source.resolve())]
    assert result['requests'][OPERATION]['settlement']['costStatus'] == 'reused'
    assert reader.migrate_to_v4()['status'] == 'already_v4'
    with pytest.raises(ValueError, match='source_budget_identity_changed'):
        call(store(dest))  # an existing v4 root cannot silently change its reuse approval


@pytest.mark.parametrize('version', [budget.LEDGER_V2, budget.LEDGER_V3])
def test_migration_preserves_paid_bounds_and_unknown_outcomes(tmp_path, version):
    root = tmp_path/'root'
    call(store(root))
    original = ledger(root)
    original['schemaVersion'] = version
    original.pop('reuseBudgetRoots')
    if version == budget.LEDGER_V2:
        original['requests'][OPERATION].pop('settlement')
    unknown = 'judge.'+'d'*64
    original['requests'][unknown] = {'identitySha256':'e'*64, 'bounds':BOUNDS, 'status':'started_response_unconfirmed'}
    jobs._persist(root/'source-budget.json', original)
    reader = store(root)
    assert reader.migrate_to_v4()['settledRows'] == 1
    result = ledger(root)
    assert result['requests'][OPERATION]['bounds'] == BOUNDS
    assert result['requests'][unknown] == original['requests'][unknown]
    assert result['requests'][OPERATION]['settlement']['costStatus'] == 'estimated_upper_bound'


def test_v3_rejects_reused_enum_and_v4_provenance_cannot_be_removed(tmp_path):
    source, dest = tmp_path/'source', tmp_path/'dest'
    call(store(source)); call(store(dest, reuse=[source]))
    current = ledger(dest)
    old = copy.deepcopy(current); old['schemaVersion'] = budget.LEDGER_V3; old.pop('reuseBudgetRoots')
    jobs._persist(dest/'source-budget.json', old)
    with pytest.raises(ValueError, match='source_budget_ledger_corrupt'):
        store(dest).returned(OPERATION, IDENTITY)
    jobs._persist(dest/'source-budget.json', current)
    response = next((dest/'responses').iterdir())
    value = jobs._read(response); value.pop('reusedFrom')
    jobs._persist(response, value)
    current['requests'][OPERATION]['responseSha256'] = jobs._digest(value)
    jobs._persist(dest/'source-budget.json', current)
    with pytest.raises(ValueError, match='source_reused_provenance_changed'):
        call(store(dest, reuse=[source]))


@pytest.mark.parametrize('changed', ['authorization', 'approval', 'runtime'])
def test_live_qc_judge_rechecks_approval_roots_and_runtime_before_dispatch(tmp_path, changed):
    from scripts import run_machine_qc_clip_test as driver
    path = JudgeAuthorizationTests().write(tmp_path, approved_reuse=[str(tmp_path/'source')], requested_reuse=[str(tmp_path/'source')])
    route = {'environment':'dev', 'credentialAlias':'tongxing-dev-runtime', 'projectId':'proj_fixture'}
    with patch('scripts.sermon_openai_runtime.selected_route', return_value=route) as selected, \
         patch('scripts.production_spark_admission.require_session'), patch.dict('os.environ', {'OPENAI_API_KEY':'fixture-not-a-key'}):
        judge = driver.ApiJudge(path)
        if changed == 'runtime':
            selected.return_value = dict(route, environment='prod')
        else:
            target = path if changed == 'authorization' else tmp_path/'approval.json'
            target.write_text(target.read_text()+'\n')
        dispatched = []
        judge.ledger.transport = lambda *args: dispatched.append(1)
        with pytest.raises(ValueError, match='authorization changed after admission'):
            call(judge.ledger)
        assert dispatched == []


@pytest.mark.parametrize('version', [budget.LEDGER_V2, budget.LEDGER_V3])
def test_read_only_reuse_from_legacy_paid_source_ledger(tmp_path, version):
    source, dest = tmp_path/'source', tmp_path/'dest'
    paid = call(store(source))
    value = ledger(source); value['schemaVersion'] = version; value.pop('reuseBudgetRoots')
    if version == budget.LEDGER_V2:
        value['requests'][OPERATION].pop('settlement')
    jobs._persist(source/'source-budget.json', value)
    before = snapshot(source)
    assert call(store(dest, reuse=[source], transport=lambda *args: pytest.fail('redispatched'))) == paid
    assert snapshot(source) == before
    saved = jobs._read(next((dest/'responses').iterdir()))
    assert saved['reusedFrom']['sourceLedgerVersion'] == version
    assert saved['reusedFrom']['sourceAuthoritySha256'] == jobs._digest(AUTHORITY)


@pytest.mark.parametrize('version', [budget.LEDGER_V2, budget.LEDGER_V3])
def test_bad_paid_response_migration_preserves_old_ledger_bytes(tmp_path, version):
    root = tmp_path/'root'
    call(store(root))
    value = ledger(root); value['schemaVersion'] = version; value.pop('reuseBudgetRoots')
    if version == budget.LEDGER_V2:
        value['requests'][OPERATION].pop('settlement')
    jobs._persist(root/'source-budget.json', value)
    response = next((root/'responses').iterdir())
    changed = jobs._read(response); changed['elapsedSeconds'] = 99
    jobs._persist(response, changed)
    before = (root/'source-budget.json').read_bytes()
    with pytest.raises(ValueError, match='source_response_identity_changed'):
        store(root).migrate_to_v4()
    assert (root/'source-budget.json').read_bytes() == before


@pytest.mark.parametrize('version', ['sermon-source-budget-ledger-v1', budget.LEDGER_V2])
@pytest.mark.parametrize('damaged_settlement', [
    {'costStatus': 'estimated_upper_bound', 'costMicrousd': -1},
    {'costStatus': 'estimated_upper_bound', 'costMicrousd': True},
    {'costStatus': 'unknown', 'costMicrousd': 'invalid'},
    {'costStatus': 'invalid', 'costMicrousd': 0},
    [], None,
])
def test_invalid_legacy_settlement_cannot_enter_reused_provenance(tmp_path, version, damaged_settlement):
    source, dest = tmp_path/'source', tmp_path/'dest'
    call(store(source))
    response = next((source/'responses').iterdir())
    saved = jobs._read(response)
    saved['settlement'] = damaged_settlement
    jobs._persist(response, saved)
    value = ledger(source)
    value.update(schemaVersion=version)
    value.pop('reuseBudgetRoots')
    if version == 'sermon-source-budget-ledger-v1':
        value.pop('maxConcurrent'); value.pop('resourcePolicySha256')
    value['requests'][OPERATION].pop('settlement')
    # Even a consistent updated response digest cannot bless bad settlement.
    value['requests'][OPERATION]['responseSha256'] = jobs._digest(saved)
    jobs._persist(source/'source-budget.json', value)
    before = snapshot(source)
    with pytest.raises(ValueError, match='source_reuse_response_reconciliation_required'):
        call(store(dest, reuse=[source], transport=lambda *args: pytest.fail('redispatched')))
    assert snapshot(source) == before
    assert not (dest/'source-budget.json').exists()
    assert not (dest/'responses').exists()


@pytest.mark.parametrize('version', ['sermon-source-budget-ledger-v1', budget.LEDGER_V2])
def test_legacy_response_without_settlement_computes_valid_direct_provenance(tmp_path, version):
    source, dest = tmp_path/'source', tmp_path/'dest'
    paid = call(store(source))
    response = next((source/'responses').iterdir())
    saved = jobs._read(response); saved.pop('settlement')
    jobs._persist(response, saved)
    value = ledger(source); value.update(schemaVersion=version); value.pop('reuseBudgetRoots')
    if version == 'sermon-source-budget-ledger-v1':
        value.pop('maxConcurrent'); value.pop('resourcePolicySha256')
    value['requests'][OPERATION].pop('settlement')
    value['requests'][OPERATION]['responseSha256'] = jobs._digest(saved)
    jobs._persist(source/'source-budget.json', value)
    before = snapshot(source)
    assert call(store(dest, reuse=[source], transport=lambda *args: pytest.fail('redispatched'))) == paid
    assert call(store(dest, reuse=[source], transport=lambda *args: pytest.fail('redispatched'))) == paid
    assert snapshot(source) == before
    reused = jobs._read(next((dest/'responses').iterdir()))
    assert budget._valid_settlement(reused['reusedFrom']['originalSettlement'], version=budget.LEDGER_V3)
