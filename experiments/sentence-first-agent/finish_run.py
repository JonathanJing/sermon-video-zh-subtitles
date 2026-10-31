#!/usr/bin/env python3
"""Pull a run back from Spark, merge, score and render previews (experiment only).

Reads ``clip.json`` (written by prepare_clip.py, or copied with --clip-from) for the
media path and the clip's media start and end. Steps, each skipped when its output
already exists unless noted:

  pull     with --remote USER@HOST:/dir, copy tts/, tts-run.log, asr.jsonl, asr-run.log
  merge    merge_track.py -> track.wav + schedule.json (always rerun; it is cheap)
  score    asr_check.py score -> asr-report.json (always rerun when asr.jsonl exists)
  video    ffmpeg: clip video + track.wav -> dub.mp4 (skip with --no-video)
  preview  dub.mp4 -> dub-preview-640.mp4, small enough to send to a phone;
           --preview-encoder auto|quality|fast|hardware (auto: hardware on macOS,
           else fast; the result must contain a video stream or it falls back)

Prints the worst lag, sentences over 8 s, dub/source length ratio, TTS speed and
the ASR sentences below --show-below.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess
import sys
import wave

from runlog import mark, write_outcome, write_timings

HERE = Path(__file__).resolve().parent


def py(*args) -> str:
    return subprocess.run([sys.executable, *map(str, args)], check=True, capture_output=True, text=True).stdout.strip()


# Preview encode settings, measured on a 55-min 640x360 preview (258 s with quality):
# decode of the 4K AV1 source dominates; fast/hardware cut the encoder part and land
# around 60-70% of the quality time (larger files). "hardware" replaces the encoder
# only, because AV1 hardware decode is not available on this host.
PREVIEW_ENCODER_FLAGS = {
    "quality": ["-c:v", "libx264", "-preset", "veryfast", "-crf", "30"],
    "fast": ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "30"],
    "hardware": ["-c:v", "h264_videotoolbox", "-b:v", "200k"],
}


def choose_preview_encoder(mode: str, platform: str, hardware_available: bool) -> str:
    """auto: hardware on macOS when the encoder exists, else fast. Explicit modes stay."""
    if mode != "auto":
        return mode
    return "hardware" if platform == "darwin" and hardware_available else "fast"


def hardware_encoder_available() -> bool:
    try:
        proc = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return "h264_videotoolbox" in proc.stdout


def preview_has_video(path: Path) -> bool:
    try:
        proc = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                               "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path)],
                              capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0 and "video" in proc.stdout


def build_preview(run: Path, mode: str) -> str:
    available = hardware_encoder_available() if mode == "auto" else False
    encoder = choose_preview_encoder(mode, sys.platform, available)
    out = run / "dub-preview-640.mp4"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(run / "dub.mp4"),
                    "-vf", "scale=640:-2", *PREVIEW_ENCODER_FLAGS[encoder],
                    "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(out)], check=True)
    if not preview_has_video(out):
        out.unlink(missing_ok=True)
        if encoder == "quality":
            raise SystemExit("preview encode produced no video stream")
        print(f"preview: {encoder} produced no video stream; falling back to quality", file=sys.stderr)
        return build_preview(run, "quality")
    return encoder


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--remote", help="USER@HOST:/path/to/the/spark/work/dir to pull from")
    parser.add_argument("--clip-from", type=Path, help="run directory whose clip.json to copy (second locale)")
    parser.add_argument("--gap", type=float, default=0.25)
    parser.add_argument("--no-video", action="store_true")
    parser.add_argument("--preview-encoder", choices=("auto", "quality", "fast", "hardware"), default="auto",
                        help="preview encode settings; auto = hardware on macOS, else fast; "
                             "quality is the old libx264 veryfast/crf30 path")
    parser.add_argument("--show-below", type=float, default=0.97)
    args = parser.parse_args()
    run = args.run
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    mark(run, "l3.finish", "started")

    if args.clip_from and not (run / "clip.json").exists():
        shutil.copy2(args.clip_from / "clip.json", run / "clip.json")
    if args.remote:
        sources = [f"{args.remote}/{name}" for name in ("tts", "tts-run.log", "asr.jsonl", "asr-run.log")]
        subprocess.run(["scp", "-q", "-o", "BatchMode=yes", "-r", sources[0], sources[1], str(run)], check=True)
        # ASR is optional (2026-10-28: no longer a review condition); pull it quietly when present.
        subprocess.run(["scp", "-q", "-o", "BatchMode=yes", sources[2], sources[3], str(run)],
                       check=False, capture_output=True)
    wavs = sorted((run / "tts").glob("s*.wav"))
    print(json.dumps({"run": str(run), "wavs": len(wavs)}))

    print(py(HERE / "merge_track.py", "--sentences", run / "sentences.jsonl", "--tts", run / "tts",
             "--out", run / "track.wav", "--schedule", run / "schedule.json", "--gap", args.gap))
    if (run / "asr.jsonl").exists():
        print(py(HERE / "asr_check.py", "score", "--speech", run / "speech.jsonl", "--asr", run / "asr.jsonl",
                 "--report", run / "asr-report.json"))

    if not args.no_video:
        clip = json.loads((run / "clip.json").read_text(encoding="utf-8"))
        if not (run / "dub.mp4").exists():
            subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", f"{clip['mediaStart']:.3f}",
                            "-to", f"{clip['mediaEnd']:.3f}", "-i", clip["media"], "-i", str(run / "track.wav"),
                            "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                            str(run / "dub.mp4")], check=True)
        if not (run / "dub-preview-640.mp4").exists():
            print("preview encoder:", build_preview(run, args.preview_encoder))
        print("preview MB:", round((run / "dub-preview-640.mp4").stat().st_size / 1e6, 1))

    rows = json.loads((run / "schedule.json").read_text(encoding="utf-8"))["sentences"]
    placed = [r for r in rows if r.get("lagSeconds") is not None]
    print("worst lag:")
    for r in sorted(placed, key=lambda r: -r["lagSeconds"])[:6]:
        m, s = divmod(int(r["actualStart"]), 60)
        print(f'  {r["id"]} at {m}:{s:02d} lag={r["lagSeconds"]:.2f} dub={r["dubSeconds"]:.2f} src={r["sourceSeconds"]:.2f}')
    over = [r for r in placed if r["lagSeconds"] > 8]
    print("over 8 s:", ", ".join(f'{r["id"]}({r["lagSeconds"]:.1f})' for r in over) or "none")
    total_dub = sum(r["dubSeconds"] for r in placed)
    total_src = sum(r["sourceSeconds"] for r in placed)
    line = f"dub {total_dub:.1f}s / source speech {total_src:.1f}s = {total_dub / total_src:.2f}"
    log = run / "tts/tts-log.jsonl"
    if log.exists():
        entries = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines() if l.strip()]
        wall = sum(e["wallSeconds"] for e in entries)
        line += f"; tts wall {wall:.1f}s for {len(entries)} sentences ({total_dub / wall:.2f}x realtime, no model load)"
    print(line)
    asr_mean = None
    if (run / "asr-report.json").exists():
        report = json.loads((run / "asr-report.json").read_text(encoding="utf-8"))
        scores = [x["similarity"] for x in report["sentences"]]
        asr_mean = round(sum(scores) / len(scores), 3) if scores else None
        low = [x for x in report["sentences"] if x["similarity"] < args.show_below]
        print(f"ASR below {args.show_below}: {len(low)}")
        for x in sorted(low, key=lambda x: x["similarity"]):
            print(f'  {x["id"]} {x["similarity"]:.3f}\n    want: {x["expected"]}\n    got:  {x["recognized"]}')
    with wave.open(str(run / "track.wav"), "rb") as handle:
        track_seconds = round(handle.getnframes() / handle.getframerate(), 2)
    locale = json.loads((run / "review.json").read_text(encoding="utf-8")).get("locale") if (run / "review.json").exists() else None
    tts_wall = None
    if log.exists():
        entries = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines() if l.strip()]
        tts_wall = round(sum(e["wallSeconds"] for e in entries), 1)
    review_mp3 = run / "review.mp3"
    if not review_mp3.exists() or review_mp3.stat().st_mtime < (run / "track.wav").stat().st_mtime:
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(run / "track.wav"),
                        "-c:a", "libmp3lame", "-b:a", "96k", str(review_mp3)], check=True)
    review_player = None
    try:
        from review_player import build_player
        player_info = build_player(run, run / "review-player.html", audio=review_mp3,
                                   title=f"{run.name} 逐句听审")
        review_player = {"html": str(run / "review-player.html"), "rows": player_info["rows"]}
        print(json.dumps({"reviewMp3MB": round(review_mp3.stat().st_size / 1e6, 1),
                          "reviewPlayer": player_info}, ensure_ascii=False))
    except Exception as exc:
        print("review player skipped:", exc)
    mark(run, "l3.finish", "finished")
    write_outcome(run, status="track_ready_for_review", delivery="four_layer_release", locale=locale,
                  trackSeconds=track_seconds, ttsWallSeconds=tts_wall,
                  realtime=round(track_seconds / tts_wall, 2) if tts_wall else None,
                  asrMean=asr_mean, startedAt=started_at,
                  endedAt=datetime.now(timezone.utc).isoformat(timespec="seconds"), published=False,
                  reviewMp3=str(review_mp3), reviewPlayer=review_player,
                  note="track merged and scored; audio alignment and review materials done in the same pass")
    write_timings(run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
