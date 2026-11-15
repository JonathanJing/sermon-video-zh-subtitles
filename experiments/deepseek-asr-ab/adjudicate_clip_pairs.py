#!/usr/bin/env python3
"""Blind audio adjudication for the DeepSeek ASR vs OpenAI A/B.

The frozen 60-clip reference set was produced by GPT-Transcribe, so scoring an
OpenAI arm against it measures self-consistency as much as accuracy. This script
gives an independent audio-capable model (Gemini) the clip audio plus both
transcripts, labelled X and Y with no hint of which provider produced which text.
It asks which transcript is closer to what was actually said, ignoring
capitalization, punctuation and formatting.

Every clip is judged twice, once with each arm in the X slot, so label-order
effects are visible instead of being scored as decisions. This is machine
adjudication, not human Gold.
"""
from __future__ import annotations

import argparse
import base64
import concurrent.futures
import hashlib
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

JUDGE_MODEL = "gemini-3.8-flash"
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
COST_NOTE = {"priceBasis": "Google AI Studio tier at time of run; not invoiced", "invoiceVerified": False}
GENERATION_CONFIG = {
    "responseMimeType": "application/json",
    "maxOutputTokens": 1024,
    "temperature": 0,
    "thinkingConfig": {"thinkingLevel": "LOW"},
}

RUBRIC = """You are an independent transcription adjudicator for English church-service audio.

Listen to the audio. Two transcripts of the same clip are given, X and Y. Choose the transcript that is
closer to what the audio actually says.

Rules:
- Ignore capitalization, punctuation, hyphenation, spacing and number formatting.
- Treat a missing or added filler word ("oh", "uh", "you know") as a trivial difference.
- Weight scripture references, Bible names, personal names, ministry names, numbers and negations heavily,
  because those change the meaning.
- If one transcript invents speech that is not in the audio, or omits a whole phrase of real speech, that
  is a real error.
- If both are equally faithful, or both are wrong in the same way, answer "tie".
- Never answer based on which text looks more polished; only the audio matters.

Answer with the JSON object only. Do not write analysis, preamble, Markdown or LaTeX before or after it.
Return JSON only, with this exact shape:
{"verdict": "X" | "Y" | "tie", "confidence": "high" | "medium" | "low",
 "x_error": null | "short description of X's real error",
 "y_error": null | "short description of Y's real error",
 "reason": "one sentence, at most 25 words"}"""


RUBRIC_V2 = """You are an independent transcription adjudicator for English church-service audio.

Listen to the audio, then decide which transcript, X or Y, is more faithful to what the audio actually says.

Scoring rules, in priority order:
1. Meaning-bearing content: scripture references, Bible book and character names, personal and ministry names,
   numbers, negations, and any word that changes what the sentence means. An error here decides the verdict.
2. Whole-phrase omissions or invented speech: if one transcript drops a phrase of real speech, or writes
   words nobody said, that transcript is worse.
3. Everything else is noise: do NOT reward or punish capitalization, punctuation, spelling of a name that is
   still recognisable, repeated words, stutters, false starts ("it's a it's a psalm"), or filler. If the two
   transcripts differ only in those, the verdict is "tie" even when one is longer.
4. Do not use outside knowledge. Do not infer lyrics from knowing the song, or scripture wording from knowing
   the translation. If you cannot hear a passage clearly, do not guess; judge the rest of the clip.
5. If both transcripts carry the same meaning and the same real errors, the verdict is "tie".

Before the verdict, quote the exact audio words that decide it.
Answer with the JSON object only. No preamble, Markdown or LaTeX.

{"verdict": "X" | "Y" | "tie", "confidence": "high" | "medium" | "low",
 "decision_quote": "the exact words you heard that decide the verdict",
 "x_error": null | "X's decisive error",
 "y_error": null | "Y's decisive error",
 "reason": "one sentence, at most 25 words"}"""

RUBRICS = {"v1": RUBRIC, "v2": RUBRIC_V2}


