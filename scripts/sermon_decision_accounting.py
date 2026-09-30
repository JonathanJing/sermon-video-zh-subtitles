"""Bounded, hash-only decision observations in the existing accounting ledger.

No SDK, credentials, responder, retry or dispatch authority lives here. Existing
v3 log records carry a versioned field envelope; older readers can ignore it.
"""
from contextlib import contextmanager
import json
import time
import uuid

from scripts import sermon_accounting as accounting
from scripts.sermon_workflow_jobs import _digest

SCHEMA = 'sermon-decision-observation-v1'
CODE = 'decision_observation'
TIMINGS = frozenset({'statePacketBuildMs', 'packetValidationMs', 'reservationMs',
                    'modelLatencyMs', 'decisionValidationMs', 'stateCommitMs', 'decisionWallSeconds'})
STATUSES = frozenset({'proposal_requires_locked_admission', 'decision_rejected',
                     'decision_outcome_unknown', 'decision_budget_unavailable',
                     'commit_recorded', 'commit_failed'})
ACTIONS = frozenset({'open_text_revision', 'open_audio_revision', 'request_human_review', 'escalate_engineering'})
FIELDS = frozenset({'schemaVersion', 'observationId', 'phase', 'productionRunId', 'decisionId', 'stateRevision',
                    'statePacketSha256', 'statePacketBytes', 'evidenceRefCount', 'allowedActionCount',
                    'parentContextInherited', 'status', 'selectedAction', 'timings'})


def safe_observation(fields):
    """Reconstruct a strict envelope; reject corrupt or unbounded read-side data."""
    if not isinstance(fields, dict) or set(fields) != FIELDS or fields.get('schemaVersion') != SCHEMA:
        raise ValueError('invalid_decision_observation')
    for key in ('productionRunId', 'decisionId', 'stateRevision', 'statePacketSha256'):
        value = fields[key]
        if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
            raise ValueError('invalid_decision_observation_identity')
    if (accounting._label(fields['observationId'], None) is None
            or fields['phase'] not in {'turn', 'commit'} or fields['status'] not in STATUSES
            or fields['parentContextInherited'] is not False
            or (fields['selectedAction'] is not None and fields['selectedAction'] not in ACTIONS)):
        raise ValueError('invalid_decision_observation_policy')
    for key, upper in (('statePacketBytes', 32768), ('evidenceRefCount', 16), ('allowedActionCount', 4)):
        if type(fields[key]) is not int or not 1 <= fields[key] <= upper:
            raise ValueError('invalid_decision_observation_count')
    if ((fields['phase'] == 'commit') != fields['status'].startswith('commit_')
            or ((fields['selectedAction'] is not None) != (fields['status'] == 'proposal_requires_locked_admission'))):
        raise ValueError('invalid_decision_observation_phase')
    timings = fields['timings']
    if not isinstance(timings, dict) or set(timings) != TIMINGS:
        raise ValueError('invalid_decision_observation_timings')
    if any(value is not None and accounting._number(value) is None for value in timings.values()):
        raise ValueError('invalid_decision_observation_timings')
    return {**{key: fields[key] for key in FIELDS if key != 'timings'}, 'timings': dict(timings)}


class Observation:
    def __init__(self, packet, *, phase='turn', observation_id=None, depends_on=None):
        self.began = time.monotonic()
        self.last_span = None
        self.depends_on = depends_on
        self.fields = dict(schemaVersion=SCHEMA, observationId=observation_id or uuid.uuid4().hex,
            phase=phase, productionRunId=packet['productionRunId'], decisionId=packet['decisionId'], stateRevision=packet['stateRevision'],
            statePacketSha256=_digest(packet),
            statePacketBytes=len(json.dumps(packet, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()),
            evidenceRefCount=len(packet['evidenceRefs']), allowedActionCount=len(packet['allowedActions']),
            parentContextInherited=False, status='commit_failed' if phase == 'commit' else 'decision_outcome_unknown', selectedAction=None,
            timings={key: None for key in TIMINGS})
        safe_observation(self.fields)

    @contextmanager
    def measure(self, metric, *, executor='deterministic_program'):
        if metric not in TIMINGS - {'statePacketBuildMs', 'decisionWallSeconds'}:
            raise ValueError('invalid_decision_metric')
        with accounting.stage('decision.' + metric, executor_type=executor,
                              billing='api' if executor == 'decision_agent' else 'local',
                              work_unit_id='decision', decision_id=self.fields['decisionId'],
                              depends_on=[self.last_span] if self.last_span else self.depends_on) as span:
            self.last_span = span
            began = time.monotonic()
            try:
                yield
            finally:
                self.fields['timings'][metric] = round((time.monotonic() - began) * 1000, 6)

    def finish(self, status, *, selected_action=None):
        self.fields['status'] = status
        self.fields['selectedAction'] = selected_action
        self.fields['timings']['decisionWallSeconds'] = round(time.monotonic() - self.began, 6)
        fields = safe_observation(self.fields)
        accounting._emit({'event': 'log', 'code': CODE, 'level': 'INFO', 'fields': fields})
        return fields
