// l0.decisions: the frozen kickoff decisions (runbook §0), prefilled from the weekly defaults.
import { $, h, loadGate, showFatal, setupDecision, createDraft, createClipPlayer, playButton, fmtClock, fmtDuration, short, fmtWhen, LOCALE_NAMES } from "./gate.mjs";

let gate, data, decision, draft;
const state = { values: {}, titles: {}, format: "title_only", window: { start: 0, end: 0 }, deliverables: [] };
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const locales = () => state.values.locales || [];
const speakerOption = () => data.choices.find(c => c.key === "speakerId").options.find(o => o.value === state.values.speakerId);

function renderChoices() {
  $("choices").replaceChildren(...data.choices.map(choice => {
    const value = state.values[choice.key];
    const changed = !same(value, choice.value);
    const buttons = choice.options.map(option => {
      const pressed = choice.multi ? value.includes(option.value) : value === option.value;
      const notes = [];
      if (choice.key === "speakerId") {
        const missing = locales().filter(l => !(option.locales || []).includes(l));
        if (missing.length) notes.push(`缺 ${missing.map(l => LOCALE_NAMES[l] || l).join("、")}`);
        if (!option.checkpointReady) notes.push("声音文件未就位");
      }
      return h("button", { type: "button", "aria-pressed": String(pressed), disabled: gate.state !== "open",
        dataset: { key: choice.key, value: option.value }, title: option.help || null },
        option.label, notes.length ? h("span", { class: "flag bad", text: notes.join(" · ") }) : null);
    });
    const picked = choice.options.filter(o => (choice.multi ? value.includes(o.value) : value === o.value) && o.help);
    return h("article", { class: `row${changed ? " flagged" : ""}` },
      h("div", { class: "row-head" }, h("strong", { text: choice.label }),
        h("span", { class: `flag ${changed ? "good" : ""}`, text: changed ? "你改过" : "默认" })),
      h("div", { class: "seg", role: "group", "aria-label": choice.label }, buttons),
      picked.map(o => h("p", { class: "secondary", text: o.help })),
      choice.evidence ? h("p", { class: "secondary", text: `依据：${choice.evidence}` }) : null);
  }));
}

function renderTitles() {
  const title = data.title;
  $("title-basis").textContent = title.basis === "title_table" ? `标题表第 ${title.week} 周` : "标题表里没有，需要你填";
  $("title-basis").className = `flag ${title.basis === "title_table" ? "" : "bad"}`;
  $("title-facts").replaceChildren(
    h("dt", { text: "英文原标题" }), h("dd", { lang: "en", text: title.english || "未识别" }),
    h("dt", { text: "经文" }), h("dd", { text: title.scripture || "未识别" }),
    h("dt", { text: "系列" }), h("dd", { text: (title.series && title.series["zh-Hans"]) || "未识别" }));
  $("titles").replaceChildren(...locales().map(locale => h("label", { class: "field" },
    h("span", { text: `${LOCALE_NAMES[locale] || locale}讲题` }),
    h("input", { type: "text", lang: locale, value: state.titles[locale] || "", disabled: gate.state !== "open", dataset: { titleLocale: locale } }))));
  for (const button of $("title-format").querySelectorAll("button")) {
    button.setAttribute("aria-pressed", String(button.dataset.format === state.format));
    button.disabled = gate.state !== "open";
  }
}

function renderWindow() {
  const { start, end } = state.window;
  $("window-start").value = start;
  $("window-end").value = end;
  const whole = start === 0 && Math.abs(end - data.window.mediaDuration) < 0.01;
  $("window-note").textContent = `当前窗口 ${fmtClock(start)}–${fmtClock(end)}，共 ${fmtDuration(end - start)}${whole ? "（整段媒体）" : "（你改过）"}。媒体全长 ${fmtDuration(data.window.mediaDuration)}。`;
}

function renderDeliverables() {
  $("deliverables").replaceChildren(...state.deliverables.map(item => h("article", { class: `row${item.deliver ? "" : " flagged"}` },
    h("div", { class: "row-head" }, h("strong", { text: `${item.n}. ${item.label}` })),
    h("div", { class: "seg" },
      h("button", { type: "button", class: "small", "aria-pressed": String(item.deliver), disabled: gate.state !== "open", dataset: { n: item.n, deliver: "1" }, text: "本轮交付" }),
      h("button", { type: "button", class: "small", "aria-pressed": String(!item.deliver), disabled: gate.state !== "open", dataset: { n: item.n, deliver: "0" }, text: "本轮不交付" })),
    item.deliver ? null : h("input", { type: "text", placeholder: "不交付的原因", value: item.reason || "", "aria-label": `第 ${item.n} 件不交付的原因`, dataset: { reasonFor: item.n } }))));
}

function save() { draft.save({ ...state, decision: decision ? decision.state() : null }); }

