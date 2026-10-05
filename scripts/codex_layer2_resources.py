"""Optional durable resource admission for one actual Codex CLI invocation.

Unknown provider outcomes retain their reservation. This helper grants no retry,
lease-expiry recovery or administrative release authority.
"""
from contextlib import contextmanager
from pathlib import Path
import json
import os
import time

from scripts.sermon_execution_harness import atomic_json, utc_now
from scripts.sermon_unified import contracts, resources
from scripts import sermon_workflow_jobs as jobs
from scripts.production_concurrency_profile import validate_profile


def reserve_classified(policy, *, operation_id, owner, resource_class, profile):
    """One atomic durable ledger; unmanaged held calls count as business."""
    profile = validate_profile(profile)
    if resource_class not in {'business', 'supervisor'} or policy['capacities']['codex_cli'] != profile['totalCodexSlots']:
        raise contracts.ContractError('invalid_codex_reserved_capacity')
    key = resources._operation(operation_id)
    with jobs._lock(resources._safe_path(policy['brokerRoot']), resources.BROKER_LOCK_ID) as (folder, _, held):
        if not held:
            return False
        ledger = resources._load(folder, policy)
        if key in ledger['reservations']:
            raise contracts.ContractError('resource_operation_already_reserved')
        occupied = [r for r in ledger['reservations'].values()
                    if r['resource'] == 'codex_cli' and r['status'] == 'held']
        def role(row):
            return ('supervisor' if isinstance(row['owner'], dict)
                    and row['owner'].get('resourceClass') == 'supervisor' else 'business')
        own = sum(r['units'] for r in occupied if role(r) == resource_class)
        limit = profile['businessCodexSlots'] if resource_class == 'business' else profile['supervisorSlots']
        if own >= limit or sum(r['units'] for r in occupied) >= profile['totalCodexSlots']:
            resources._save(folder, ledger)
            return False
        ledger['reservations'][key] = {'operationId': operation_id, 'owner': owner,
            'resource': 'codex_cli', 'units': 1, 'status': 'held', 'reservedAt': utc_now()}
        resources._save(folder, ledger)
        return True


def policy_identity(policy):
    return resources._identity(resources.validate_policy(policy))


class Admission:
    def __init__(self, policy, *, call_id, identity, receipt_directory,
                 concurrency_profile=None, resource_class='business'):
        self.policy = resources.validate_policy(policy)
        self.operation_id = 'codex-layer2:' + call_id
        self.owner = {'callId': call_id, 'transportIdentitySha256': contracts.digest(identity),
                      'resourcePolicySha256': policy_identity(policy)}
        self.profile = validate_profile(concurrency_profile) if concurrency_profile is not None else None
        self.resource_class = resource_class
        if self.profile is not None:
            self.owner.update(resourceClass=resource_class, concurrencyProfileSha256=contracts.digest(self.profile))
        self.directory = Path(receipt_directory)
        self.known_terminal = False
        self.response_sha256 = None
        self.reserved = False
        self.consumed = False

    def mark_terminal(self):
        """Caller has waited for the subprocess and seen an explicit terminal turn."""
        self.known_terminal = True

    def reserve(self, *, wait_timeout_seconds=None):
        if self.reserved:
            raise contracts.ContractError('resource_permit_already_reserved')
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        binding = {'schemaVersion': 'codex-layer2-resource-binding-v1',
                   'operationId': self.operation_id, 'owner': self.owner}
        path = self.directory / 'resource-binding.json'
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            if json.loads(path.read_text()) != binding:
                raise contracts.ContractError('resource_call_identity_changed', 7)
        else:
            with os.fdopen(fd, 'w') as handle:
                json.dump(binding, handle, sort_keys=True)
                handle.write('\n')
                handle.flush()
                os.fsync(handle.fileno())
            jobs._sync_directory(self.directory)
        wait_seconds = self.profile['busyWaitSeconds'] if self.profile else 0
        if wait_timeout_seconds is not None:
            if type(wait_timeout_seconds) not in (int,float) or not 0 <= wait_timeout_seconds < float('inf'):
                raise ValueError('invalid_resource_wait_timeout')
            wait_seconds=min(wait_seconds,wait_timeout_seconds)
        deadline = time.monotonic() + wait_seconds
        while True:
            granted = (reserve_classified(self.policy, operation_id=self.operation_id, owner=self.owner,
                resource_class=self.resource_class, profile=self.profile) if self.profile else
                resources.reserve(self.policy, operation_id=self.operation_id, owner=self.owner,
                                  resource='codex_cli', units=1))
            if granted:
                break
            if time.monotonic() >= deadline:
                raise contracts.ContractError('resource_broker_busy')
            time.sleep(.05)
        self.reserved = True
        return self

    @contextmanager
    def dispatch(self):
        if not self.reserved or self.consumed:
            raise contracts.ContractError('resource_permit_not_dispatchable')
        self.consumed = True
        error = None
        try:
            yield self
        except BaseException as exc:
            error = exc
            raise
        finally:
            # A write failure must keep capacity held. Never replace the original
            # model exception with a release/write error.
            try:
                atomic_json(self.directory / 'resource-outcome.json', {
                    'schemaVersion': 'codex-layer2-resource-outcome-v1',
                    'operationId': self.operation_id, 'owner': self.owner,
                    'status': 'terminal' if self.known_terminal else 'unknown_outcome',
                    'errorType': type(error).__name__ if error else None,
                    'responseSha256': self.response_sha256, 'recordedAt': utc_now()})
                jobs._sync_directory(self.directory)
                if self.known_terminal:
                    resources.release(self.policy, operation_id=self.operation_id, owner=self.owner)
            except BaseException:
                if error is None:
                    raise
                error.codex_resource_finalization_failed = True
