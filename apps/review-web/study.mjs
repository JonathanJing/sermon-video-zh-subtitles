// l4.study: approve the outline and the devotion, one conclusion per language.
// humanApproval for study content can only come from this page's reviewer, never from the drafting agent.
import { $, h, loadGate, showFatal, setupDecision, createDraft, short, LOCALE_NAMES } from "./gate.mjs";

let gate, data, decision, draft, active;
const state = { verdicts: {}, notes: {} };          // notes: "<locale>:<kind>:<index>" -> text
const VERDICT_TEXT = { approved: "批准", changes_requested: "要修改" };

function sectionRows(locale, kind) {
  const artifact = locale[kind];
  return artifact.sections.map((section, index) => {
    const key = `${locale.locale}:${kind}:${index}`;
    return h("article", { class: `row${state.notes[key] ? " issue" : ""}` },
      h("div", { class: "row-head" }, h("strong", { lang: locale.locale, text: section.title })),
      h("div", { class: "prose", lang: locale.locale }, h("p", { text: section.body })),
      h("details", {}, h("summary", { class: "small muted", text: `依据：讲道里的 ${section.sourceUnitIds.length} 句` }),
        h("div", { class: "rows" }, (section.evidence || []).map(unit => h("div", { class: "row" },
          h("div", { class: "row-head" }, h("span", { class: "id", text: unit.id })),
          h("p", { class: "secondary", lang: "en", text: unit.english }),
          unit.target ? h("p", { class: "secondary", lang: locale.locale, text: unit.target }) : null)))),
      h("input", { type: "text", placeholder: "这一节有问题就写在这里", value: state.notes[key] || "", disabled: gate.state !== "open",
        "aria-label": `${section.title} 的修改意见`, dataset: { noteKey: key } }));
  });
}

function render() {
  const locale = data.locales.find(l => l.locale === active);
  $("tabs").replaceChildren(...data.locales.map(l => h("button", { type: "button", role: "tab", "aria-selected": String(l.locale === active),
    "aria-pressed": String(l.locale === active), dataset: { locale: l.locale } },
    LOCALE_NAMES[l.locale] || l.locale, state.verdicts[l.locale] ? h("span", { class: `flag ${state.verdicts[l.locale] === "approved" ? "good" : "bad"}`, text: VERDICT_TEXT[state.verdicts[l.locale]] }) : null)));
  $("locale-facts").replaceChildren(
    h("dt", { text: "大纲" }), h("dd", { text: `${locale.outline.sections.length} 节 · 版本 ${short(locale.outline.sha256)}` }),
    h("dt", { text: "默想" }), h("dd", { text: `${locale.devotion.sections.length} 节 · 版本 ${short(locale.devotion.sha256)}` }),
    h("dt", { text: "起草" }), h("dd", { text: locale.draftedBy || "代理草稿，未经人工批准" }));
  $("outline").replaceChildren(...sectionRows(locale, "outline"));
  $("devotion").replaceChildren(...sectionRows(locale, "devotion"));
  for (const button of $("locale-verdict").querySelectorAll("button")) {
    button.setAttribute("aria-pressed", String(state.verdicts[active] === button.dataset.verdict));
    button.disabled = gate.state !== "open";
  }
  $("locale-status").replaceChildren(...data.locales.map(l => {
    const verdict = state.verdicts[l.locale];
    return h("li", { dataset: { ok: verdict ? String(verdict === "approved") : "" } },
      h("span", { class: "mark", text: verdict === "approved" ? "✓" : verdict ? "✕" : "·" }),
      h("span", {}, LOCALE_NAMES[l.locale] || l.locale, h("small", { text: verdict ? VERDICT_TEXT[verdict] : "还没给结论" })));
  }));
}

const notesFor = locale => Object.fromEntries(Object.entries(state.notes).filter(([key, text]) => key.startsWith(`${locale}:`) && text.trim())
  .map(([key, text]) => [key.slice(locale.length + 1), text.trim()]));

function collect(verdict) {
  const undecided = data.locales.filter(l => !state.verdicts[l.locale]);
  const rejected = data.locales.filter(l => state.verdicts[l.locale] === "changes_requested");
  const noted = data.locales.filter(l => state.verdicts[l.locale] === "approved" && Object.keys(notesFor(l.locale)).length);
  let blocked = null;
  if (undecided.length) blocked = `还有 ${undecided.length} 种语言没给结论`;
  else if (rejected.length) blocked = "有语言要修改，不能批准全部";
  else if (noted.length) blocked = "已批准的语言里还写着修改意见，先清掉或改成要修改";
  return {
    blocked, hasIssues: rejected.length > 0,
    payload: { locales: Object.fromEntries(data.locales.map(l => [l.locale, { verdict: state.verdicts[l.locale] || null,
      outlineSha256: l.outline.sha256, devotionSha256: l.devotion.sha256, sectionNotes: notesFor(l.locale) }])) },
    summary: [
      verdict === "approved" ? "批准全部语言的大纲与默想，可以随页面发布" : "有语言要修改",
      ...data.locales.map(l => `${LOCALE_NAMES[l.locale] || l.locale}：${VERDICT_TEXT[state.verdicts[l.locale]] || "未定"}`
        + `${Object.keys(notesFor(l.locale)).length ? `，${Object.keys(notesFor(l.locale)).length} 节有意见` : ""}`),
      verdict === "approved" ? "批准绑定当前这一版文本；之后再改就要重新批准" : "已批准的语言保留结论，要修改的语言改完再审",
    ],
  };
}

async function main() {
  gate = await loadGate("study");
  data = gate.data;
  draft = createDraft(gate);
  active = data.locales[0].locale;
  const saved = draft.load();
  if (saved) Object.assign(state, { verdicts: saved.verdicts || {}, notes: saved.notes || {} });
  const save = () => draft.save({ ...state, decision: decision ? decision.state() : null });
  decision = setupDecision(gate, { collect, onChange: () => decision && save() });
  if (saved) decision.restore(saved.decision);
  render(); decision.refresh();
  $("tabs").addEventListener("click", event => {
    const button = event.target.closest("button[data-locale]");
    if (button) { active = button.dataset.locale; render(); }
  });
  $("locale-verdict").addEventListener("click", event => {
    const button = event.target.closest("button[data-verdict]");
    if (!button) return;
    state.verdicts[active] = state.verdicts[active] === button.dataset.verdict ? null : button.dataset.verdict;
    render(); decision.refresh();
  });
  document.addEventListener("input", event => {
    const key = event.target.dataset && event.target.dataset.noteKey;
    if (key) { state.notes[key] = event.target.value; decision.refresh(); }
  });
}

main().catch(showFatal);
