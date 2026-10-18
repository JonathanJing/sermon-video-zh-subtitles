#!/usr/bin/env python3
"""Independently align field recordings to their full source audio.

This uses spectral-band correlation and waveform correlation, not the production
landmark matcher. Private audio stays under --data-root. The complete report is
written only to the required mode-0600 --out file; stdout carries a fixed status.

Requires ffmpeg and numpy. The repository's main .venv may not include numpy;
the Codex desktop bundled Python does. Example (from the PR worktree):
  "$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3" \
    scripts/field_venue_independent_truth.py MANIFEST --data-root CHECKOUT --out TRUTH.json
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

np = None


SAMPLE_RATE = 8000
HOP = 800
BAND_EDGES = (120, 180, 260, 370, 520, 730, 1000, 1350, 1800, 2350, 3000, 3700)
METHOD_VERSION = "band-energy-global-v1+waveform-local-v1"


def checked_file(root, entry):
    path = (root / entry["path"]).resolve()
    if not path.is_relative_to(root):
        raise ValueError("input escapes data root")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != entry["sha256"]:
        raise ValueError("input SHA-256 mismatch")
    return path


def decode(path, stream="a:0", channel="mix", start=None, duration=None):
    cmd = ["ffmpeg", "-v", "error"]
    if start is not None:
        cmd.extend(["-ss", str(start)])
    cmd.extend(["-i", str(path)])
    if duration is not None:
        cmd.extend(["-t", str(duration)])
    cmd.extend(["-map", "0:" + stream])
    if channel == "mix":
        cmd.extend(["-ac", "1"])
    elif channel in ("left", "right"):
        cmd.extend(["-af", "pan=mono|c0=c" + ("0" if channel == "left" else "1")])
    else:
        raise ValueError("unsupported channel")
    cmd.extend(["-ar", str(SAMPLE_RATE), "-f", "f32le", "pipe:1"])
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode != 0:
        raise RuntimeError("ffmpeg decode failed")
    return np.frombuffer(result.stdout, dtype="<f4")


def band_features(samples):
    size = 2048
    frames = np.lib.stride_tricks.sliding_window_view(samples, size)[::HOP]
    power = np.abs(np.fft.rfft(frames * np.hanning(size), axis=1)) ** 2
    hz = np.fft.rfftfreq(size, 1 / SAMPLE_RATE)
    bands = np.stack([
        np.log1p(power[:, (hz >= low) & (hz < high)].sum(axis=1))
        for low, high in zip(BAND_EDGES[:-1], BAND_EDGES[1:])
    ], axis=1)
    moving = np.ones(31) / 31
    bands -= np.stack([np.convolve(bands[:, col], moving, mode="same")
                       for col in range(bands.shape[1])], axis=1)
    return (bands - bands.mean(axis=0)) / (bands.std(axis=0) + 1e-6)


def global_peak(source, query):
    # FFT convolution with reversed query. Valid index k means query frame zero
    # aligns to source frame k; source and query were normalized separately.
    count = len(source) + len(query) - 1
    fft_size = 1 << (count - 1).bit_length()
    correlation = np.zeros(count)
    for col in range(source.shape[1]):
        correlation += np.fft.irfft(
            np.fft.rfft(source[:, col], fft_size)
            * np.fft.rfft(query[::-1, col], fft_size), fft_size
        )[:count]
    valid = correlation[len(query) - 1:len(source)] / (len(query) * source.shape[1])
    best = int(np.argmax(valid))
    # A nearby hop can be the same acoustic event. Exclude a +/- 2 s radius.
    others = valid.copy()
    others[max(0, best - 20):min(len(others), best + 21)] = -np.inf
    return best * HOP / SAMPLE_RATE, float(valid[best]), float(np.max(others))


def waveform_peak(source_path, source_stream, query, approximate, query_start=0):
    # Search an approximately seven-second source interval around a full-source
    # coarse peak. Source PCM begins at its requested time; query PCM begins at
    # query_start seconds from the original recording.
    source_start = max(0, int(approximate + query_start) - 3)
    source = decode(source_path, source_stream, start=source_start,
                    duration=len(query) / SAMPLE_RATE + 7).astype(np.float64)
    query = query.astype(np.float64)
    fft_size = 1 << (len(source) + len(query) - 2).bit_length()
    frequencies = np.fft.rfftfreq(fft_size, 1 / SAMPLE_RATE)
    band = (frequencies >= 200) & (frequencies <= 3500)
    correlation = np.fft.irfft(
        (np.fft.rfft(source - source.mean(), fft_size) * band)
        * np.conj(np.fft.rfft(query - query.mean(), fft_size) * band), fft_size
    )
    search = min(len(source) - len(query) + 1, 7 * SAMPLE_RATE)
    lag = int(np.argmax(correlation[:search]))
    return source_start + lag / SAMPLE_RATE - query_start


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True,
                        help="new 0600 JSON file; never overwritten")
    args = parser.parse_args()
    global np
    try:
        import numpy as numpy_module
    except ImportError as exc:
        raise SystemExit("numpy is required for independent truth alignment") from exc
    np = numpy_module
    root = args.data_root.resolve()
    manifest = json.loads(args.manifest.read_text())
    if manifest.get("schemaVersion") not in ("field-venue-fingerprint-benchmark-v1", "field-venue-fingerprint-benchmark-v2"):
        raise ValueError("unsupported manifest")
    source_path = checked_file(root, manifest["reference"])
    index_path = checked_file(root, manifest["index"])
    index_start = json.loads(index_path.read_text())["sourceStartSeconds"]
    if not isinstance(index_start, (int, float)) or not np.isfinite(index_start):
        raise ValueError("invalid index start")
    recording_paths = [(recording, checked_file(root, recording))
                       for recording in manifest["recordings"]]
    source = band_features(decode(source_path))
    report = {
        "schemaVersion": "field-venue-independent-truth-v1",
        "methodVersion": METHOD_VERSION,
        "sourceSha256": manifest["reference"]["sha256"],
        "recordings": [],
    }
    for recording, path in recording_paths:
        # The first audio stream and average of its channels define PCM sample
        # zero, matching the benchmark's `mix` channel timeline.
        samples = decode(path, recording.get("stream", "a:0"))
        coarse, best, runner = global_peak(source, band_features(samples))
        refined = waveform_peak(source_path, "a:0", samples[:20 * SAMPLE_RATE], coarse)
        segments = []
        for query_start in (0, 10, 20, 30):
            stop = (query_start + 8) * SAMPLE_RATE
            if stop <= len(samples):
                segment = samples[query_start * SAMPLE_RATE:stop]
                segments.append(waveform_peak(source_path, "a:0", segment,
                                              coarse, query_start))
        report["recordings"].append({
            "id": recording["id"],
            "recordingSha256": recording["sha256"],
            "sourceStartSecondsAbsolute": round(refined, 4),
            "indexStartSeconds": round(refined - index_start, 4),
            "segmentStartMinSeconds": round(min(segments), 4),
            "segmentStartMaxSeconds": round(max(segments), 4),
            "bestScore": round(best, 4),
            "runnerUpScore": round(runner, 4),
            "coarseSourceStartSecondsAbsolute": round(coarse, 4),
        })
    encoded = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    fd = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as output:
        output.write(encoded)
    print("independent truth written")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        # Error messages from ffmpeg and OS paths may reveal private locations.
        print(f"independent truth alignment failed: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from exc
