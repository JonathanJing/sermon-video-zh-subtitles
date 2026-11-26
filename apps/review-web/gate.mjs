// Shared by every review page: load the gate, show what it binds to, keep a draft,
// submit one decision. A page never writes a receipt; it posts a decision that names the
// gate revision and the hashes it showed, and the Mac validates those before anything continues.

export const params = new URLSearchParams(location.search);
export const demo = params.has("demo");
export const $ = id => document.getElementById(id);

export const LOCALE_NAMES = { "zh-Hans": "中文", ko: "韩语", es: "西班牙语", en: "英文" };

export const STATE_TEXT = {
  pending: ["还没到这一步", "机器还在准备，暂时不用看。"],
  open: ["等你审核", "下面是机器产物，还没有人工结论。"],
  submitted: ["决定已提交", "已写入本机收件箱，等本机核对哈希并生成收据。"],
  applied: ["已应用", "本机已核对哈希并生成收据。"],
  changes_requested: ["已退回修改", "你要求修改。改完会出新版本，再请你审。"],
  stale: ["这一版已过期", "页面展示的文件已经变了，这一版不能再提交。请回总览打开新版本。"],
  skipped: ["本期不需要", "本期不走这一步。"],
};

// Element builder. Attributes only: no style, no inline handlers (CSP style-src/script-src 'self').
export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "text") el.textContent = value;
    else if (key === "dataset") Object.assign(el.dataset, value);
    else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else if (value === true) el.setAttribute(key, "");
    else el.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

export function fmtClock(seconds) {
  const s = Math.max(0, Math.floor(seconds || 0));
  const pad = n => String(n).padStart(2, "0");
  return s >= 3600 ? `${Math.floor(s / 3600)}:${pad(Math.floor(s / 60) % 60)}:${pad(s % 60)}` : `${pad(Math.floor(s / 60))}:${pad(s % 60)}`;
}

export function fmtDuration(seconds) {
  const s = Math.round(seconds || 0);
  return s >= 60 ? `${Math.floor(s / 60)} 分 ${s % 60} 秒` : `${s} 秒`;
}

export const short = sha => (sha ? String(sha).slice(0, 12) : "—");

export function fmtWhen(iso) {
  if (!iso) return "—";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? String(iso) : date.toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

// Links between pages keep the production and the demo switch.
export function pageHref(page, gateId, production = params.get("production")) {
  const query = new URLSearchParams();
  if (demo) query.set("demo", "1");
  else {
    if (production) query.set("production", production);
    if (gateId) query.set("gate", gateId);
  }
  const text = query.toString();
  return text ? `${page}?${text}` : page;
}

async function getJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`读取失败（HTTP ${response.status}）：${url}`);
  return response.json();
}

export function showFatal(error) {
  const strip = $("label-strip");
  if (strip) {
    strip.dataset.state = "error";
    strip.replaceChildren(h("strong", { text: "打不开这一页" }), String(error.message || error));
  }
  const actions = $("actions");
  if (actions) actions.hidden = true;
}

export async function loadIndex() {
  const query = params.get("production") ? `?production=${encodeURIComponent(params.get("production"))}` : "";
  return getJson(demo ? "demo/index.json" : `api/gates${query}`);
}

export async function loadGate(kind) {
  const url = demo ? `demo/${kind}.json`
    : `api/gate?production=${encodeURIComponent(params.get("production") || "")}&gate=${encodeURIComponent(params.get("gate") || "")}`;
  const gate = await getJson(url);
  if (gate.schemaVersion !== "sermon-review-gate-v1") throw new Error(`不认识的任务版本：${gate.schemaVersion}`);
  if (gate.kind !== kind) throw new Error(`这个任务是「${gate.kind}」，不该在这一页打开`);
  renderShell(gate);
  return gate;
}

