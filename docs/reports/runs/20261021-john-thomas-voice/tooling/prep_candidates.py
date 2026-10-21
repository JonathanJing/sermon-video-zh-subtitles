#!/usr/bin/env python3
"""Select John Thomas (VibeVoice speaker 1) English training clips from one podcast episode.

Runs inside the Spark speech runtime container (qwen-asr 0.0.6, CUDA). Inputs are the
staged files under <work>/source; outputs are candidates (train split), a time-held-out
validation split, every exclusion with its reason, and a frozen reference clip.
Machine selection only: nothing here is human audio/speaker review.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
from pathlib import Path

ASR = ("Qwen/Qwen3-ASR-0.6B", "5eb144179a02acc5e5ba31e748d22b0cf3e303b0")
ALIGNER = ("Qwen/Qwen3-ForcedAligner-0.6B", "c7cbfc2048c462b0d63a45797104fc9db3ad62b7")
SOURCE_HASHES = {
    "audio_24k_mono.wav": "23f08c5ccc5800e1319e8eb800e2dd186e9dadcaafaf18218215d75baf833a0d",
    "audio_16k_mono.wav": "26f2ee7bf229cd4723d0537a350dc2e1edcd505e9e80fa03410c5cbc4fb1d4b3",
    "segments.bf16.json": "cc130af715330dd1aabd44e92e02877c17195f1f96393c033bfae501ba02fc6e",
    "segments.mlx8bit.json": "0c234f522589c2e78d3101f6418781e2d6673181c1be5f39667dd82541e778dc",
    "youtube-auto.srt": "1c2e172a6161a4f3d4e35d820a3c3d533e098500dc6927ed4b1bcc1cbc30c909",
}
JOHN = 1
CONFIG = {
    "validationSplitStartSeconds": 2000.0,   # John turns starting at/after 33:20 are held out
    "mergeGapSeconds": 0.3,                   # consecutive speaker-1 segments closer than this form one turn
    "minTurnSeconds": 4.5,
    "dropTurnBoundarySentences": True,        # first/last sentence of every turn is never used
    "turnEdgeMarginSeconds": 0.4,
    "episodeEdgeExclusionSeconds": 10.0,      # intro/outro music
    "clipPadSeconds": 0.06,
    "budgetSeconds": [4.0, 15.0],
    "groupSoftSeconds": 6.0,
    "groupMaxSeconds": 12.0,
    "minVibeVoiceTokenCoverage": 0.95,
    "minYoutubeTokenCoverage": 0.85,
    "youtubeSpeakerMarkerToleranceSeconds": 0.5,
    "mlxOtherSpeakerToleranceSeconds": 0.2,
    "maxPeak": 0.999,
    "minRmsDbfs": -40.0,
    "silenceFloorDbfs": -45.0,
    "maxInternalSilenceSeconds": 1.5,
    "referenceSecondsRange": [10.0, 15.0],
}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def normalize(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())


def tokens(text):
    return [t for t in (normalize(w) for w in text.replace(">>", " ").split()) if t]


def coverage(unit, reference):
    unit, reference = tokens(unit), tokens(reference)
    if not unit:
        return 0.0
    blocks = difflib.SequenceMatcher(None, unit, reference, autojunk=False).get_matching_blocks()
    return sum(b.size for b in blocks) / len(unit)


def sentence_spans(text, words):
    """Same contract as prepare_voice_candidates.sentence_spans: exact token agreement."""
    cursor, spans = 0, []
    for match in re.finditer(r"[^.!?]+[.!?]", text):
        sentence = match.group().strip()
        toks = [normalize(t) for t in sentence.split() if normalize(t)]
        selected = words[cursor:cursor + len(toks)]
        if [normalize(w["text"]) for w in selected] != toks:
            raise ValueError("Sentence/aligner tokens disagree")
        cursor += len(toks)
        if selected:
            spans.append({"text": sentence, "start": selected[0]["start"], "end": selected[-1]["end"]})
    return spans


def group(spans):
    units, current = [], []
    def emit():
        nonlocal current
        if current:
            units.append({"text": " ".join(s["text"] for s in current), "start": current[0]["start"], "end": current[-1]["end"]})
        current = []
    for span in spans:
        if current and span["end"] - current[0]["start"] > CONFIG["groupMaxSeconds"]:
            emit()
        current.append(span)
        if current[-1]["end"] - current[0]["start"] >= CONFIG["groupSoftSeconds"]:
            emit()
    emit()
    return units


def parse_srt(path):
    cues = []
    for block in re.split(r"\n\s*\n", Path(path).read_text(encoding="utf-8-sig").strip()):
        lines = block.strip().splitlines()
        if len(lines) < 3:
            continue
        m = re.match(r"(\d+):(\d+):(\d+),(\d+) --> (\d+):(\d+):(\d+),(\d+)", lines[1])
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        start = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
        end = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
        text = " ".join(lines[2:])
        cues.append({"start": start, "end": end, "text": text, "marker": ">>" in text})
    return cues


def john_turns(segments):
    turns = []
    for seg in segments:
        if seg.get("speaker_id") != JOHN:
            continue
        if turns and seg["start_time"] - turns[-1]["end"] < CONFIG["mergeGapSeconds"] and turns[-1]["lastIndex"] == seg["_i"] - 1:
            turns[-1]["end"] = seg["end_time"]
            turns[-1]["text"] += " " + seg["text"]
            turns[-1]["lastIndex"] = seg["_i"]
        else:
            turns.append({"start": seg["start_time"], "end": seg["end_time"], "text": seg["text"], "lastIndex": seg["_i"]})
    for i, t in enumerate(turns):
        t["turnId"] = f"turn-{i:03d}"
    return turns


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()
    work = args.work.resolve()
    src = work / "source"
    for name, digest in SOURCE_HASHES.items():
        if sha256(src / name) != digest:
            raise ValueError(f"Source changed: {name}")
    out = work / "prep"
    if (out / "prep-report.json").exists():
        raise ValueError("Preserve the completed preparation; use a new work directory")
    (out / "clips").mkdir(parents=True, exist_ok=True)

    import numpy as np
    import soundfile as sf
    import torch
    from huggingface_hub import snapshot_download
    from qwen_asr import Qwen3ASRModel, Qwen3ForcedAligner

    audio16, rate16 = sf.read(src / "audio_16k_mono.wav", dtype="float32")
    audio24, rate24 = sf.read(src / "audio_24k_mono.wav", dtype="float32")
    if rate16 != 16000 or rate24 != 24000 or audio16.ndim != 1 or audio24.ndim != 1:
        raise ValueError("Unexpected staged audio format")
    episode = len(audio24) / rate24
    bf16 = json.loads((src / "segments.bf16.json").read_text())
    for i, seg in enumerate(bf16):
        seg["_i"] = i
    mlx = [{"start_time": s.get("start_time", s.get("start")), "end_time": s.get("end_time", s.get("end")), "speaker_id": s.get("speaker_id")}
           for s in json.loads((src / "segments.mlx8bit.json").read_text())]
    cues = parse_srt(src / "youtube-auto.srt")
    markers = [c["start"] for c in cues if c["marker"]]

    turns = john_turns(bf16)
    exclusions = []
    usable = []
    for t in turns:
        dur = t["end"] - t["start"]
        split = "validation" if t["start"] >= CONFIG["validationSplitStartSeconds"] else "train"
        t["split"] = split
        if split == "train" and t["end"] > CONFIG["validationSplitStartSeconds"]:
            exclusions.append({"turnId": t["turnId"], "start": t["start"], "end": t["end"], "reasons": ["crosses_validation_split"]})
            continue
        if dur < CONFIG["minTurnSeconds"]:
            exclusions.append({"turnId": t["turnId"], "start": t["start"], "end": t["end"], "seconds": dur, "reasons": ["turn_shorter_than_min"]})
            continue
        usable.append(t)

    kwargs = dict(dtype=torch.bfloat16, device_map="cuda:0")
    asr_path = snapshot_download(repo_id=ASR[0], revision=ASR[1], local_files_only=True)
    cache = out / "turn-asr-alignment.json"
    cached = json.loads(cache.read_text()) if cache.exists() else None
    if cached and cached["asr"] == list(ASR) and cached["aligner"] == list(ALIGNER) and \
            [(r["turnId"], r["start"], r["end"]) for r in cached["turns"]] == [(t["turnId"], t["start"], t["end"]) for t in usable]:
        # Reuse the verified ASR/alignment of an earlier attempt over identical turns.
        per_turn = cached["turns"]
        for t, row in zip(usable, per_turn):
            t["asrText"] = row["asrText"]
        print(json.dumps({"reused": str(cache.name), "turns": len(per_turn)}), flush=True)
    else:
        model = Qwen3ASRModel.from_pretrained(asr_path, max_new_tokens=2048, max_inference_batch_size=1, **kwargs)
        for n, t in enumerate(usable):
            piece = audio16[int(t["start"] * rate16):int(t["end"] * rate16)]
            t["asrText"] = model.transcribe(audio=(piece, rate16), language="English")[0].text
            print(json.dumps({"asr": t["turnId"], "done": n + 1, "of": len(usable)}), flush=True)
        del model
        torch.cuda.empty_cache()

        aligner_path = snapshot_download(repo_id=ALIGNER[0], revision=ALIGNER[1], local_files_only=True)
        aligner = Qwen3ForcedAligner.from_pretrained(aligner_path, **kwargs)
        per_turn = []
        for t in usable:
            piece = audio16[int(t["start"] * rate16):int(t["end"] * rate16)]
            aligned = aligner.align(audio=(piece, rate16), text=t["asrText"], language="English")[0]
            words = [{"text": w.text, "start": float(w.start_time), "end": float(w.end_time)} for w in aligned]
            per_turn.append({"turnId": t["turnId"], "start": t["start"], "end": t["end"], "split": t["split"], "vibevoiceText": t["text"], "asrText": t["asrText"], "words": words})
        write_json(cache, {"asr": list(ASR), "aligner": list(ALIGNER), "turns": per_turn})
        del aligner
        torch.cuda.empty_cache()

    candidates = {"train": [], "validation": []}
    for t, row in zip(usable, per_turn):
        try:
            spans = sentence_spans(t["asrText"], row["words"])
        except ValueError:
            exclusions.append({"turnId": t["turnId"], "start": t["start"], "end": t["end"], "reasons": ["tokenizer_alignment_mismatch"]})
            continue
        dur = t["end"] - t["start"]
        dropped = spans[:1] + spans[-1:] if len(spans) > 1 else spans
        for s in dropped:
            exclusions.append({"turnId": t["turnId"], "start": t["start"] + s["start"], "end": t["start"] + s["end"], "text": s["text"], "reasons": ["turn_boundary_sentence"]})
        inner = spans[1:-1]
        kept = []
        for s in inner:
            if s["start"] < CONFIG["turnEdgeMarginSeconds"] or s["end"] > dur - CONFIG["turnEdgeMarginSeconds"]:
                exclusions.append({"turnId": t["turnId"], "start": t["start"] + s["start"], "end": t["start"] + s["end"], "text": s["text"], "reasons": ["within_turn_edge_margin"]})
            else:
                kept.append(s)
        for j, unit in enumerate(group(kept)):
            start = t["start"] + unit["start"] - CONFIG["clipPadSeconds"]
            end = t["start"] + unit["end"] + CONFIG["clipPadSeconds"]
            seconds = end - start
            reasons = []
            lo, hi = CONFIG["budgetSeconds"]
            if not lo <= seconds <= hi:
                reasons.append("outside_4_to_15_second_budget")
            if start < CONFIG["episodeEdgeExclusionSeconds"] or end > episode - CONFIG["episodeEdgeExclusionSeconds"]:
                reasons.append("episode_edge_music_window")
            vv = coverage(unit["text"], t["text"])
            if vv < CONFIG["minVibeVoiceTokenCoverage"]:
                reasons.append("vibevoice_text_disagreement")
            yt_text = " ".join(c["text"] for c in cues if c["end"] > start - 2 and c["start"] < end + 2)
            yt = coverage(unit["text"], yt_text)
            if yt < CONFIG["minYoutubeTokenCoverage"]:
                reasons.append("youtube_caption_disagreement")
            tol = CONFIG["youtubeSpeakerMarkerToleranceSeconds"]
            near_markers = [m for m in markers if start - tol <= m <= end + tol]
            if near_markers:
                reasons.append("youtube_speaker_change_marker")
            mtol = CONFIG["mlxOtherSpeakerToleranceSeconds"]
            other = [s for s in mlx if s.get("speaker_id") != JOHN and s["end_time"] > start - mtol and s["start_time"] < end + mtol]
            if other:
                reasons.append("mlx_diarization_other_speaker_or_nonspeech")
            clip = audio24[int(round(start * rate24)):int(round(end * rate24))]
            peak = float(np.max(np.abs(clip))) if len(clip) else 0.0
            rms = float(20 * np.log10(np.sqrt(np.mean(clip ** 2)) + 1e-12)) if len(clip) else -200.0
            frame = int(0.02 * rate24)
            frames = clip[:len(clip) // frame * frame].reshape(-1, frame)
            quiet = 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-12) < CONFIG["silenceFloorDbfs"]
            longest, run = 0, 0
            for q in quiet:
                run = run + 1 if q else 0
                longest = max(longest, run)
            silence = longest * 0.02
            if not np.isfinite(clip).all() or peak >= CONFIG["maxPeak"]:
                reasons.append("nonfinite_or_near_fullscale_audio")
            if rms < CONFIG["minRmsDbfs"]:
                reasons.append("too_quiet")
            if silence > CONFIG["maxInternalSilenceSeconds"]:
                reasons.append("long_internal_silence")
            record = {"turnId": t["turnId"], "split": t["split"], "text": unit["text"], "sourceStartSeconds": round(start, 3), "sourceEndSeconds": round(end, 3),
                      "durationSeconds": round(len(clip) / rate24, 3), "vibevoiceCoverage": round(vv, 4), "youtubeCoverage": round(yt, 4),
                      "youtubeMarkersNear": near_markers, "mlxOtherSegments": [[s["start_time"], s["end_time"], s.get("speaker_id")] for s in other],
                      "peak": round(peak, 4), "rmsDbfs": round(rms, 2), "longestSilenceSeconds": round(silence, 2)}
            if reasons:
                exclusions.append({**record, "reasons": reasons})
                continue
            name = f"clips/{t['split']}-{t['turnId']}-{j:02d}.wav"
            sf.write(out / name, clip, rate24, subtype="PCM_24")
            candidates[t["split"]].append({**record, "file": f"prep/{name}", "sha256": sha256(out / name), "language": "English", "speaker": "John Thomas",
                                           "speakerEvidence": "vibevoice_speaker_1_user_confirmed_mapping", "speakerTurnsVerified": False,
                                           "humanReviewStatus": "pending", "productionTrainingAdmission": False})

    train = candidates["train"]
    pool = [c for c in train if CONFIG["referenceSecondsRange"][0] <= c["durationSeconds"] <= CONFIG["referenceSecondsRange"][1]]
    if not pool:
        raise ValueError("No 10-15 s training clip available for the reference")
    median = float(np.median([c["rmsDbfs"] for c in train]))
    pool.sort(key=lambda c: (abs(c["rmsDbfs"] - median), c["longestSilenceSeconds"], -c["youtubeCoverage"], c["sourceStartSeconds"]))
    model = Qwen3ASRModel.from_pretrained(asr_path, max_new_tokens=512, max_inference_batch_size=1, **kwargs)
    reference = None
    checks = []
    for c in pool[:5]:
        wave, rate = sf.read(work / c["file"], dtype="float32")
        heard = model.transcribe(audio=(wave, rate), language="English")[0].text
        ok = normalize(heard) == normalize(c["text"])
        checks.append({"file": c["file"], "asrText": heard, "matches": ok})
        if ok:
            reference = c
            break
    if reference is None:
        raise ValueError("No reference candidate re-transcribed exactly; inspect")
    write_json(out / "reference-asr-check.json", {"asr": list(ASR), "checks": checks, "selectionRule": "train clip 10-15 s, RMS closest to train median, then shortest silence; first exact re-transcription"})

    (out / "candidates.jsonl").write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in train))
    (out / "validation.jsonl").write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in candidates["validation"]))
    reason_counts = {}
    for e in exclusions:
        for r in e["reasons"]:
            reason_counts[r] = reason_counts.get(r, 0) + 1
    report = {"schemaVersion": "john-thomas-voice-prep-v1", "config": CONFIG, "asr": list(ASR), "aligner": list(ALIGNER), "sourceHashes": SOURCE_HASHES,
              "johnTurns": len(turns), "johnTurnSeconds": round(sum(t["end"] - t["start"] for t in turns), 2), "turnsTranscribed": len(usable),
              "train": {"count": len(train), "seconds": round(sum(c["durationSeconds"] for c in train), 2)},
              "validation": {"count": len(candidates["validation"]), "seconds": round(sum(c["durationSeconds"] for c in candidates["validation"]), 2)},
              "reference": {"file": reference["file"], "sha256": reference["sha256"], "text": reference["text"], "durationSeconds": reference["durationSeconds"],
                            "sourceStartSeconds": reference["sourceStartSeconds"]},
              "exclusionReasonCounts": reason_counts, "exclusions": exclusions, "trainingAdmittedCount": 0,
              "limitations": ["Single podcast episode: engineering smoke only, no generalization claim",
                              "Speaker identity is diarization plus a user-confirmed label mapping, not per-clip human review",
                              "Machine alignment and caption agreement are not human audio review",
                              "Overlapping backchannels are screened only through MLX diarization and YouTube >> markers"]}
    write_json(out / "prep-report.json", report)
    print(json.dumps({k: report[k] for k in ["train", "validation", "reference", "exclusionReasonCounts"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
