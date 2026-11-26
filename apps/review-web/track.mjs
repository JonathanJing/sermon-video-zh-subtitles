// l3.review.<locale>: listen to one language's merged track and review its translation.
// The page measures what was actually played; the receipt's review mode comes from that.
import { $, h, demo, loadGate, showFatal, setupDecision, createDraft, createClipPlayer, playButton, mediaUrl, fmtClock, fmtDuration, short, LOCALE_NAMES } from "./gate.mjs";
import { createCoverage, reviewMode } from "./coverage.mjs";

const FLAGS = { fixed: ["按你的要求改了", "good"], rerendered: ["重新配音", "warn"], unclear: ["没看懂要求", "bad"], revised: ["复核改过", "warn"], condensed: ["精简过", "warn"], lag: ["落后", "warn"], speaker: ["讲员存疑", "warn"], speed: ["加速过", ""], note: ["有备注", ""] };
const CHANGED = ["fixed", "rerendered", "unclear"];   // what the last request for changes did to a sentence
const TAGS = { translation: "译文", reading: "读音", facts: "数字／人名／经文", audio: "音质", sync: "不同步", other: "其他" };
const state = { marks: {}, clipHeard: new Set(), filter: "all", query: "", follow: true, declared: false, position: 0 };
let gate, data, rows, decision, draft, coverage, current = null, lastSave = 0;

const mark = id => state.marks[id] || (state.marks[id] = { verdict: null, tags: [], note: "" });
const verdictOf = id => (state.marks[id] || {}).verdict || null;
const heard = row => state.clipHeard.has(row.id) || coverage.covers(row.start, row.start + row.dur);

function matches(row) {
  const f = state.filter;
  if (f === "flagged" && !row.flags.length) return false;
  if (f === "unheard" && !(row.flags.length && !heard(row))) return false;
  if (f === "issue" && verdictOf(row.id) !== "issue") return false;
  if ((f === "condensed" || f === "lag") && !row.flags.includes(f)) return false;
  if (f === "changed" && !row.flags.some(flag => CHANGED.includes(flag))) return false;
  const q = state.query.trim().toLowerCase();
  return !q || [row.id, row.target, row.english].some(text => String(text).toLowerCase().includes(q));
}

function rowElement(row) {
  const verdict = verdictOf(row.id), entry = state.marks[row.id] || { tags: [], note: "" };
  const flags = row.flags.map(f => h("span", { class: `flag ${FLAGS[f][1]}`, text: f === "lag" && row.lag != null ? `落后 ${row.lag.toFixed(1)} 秒` : FLAGS[f][0] }));
  if (heard(row)) flags.push(h("span", { class: "flag", text: "已听" }));
  const off = gate.state !== "open";
  const classes = ["row", row.flags.length ? "flagged" : "", verdict || "", current === row.id ? "current" : ""].filter(Boolean).join(" ");
  return h("article", { class: classes, id: `row-${row.id}`, dataset: { id: row.id } },
    h("div", { class: "row-head" }, h("span", { class: "id", text: row.id }), h("span", { text: `轨内 ${fmtClock(row.start)} · ${row.dur.toFixed(1)} 秒` }),
      row.speaker ? h("span", { text: row.speaker }) : null, ...flags),
    h("p", { class: "text", lang: data.locale, text: row.target }),
    h("p", { class: "secondary", lang: "en", text: row.english }),
    row.spoken && row.spoken !== row.target ? h("p", { class: "secondary", lang: data.locale, text: `实际口播：${row.spoken}` }) : null,
    row.note ? h("p", { class: "secondary", text: `备注：${row.note}` }) : null,
    row.fix ? h("p", { class: "secondary", text: `你上一版写的：${row.fix.asked || row.fix.tags.join("、") || "（没有写说明）"}` }) : null,
    row.fix && row.fix.before ? h("p", { class: "before", lang: data.locale, text: row.fix.before }) : null,
    row.fix && row.fix.did ? h("p", { class: "secondary", text: `${row.fix.action === "unclear" ? "没有改" : "这次的处理"}：${row.fix.did}` }) : null,
    h("div", { class: "row-tools" },
      playButton(row.dub, "▶ 配音", "听这一句的配音"),
      playButton(row.source, "▶ 原声", "听这一句的英文原声"),
      playButton(`${row.source}|${row.dub}`, "▶ 先原声后配音", "先听原声，再听配音"),
      h("button", { type: "button", class: "small", "data-act": "seek", text: "从这里听整轨" })),
    h("div", { class: "row-tools" },
      h("button", { type: "button", class: "small", "data-act": "pass", "aria-pressed": String(verdict === "pass"), disabled: off, text: "通过" }),
      h("button", { type: "button", class: "small", "data-act": "issue", "aria-pressed": String(verdict === "issue"), disabled: off, text: "有问题" })),
    verdict === "issue" ? h("div", { class: "chips", role: "group", "aria-label": "问题类型" },
      Object.entries(TAGS).map(([tag, label]) => h("button", { type: "button", "data-tag": tag, "aria-pressed": String(entry.tags.includes(tag)), disabled: off, text: label }))) : null,
    verdict === "issue" ? h("input", { type: "text", class: "issue-note", placeholder: "哪里不对，改成什么", value: entry.note, disabled: off, "aria-label": `${row.id} 的问题说明` }) : null);
}

