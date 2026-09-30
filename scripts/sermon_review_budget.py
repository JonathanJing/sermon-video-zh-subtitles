"""Private D5 reservation ledger using the existing durable-job primitives.

Trusted integration must supply ONE pinned shared root and load approved bounds.
An approval hash is a reference, not proof of human authorization. This module
cannot discover another fresh ledger or authorize a provider call. execute_local
is solely an injected callback seam; provider enforcement and Gate commit live
elsewhere. Reservations are conservative: pending/unknown consume full bounds.
No elapsed-time or process-liveness heuristic releases money or permits retry.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import re

from scripts import sermon_workflow_jobs as jobs
from scripts.sermon_review_contracts import canonical_sha256, read_snapshot, require

SCHEMA = 'sermon-review-budget-v1'
SNAPSHOT_SCHEMA = 'sermon-review-budget-snapshot-v1'
STORE_ID = canonical_sha256({'schemaVersion': SCHEMA})
METRICS = ('requests', 'inputTokens', 'outputTokens', 'wallTimeMs', 'costMicrousd')
DEFAULT_LIMITS = {'contentRevisions': 2, 'reviewAttemptsPerRevision': 2, 'decisionProposals': 1}
IDENTITY_FIELDS = ('sourceIdentitySha256', 'sourcePackageSha256', 'anchorSha256',
                   'policySha256', 'rubricSha256', 'targetLocale', 'workUnitId')
KINDS = ('initial_generation', 'review', 'content_revision', 'decision_proposal')


def _exact(value, keys, code):
    require(type(value) is dict and set(value) == set(keys), code)


def _hash(value):
    require(type(value) is str and re.fullmatch('[a-f0-9]{64}', value) is not None, 'invalid_budget_hash')
    return value


def _label(value):
    require(type(value) is str and re.fullmatch('[A-Za-z0-9_.:-]{1,100}', value) is not None,
            'invalid_budget_label')
    return value


def _amounts(value, *, positive):
    _exact(value, METRICS, 'missing_or_invalid_budget_bounds')
    require(all(type(v) is int and (0 < v if positive else 0 <= v) and v <= 10**15
                for v in value.values()), 'invalid_budget_amount')
    return deepcopy(value)


def chain_identity(value):
    """Closed, typed identity: caller metadata such as output/issue is rejected."""
    _exact(value, IDENTITY_FIELDS, 'invalid_budget_chain_identity')
    for key in IDENTITY_FIELDS[:5]: _hash(value[key])
    require(value['targetLocale'] in ('zh-Hans', 'ko', 'es'), 'invalid_budget_locale')
    unit = _label(value['workUnitId'])
    require(unit.startswith('l2.' + value['targetLocale'] + '.') and
            len(unit) > len('l2.' + value['targetLocale'] + '.'), 'invalid_budget_work_unit')
    return deepcopy(value)


def _authority(value):
    _exact(value, ('approvalSha256', 'globalBounds', 'unitBounds', 'limits'), 'invalid_budget_authority')
    _hash(value['approvalSha256'])
    _amounts(value['globalBounds'], positive=True)
    _amounts(value['unitBounds'], positive=True)
    _exact(value['limits'], DEFAULT_LIMITS, 'invalid_budget_limits')
    for key, cap in DEFAULT_LIMITS.items():
        minimum = 1 if key == 'reviewAttemptsPerRevision' else 0
        require(type(value['limits'][key]) is int and minimum <= value['limits'][key] <= cap,
                'invalid_budget_limits')
    return deepcopy(value)


def _request(identity, operation_id, kind, revision_id, revision_number, input_sha256, bounds):
    identity = chain_identity(identity)
    _label(operation_id); _label(revision_id); _hash(input_sha256)
    require(kind in KINDS, 'invalid_reservation_kind')
    require(type(revision_number) is int and 1 <= revision_number <= 3, 'invalid_revision_number')
    bounds = _amounts(bounds, positive=True)
    require(bounds['requests'] == 1, 'reservation_requires_one_request')
    return {'identity': identity, 'operationId': operation_id, 'kind': kind,
            'revisionId': revision_id, 'revisionNumber': revision_number,
            'inputSha256': input_sha256, 'bounds': bounds}


def _result(value):
    _exact(value, ('executionStatus', 'contentStatus', 'receiptSha256', 'usage'), 'invalid_budget_result')
    require(type(value['executionStatus']) is str and value['executionStatus'] in
            ('succeeded', 'failed', 'cancelled', 'outcome_unknown'), 'invalid_budget_execution_status')
    require(type(value['contentStatus']) is str and value['contentStatus'] in
            ('pass', 'fail', 'uncertain', 'not_assessed'), 'invalid_budget_content_status')
    if value['executionStatus'] != 'succeeded':
        require(value['contentStatus'] == 'not_assessed', 'execution_failure_cannot_assess_content')
    _hash(value['receiptSha256'])
    if value['executionStatus'] == 'outcome_unknown':
        require(value['usage'] is None, 'unknown_usage_must_remain_reserved')
    else:
        _amounts(value['usage'], positive=False)
        require(value['usage']['requests'] == 1, 'known_result_requires_request_usage')
    return deepcopy(value)


def _charge(row):
    result = row.get('result')
    if result is None or result['executionStatus'] == 'outcome_unknown':
        return row['request']['bounds']
    # Never return unused reservation capacity: safe even if caller underreports.
    return {key: max(row['request']['bounds'][key], result['usage'][key]) for key in METRICS}


def _sum(rows):
    return {key: sum(_charge(row)[key] for row in rows) for key in METRICS}


class BudgetStore:
    def __init__(self, root, authority):
        self.root = Path(root).resolve()
        self.authority = _authority(authority)
        self.authority_sha256 = canonical_sha256(self.authority)
        self.store_sha256 = canonical_sha256({'root': str(self.root), 'schemaVersion': SCHEMA})
        self._execution_permits = set()

    @contextmanager
    def _locked(self):
        # The constant lock serializes ALL chains; a unit-only lock overspends
        # global budgets under concurrency. Busy callers may retry admission,
        # never execution. This is not a second job scheduler.
        with jobs._lock(self.root, STORE_ID) as (folder, fd, held):
            require(held, 'budget_store_busy')
            if not folder.exists():
                folder.mkdir(mode=0o700)
                os.fsync(fd)
                jobs._sync_directory(self.root / '.locks')
                jobs._sync_directory_ancestry(self.root)
                ledger = {'schemaVersion': SCHEMA, 'authority': self.authority,
                          'storeSha256': self.store_sha256, 'reservations': {}}
                jobs._persist(folder / 'state.json', ledger)
            # An existing folder with missing/corrupt state is never reset.
            ledger, _ = read_snapshot(folder / 'state.json')
            _exact(ledger, ('schemaVersion', 'authority', 'storeSha256', 'reservations'),
                   'invalid_budget_ledger')
            require(ledger['schemaVersion'] == SCHEMA and ledger['authority'] == self.authority
                    and ledger['storeSha256'] == self.store_sha256, 'budget_authority_changed')
            require(type(ledger['reservations']) is dict, 'invalid_budget_ledger')
            for key, row in ledger['reservations'].items(): self._validate_row(key, row)
            yield folder, ledger

    def _validate_row(self, key, row):
        _hash(key)
        require(type(row) is dict and set(row) in
                ({'request', 'phase'}, {'request', 'phase', 'result'}), 'invalid_budget_reservation')
        request = row['request']
        _exact(request, ('identity', 'operationId', 'kind', 'revisionId', 'revisionNumber',
                         'inputSha256', 'bounds'), 'invalid_budget_request')
        _request(request['identity'], request['operationId'], request['kind'], request['revisionId'],
                 request['revisionNumber'], request['inputSha256'], request['bounds'])
        require(key == self._reservation_id(request), 'invalid_budget_reservation_identity')
        require(row['phase'] in ('intent', 'request', 'result'), 'invalid_budget_phase')
        require(('result' in row) == (row['phase'] == 'result'), 'invalid_budget_result_phase')
        if 'result' in row: _result(row['result'])

    def _reservation_id(self, request):
        return canonical_sha256({'chainId': canonical_sha256(request['identity']),
                                 'operationId': request['operationId']})

    @staticmethod
    def _check_serialized_size(ledger):
        from scripts.sermon_review_contracts import MAX_BYTES
        # Match the bytes jobs._persist writes, not the smaller canonical JSON.
        require(len((json.dumps(ledger, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode())
                <= MAX_BYTES, 'budget_ledger_size_limit')

    def _check_settlement_capacity(self, ledger):
        # Every pending or unknown reservation can still acquire a known result.
        # Reserve the largest permitted known-result envelope for ALL such rows,
        # including other chains, before granting any external execution. The
        # fixed-width hash and bounded metrics make this a deterministic bound;
        # requests is exactly one even when an actual result exceeds its budget.
        projected = deepcopy(ledger)
        largest = {'executionStatus': 'succeeded', 'contentStatus': 'not_assessed',
                   'receiptSha256': 'f' * 64,
                   'usage': {key: 1 if key == 'requests' else 10**15 for key in METRICS}}
        for row in projected['reservations'].values():
            if row['phase'] != 'result' or row['result']['executionStatus'] == 'outcome_unknown':
                row.update(phase='result', result=largest)
        self._check_serialized_size(projected)

    def _save(self, folder, ledger):
        # Ensure we never publish a ledger larger than our bounded reader accepts.
        self._check_serialized_size(ledger)
        jobs._persist(folder / 'state.json', ledger)

    def reserve(self, identity, *, operation_id, kind, revision_id, revision_number,
                input_sha256, bounds, locked_check=None):
        """Reserve after an optional trusted read-only guard under this same lock.

        The guard receives the store folder and a detached ledger snapshot. It
        also runs for an exact replay; it must never call a responder or re-lock
        this store. An exception denies the reservation without ledger changes.
        """
        require(locked_check is None or callable(locked_check), 'invalid_reservation_guard')
        request = _request(identity, operation_id, kind, revision_id, revision_number, input_sha256, bounds)
        rid = self._reservation_id(request)
        with self._locked() as (folder, ledger):
            rows = ledger['reservations']
            if rid in rows:
                require(rows[rid]['request'] == request, 'reservation_idempotency_conflict')
                if locked_check is not None: locked_check(folder, deepcopy(ledger))
                return self._public(rid, rows[rid], False)
            if locked_check is not None: locked_check(folder, deepcopy(ledger))
            same = [row for row in rows.values() if row['request']['identity'] == identity]
            require(not any(row['phase'] != 'result' or row['result']['executionStatus'] == 'outcome_unknown'
                            for row in same), 'budget_reconciliation_required')
            require(not any(any(_charge(row)[k] > row['request']['bounds'][k] for k in METRICS)
                            for row in rows.values()), 'budget_bound_exceeded')
            self._check_transition(request, same)
            for relevant, cap in ((list(rows.values()), self.authority['globalBounds']),
                                  (same, self.authority['unitBounds'])):
                used = _sum(relevant)
                require(all(used[k] + bounds[k] <= cap[k] for k in METRICS), 'budget_exhausted')
            rows[rid] = {'request': request, 'phase': 'intent'}
            self._check_settlement_capacity(ledger)
            self._save(folder, ledger)
            # Including ancestors is necessary even if a concurrent creator just
            # made the store parent. A failed fsync never grants execution.
            jobs._sync_directory_ancestry(folder)
            self._execution_permits.add(rid)
            return self._public(rid, rows[rid], True)

    def _check_transition(self, request, rows):
        number, revision = request['revisionNumber'], request['revisionId']
        by_number = {row['request']['revisionNumber']: row['request']['revisionId'] for row in rows}
        require(number not in by_number or by_number[number] == revision, 'revision_identity_changed')
        require(all(n == number or r != revision for n, r in by_number.items()), 'revision_identity_reused')
        highest = max(by_number, default=1)
        kind = request['kind']
        limits = self.authority['limits']
        if kind == 'initial_generation':
            require(number == 1 and not rows, 'initial_generation_already_started')
        elif kind == 'content_revision':
            require(number == highest + 1 and number <= 1 + limits['contentRevisions'], 'content_revision_limit')
            previous_reviews = [row for row in rows if row['request']['kind'] == 'review'
                                and row['request']['revisionNumber'] == highest]
            require(previous_reviews and previous_reviews[-1]['result']['executionStatus'] == 'succeeded'
                    and previous_reviews[-1]['result']['contentStatus'] in ('fail', 'uncertain'),
                    'content_revision_requires_failed_review')
        else:
            require(number == highest, 'revision_not_current')
            if number > 1:
                revisions = [row for row in rows if row['request']['kind'] == 'content_revision'
                             and row['request']['revisionNumber'] == number]
                require(revisions and revisions[-1]['result']['executionStatus'] == 'succeeded',
                        'revision_not_completed')
            if kind == 'review':
                initial = [row for row in rows if row['request']['kind'] == 'initial_generation']
                require(not initial or initial[0]['result']['executionStatus'] == 'succeeded',
                        'initial_generation_not_completed')
                attempts = [row for row in rows if row['request']['kind'] == kind
                            and row['request']['revisionNumber'] == number]
                require(len(attempts) < limits['reviewAttemptsPerRevision'], 'review_attempt_limit')
                require(not attempts or attempts[-1]['result']['executionStatus'] == 'failed',
                        'review_retry_requires_execution_failure')
            else:
                require(sum(row['request']['kind'] == kind for row in rows) < limits['decisionProposals'],
                        'decision_proposal_limit')

    @staticmethod
    def _public(rid, row, created):
        status = row['result']['executionStatus'] if 'result' in row else 'outcome_unknown'
        return {'reservationId': rid, 'created': created, 'executionAllowed': created,
                'status': status, 'phase': row['phase']}

    def mark_request(self, reservation_id):
        """Consume intent exactly once immediately before the injected callback."""
        _hash(reservation_id)
        require(reservation_id in self._execution_permits, 'request_requires_fresh_reservation')
        with self._locked() as (folder, ledger):
            row = ledger['reservations'].get(reservation_id)
            require(row is not None and row['phase'] == 'intent', 'request_already_started_or_unknown')
            self._check_settlement_capacity(ledger)
            # A busy nonblocking lock did not attempt dispatch and must preserve
            # this fresh permit. Consume before the first possibly uncertain write.
            self._execution_permits.remove(reservation_id)
            row['phase'] = 'request'
            self._save(folder, ledger)
            jobs._sync_directory_ancestry(folder)

    def record_result(self, reservation_id, result):
        """Save a sanitized receipt marker, then settle; replay is exact only."""
        return self._record(reservation_id, _result(result), reconciliation=False)

    def _record(self, rid, result, *, reconciliation):
        _hash(rid)
        with self._locked() as (folder, ledger):
            row = ledger['reservations'].get(rid)
            require(row is not None, 'unknown_budget_reservation')
            require(reconciliation or row['phase'] != 'intent', 'result_requires_started_request')
            if 'result' in row and row['result'] == result:
                return self._public(rid, row, False)
            require('result' not in row or reconciliation and
                    row['result']['executionStatus'] == 'outcome_unknown', 'conflicting_budget_result')
            marker = folder / (rid + '.result.json')
            if marker.exists():
                existing, _ = read_snapshot(marker)
                _exact(existing, ('reservationId', 'result'), 'invalid_saved_budget_result')
                require(existing['reservationId'] == rid, 'invalid_saved_budget_result')
                _result(existing['result'])
                require(existing == {'reservationId': rid, 'result': result} or reconciliation and
                        existing['result']['executionStatus'] == 'outcome_unknown', 'conflicting_saved_result')
            jobs._persist(marker, {'reservationId': rid, 'result': result})
            row.update(phase='result', result=result)
            self._save(folder, ledger)
            return self._public(rid, row, False)

    def reconcile(self, reservation_id, *, result=None, evidence_sha256=None):
        """Replay a saved marker, or explicitly attest a recovered known result.

        The trusted caller verifies external evidence. Merely waiting, losing an
        owner, or observing no response supplies no proof of execution failure.
        """
        _hash(reservation_id)
        if result is not None:
            _hash(evidence_sha256)
            result = _result(result)
            require(result['executionStatus'] != 'outcome_unknown', 'reconciliation_requires_known_result')
            require(result['receiptSha256'] == evidence_sha256, 'reconciliation_evidence_mismatch')
        else:
            with self._locked() as (folder, ledger):
                require(reservation_id in ledger['reservations'], 'unknown_budget_reservation')
                path = folder / (reservation_id + '.result.json')
                if not path.exists():
                    return self._public(reservation_id, ledger['reservations'][reservation_id], False)
                marker, _ = read_snapshot(path)
                _exact(marker, ('reservationId', 'result'), 'invalid_saved_budget_result')
                require(marker['reservationId'] == reservation_id, 'invalid_saved_budget_result')
                result = _result(marker['result'])
        return self._record(reservation_id, result, reconciliation=True)

    def snapshot(self, identity):
        identity = chain_identity(identity)
        with self._locked() as (_, ledger):
            rows = ledger['reservations']
            same = {rid: row for rid, row in rows.items() if row['request']['identity'] == identity}
            unknown = sorted(rid for rid, row in same.items() if row['phase'] != 'result'
                             or row['result']['executionStatus'] == 'outcome_unknown')
            revisions = {}
            for row in same.values():
                req = row['request']; number = str(req['revisionNumber'])
                rev = revisions.setdefault(number, {'revisionId': req['revisionId'], 'reviewAttempts': 0,
                                                    'lastReviewExecutionStatus': None, 'lastReviewContentStatus': None,
                                                    'lastReviewReceiptSha256': None})
                if req['kind'] == 'review':
                    rev['reviewAttempts'] += 1
                    rev['lastReviewExecutionStatus'] = (row.get('result') or {}).get('executionStatus', 'outcome_unknown')
                    rev['lastReviewContentStatus'] = (row.get('result') or {}).get('contentStatus', 'not_assessed')
                    rev['lastReviewReceiptSha256'] = (row.get('result') or {}).get('receiptSha256')
            highest = max((int(n) for n in revisions), default=1)
            availability = {}
            for kind in KINDS:
                if unknown:
                    availability[kind] = False
                    continue
                try:
                    # A synthetic safe label only probes transitions; never creates intent.
                    rev_id = revisions.get(str(highest), {}).get('revisionId', 'initial')
                    used_ids = {value['revisionId'] for value in revisions.values()}
                    fresh_id = next(f'snapshot-next-{n}' for n in range(len(used_ids) + 1)
                                    if f'snapshot-next-{n}' not in used_ids)
                    probe = {'kind': kind, 'revisionNumber': highest + (kind == 'content_revision'),
                             'revisionId': fresh_id if kind == 'content_revision' else rev_id}
                    self._check_transition(probe, list(same.values()))
                    availability[kind] = not unknown
                except ValueError:
                    availability[kind] = False
            used_global, used_unit = _sum(rows.values()), _sum(same.values())
            remaining = {scope: {k: max(0, self.authority[scope + 'Bounds'][k] - used[k]) for k in METRICS}
                         for scope, used in (('global', used_global), ('unit', used_unit))}
            overrun = any(any(_charge(row)[k] > row['request']['bounds'][k] for k in METRICS) for row in rows.values())
            if overrun or any(v == 0 for amounts in remaining.values() for v in amounts.values()):
                availability = dict.fromkeys(KINDS, False)
            return {'schemaVersion': SNAPSHOT_SCHEMA, 'chainId': canonical_sha256(identity),
                    'identity': identity, 'stateRevision': canonical_sha256(ledger),
                    'authoritySha256': self.authority_sha256, 'storeSha256': self.store_sha256,
                    'approvalSha256': self.authority['approvalSha256'], 'limits': deepcopy(self.authority['limits']),
                    'revisions': revisions, 'contentRevisions': sum(r['request']['kind'] == 'content_revision' for r in same.values()),
                    'decisionProposals': sum(r['request']['kind'] == 'decision_proposal' for r in same.values()),
                    'unknownReservations': unknown, 'remaining': remaining, 'availability': availability,
                    'reservations': [{'reservationId': rid, 'operationId': row['request']['operationId'],
                                      'kind': row['request']['kind'], 'revisionId': row['request']['revisionId'],
                                      'revisionNumber': row['request']['revisionNumber'],
                                      'inputSha256': row['request']['inputSha256'],
                                      'phase': row['phase'],
                                      'executionStatus': (row.get('result') or {}).get('executionStatus', 'outcome_unknown'),
                                      'receiptSha256': (row.get('result') or {}).get('receiptSha256')}
                                     for rid, row in sorted(same.items())],
                    'boundExceeded': overrun, 'executionAuthority': 'none'}

    def execute_local(self, identity, *, callback, **request):
        """Developer seam, not a provider adapter or external exactly-once claim."""
        reservation = self.reserve(identity, **request)
        if not reservation['created']:
            return reservation
        rid = reservation['reservationId']
        self.mark_request(rid)
        # Exceptions/termination intentionally preserve request + full reservation.
        result = callback(deepcopy(reservation))
        return self.record_result(rid, result)
