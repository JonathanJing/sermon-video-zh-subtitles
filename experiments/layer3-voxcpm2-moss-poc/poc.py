#!/usr/bin/env python3
"""Validate and evaluate the VoxCPM2/MOSS-TTS Layer 3 shadow POC."""
import argparse
import hashlib
import html
import json
from pathlib import Path
import struct
import wave


SCHEMA = "sermon-layer3-voxcpm2-moss-poc-plan-v1"


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def text_sha256(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_pcm_wav(path):
    with wave.open(str(path), "rb") as stream:
        if stream.getcomptype() != "NONE":
            raise ValueError(f"compressed WAV is unsupported: {path}")
        channels = stream.getnchannels()
        sample_width = stream.getsampwidth()
        sample_rate = stream.getframerate()
        frame_count = stream.getnframes()
        frames = stream.readframes(frame_count)
    if sample_width not in {1, 2, 3, 4}:
        raise ValueError(f"unsupported PCM sample width: {sample_width}")
    if len(frames) != frame_count * channels * sample_width:
        raise ValueError(f"truncated WAV data: {path}")
    return frames, sample_rate, channels, sample_width, frame_count


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
    units = plan.get("primaryUnits", [])
    if [unit.get("sourceUnitId") for unit in units] != ["block-59-u001", "block-59-u005"]:
        raise ValueError("primary Chinese challenger set changed")
    smoke = plan.get("multilingualSmoke", [])
    if [row.get("targetLocale") for row in smoke] != ["zh-Hans", "ko", "es", "vi"]:
        raise ValueError("target-locale smoke set changed")
    for item in units + smoke:
        if text_sha256(item.get("targetText", "")) != item.get("targetTextSha256"):
            raise ValueError(f"target text changed: {item.get('sourceUnitId') or item.get('sampleId')}")
    probe = plan.get("pauseProbe", {})
    if probe.get("pauseSeconds") != 1.450001:
        raise ValueError("explicit pause probe changed")
    return plan


def probe_audio(path):
    path = Path(path)
    _, sample_rate, channels, _, frame_count = read_pcm_wav(path)
    return {
        "durationSeconds": frame_count / sample_rate,
        "sampleRate": sample_rate,
        "channels": channels,
        "fullDecode": "pass",
    }


def candidate_specs(plan, run_dir):
    run_dir = Path(run_dir)
    for unit in plan["primaryUnits"]:
        sample_id = unit["sourceUnitId"]
        candidates = [
            ("qwen_sft_unit", run_dir / "baseline" / "qwen" / f"{sample_id}.wav"),
            ("voxcpm2_clone", run_dir / "voxcpm2" / sample_id / "clone.wav"),
            ("voxcpm2_style_guided", run_dir / "voxcpm2" / sample_id / "style_guided.wav"),
            ("moss_clone", run_dir / "moss" / sample_id / "clone.wav"),
            ("moss_duration_control", run_dir / "moss" / sample_id / "duration_control.wav"),
        ]
        for variant, path in candidates:
            if path.exists():
                yield {
                    "sampleId": sample_id, "sourceUnitId": sample_id, "category": "primary_chinese_challenger",
                    "variant": variant, "path": path, "targetText": unit["targetText"],
                    "targetTextSha256": unit["targetTextSha256"], "targetLocale": unit["targetLocale"],
                    "language": unit["language"], "targetDurationSeconds": unit["targetDurationSeconds"],
                }
    pause = plan["pauseProbe"]
    pause_path = run_dir / "moss" / pause["sampleId"] / "explicit_pause.wav"
    if pause_path.exists():
        yield {
            "sampleId": pause["sampleId"], "sourceUnitId": pause["sampleId"], "category": "explicit_pause",
            "variant": "moss_explicit_pause", "path": pause_path,
            "targetText": pause["beforeText"] + " " + pause["afterText"],
            "targetTextSha256": text_sha256(pause["beforeText"] + " " + pause["afterText"]),
            "targetLocale": pause["targetLocale"], "language": pause["language"],
            "targetDurationSeconds": next(unit["targetDurationSeconds"] for unit in plan["primaryUnits"] if unit["sourceUnitId"] == pause["beforeSourceUnitId"]) + pause["pauseSeconds"] + pause["afterDurationSeconds"],
            "expectedPauseSeconds": pause["pauseSeconds"],
        }
    for smoke in plan["multilingualSmoke"]:
        for model in ("voxcpm2", "moss"):
            path = run_dir / model / "smoke" / f'{smoke["targetLocale"]}.wav'
            if path.exists():
                yield {
                    "sampleId": smoke["sampleId"], "sourceUnitId": smoke["sourceUnitId"],
                    "category": "four_target_locale_smoke", "variant": f"{model}_clone", "path": path,
                    "targetText": smoke["targetText"], "targetTextSha256": smoke["targetTextSha256"],
                    "targetLocale": smoke["targetLocale"], "language": smoke["language"],
                    "targetDurationSeconds": None,
                }


def detect_silences(path, minimum=0.35, noise="-38dB"):
    if not noise.endswith("dB"):
        raise ValueError("silence threshold must use dB")
    frames, sample_rate, channels, sample_width, frame_count = read_pcm_wav(path)
    maximum = (1 << (sample_width * 8 - 1)) - 1
    threshold = maximum * 10 ** (float(noise[:-2]) / 20)
    if sample_width == 1:
        samples = (value - 128 for value in frames)
    elif sample_width in {2, 4}:
        code = "h" if sample_width == 2 else "i"
        samples = (value[0] for value in struct.iter_unpack("<" + code, frames))
    else:
        samples = (
            int.from_bytes(frames[offset:offset + 3], "little", signed=True)
            for offset in range(0, len(frames), 3)
        )
    quiet = []
    for _ in range(frame_count):
        quiet.append(all(abs(next(samples)) <= threshold for _ in range(channels)))
    spans = []
    start = None
    for index, is_quiet in enumerate(quiet + [False]):
        if is_quiet and start is None:
            start = index
        elif not is_quiet and start is not None:
            spans.append((start, index))
            start = None
    rows = []
    for start, end in spans:
        duration = (end - start) / sample_rate
        if duration >= minimum:
            rows.append({
                "startSeconds": start / sample_rate,
                "endSeconds": end / sample_rate,
                "durationSeconds": duration,
            })
    return rows


def read_optional(path):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"results": []}