function collect(verdict) {
  const option = speakerOption(), picked = locales();
  const publishing = state.values.publish !== "none";
  const { start, end } = state.window;
  let blocked = null;
  if (!picked.length) blocked = "至少选一种语言";
  else if (!option) blocked = "请选讲员";
  else if (picked.some(l => !(option.locales || []).includes(l))) blocked = `${option.label} 没有所选语言的配音能力，换讲员或去掉那种语言`;
  else if (!option.checkpointReady) blocked = `${option.label} 的声音文件还没放到生产机上`;
  else if (publishing && picked.some(l => !(state.titles[l] || "").trim())) blocked = "要发布的语言都需要讲题";
  else if (!(start >= 0 && end > start && end <= data.window.mediaDuration + 0.01)) blocked = "窗口起止不对";
  else if (state.deliverables.some(d => !d.deliver && !(d.reason || "").trim())) blocked = "本轮不交付的那一件要写原因";
  const changed = data.choices.filter(c => !same(state.values[c.key], c.value)).map(c => c.key);
  if (!same(state.titles, data.title.titles) || state.format !== data.title.format) changed.push("title");
  if (!(start === data.window.start && end === data.window.end)) changed.push("window");
  if (state.deliverables.some(d => !d.deliver)) changed.push("deliverables");
  const label = key => { const c = data.choices.find(x => x.key === key); const v = state.values[key];
    return c.options.filter(o => (c.multi ? v.includes(o.value) : v === o.value)).map(o => o.label).join("、"); };
  const listen = Math.round((end - start) * 1.28 / 60) * picked.length;
  return {
    blocked,
    payload: { decisions: state.values, title: { basis: changed.includes("title") ? "approved_exception" : data.title.basis,
        english: data.title.english, format: state.format, titles: Object.fromEntries(picked.map(l => [l, (state.titles[l] || "").trim()])) },
      window: { start, end }, deliverables: state.deliverables.map(d => ({ n: d.n, deliver: d.deliver, reason: d.deliver ? null : d.reason })),
      changedFromDefaults: changed },
    summary: [
      verdict === "approved" ? "按以下决定开工，之后不再改" : "暂不开工，等你处理备注里的问题",
      `${label("form")} · ${label("locales")} · ${label("sync")} · ${label("publish")}`,
      `讲员 ${label("speakerId")} · 讲题「${state.titles[picked[0]] || "未填"}」`,
      `窗口 ${fmtClock(start)}–${fmtClock(end)} · 七件套交付 ${state.deliverables.filter(d => d.deliver).length} 件`,
      changed.length ? `与默认不同：${changed.map(key => ({ title: "标题", window: "窗口", deliverables: "交付范围" })[key]
        || data.choices.find(c => c.key === key).label).join("、")}` : "全部按默认值",
      `之后的听审大约 ${listen} 分钟（${picked.length} 条整轨）`,
    ],
  };
}

async function main() {
  gate = await loadGate("decisions");
  data = gate.data;
  draft = createDraft(gate);
  const saved = draft.load();
  Object.assign(state, {
    values: Object.fromEntries(data.choices.map(c => [c.key, c.value])), titles: { ...data.title.titles }, format: data.title.format,
    window: { start: data.window.start, end: data.window.end }, deliverables: data.deliverables.map(d => ({ ...d })) });
  if (saved) Object.assign(state, { values: saved.values, titles: saved.titles, format: saved.format, window: saved.window, deliverables: saved.deliverables });

  const source = data.source;
  $("source").replaceChildren(
    h("dt", { text: "文件" }), h("dd", {}, source.fileUrl ? h("a", { href: source.fileUrl, target: "_blank", rel: "noopener", text: source.fileName }) : source.fileName),
    h("dt", { text: "大小与时长" }), h("dd", { text: `${(source.sizeBytes / 1e9).toFixed(2)} GB · ${fmtDuration(source.durationSeconds)}` }),
    h("dt", { text: "上传时间" }), h("dd", { text: fmtWhen(source.uploadedAt) }),
    h("dt", { text: "媒体哈希" }), h("dd", { class: "mono", title: source.sha256, text: short(source.sha256) }),
    h("dt", { text: "来源署名" }), h("dd", { text: source.attribution }),
    h("dt", { text: "自动开工依据" }), h("dd", { text: source.authorization }));
  $("plan").replaceChildren(...data.plan.map(step => h("li", {}, h("span", { class: "mark", text: "·" }),
    h("span", {}, `${step.label}：${step.when}`, h("small", { text: step.effort })))));
  $("window-tools").replaceChildren(playButton(data.window.head, "▶ 开头 15 秒"), playButton(data.window.tail, "▶ 结尾 15 秒"));

  decision = setupDecision(gate, { collect, onChange: () => decision && save() });
  if (saved) decision.restore(saved.decision);
  const rerender = () => { renderChoices(); renderTitles(); renderWindow(); renderDeliverables(); decision.refresh(); };
  rerender();
  createClipPlayer(gate, $("clip"));

  $("choices").addEventListener("click", event => {
    const button = event.target.closest("button[data-key]");
    if (!button) return;
    const choice = data.choices.find(c => c.key === button.dataset.key), value = button.dataset.value;
    if (choice.multi) {
      const set = new Set(state.values[choice.key]);
      set.has(value) ? set.delete(value) : set.add(value);
      state.values[choice.key] = choice.options.map(o => o.value).filter(v => set.has(v));
    } else state.values[choice.key] = value;
    rerender();
  });
  $("titles").addEventListener("input", event => { state.titles[event.target.dataset.titleLocale] = event.target.value; decision.refresh(); });
  $("title-format").addEventListener("click", event => {
    const button = event.target.closest("button[data-format]");
    if (button) { state.format = button.dataset.format; renderTitles(); decision.refresh(); }
  });
  for (const [id, key] of [["window-start", "start"], ["window-end", "end"]]) {
    $(id).disabled = gate.state !== "open";
    $(id).addEventListener("change", event => { state.window[key] = Number(event.target.value); renderWindow(); decision.refresh(); });
  }
  $("deliverables").addEventListener("click", event => {
    const button = event.target.closest("button[data-n]");
    if (!button) return;
    state.deliverables.find(d => String(d.n) === button.dataset.n).deliver = button.dataset.deliver === "1";
    renderDeliverables(); decision.refresh();
  });
  $("deliverables").addEventListener("input", event => {
    const n = event.target.dataset.reasonFor;
    if (n) { state.deliverables.find(d => String(d.n) === n).reason = event.target.value; decision.refresh(); }
  });
}

main().catch(showFatal);
