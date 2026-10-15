"""Host-local durable reservations; unknown outcomes keep capacity occupied.

No process is started here. A reservation is a single dispatch permission, never
an idempotent invitation to dispatch again. Only the original owner may release
it after the caller has confirmed a known terminal outcome. Different broker
roots and unmanaged callers do not share this bound.
"""
from __future__ import annotations

import copy
from pathlib import Path
import time

from scripts import sermon_workflow_jobs as jobs
from scripts.sermon_execution_harness import atomic_json, utc_now
from scripts.sermon_release_workflow import _safe_path
from scripts.sermon_unified import contracts

POLICY_VERSION = 'sermon-unified-resource-policy-v1'
LEDGER_VERSION = 'sermon-unified-resource-ledger-v1'
BROKER_LOCK_ID = contracts.digest({'resourceBroker': LEDGER_VERSION})
RESOURCE_LIMITS = {'cpu': 64, 'online_api': 24, 'codex_cli': 24,
                   'spark_tts': 1, 'publisher': 1}


def validate_policy(policy):
    """Pure admission, including paths; does not create the broker directory."""
    contracts.validate(policy, POLICY_VERSION)
    # Explicit types disallow bool and integral floats regardless of validator.
    if any(type(value) is not int or not 0 <= value <= RESOURCE_LIMITS[name]
           for name, value in policy['capacities'].items()):
        raise contracts.ContractError('resource_capacity_invalid', 2)
    raw = policy['brokerRoot']
    path = Path(raw)
    if not path.is_absolute() or '\x00' in raw or '..' in path.parts or path == Path('/'):
        raise contracts.ContractError('resource_broker_path_invalid', 2)
    try:
        safe = _safe_path(path)
        if safe.exists() and not safe.is_dir():
            raise ValueError('Broker must be a directory')
    except (OSError, ValueError):
        raise contracts.ContractError('resource_broker_path_invalid', 2) from None
    return copy.deepcopy(policy)


def _owner(owner):
    if not ((isinstance(owner, str) and owner.strip() and len(owner) <= 1024)
            or (type(owner) is dict and owner)):
        raise contracts.ContractError('resource_owner_invalid', 2)
    try:
        contracts.digest(owner)
    except (TypeError, ValueError):
        raise contracts.ContractError('resource_owner_invalid', 2) from None
    return copy.deepcopy(owner)


def _operation(operation_id):
    if (not isinstance(operation_id, str) or not 1 <= len(operation_id) <= 256
            or not operation_id.strip() or any(ord(c) < 32 for c in operation_id)):
        raise contracts.ContractError('resource_operation_invalid', 2)
    return contracts.digest(operation_id)


def _identity(policy):
    # System aliases (e.g. /tmp and /private/tmp on macOS) are the same broker.
    return contracts.digest({**policy, 'brokerRoot': str(_safe_path(policy['brokerRoot']))})


def _load(folder, policy):
    path = _safe_path(folder / 'resources.json')
    policy_hash = _identity(policy)
    if not path.exists():
        return {'schemaVersion': LEDGER_VERSION, 'policySha256': policy_hash,
                'reservations': {}}
    ledger = contracts.read(path)
    if (not isinstance(ledger, dict) or set(ledger) != {'schemaVersion', 'policySha256', 'reservations'}
            or ledger['schemaVersion'] != LEDGER_VERSION or not isinstance(ledger['reservations'], dict)):
        raise contracts.ContractError('resource_ledger_invalid')
    if ledger['policySha256'] != policy_hash:
        raise contracts.ContractError('resource_policy_changed', 7)
    for key, row in ledger['reservations'].items():
        if (not isinstance(row, dict)
                or set(row) not in ({'operationId', 'owner', 'resource', 'units', 'status', 'reservedAt'},
                                    {'operationId', 'owner', 'resource', 'units', 'status', 'reservedAt', 'releasedAt'})
                or row['resource'] not in RESOURCE_LIMITS
                or type(row['units']) is not int or not 1 <= row['units'] <= policy['capacities'][row['resource']]
                or row['status'] not in ('held', 'released')
                or (row['status'] == 'released') != ('releasedAt' in row)
                or not isinstance(row['reservedAt'], str)
                or _operation(row['operationId']) != key):
            raise contracts.ContractError('resource_ledger_invalid')
        _owner(row['owner'])
    if any(sum(row['units'] for row in ledger['reservations'].values()
               if row['status'] == 'held' and row['resource'] == name) > capacity
           for name, capacity in policy['capacities'].items()):
        raise contracts.ContractError('resource_ledger_over_capacity')
    return ledger


def _save(folder, ledger):
    folder = _safe_path(folder)
    folder.mkdir(exist_ok=True, mode=0o700)
    atomic_json(_safe_path(folder / 'resources.json'), ledger)
    jobs._sync_directory(folder)
    jobs._sync_directory(folder.parent)


def reserve(policy, *, operation_id, owner, resource, units=1):
    """Return True for a new permit, False for busy; duplicate dispatch raises."""
    policy = validate_policy(policy)
    key, owner = _operation(operation_id), _owner(owner)
    if not isinstance(resource, str) or resource not in RESOURCE_LIMITS:
        raise contracts.ContractError('resource_name_invalid', 2)
    if type(units) is not int or units < 1 or (policy['capacities'][resource] > 0
                                             and units > policy['capacities'][resource]):
        raise contracts.ContractError('resource_units_invalid', 2)
    with jobs._lock(_safe_path(policy['brokerRoot']), BROKER_LOCK_ID) as (folder, _, held):
        if not held:
            return False
        ledger = _load(folder, policy)
        previous = ledger['reservations'].get(key)
        if previous is not None:
            if previous['owner'] != owner or previous['resource'] != resource or previous['units'] != units:
                raise contracts.ContractError('resource_operation_identity_changed', 7)
            raise contracts.ContractError('resource_operation_already_reserved')
        occupied = sum(row['units'] for row in ledger['reservations'].values()
                       if row['resource'] == resource and row['status'] == 'held')
        if occupied + units > policy['capacities'][resource]:
            # Even a zero-capacity first admission freezes this broker policy.
            _save(folder, ledger)
            return False
        ledger['reservations'][key] = {'operationId': operation_id, 'owner': owner,
            'resource': resource, 'units': units, 'status': 'held', 'reservedAt': utc_now()}
        _save(folder, ledger)
        return True


def release(policy, *, operation_id, owner):
    """Explicit known-terminal acknowledgement by the bound original owner.

    There is deliberately no lease expiry, PID check, cancellation shortcut or
    administrative owner takeover. Reconciliation must prove terminal outcome
    before the runtime calls this function. A released operation stays recorded.
    """
    policy = validate_policy(policy)
    key, owner = _operation(operation_id), _owner(owner)
    deadline = time.monotonic() + 10
    while True:
        with jobs._lock(_safe_path(policy['brokerRoot']), BROKER_LOCK_ID) as (folder, _, held):
            if held:
                ledger = _load(folder, policy)
                previous = ledger['reservations'].get(key)
                if previous is None:
                    raise contracts.ContractError('resource_reservation_missing')
                if previous['owner'] != owner:
                    raise contracts.ContractError('resource_owner_changed', 7)
                if previous['status'] == 'released':
                    return
                previous.update(status='released', releasedAt=utc_now())
                _save(folder, ledger)
                return
        if time.monotonic() >= deadline:
            raise contracts.ContractError('resource_broker_busy')
        time.sleep(.02)