def google_key() -> str:
    """Same credential resolution as the repository's Gemini supervisor transport."""
    value = os.environ.get("GOOGLE_API_KEY", "").strip()
    if value:
        return value
    path = REPO_ROOT / ".env"
    if path.is_file():
        for line in path.read_text().splitlines():
            if line.startswith("GOOGLE_API_KEY="):
                candidate = line.split("=", 1)[1].strip().strip("\"'")
                if candidate:
                    return candidate
    raise SystemExit("GOOGLE_API_KEY missing")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build_prompt(text_x: str, text_y: str, rubric: str = "v1") -> str:
    return (
        RUBRICS[rubric]
        + "\n\nTranscript X:\n"
        + (text_x.strip() or "[no speech reported]")
        + "\n\nTranscript Y:\n"
        + (text_y.strip() or "[no speech reported]")
    )


def call_judge(api_key: str, prompt: str, audio_b64: str, generation_config: dict[str, Any],
               timeout: int = 180) -> dict[str, Any]:
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": "audio/wav", "data": audio_b64}},
                ],
            }
        ],
        "generationConfig": generation_config,
    }
    attempts = []
    for attempt in range(3):
        request = urllib.request.Request(
            ENDPOINT.format(model=JUDGE_MODEL),
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
            method="POST",
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read().decode()
            latency = time.perf_counter() - started
            attempts.append({"httpStatus": 200, "latencySeconds": round(latency, 3)})
            return {"ok": True, "latency": latency, "attempts": attempts, "body": body}
        except urllib.error.HTTPError as exc:
            latency = time.perf_counter() - started
            text = exc.read().decode(errors="replace")
            attempts.append({"httpStatus": exc.code, "latencySeconds": round(latency, 3), "body": text[:600]})
            if exc.code in (429, 500, 503) and attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            return {"ok": False, "latency": latency, "attempts": attempts, "body": text}
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            latency = time.perf_counter() - started
            attempts.append({"error": str(exc), "latencySeconds": round(latency, 3)})
            if attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            return {"ok": False, "latency": latency, "attempts": attempts, "body": str(exc)}
    raise AssertionError("unreachable")


def extract_text(body: str) -> str:
    value = json.loads(body)
    parts = value["candidates"][0]["content"]["parts"]
    return "".join(part.get("text", "") for part in parts)


def first_json_object(text: str) -> dict[str, Any] | None:
    """Return the first JSON object carrying a verdict, skipping any prose the judge wrote first."""
    decoder = json.JSONDecoder()
    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("verdict") in ("X", "Y", "tie"):
            return value
    return None


def parse_outcome(outcome: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    if not outcome["ok"]:
        return None, ""
    try:
        text = extract_text(outcome["body"])
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        return None, ""
    value = first_json_object(text)
    if value is None:
        try:
            candidate = json.loads(text)
        except json.JSONDecodeError:
            return None, text
        value = candidate if isinstance(candidate, dict) else None
    return value, text


def judge_one(job: dict[str, Any], *, api_key: str, raw_dir: Path) -> dict[str, Any]:
    item_id = job["id"]
    x_arm, y_arm = job["xArm"], job["yArm"]
    prompt = build_prompt(job["textX"], job["textY"], job["rubric"])
    prompt_sha = sha256_bytes(prompt.encode())
    identity = {
        "schemaVersion": "deepseek-asr-ab-adjudication-v1",
        "judgeModel": JUDGE_MODEL,
        "itemId": item_id,
        "xArm": x_arm,
        "yArm": y_arm,
        "labelToArm": {"X": x_arm, "Y": y_arm},
        "textSha256": {"X": sha256_bytes(job["textX"].encode()), "Y": sha256_bytes(job["textY"].encode())},
        "promptSha256": prompt_sha,
        "audioSha256": job["audioSha256"],
        "generationConfigSha256": sha256_bytes(json.dumps(job["generationConfig"], sort_keys=True).encode()),
        "rubric": job["rubric"],
    }
    tag = f"{job['rubric']}.X-{x_arm}"
    request_path = raw_dir / f"{item_id}.{tag}.request.json"
    response_path = raw_dir / f"{item_id}.{tag}.response.json"
    if request_path.exists() and response_path.exists():
        try:
            if json.loads(request_path.read_text()) == identity:
                cached = json.loads(response_path.read_text())
                if cached.get("ok"):
                    return {**cached, "cacheHit": True}
        except (OSError, json.JSONDecodeError):
            pass
    write_json(request_path, identity)
    audio_b64 = base64.b64encode(job["audio"].read_bytes()).decode()
    outcome = call_judge(api_key, prompt, audio_b64, job["generationConfig"])
    parsed, raw_text = parse_outcome(outcome)
    if parsed is None and outcome["attempts"][-1].get("httpStatus") == 200:
        retry = call_judge(api_key, prompt, audio_b64, job["generationConfig"])
        retry_parsed, retry_text = parse_outcome(retry)
        outcome["attempts"] = outcome["attempts"] + retry["attempts"]
        if retry_parsed is not None:
            outcome, parsed, raw_text = retry, retry_parsed, retry_text
    winner = None
    verdict = None
    if isinstance(parsed, dict) and parsed.get("verdict") in ("X", "Y", "tie"):
        verdict = parsed["verdict"]
        winner = "tie" if verdict == "tie" else identity["labelToArm"][verdict]
    record = {
        "id": item_id,
        "judgeModel": JUDGE_MODEL,
        "xArm": x_arm,
        "yArm": y_arm,
        "labelToArm": identity["labelToArm"],
        "verdict": verdict,
        "winnerArm": winner,
        "confidence": (parsed or {}).get("confidence"),
        "decisionQuote": (parsed or {}).get("decision_quote"),
        "xError": (parsed or {}).get("x_error"),
        "yError": (parsed or {}).get("y_error"),
        "reason": (parsed or {}).get("reason"),
        "ok": winner is not None,
        "httpStatus": outcome["attempts"][-1].get("httpStatus"),
        "attemptLatencies": [attempt.get("latencySeconds") for attempt in outcome["attempts"]],
        "latencySeconds": round(outcome["latency"], 3),
        "promptSha256": prompt_sha,
        "audioSha256": job["audioSha256"],
        "responseSha256": sha256_bytes(outcome["body"].encode()),
        "judgeText": raw_text[:1200],
        "judgedAt": datetime.now(timezone.utc).isoformat(),
    }
    write_json(response_path, record)
    return {**record, "cacheHit": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm-a", required=True, help="named arm; it sits in the X slot on the first pass")
    parser.add_argument("--arm-b", required=True)
    parser.add_argument("--runs-dir", type=Path, default=Path("artifacts/deepseek-asr-ab/runs"))
    parser.add_argument("--audio-dir", type=Path, default=Path("artifacts/deepseek-asr-ab/audio"))
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/deepseek-asr-ab/adjudication"))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--rubric", choices=sorted(RUBRICS), default="v1")
    parser.add_argument("--thinking", choices=("LOW", "MEDIUM", "HIGH"), default="LOW")
    parser.add_argument("--confirm-billable", action="store_true")
    args = parser.parse_args()
    if not args.confirm_billable:
        raise SystemExit("--confirm-billable is required: this dispatches judge calls")

    api_key = google_key()

    runs_dir = (REPO_ROOT / args.runs_dir).resolve()
    audio_dir = (REPO_ROOT / args.audio_dir).resolve()
    output_dir = (REPO_ROOT / args.output_dir).resolve()
    raw_dir = output_dir / "raw"
    arm_a_rows = {row["id"]: row for row in read_jsonl(runs_dir / args.arm_a / "predictions.jsonl")}
    arm_b_rows = {row["id"]: row for row in read_jsonl(runs_dir / args.arm_b / "predictions.jsonl")}
    if set(arm_a_rows) != set(arm_b_rows):
        raise SystemExit("arm prediction item sets differ")
    item_ids = sorted(arm_a_rows)[: args.limit]

    jobs = []
    for item_id in item_ids:
        audio_path = audio_dir / f"{item_id}.wav"
        if not audio_path.exists():
            raise SystemExit(f"missing adjudication audio: {audio_path}")
        audio_sha = sha256_file(audio_path)
        text_a = arm_a_rows[item_id]["transcript"]
        text_b = arm_b_rows[item_id]["transcript"]
        for x_arm, y_arm, text_x, text_y in (
            (args.arm_a, args.arm_b, text_a, text_b),
            (args.arm_b, args.arm_a, text_b, text_a),
        ):
            jobs.append(
                {
                    "id": item_id,
                    "xArm": x_arm,
                    "yArm": y_arm,
                    "textX": text_x,
                    "textY": text_y,
                    "audio": audio_path,
                    "audioSha256": audio_sha,
                    "rubric": args.rubric,
                    "generationConfig": {
                        **GENERATION_CONFIG,
                        "thinkingConfig": {"thinkingLevel": args.thinking},
                    },
                }
            )

    results: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(judge_one, job, api_key=api_key, raw_dir=raw_dir): (job["id"], job["xArm"])
            for job in jobs
        }
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda row: (row["id"], row["xArm"]))

    results_path = output_dir / "adjudications.jsonl"
    results_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in results), encoding="utf-8"
    )
    by_item: dict[str, list[dict[str, Any]]] = {}
    for row in results:
        by_item.setdefault(row["id"], []).append(row)
    flips = []
    for item_id, rows in by_item.items():
        winners = {row["winnerArm"] for row in rows if row["winnerArm"]}
        if len(rows) == 2 and len(winners) > 1:
            flips.append(item_id)
    arm_a_wins = sum(1 for row in results if row["winnerArm"] == args.arm_a)
    arm_b_wins = sum(1 for row in results if row["winnerArm"] == args.arm_b)
    ties = sum(1 for row in results if row["winnerArm"] == "tie")
    summary = {
        "schemaVersion": "deepseek-asr-ab-adjudication-v1",
        "completedAt": datetime.now(timezone.utc).isoformat(),
        "judgeModel": JUDGE_MODEL,
        "rubric": args.rubric,
        "thinking": args.thinking,
        "judgeRole": "independent_audio_model_adjudication_not_human_gold",
        "humanListeningCompleted": False,
        "armA": args.arm_a,
        "armB": args.arm_b,
        "itemCount": len(by_item),
        "judgmentCount": len(results),
        "successfulJudgments": sum(row["ok"] for row in results),
        "failedJudgments": sum(not row["ok"] for row in results),
        "wins": {args.arm_a: arm_a_wins, args.arm_b: arm_b_wins, "tie": ties},
        "winsBySlot": {
            "aInXSlot": {
                args.arm_a: sum(
                    1 for row in results if row["xArm"] == args.arm_a and row["winnerArm"] == args.arm_a
                ),
                args.arm_b: sum(
                    1 for row in results if row["xArm"] == args.arm_a and row["winnerArm"] == args.arm_b
                ),
                "tie": sum(1 for row in results if row["xArm"] == args.arm_a and row["winnerArm"] == "tie"),
            },
            "bInXSlot": {
                args.arm_a: sum(
                    1 for row in results if row["xArm"] == args.arm_b and row["winnerArm"] == args.arm_a
                ),
                args.arm_b: sum(
                    1 for row in results if row["xArm"] == args.arm_b and row["winnerArm"] == args.arm_b
                ),
                "tie": sum(1 for row in results if row["xArm"] == args.arm_b and row["winnerArm"] == "tie"),
            },
        },
        "swappedOrderFlips": len(flips),
        "swappedOrderFlipIds": flips,
        "meanJudgeLatencySeconds": round(statistics.mean(row["latencySeconds"] for row in results), 3),
        "cost": COST_NOTE,
        "resultsSha256": sha256_file(results_path),
    }
    write_json(output_dir / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["failedJudgments"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
