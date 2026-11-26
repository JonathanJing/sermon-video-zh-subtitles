// The hub: every step of this week's production that needs a person, and its state.
import { $, h, demo, loadIndex, showFatal, pageHref, fmtWhen, STATE_TEXT, LOCALE_NAMES } from "./gate.mjs";

const PAGES = { decisions: "decisions.html", english: "english.html", speakers: "speakers.html", track: "track.html",
  study: "study.html", publish: "publish.html", confirm: "confirm.html", poster: "poster.html" };

function ago(iso) {
  const seconds = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (seconds < 90) return `${seconds} 秒前`;
  return seconds < 5400 ? `${Math.round(seconds / 60)} 分钟前` : `${Math.round(seconds / 3600)} 小时前`;
}

function render(index) {
  const episode = index.episode || {};
  $("episode").textContent = [episode.sunday, episode.title, episode.speaker].filter(Boolean).join(" · ");
  const open = index.gates.filter(gate => gate.state === "open");
  const strip = $("label-strip");
  strip.dataset.state = open.length ? "open" : "";
  const label = `${index.rehearsal ? "演练 · " : ""}${demo ? "演示数据" : (open.length ? `有 ${open.length} 步在等你` : "现在没有等你的步骤")}`;
  strip.replaceChildren(h("strong", { text: label }),
    (open.length ? open.map(gate => gate.title).join("、") : "机器在继续做，或这一期已经做完。")
      + (index.rehearsal ? " 这是演练，不产生任何人工批准。" : ""));

  const worker = index.worker || {};
  const stale = !demo && worker.lastSeenAt && Date.now() - new Date(worker.lastSeenAt).getTime() > 120000;
  $("heartbeat").textContent = worker.lastSeenAt ? `最近一次报告：${demo ? fmtWhen(worker.lastSeenAt) : ago(worker.lastSeenAt)}` : "没有收到报告";
  $("now").replaceChildren(
    h("dt", { text: "生产" }), h("dd", { class: "mono", text: index.production }),
    h("dt", { text: "当前阶段" }), h("dd", { text: worker.stage || "—" }),
    h("dt", { text: "进度" }), h("dd", { text: worker.detail || "—" }),
    h("dt", { text: "状态" }), h("dd", { text: stale ? "超过 2 分钟没有报告，生产机可能离线或卡住" : (worker.state || "—") }));

  $("waiting").textContent = `共 ${index.gates.length} 步`;
  $("gates").replaceChildren(...index.gates.map(gate => {
    const [stateText] = STATE_TEXT[gate.state] || [gate.state];
    const clickable = gate.state !== "pending" && gate.state !== "skipped";
    const title = gate.locale ? `${gate.title} · ${LOCALE_NAMES[gate.locale] || gate.locale}` : gate.title;
    const body = [
      h("span", { class: "gate-title", text: title }),
      h("span", { class: "gate-state", text: stateText }),
      h("span", { class: "gate-summary", text: [gate.summary, gate.openedAt && gate.state === "open" ? `${fmtWhen(gate.openedAt)} 起等你` : null,
        gate.decidedAt ? `${fmtWhen(gate.decidedAt)} 提交` : null].filter(Boolean).join(" · ") }),
    ];
    return h("li", {}, clickable
      ? h("a", { class: "gate-item", dataset: { state: gate.state }, href: pageHref(PAGES[gate.kind], gate.gateId, index.production) }, body)
      : h("div", { class: "gate-item", dataset: { state: gate.state } }, body));
  }));
}

async function refresh() {
  render(await loadIndex());
}

refresh().catch(showFatal);
if (!demo) setInterval(() => refresh().catch(() => {}), 30000);