export function renderState(gate) {
  const strip = $("label-strip");
  if (!strip) return;
  const [title, detail] = STATE_TEXT[gate.state] || [gate.state, ""];
  strip.dataset.state = gate.state;
  strip.replaceChildren(h("strong", { text: demo ? `演示 · ${title}` : title }), detail);
}

function renderShell(gate) {
  const back = $("back");
  if (back) back.href = pageHref("index.html");
  const episode = gate.episode || {};
  const parts = [episode.sunday, episode.title, episode.speaker, gate.locale ? LOCALE_NAMES[gate.locale] || gate.locale : null];
  if ($("episode")) $("episode").textContent = parts.filter(Boolean).join(" · ");
  renderState(gate);
  const bindings = $("bindings");
  if (bindings) {
    const viewer = gate.viewer || {};
    const who = viewer.login ? `${viewer.name || viewer.login}（${viewer.source === "tailscale" ? "Tailscale 身份" : viewer.source || "本机"}）` : "未识别";
    bindings.replaceChildren(
      h("dt", { text: "审核者" }), h("dd", { text: who }),
      h("dt", { text: "任务" }), h("dd", { class: "mono", text: `${gate.gateId} · 第 ${gate.revision} 版` }),
      ...Object.entries(gate.bindings || {}).flatMap(([name, value]) => [
        h("dt", { class: "mono", text: name }), h("dd", { class: "mono", title: String(value), text: short(value) })]));
  }
  if (gate.lastDecision) renderResult(gate, gate.lastDecision);
}

// What happened to a submitted decision. Submitted, applied and next-step-started are
// separate facts; the page shows each one on its own line and never merges them into "done".
export function renderResult(gate, last, sent) {
  const box = $("result");
  if (!box) return;
  box.hidden = false;
  const outcome = last.outcome || "queued";
  const failed = outcome === "rejected_stale" || outcome === "failed";
  const applied = outcome === "applied";
  const verdictText = last.verdict === "approved" ? "同意" : "要求修改";
  const steps = [
    ["true", `决定已提交：${verdictText} · ${last.reviewer || "审核者未识别"} · ${fmtWhen(last.submittedAt)}`],
    [failed ? "failed" : String(applied), failed
      ? (outcome === "rejected_stale" ? "本机拒绝：文件已变化，这一版作废，没有产生批准" : `本机处理失败：${last.message || "见本机日志"}`)
      : (applied ? `本机已核对哈希并生成收据${last.receiptSha256 ? ` ${short(last.receiptSha256)}` : ""}` : "等待本机核对哈希并生成收据")],
    [String(Boolean(last.nextStage)), last.nextStage ? `下一步已开始：${last.nextStage}` : "下一步尚未开始"],
  ];
  const list = h("ol", { class: "steps" }, steps.map(([done, text]) => h("li", { dataset: { done }, text })));
  const children = [h("h2", { text: demo ? "演示：这是将要提交的决定（没有发送）" : "提交结果" })];
  if (!demo) children.push(list, h("p", { class: "small muted", text: `决定编号 ${last.decisionId || "—"}` }));
  if (sent) children.push(h("pre", { class: "json", text: JSON.stringify(sent, null, 2) }));
  box.replaceChildren(...children);
}

// Draft: what the reviewer has done so far on this device, for this exact revision.
export function createDraft(gate) {
  const key = `sermon-review-draft:${gate.production}:${gate.gateId}:${gate.revision}:${JSON.stringify(gate.bindings || {})}`;
  return {
    load() { try { return JSON.parse(localStorage.getItem(key) || "null"); } catch { return null; } },
    save(value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* the form still works */ } },
    clear() { try { localStorage.removeItem(key); } catch { /* nothing to clear */ } },
  };
}

function newKey() {
  if (crypto.randomUUID) return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, b => b.toString(16).padStart(2, "0")).join("");
}

