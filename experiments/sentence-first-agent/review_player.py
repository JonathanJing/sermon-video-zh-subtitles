#!/usr/bin/env python3
"""Build a local per-sentence review player for one sentence-first track (v2).

Why v2. The 2026-10-24 run showed the v1 page was slow to review 418 sentences:
it played the merged MP3 by seeking a 22 MB file served by ``python -m http.server``
(no Range support), had no keyboard shortcuts, no original-audio comparison, no
auto-scroll, no lag column and no bulk pass. v2 keeps the same inputs and the same
``build_player`` call from ``finish_run.py`` but changes what the page can do:

* **per-sentence playback from the TTS wavs** (``tts/<id>.wav``) — instant and exact,
  with the merged ``review.mp3`` kept as an optional "track mode" fallback;
* **original-vs-dub A/B** — ``slices/<id>.wav`` is the English source slice; one button
  plays both in order so the reviewer hears what the source said before the dub;
* **keyboard-first review** — Space play/pause, J/K or arrows to move, Enter pass,
  X issue, F next flagged, S source, D dub, B both, / search;
* **verdict + issue tags + note per sentence**, persisted in localStorage, exportable as
  JSON/CSV with the run's audio hashes so the file can back a review receipt, and
  re-importable on another machine;
* **signals the reviewer actually needs**: dub time, source-video time, per-sentence lag,
  budget vs dub seconds, ASR similarity with a character diff of expected vs recognised;
* **filters and progress**: flagged/asr_content/asr_variant/revised/note/pending/
  no-issue, search, pass-all-visible, next-flagged, progress bar, auto-scroll.

Open it with a local server so the wavs can be fetched:

  python3 -m http.server -d <run dir> 8765
  # then open http://localhost:8765/review-player.html

Usage:
  review_player.py --run artifacts/sentence-first-agent/<run> \
      --audio artifacts/.../review.mp3 --out <run>/review-player.html
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from asr_triage import classify as asr_classify  # noqa: E402

DEFAULT_NAMES = {"steve_bang_lee": "Steve", "eric_geiger": "Eric"}


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    slices = {s["id"]: s for s in json.loads((run / "slices/slices.json").read_text(encoding="utf-8"))} \
        if (run / "slices/slices.json").exists() else {}
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
        asr_class = None
        if similarity is not None and similarity < 0.85:
            asr_class = asr_classify((asr.get(sid) or {}).get("expected", ""),
                                     (asr.get(sid) or {}).get("recognized", ""),
                                     (review.get("locale") or ""))
            flags.append("asr_variant" if asr_class in ("identical", "variant", "number_form", "homophone") else "asr_content")
        if s.get("speakerReview") == "check":
            flags.append("speaker")
        if sid in revisions:
            flags.append("revised")
        if sid in notes:
            flags.append("note")
        rows.append({"id": sid, "speaker": names.get(s.get("speakerId"), s.get("speakerId", "")),
                     "start": round(float(start), 3), "end": round(float(start) + float(dur), 3),
                     "src": round(float(s.get("start", 0.0)), 3),
                     "lag": None if sch.get("lagSeconds") is None else round(float(sch["lagSeconds"]), 2),
                     "dur": round(float(dur), 2),
                     "budget": round(float((slices.get(sid) or {}).get("budgetSeconds", 0.0)), 2),
                     "english": s.get("english", ""), "target": target,
                     "asr": None if similarity is None else round(float(similarity), 3),
                     "asrClass": asr_class,
                     "flags": flags,
                     "note": notes.get(sid, ""),
                     "recognized": (asr.get(sid) or {}).get("recognized", "") if similarity is not None and similarity < 0.85 else "",
                     "expected": (asr.get(sid) or {}).get("expected", "") if similarity is not None and similarity < 0.85 else "",
                     "dubWav": f"tts/{sid}.wav" if (run / "tts" / f"{sid}.wav").exists() else None,
                     "srcWav": f"slices/{sid}.wav" if (run / "slices" / f"{sid}.wav").exists() else None})
    rows.sort(key=lambda r: (r["start"], r["id"]))
    return rows


def build_meta(run: Path, audio: Path, rows: list[dict]) -> dict:
    clip = json.loads((run / "clip.json").read_text(encoding="utf-8")) if (run / "clip.json").exists() else {}
    review = json.loads((run / "review.json").read_text(encoding="utf-8"))
    return {
        "schemaVersion": "sentence-first-review-player-v2",
        "run": run.name,
        "locale": review.get("locale"),
        "windowStart": clip.get("windowStart"),
        "mediaStart": clip.get("mediaStart"),
        "mediaEnd": clip.get("mediaEnd"),
        "trackSha256": sha256(run / "track.wav"),
        "audioSha256": sha256(audio),
        "sentencesJsonSha256": sha256(run / "sentences.jsonl"),
        "translationsJsonSha256": sha256(run / "translations.jsonl"),
        "hasSourceClip": (run / "source-clip.mp4").exists(),
        "counts": {"rows": len(rows), "flagged": sum(1 for r in rows if r["flags"])},
    }


HTML_TEMPLATE = r"""<!doctype html>
<html lang="zh-Hans">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>/*__TITLE__*/</title>
<style>
:root { --bg:#faf9f6; --card:#fff; --ink:#1d1d1f; --muted:#6e6e73; --line:#e5e3dd; --accent:#0b5cad; --ok:#166534; --warn:#b45309; --bad:#b91c1c; }
* { box-sizing:border-box; }
body { margin:0; font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:var(--bg); color:var(--ink); }
header { position:sticky; top:0; z-index:9; background:rgba(250,249,246,.97); backdrop-filter:blur(8px); border-bottom:1px solid var(--line); padding:10px 16px 8px; }
h1 { font-size:16px; margin:0 0 6px; }
.hud { display:flex; flex-direction:column; gap:6px; }
.hudrow { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
button, select, input[type=search], input[type=text] { padding:6px 10px; border:1px solid var(--line); border-radius:8px; background:#fff; font:inherit; cursor:pointer; }
button.primary { background:var(--accent); color:#fff; border-color:var(--accent); }
button.ghost { background:#fff; }
button:disabled { opacity:.45; cursor:default; }
input[type=search] { flex:1 1 180px; cursor:text; }
.chip { font-size:12px; padding:1px 7px; border-radius:999px; background:#f1efe8; color:var(--muted); }
.chip.asr_variant { background:#fef3c7; color:#92400e; }
.chip.asr_content { background:#fee2e2; color:#991b1b; }
.chip.speaker { background:#e0e7ff; color:#3730a3; }
.chip.revised { background:#dcfce7; color:#166534; }
.chip.note { background:#fce7f3; color:#9d174d; }
.progress { height:5px; background:#eeece6; border-radius:99px; overflow:hidden; margin-top:2px; }
.progress > div { height:100%; width:0; background:var(--accent); transition:width .2s; }
.stats { color:var(--muted); font-size:12.5px; display:flex; gap:12px; flex-wrap:wrap; }
.stats b { color:var(--ink); }
main { max-width:1000px; margin:0 auto; padding:12px 12px 120px; }
.row { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:11px 13px; margin:9px 0; }
.row.active { outline:2px solid var(--accent); box-shadow:0 0 0 4px rgba(11,92,173,.08); }
.row.pass { border-left:4px solid var(--ok); }
.row.issue { border-left:4px solid var(--bad); }
.head { display:flex; gap:8px; align-items:center; flex-wrap:wrap; font-size:12.5px; color:var(--muted); }
.head .id { font-weight:700; color:var(--ink); font-size:13.5px; }
.head .num { font-variant-numeric:tabular-nums; }
.head .sp { margin-left:auto; }
.lag { font-variant-numeric:tabular-nums; }
.lag.hi { color:var(--bad); font-weight:600; }
.en { margin:7px 0 3px; color:var(--muted); font-size:14px; }
.tgt { font-size:16.5px; }
.rec { margin-top:5px; font-size:13px; color:var(--bad); }
.rec del { background:#fee2e2; text-decoration:none; border-radius:3px; padding:0 1px; }
.rec ins { background:#dcfce7; text-decoration:none; border-radius:3px; padding:0 1px; }
.ctl { display:flex; gap:8px; align-items:center; margin-top:8px; flex-wrap:wrap; }
.ctl .verdicts { display:flex; gap:4px; }
.ctl .verdicts button { padding:4px 9px; font-size:13px; }
.ctl .verdicts button.on-pass { background:var(--ok); color:#fff; border-color:var(--ok); }
.ctl .verdicts button.on-issue { background:var(--bad); color:#fff; border-color:var(--bad); }
.ctl input.tags { flex:0 1 180px; }
.ctl input.note { flex:1 1 220px; cursor:text; }
.kbd { color:var(--muted); font-size:12px; }
</style>
</head>
<body>
<header>
  <h1>/*__TITLE__*/</h1>
  <div class="hud">
    <div class="hudrow">
      <button class="primary" id="play" title="Space">▶ 播放</button>
      <button class="ghost" id="playSrc" title="S">原声</button>
      <button class="ghost" id="playBoth" title="B">原声+配音</button>
      <label class="kbd">语速 <select id="rate"><option>0.8</option><option selected>1</option><option>1.2</option><option>1.5</option></select></label>
      <label class="kbd"><input type="checkbox" id="auto"> 自动下一句</label>
      <label class="kbd"><input type="checkbox" id="useTrack"> 整轨播放</label>
      <span class="stats" id="cur"></span>
    </div>
    <div class="hudrow">
      <button class="ghost" id="prev" title="↑/K">上一句</button>
      <button class="ghost" id="next" title="↓/J">下一句</button>
      <button class="ghost" id="nextFlag" title="F">下一句标记</button>
      <input type="search" id="search" placeholder="搜句号 / 英文 / 译文（/）">
      <select id="filter">
        <option value="all">全部</option>
        <option value="flagged">只看标记</option>
        <option value="pending">未写结论</option>
        <option value="issue">已标问题</option>
        <option value="pass">已通过</option>
        <option value="asr_variant">ASR 同音/数字</option>
        <option value="asr_content">ASR 内容差异</option>
        <option value="revised">复核修订</option>
        <option value="note">有备注</option>
      </select>
      <button class="ghost" id="passVisible">全部标通过（当前筛选）</button>
      <button class="ghost" id="export">导出 JSON</button>
      <button class="ghost" id="exportCsv">导出 CSV</button>
      <button class="ghost" id="importBtn">导入 JSON</button>
      <button class="ghost" id="reset">清空</button>
      <input type="file" id="importFile" accept="application/json" style="display:none">
    </div>
    <div class="progress"><div id="pbar"></div></div>
    <div class="stats" id="stats"></div>
  </div>
</header>
<main id="list"></main>
<audio id="dub" preload="auto"></audio>
<audio id="src" preload="auto"></audio>
<audio id="track" src="/*__TRACK__*/" preload="none"></audio>
<script>
const ROWS = /*__ROWS__*/;
const META = /*__META__*/;
const KEY = 'sentence-first-review:v2:' + (META.run || '') + ':' + (META.trackSha256 || '');
const store = JSON.parse(localStorage.getItem(KEY) || '{}');
const list = document.getElementById('list');
const dub = document.getElementById('dub'), src = document.getElementById('src'), track = document.getElementById('track');
const $ = (id) => document.getElementById(id);
let current = null, stopTimer = null;

/* ---------- store ---------- */
function entry(id) { return store[id] || (store[id] = {verdict: 'pending', note: '', tags: []}); }
function verdictOf(id) { return (store[id] && store[id].verdict) || 'pending'; }
function noteOf(id) { return (store[id] && store[id].note) || ''; }
function tagsOf(id) { return (store[id] && store[id].tags) || []; }
function save() { localStorage.setItem(KEY, JSON.stringify(store)); }
function rowById(id) { return ROWS.find(r => r.id === id); }

/* ---------- helpers ---------- */
function fmt(t) { if (t == null) return '—'; const m = Math.floor(t / 60), s = t - m * 60; return m + ':' + s.toFixed(1).padStart(4, '0'); }
function esc(s) { return (s || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function visible() {
  const f = $('filter').value, q = $('search').value.trim().toLowerCase();
  return ROWS.filter(r => {
    if (f === 'flagged' && r.flags.length === 0) return false;
    if (['asr_variant','asr_content','revised','note'].includes(f) && !r.flags.includes(f)) return false;
    if (f === 'pending' && verdictOf(r.id) !== 'pending') return false;
    if (f === 'issue' && verdictOf(r.id) !== 'issue') return false;
    if (f === 'pass' && verdictOf(r.id) !== 'pass') return false;
    if (q && !(r.id + ' ' + r.english + ' ' + r.target + ' ' + r.recognized).toLowerCase().includes(q)) return false;
    return true;
  });
}

/* ---------- character diff for ASR ---------- */
function diff(a, b) {
  a = Array.from(a || ''); b = Array.from(b || '');
  const n = a.length, m = b.length;
  if (n * m > 40000) return esc(b || '');
  const dp = Array.from({length: n + 1}, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--)
    dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  let i = 0, j = 0, out = '';
  while (i < n && j < m) {
    if (a[i] === b[j]) { out += esc(a[i]); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) { out += '<del>' + esc(a[i]) + '</del>'; i++; }
    else { out += '<ins>' + esc(b[j]) + '</ins>'; j++; }
  }
  while (i < n) { out += '<del>' + esc(a[i]) + '</del>'; i++; }
  while (j < m) { out += '<ins>' + esc(b[j]) + '</ins>'; j++; }
  return out;
}

/* ---------- rendering ---------- */
function render() {
  const rows = visible();
  list.innerHTML = '';
  const frag = document.createDocumentFragment();
  for (const r of rows) {
    const el = document.createElement('div');
    el.className = 'row ' + (verdictOf(r.id) || '');
    el.dataset.id = r.id;
    const lag = r.lag == null ? '' : `<span class="lag ${r.lag > 1 ? 'hi' : ''}">落后 ${r.lag.toFixed(2)}s</span>`;
    const fit = r.budget ? `<span class="num">配音 ${r.dur}s / 预算 ${r.budget}s</span>` : '';
    el.innerHTML =
      `<div class="head"><span class="id">${r.id}</span>` +
      `<span class="num">配音 ${fmt(r.start)}–${fmt(r.end)}</span>` +
      `<span class="num">原片 ${fmt((META.mediaStart || 0) + r.src)}</span>` +
      lag + fit +
      r.flags.map(f => `<span class="chip ${f}">${({asr_variant:'ASR 同音/数字',asr_content:'ASR 内容差异',speaker:'讲员存疑',revised:'复核修订',note:'备注'})[f] || f}</span>`).join('') +
      `<span class="sp">${esc(r.speaker)}</span></div>` +
      `<div class="en">${esc(r.english)}</div><div class="tgt">${esc(r.target)}</div>` +
      (r.recognized ? `<div class="rec">ASR ${r.asr}（${r.asrClass}）：${diff(r.expected, r.recognized)}</div>` : '') +
      `<div class="ctl"><span class="verdicts">` +
      `<button data-v="pass" class="${verdictOf(r.id)==='pass'?'on-pass':''}">通过</button>` +
      `<button data-v="issue" class="${verdictOf(r.id)==='issue'?'on-issue':''}">问题</button>` +
      `<button data-v="pending">清</button></span>` +
      `<input class="tags" data-tags="${r.id}" placeholder="问题类型（逗号）" value="${esc(tagsOf(r.id).join(','))}">` +
      `<input class="note" data-note="${r.id}" placeholder="备注" value="${esc(noteOf(r.id))}">` +
      `<button data-play="${r.id}">▶</button>` +
      (r.srcWav ? `<button data-play-src="${r.id}">原声</button>` : '') +
      (META.hasSourceClip ? `<a href="source-clip.mp4#t=${((META.mediaStart || 0) + r.src).toFixed(2)}" target="_blank" rel="noopener"><button>看原片</button></a>` : '') +
      `</div>`;
    frag.appendChild(el);
  }
  list.appendChild(frag);
  list.querySelectorAll('[data-v]').forEach(b => b.onclick = () => {
    const id = b.closest('.row').dataset.id;
    entry(id).verdict = b.dataset.v; save(); refreshRow(id); updateStats();
  });
  list.querySelectorAll('[data-tags]').forEach(t => t.oninput = () => {
    const id = t.dataset.tags;
    entry(id).tags = t.value.split(/[,，]/).map(s => s.trim()).filter(Boolean); save();
  });
  list.querySelectorAll('[data-note]').forEach(t => t.oninput = () => {
    const id = t.dataset.note; entry(id).note = t.value; save();
  });
  list.querySelectorAll('[data-play]').forEach(b => b.onclick = () => playDub(b.dataset.play, true));
  list.querySelectorAll('[data-play-src]').forEach(b => b.onclick = () => playSrc(b.dataset.play));
  updateStats();
  if (current) markActive(current);
}
function refreshRow(id) {
  const el = list.querySelector(`.row[data-id="${id}"]`);
  if (!el) return;
  el.className = 'row ' + (verdictOf(id) || '') + (current === id ? ' active' : '');
  el.querySelectorAll('[data-v]').forEach(b => {
    b.className = b.dataset.v === 'pass' ? (verdictOf(id) === 'pass' ? 'on-pass' : '') :
                  b.dataset.v === 'issue' ? (verdictOf(id) === 'issue' ? 'on-issue' : '') : '';
  });
}
function updateStats() {
  const total = ROWS.length;
  const done = ROWS.filter(r => verdictOf(r.id) !== 'pending').length;
  const pass = ROWS.filter(r => verdictOf(r.id) === 'pass').length;
  const issue = ROWS.filter(r => verdictOf(r.id) === 'issue').length;
  const flagged = ROWS.filter(r => r.flags.length).length;
  $('stats').innerHTML = `共 <b>${total}</b> 句 · 有标记 <b>${flagged}</b> · 已审 <b>${done}</b> · 通过 <b>${pass}</b> · 问题 <b>${issue}</b> · 显示 <b>${visible().length}</b>`;
  $('pbar').style.width = total ? (done / total * 100).toFixed(1) + '%' : '0';
}
function markActive(id) {
  list.querySelectorAll('.row').forEach(el => el.classList.toggle('active', el.dataset.id === id));
  const el = list.querySelector(`.row[data-id="${id}"]`);
  if (el) el.scrollIntoView({ block: 'center', behavior: 'smooth' });
}

/* ---------- playback ---------- */
function clearStop() { if (stopTimer) { clearInterval(stopTimer); stopTimer = null; } }
function setRate(el) { el.playbackRate = parseFloat($('rate').value) || 1; }
function playDub(id, advance) {
  const r = rowById(id); if (!r) return;
  current = id; markActive(id); clearStop(); src.pause();
  $('cur').textContent = `${id} · 配音 ${fmt(r.start)}–${fmt(r.end)}`;
  if (r.dubWav && !$('useTrack').checked) {
    dub.src = r.dubWav; setRate(dub);
    dub.onended = () => { if (advance && $('auto').checked) step(1); };
    dub.play().catch(() => {});
  } else {
    track.currentTime = r.start;
    setRate(track);
    track.play().catch(() => {});
    stopTimer = setInterval(() => { if (track.currentTime >= r.end) { track.pause(); clearStop(); if (advance && $('auto').checked) step(1); } }, 80);
  }
}
function playSrc(id) {
  const r = rowById(id); if (!r || !r.srcWav) return;
  current = id; markActive(id); clearStop(); dub.pause(); track.pause();
  src.src = r.srcWav; setRate(src); src.play().catch(() => {});
  $('cur').textContent = `${id} · 原声`;
}
function playBoth(id) {
  const r = rowById(id); if (!r) return;
  if (!r.srcWav) { playDub(id, true); return; }
  current = id; markActive(id); clearStop(); dub.pause(); track.pause();
  src.src = r.srcWav; setRate(src);
  src.onended = () => { dub.src = r.dubWav; setRate(dub); dub.play().catch(() => {}); };
  src.play().catch(() => {});
  $('cur').textContent = `${id} · 原声→配音`;
}
function step(delta) {
  const rows = visible(); if (!rows.length) return;
  let idx = rows.findIndex(r => r.id === current);
  if (idx < 0) idx = delta > 0 ? -1 : 0;
  const next = rows[Math.min(rows.length - 1, Math.max(0, idx + delta))];
  if (next) playDub(next.id, true);
}
function nextFlagged() {
  const rows = visible().filter(r => r.flags.length || verdictOf(r.id) === 'pending');
  if (!rows.length) return;
  let idx = rows.findIndex(r => r.id === current);
  const next = rows[(idx + 1) % rows.length];
  if (next) playDub(next.id, true);
}
function passVisible() {
  const rows = visible();
  if (!rows.length) return;
  if (!confirm(`把当前筛选的 ${rows.length} 句标为“通过”？`)) return;
  rows.forEach(r => { entry(r.id).verdict = 'pass'; });
  save(); render();
}

/* ---------- export / import ---------- */
function download(name, text, type) {
  const blob = new Blob([text], { type });
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}
function reviewedRows() {
  return ROWS.filter(r => verdictOf(r.id) !== 'pending' || noteOf(r.id) || tagsOf(r.id).length)
    .map(r => ({ id: r.id, verdict: verdictOf(r.id), tags: tagsOf(r.id), note: noteOf(r.id),
                 start: r.start, dur: r.dur, lag: r.lag, english: r.english, target: r.target }));
}
function exportJson() {
  const out = { schemaVersion: 'sentence-first-review-verdict-v2', exportedAt: new Date().toISOString(),
                meta: META, reviewer: '', rows: reviewedRows() };
  download((META.run || 'review') + '-verdict.json', JSON.stringify(out, null, 1), 'application/json');
}
function exportCsv() {
  const head = ['id','verdict','tags','note','dubStart','dubSeconds','lag','english','target'];
  const q = (v) => '"' + String(v == null ? '' : v).replace(/"/g, '""') + '"';
  const lines = [head.join(',')].concat(reviewedRows().map(r => [r.id,r.verdict,r.tags.join('|'),r.note,r.start,r.dur,r.lag,r.english,r.target].map(q).join(',')));
  download((META.run || 'review') + '-verdict.csv', lines.join('\n'), 'text/csv');
}
function importJson(file) {
  const reader = new FileReader();
  reader.onload = () => {
    try {
      const data = JSON.parse(reader.result);
      if (!Array.isArray(data.rows)) throw new Error('rows missing');
      let n = 0;
      for (const r of data.rows) {
        if (!r || !r.id) continue;
        store[r.id] = { verdict: r.verdict || 'pending', note: r.note || '', tags: r.tags || [] }; n++;
      }
      save(); render(); alert('导入 ' + n + ' 行');
    } catch (e) { alert('导入失败：' + e.message); }
  };
  reader.readAsText(file);
}

/* ---------- wiring ---------- */
$('play').onclick = () => { if (current) playDub(current, true); else step(1); };
$('playSrc').onclick = () => { if (current) playSrc(current); };
$('playBoth').onclick = () => { if (current) playBoth(current); };
$('prev').onclick = () => step(-1);
$('next').onclick = () => step(1);
$('nextFlag').onclick = nextFlagged;
$('passVisible').onclick = passVisible;
$('filter').onchange = render;
$('search').oninput = render;
$('rate').onchange = () => { setRate(dub); setRate(src); setRate(track); };
$('export').onclick = exportJson;
$('exportCsv').onclick = exportCsv;
$('importBtn').onclick = () => $('importFile').click();
$('importFile').onchange = (e) => { if (e.target.files[0]) importJson(e.target.files[0]); e.target.value = ''; };
$('reset').onclick = () => { if (confirm('清空本页所有结论和备注？')) { localStorage.removeItem(KEY); location.reload(); } };
document.addEventListener('keydown', (e) => {
  if (e.target.matches('input, textarea, select')) return;
  const k = e.key;
  if (k === ' ') { e.preventDefault(); $('play').click(); }
  else if (k === 'ArrowDown' || k === 'j') { e.preventDefault(); step(1); }
  else if (k === 'ArrowUp' || k === 'k') { e.preventDefault(); step(-1); }
  else if (k === 'Enter') { e.preventDefault(); if (current) { entry(current).verdict = 'pass'; save(); refreshRow(current); updateStats(); step(1); } }
  else if (k === 'x' || k === 'X') { e.preventDefault(); if (current) { entry(current).verdict = 'issue'; save(); refreshRow(current); updateStats(); } }
  else if (k === 'f' || k === 'F') { e.preventDefault(); nextFlagged(); }
  else if (k === 's' || k === 'S') { e.preventDefault(); if (current) playSrc(current); }
  else if (k === 'd' || k === 'D') { e.preventDefault(); if (current) playDub(current, true); }
  else if (k === 'b' || k === 'B') { e.preventDefault(); if (current) playBoth(current); }
  else if (k === '/') { e.preventDefault(); $('search').focus(); }
});
render();
</script>
</body>
</html>
"""


def build_html(rows: list[dict], meta: dict, *, title: str, track_src: str) -> str:
    data = json.dumps(rows, ensure_ascii=False).replace("<", "\\u003c")
    meta_json = json.dumps(meta, ensure_ascii=False).replace("<", "\\u003c")
    return (HTML_TEMPLATE
            .replace("/*__TITLE__*/", html.escape(title))
            .replace("/*__ROWS__*/", data)
            .replace("/*__META__*/", meta_json)
            .replace("/*__TRACK__*/", html.escape(track_src)))


def build_player(run: Path, out: Path, *, audio: Path | None = None,
                 title: str = "逐句听审", names: dict[str, str] | None = None) -> dict:
    rows = build_rows(run, {**DEFAULT_NAMES, **(names or {})})
    if audio is None:
        audio = run / "track.wav"
    if not audio.exists():
        raise FileNotFoundError(f"audio not found: {audio}")
    src = os.path.relpath(audio.resolve(), out.resolve().parent) if out.resolve().parent != audio.resolve().parent else audio.name
    meta = build_meta(run, audio, rows)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_html(rows, meta, title=title, track_src=src), encoding="utf-8")
    flagged = sum(1 for r in rows if r["flags"])
    return {"player": str(out), "rows": len(rows), "flagged": flagged, "audio": src,
            "audioBytes": audio.stat().st_size, "hasDubWavs": sum(1 for r in rows if r["dubWav"]),
            "hasSourceSlices": sum(1 for r in rows if r["srcWav"])}


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
