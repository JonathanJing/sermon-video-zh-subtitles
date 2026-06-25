#!/usr/bin/env python3
"""Run delayed stable correction for an active realtime caption session."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any, Callable

from stabilize_realtime_deltas_with_openai import (
    DEFAULT_MODEL,
    access_secret,
    batched,
    build_output,
    post_stable_corrections,
    read_jsonl,
    stable_correction_candidates,
    stabilize_batch,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = Path("artifacts/realtime-stable-corrections")


def main() -> int:
    args = parse_args()
    api_key = access_secret(args.api_key_secret)
    iterations = 0
    while True:
        report = run_iteration(args, api_key=api_key)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        iterations += 1
        if args.once or (args.max_iterations and iterations >= args.max_iterations):
            return 0
        time.sleep(args.interval_seconds)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Continuously stabilize saved realtime deltas with gpt-5.5-mini and post corrections."
    )
    parser.add_argument("--input-jsonl", type=Path, required=True, help="Realtime event JSONL file.")
    parser.add_argument("--api-key-secret", required=True, help="Secret Manager resource for the OpenAI API key.")
    parser.add_argument("--backend-url", required=True, help="Backend base URL.")
    parser.add_argument("--session-id", required=True, help="Realtime session id.")
    parser.add_argument("--event-token", required=True, help="Realtime event token.")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--max-windows", type=int, default=20)
    parser.add_argument("--min-age-seconds", type=float, default=4.0)
    parser.add_argument("--interval-seconds", type=float, default=6.0)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--max-iterations", type=int, default=0)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--state-file", type=Path)
    args = parser.parse_args()
    args.input_jsonl = resolve_repo_path(args.input_jsonl)
    args.out_dir = resolve_repo_path(args.out_dir)
    args.state_file = resolve_repo_path(args.state_file or (args.out_dir / f"{args.session_id}.stabilizer-state.json"))
    if args.batch_size < 1:
        raise SystemExit("--batch-size must be >= 1")
    if args.max_windows < 1:
        raise SystemExit("--max-windows must be >= 1")
    if args.interval_seconds <= 0:
        raise SystemExit("--interval-seconds must be > 0")
    if args.min_age_seconds < 0:
        raise SystemExit("--min-age-seconds must be >= 0")
    return args


def run_iteration(
    args: argparse.Namespace,
    *,
    api_key: str,
    now: datetime | None = None,
    stabilize_fn: Callable[[list[dict[str, Any]], str, str], list[dict[str, Any]]] | None = None,
    post_fn: Callable[..., int] | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    state = read_state(args.state_file)
    events = read_jsonl(args.input_jsonl)
    all_candidates = stable_correction_candidates(events, max_windows=args.max_windows)
    candidates = filter_ready_candidates(
        all_candidates,
        posted_ids=set(state.get("postedSegmentIds") or []),
        min_age_seconds=args.min_age_seconds,
        now=now,
    )
    corrections: list[dict[str, Any]] = []
    stabilize = stabilize_fn or (lambda batch, key, model: stabilize_batch(batch, api_key=key, model=model))
    for batch in batched(candidates, args.batch_size):
        corrections.extend(stabilize(batch, api_key, args.model))

    output = build_output(
        input_jsonl=args.input_jsonl,
        model=args.model,
        candidates=candidates,
        corrections=corrections,
        api_key_secret=args.api_key_secret,
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.out_dir / f"{args.session_id}.stable-corrections.latest.json"
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    post = post_fn or post_stable_corrections
    posted = 0
    if corrections:
        posted = post(
            output=output,
            backend_url=args.backend_url,
            session_id=args.session_id,
            event_token=args.event_token,
            model=args.model,
        )
    if posted:
        posted_ids = set(state.get("postedSegmentIds") or [])
        posted_ids.update(item["id"] for item in corrections)
        state = {
            "schemaVersion": 1,
            "sessionId": args.session_id,
            "model": args.model,
            "updatedAt": now.isoformat(),
            "postedSegmentIds": sorted(posted_ids),
        }
        write_state(args.state_file, state)

    return {
        "schemaVersion": 1,
        "status": "ok",
        "sessionId": args.session_id,
        "model": args.model,
        "candidateWindows": len(all_candidates),
        "readyWindows": len(candidates),
        "correctedWindows": len(corrections),
        "postedStableCorrections": posted,
        "stateFile": safe_display_path(args.state_file),
        "out": safe_display_path(output_path),
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }


def filter_ready_candidates(
    candidates: list[dict[str, Any]],
    *,
    posted_ids: set[str],
    min_age_seconds: float,
    now: datetime,
) -> list[dict[str, Any]]:
    ready = []
    for candidate in candidates:
        candidate_id = str(candidate.get("id") or "")
        if not candidate_id or candidate_id in posted_ids:
            continue
        created_at = parse_datetime(candidate.get("createdAt"))
        if created_at and (now - created_at).total_seconds() < min_age_seconds:
            continue
        ready.append(candidate)
    return ready


def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def read_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"schemaVersion": 1, "postedSegmentIds": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"schemaVersion": 1, "postedSegmentIds": []}
    return data if isinstance(data, dict) else {"schemaVersion": 1, "postedSegmentIds": []}


def write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def safe_display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.name


if __name__ == "__main__":
    raise SystemExit(main())
