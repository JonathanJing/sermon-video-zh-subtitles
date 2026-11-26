// l4.device-confirm: after publishing, the reviewer opens each language on their own device.
// This is device evidence. It is recorded apart from the HTTP checks and is not venue acceptance.
import { $, h, loadGate, showFatal, setupDecision, createDraft, fmtWhen, LOCALE_NAMES } from "./gate.mjs";

let gate, data, decision, draft;
const state = { items: {}, notes: {} };             // items: "<locale>:<key>" -> "ok" | "problem"
const STATES = { ok: "正常", problem: "有问题" };

function render() {
  $("locales").replaceChildren(...data.locales.map(locale => h("article", { class: "row" },
    h("div", { class: "row-head" }, h("strong", { text: LOCALE_NAMES[locale.locale] || locale.locale })),
    h("p", {}, h("a", { href: locale.url, target: "_blank", rel: "noopener", text: "打开网页" }),
      locale.appUrl ? [" · ", h("a", { href: locale.appUrl, target: "_blank", rel: "noopener", text: "在 App 里打开" })] : null),
    data.items.map(item => {
      const key = `${locale.locale}:${item.key}`;
      return h("div", { class: "row-tools" },
        h("span", {}, item.label, item.required ? h("span", { class: "flag", text: "必看" }) : null),
        h("div", { class: "seg", role: "group", "aria-label": item.label }, Object.entries(STATES).map(([value, label]) =>
          h("button", { type: "button", class: "small", "aria-pressed": String(state.items[key] === value), disabled: gate.state !== "open",
            dataset: { item: key, value }, text: label }))));
    }),
    h("input", { type: "text", placeholder: "有问题时写下看到了什么", value: state.notes[locale.locale] || "", disabled: gate.state !== "open",
      "aria-label": `${LOCALE_NAMES[locale.locale] || locale.locale}的问题说明`, dataset: { noteLocale: locale.locale } }))));
}

function device() {
  return { userAgent: navigator.userAgent, viewport: `${window.innerWidth}x${window.innerHeight}`,
    standalone: Boolean(window.matchMedia && window.matchMedia("(display-mode: standalone)").matches), language: navigator.language };
}

function collect(verdict) {
  const problems = Object.entries(state.items).filter(([, value]) => value === "problem").map(([key]) => key);
  const missing = data.locales.flatMap(locale => data.items.filter(item => item.required && state.items[`${locale.locale}:${item.key}`] !== "ok")
    .map(item => `${LOCALE_NAMES[locale.locale] || locale.locale}的「${item.label}」`));
  const total = data.locales.length * data.items.length, checked = Object.values(state.items).filter(Boolean).length;
  let blocked = null;
  if (problems.length) blocked = `有 ${problems.length} 项标了有问题，请用「报告问题」提交`;
  else if (missing.length) blocked = `必看的项目还没确认正常：${missing[0]}${missing.length > 1 ? ` 等 ${missing.length} 项` : ""}`;
  return {
    blocked, hasIssues: problems.length > 0,
    payload: { pageId: data.pageId, locales: Object.fromEntries(data.locales.map(locale => [locale.locale, {
      items: Object.fromEntries(data.items.map(item => [item.key, state.items[`${locale.locale}:${item.key}`] || "not_checked"])),
      note: (state.notes[locale.locale] || "").trim() }])), device: device() },
    summary: [
      verdict === "approved" ? "确认：在这台设备上看到的都正常" : "报告问题",
      `检查了 ${checked} / ${total} 项，其中有问题 ${problems.length} 项，没检查 ${total - checked} 项`,
      "没检查的项目会如实记为没检查",
      "这是设备上的确认，不代表现场使用的验收",
    ],
  };
}

async function main() {
  gate = await loadGate("confirm");
  data = gate.data;
  draft = createDraft(gate);
  const saved = draft.load();
  if (saved) Object.assign(state, { items: saved.items || {}, notes: saved.notes || {} });
  const published = data.published;
  $("published").replaceChildren(
    h("dt", { text: "页面" }), h("dd", { class: "mono", text: data.pageId }),
    h("dt", { text: "部署完成" }), h("dd", { text: fmtWhen(published.deployedAt) }),
    h("dt", { text: "发布门禁" }), h("dd", { text: published.gate }),
    h("dt", { text: "浏览器冒烟" }), h("dd", { text: published.smoke }),
    h("dt", { text: "现场验收" }), h("dd", { text: "没有做，不在这一页的范围内" }));
  const missing = data.notDelivered || [];          // what this publish intent left out: said here so nobody assumes it is live
  $("not-delivered-block").hidden = !missing.length;
  $("not-delivered").replaceChildren(...missing.map(text => h("li", {}, h("span", { class: "mark", text: "·" }), h("span", { text }))));
  const info = device();
  $("device").replaceChildren(
    h("dt", { text: "浏览器" }), h("dd", { class: "small", text: info.userAgent }),
    h("dt", { text: "窗口" }), h("dd", { text: `${info.viewport}${info.standalone ? " · 从主屏幕打开" : ""}` }));
  const save = () => draft.save({ ...state, decision: decision ? decision.state() : null });
  decision = setupDecision(gate, { collect, onChange: () => decision && save() });
  if (saved) decision.restore(saved.decision);
  render(); decision.refresh();
  $("locales").addEventListener("click", event => {
    const button = event.target.closest("button[data-item]");
    if (!button) return;
    state.items[button.dataset.item] = state.items[button.dataset.item] === button.dataset.value ? null : button.dataset.value;
    render(); decision.refresh();
  });
  $("locales").addEventListener("input", event => {
    const locale = event.target.dataset.noteLocale;
    if (locale) { state.notes[locale] = event.target.value; decision.refresh(); }
  });
}

main().catch(showFatal);
