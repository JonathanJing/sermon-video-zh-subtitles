#!/usr/bin/env python3
"""Validate, assemble, and evaluate the Qwen/AuK Layer 3 shadow POC."""
import argparse
import hashlib
import html
import json
from pathlib import Path
import subprocess


SCHEMA = "sermon-layer3-qwen-auk-poc-plan-v1"


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def text_sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_plan(path):
    plan = json.loads(Path(path).read_text(encoding="utf-8"))
    if plan.get("schemaVersion") != SCHEMA:
        raise ValueError("unsupported POC plan")
    if plan.get("scope") != "layer_3_shadow_experiment":
        raise ValueError("POC must remain a Layer 3 shadow experiment")
    if plan.get("productionEligible") is not False or plan.get("humanApproval") is not False:
        raise ValueError("POC cannot be production eligible or human approved")
    if plan.get("source", {}).get("translationStatus") != "machine_review_pass_human_review_pending":
        raise ValueError("unexpected upstream translation status")
    units = plan.get("units")
    if not isinstance(units, list) or len(units) != 6:
        raise ValueError("the frozen POC must contain six source units")
    ids = []
    for index, unit in enumerate(units):
        if unit.get("unitIndex") != index:
            raise ValueError("unit indices must be contiguous")
        if text_sha256(unit.get("targetText", "")) != unit.get("targetTextSha256"):
            raise ValueError(f"target text changed: {unit.get('sourceUnitId')}")
        if unit.get("targetDurationSeconds", 0) <= 0 or unit.get("pauseAfterSeconds", -1) < 0:
            raise ValueError("invalid duration or pause")
        ids.append(unit.get("sourceUnitId"))
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate source unit IDs")
    challengers = [unit["sourceUnitId"] for unit in units if unit.get("challenger")]
    if challengers != ["block-59-u001", "block-59-u005"]:
        raise ValueError("challenger set changed")
    return plan


def probe(path):
    command = [
        "ffprobe", "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=sample_rate,channels:format=duration",
        "-of", "json", str(path),
    ]
    data = json.loads(subprocess.run(command, check=True, capture_output=True, text=True).stdout)
    stream = data["streams"][0]
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"], check=True)
    return {
        "durationSeconds": float(data["format"]["duration"]),
        "sampleRate": int(stream["sample_rate"]),
        "channels": int(stream["channels"]),
        "fullDecode": "pass",
    }


def assemble(plan, qwen_dir, out):
    import wave

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    rate = 24000
    format_identity = None
    pieces, cues, cursor = [], [], 0
    for index, unit in enumerate(plan["units"]):
        path = Path(qwen_dir) / f'{unit["sourceUnitId"]}.wav'
        with wave.open(str(path), "rb") as stream:
            observed = (stream.getnchannels(), stream.getsampwidth(), stream.getframerate(), stream.getcomptype())
            if observed[2] != rate or observed[3] != "NONE":
                raise ValueError(f"unexpected Qwen WAV format: {path}")
            if format_identity is None:
                format_identity = observed
            elif observed != format_identity:
                raise ValueError(f"Qwen unit WAV formats differ: {path}")
            frames = stream.readframes(stream.getnframes())
            frame_count = stream.getnframes()
        start = cursor / rate
        pieces.append(frames)
        cursor += frame_count
        end = cursor / rate
        pause = unit["pauseAfterSeconds"] if index + 1 < len(plan["units"]) else 0.0
        cues.append({
            "sourceUnitId": unit["sourceUnitId"], "startSeconds": start, "endSeconds": end,
            "durationSeconds": end - start, "pauseAfterSeconds": pause,
            "targetDurationSeconds": unit["targetDurationSeconds"], "text": unit["targetText"],
        })
        if pause:
            silence_frames = round(pause * rate)
            silence = b"\0" * silence_frames * format_identity[0] * format_identity[1]
            pieces.append(silence)
            cursor += silence_frames
    with wave.open(str(out), "wb") as stream:
        stream.setnchannels(format_identity[0])
        stream.setsampwidth(format_identity[1])
        stream.setframerate(rate)
        stream.writeframes(b"".join(pieces))
    receipt = {
        "schemaVersion": "sermon-layer3-qwen-unit-assembly-v1",
        "planSha256": None,
        "track": {"path": out.name, "sha256": sha256(out), **probe(out)},
        "cues": cues,
        "pausePolicy": "deterministic_copy_of_layer1_inter_unit_pauses",
        "ratePolicy": "natural_no_time_stretch",
        "productionEligible": False,
        "humanApproval": False,
    }
    return receipt


def candidate_paths(plan, run_dir):
    run_dir = Path(run_dir)
    for unit in plan["units"]:
        qwen = run_dir / "qwen" / f'{unit["sourceUnitId"]}.wav'
        if qwen.exists():
            yield unit, "qwen_sft_unit", qwen
        if unit.get("challenger"):
            baseline = run_dir / "baseline" / f'{unit["sourceUnitId"]}.wav'
            if baseline.exists():
                yield unit, "qwen_whole_group_estimated_slice", baseline
            for variant in ("auk_zero_shot", "qwen_then_auk_speed_emphasis"):
                path = run_dir / "auk" / unit["sourceUnitId"] / f"{variant}.wav"
                if path.exists():
                    yield unit, variant, path


