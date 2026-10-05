"""Optional durable resource admission for one actual Codex CLI invocation.

Unknown provider outcomes retain their reservation. This helper grants no retry,
lease-expiry recovery or administrative release authority.
"""
from contextlib import contextmanager
from pathlib import Path
import json
import os

from scripts.sermon_execution_harness import atomic_json, utc_now
from scripts.sermon_unified import contracts, resources
from scripts import sermon_workflow_jobs as jobs


def policy_identity(policy):
    return resources._identity(resources.validate_policy(policy))


class Admission:
    def __init__(self, policy, *, call_id, identity, receipt_directory):
        self.policy = resources.validate_policy(policy)
        self.operation_id = 'codex-layer2:' + call_id
        self.owner = {'callId': call_id, 'transportIdentitySha256': contracts.digest(identity),
                      'resourcePolicySha256': policy_identity(policy)}
        self.directory = Path(receipt_directory)
        self.known_terminal = False
        self.response_sha256 = None
        self.reserved = False
        self.consumed = False

    def mark_terminal(self):
        """Caller has waited for the subprocess and seen an explicit terminal turn."""
        self.known_terminal = True

    def reserve(self):
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
        if not resources.reserve(self.policy, operation_id=self.operation_id, owner=self.owner,
                                 resource='codex_cli', units=1):
            raise contracts.ContractError('resource_broker_busy')
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
