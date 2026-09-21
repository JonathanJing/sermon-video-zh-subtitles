#!/usr/bin/env python3
"""Run a cached multimodal request against a local OpenAI-compatible server."""
from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path

from schema import extract_json, sha256, validate, validate_expected_modalities


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8910/v1")
    parser.add_argument("--model", required=True)
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--server-video-uri", required=True)
    parser.add_argument("--server-audio-uri", required=True)
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--expected-audio-status", choices=("matched", "mismatch", "no_speech"))
    parser.add_argument("--expected-video-status", choices=("matched", "mismatch", "no_visual"))
    parser.add_argument("--expected-transcript-status",
                        choices=("matched", "partial", "mismatch", "not_provided"))
    parser.add_argument("--enable-thinking", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--max-tokens", type=int, default=4096)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    result_path = args.out / f"{args.case_id}.result.json"
    if result_path.exists():
        print(result_path)
        return
    prompt = args.prompt.read_text(encoding="utf-8")
    request_body = {
        "model": args.model,
        "messages": [{"role": "user", "content": [
            {"type": "video_url", "video_url": {"url": args.server_video_uri}},
            {"type": "audio_url", "audio_url": {"url": args.server_audio_uri}},
            {"type": "text", "text": prompt},
        ]}],
        "temperature": 0.2,
        "max_tokens": args.max_tokens,
        "stream": False,
        "mm_processor_kwargs": {"use_audio_in_video": False},
    }
    if args.enable_thinking:
        request_body["chat_template_kwargs"] = {"enable_thinking": True}
    request_bytes = json.dumps(request_body).encode()
    request_identity = {
        "model": args.model,
        "promptSha256": sha256(args.prompt),
        "videoSha256": sha256(args.video),
        "audioSha256": sha256(args.audio),
        "caseId": args.case_id,
        "thinkingEnabled": args.enable_thinking,
        "maxTokens": args.max_tokens,
    }
    attempt_path = args.out / f"{args.case_id}.attempt.json"
    response_path = args.out / f"{args.case_id}.response.json"
    if attempt_path.exists() or response_path.exists():
        raise RuntimeError("Incomplete prior attempt exists; inspect it before retrying")
    write_json(attempt_path, {**request_identity, "startedUnix": time.time(), "apiKeyMaterialIncluded": False})
    request = urllib.request.Request(
        args.base_url.rstrip("/") + "/chat/completions", data=request_bytes,
        headers={"Content-Type": "application/json"}, method="POST")
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=args.timeout) as response:
        raw = json.load(response)
    write_json(response_path, raw)
    content = raw["choices"][0]["message"]["content"]
    parse_error = None
    try:
        analysis = extract_json(content)
        errors = sorted(set(validate(analysis, args.duration)
                            + validate_expected_modalities(
                                analysis,
                                expected_audio_status=args.expected_audio_status,
                                expected_video_status=args.expected_video_status,
                                expected_transcript_status=args.expected_transcript_status)))
    except Exception as exc:  # raw output remains inspectable
        analysis = None
        errors = ["invalid_json"]
        parse_error = f"{type(exc).__name__}: {exc}"
    finish_reason = raw["choices"][0].get("finish_reason")
    if finish_reason not in (None, "stop"):
        errors = sorted(set(errors + [f"finish_reason_{finish_reason}"]))
    result = {
        **request_identity,
        "latencySeconds": round(time.monotonic() - started, 3),
        "analysis": analysis,
        "validationErrors": errors,
        "parseError": parse_error,
        "finishReason": finish_reason,
        "usage": raw.get("usage"),
        "reviewState": "machine_candidate_requires_review",
        "apiKeyMaterialIncluded": False,
    }
    write_json(result_path, result)
    print(json.dumps({"result": str(result_path), "validationErrors": errors, "latencySeconds": result["latencySeconds"]}))


if __name__ == "__main__":
    main()
