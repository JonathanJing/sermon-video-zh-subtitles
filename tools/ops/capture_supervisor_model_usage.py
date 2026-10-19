"""Capture content-free supervision usage from a live Codex exec JSONL pipe.

Codex turn durations include tools/queueing and are session throughput, never
decode TPS. Normalized observations from future hosts can also be imported.
This collector neither launches models nor stores prompts/tool output.
"""
from __future__ import annotations
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import sermon_accounting as accounting
from scripts import sermon_model_call_observation as observations


def capture_codex(lines, model, *, service_tier=None):
    """Receiver-observed turn intervals; requires a live stream, not file replay."""
    stack, receipt = None, None
    completed, failed = 0, 0
    try:
        for line in lines:
            try:
                row = json.loads(line)
            except (ValueError, TypeError):
                raise ValueError('invalid_monitor_json_line') from None
            if not isinstance(row, dict):
                raise ValueError('invalid_monitor_event')
            kind = row.get('type')
            if kind == 'turn.started':
                if stack is not None:
                    raise ValueError('overlapping_monitor_turns')
                stack = ExitStack()
                receipt = stack.enter_context(observations.invocation(model, backend='agent_session',
                    provider='codex', role='supervisor', timing_scope='agent_session_including_tools',
                    usage_source='host_telemetry', service_tier=service_tier))
            elif kind in {'turn.completed', 'turn.failed'}:
                if stack is None:
                    raise ValueError('monitor_turn_start_not_observed')
                receipt['usage'] = row.get('usage')
                active, stack = stack, None
                if kind == 'turn.failed':
                    error = RuntimeError('monitor_turn_failed')
                    active.__exit__(RuntimeError, error, None)
                    failed += 1
                else:
                    active.close()
                    completed += 1
                receipt = None
            # Ignore item/command/text/error bodies entirely; never persist them.
        if stack is not None:
            raise InterruptedError('monitor_turn_finish_not_observed')
    except BaseException as exc:
        if stack is not None:
            stack.__exit__(type(exc), exc, exc.__traceback__)
        raise
    return {'status': 'needs_attention' if failed else 'captured', 'completedTurns': completed, 'failedTurns': failed,
            'timingEvidence': 'receiver_monotonic_live_stream', 'generationTokensPerSecond': None}


def import_observations(lines):
    """Versioned host observations retain original measurement times/identities."""
    count = 0
    for line in lines:
        try:
            fields = observations.safe_observation(json.loads(line))
        except (ValueError, TypeError):
            raise ValueError('invalid_monitor_observation') from None
        observations._emit(fields)
        count += 1
    return {'status': 'imported', 'observations': count}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--accounting-dir', required=True, type=Path)
    parser.add_argument('--format', choices=('codex-exec-live', 'observations'), required=True)
    parser.add_argument('--model', help='Configured Codex model identity (host may not report actual model)')
    parser.add_argument('--service-tier', choices=('default', 'fast', 'ultrafast'),
                        help='Explicit configured Codex tier for credit estimates; omitted remains unknown')
    parser.add_argument('--live', action='store_true', help='Assert stdin is a live model stream; never use on a saved file')
    args = parser.parse_args()
    if args.format == 'codex-exec-live' and (not args.live or not args.model):
        parser.error('Codex capture requires --live and --model; saved logs need original timestamp observations')
    with accounting.accounting_session(args.accounting_dir, 'supervisor_usage_capture'):
        result = capture_codex(sys.stdin, args.model, service_tier=args.service_tier) if args.format == 'codex-exec-live' else import_observations(sys.stdin)
    print(json.dumps(result))
    return 1 if result['status'] == 'needs_attention' else 0


if __name__ == '__main__':
    raise SystemExit(main())
