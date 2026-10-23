#!/usr/bin/env python3
"""Build a local per-sentence review player for one sentence-first track.

Reads the run's sentences, translations, review revisions, back-transcription scores and
schedule, and writes a self-contained HTML page that plays one sentence at a time from the
merged track. Each row carries the flags a listener actually needs (ASR below 0.85,
speaker-attribution "check", revised translation, review note) and a per-sentence verdict
and note; notes persist in localStorage and export as JSON for the review receipt.

Open it with a local server so the audio can be fetched:

  python3 -m http.server -d <review dir> 8765
  # then open http://localhost:8765/review-player.html

Usage:
  review_player.py --run artifacts/sentence-first-agent/<run> \
      --audio artifacts/.../20261023-...-zh-Hans.mp3 --out <review dir>/review-player.html
"""
from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path

DEFAULT_NAMES = {"steve_bang_lee": "Steve", "eric_geiger": "Eric"}


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build_rows(run: Path, names: dict[str, str]) -> list[dict]:
    sentences = load_jsonl(run / "sentences.jsonl")
    translations = {t["id"]: t for t in load_jsonl(run / "translations.jsonl")}
    review = json.loads((run / "review.json").read_text(encoding="utf-8"))
    revisions = review.get("revisions") or {}
    notes = review.get("notes") or {}
    asr = {s["id"]: s for s in json.loads((run / "asr-report.json").read_text(encoding="utf-8"))["sentences"]} \
        if (run / "asr-report.json").exists() else {}
    schedule = {s["id"]: s for s in json.loads((run / "schedule.json").read_text(encoding="utf-8"))["sentences"]} \
        if (run / "schedule.json").exists() else {}
    rows = []
    for s in sentences:
        sid = s["id"]
        sch = schedule.get(sid, {})
        start = sch.get("actualStart")
        if start is None:
            start = sch.get("plannedStart", s.get("start", 0.0))
        dur = sch.get("dubSeconds") or 0.0
        target = (revisions.get(sid) or {}).get("target") or (translations.get(sid) or {}).get("target", "")
        flags = []
        similarity = (asr.get(sid) or {}).get("similarity")
        if similarity is not None and similarity < 0.85:
            flags.append("asr")
        if s.get("speakerReview") == "check":
            flags.append("speaker")
        if sid in revisions:
            flags.append("revised")
        if sid in notes:
            flags.append("note")
        rows.append({"id": sid, "speaker": names.get(s.get("speakerId"), s.get("speakerId", "")),
                     "start": round(float(start), 3), "end": round(float(start) + float(dur), 3),
                     "english": s.get("english", ""), "target": target,
                     "asr": None if similarity is None else round(float(similarity), 3),
                     "flags": flags,
                     "note": notes.get(sid, ""),
                     "recognized": (asr.get(sid) or {}).get("recognized", "") if similarity is not None and similarity < 0.85 else ""})
    rows.sort(key=lambda r: (r["start"], r["id"]))
    return rows


