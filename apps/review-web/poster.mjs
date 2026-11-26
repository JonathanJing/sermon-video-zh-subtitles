// l4.poster: pick one of the composed posters, or send them all back. Approving is the instruction
// to upload the chosen one; nothing is uploaded before that, and nothing is ever sent anywhere else.
import { $, h, demo, loadGate, showFatal, setupDecision, createDraft, LOCALE_NAMES } from "./gate.mjs";

let gate, data, decision, draft;
const state = { choice: null, next: "redraw" };
const NEXT = { redraw: "同一个概念重画", redesign: "换概念重新设计", skip: "本周不发海报" };
const TIER = { title: "标题", scripture: "经文", teaching: "讲解", illustration: "例子" };

// A real page shows the composed PNG; the demo has no files, so it draws a labelled placeholder.
function imageUrl(path, label) {
  if (!demo) return (gate.assetsBase || "") + path;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 300"><rect width="200" height="300" fill="#2b3a37"/>`
    + `<text x="100" y="150" fill="#cfe3dd" font-size="18" text-anchor="middle">${label}</text></svg>`;
  return "data:image/svg+xml;utf8," + encodeURIComponent(svg);
}

function candidateElement(candidate) {
  const chosen = state.choice === candidate.id;
  return h("article", { class: `row${chosen ? " current" : ""}`, dataset: { id: candidate.id } },
    h("div", { class: "row-head" }, h("strong", { text: candidate.label }),
      candidate.lint ? h("span", { class: `flag ${candidate.lint.ok ? "" : "warn"}`, text: candidate.lint.text }) : null,
      h("span", { class: `flag ${candidate.qrOk ? "good" : "bad"}`, text: candidate.qrOk ? "二维码已解码核对" : "二维码没有核对通过" })),
    h("div", { class: "posters" }, candidate.locales.map(item => h("figure", {},
      h("a", { href: imageUrl(item.poster, item.locale), target: "_blank", rel: "noopener" },
        h("img", { src: imageUrl(item.preview, item.locale), alt: `${LOCALE_NAMES[item.locale] || item.locale}海报`, loading: "lazy", width: "600", height: "900" })),
      h("figcaption", { text: LOCALE_NAMES[item.locale] || item.locale })))),
    h("div", { class: "row-tools" },
      h("button", { type: "button", class: "small", "data-choose": candidate.id, "aria-pressed": String(chosen), disabled: gate.state !== "open", text: chosen ? "已选这一张" : "选这一张" })));
}

function render() {
  $("candidates").replaceChildren(...data.candidates.map(candidateElement));
  for (const button of $("next").querySelectorAll("button")) {
    button.setAttribute("aria-pressed", String(button.dataset.next === state.next));
    button.disabled = gate.state !== "open";
  }
}

function collect(verdict) {
  const candidate = data.candidates.find(item => item.id === state.choice);
  let blocked = null;
  if (verdict === "approved" && !candidate) blocked = "先选一张海报";
  else if (verdict === "approved" && !candidate.qrOk) blocked = "这一张的二维码没有核对通过，不能上传";
  return {
    blocked, hasIssues: false,
    payload: verdict === "approved"
      ? { pageId: data.pageId, round: data.round, choice: candidate ? candidate.id : null, artSha256: candidate ? candidate.artSha256 : null }
      : { pageId: data.pageId, round: data.round, next: state.next },
    summary: verdict === "approved"
      ? [`批准并上传：${candidate ? candidate.label : ""}`, `上传 ${data.upload.files.length} 个文件到 ${data.origin}`, "海报会出现在 App 的公告里", "不会发到聊天或邮件"]
      : [`这 ${data.candidates.length} 张都不用`, `接下来：${NEXT[state.next]}`, state.next === "skip" ? "本周不会有海报上线" : "新的候选出来后再请你看", "什么都不会上传"],
  };
}

async function main() {
  gate = await loadGate("poster");
  data = gate.data;
  draft = createDraft(gate);
  const saved = draft.load();
  if (saved) Object.assign(state, { choice: saved.choice || null, next: saved.next || "redraw" });
  $("page-facts").replaceChildren(
    h("dt", { text: "页面" }), h("dd", { class: "mono", text: data.pageId }),
    h("dt", { text: "标题" }), h("dd", { text: data.title }),
    h("dt", { text: "站点" }), h("dd", { class: "small mono", text: data.origin }));
  const concept = data.design.chosen;
  $("concept").replaceChildren(
    h("dt", { text: "概念" }), h("dd", { text: concept.concept }),
    h("dt", { text: "画面主体" }), h("dd", { text: concept.primarySubject }),
    h("dt", { text: "立足点" }), h("dd", { text: `${TIER[concept.anchorTier] || concept.anchorTier}里的「${concept.anchorTerm}」` }),
    h("dt", { text: "为什么选它" }), h("dd", { text: data.design.why }),
    h("dt", { text: "机器打分" }), h("dd", { text: `${concept.total} 分（这是起草模型自己打的，不是审核结论）` }));
  $("evidence").replaceChildren(...concept.evidence.map(row => h("li", {},
    h("span", { class: "mark", text: "·" }), h("span", {}, row.quote, h("small", { text: `${TIER[row.tier] || row.tier} · ${row.textGroupId}` })))));
  $("other-concepts").replaceChildren(...data.design.others.map(item => h("li", {},
    h("span", { class: "mark", text: "·" }), h("span", {}, item.concept, h("small", { text: `${item.total} 分${item.rejected ? ` · 没选的原因：${item.rejected}` : ""}` })))));
  $("round").textContent = `第 ${data.round} 轮`;
  $("upload-note").textContent = data.upload.note;
  $("upload-files").replaceChildren(...data.upload.files.map(path => h("li", {}, h("span", { class: "mark", text: "·" }), h("span", { class: "small mono", text: path }))));
  const save = () => draft.save({ ...state, decision: decision ? decision.state() : null });
  decision = setupDecision(gate, { collect, onChange: () => decision && save() });
  if (saved) decision.restore(saved.decision);
  render(); decision.refresh();
  $("candidates").addEventListener("click", event => {
    const button = event.target.closest("button[data-choose]");
    if (!button) return;
    state.choice = state.choice === button.dataset.choose ? null : button.dataset.choose;
    render(); save(); decision.refresh();
  });
  $("next").addEventListener("click", event => {
    const button = event.target.closest("button[data-next]");
    if (!button) return;
    state.next = button.dataset.next;
    render(); save(); decision.refresh();
  });
}

main().catch(showFatal);
