// l1.english-review: approve the English sentence table (Layer 1) before translation starts.
import { $, h, loadGate, showFatal, setupDecision, createDraft, createClipPlayer, playButton, fmtClock, fmtDuration } from "./gate.mjs";

const FLAGS = { edited: ["机器改过", "warn"], disagree: ["两遍不一致", "warn"], number: ["数字／经文", ""], long: ["超过 12 秒", ""] };
const state = { replace: {}, merge: new Set(), drop: new Set(), heard: new Set(), filter: "all", query: "", editing: null };
let gate, rows, decision, draft;

const textOf = row => state.replace[row.id] ?? row.english;
const touched = row => row.id in state.replace || state.merge.has(row.id) || state.drop.has(row.id);

function matches(row) {
  const f = state.filter;
  if (f === "flagged" && !row.flags.length) return false;
  if (f === "mine" && !touched(row)) return false;
  if (f === "unheard" && !(row.flags.length && !state.heard.has(row.id))) return false;
  if (FLAGS[f] && !row.flags.includes(f)) return false;
  const q = state.query.trim().toLowerCase();
  return !q || row.id.toLowerCase().includes(q) || textOf(row).toLowerCase().includes(q);
}

function rowElement(row) {
  const index = rows.indexOf(row);
  const dropped = state.drop.has(row.id), merged = state.merge.has(row.id), mine = row.id in state.replace;
  const editing = state.editing === row.id && gate.state === "open";
  const flags = row.flags.map(f => h("span", { class: `flag ${FLAGS[f][1]}`, text: FLAGS[f][0] }));
  if (mine) flags.push(h("span", { class: "flag good", text: "你改过" }));
  if (merged) flags.push(h("span", { class: "flag good", text: "并入上一句" }));
  if (dropped) flags.push(h("span", { class: "flag bad", text: "删除" }));
  if (state.heard.has(row.id)) flags.push(h("span", { class: "flag", text: "已听" }));
  const act = (name, label, pressed) => h("button", { type: "button", class: "small", "data-act": name,
    "aria-pressed": pressed === undefined ? null : String(pressed), disabled: gate.state !== "open", text: label });
  return h("article", { class: `row${row.flags.length ? " flagged" : ""}${dropped ? " dropped" : ""}`, id: `row-${row.id}`, dataset: { id: row.id } },
    h("div", { class: "row-head" },
      h("span", { class: "id", text: row.id }),
      h("span", { text: `${fmtClock(row.start)} · ${row.seconds.toFixed(1)} 秒` }), ...flags),
    editing ? h("textarea", { class: "edit", lang: "en", "aria-label": `${row.id} 的英文`, text: textOf(row) })
      : h("p", { class: "text", lang: "en", text: textOf(row) }),
    mine ? h("p", { class: "before", lang: "en", text: row.english }) : (row.before ? h("p", { class: "before", lang: "en", text: row.before }) : null),
    row.secondPass ? h("p", { class: "secondary", lang: "en", text: `第二遍转写：${row.secondPass}` }) : null,
    h("div", { class: "row-tools" },
      playButton(row.audio, "▶", "听这一句的原声"),
      editing ? [act("save", "保存"), act("cancel", "取消")] : act("edit", "改字"),
      row.secondPass && !editing ? act("use-second", "采用第二遍") : null,
      index > 0 ? act("merge", "并入上一句", merged) : null,
      act("drop", "删除", dropped),
      touched(row) ? act("reset", "还原") : null));
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

function save() {
  draft.save({ replace: state.replace, merge: [...state.merge], drop: [...state.drop], heard: [...state.heard], decision: decision.state() });
}

function onRowAction(event) {
  const button = event.target.closest("button[data-act]");
  if (!button) return;
  const id = button.closest(".row").dataset.id, row = rows.find(r => r.id === id);
  const action = button.dataset.act;
  if (action === "edit") state.editing = id;
  else if (action === "cancel") state.editing = null;
  else if (action === "save") {
    const text = button.closest(".row").querySelector("textarea").value.replace(/\s+/g, " ").trim();
    if (text && text !== row.english) state.replace[id] = text; else delete state.replace[id];
    state.editing = null;
  } else if (action === "use-second") state.replace[id] = row.secondPass;
  else if (action === "merge") { state.merge.has(id) ? state.merge.delete(id) : state.merge.add(id); state.drop.delete(id); }
  else if (action === "drop") { state.drop.has(id) ? state.drop.delete(id) : state.drop.add(id); state.merge.delete(id); }
  else if (action === "reset") { delete state.replace[id]; state.merge.delete(id); state.drop.delete(id); }
  refreshRow(id);
  if (action === "edit") $(`row-${id}`).querySelector("textarea").focus();
  save();
  decision.refresh();
}

function collect(verdict) {
  const order = rows.map(r => r.id);
  const merges = [...state.merge].sort((a, b) => order.indexOf(a) - order.indexOf(b));
  const drops = [...state.drop].sort((a, b) => order.indexOf(a) - order.indexOf(b));
  const replaced = Object.keys(state.replace).filter(id => !state.drop.has(id));
  const kept = rows.length - drops.length - merges.length;
  const flagged = rows.filter(r => r.flags.length);
  const unheard = flagged.filter(r => !state.heard.has(r.id)).length;
  let blocked = null;
  if (state.editing) blocked = `${state.editing} 还在改字，先保存或取消`;
  else if (merges.some(id => state.drop.has(order[order.indexOf(id) - 1]))) blocked = "有一句要并入的上一句已标为删除";
  else if (kept < 1) blocked = "句表不能全部删除";
  const window = gate.data.summary.window;
  return {
    blocked,
    hasIssues: replaced.length + merges.length + drops.length > 0,
    payload: { edits: { replace: Object.fromEntries(replaced.map(id => [id, state.replace[id]])), mergeWithPrevious: merges, drop: drops },
      heardUnitIds: order.filter(id => state.heard.has(id)) },
    client: { heardUnits: state.heard.size, flaggedUnits: flagged.length, flaggedUnheard: unheard },
    summary: [
      verdict === "approved" ? `批准英文表：改完后共 ${kept} 句` : "不批准，退回修改",
      `你的修改：改字 ${replaced.length} 句，并入上一句 ${merges.length} 句，删除 ${drops.length} 句`,
      `原声已听 ${state.heard.size} 句；有标记的 ${flagged.length} 句里还有 ${unheard} 句没听`,
      `窗口：${fmtClock(window.start)}–${fmtClock(window.end)}`,
      verdict === "approved" ? "批准后开始三种语言的翻译" : "退回后不会开始翻译",
    ],
  };
}

async function main() {
  gate = await loadGate("english");
  rows = gate.data.rows;
  draft = createDraft(gate);
  const summary = gate.data.summary, count = name => rows.filter(r => r.flags.includes(name)).length;
  $("facts").replaceChildren(
    h("dt", { text: "来源文件" }), h("dd", { text: summary.fileName || "—" }),
    h("dt", { text: "媒体时长" }), h("dd", { text: fmtDuration(summary.durationSeconds) }),
    h("dt", { text: "句表" }), h("dd", { text: `${rows.length} 句，覆盖 ${fmtClock(rows[0].start)}–${fmtClock(rows[rows.length - 1].end)}` }),
    h("dt", { text: "转写" }), h("dd", { text: summary.transcription || "—" }),
    h("dt", { text: "要重点看" }), h("dd", { text: `机器改过 ${count("edited")} 句 · 两遍不一致 ${count("disagree")} 句 · 数字／经文 ${count("number")} 句 · 超过 12 秒 ${count("long")} 句` }));
  $("window-text").textContent = `按整段媒体 ${fmtClock(summary.window.start)}–${fmtClock(summary.window.end)} 登记；句表之外的开头结尾不翻译、不配音。`;

  const saved = draft.load();
  if (saved) {
    state.replace = saved.replace || {};
    state.merge = new Set(saved.merge || []);
    state.drop = new Set(saved.drop || []);
    state.heard = new Set(saved.heard || []);
  }
  decision = setupDecision(gate, { collect, onChange: () => draft && decision && save() });
  if (saved) decision.restore(saved.decision);
  render();

  createClipPlayer(gate, $("clip"), { onPlayed(button) {
    const id = button.closest(".row").dataset.id;
    if (!state.heard.has(id)) { state.heard.add(id); refreshRow(id); save(); }
  } });
  $("rows").addEventListener("click", onRowAction);
  $("filters").addEventListener("click", event => {
    const button = event.target.closest("button[data-filter]");
    if (!button) return;
    state.filter = button.dataset.filter;
    for (const other of $("filters").querySelectorAll("button")) other.setAttribute("aria-pressed", String(other === button));
    render();
  });
  $("search").addEventListener("input", event => { state.query = event.target.value; render(); });
}

main().catch(showFatal);