def read_optional(path, default):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def evaluate(plan, run_dir):
    run_dir = Path(run_dir)
    asr = read_optional(run_dir / "asr-screening.json", {"results": []})
    speaker = read_optional(run_dir / "speaker-similarity.json", {"results": []})
    asr_by_key = {(r["sourceUnitId"], r["variant"]): r for r in asr.get("results", [])}
    speaker_by_key = {(r["sourceUnitId"], r["variant"]): r for r in speaker.get("results", [])}
    rows = []
    for unit, variant, path in candidate_paths(plan, run_dir):
        media = probe(path)
        error = media["durationSeconds"] - unit["targetDurationSeconds"]
        key = (unit["sourceUnitId"], variant)
        audio_hash = sha256(path)
        asr_screen = asr_by_key.get(key, {})
        speaker_screen = speaker_by_key.get(key, {})
        rows.append({
            "sourceUnitId": unit["sourceUnitId"],
            "variant": variant,
            "audio": {"path": str(path.relative_to(run_dir)), "sha256": audio_hash, **media},
            "targetDurationSeconds": unit["targetDurationSeconds"],
            "durationErrorSeconds": error,
            "durationAbsoluteErrorSeconds": abs(error),
            "durationTarget": "pass" if abs(error) <= plan["evaluation"]["durationAbsoluteErrorTargetSeconds"] else "fail",
            "contentAsrScreen": asr_screen if asr_screen.get("audioSha256") == audio_hash and asr_screen.get("status") == "screened" else {"status": "pending"},
            "speakerSimilarityScreen": speaker_screen if speaker_screen.get("audioSha256") == audio_hash and speaker_screen.get("status") == "screened" else {"status": "pending"},
            "humanListening": "pending",
        })
    required = {(unit["sourceUnitId"], "qwen_sft_unit") for unit in plan["units"]}
    required.update(
        (unit["sourceUnitId"], variant)
        for unit in plan["units"] if unit.get("challenger")
        for variant in ("auk_zero_shot", "qwen_then_auk_speed_emphasis")
    )
    observed = {(row["sourceUnitId"], row["variant"]) for row in rows}
    expected = len(required)
    return {
        "schemaVersion": "sermon-layer3-qwen-auk-poc-evaluation-v1",
        "scope": plan["scope"],
        "status": "machine_checks_complete_human_listening_pending" if required <= observed and all(r["contentAsrScreen"].get("status") != "pending" and r["speakerSimilarityScreen"].get("status") != "pending" for r in rows) else "partial",
        "candidateCount": len(rows),
        "expectedMinimumCandidateCount": expected,
        "results": rows,
        "limitations": [
            "upstream Korean translation has machine review only",
            "speaker similarity is a machine screen and not human identity acceptance",
            "AuK duration conditioning does not establish word-level alignment",
            "AuK-edited audio violates the current natural_no_time_stretch production contract",
            "human blind listening is pending",
        ],
        "productionEligible": False,
        "humanApproval": False,
    }


def listening_page(plan, run_dir, evaluation):
    run_dir = Path(run_dir)
    cards = []
    for unit in plan["units"]:
        if not unit.get("challenger"):
            continue
        rows = [row for row in evaluation["results"] if row["sourceUnitId"] == unit["sourceUnitId"]]
        players = []
        for index, row in enumerate(sorted(rows, key=lambda value: value["audio"]["sha256"])):
            players.append(
                f'<section><h3>样本 {index + 1}</h3><audio controls preload="metadata" src="{html.escape(row["audio"]["path"])}"></audio>'
                f'<p>时长 {row["audio"]["durationSeconds"]:.2f}s；目标误差 {row["durationErrorSeconds"]:+.2f}s</p>'
                '<p>请记录：内容完整性、像 Eric、自然度、强调、整体偏好（1–5）。</p></section>'
            )
        cards.append(
            f'<article><h2>{html.escape(unit["sourceUnitId"])} · 目标 {unit["targetDurationSeconds"]:.2f}s</h2>'
            f'<p lang="ko">{html.escape(unit["targetText"])}</p>{"".join(players)}</article>'
        )
    return """<!doctype html><meta charset=\"utf-8\"><title>Layer 3 Qwen/AuK 盲听</title>
<style>body{font:16px system-ui;max-width:900px;margin:32px auto;padding:0 20px;color:#172019}article{border:1px solid #ccd5cc;border-radius:14px;padding:20px;margin:20px 0}section{background:#f4f7f4;padding:14px;margin:12px 0;border-radius:10px}audio{width:100%}</style>
<h1>Layer 3 Qwen / AuK POC 盲听</h1><p>本页只用于 shadow POC。播放器顺序按音频哈希固定盲化；映射保存在 evaluation.json。机器分数不能代替本页的人耳判断。</p>""" + "".join(cards)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["validate", "assemble", "evaluate", "listening-page"])
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--qwen-dir", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    plan = load_plan(args.plan)
    if args.command == "validate":
        print(json.dumps({"status": "valid", "units": len(plan["units"]), "challengers": 2}))
        return
    if args.command == "assemble":
        if not args.qwen_dir or not args.out:
            parser.error("assemble requires --qwen-dir and --out")
        receipt = assemble(plan, args.qwen_dir, args.out)
        receipt["planSha256"] = sha256(args.plan)
        write_json(args.out.with_suffix(".json"), receipt)
        print(json.dumps({"status": "assembled", "track": str(args.out)}))
        return
    if not args.run_dir:
        parser.error(f"{args.command} requires --run-dir")
    evaluation_path = args.run_dir / "evaluation.json"
    evaluation = evaluate(plan, args.run_dir)
    if args.command == "evaluate":
        write_json(evaluation_path, evaluation)
        print(json.dumps({"status": evaluation["status"], "results": len(evaluation["results"])}))
    else:
        output = args.out or args.run_dir / "listening.html"
        output.write_text(listening_page(plan, args.run_dir, evaluation), encoding="utf-8")
        print(json.dumps({"status": "written", "page": str(output)}))


if __name__ == "__main__":
    main()