export async function submitDecision(gate, body, idempotencyKey) {
  const decision = {
    schemaVersion: "sermon-review-decision-v1",
    gateId: gate.gateId, kind: gate.kind, production: gate.production, locale: gate.locale ?? null,
    revision: gate.revision, bindings: gate.bindings || {},
    verdict: body.verdict, checks: body.checks || {}, payload: body.payload || {}, note: body.note || "",
    idempotencyKey,
    client: { submittedAt: new Date().toISOString(), userAgent: navigator.userAgent, ...(body.client || {}) },
  };
  if (demo) return { demo: true, decision };
  const response = await fetch("api/decisions", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(decision) });
  const reply = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(reply.message || `提交失败（HTTP ${response.status}）`);
  return { ...reply, decision };
}

// The decision bar every gate page ends with.
//   collect(verdict) -> { payload, client?, summary: [lines], blocked?: "why approving is not possible" }
// The fixed checks are the checkboxes inside #checks; all of them must be ticked to approve.
export function setupDecision(gate, { collect, onChange }) {
  const approve = $("approve"), reject = $("request-changes"), note = $("note"), hint = $("hint");
  const dialog = $("confirm-dialog");
  const boxes = Array.from(document.querySelectorAll("#checks input[type=checkbox][data-check]"));
  const editable = gate.state === "open";
  let pendingVerdict = null, key = null;

  function checks() { return Object.fromEntries(boxes.map(box => [box.dataset.check, box.checked])); }
  function refresh() {
    const unticked = boxes.filter(box => !box.checked && !box.closest("[hidden]")).length;
    const blocked = editable ? collect("approved").blocked : "这一版已不能提交";
    approve.disabled = !editable || Boolean(blocked) || unticked > 0;
    reject.disabled = !editable;
    hint.textContent = blocked || (unticked ? `还有 ${unticked} 项确认没有勾` : "");
    if (onChange) onChange();
  }
  function open(verdict) {
    const result = collect(verdict);
    if (verdict === "changes_requested" && !note.value.trim() && !result.hasIssues) {
      hint.textContent = "要求修改时，请在备注里写清要改什么，或在条目上标出问题";
      note.focus();
      return;
    }
    pendingVerdict = verdict;
    key = key || newKey();
    $("confirm-title").textContent = verdict === "approved" ? approve.textContent.trim() : reject.textContent.trim();
    $("confirm-summary").replaceChildren(...result.summary.map(line => h("li", { text: line })));
    $("submit-error").textContent = "";
    dialog.showModal();
  }
  async function send() {
    const result = collect(pendingVerdict);
    $("confirm-send").disabled = true;
    try {
      const reply = await submitDecision(gate, {
        verdict: pendingVerdict, checks: checks(), payload: result.payload, note: note.value.trim(), client: result.client }, key);
      dialog.close();
      gate.state = "submitted";
      if (!demo) renderState(gate);
      for (const control of document.querySelectorAll("main input, main textarea, main select, main button:not(.play), #actions button")) control.disabled = true;
      renderResult(gate, { decisionId: reply.decisionId, verdict: pendingVerdict, reviewer: reply.reviewer,
        submittedAt: reply.decision.client.submittedAt, outcome: reply.outcome || "queued" }, demo ? reply.decision : null);
      $("result").scrollIntoView({ behavior: "smooth" });
      if (!demo) { createDraft(gate).clear(); poll(); }
    } catch (error) {
      $("submit-error").textContent = String(error.message || error);
    } finally {
      $("confirm-send").disabled = false;
    }
  }
  // After a real submit, ask the Mac what it did with the decision.
  function poll(attempt = 0) {
    if (attempt > 60) return;
    setTimeout(async () => {
      try {
        const fresh = await getJson(`api/gate?production=${encodeURIComponent(gate.production)}&gate=${encodeURIComponent(gate.gateId)}`);
        if (fresh.lastDecision) renderResult(fresh, fresh.lastDecision);
        if (fresh.state !== gate.state) { gate.state = fresh.state; renderState(gate); }
        if (fresh.lastDecision && ["applied", "rejected_stale", "failed"].includes(fresh.lastDecision.outcome) && fresh.lastDecision.nextStage !== undefined) return;
      } catch { /* the Mac may be busy; keep asking */ }
      poll(attempt + 1);
    }, 5000);
  }

  for (const box of boxes) box.addEventListener("change", refresh);
  note.addEventListener("input", refresh);
  approve.addEventListener("click", () => open("approved"));
  reject.addEventListener("click", () => open("changes_requested"));
  $("confirm-send").addEventListener("click", send);
  $("confirm-cancel").addEventListener("click", () => dialog.close());
  if (!editable) for (const control of document.querySelectorAll("#checks input, #note")) control.disabled = true;
  refresh();
  return {
    refresh, checks,
    state() { return { checks: checks(), note: note.value }; },
    restore(saved) {
      if (!saved) return;
      for (const box of boxes) box.checked = Boolean(saved.checks && saved.checks[box.dataset.check]);
      note.value = saved.note || "";
      refresh();
    },
  };
}

