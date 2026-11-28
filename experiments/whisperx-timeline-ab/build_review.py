#!/usr/bin/env python3
"""Render local listening snippets for the WhisperX timeline A/B review queue.

The page is a review aid, not evidence of human approval. Each item plays one
short audio span and keeps the arm labels behind a disclosure so the first
listen is not anchored by the numbers.
"""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
import subprocess


def cut(audio: Path, start: float, end: float, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        return
    subprocess.run([
        "ffmpeg", "-v", "error", "-n", "-ss", f"{start:.4f}", "-t", f"{max(end - start, 0.2):.4f}",
        "-i", str(audio), "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(target),
    ], check=True)


def item_html(index: int, kind: str, label: str, audio_name: str, detail: str,
              times: str) -> str:
    return f"""
    <article class="item">
      <h3>{index}. <span class="kind">{html.escape(kind)}</span> {html.escape(label)}</h3>
      <audio controls preload="none" src="{html.escape(audio_name)}"></audio>
      <details><summary>Reveal timestamps</summary><pre>{html.escape(times)}</pre></details>
      <p class="detail">{html.escape(detail)}</p>
    </article>"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    report = json.loads((args.report / "report.json").read_text(encoding="utf-8"))
    review = json.loads((args.report / "review-queue.json").read_text(encoding="utf-8"))
    args.out.mkdir(parents=True, exist_ok=True)
    blocks = []
    for index, item in enumerate(review.get("wordCandidates", []), start=1):
        snippet = item["snippet"]
        name = f"word-{index:02d}.wav"
        cut(args.audio, snippet["start"], snippet["end"], args.out / name)
        times = (f"A  {item['armA']['start']:.3f} - {item['armA']['end']:.3f}\n"
                 f"B  {item['armB']['start']:.3f} - {item['armB']['end']:.3f}\n"
                 f"MFA {item['mfa']['start']:.3f} - {item['mfa']['end']:.3f}\n"
                 f"max |arm-MFA| midpoint: {item['maxReferenceErrorSeconds']:.3f} s")
        blocks.append(item_html(index, "word", item["text"], name,
                                f"token {item['tokenIndex']} · A source {item['timingSource']}",
                                times))
    offset = len(review.get("wordCandidates", []))
    for index, item in enumerate(review.get("unitCandidates", []), start=1):
        snippet = item["snippet"]
        name = f"unit-{index:02d}.wav"
        cut(args.audio, snippet["start"], snippet["end"], args.out / name)
        times = (f"A  {item['armA']['start']:.3f} - {item['armA']['end']:.3f}\n"
                 f"B  {item['armB']['start']:.3f} - {item['armB']['end']:.3f}\n"
                 f"start shift {item['startDeltaSeconds']:.3f} s · "
                 f"end shift {item['endDeltaSeconds']:.3f} s")
        blocks.append(item_html(offset + index, "unit", item["unitId"], name,
                                item["text"], times))
    page = f"""<!doctype html>
<html lang="zh-CN"><meta charset="utf-8">
<title>WhisperX timeline A/B listening queue</title>
<style>
:root {{ color-scheme: dark; --bg:#111318; --panel:#1b1f27; --text:#e7ecf3; --muted:#9aa7b8; --accent:#7cc4ff; }}
body {{ margin:0; background:var(--bg); color:var(--text); font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
main {{ max-width:860px; margin:0 auto; padding:32px 20px 80px; }}
h1 {{ font-size:26px; margin:0 0 8px; }}
h2 {{ font-size:19px; margin:32px 0 12px; }}
p {{ color:var(--muted); }}
.item {{ background:var(--panel); border:1px solid #2b3240; border-radius:12px; padding:14px 16px; margin:12px 0; }}
.item h3 {{ font-size:16px; margin:0 0 8px; font-weight:600; }}
.kind {{ color:var(--accent); font-size:12px; text-transform:uppercase; letter-spacing:.08em; }}
audio {{ width:100%; margin:6px 0; }}
details {{ margin-top:8px; }} summary {{ cursor:pointer; color:var(--accent); }}
pre {{ background:#0d1015; padding:10px; border-radius:8px; overflow:auto; color:#d6e2f0; }}
.detail {{ margin:8px 0 0; font-size:14px; }}
</style>
<main>
<h1>WhisperX vs OpenAI Layer 1 timeline A/B</h1>
<p>2026-11-08 approved sermon source · machine comparison only · human listening pending.</p>
<p>Listen once before opening “Reveal timestamps”. The question is which boundary matches the
audible word onset/release, not which arm has the earlier number.</p>
<h2>Word disputes (top MFA disagreements)</h2>
{''.join(blocks)}
<h2>Notes</h2>
<p>MFA is a third model estimate, not human Gold. A machine review is never human approval.
The full report is <code>{html.escape(str(args.report / 'summary.md'))}</code>.</p>
</main></html>"""
    (args.out / "review.html").write_text(page, encoding="utf-8")
    print(json.dumps({"out": str(args.out / "review.html"),
                      "items": len(review.get("wordCandidates", [])) + len(review.get("unitCandidates", []))},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
