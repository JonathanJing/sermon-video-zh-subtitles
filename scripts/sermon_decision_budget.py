"""Durable attempt reservation for bounded proposals, using existing job locks.

No model SDK or dispatch is added. The initial conservative policy permits two
decision calls per production run, not two per changed packet or per locale.
An interrupted/unknown outcome requires reconciliation; it never resets budget.
"""
import os
from pathlib import Path

from scripts import sermon_bounded_decision as decision
from scripts import sermon_workflow_jobs as jobs
from scripts.sermon_decision_accounting import Observation
from scripts.sermon_accounting import AccountingWriteError
from scripts.sermon_release_workflow import _safe_path

SCHEMA = 'sermon-decision-budget-v1'


class Budget:
    def __init__(self, root, production_run_id):
        if not decision._sha(production_run_id):
            raise ValueError('invalid_production_run_identity')
        self.root = _safe_path(Path(root).absolute())
        self.key = jobs._digest({'purpose': 'decision-budget', 'productionRunId': production_run_id})
        self.folder = self.root / self.key
        self.lock_path = self.root / '.locks' / (self.key + '.lock')
        self.binding = {'schemaVersion': SCHEMA, 'productionRunId': production_run_id,
                        'workflowDefinitionVersion': decision.VERSION, 'maxAttempts': decision.MAX_ATTEMPTS}

    def _load(self):
        state_path = self.folder / 'state.json'
        jobs._reject_link(self.folder, directory=True)
        if state_path.stat().st_size > 16384:
            raise ValueError('decision_budget_evidence_too_large')
        saved = jobs._read(state_path)
        if not isinstance(saved, dict) or set(saved) != {'binding', 'attempts'} or saved['binding'] != self.binding:
            raise ValueError('decision_budget_binding_changed')
        attempts = saved['attempts']
        if not isinstance(attempts, list) or not 1 <= len(attempts) <= decision.MAX_ATTEMPTS:
            raise ValueError('invalid_decision_attempts')
        seen = set()
        for row in attempts:
            if (not isinstance(row, dict) or set(row) != {'decisionId', 'packetSha256', 'stateRevision', 'status', 'resultSha256'}
                    or any(not decision._sha(row[k]) for k in ('decisionId', 'packetSha256', 'stateRevision'))
                    or row['decisionId'] in seen or row['status'] not in {'reserved', 'returned'}
                    or (row['status'] == 'reserved' and row['resultSha256'] is not None)
                    or (row['status'] == 'returned' and not decision._sha(row['resultSha256']))):
                raise ValueError('invalid_decision_attempt_evidence')
            seen.add(row['decisionId'])
        return saved

    def remaining(self):
        """Read-only optimistic budget; reserve rechecks under the durable lock."""
        if not self.folder.exists():
            if self.lock_path.exists():
                raise ValueError('decision_budget_initialization_uncertain')
            return decision.MAX_ATTEMPTS
        saved = self._load()
        return 0 if any(row['status'] == 'reserved' for row in saved['attempts']) else decision.MAX_ATTEMPTS - len(saved['attempts'])

    def reserve(self, packet):
        packet = decision.validate_packet(packet)
        if packet['productionRunId'] != self.binding['productionRunId']:
            raise ValueError('decision_budget_run_mismatch')
        if not self.folder.exists() and packet['retryBudget']['remainingDecisionAttempts'] != decision.MAX_ATTEMPTS:
            return False
        had_lock = self.lock_path.exists()
        # _lock may create root and multiple missing ancestors. Remember their
        # parent entries before creation so a host crash cannot erase the run's
        # uncertainty markers and reopen its budget after a model call.
        parents_to_sync = [self.root.parent]
        while not parents_to_sync[-1].exists():
            parents_to_sync.append(parents_to_sync[-1].parent)
        with jobs._lock(self.root, self.key) as (folder, lock_fd, held):
            if not held:
                return False
            if folder.exists():
                saved = self._load()
            else:
                if had_lock:
                    raise ValueError('decision_budget_initialization_uncertain')
                saved = {'binding': self.binding, 'attempts': []}
            attempts = saved['attempts']
            if (len(attempts) >= decision.MAX_ATTEMPTS
                    or any(row['status'] == 'reserved' or row['decisionId'] == packet['decisionId'] for row in attempts)
                    or packet['retryBudget']['remainingDecisionAttempts'] != decision.MAX_ATTEMPTS - len(attempts)):
                return False
            attempts.append({'decisionId': packet['decisionId'], 'packetSha256': jobs._digest(packet),
                             'stateRevision': packet['stateRevision'], 'status': 'reserved', 'resultSha256': None})
            # Existence is an initialization marker. A crash before state.json
            # becomes durable is uncertainty, never permission to start over.
            folder.mkdir(exist_ok=True)
            # Persist the lock inode, lock directory entry, budget-folder entry
            # and root/ancestor entries BEFORE publishing the reservation. The
            # existing atomic writer then fsyncs state.json and its directory.
            # Any failed sync aborts admission before the responder is invoked.
            os.fsync(lock_fd)
            jobs._sync_directory(self.lock_path.parent)
            jobs._sync_directory(self.root)
            for parent in parents_to_sync:
                jobs._sync_directory(parent)
            jobs._persist(folder / 'state.json', saved)
            return True

    def _record_returned(self, packet, result):
        with jobs._lock(self.root, self.key) as (_, _, held):
            if not held:
                return False
            saved = self._load()
            row = next((r for r in saved['attempts'] if r['decisionId'] == packet['decisionId']), None)
            if row is None or row['status'] != 'reserved' or row['packetSha256'] != jobs._digest(packet):
                raise ValueError('decision_reservation_changed')
            row.update(status='returned', resultSha256=jobs._digest(result))
            jobs._persist(self.folder / 'state.json', saved)
            return True


def propose(packet, *, budget, responder, fresh_packet):
    """Reserve before one injected call; still requires later locked admission."""
    packet = decision.validate_packet(packet)
    # A stale proposal need not consume a call. The existing validator repeats
    # freshness checks after the responder and before returning any proposal.
    if decision.validate_packet(fresh_packet()) != packet:
        return {'status': 'blocked', 'reasonCode': 'stale_state_before_reservation', 'dispatchEnabled': False}
    result = decision.propose(packet, reserve_attempt=budget.reserve, responder=responder, fresh_packet=fresh_packet)
    if result['status'] == 'proposal_requires_locked_admission' or result.get('reasonCode') == 'decision_rejected':
        observation = Observation(packet, phase='commit', observation_id=result['decisionObservationId'],
                                  depends_on=[result['decisionValidationSpanId']])
        try:
            with observation.measure('stateCommitMs'):
                recorded = budget._record_returned(packet, result)
        except AccountingWriteError:
            # A trace failure can occur after the durable commit succeeded.
            # Preserve that distinction; never relabel it as a failed commit.
            raise
        except (OSError, ValueError):
            recorded = False
        observation.finish('commit_recorded' if recorded else 'commit_failed')
        if not recorded:
            return {'status': 'blocked', 'reasonCode': 'decision_return_not_durably_recorded', 'dispatchEnabled': False}
    # Unknown outcome leaves the reserved record untouched, consuming the call
    # and blocking further calls until a separate trusted reconciliation exists.
    return result
