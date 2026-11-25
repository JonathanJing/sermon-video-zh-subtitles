// l4.publish.authorization: authorize one publish intent and the deployments it lists.
// Machine checks are shown as machine checks; the authorization is the only human fact here.
import { $, h, loadGate, showFatal, setupDecision, createDraft, fmtWhen, LOCALE_NAMES } from "./gate.mjs";

let gate, data, decision;
const MAX_DEPLOYMENTS = 3;

function statusItem(ok, title, detail) {
  return h("li", { dataset: { ok: ok === null ? "" : String(ok) } },
    h("span", { class: "mark", text: ok === null ? "·" : ok ? "✓" : "✕" }),
    h("span", {}, title, detail ? h("small", { text: detail }) : null));
}

function collect(verdict) {
  const failing = data.preconditions.filter(item => item.ok === false);
  const notReady = data.deliverables.filter(item => item.deliver && item.state !== "ready");
  let blocked = null;
  if (failing.length) blocked = `发布前条件有 ${failing.length} 项没过：${failing[0].label}`;
  else if (data.deployments.length > MAX_DEPLOYMENTS) blocked = `计划了 ${data.deployments.length} 次部署，超过 ${MAX_DEPLOYMENTS} 次上限，先查清单是不是没列全`;
  else if (notReady.length) blocked = `要交付的 ${notReady[0].label} 还没准备好`;
  const other = data.deployments.filter(d => d.touchesOtherPages);
  return {
    blocked, hasIssues: false,
    payload: { intentId: data.intent.id, pageId: data.intent.pageId, environment: data.intent.environment,
      authorizedDeployments: verdict === "approved" ? data.deployments.map(d => d.n) : [],
      acknowledgedOtherPageChanges: other.map(d => d.n), maxDeployments: MAX_DEPLOYMENTS },
    summary: [
      verdict === "approved" ? `授权发布 ${data.intent.pageId} 到 ${data.intent.environment}` : "暂不发布，不会做任何部署",
      `发布意图 ${data.intent.id}：${data.deployments.length} 次部署`,
      ...data.deployments.map(d => `第 ${d.n} 次：${d.label}${d.touchesOtherPages ? "（会改动其他页面）" : ""}`),
      `七件套交付 ${data.deliverables.filter(d => d.deliver).length} 件，不交付 ${data.deliverables.filter(d => !d.deliver).length} 件`,
      verdict === "approved" ? "授权后自动部署、核验、过发布门禁；之后请你在手机上确认" : "准备好的文件保留，等你再授权",
    ],
  };
}

async function main() {
  gate = await loadGate("publish");
  data = gate.data;
  const intent = data.intent, page = data.page;
  $("intent").replaceChildren(
    h("dt", { text: "发布意图" }), h("dd", { class: "mono", text: intent.id }),
    h("dt", { text: "页面" }), h("dd", { class: "mono", text: intent.pageId }),
    h("dt", { text: "环境" }), h("dd", { text: `${intent.environment} · ${intent.origin}` }),
    h("dt", { text: "性质" }), h("dd", { text: intent.kindLabel }),
    h("dt", { text: "准备完成" }), h("dd", { text: fmtWhen(intent.preparedAt) }));
  $("meta-facts").replaceChildren(
    h("dt", { text: "日期" }), h("dd", { text: page.date }),
    h("dt", { text: "讲员" }), h("dd", { text: page.speaker }),
    h("dt", { text: "标题核对" }), h("dd", { text: page.titleCheck.detail }),
    h("dt", { text: "审核标注" }), h("dd", { text: page.reviewLabel }));
  $("meta").replaceChildren(...page.locales.map(item => h("article", { class: "row", lang: item.locale },
    h("div", { class: "row-head" }, h("strong", { text: LOCALE_NAMES[item.locale] || item.locale }), h("span", { class: "flag", text: item.category })),
    h("p", { class: "text", text: item.title }),
    h("p", { class: "secondary", text: `${item.series} · ${item.scripture}` }),
    h("p", { class: "secondary", text: item.badge }),
    h("p", { class: "secondary", text: item.note }),
    h("p", { class: "small mono", text: item.url }))));
  $("preconditions").replaceChildren(...data.preconditions.map(item => statusItem(item.ok, item.label, item.detail)));
  $("deliverables").replaceChildren(...data.deliverables.map(item => statusItem(item.deliver ? item.state === "ready" : null,
    `${item.n}. ${item.label}`, item.deliver ? `本轮交付 · ${item.state === "ready" ? "已准备好" : "还没准备好"} · 证据：${item.evidence}` : `本轮不交付：${item.reason}`)));
  $("deploy-count").textContent = `${data.deployments.length} / ${MAX_DEPLOYMENTS} 次`;
  $("deploy-count").className = `flag ${data.deployments.length > MAX_DEPLOYMENTS ? "bad" : ""}`;
  $("deployments").replaceChildren(...data.deployments.map(item => h("article", { class: `row${item.touchesOtherPages ? " flagged" : ""}` },
    h("div", { class: "row-head" }, h("strong", { text: `第 ${item.n} 次：${item.label}` }),
      item.touchesOtherPages ? h("span", { class: "flag warn", text: "会改动其他页面" }) : null),
    h("p", { class: "secondary", text: item.changes.join("；") }),
    item.touchesOtherPages ? h("p", { class: "text", text: item.otherPagesNote }) : null,
    h("p", { class: "small muted", text: `部署后核对：${item.verify}` }))));
  $("after").replaceChildren(...data.afterPublish.map(text => statusItem(null, text)));
  $("other-pages-check").hidden = !data.deployments.some(d => d.touchesOtherPages);

  const draft = createDraft(gate), saved = draft.load();
  decision = setupDecision(gate, { collect, onChange: () => decision && draft.save({ decision: decision.state() }) });
  if (saved) decision.restore(saved.decision);
}

main().catch(showFatal);