def build_html(rows: list[dict], *, title: str, audio_src: str) -> str:
    data = json.dumps(rows, ensure_ascii=False).replace("<", "\\u003c")
    return f"""<!doctype html>
<html lang="zh-Hans">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
:root {{ --bg:#faf9f6; --card:#fff; --ink:#1d1d1f; --muted:#6e6e73; --line:#e5e3dd; --accent:#0b5cad; --warn:#b45309; --bad:#b91c1c; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:var(--bg); color:var(--ink); }}
header {{ position:sticky; top:0; z-index:5; background:rgba(250,249,246,.96); backdrop-filter:blur(8px); border-bottom:1px solid var(--line); padding:12px 18px; }}
h1 {{ font-size:17px; margin:0 0 6px; }}
.bar {{ display:flex; gap:10px; flex-wrap:wrap; align-items:center; }}
.bar input[type=search] {{ flex:1 1 220px; padding:7px 10px; border:1px solid var(--line); border-radius:8px; background:#fff; }}
.bar select, .bar button {{ padding:7px 10px; border:1px solid var(--line); border-radius:8px; background:#fff; cursor:pointer; }}
.bar button.primary {{ background:var(--accent); color:#fff; border-color:var(--accent); }}
.stats {{ color:var(--muted); font-size:13px; margin-top:6px; }}
#audio {{ width:100%; margin-top:8px; }}
main {{ max-width:980px; margin:0 auto; padding:14px 14px 80px; }}
.row {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:12px 14px; margin:10px 0; }}
.row.active {{ outline:2px solid var(--accent); }}
.head {{ display:flex; gap:8px; align-items:center; flex-wrap:wrap; font-size:13px; color:var(--muted); }}
.head .id {{ font-weight:600; color:var(--ink); }}
.head .time {{ font-variant-numeric:tabular-nums; }}
.head .sp {{ margin-left:auto; }}
.flag {{ font-size:12px; padding:1px 7px; border-radius:999px; background:#f1efe8; color:var(--muted); }}
.flag.asr {{ background:#fef3c7; color:#92400e; }}
.flag.speaker {{ background:#e0e7ff; color:#3730a3; }}
.flag.revised {{ background:#dcfce7; color:#166534; }}
.flag.note {{ background:#fce7f3; color:#9d174d; }}
.en {{ margin:6px 0 2px; color:var(--muted); }}
.zh {{ font-size:16px; }}
.rec {{ color:var(--bad); font-size:13px; margin-top:4px; }}
.controls {{ display:flex; gap:8px; margin-top:8px; align-items:center; flex-wrap:wrap; }}
.controls button {{ padding:5px 10px; border:1px solid var(--line); border-radius:7px; background:#fff; cursor:pointer; }}
.controls select {{ padding:5px 8px; border:1px solid var(--line); border-radius:7px; background:#fff; }}
.controls textarea {{ flex:1 1 260px; min-height:34px; padding:6px 8px; border:1px solid var(--line); border-radius:7px; font:inherit; }}
.hint {{ color:var(--muted); font-size:12px; margin:8px 0 0; }}
</style>
</head>
<body>
<header>
  <h1>{html.escape(title)}</h1>
  <div class="bar">
    <button class="primary" id="prev">上一句</button>
    <button class="primary" id="next">下一句</button>
    <select id="filter">
      <option value="all">全部（<span id="c-all"></span>）</option>
      <option value="flagged">只看标记</option>
      <option value="asr">回转写 &lt; 0.85</option>
      <option value="speaker">讲员存疑</option>
      <option value="revised">复核修订</option>
      <option value="note">有备注</option>
      <option value="pending">未写结论</option>
    </select>
    <input type="search" id="search" placeholder="搜句号 / 英文 / 译文">
    <button id="export">导出结论 JSON</button>
  </div>
  <div class="stats" id="stats"></div>
  <audio id="audio" controls preload="metadata" src="{html.escape(audio_src)}"></audio>
</header>
<main id="list"></main>
<script>
const ROWS = {data};
const KEY = 'sentence-first-review:' + location.pathname;
const store = JSON.parse(localStorage.getItem(KEY) || '{{}}');
const audio = document.getElementById('audio');
const list = document.getElementById('list');
let current = null, timer = null;
const flagText = {{asr:'ASR 低分', speaker:'讲员存疑', revised:'复核修订', note:'备注'}};
function save() {{ localStorage.setItem(KEY, JSON.stringify(store)); }}
function verdictOf(id) {{ return (store[id] && store[id].verdict) || 'pending'; }}
function noteOf(id) {{ return (store[id] && store[id].note) || ''; }}
function fmt(t) {{ const m = Math.floor(t / 60), s = Math.floor(t % 60); return m + ':' + String(s).padStart(2,'0'); }}
function play(id) {{
  const r = ROWS.find(x => x.id === id); if (!r) return;
  current = id;
  document.querySelectorAll('.row').forEach(el => el.classList.toggle('active', el.dataset.id === id));
  audio.currentTime = r.start; audio.play();
  if (timer) clearInterval(timer);
  timer = setInterval(() => {{ if (audio.currentTime >= r.end) {{ audio.pause(); clearInterval(timer); timer = null; }} }}, 60);
}}
function visible() {{
  const f = document.getElementById('filter').value;
  const q = document.getElementById('search').value.trim().toLowerCase();
  return ROWS.filter(r => {{
    if (f === 'flagged' && r.flags.length === 0) return false;
    if (['asr','speaker','revised','note'].includes(f) && !r.flags.includes(f)) return false;
    if (f === 'pending' && verdictOf(r.id) !== 'pending') return false;
    if (q && !(r.id + ' ' + r.english + ' ' + r.target).toLowerCase().includes(q)) return false;
    return true;
  }});
}}
function render() {{
  const rows = visible();
  list.innerHTML = '';
  for (const r of rows) {{
    const el = document.createElement('div');
    el.className = 'row'; el.dataset.id = r.id;
    el.innerHTML = `<div class="head"><span class="id">${{r.id}}</span><span class="time">${{fmt(r.start)}}–${{fmt(r.end)}}</span>`
      + r.flags.map(f => `<span class="flag ${{f}}">${{flagText[f]}}</span>`).join('')
      + `<span class="sp">${{r.speaker}}</span></div>`
      + `<div class="en">${{escapeHtml(r.english)}}</div><div class="zh">${{escapeHtml(r.target)}}</div>`
      + (r.recognized ? `<div class="rec">ASR: ${{escapeHtml(r.recognized)}}（${{r.asr}}）</div>` : '')
      + `<div class="controls"><button data-play="${{r.id}}">播放</button>`
      + `<select data-verdict="${{r.id}}">${{['pending','pass','issue'].map(v => `<option value="${{v}}" ${{verdictOf(r.id)===v?'selected':''}}>${{v==='pending'?'未定':v==='pass'?'通过':'问题'}}</option>`).join('')}}</select>`
      + `<textarea data-note="${{r.id}}" placeholder="备注（可选）">${{escapeHtml(noteOf(r.id))}}</textarea></div>`;
    list.appendChild(el);
  }}
  const stats = document.getElementById('stats');
  const flagged = ROWS.filter(r => r.flags.length).length;
  const done = ROWS.filter(r => verdictOf(r.id) !== 'pending').length;
  stats.textContent = `${{ROWS.length}} 句；${{flagged}} 句有标记；已写结论 ${{done}}；显示 ${{rows.length}}`;
  list.querySelectorAll('[data-play]').forEach(b => b.onclick = () => play(b.dataset.play));
  list.querySelectorAll('[data-verdict]').forEach(sel => sel.onchange = () => {{
    const id = sel.dataset.verdict; store[id] = {{...(store[id]||{{}}), verdict: sel.value}}; save();
  }});
  list.querySelectorAll('[data-note]').forEach(t => t.oninput = () => {{
    const id = t.dataset.note; store[id] = {{...(store[id]||{{}}), note: t.value}}; save();
  }});
}}
function escapeHtml(s) {{ return (s||'').replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c])); }}
function step(delta) {{
  const rows = visible(); if (!rows.length) return;
  const idx = rows.findIndex(r => r.id === current);
  const next = rows[Math.min(rows.length-1, Math.max(0, (idx < 0 ? 0 : idx + delta)))];
  if (next) play(next.id);
}}
document.getElementById('prev').onclick = () => step(-1);
document.getElementById('next').onclick = () => step(1);
document.getElementById('filter').onchange = render;
document.getElementById('search').oninput = render;
document.getElementById('export').onclick = () => {{
  const out = {{exportedAt: new Date().toISOString(), rows: ROWS.filter(r => verdictOf(r.id) !== 'pending' || noteOf(r.id)).map(r => ({{id: r.id, verdict: verdictOf(r.id), note: noteOf(r.id)}}))}};
  const blob = new Blob([JSON.stringify(out, null, 1)], {{type: 'application/json'}});
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'review-verdict.json'; a.click();
}};
render();
</script>
</body>
</html>
"""


def build_player(run: Path, out: Path, *, audio: Path | None = None,
                 title: str = "逐句听审", names: dict[str, str] | None = None) -> dict:
    rows = build_rows(run, {**DEFAULT_NAMES, **(names or {})})
    if audio is None:
        audio = run / "track.wav"
    if not audio.exists():
        raise FileNotFoundError(f"audio not found: {audio}")
    src = os.path.relpath(audio.resolve(), out.resolve().parent) if out.resolve().parent != audio.resolve().parent else audio.name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_html(rows, title=title, audio_src=src), encoding="utf-8")
    flagged = sum(1 for r in rows if r["flags"])
    return {"player": str(out), "rows": len(rows), "flagged": flagged, "audio": src, "audioBytes": audio.stat().st_size}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--audio", type=Path)
    p.add_argument("--title", default="逐句听审")
    p.add_argument("--name", action="append", default=[], metavar="SPEAKER_ID=NAME")
    a = p.parse_args(argv)
    names = {}
    for item in a.name:
        k, _, v = item.partition("=")
        if k and v:
            names[k] = v
    print(json.dumps(build_player(a.run, a.out, audio=a.audio, title=a.title, names=names), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