// A short tone stands in for audio in demo mode, so the controls can be tried without recordings.
const tones = new Map();
export function toneUrl(seconds = 0.6, hz = 440) {
  const id = `${seconds}:${hz}`;
  if (tones.has(id)) return tones.get(id);
  const rate = 8000, count = Math.floor(rate * seconds);
  const buffer = new ArrayBuffer(44 + count * 2), view = new DataView(buffer);
  const write = (offset, text) => [...text].forEach((c, i) => view.setUint8(offset + i, c.charCodeAt(0)));
  write(0, "RIFF"); view.setUint32(4, 36 + count * 2, true); write(8, "WAVEfmt ");
  view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, rate, true); view.setUint32(28, rate * 2, true); view.setUint16(32, 2, true);
  view.setUint16(34, 16, true); write(36, "data"); view.setUint32(40, count * 2, true);
  for (let i = 0; i < count; i += 1) {
    const fade = Math.min(1, i / 400, (count - i) / 400);
    view.setInt16(44 + i * 2, Math.sin((i / rate) * 2 * Math.PI * hz) * 5000 * fade, true);
  }
  const url = URL.createObjectURL(new Blob([buffer], { type: "audio/wav" }));
  tones.set(id, url);
  return url;
}

export function mediaUrl(gate, path, { seconds = 0.6, hz = 440 } = {}) {
  return demo ? toneUrl(seconds, hz) : (gate.assetsBase || "") + path;
}

// One audio element for every per-row play button on a page. Buttons carry data-audio
// (a path under the gate's assets) and optionally data-hz for the demo tone.
export function createClipPlayer(gate, audio, { onPlayed } = {}) {
  let button = null, queue = [];
  function reset() {
    if (button) { button.setAttribute("aria-pressed", "false"); button.textContent = button.dataset.label || "▶"; }
    button = null;
  }
  function start(target, paths) {
    audio.pause();
    reset();
    button = target;
    queue = paths.slice(1);
    button.dataset.label = button.dataset.label || button.textContent;
    button.setAttribute("aria-pressed", "true");
    button.textContent = "■";
    audio.src = mediaUrl(gate, paths[0], { hz: Number(target.dataset.hz) || 440 });
    audio.play().catch(reset);
  }
  audio.addEventListener("ended", () => {
    if (queue.length && button) {
      audio.src = mediaUrl(gate, queue.shift(), { hz: 660 });
      audio.play().catch(reset);
      return;
    }
    const done = button;
    reset();
    if (done && onPlayed) onPlayed(done);
  });
  document.addEventListener("click", event => {
    const target = event.target.closest("button.play[data-audio]");
    if (!target) return;
    if (target === button) { audio.pause(); reset(); return; }
    start(target, target.dataset.audio.split("|"));
  });
  return { stop() { audio.pause(); reset(); } };
}

export function playButton(path, label = "▶", title = "播放") {
  return h("button", { type: "button", class: "play small", "data-audio": path, "aria-pressed": "false", title, text: label });
}
