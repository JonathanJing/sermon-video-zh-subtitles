#!/usr/bin/env python3
"""Measure English low-energy pauses independently of target-language text.

This is a Layer 1 POC sidecar, not a revision of the frozen English Source
Package. Word alignment proposes which words border a pause; PCM energy is
separate evidence. A gap in the aligner alone never becomes a supported pause.
"""
from __future__ import annotations

import argparse
import array
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_multilingual_prosody_poc import canonical_sha, read_object, write_json

SCHEMA = "sermon-english-acoustic-pause-evidence-poc-v1"
SAMPLE_RATE = 16000
HOP_SECONDS = 0.01
FRAME_SECONDS = 0.02
BELOW_P95_DB = 11.0
MIN_LOW_ENERGY_SECONDS = 0.25
MIN_SUPPORTED_GAP_SECONDS = 0.25
MIN_GAP_OVERLAP_SECONDS = 0.22


def decode_mono_pcm(media_path: Path) -> array.array:
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(media_path), "-ac", "1", "-ar", str(SAMPLE_RATE),
         "-f", "s16le", "-acodec", "pcm_s16le", "-"],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if len(result.stdout) < 2 or len(result.stdout) % 2:
        raise ValueError("English source failed PCM decode")
    samples = array.array("h")
    samples.frombytes(result.stdout)
    if sys.byteorder != "little":
        samples.byteswap()
    return samples


def low_energy_intervals(samples: array.array) -> tuple[list[dict], float]:
    hop = round(SAMPLE_RATE * HOP_SECONDS)
    frame = round(SAMPLE_RATE * FRAME_SECONDS)
    rms = []
    for position in range(0, len(samples) - frame + 1, hop):
        window = samples[position:position + frame]
        rms.append(math.sqrt(sum(value * value for value in window) / frame) / 32768)
    if not rms or max(rms) <= 0:
        raise ValueError("English source has no measurable audio")
    reference = sorted(rms)[int((len(rms) - 1) * 0.95)]
    threshold = reference * 10 ** (-BELOW_P95_DB / 20)
    active_start = None
    intervals = []
    for index, value in enumerate(rms + [math.inf]):
        if value <= threshold and active_start is None:
            active_start = index
        elif value > threshold and active_start is not None:
            start = active_start * HOP_SECONDS
            end = min(len(samples) / SAMPLE_RATE, index * HOP_SECONDS + FRAME_SECONDS)
            if end - start >= MIN_LOW_ENERGY_SECONDS:
                intervals.append({"startSeconds": round(start, 6), "endSeconds": round(end, 6),
                                  "durationSeconds": round(end - start, 6)})
            active_start = None
    return intervals, round(20 * math.log10(threshold), 3)


def boundary_evidence(words: list[dict], intervals: list[dict], origin: float) -> list[dict]:
    rows = []
    for left, right in zip(words, words[1:]):
        gap_start = float(left["end"]) - origin
        gap_end = float(right["start"]) - origin
        gap = max(0.0, gap_end - gap_start)
        candidates = []
        for interval in intervals:
            overlap = max(0.0, min(gap_end, interval["endSeconds"]) - max(gap_start, interval["startSeconds"]))
            if overlap > 0:
                candidates.append((overlap, interval))
        overlap, interval = max(candidates, key=lambda item: item[0]) if candidates else (0.0, None)
        supported = gap >= MIN_SUPPORTED_GAP_SECONDS and overlap >= MIN_GAP_OVERLAP_SECONDS
        conflict = (not supported and gap < MIN_SUPPORTED_GAP_SECONDS and any(
            item["durationSeconds"] >= 0.5
            and item["startSeconds"] <= gap_start <= item["endSeconds"] for item in intervals))
        rows.append({
            "afterWordId": left["wordId"], "beforeWordId": right["wordId"],
            "afterText": left["text"], "beforeText": right["text"],
            "alignmentGapSeconds": round(gap, 6),
            "measuredLowEnergyOverlapSeconds": round(overlap, 6),
            "measuredLowEnergyInterval": interval,
            "classification": ("supported_pause_candidate" if supported else
                               "alignment_acoustic_conflict" if conflict else
                               "alignment_gap_only" if gap >= MIN_SUPPORTED_GAP_SECONDS else "no_supported_pause"),
            "humanListeningStatus": "pending" if supported or conflict else "not_requested",
        })
    return rows


def extract(media_path: Path, anchor_path: Path, *, expected_media_sha256: str) -> dict:
    media_hash = hashlib.sha256(media_path.read_bytes()).hexdigest()
    if media_hash != expected_media_sha256:
        raise ValueError("English source media hash differs from expected source")
    anchor = read_object(anchor_path)
    if anchor.get("schemaVersion") != "sermon-sentence-anchor-manifest-v2":
        raise ValueError("Requires frozen Layer 1 word anchors")
    source_units = [unit for unit in anchor["sourceUnits"] if unit["sourceUnitId"].startswith("block-59-u")]
    if not source_units:
        raise ValueError("No selected English source units")
    words = [word for unit in source_units for word in unit["words"]]
    origin = float(source_units[0]["start"])
    samples = decode_mono_pcm(media_path)
    duration = len(samples) / SAMPLE_RATE
    if abs(duration - (float(source_units[-1]["end"]) - origin)) > 0.15:
        raise ValueError("English source audio does not match anchor window duration")
    intervals, threshold = low_energy_intervals(samples)
    rows = boundary_evidence(words, intervals, origin)
    return {
        "schemaVersion": SCHEMA,
        "scope": "layer_1_english_source_acoustic_pause_shadow_poc",
        "status": "machine_pause_candidates_human_listening_pending",
        "humanApproval": False,
        "productionEligible": False,
        "sourceMediaSha256": media_hash,
        "anchorManifestJsonSha256": canonical_sha(anchor),
        "sourceWindow": {"startSeconds": origin, "endSeconds": float(source_units[-1]["end"]),
                         "audioDurationSeconds": round(duration, 6)},
        "measurement": {"method": "mono_pcm_16khz_20ms_rms_10ms_hop",
                        "thresholdDbfs": threshold, "thresholdBelowP95Db": BELOW_P95_DB,
                        "minimumLowEnergySeconds": MIN_LOW_ENERGY_SECONDS,
                        "minimumSupportedGapSeconds": MIN_SUPPORTED_GAP_SECONDS,
                        "minimumGapOverlapSeconds": MIN_GAP_OVERLAP_SECONDS,
                        "caveat": "Low energy and word alignment are candidate evidence; neither proves a rhetorical pause or its intended meaning."},
        "lowEnergyIntervals": intervals,
        "boundaries": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--media", required=True, type=Path)
    parser.add_argument("--anchor", required=True, type=Path)
    parser.add_argument("--expected-media-sha256", required=True)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError(f"Pause evidence already exists: {args.out}")
    evidence = extract(args.media, args.anchor, expected_media_sha256=args.expected_media_sha256)
    write_json(args.out, evidence)
    print(json.dumps({"status": evidence["status"],
                      "supportedPauseCandidates": sum(row["classification"] == "supported_pause_candidate" for row in evidence["boundaries"]),
                      "alignmentAcousticConflicts": sum(row["classification"] == "alignment_acoustic_conflict" for row in evidence["boundaries"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
