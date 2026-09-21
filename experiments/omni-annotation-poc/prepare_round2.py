#!/usr/bin/env python3
"""Prepare a frozen multi-sample, multi-modality Omni annotation corpus."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from schema import PROMPT, SCHEMA_VERSION, sha256


CONDITIONS = (
    {
        "id": "av-transcript",
        "video": "real-av.mp4", "audio": "real-audio.wav", "prompt": "prompt.txt",
        "expectedAudioStatus": "matched",
    },
    {
        "id": "av-no-transcript",
        "video": "real-av.mp4", "audio": "real-audio.wav", "prompt": "prompt-no-transcript.txt",
        "expectedAudioStatus": "matched", "expectedTranscriptStatus": "not_provided",
    },
    {
        "id": "audio-transcript-no-visual",
        "video": "no-visual.mp4", "audio": "real-audio.wav", "prompt": "prompt.txt",
        "expectedAudioStatus": "matched", "expectedVideoStatus": "no_visual",
    },
    {
        "id": "mismatch-av-transcript",
        "video": "real-av.mp4", "audio": "mismatch-audio.wav", "prompt": "prompt.txt",
        "expectedAudioStatus": "mismatch",
    },
    {
        "id": "silence-av-transcript",
        "video": "real-av.mp4", "audio": "silence-audio.wav", "prompt": "prompt.txt",
        "expectedAudioStatus": "no_speech",
    },
)


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_prompt(duration: float, transcript: str | None) -> str:
    text = transcript.strip() if transcript else "[not supplied]"
    return (PROMPT.replace("__DURATION__", f"{duration:.3f}")
            .replace("__TRANSCRIPT__", text))


def prepare_media(source: Path, source_start: float, duration: float, sample_dir: Path) -> None:
    input_dir = sample_dir / "input"
    review_dir = sample_dir / "review"
    input_dir.mkdir(parents=True, exist_ok=True)
    review_dir.mkdir(parents=True, exist_ok=True)
    video = input_dir / "real-av.mp4"
    audio = input_dir / "real-audio.wav"
    silence = input_dir / "silence-audio.wav"
    no_visual = input_dir / "no-visual.mp4"
    contact_sheet = review_dir / "contact-sheet.jpg"
    if not video.exists():
        run(["ffmpeg", "-v", "error", "-y", "-ss", str(source_start), "-i", str(source),
             "-t", str(duration), "-vf", "scale=1280:-2,fps=2", "-c:v", "libx264",
             "-preset", "fast", "-crf", "23", "-c:a", "aac", "-b:a", "128k", str(video)])
    if not audio.exists():
        run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vn", "-ar", "16000",
             "-ac", "1", "-c:a", "pcm_s16le", str(audio)])
    if not silence.exists():
        run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
             "anullsrc=r=16000:cl=mono", "-t", str(duration), "-c:a", "pcm_s16le", str(silence)])
    if not no_visual.exists():
        run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
             "color=c=black:s=1280x720:r=2", "-t", str(duration), "-an", "-c:v", "libx264",
             "-pix_fmt", "yuv420p", str(no_visual)])
    if not contact_sheet.exists():
        run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vf",
             "fps=1/3,scale=320:-2,tile=5x1:padding=2:margin=2", "-frames:v", "1",
             str(contact_sheet)])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-video", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    source = args.source_video.resolve()
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    selection = json.loads(args.selection.read_text(encoding="utf-8"))
    week = next(item for item in catalog["weeks"] if item["sourceId"] == selection["sourceId"])
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    duration_default = float(selection["clipDurationSeconds"])
    samples: list[dict] = []
    for item in selection["samples"]:
        duration = float(item.get("durationSeconds", duration_default))
        relative_start = float(item["relativeStartSeconds"])
        source_start = float(week["sourceStartSeconds"]) + relative_start
        sample_dir = out / item["id"]
        prepare_media(source, source_start, duration, sample_dir)
        prompt = sample_dir / "prompt.txt"
        prompt_none = sample_dir / "prompt-no-transcript.txt"
        prompt.write_text(build_prompt(duration, item["transcriptExcerpt"]), encoding="utf-8")
        prompt_none.write_text(build_prompt(duration, None), encoding="utf-8")
        review = {
            "schemaVersion": "sermon-omni-round2-human-gold-v1",
            "sampleId": item["id"],
            "reviewState": "pending_operator_listening_review",
            "verbatimEnglish": None,
            "scriptureReadingIntervals": None,
            "explanationIntervals": None,
            "audiblePauses": None,
            "notes": None,
        }
        write_json(sample_dir / "human-gold.json", review)
        samples.append({
            **item,
            "durationSeconds": duration,
            "sourceStartSeconds": source_start,
            "sourceEndSeconds": source_start + duration,
            "sourceVideoSha256": sha256(source),
            "transcriptProvenance": "existing_reading_edition_candidate_not_verbatim_gold",
            "paths": {
                "video": f'{item["id"]}/input/real-av.mp4',
                "audio": f'{item["id"]}/input/real-audio.wav',
                "silence": f'{item["id"]}/input/silence-audio.wav',
                "noVisual": f'{item["id"]}/input/no-visual.mp4',
                "prompt": f'{item["id"]}/prompt.txt',
                "promptNoTranscript": f'{item["id"]}/prompt-no-transcript.txt',
                "humanGold": f'{item["id"]}/human-gold.json',
                "contactSheet": f'{item["id"]}/review/contact-sheet.jpg',
            },
        })
    by_id = {item["id"]: item for item in samples}
    for index, item in enumerate(samples):
        donor = samples[(index + len(samples) // 2) % len(samples)]
        mismatch = out / item["id"] / "input" / "mismatch-audio.wav"
        if not mismatch.exists():
            run(["ffmpeg", "-v", "error", "-y", "-i", str(out / donor["paths"]["audio"]),
                 "-t", str(item["durationSeconds"]), "-ar", "16000", "-ac", "1",
                 "-c:a", "pcm_s16le", str(mismatch)])
        item["mismatchDonorSampleId"] = donor["id"]
        item["paths"]["mismatchAudio"] = f'{item["id"]}/input/mismatch-audio.wav'
        item["hashes"] = {name: sha256(out / path) for name, path in item["paths"].items()}
    matrix: list[dict] = []
    for sample in samples:
        sample_dir = out / sample["id"]
        for condition in CONDITIONS:
            matrix.append({
                "sampleId": sample["id"], "conditionId": condition["id"],
                "caseId": f'{sample["id"]}--{condition["id"]}',
                "durationSeconds": sample["durationSeconds"],
                "video": f'{sample["id"]}/input/{condition["video"]}',
                "audio": f'{sample["id"]}/input/{condition["audio"]}',
                "prompt": f'{sample["id"]}/{condition["prompt"]}',
                **{key: value for key, value in condition.items()
                   if key not in {"id", "video", "audio", "prompt"}},
            })
    manifest = {
        "schemaVersion": "sermon-omni-round2-corpus-v1",
        "annotationSchemaVersion": SCHEMA_VERSION,
        "reviewState": "machine_corpus_requires_operator_listening_review",
        "source": {"id": selection["sourceId"], "path": str(source), "sha256": sha256(source),
                   "sermonStartSeconds": week["sourceStartSeconds"]},
        "selection": {"path": str(args.selection.resolve()), "sha256": sha256(args.selection.resolve())},
        "catalog": {"path": str(args.catalog.resolve()), "sha256": sha256(args.catalog.resolve())},
        "sampleCount": len(samples), "conditionCount": len(CONDITIONS),
        "caseCount": len(matrix), "samples": samples, "matrix": matrix,
        "limitations": [
            "Transcript excerpts are reading-edition candidates, not verbatim human Gold.",
            "Semantic target categories are selection hypotheses until operator listening review.",
            "Model outputs remain sidecar candidates and cannot become timeline authority.",
        ],
    }
    write_json(out / "corpus-manifest.json", manifest)
    print(json.dumps({"manifest": str(out / "corpus-manifest.json"),
                      "samples": len(samples), "cases": len(matrix)}))


if __name__ == "__main__":
    main()
