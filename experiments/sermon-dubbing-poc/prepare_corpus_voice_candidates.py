#!/usr/bin/env python3
"""Bounded three-sermon expansion, with audio alignment and English agreement."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

from poc import ROOT, sha256, write_json
from prepare_voice_candidates import ASR, ALIGNER, sentence_spans, group_candidates


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--work", type=Path, default=ROOT / "artifacts/sermon-dubbing/2026-09-05-corpus-expansion")
    args = parser.parse_args()
    work = args.work.resolve()
    plan = json.loads((work / "expansion-plan.json").read_text())
    audit = json.loads((work / "audit.json").read_text())
    if sha256(work / "audit.json") != plan["auditSha256"] or len(plan["sources"]) != 3:
        raise ValueError("Expansion requires the frozen, audited three-source plan")
    authorization = json.loads((work / "authorization.json").read_text())
    from voice_source import authorized_source
    from huggingface_hub import snapshot_download
    from mlx_audio.stt.utils import load_model
    import mlx.core as mx
    import numpy as np
    import soundfile as sf
    asr = load_model(snapshot_download(repo_id=ASR[0], revision=ASR[1], local_files_only=True))
    windows = []
    for source in plan["sources"]:
        sid = source["sourceId"]
        if source["speaker"] != plan["speaker"] or source["split"] != "train" or sid in audit["protectedIds"] or source["date"] in audit["protectedDates"]:
            raise ValueError("Reserved source cannot enter voice preparation")
        if sha256(Path(source["audio"])) != source["sha256"] or not authorized_source(authorization, sid, source["sha256"], "voice_training"):
            raise ValueError("Changed or unauthorized source")
        english = Path(source["english"])
        if sha256(english) != source["englishSha256"]:
            raise ValueError("English source changed")
        canonical = " ".join(json.loads(line)["en"] for line in english.read_text().splitlines() if line.strip())
        folder = work / "candidates" / sid
        folder.mkdir(parents=True, exist_ok=True)
        for offset in plan["windowOffsetsSeconds"]:
            path = folder / f"window-{offset}.wav"
            if not path.exists():
                subprocess.run(["ffmpeg", "-v", "error", "-n", "-ss", str(offset), "-i", source["audio"], "-t", "60", "-ac", "1", "-ar", "16000", str(path)], check=True)
            receipt = path.with_suffix(".asr.json")
            if receipt.exists():
                row = json.loads(receipt.read_text())
                if row["audioSha256"] != sha256(path) or row["sourceSha256"] != source["sha256"]:
                    raise ValueError("Stale window")
            else:
                text = asr.generate(str(path), language="English", max_tokens=2048).text
                row = {"text": text, "audioSha256": sha256(path), "sourceSha256": source["sha256"], "model": ASR[0], "revision": ASR[1]}
                write_json(receipt, row)
            windows.append((source, canonical, offset, path, row))
            mx.clear_cache()
            print(f"ASR {sid} {offset}s; {len(windows)}/15", flush=True)
    del asr
    mx.clear_cache()
    aligner = load_model(snapshot_download(repo_id=ALIGNER[0], revision=ALIGNER[1], local_files_only=True))
    candidates, exclusions = [], []
    for source, canonical, offset, path, row in windows:
        aligned = aligner.generate(str(path), text=row["text"], language="English")
        write_json(path.with_suffix(".alignment.json"), {"words": aligned.segments, "model": ALIGNER[0], "revision": ALIGNER[1], "audioSha256": sha256(path)})
        try:
            spans = sentence_spans(row["text"], aligned.segments)
        except ValueError:
            exclusions.append({"sourceId": source["sourceId"], "offset": offset, "reason": "tokenizer_alignment_mismatch"})
            continue
        # Skip both boundary sentences, even when a caption substring matches.
        spans = [s for s in spans[1:-1] if s["start"] >= 1 and s["end"] <= 59]
        units, rejected = group_candidates(spans, canonical)
        exclusions.extend({"sourceId": source["sourceId"], "offset": offset, **r} for r in rejected)
        for j, unit in enumerate(units):
            start, end = offset + unit["start"] - .06, offset + unit["end"] + .06
            clip = path.parent / f"clip-{offset}-{j:02}.wav"
            if not clip.exists():
                subprocess.run(["ffmpeg", "-v", "error", "-n", "-ss", str(start), "-i", source["audio"], "-t", str(end - start), "-ac", "1", "-ar", "24000", "-c:a", "pcm_s24le", str(clip)], check=True)
            wave, rate = sf.read(clip)
            if not np.isfinite(wave).all() or np.max(np.abs(wave)) >= .999:
                exclusions.append({"sourceId": source["sourceId"], "offset": start, "reason": "nonfinite_or_near_fullscale_audio"})
                continue
            candidates.append({"sourceId": source["sourceId"], "sourceSha256": source["sha256"], "speaker": source["speaker"], "split": "train",
                "file": str(clip.relative_to(work)), "sha256": sha256(clip), "language": "English", "text": unit["text"],
                "durationSeconds": len(wave) / rate, "sourceStartSeconds": start, "sourceEndSeconds": end,
                "speakerTurnsVerified": False, "humanReviewStatus": "pending", "productionTrainingAdmission": False})
        mx.clear_cache()
        print(f"Aligned {source['sourceId']} {offset}s; total {len(candidates)} clips", flush=True)
    (work / "candidates.jsonl").write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in candidates))
    write_json(work / "candidate-report.json", {"candidateCount": len(candidates), "candidateSeconds": sum(c["durationSeconds"] for c in candidates),
        "sourceCount": len({c["sourceId"] for c in candidates}), "exclusions": exclusions, "trainingAdmittedCount": 0,
        "limitations": ["Source speaker metadata is not per-turn diarization", "Machine alignment and English agreement are not human audio review"]})
    print(json.dumps({"clips": len(candidates), "seconds": round(sum(c["durationSeconds"] for c in candidates), 2)}), flush=True)


if __name__ == "__main__":
    main()