function refreshRow(id) {
  const row = rows.find(r => r.id === id), old = $(`row-${id}`);
  if (row && old) old.replaceWith(rowElement(row));
}

function render() {
  const list = rows.filter(matches);
  $("rows").replaceChildren(...list.map(rowElement));
  $("shown").textContent = `显示 ${list.length} / ${rows.length} 句`;
}

function listening() {
  const summary = coverage.summary();
  const flagged = rows.filter(r => r.flags.length);
  const mode = reviewMode({ shareAt1x: summary.shareAt1x, flaggedIds: flagged.map(r => r.id),
    heardIds: rows.filter(heard).map(r => r.id), declaredWholeTrackElsewhere: state.declared });
  return { ...summary, mode: mode.mode, basis: mode.basis, flaggedSentences: flagged.length, flaggedUnheard: mode.missingFlagged.length,
    heardSentences: rows.filter(heard).length, declaredWholeTrackElsewhere: state.declared };
}

function renderCoverage() {
  const info = listening();
  $("coverage").value = info.shareAt1x;
  const modeText = { whole_track: info.basis === "declared" ? "整轨（你的声明）" : "整轨", flagged_only: "只听标记",
    partial: `还不够：有标记的 ${info.flaggedSentences} 句里还有 ${info.flaggedUnheard} 句没听` }[info.mode];
  const other = info.heardSecondsAnySpeed - info.heardSecondsAt1x;
  $("coverage-text").textContent = `已按 1 倍速听 ${fmtClock(info.heardSecondsAt1x)} / ${fmtClock(info.trackSeconds)}（${Math.round(info.shareAt1x * 100)}%）`
    + `${other > 0 ? `，另有 ${fmtClock(other)} 是变速听的` : ""}。听审方式：${modeText}。`;
}

function save(force) {
  if (!force && Date.now() - lastSave < 10000) return;
  lastSave = Date.now();
  draft.save({ marks: state.marks, clipHeard: [...state.clipHeard], declared: state.declared, position: state.position,
    coverage: coverage.snapshot(), decision: decision ? decision.state() : null });
}

function highlight(position) {
  let found = null;
  for (const row of rows) { if (row.start <= position) found = row; else break; }
  const id = found && position < found.start + Math.max(found.dur, 0.5) + 1 ? found.id : null;
  if (id === current) return;
  const previous = current;
  current = id;
  if (previous) refreshRow(previous);
  if (id) {
    refreshRow(id);
    if (state.follow && $(`row-${id}`)) $(`row-${id}`).scrollIntoView({ block: "center", behavior: "smooth" });
  }
}

function collect(verdict) {
  const info = listening();
  const issues = rows.filter(r => verdictOf(r.id) === "issue");
  const passed = rows.filter(r => verdictOf(r.id) === "pass").length;
  let blocked = null;
  if (issues.length) blocked = `有 ${issues.length} 句标了问题，不能直接通过；退回修改，或取消这些标记`;
  else if (info.mode === "partial") blocked = `有标记的句子还有 ${info.flaggedUnheard} 句没听；听完它们或按 1 倍速听完整轨后才能通过`;
  const marks = Object.fromEntries(Object.entries(state.marks).filter(([, m]) => m.verdict || m.note).map(([id, m]) => [id, m]));
  const modeText = { whole_track: info.basis === "declared" ? "整轨（你声明在别处听完）" : "整轨（页面测到）", flagged_only: "只听标记", partial: "不完整" }[info.mode];
  return {
    blocked, hasIssues: issues.length > 0,
    payload: { locale: data.locale, rows: marks, issueIds: issues.map(r => r.id), listening: info },
    client: { reviewMode: info.mode },
    summary: [
      verdict === "approved" ? `${LOCALE_NAMES[data.locale] || data.locale}音轨通过` : `${LOCALE_NAMES[data.locale] || data.locale}音轨退回修改`,
      `听审方式：${modeText}；按 1 倍速听了 ${fmtClock(info.heardSecondsAt1x)} / ${fmtClock(info.trackSeconds)}`,
      `逐句：通过 ${passed} 句，有问题 ${issues.length} 句，听过 ${info.heardSentences} / ${rows.length} 句`,
      issues.length ? `要改的句子：${issues.slice(0, 8).map(r => r.id).join("、")}${issues.length > 8 ? " 等" : ""}` : "没有标问题的句子",
      verdict === "approved" ? "收据会绑定这一版音轨的哈希；之后重配就要重新听" : "改完只重配这些句子，再请你听",
    ],
  };
}

