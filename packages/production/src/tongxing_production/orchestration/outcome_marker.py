"""Single end-of-run marker shared by long local producers.

Writes `outcome.json` once a run finishes, on both the success and the failure
path, so a waiter does not have to infer completion from absent result files.
The marker records the outcome only; it never changes the run's own state.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

SCHEMA = 'sermon-run-outcome-v1'


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_outcome(path: Path, *, command: str, status: str, exit_code: int, started_at: str,
                  error: BaseException | None = None) -> dict[str, Any]:
    """Atomically write the marker. An existing marker is replaced by a newer finish."""
    record: dict[str, Any] = {'schemaVersion': SCHEMA, 'command': command, 'status': status,
                              'exitCode': exit_code, 'startedAt': started_at, 'endedAt': _now()}
    if error is not None:
        record['error'] = {'type': type(error).__name__, 'message': str(error)[:500]}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(temporary, path)
    return record


def run_with_outcome(path: Path, command: str, function: Callable[[], Any]) -> Any:
    """Run `function`, record its outcome, and re-raise any failure unchanged."""
    started_at = _now()
    try:
        result = function()
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
        write_outcome(path, command=command, status='succeeded' if code == 0 else 'failed',
                      exit_code=code, started_at=started_at)
        raise
    except BaseException as exc:
        write_outcome(path, command=command, status='failed', exit_code=1,
                      started_at=started_at, error=exc)
        raise
    write_outcome(path, command=command, status='succeeded', exit_code=0, started_at=started_at)
    return result
