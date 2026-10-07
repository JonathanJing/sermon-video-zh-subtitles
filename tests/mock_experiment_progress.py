"""Non-authoritative, bounded progress for the local synthetic experiment only."""
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

EVENTS = {'preflight_started', 'preflight_finished', 'invocation_started',
          'invocation_finished', 'scenario_verified'}
SCENARIOS = {'happy', 'failure', 'timeout'}
STATUSES = {'completed', 'failed', 'passed', 'synthetic_complete', 'incomplete'}


def emit_progress(event, *, scenario, invocation=None, status=None, wall_seconds=None):
    if event not in EVENTS or scenario not in SCENARIOS:
        raise ValueError('invalid_experiment_progress')
    if invocation is not None and (type(invocation) is not int or invocation not in (1, 2)):
        raise ValueError('invalid_experiment_invocation')
    if status is not None and status not in STATUSES:
        raise ValueError('invalid_experiment_status')
    if wall_seconds is not None and (not isinstance(wall_seconds, (int, float))
            or not math.isfinite(wall_seconds) or wall_seconds < 0):
        raise ValueError('invalid_experiment_timing')
    destination = os.environ.get('SERMON_MOCK_EXPERIMENT_PROGRESS_FILE')
    if not destination:
        return
    record = {'schemaVersion': 'mock-experiment-progress-v1', 'event': event,
              'scenario': scenario, 'observedAt': datetime.now(timezone.utc).isoformat(),
              'scope': 'diagnostic_only_not_completion_evidence'}
    record.update({key: value for key, value in {'invocation': invocation,
        'status': status, 'wallSeconds': wall_seconds}.items() if value is not None})
    path = Path(destination)
    # Runner owns a new output directory. Never follow a substituted link.
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'a') as stream:
        stream.write(json.dumps(record, sort_keys=True)+'\n')