def evaluate(plan, run_dir):
    run_dir = Path(run_dir)
    asr = read_optional(run_dir / "asr-screening.json")
    speaker = read_optional(run_dir / "speaker-similarity.json")
    asr_by_key = {(row["sampleId"], row["variant"]): row for row in asr.get("results", [])}
    speaker_by_key = {(row["sampleId"], row["variant"]): row for row in speaker.get("results", [])}
    rows = []
    for spec in candidate_specs(plan, run_dir):
        media = probe_audio(spec["path"])
        target = spec.get("targetDurationSeconds")
        error = None if target is None else media["durationSeconds"] - target
        key = (spec["sampleId"], spec["variant"])
        pause_screen = None
        if spec.get("expectedPauseSeconds") is not None:
            silences = detect_silences(spec["path"])
            closest = min(silences, key=lambda row: abs(row["durationSeconds"] - spec["expectedPauseSeconds"]), default=None)
            pause_screen = {
                "status": "screened", "expectedSeconds": spec["expectedPauseSeconds"],
                "detectedSilences": silences, "closest": closest,
                "absoluteErrorSeconds": None if closest is None else abs(closest["durationSeconds"] - spec["expectedPauseSeconds"]),
            }
        audio_hash = sha256(spec["path"])
        asr_screen = asr_by_key.get(key, {})
        speaker_screen = speaker_by_key.get(key, {})
        rows.append({
            "sampleId": spec["sampleId"], "sourceUnitId": spec["sourceUnitId"],
            "category": spec["category"], "targetLocale": spec["targetLocale"], "variant": spec["variant"],
            "audio": {"path": str(spec["path"].relative_to(run_dir)), "sha256": audio_hash, **media},
            "targetDurationSeconds": target,
            "durationErrorSeconds": error,
            "durationAbsoluteErrorSeconds": None if error is None else abs(error),
            "durationTarget": "not_applicable" if error is None else ("pass" if abs(error) <= plan["evaluation"]["durationAbsoluteErrorTargetSeconds"] else "fail"),
            "contentAsrScreen": asr_screen if asr_screen.get("audioSha256") == audio_hash and asr_screen.get("status") == "screened" else {"status": "pending"},
            "speakerSimilarityScreen": speaker_screen if speaker_screen.get("audioSha256") == audio_hash and speaker_screen.get("status") == "screened" else {"status": "pending"},
            "explicitPauseScreen": pause_screen,
            "humanListening": "pending",
        })
    expected = 19
    screened = all(row["contentAsrScreen"].get("status") != "pending" and row["speakerSimilarityScreen"].get("status") != "pending" for row in rows)
    return {
        "schemaVersion": "sermon-layer3-voxcpm2-moss-poc-evaluation-v1",
        "scope": plan["scope"],
        "status": "machine_checks_complete_human_listening_pending" if len(rows) == expected and screened else "partial",
        "candidateCount": len(rows), "expectedCandidateCount": expected, "results": rows,
        "limitations": [
            "all target-language text remains machine_review_pass_human_review_pending",
            "cross-language ASR and speaker embeddings are machine screens only",
            "silence detection does not establish semantic pause placement without forced alignment or listening",
            "duration and pause controls are shadow experiments outside the natural_no_time_stretch production contract",
            "human blind listening is pending",
        ],
        "productionEligible": False, "humanApproval": False,
    }


