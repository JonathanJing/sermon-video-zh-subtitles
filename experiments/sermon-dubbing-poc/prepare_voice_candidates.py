#!/usr/bin/env python3
"""Build English audio/text candidates with measured, never reading-layout, times."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess

from poc import ROOT, sha256, write_json
from voice_source import AUTHORIZATION, authorized_source

ASR = ("mlx-community/Qwen3-ASR-0.6B-8bit", "89e96d92ba34aca20b3e29fb10cc284097d1219f")
ALIGNER = ("mlx-community/Qwen3-ForcedAligner-0.6B-8bit", "0e1a68e91d815300c7c9754b2a7639378b23db15")
SOURCE_ID = "ZDQwL3K-A44"
DEFAULT_PACK = ROOT / "artifacts/sermon-dubbing/2026-09-05-authorized-voice-poc"


def normalize(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())


def sentence_spans(text, words):
    """Require exact agreement between tokenizer units; omit trailing cut sentence."""
    cursor = 0
    spans = []
    for match in re.finditer(r"[^.!?]+[.!?]", text):
        sentence = match.group().strip()
        tokens = [normalize(token) for token in sentence.split() if normalize(token)]
        selected = words[cursor:cursor + len(tokens)]
        if [normalize(w["text"]) for w in selected] != tokens:
            raise ValueError("Sentence/aligner tokens disagree; inspect instead of guessing")
        cursor += len(tokens)
        if selected:
            spans.append({"text": sentence, "start": selected[0]["start"], "end": selected[-1]["end"]})
    return spans


def group_candidates(spans, canonical):
    candidates, excluded, current = [], [], []
    def emit():
        nonlocal current
        if not current:
            return
        unit = {"text": " ".join(s["text"] for s in current), "start": current[0]["start"], "end": current[-1]["end"]}
        duration = unit["end"] - unit["start"]
        reasons = []
        if not 4 <= duration <= 15:
            reasons.append("outside_4_to_15_second_budget")
        if normalize(unit["text"]) not in normalize(canonical):
            reasons.append("does_not_match_existing_english_source")
        if reasons:
            excluded.append({**unit, "reasons": reasons})
        else:
            candidates.append(unit)
        current = []
    for span in spans:
        if current and span["end"] - current[0]["start"] > 12:
            emit()
        current.append(span)
        if current[-1]["end"] - current[0]["start"] >= 6:
            emit()
    emit()
    return candidates, excluded


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", type=Path, default=DEFAULT_PACK)
    parser.add_argument("--windows", type=int, default=5)
    args = parser.parse_args()
    if not 1 <= args.windows <= 5:
        raise ValueError("This bounded POC accepts the first 1–5 minutes only")
    pipeline = ROOT / f"artifacts/post-live-runs/2026-08-23/sermon_{SOURCE_ID}/pipeline"
    source = pipeline / "source_clip.m4a"
    source_hash = sha256(source)
    authorization = json.loads(AUTHORIZATION.read_text())
    if not authorized_source(authorization, SOURCE_ID, source_hash, "voice_training"):
        raise ValueError("Training purpose/source is not authorized")
    corpus = args.pack / "training-candidates"
    corpus.mkdir(parents=True, exist_ok=True)
    canonical = " ".join(item["text"] for item in json.loads((pipeline / "asr_reference_chunks.json").read_text()))
    from huggingface_hub import snapshot_download
    from mlx_audio.stt.utils import load_model
    import mlx.core as mx
    import numpy as np
    import soundfile as sf
    records = []
    asr = load_model(snapshot_download(repo_id=ASR[0], revision=ASR[1], local_files_only=True))
    for i in range(args.windows):
        window = corpus / f"window-{i:02d}.wav"
        if not window.exists():
            subprocess.run(["ffmpeg", "-v", "error", "-n", "-i", str(source), "-ss", str(i * 60), "-t", "60", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(window)], check=True)
        receipt = corpus / f"window-{i:02d}.asr.json"
        if receipt.exists():
            record = json.loads(receipt.read_text())
            if record["sourceSha256"] != source_hash or record["audioSha256"] != sha256(window):
                raise ValueError("Stale source window")
        else:
            text = asr.generate(str(window), language="English", max_tokens=2048).text
            record = {"sourceId": SOURCE_ID, "sourceSha256": source_hash, "audioSha256": sha256(window), "window": str(window), "offset": i * 60, "text": text, "model": ASR[0], "revision": ASR[1]}
            write_json(receipt, record)
        records.append(record)
        mx.clear_cache()
        print(f"English window {i + 1}/{args.windows}", flush=True)
    del asr
    mx.clear_cache()
    aligner = load_model(snapshot_download(repo_id=ALIGNER[0], revision=ALIGNER[1], local_files_only=True))
    candidates, exclusions = [], []
    for i, record in enumerate(records):
        aligned = aligner.generate(record["window"], text=record["text"], language="English")
        write_json(corpus / f"window-{i:02d}.alignment.json", {"model": ALIGNER[0], "revision": ALIGNER[1], "audioSha256": record["audioSha256"], "words": aligned.segments})
        units, rejected = group_candidates(sentence_spans(record["text"], aligned.segments), canonical)
        exclusions.extend({**unit, "windowOffset": record["offset"]} for unit in rejected)
        for j, unit in enumerate(units):
            # Small context margins need listening review for neighboring phonemes.
            start = max(0, record["offset"] + unit["start"] - 0.08)
            end = min(record["offset"] + 60, record["offset"] + unit["end"] + 0.08)
            path = corpus / f"eric-{i:02d}-{j:02d}.wav"
            if not path.exists():
                subprocess.run(["ffmpeg", "-v", "error", "-n", "-i", str(source), "-ss", str(start), "-t", str(end - start), "-ac", "1", "-ar", "24000", "-c:a", "pcm_s24le", str(path)], check=True)
            waveform, rate = sf.read(path)
            if not np.isfinite(waveform).all() or np.max(np.abs(waveform)) >= 0.999:
                exclusions.append({**unit, "reasons": ["nonfinite_or_near_fullscale_audio"]})
                continue
            candidates.append({"id": path.stem, "speakerCandidate": "eric-self-intro-20260823", "speakerTurnsVerified": False,
                "sourceId": SOURCE_ID, "sourceSha256": source_hash, "audio": str(path), "audioSha256": sha256(path), "text": unit["text"], "language": "English",
                "sourceStartSeconds": start, "sourceEndSeconds": end, "durationSeconds": len(waveform) / rate, "ref_audio": str(args.pack / "eric-reference.wav"),
                "authorizationId": authorization["authorizationId"], "textEvidence": "local_asr_agrees_with_existing_english_after_case_punctuation_normalization",
                "alignmentEvidence": f"window-{i:02d}.alignment.json", "humanReviewStatus": "pending", "trainingAdmission": "pending", "split": "unassigned_same_sermon_group", "status": "machine_candidate"})
        mx.clear_cache()
        print(f"Aligned window {i + 1}/{args.windows}; candidates {len(candidates)}", flush=True)
    (corpus / "candidates.jsonl").write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in candidates))
    write_json(corpus / "report.json", {"sourceId": SOURCE_ID, "sourceSha256": source_hash, "candidateCount": len(candidates), "candidateSeconds": sum(c["durationSeconds"] for c in candidates),
        "trainingAdmittedCount": 0, "status": "needs_speaker_and_audio_text_review", "exclusions": exclusions, "windows": args.windows,
        "limitations": ["Only one sermon; no independent validation split", "First and last sentences of each 60s window may be cut; unmatched units excluded", "Speaker candidate from self-introduction; no diarization or individual clip approval"]})
    print(json.dumps({"candidateCount": len(candidates), "candidateSeconds": round(sum(c["durationSeconds"] for c in candidates), 2), "trainingAdmitted": 0}), flush=True)


if __name__ == "__main__":
    main()
