#!/usr/bin/env python3
"""Cut a clip from an anchor manifest and prepare a run directory (experiment only).

Takes a ``sermon-sentence-anchor-manifest-v2`` (whose times are relative to the
approved window), the source media, the window start in media seconds and an
inclusive range of anchor unit indices. Writes into ``--run``:

  clip.wav         the clip audio, 16 kHz mono PCM16
  clip.json        media path, media start/end, unit range (finish_run.py reads it)
  words.json       word times relative to clip.wav
  sentences.jsonl  one anchor unit per line, times relative to clip.wav
  slices/          per-sentence source audio (via slice_sentences.py)
  run.md           a header for the agent's log, only if it does not exist yet

Sentence boundaries are the manifest's own units; nothing is re-split. Existing
clip.wav and slices are kept, so a rerun is cheap.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent


def unit_range(text: str) -> tuple[int, int]:
    lo, sep, hi = text.partition(":")
    if not sep:
        raise argparse.ArgumentTypeError("use LO:HI, inclusive anchor unit indices, e.g. 127:214")
    lo_i, hi_i = int(lo), int(hi)
    if lo_i < 0 or hi_i < lo_i:
        raise argparse.ArgumentTypeError("need 0 <= LO <= HI")
    return lo_i, hi_i


RELEASE_INTENT_TEMPLATE = """## 发布意图清单（发布前填，收尾逐项打勾）

一次发布意图 = 下面七件共享同一套 release 哈希的产物；同批构建、同一次 gate、同一轮 smoke。
不发布（`--no-publish`、只出审核包）时每行写「本轮不交付」并注明原因。

| # | 产物 | 本轮 | 产物位置／证据 | 状态 |
|---|---|---|---|---|
| 1 | 页面 + 三语 assets（page/content/audio/captions） | | | 未开始 |
| 2 | release 包（v2；含四产品时 v3） | | | 未开始 |
| 3 | 目录（multilingual-v5/v4/v3） | | | 未开始 |
| 4 | `/english-reference/<pageId>.json` | | | 未开始 |
| 5 | 现场对齐（sidecar + 每语指纹索引 + 目录 `audioFingerprint`/`capabilities`） | | | 未开始 |
| 6 | 研读手册 `/weekly-guides/manifest-v1.json` 条目 | | | 未开始 |
| 7 | 统计目录（`sermon-feedback-api` 函数目录） | | | 未开始 |

- 海报是独立交付，不占本清单关键路径；只在发布后制作。
- 完成信号只有一条：`sfa_publish_gate --require-guide --require-alignment` 通过，且 smoke 三语含
  `/api/session`。**不带这两个开关的 gate 通过不算完成**（2026-11-07 复盘：假 pass 导致漏三件产物）。
- 部署次数上限：一个发布意图 ≤3 次托管部署；超了先停下查发布意图是否列全。
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--anchor", type=Path, required=True, help="anchor-manifest.json (v2)")
    parser.add_argument("--media", type=Path, required=True, help="source video or audio")
    parser.add_argument("--window-start", type=float, required=True,
                        help="media seconds where anchor time 0 sits (the approved window start)")
    parser.add_argument("--units", type=unit_range, required=True, help="inclusive anchor unit indices LO:HI")
    parser.add_argument("--run", type=Path, required=True, help="run directory under artifacts/sentence-first-agent/")
    parser.add_argument("--margin-before", type=float, default=1.0)
    parser.add_argument("--margin-after", type=float, default=8.0)
    parser.add_argument("--pad", type=float, default=0.08, help="slice padding, passed to slice_sentences.py")
    parser.add_argument("--title", default="", help="one line for the run.md header")
    args = parser.parse_args()

    manifest = json.loads(args.anchor.read_text(encoding="utf-8"))
    if manifest.get("schemaVersion") != "sermon-sentence-anchor-manifest-v2":
        raise SystemExit("anchor: expected sermon-sentence-anchor-manifest-v2")
    all_units = manifest["sourceUnits"]
    lo, hi = args.units
    if hi >= len(all_units):
        raise SystemExit(f"units: manifest has {len(all_units)} units, HI must be < {len(all_units)}")
    units = all_units[lo:hi + 1]
    clip_start = units[0]["start"] - args.margin_before
    clip_end = units[-1]["end"] + args.margin_after
    media_start, media_end = args.window_start + clip_start, args.window_start + clip_end
    if media_start < 0:
        raise SystemExit("clip would start before the media; lower --margin-before")

    run = args.run
    run.mkdir(parents=True, exist_ok=True)
    clip = run / "clip.wav"
    if not clip.exists():
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", f"{media_start:.3f}", "-to", f"{media_end:.3f}",
                        "-i", str(args.media), "-map", "0:a:0", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(clip)],
                       check=True)

    words, sentences = [], []
    for i, u in enumerate(units):
        ws = [{"text": w["text"], "start": round(w["start"] - clip_start, 3), "end": round(w["end"] - clip_start, 3)}
              for w in u["words"]]
        words.extend(ws)
        nxt = units[i + 1]["start"] if i + 1 < len(units) else u["end"]
        sentences.append({"id": f"s{i + 1:04d}", "english": u["english"], "start": round(u["start"] - clip_start, 3),
                          "end": round(u["end"] - clip_start, 3), "pauseAfter": round(max(0.0, nxt - u["end"]), 3),
                          "words": ws, "sourceUnitId": u["sourceUnitId"]})
    (run / "words.json").write_text(json.dumps(words, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    with (run / "sentences.jsonl").open("w", encoding="utf-8") as out:
        for s in sentences:
            out.write(json.dumps(s, ensure_ascii=False) + "\n")
    clip_info = {"media": str(args.media.resolve()), "mediaStart": round(media_start, 3), "mediaEnd": round(media_end, 3),
                 "windowStart": args.window_start, "anchor": str(args.anchor.resolve()), "units": [lo, hi],
                 "firstSourceUnitId": units[0]["sourceUnitId"], "lastSourceUnitId": units[-1]["sourceUnitId"],
                 "marginBefore": args.margin_before, "marginAfter": args.margin_after}
    (run / "clip.json").write_text(json.dumps(clip_info, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    subprocess.run([sys.executable, str(HERE / "slice_sentences.py"), "--audio", str(clip),
                    "--sentences", str(run / "sentences.jsonl"), "--out", str(run / "slices"), "--pad", str(args.pad)],
                   check=True, stdout=subprocess.DEVNULL)

    if not (run / "run.md").exists():
        (run / "run.md").write_text(
            f"# 逐句优先代理实验：{args.title or run.name}\n\n"
            f"- 测试运行，experiment_only。\n"
            f"- 媒体：`{args.media.name}`；片段媒体时间 {media_start:.3f}–{media_end:.3f} s"
            f"（前垫 {args.margin_before} s，后垫 {args.margin_after} s）\n"
            f"- 锚点：`{args.anchor}`，单元索引 {lo}–{hi}（{units[0]['sourceUnitId']} … {units[-1]['sourceUnitId']}），"
            f"{len(sentences)} 句；分句沿用锚点单元\n\n"
            + RELEASE_INTENT_TEMPLATE + "\n## 决定与改动\n", encoding="utf-8")

    print(json.dumps({"run": str(run), "sentences": len(sentences), "clipSeconds": round(clip_end - clip_start, 3),
                      "mediaStart": round(media_start, 3), "mediaEnd": round(media_end, 3)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