async function main() {
  gate = await loadGate("track");
  data = gate.data;
  rows = data.rows;
  draft = createDraft(gate);
  coverage = createCoverage(data.track.seconds);
  const saved = draft.load();
  if (saved) {
    state.marks = saved.marks || {};
    state.clipHeard = new Set(saved.clipHeard || []);
    state.declared = Boolean(saved.declared);
    state.position = saved.position || 0;
    coverage.restore(saved.coverage);
  }
  const sync = data.sync;
  $("track-facts").replaceChildren(
    h("dt", { text: "语言" }), h("dd", { text: LOCALE_NAMES[data.locale] || data.locale }),
    h("dt", { text: "时长" }), h("dd", { text: `${fmtDuration(data.track.seconds)}，共 ${rows.length} 句，${rows.filter(r => r.flags.length).length} 句有标记` }),
    h("dt", { text: "同步" }), h("dd", { text: sync.mode === "synced"
      ? `跟视频同步；最大落后 ${sync.maxLagSeconds.toFixed(1)} 秒，超过 8 秒的 ${sync.over8s} 句` : "独立音轨，不跟视频同步" }),
    h("dt", { text: "配音" }), h("dd", { text: data.track.voice || "—" }),
    h("dt", { text: "音轨哈希" }), h("dd", { class: "mono", title: data.track.trackWavSha256, text: short(data.track.trackWavSha256) }));
  const previous = data.previous;
  if (previous) {
    const count = name => previous[name].length;
    $("previous").hidden = false;
    $("previous").textContent = `这是第 ${gate.revision} 版。你在上一版标了 ${previous.issues} 句：按你的要求改字 ${count("fixed")} 句，`
      + `重新配音 ${count("rerendered")} 句（改字的句子和它同一批的句子都会重配）${count("unclear") ? `，没看懂要求、没有改 ${count("unclear")} 句` : ""}。`
      + "其余句子的文字和声音与上一版相同。点「这次改的」只听这些句子。";
    $("filters").querySelector('[data-filter="changed"]').hidden = false;
  }
  $("sync-check").hidden = sync.mode !== "synced";
  $("declared").checked = state.declared;
  $("declared").disabled = gate.state !== "open";

  const track = $("track");
  track.src = mediaUrl(gate, data.track.audio, { seconds: data.track.seconds, hz: 330 });
  if (data.track.video && !demo) { $("video-card").hidden = false; $("video").src = mediaUrl(gate, data.track.video); }

  decision = setupDecision(gate, { collect, onChange: () => decision && save(true) });
  if (saved) decision.restore(saved.decision);
  render(); renderCoverage();

  const clips = createClipPlayer(gate, $("clip"), { onPlayed(button) {
    const id = button.closest(".row").dataset.id;
    if (!button.dataset.audio.endsWith(rows.find(r => r.id === id).dub)) return;   // source only does not count
    state.clipHeard.add(id); refreshRow(id); renderCoverage(); decision.refresh(); save(true);
  } });
  track.addEventListener("play", () => clips.stop());
  $("clip").addEventListener("play", () => track.pause());
  track.addEventListener("timeupdate", () => {
    coverage.tick(track.currentTime, track.playbackRate);
    state.position = track.currentTime;
    highlight(track.currentTime);
    renderCoverage();
    save(false);
  });
  for (const name of ["pause", "seeking", "ended"]) track.addEventListener(name, () => { coverage.stop(); decision.refresh(); save(true); });
  $("resume").addEventListener("click", () => { track.currentTime = state.position; track.play(); });
  $("follow").addEventListener("click", event => {
    state.follow = !state.follow;
    event.target.setAttribute("aria-pressed", String(state.follow));
  });
  $("declared").addEventListener("change", event => { state.declared = event.target.checked; renderCoverage(); decision.refresh(); save(true); });

  $("rows").addEventListener("click", event => {
    const row = event.target.closest(".row");
    if (!row) return;
    const id = row.dataset.id, action = event.target.closest("button[data-act]"), tag = event.target.closest("button[data-tag]");
    if (action && action.dataset.act === "seek") { track.currentTime = rows.find(r => r.id === id).start; track.play(); return; }
    if (action) { const entry = mark(id); entry.verdict = entry.verdict === action.dataset.act ? null : action.dataset.act; }
    else if (tag) { const entry = mark(id); entry.tags = entry.tags.includes(tag.dataset.tag) ? entry.tags.filter(t => t !== tag.dataset.tag) : [...entry.tags, tag.dataset.tag]; }
    else return;
    refreshRow(id); decision.refresh(); save(true);
  });
  $("rows").addEventListener("input", event => {
    if (!event.target.classList.contains("issue-note")) return;
    mark(event.target.closest(".row").dataset.id).note = event.target.value;
    save(false);
  });
  $("filters").addEventListener("click", event => {
    const button = event.target.closest("button[data-filter]");
    if (!button) return;
    state.filter = button.dataset.filter;
    for (const other of $("filters").querySelectorAll("button")) other.setAttribute("aria-pressed", String(other === button));
    render();
  });
  $("search").addEventListener("input", event => { state.query = event.target.value; render(); });
  window.addEventListener("pagehide", () => save(true));
}

main().catch(showFatal);
