// l1.speakers: dual-speaker only. Confirm which diarization label is which speaker and
// settle every sentence the word vote could not assign with confidence (share < minShare).
import { $, h, loadGate, showFatal, setupDecision, createDraft, createClipPlayer, playButton, fmtClock, fmtDuration } from "./gate.mjs";

let gate, data, decision, draft;
const state = { mapping: {}, sentences: {}, bulk: 0, heard: [] };
const nameOf = id => (data.speakers.find(s => s.id === id) || { name: id }).name;

function speakerButtons(current, attrs) {
  return h("div", { class: "seg", role: "group" }, data.speakers.map(speaker => h("button", { type: "button", class: "small",
    "aria-pressed": String(current === speaker.id), disabled: gate.state !== "open", dataset: { ...attrs, speaker: speaker.id }, text: speaker.name })));
}

function renderLabels() {
  $("labels").replaceChildren(...data.labels.map(item => h("article", { class: "row" },
    h("div", { class: "row-head" }, h("strong", { class: "mono", text: item.label }),
      h("span", { text: `共 ${fmtDuration(item.seconds)}` }),
      h("span", { class: "flag", text: `机器建议：${nameOf(item.proposed)}` })),
    item.samples.map(sample => h("div", { class: "row-tools" }, playButton(sample.audio, "▶", "听样本"),
      h("span", { class: "secondary", lang: "en", text: sample.english }))),
    speakerButtons(state.mapping[item.label], { label: item.label }))));
}

function renderRows() {
  const done = data.toCheck.filter(row => state.sentences[row.id]).length;
  $("shown").textContent = `已确认 ${done} / ${data.toCheck.length} 句`;
  $("rows-lead").textContent = `机器按词投票给每句定讲员；下面 ${data.toCheck.length} 句的一致度低于 ${data.minShare}，多半是短附和或两人同时说话。听一下，点对应的讲员。`;
  $("rows").replaceChildren(...data.toCheck.map(row => h("article", { class: `row${state.sentences[row.id] ? " pass" : " flagged"}`, dataset: { id: row.id } },
    h("div", { class: "row-head" }, h("span", { class: "id", text: row.id }), h("span", { text: fmtClock(row.start) }),
      h("span", { class: "flag warn", text: `一致度 ${row.share.toFixed(2)}` }),
      h("span", { class: "flag", text: `机器建议：${nameOf(row.proposed)}` })),
    row.before ? h("p", { class: "secondary", lang: "en", text: `前一句：${row.before}` }) : null,
    h("p", { class: "text", lang: "en", text: row.english }),
    row.after ? h("p", { class: "secondary", lang: "en", text: `后一句：${row.after}` }) : null,
    h("div", { class: "row-tools" }, playButton(row.audio, "▶", "听这一句"), speakerButtons(state.sentences[row.id], { sentence: row.id })))));
}

function save() { draft.save({ ...state, decision: decision ? decision.state() : null }); }

function collect(verdict) {
  const open = data.toCheck.filter(row => !state.sentences[row.id]).length;
  const unmapped = data.labels.filter(item => !state.mapping[item.label]).length;
  const changed = data.toCheck.filter(row => state.sentences[row.id] && state.sentences[row.id] !== row.proposed).length;
  const used = new Set(Object.values(state.mapping));
  let blocked = null;
  if (unmapped) blocked = `还有 ${unmapped} 个标签没定讲员`;
  else if (used.size < data.labels.length) blocked = "两个标签不能是同一位讲员";
  else if (open) blocked = `还有 ${open} 句没确认`;
  return {
    blocked, hasIssues: false,
    payload: { mapping: state.mapping, sentences: state.sentences, heardIds: state.heard },
    client: { bulkAccepted: state.bulk, heard: state.heard.length },
    summary: [
      verdict === "approved" ? "确认讲员，之后按这个结果翻译和配音" : "不确认，退回修改",
      ...data.labels.map(item => `${item.label} 是 ${state.mapping[item.label] ? nameOf(state.mapping[item.label]) : "未定"}`),
      `存疑 ${data.toCheck.length} 句：与机器建议不同 ${changed} 句，一次性按建议接受 ${state.bulk} 句，听过 ${state.heard.length} 句`,
    ],
  };
}

async function main() {
  gate = await loadGate("speakers");
  data = gate.data;
  draft = createDraft(gate);
  const saved = draft.load();
  state.mapping = Object.fromEntries(data.labels.map(item => [item.label, null]));
  if (saved) Object.assign(state, { mapping: saved.mapping, sentences: saved.sentences, bulk: saved.bulk || 0, heard: saved.heard || [] });
  $("summary").replaceChildren(...data.bySpeaker.flatMap(row => [
    h("dt", { text: nameOf(row.speakerId) }), h("dd", { text: `${row.sentences} 句 · ${fmtDuration(row.seconds)}` })]),
    h("dt", { text: "全篇" }), h("dd", { text: `${data.sentenceCount} 句，其中 ${data.toCheck.length} 句要你确认` }));
  decision = setupDecision(gate, { collect, onChange: () => decision && save() });
  if (saved) decision.restore(saved.decision);
  renderLabels(); renderRows(); decision.refresh();

  createClipPlayer(gate, $("clip"), { onPlayed(button) {
    const row = button.closest(".row[data-id]");
    if (row && !state.heard.includes(row.dataset.id)) { state.heard.push(row.dataset.id); save(); }
  } });
  document.addEventListener("click", event => {
    const button = event.target.closest("button[data-speaker]");
    if (!button) return;
    if (button.dataset.label) { state.mapping[button.dataset.label] = button.dataset.speaker; renderLabels(); }
    else { state.sentences[button.dataset.sentence] = button.dataset.speaker; renderRows(); }
    decision.refresh();
  });
  $("accept-rest").disabled = gate.state !== "open";
  $("accept-rest").addEventListener("click", () => {
    for (const row of data.toCheck) if (!state.sentences[row.id]) { state.sentences[row.id] = row.proposed; state.bulk += 1; }
    renderRows(); decision.refresh();
  });
}

main().catch(showFatal);
