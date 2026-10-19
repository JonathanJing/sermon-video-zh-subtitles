#!/usr/bin/env python3
"""Measure output tokens/s for a model through Codex CLI, default vs fast tier.

Counterpart of measure_openai_model_tps.py for the ChatGPT-authenticated CLI
route. It reuses the same model, reasoning effort, tiers and user prompt, and
runs the same interleaved round order. The CLI never receives an API key: every
OPENAI_* variable and CODEX_API_KEY is removed from the child environment, as in
codex_layer2_transport.py.

  python3 scripts/measure_codex_cli_tps.py --rounds 3

Limits of the CLI route, all recorded in the output:
- `codex exec --json` emits whole messages, not token deltas, so no first-token
  or pure generation time exists. Rates are end-to-end session rates:
  output tokens / process wall time and / turn wall time (turn.started to
  turn.completed as the stream delivers them).
- Each call carries Codex's own system context (input tokens are reported), so
  its input differs from the raw API probe even though the user prompt is identical.
- The CLI cannot apply an output-token cap, so completion length is not fixed.
- The response does not report the applied service tier; only the requested tier is stored.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.measure_openai_model_tps import PROMPT, TIERS  # noqa: E402

DEFAULT_CLI = Path.home() / ".local" / "bin" / "codex"
SCHEMA_VERSION = "codex-cli-model-tps-v1"


def cli_environment(inherited=None):
    """Child environment with no API credential, mirroring codex_layer2_transport."""
    source = os.environ if inherited is None else inherited
    return {key: value for key, value in source.items()
            if not key.startswith("OPENAI_") and key != "CODEX_API_KEY"}


def build_command(cli, model, tier, reasoning_effort):
    command = [str(cli), "exec", "--ignore-user-config", "--ephemeral",
               "-m", model, "-c", f'service_tier="{tier}"',
               "-c", f'model_reasoning_effort="{reasoning_effort}"',
               "--json", "-s", "read-only", "--skip-git-repo-check", "-"]
    if tier == "fast":
        command += ["--enable", "fast_mode"]  # Same placement as codex_layer2_transport.py.
    return command


def parse_events(timed_rows):
    """Pure parser. timed_rows: list of (seconds_since_start, event_dict)."""
    turn_start = turn_end = first_message = None
    usage = None
    item_types = []
    failed = False
    for when, row in timed_rows:
        kind = row.get("type")
        if kind == "turn.started" and turn_start is None:
            turn_start = when
        elif kind == "item.completed":
            item = row.get("item") or {}
            item_types.append(item.get("type"))
            if item.get("type") == "agent_message" and first_message is None:
                first_message = when
        elif kind == "turn.completed":
            turn_end = when
            usage = row.get("usage")
        elif kind in {"turn.failed", "error"}:
            failed = True
    tools = [t for t in item_types if t not in {None, "agent_message", "reasoning"}]
    return {"turnS": round(turn_end - turn_start, 4) if turn_start is not None and turn_end is not None else None,
            "firstMessageS": round(first_message, 4) if first_message is not None else None,
            "usage": usage, "toolItems": len(tools), "turnFailed": failed,
            "completed": turn_end is not None}


def rates(usage, wall_s, turn_s):
    out = {"inputTokens": None, "cachedInputTokens": None, "outputTokens": None,
           "reasoningTokens": None, "outputTpsWall": None, "outputTpsTurn": None}
    if usage:
        out.update(inputTokens=usage.get("input_tokens"),
                   cachedInputTokens=usage.get("cached_input_tokens"),
                   outputTokens=usage.get("output_tokens"),
                   reasoningTokens=usage.get("reasoning_output_tokens"))
        output = usage.get("output_tokens")
        if isinstance(output, int) and wall_s > 0:
            out["outputTpsWall"] = round(output / wall_s, 2)
        if isinstance(output, int) and turn_s and turn_s > 0:
            out["outputTpsTurn"] = round(output / turn_s, 2)
    return out


def run_once(cli, model, tier, reasoning_effort, timeout):
    command = build_command(cli, model, tier, reasoning_effort)
    record = {"outcome": "ok", "exitCode": None, "requestedTier": tier}
    with tempfile.TemporaryFile(mode="w+") as stderr, tempfile.TemporaryDirectory(prefix="tongxing-codex-tps-") as work:
        start = time.perf_counter()
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=stderr, cwd=work, env=cli_environment(), text=True)
        process.stdin.write(PROMPT)
        process.stdin.close()
        timed_rows = []
        try:
            for line in process.stdout:
                if not line.strip():
                    continue
                try:
                    timed_rows.append((time.perf_counter() - start, json.loads(line)))
                except ValueError:
                    timed_rows.append((time.perf_counter() - start, {"type": "unparsed"}))
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            record["outcome"] = "unknown_timeout"
        wall_s = time.perf_counter() - start
        stderr.seek(0)
        record["stderrLines"] = len(stderr.read().splitlines())
    record["exitCode"] = process.returncode
    parsed = parse_events(timed_rows)
    if record["outcome"] == "ok" and (process.returncode != 0 or parsed["turnFailed"] or not parsed["completed"]):
        record["outcome"] = "failed"
    if parsed["toolItems"]:
        record["outcome"] = "used_tools"
    record.update(wallS=round(wall_s, 4), turnS=parsed["turnS"], firstMessageS=parsed["firstMessageS"],
                  toolItems=parsed["toolItems"])
    record.update(rates(parsed["usage"], wall_s, parsed["turnS"]))
    return record


def median_or_none(values):
    values = [v for v in values if v is not None]
    return round(statistics.median(values), 2) if values else None


def summarize(results, tiers):
    summary = {}
    for tier in tiers:
        rows = [r for r in results if r["requestedTier"] == tier]
        ok = [r for r in rows if r["outcome"] == "ok" and r["outputTokens"]]
        summary[tier] = {
            "requested": len(rows), "ok": len(ok), "notOk": len(rows) - len(ok),
            "medianWallS": median_or_none([r["wallS"] for r in ok]),
            "medianTurnS": median_or_none([r["turnS"] for r in ok]),
            "medianFirstMessageS": median_or_none([r["firstMessageS"] for r in ok]),
            "medianOutputTokens": median_or_none([r["outputTokens"] for r in ok]),
            "medianReasoningTokens": median_or_none([r["reasoningTokens"] for r in ok]),
            "medianInputTokens": median_or_none([r["inputTokens"] for r in ok]),
            "medianOutputTpsWall": median_or_none([r["outputTpsWall"] for r in ok]),
            "medianOutputTpsTurn": median_or_none([r["outputTpsTurn"] for r in ok]),
            "minOutputTpsWall": min((r["outputTpsWall"] for r in ok if r["outputTpsWall"] is not None), default=None),
            "maxOutputTpsWall": max((r["outputTpsWall"] for r in ok if r["outputTpsWall"] is not None), default=None),
        }
    return summary


def print_summary(summary, model):
    print(f"\nCodex CLI {model}: output tokens/s (median over successful calls)")
    print(f"{'tier':<9}{'ok/req':>8}{'wall s':>9}{'turn s':>9}{'out tok':>9}{'reason':>8}"
          f"{'input':>9}{'wall t/s':>10}{'turn t/s':>10}{'wall min':>10}{'wall max':>10}")
    for tier, row in summary.items():
        print(f"{tier:<9}{str(row['ok']) + '/' + str(row['requested']):>8}"
              f"{str(row['medianWallS']):>9}{str(row['medianTurnS']):>9}"
              f"{str(row['medianOutputTokens']):>9}{str(row['medianReasoningTokens']):>8}"
              f"{str(row['medianInputTokens']):>9}{str(row['medianOutputTpsWall']):>10}"
              f"{str(row['medianOutputTpsTurn']):>10}{str(row['minOutputTpsWall']):>10}"
              f"{str(row['maxOutputTpsWall']):>10}")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cli", type=Path, default=DEFAULT_CLI)
    parser.add_argument("--model", default="gpt-6-luna")
    parser.add_argument("--reasoning-effort", default="medium", choices=("low", "medium", "high"))
    parser.add_argument("--tiers", nargs="+", default=list(TIERS), choices=TIERS)
    parser.add_argument("--rounds", type=int, default=3, help="Calls per tier, 1-5.")
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--out", type=Path,
                        default=REPO_ROOT / "artifacts" / "codex-cli-tps" / "summary.json")
    args = parser.parse_args(argv)
    if not 1 <= args.rounds <= 5:
        parser.error("--rounds must be between 1 and 5")
    return args


def main(argv=None):
    args = parse_args(argv)
    if not args.cli.exists():
        print(f"codex_cli_missing: {args.cli}", file=sys.stderr)
        return 2
    results = []
    for round_index in range(args.rounds):
        order = list(args.tiers) if round_index % 2 == 0 else list(reversed(args.tiers))
        for tier in order:
            record = run_once(args.cli, args.model, tier, args.reasoning_effort, args.timeout)
            record["round"] = round_index + 1
            results.append(record)
            print(f"round {round_index + 1} {tier:<8} {record['outcome']:<12} "
                  f"out={record['outputTokens']} wall_s={record['wallS']} "
                  f"turn_tps={record['outputTpsTurn']}", flush=True)
    summary = summarize(results, args.tiers)
    report = {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "cli": str(args.cli),
        "model": args.model,
        "reasoningEffort": args.reasoning_effort,
        "promptChars": len(PROMPT),
        "rounds": args.rounds,
        "results": results,
        "summary": summary,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print_summary(summary, args.model)
    print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
