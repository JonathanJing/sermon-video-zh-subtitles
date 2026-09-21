#!/usr/bin/env python3
"""Build a local, read-only listening review page for round-two human Gold."""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path


def load_result(directory: Path | None, sample_id: str) -> dict | None:
    if directory is None:
        return None
    path = directory / f"{sample_id}--av-transcript.result.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def model_html(label: str, result: dict | None) -> str:
    if not result:
        return f"<h4>{html.escape(label)}</h4><p>未运行该样本。</p>"
    analysis = result.get("analysis") or {}
    events = analysis.get("events") or []
    pauses = analysis.get("pause_candidates") or []
    return (
        f"<h4>{html.escape(label)}</h4>"
        f"<p>延迟 {result.get('latencySeconds')} 秒；校验错误："
        f"{html.escape(', '.join(result.get('validationErrors') or []) or '无')}</p>"
        f"<pre>{html.escape(json.dumps({'events': events, 'pause_candidates': pauses}, ensure_ascii=False, indent=2))}</pre>"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--gemini-results", type=Path)
    parser.add_argument("--qwen-results", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    root = args.manifest.resolve().parent
    out = args.out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    sections = []
    for sample in manifest["samples"]:
        sid = sample["id"]
        sample_dir = root / sid
        audio_url = Path("..") / sid / "input" / "real-audio.wav"
        image_url = Path("..") / sid / "review" / "contact-sheet.jpg"
        gold_path = sample_dir / "human-gold.json"
        sections.append(f"""
<section id="{html.escape(sid)}">
  <h2>{html.escape(sid)}</h2>
  <p><strong>选样目的：</strong>{html.escape(sample['purpose'])}；
     <strong>原视频：</strong>{sample['sourceStartSeconds']:.3f}–{sample['sourceEndSeconds']:.3f} 秒</p>
  <img src="{html.escape(str(image_url))}" alt="{html.escape(sid)} contact sheet">
  <audio controls preload="none" src="{html.escape(str(audio_url))}"></audio>
  <h3>Transcript candidate（不是逐字 Gold）</h3>
  <p>{html.escape(sample['transcriptExcerpt'])}</p>
  <p><strong>待填写：</strong><code>{html.escape(str(gold_path))}</code></p>
  <div class="models">
    <div>{model_html('Gemini', load_result(args.gemini_results, sid))}</div>
    <div>{model_html('Qwen', load_result(args.qwen_results, sid))}</div>
  </div>
</section>""")
    document = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Omni Round 2 人工听审</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;max-width:1200px;margin:2rem auto;padding:0 1rem;line-height:1.5}}
section{{border-top:2px solid #bbb;padding:1.5rem 0}} img{{max-width:100%;display:block;margin:.5rem 0}} audio{{width:100%}}
.models{{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:1rem}} pre{{white-space:pre-wrap;background:#f5f5f5;padding:.75rem;overflow:auto}}
code{{overflow-wrap:anywhere}}
</style></head><body>
<h1>Omni Round 2 人工听审</h1>
<p>先听原声，再看模型候选。逐字英文、读经／解释区间及可听停顿必须写入对应 <code>human-gold.json</code>；本页不会自动把模型输出升级为 Gold。</p>
{''.join(sections)}
</body></html>"""
    out.write_text(document, encoding="utf-8")
    print(json.dumps({"review": str(out), "samples": len(sections)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