def listening_page(plan, run_dir, evaluation):
    groups = []
    order = [unit["sourceUnitId"] for unit in plan["primaryUnits"]] + [plan["pauseProbe"]["sampleId"]] + [row["sampleId"] for row in plan["multilingualSmoke"]]
    for sample_id in order:
        rows = [row for row in evaluation["results"] if row["sampleId"] == sample_id]
        if not rows:
            continue
        players = []
        for index, row in enumerate(sorted(rows, key=lambda value: value["audio"]["sha256"])):
            players.append(
                f'<section><h3>样本 {index + 1}</h3><audio controls preload="metadata" src="{html.escape(row["audio"]["path"])}"></audio>'
                f'<p>时长 {row["audio"]["durationSeconds"]:.2f}s；请记录内容、像 Eric、自然度、速度/停顿和整体偏好（1–5）。</p></section>'
            )
        groups.append(f'<article><h2>{html.escape(sample_id)}</h2>{"".join(players)}</article>')
    return """<!doctype html><meta charset="utf-8"><title>Layer 3 VoxCPM2 / MOSS-TTS 盲听</title>
<style>body{font:16px system-ui;max-width:960px;margin:32px auto;padding:0 20px;color:#172019}article{border:1px solid #ccd5cc;border-radius:14px;padding:20px;margin:20px 0}section{background:#f4f7f4;padding:14px;margin:12px 0;border-radius:10px}audio{width:100%}</style>
<h1>Layer 3 VoxCPM2 / MOSS-TTS v1.5 POC 盲听</h1><p>仅用于 shadow POC；播放器按音频哈希固定盲化，映射在 evaluation.json。机器分数不等于人耳验收。</p>""" + "".join(groups)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["validate", "evaluate", "listening-page"])
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    plan = load_plan(args.plan)
    if args.command == "validate":
        print(json.dumps({"status": "valid", "primaryChineseUnits": 2, "smokeLocales": 4}))
        return
    if not args.run_dir:
        parser.error(f"{args.command} requires --run-dir")
    evaluation = evaluate(plan, args.run_dir)
    if args.command == "evaluate":
        write_json(args.run_dir / "evaluation.json", evaluation)
        print(json.dumps({"status": evaluation["status"], "results": len(evaluation["results"])}))
    else:
        output = args.out or args.run_dir / "listening.html"
        output.write_text(listening_page(plan, args.run_dir, evaluation), encoding="utf-8")
        print(json.dumps({"status": "written", "page": str(output)}))


if __name__ == "__main__":
    main()
