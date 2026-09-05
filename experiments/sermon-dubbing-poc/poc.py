#!/usr/bin/env python3
"""Local, source-backed Chinese speech experiment; generated assets stay outside Git."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / "artifacts/sermon-dubbing/2026-09-05-fluency-poc-v2"
MODEL = "mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit"
REVISION = "41d3337e8b7f2843a75841595fc14e4b9a7a4b96"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def probe(path: Path) -> dict:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,codec_name,sample_rate,channels", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(result.stdout)
    duration = float(data["format"]["duration"])
    if duration <= 0 or not any(s["codec_type"] == "audio" for s in data["streams"]):
        raise ValueError(f"No usable audio: {path}")
    return {"durationSeconds": duration, "streams": data["streams"]}


def sentences(text: str) -> list[str]:
    # Attach closing quotes to the sentence whose punctuation they follow.
    parts = re.findall(r"[^。！？]+[。！？]?[”’\"']*", text)
    return [s.strip() for s in parts if s.strip()]


def speech_units(paragraphs: list[str], mode: str) -> list[str]:
    if mode not in {"flow", "sentence"}:
        raise ValueError("Unknown segmentation mode")
    output = []
    for paragraph in paragraphs:
        current = ""
        for sentence in sentences(paragraph):
            if mode == "sentence":
                output.append(sentence)
                continue
            if current and len(current) + len(sentence) > 100:
                output.append(current)
                current = ""
            current += sentence
        if current:
            output.append(current)
    expected = "".join(paragraphs).replace(" ", "")
    if "".join(output).replace(" ", "") != expected:
        raise ValueError("Segmentation changed source text")
    return output


def inventory(root: Path, out: Path) -> dict:
    from voice_source import AUTHORIZATION, authorized_source
    authorization = json.loads(AUTHORIZATION.read_text()) if AUTHORIZATION.is_file() else {}
    benchmark_path = root / "data/benchmarks/live-sermon-translation-v1/benchmark-manifest.json"
    benchmark = json.loads(benchmark_path.read_text())
    sources = []
    for item in benchmark["items"]:
        path = root / f"data/benchmarks/live-sermon-translation-v1/work/audio/{item['videoId']}.mp4"
        if not path.is_file():
            continue
        sources.append({
            "sourceId": item["videoId"], "path": str(path), "speakerCandidate": item["speaker"],
            "speakerEvidence": "existing_benchmark_metadata", "speakerTurnsVerified": False,
            "role": "protected_evaluation", "eligibleForTraining": False,
            "exclusions": ["existing_untouched_test"], "sha256": sha256(path), **probe(path),
        })
    protected_dates = {item["uploadDate"] for item in benchmark["items"]}
    for summary_path in sorted((root / "artifacts/post-live-runs").glob("*/*/pipeline/summary.json")):
        summary = json.loads(summary_path.read_text())
        path = summary_path.parent / "source_clip.m4a"
        if not path.is_file():
            continue
        reading_path = summary_path.parent / "reading-edition-v2/reading_blocks.final.json"
        reading = json.loads(reading_path.read_text()) if reading_path.is_file() else []
        self_intro = any("my name is Eric" in block.get("en", "") for block in reading)
        date = summary_path.parents[2].name
        exclusions = ["voice_permission_pending", "speaker_turns_not_verified", "audio_text_alignment_not_verified"]
        if date.replace("-", "") in protected_dates:
            exclusions.append("possible_same_sermon_as_protected_evaluation")
        sources.append({
            "sourceId": summary_path.parents[1].name.removeprefix("sermon_"), "serviceDate": date,
            "path": str(path), "speakerCandidate": "Eric (self-introduction)" if self_intro else "unassigned",
            "speakerEvidence": "source_transcript_self_introduction" if self_intro else "pending_review",
            "speakerTurnsVerified": False, "role": "production_source_candidate", "eligibleForTraining": False,
            "exclusions": exclusions, "sha256": sha256(path), **probe(path),
            "parentAudioSha256": summary["pipelineInputIdentity"]["sourceAudio"]["sha256"],
            "sourceWindowStartSeconds": summary["sermonStartSeconds"],
            "sourceWindowEndSeconds": summary["sermonEndSeconds"],
            "timingPrecision": summary["timingPrecision"], "readingSource": str(reading_path),
        })
    report = {"schemaVersion": "speaker-corpus-inventory-v1", "createdAt": datetime.now(timezone.utc).isoformat(),
              "sources": sources, "sourceCount": len(sources), "trainingAdmittedCount": 0,
              "note": "Metadata grouping is not diarization or verified identity. Same-sermon duplicates need content checks, not hashes alone."}
    for source in sources:
        confirmed = authorized_source(authorization, source["sourceId"], source["sha256"], "voice_training")
        source["voiceTrainingPermission"] = "confirmed_by_user" if confirmed else "pending"
        if confirmed:
            source["authorizationId"] = authorization["authorizationId"]
            source["exclusions"] = [reason for reason in source["exclusions"] if reason != "voice_permission_pending"]
    write_json(out / "speaker-inventory.json", report)
    return report


def prepare(out: Path) -> dict:
    pipeline = ROOT / "artifacts/post-live-runs/2026-08-23/sermon_ZDQwL3K-A44/pipeline"
    reading_path = pipeline / "reading-edition-v2/reading_blocks.final.json"
    blocks = json.loads(reading_path.read_text())
    chosen = [block for block in blocks if block["id"] in [9, 10]]
    if [b["id"] for b in chosen] != [9, 10]:
        raise ValueError("Expected the two contiguous source blocks")
    paragraphs = [b["zh"] for b in chosen]
    plan = {
        "schemaVersion": "sermon-fluency-experiment-v1", "sourceId": "ZDQwL3K-A44",
        "serviceDate": "2026-08-23", "title": "诗篇 55 篇 · 面对背叛", "sourceBlockIds": [9, 10],
        "readingSource": str(reading_path), "readingSha256": sha256(reading_path),
        "sourceAudio": str(pipeline / "source_clip.m4a"), "sourceAudioSha256": sha256(pipeline / "source_clip.m4a"),
        "english": "\n\n".join(b["en"] for b in chosen), "paragraphs": paragraphs,
        "translationStatus": "existing_model_reviewed_candidate", "humanListeningStatus": "pending",
        "sourceTiming": "synthetic_reading_layout_only", "videoSynchronization": "not_validated",
        "voice": {"type": "preset", "name": "Uncle_Fu", "speakerClone": False},
        "model": MODEL, "revision": REVISION,
        "instruct": "用自然、清楚、温和的普通话讲述。保持上下句连贯，语气平稳，停顿自然，不夸张，不朗诵。",
        "temperature": 0.7, "seed": 42, "joinSilenceSeconds": 0.18,
        "changedVariable": "segmentation_only", "flowMaxCharacters": 100,
        "variants": {mode: speech_units(paragraphs, mode) for mode in ["flow", "sentence"]},
    }
    write_json(out / "experiment.json", plan)
    (out / "chinese-spoken.txt").write_text("\n\n".join(paragraphs) + "\n")
    return plan


def synthesize(out: Path) -> dict:
    import mlx.core as mx
    import numpy as np
    import soundfile as sf
    from huggingface_hub import snapshot_download
    from mlx_audio.tts.utils import load_model

    plan = json.loads((out / "experiment.json").read_text())
    reference = None
    if plan["voice"].get("type") == "reference":
        from voice_source import verify_reference
        reference = verify_reference(plan)
        if plan["model"] != "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit":
            raise ValueError("Reference experiment requires the declared Base model")
    elif plan["voice"] != {"type": "preset", "name": "Uncle_Fu", "speakerClone": False}:
        raise ValueError("Unknown voice experiment")
    if sha256(Path(plan["readingSource"])) != plan["readingSha256"]:
        raise ValueError("Reading source changed; prepare a new experiment")
    if sha256(Path(plan["sourceAudio"])) != plan["sourceAudioSha256"]:
        raise ValueError("Source audio changed; prepare a new experiment")
    model_path = snapshot_download(repo_id=plan["model"], revision=plan["revision"])
    model = load_model(model_path)
    tracks = []
    for mode, units in plan["variants"].items():
        chunks = []
        cues = []
        cursor = 0
        sample_rate = None
        receipts = []
        for index, text in enumerate(units):
            chunk_path = out / "chunks" / mode / f"{index:03d}.wav"
            receipt_path = chunk_path.with_suffix(".json")
            key = hashlib.sha256(json.dumps({"plan": plan, "mode": mode, "index": index, "text": text}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            if chunk_path.exists() and receipt_path.exists():
                receipt = json.loads(receipt_path.read_text())
                if receipt["inputKey"] != key or receipt["audioSha256"] != sha256(chunk_path):
                    raise ValueError(f"Stale cached chunk: {chunk_path}; use a new output directory")
                waveform, rate = sf.read(chunk_path, dtype="float32")
            else:
                started = time.monotonic()
                mx.random.seed(plan["seed"])
                if reference:
                    results = list(model.generate(text=text, ref_audio=reference["referenceAudio"], ref_text=reference["referenceText"], lang_code="Chinese", temperature=plan["temperature"], max_tokens=4096, verbose=False))
                else:
                    results = list(model.generate_custom_voice(text=text, speaker=plan["voice"]["name"], language="Chinese", instruct=plan["instruct"], temperature=plan["temperature"], max_tokens=4096, verbose=False))
                if not results or len({r.sample_rate for r in results}) != 1:
                    raise ValueError("Empty or mixed-rate TTS response")
                waveform = np.concatenate([np.asarray(r.audio).reshape(-1) for r in results])
                rate = results[0].sample_rate
                duration = len(waveform) / rate
                if not np.isfinite(waveform).all() or duration < 0.3 or duration > len(text) / 1.2 + 10:
                    raise ValueError("Suspicious generated audio; preserve run for inspection")
                chunk_path.parent.mkdir(parents=True, exist_ok=True)
                sf.write(chunk_path, waveform, rate, subtype="PCM_24")
                receipt = {"inputKey": key, "text": text, "audioSha256": sha256(chunk_path), "durationSeconds": duration, "generationSeconds": time.monotonic() - started}
                write_json(receipt_path, receipt)
            if sample_rate is not None and sample_rate != rate:
                raise ValueError("Sample rate changed between utterances")
            sample_rate = rate
            cues.append({"start": cursor / rate, "end": (cursor + len(waveform)) / rate, "text": text})
            chunks.append(waveform)
            cursor += len(waveform)
            if index < len(units) - 1:
                silence = np.zeros(round(plan["joinSilenceSeconds"] * rate), dtype=np.float32)
                chunks.append(silence)
                cursor += len(silence)
            receipts.append(receipt)
            print(json.dumps({"mode": mode, "chunk": index + 1, "total": len(units), "audioSeconds": round(receipt["durationSeconds"], 2)}, ensure_ascii=False), flush=True)
            mx.clear_cache()
        raw = out / f"{mode}.raw.wav"
        sf.write(raw, np.concatenate(chunks), sample_rate, subtype="PCM_24")
        # One continuous MP3 per variant: browser playback never schedules individual chunks.
        analysis = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(raw), "-af", "loudnorm=I=-18:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"], capture_output=True, text=True, check=True)
        loudness, _ = json.JSONDecoder().raw_decode(analysis.stderr[analysis.stderr.rfind("{"):])
        filt = "loudnorm=I=-18:TP=-1.5:LRA=11:linear=true:" + ":".join(f"{a}={loudness[b]}" for a, b in [("measured_I", "input_i"), ("measured_TP", "input_tp"), ("measured_LRA", "input_lra"), ("measured_thresh", "input_thresh"), ("offset", "target_offset")])
        mp3 = out / f"{mode}.mp3"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-af", filt, "-ar", "48000", "-c:a", "libmp3lame", "-b:a", "192k", str(mp3)], check=True)
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(mp3), "-f", "null", "-"], check=True)
        tracks.append({"id": mode, "label": plan.get("variantLabels", {}).get(mode, "连贯分组" if mode == "flow" else "逐句合成"), "file": mp3.name, "audioUrl": f"/media/{mp3.name}", "durationSeconds": cursor / sample_rate, "sha256": sha256(mp3), "cues": cues, "generationSeconds": sum(r["generationSeconds"] for r in receipts), "chunkCount": len(units), "probe": probe(mp3), "loudnessBefore": loudness})
        write_json(out / "build-progress.json", {"completedTracks": tracks, "humanListeningStatus": "pending"})
    library = {"schemaVersion": "sermon-audio-library-v1", "title": plan["title"], "date": plan["serviceDate"], "speakerLabel": "Eric（英文原稿自述）", "voiceLabel": "授权原声参考 · AI 中文音色克隆" if reference else "中文预设音色 · 非讲员克隆", "reviewLabel": "AI 中文试听 · 待人工听审", "sourceTiming": plan["sourceTiming"], "videoSynchronization": "not_validated", "tracks": tracks}
    write_json(out / "library.json", library)
    write_json(out / "build-report.json", {"status": "generated_and_decoded", "experimentSha256": sha256(out / "experiment.json"), "packages": {name: importlib.metadata.version(name) for name in ["mlx-audio", "mlx", "soundfile", "transformers"]}, "humanListeningStatus": "pending", "speakerClone": bool(reference), "trainedCheckpoint": None, "tracks": tracks})
    return library


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["inventory", "prepare", "synthesize"])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    if args.command == "inventory":
        data = inventory(ROOT, args.out)
        print(json.dumps({"sources": data["sourceCount"], "trainingAdmitted": data["trainingAdmittedCount"]}))
    elif args.command == "prepare":
        data = prepare(args.out)
        print(json.dumps({"characters": sum(map(len, data["paragraphs"])), "units": {k: len(v) for k, v in data["variants"].items()}}, ensure_ascii=False))
    else:
        data = synthesize(args.out)
        print(json.dumps({"status": "generated_and_decoded", "tracks": [{"id": t["id"], "seconds": t["durationSeconds"]} for t in data["tracks"]]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
