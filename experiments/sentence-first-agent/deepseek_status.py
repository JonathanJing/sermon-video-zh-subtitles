#!/usr/bin/env python3
"""Watch a DeepSeek stage: live state.json plus the last events from events.jsonl.

Written by coherence_core.DeepSeek (translate / audit / trim all share it), so a long
window pass is observable without reading the cache or waiting for the final JSON.

  python3 $EXP/deepseek_status.py --run $RUN/coherence-D
  python3 $EXP/deepseek_status.py --run $RUN --watch 2
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


def read_state(run: Path) -> dict:
    path = run / "state.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def read_events(run: Path, limit: int) -> list[dict]:
    path = run / "events.jsonl"
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines[-limit:] if line.strip()]


def cost(event: dict) -> float:
    return (0.3 * int(event.get("promptTokens") or 0)
            + 1.2 * int(event.get("completionTokens") or 0)) / 1_000_000


def render(run: Path, tail: int) -> str:
    state = read_state(run)
    if not state:
        return f"{run}: no state.json yet (stage has not started)"
    total = state.get("total") or 0
    done = state.get("done") or 0
    share = f"{done}/{total} ({done * 100 // total}%)" if total else str(done)
    eta = ""
    if total and state.get("avgSeconds") and done:
        eta = f"  eta≈{max(0, total - done) * state['avgSeconds']:.0f}s"
    rows = [f"{state.get('label')}  {state.get('model')}/{state.get('effort')}  {state.get('status')}"
            f"  {share}{eta}",
            f"units {state.get('unitsDone')}  calls {state.get('calls')}  hits {state.get('hits')}"
            f"  failed {state.get('failed')}  validation {state.get('validationFailures')}"
            f"  ${state.get('costUsd')}  elapsed {state.get('elapsedSeconds')}s"
            f"  avg {state.get('avgSeconds')}s/call"]
    if state.get("lastError"):
        rows.append(f"last error: {state['lastError']}")
    if state.get("summary"):
        rows.append(f"summary: {json.dumps(state['summary'], ensure_ascii=False)}")
    events = read_events(run, tail)
    if events:
        rows.append("")
        rows.append("recent events:")
        for event in events:
            detail = event.get("error") or ""
            if event.get("status") == "ok":
                detail = f"{event.get('promptTokens')}+{event.get('completionTokens')} tok  ${cost(event):.4f}"
            context = (event.get("context") or "")[:24]
            rows.append(f"  {event.get('ts', '')[11:23]}  {event.get('status'):5s}"
                        f"  {event.get('latencyMs', 0):7.0f} ms  {context:24s}  {detail}")
    return "\n".join(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True, help="directory holding state.json/events.jsonl")
    parser.add_argument("--tail", type=int, default=8)
    parser.add_argument("--watch", type=float, default=0.0, help="refresh every N seconds")
    args = parser.parse_args()
    if not args.watch:
        print(render(args.run, args.tail))
        return 0
    while True:
        print("\033[2J\033[H" + render(args.run, args.tail), flush=True)
        time.sleep(args.watch)


if __name__ == "__main__":
    raise SystemExit(main())
