import { boundedTime, nudge, formatTime, cueIndex } from "/timing.mjs";
import { validateCatalog, chooseWeek, parseTimecode } from "/catalog.mjs";

const $ = id => document.getElementById(id);
const audio = $("audio");
let catalog, week, track, fineOffset = 0, lastCue = -2, generation = 0;
const controls = [$("play"), $("back"), $("forward"), $("progress"), $("jump-time"), $("jump"), ...document.querySelectorAll("[data-nudge]")];
const tabs = [...document.querySelectorAll('[role="tab"]')];
function status(text) { $("status").textContent = text; }
function ready(value) {
  controls.forEach(control => { control.disabled = !value; });
  document.querySelectorAll(".cue-button").forEach(control => { control.disabled = !value; });
}
function currentDuration() { return Number.isFinite(audio.duration) ? audio.duration : track?.durationSeconds || 0; }
function update() {
  const duration = track ? currentDuration() : 0;
  const time = track ? audio.currentTime : 0;
  $("progress").max = duration || 1;
  $("progress").value = time;
  $("progress").setAttribute("aria-valuetext", `${formatTime(time)}，共 ${formatTime(duration)}`);
  $("elapsed").textContent = formatTime(time);
  $("duration").textContent = formatTime(duration);
  $("play-icon").textContent = audio.paused ? "▶" : "Ⅱ";
  $("play-label").textContent = !track ? "配音准备中" : audio.ended ? "重新播放" : audio.paused ? "开始播放" : "暂停播放";
  if (!track) return;
  const index = cueIndex(track.cues, time);
  const display = index < 0 ? Math.max(0, track.cues.findLastIndex(cue => cue.start <= time)) : index;
  if (display !== lastCue) {
    $("current-text").textContent = track.cues[display]?.text || "";
    const next = track.cues[display + 1]?.text;
    $("next-text").textContent = next ? `接下来 · ${next.slice(0, 42)}${next.length > 42 ? "…" : ""}` : "";
    $("cue-count").textContent = `${display + 1} / ${track.cues.length}`;
    document.querySelectorAll(".cue-button").forEach((b, i) => b.setAttribute("aria-current", String(i === display)));
    lastCue = display;
  }
}
function selectTab(id, focus = false) {
  const voices = id === "tab-voices";
  document.querySelector(".sermon-banner").hidden = voices;
  document.querySelector(".content-layout").hidden = voices;
  $("source-link").hidden = voices;
  if (voices) audio.pause();
  else document.querySelectorAll(".voice-card audio").forEach(item => item.pause());
  const url = new URL(location.href);
  if (id === "tab-listen") url.searchParams.delete("tab");
  else url.searchParams.set("tab", id.replace("tab-", ""));
  history.replaceState(null, "", url);
  if (week) document.title = `${voices ? "讲员音色" : week.title} · 同行中文听译`;
  for (const tab of tabs) {
    const selected = tab.id === id;
    tab.setAttribute("aria-selected", String(selected));
    tab.tabIndex = selected ? 0 : -1;
    $(tab.getAttribute("aria-controls")).hidden = !selected;
    if (selected && focus) tab.focus();
  }
}
function renderTranscript() {
  $("transcript-list").replaceChildren();
  if (!track) {
    $("transcript-description").textContent = "本周配音尚未生成。可先打开证道同行，阅读大纲与默想。";
    return;
  }
  $("transcript-description").textContent = "以下为当前音频的完整字幕。点击时间或段落可定位中文音频。";
  track.cues.forEach(cue => {
    const button = document.createElement("button");
    button.className = "cue-button";
    button.disabled = true;
    const time = document.createElement("time");
    time.textContent = formatTime(cue.start);
    const text = document.createElement("span");
    text.textContent = cue.text;
    button.append(time, text);
    button.addEventListener("click", () => { audio.currentTime = boundedTime(cue.start, audio.duration); update(); });
    $("transcript-list").append(button);
  });
}
function selectTrack(id) {
  generation += 1;
  audio.pause();
  ready(false);
  track = week.tracks.find(t => t.id === id) || null;
  fineOffset = 0;
  lastCue = -2;
  $("offset").textContent = "0.00 秒";
  $("jump-time").value = "";
  $("jump-message").textContent = "";
  $("download").hidden = !track;
  $("audio-scope").textContent = track?.scope === "full_candidate" ? "整篇待审" : track?.scope === "full_reviewed" ? "整篇中文" : track ? "样片" : "待配音";
  $("voice").textContent = track?.voiceLabel || "本周中文语音尚未就绪";
  renderTranscript();
  for (const button of $("variants").children) button.setAttribute("aria-pressed", String(button.dataset.id === track?.id));
  if (track) {
    status("正在加载音频…");
    audio.src = track.audioUrl;
    audio.load();
    $("download").href = `${track.audioUrl}?download=1`;
    $("download").download = track.file;
    $("subtitle-note").textContent = "字幕随中文音频更新";
  } else {
    audio.removeAttribute("src");
    audio.load();
    status("本周配音准备中");
    $("current-text").textContent = "本周大纲已经就绪。中文配音完成后，就能在这里一同聆听。";
    $("next-text").textContent = "可切换至其他周次收听，或打开讲员音色试听。";
    $("cue-count").textContent = "";
    $("subtitle-note").textContent = "本周字幕待配音后同步";
    $("download").removeAttribute("href");
  }
  update();
}
function renderOutline() {
  $("outline-title").textContent = week.title;
  $("outline-meta").textContent = `${week.date.replaceAll("-", ".")} · ${week.speaker} · ${week.scripture}`;
  $("outline-summary").textContent = week.summary;
  $("outline-content").replaceChildren();
  for (const item of week.outline) {
    const section = document.createElement("section");
    section.className = "outline-section";
    const h3 = document.createElement("h3");
    h3.textContent = item.title;
    const list = document.createElement("ul");
    for (const point of item.points) { const li = document.createElement("li"); li.textContent = point; list.append(li); }
    section.append(h3, list);
    $("outline-content").append(section);
  }
  $("reflection-questions").replaceChildren();
  for (const question of week.questions) { const li = document.createElement("li"); li.textContent = question; $("reflection-questions").append(li); }
  document.querySelector(".reflection").hidden = !week.questions.length;
  $("outline-review").textContent = `${week.contentReview}。${week.audioStatus?.startsWith("full_") ? "大纲与整篇中文配音对应同一周证道。" : "大纲覆盖整篇证道，播放样片仅覆盖其中一小段。"}`;
}
function renderProduction() {
  const stages = week.productionStages || [
    { label: "周六阅读稿与证道同行", status: "pass", detail: "本周大纲已就绪" },
    { label: "中文配音", status: week.tracks.length ? "review" : "pending", detail: week.tracks.length ? "当前提供片段试听" : "等待完整中文配音" },
    { label: "试听与视频同步审核", status: "pending", detail: "核对整篇中文、讲员音色与同一份视频的时间" },
    { label: "周日版本发布", status: "pending", detail: "审核通过后提供本周中文配音" },
  ];
  $("production-stages").replaceChildren();
  for (const item of stages) {
    const li = document.createElement("li");
    li.dataset.status = item.status;
    const mark = document.createElement("span");
    mark.className = "stage-mark";
    mark.textContent = item.status === "pass" ? "✓" : item.status === "review" ? "◐" : "○";
    const body = document.createElement("div"), heading = document.createElement("h3"), detail = document.createElement("p"), state = document.createElement("small");
    heading.textContent = item.label;
    detail.textContent = item.detail;
    state.textContent = item.status === "pass" ? "已完成" : item.status === "review" ? "待审核" : "待完成";
    body.append(heading, detail);
    li.append(mark, body, state);
    $("production-stages").append(li);
  }
}
function renderVoiceBank() {
  const bank = catalog.voiceBank;
  $("voice-bank-notice").textContent = bank?.notice || "其他讲员的音色试听正在准备。";
  $("probe-text").textContent = bank?.probeText?.join("\n\n") || "";
  $("voice-grid").replaceChildren();
  for (const speaker of bank?.speakers || []) {
    const card = document.createElement("article");
    card.className = "voice-card";
    const heading = document.createElement("h3"), meta = document.createElement("p");
    heading.textContent = speaker.name;
    meta.className = "voice-card-meta";
    meta.textContent = `${speaker.sourceCount} 篇证道 · ${(speaker.trainingSeconds / 60).toFixed(1)} 分钟训练候选片段`;
    card.append(heading, meta);
    for (const key of ["reference", "chinese"]) {
      const label = document.createElement("p"), sample = document.createElement("audio");
      label.className = "sample-label";
      label.textContent = key === "reference" ? "01  英文原声" : "02  中文训练音色";
      sample.controls = true;
      sample.preload = "metadata";
      sample.src = speaker[key].audioUrl;
      sample.setAttribute("aria-label", `${speaker.name} ${label.textContent.slice(4)}`);
      sample.addEventListener("play", () => { document.querySelectorAll("audio").forEach(other => { if (other !== sample) other.pause(); }); });
      card.append(label, sample);
    }
    const note = document.createElement("p");
    note.className = "voice-card-note";
    note.textContent = speaker.humanListeningStatus === "accepted" ? "试听音色已认可" : "等待试听确认音色与中文流畅度";
    card.append(note);
    $("voice-grid").append(card);
  }
}
function selectWeek(id) {
  week = chooseWeek(catalog, id);
  $("week-select").value = week.id;
  $("title").textContent = week.title;
  $("series").textContent = week.series;
  $("speaker").textContent = week.speaker;
  $("scripture").textContent = week.scripture;
  $("cover-number").textContent = week.number;
  $("date").textContent = week.date.replaceAll("-", ".");
  $("week-status").textContent = week.audioStatus === "full_candidate" ? "整篇中文 · 待审核" : week.audioStatus === "full_reviewed" ? "整篇中文已就绪" : week.tracks.length ? "中文样片可试听" : "大纲已就绪 · 待配音";
  $("central-message").textContent = week.centralMessage;
  $("audio-notice").textContent = week.audioNotice;
  $("source-link").href = week.sourceUrl;
  $("source-link").hidden = false;
  $("variants").replaceChildren();
  $("variants").hidden = !week.tracks.length;
  for (const item of week.tracks) {
    const button = document.createElement("button");
    button.textContent = item.label;
    button.dataset.id = item.id;
    button.addEventListener("click", () => selectTrack(item.id));
    $("variants").append(button);
  }
  renderOutline();
  renderProduction();
  $("outline-open").disabled = false;
  $("outline-secondary").disabled = false;
  selectTrack(week.tracks[0]?.id);
  if ($("tab-voices").getAttribute("aria-selected") === "true") selectTab("tab-listen");
  const url = new URL(location.href);
  url.searchParams.set("week", week.id);
  history.replaceState(null, "", url);
  document.title = `${week.title} · 同行中文听译`;
}
async function togglePlay() {
  if (!track || $("play").disabled) return;
  if (!audio.paused) { audio.pause(); return; }
  if (audio.ended) audio.currentTime = 0;
  const token = generation;
  try { await audio.play(); } catch { if (token === generation) status("无法开始播放，请再次点击或下载 MP3。"); }
}
function seek(delta, fine = false) {
  if (!track || !Number.isFinite(audio.duration)) return;
  const result = nudge(audio.currentTime, delta, audio.duration);
  audio.currentTime = result.time;
  if (fine) {
    fineOffset += result.applied;
    $("offset").textContent = `${fineOffset > 0 ? "+" : ""}${fineOffset.toFixed(2)} 秒`;
  }
  update();
}
$("week-select").addEventListener("change", event => selectWeek(event.target.value));
$("play").addEventListener("click", togglePlay);
$("back").addEventListener("click", () => seek(-5));
$("forward").addEventListener("click", () => seek(5));
document.querySelectorAll("[data-nudge]").forEach(button => button.addEventListener("click", () => seek(Number(button.dataset.nudge), true)));
$("progress").addEventListener("input", event => { if (track) audio.currentTime = boundedTime(Number(event.target.value), audio.duration); update(); });
$("jump-form").addEventListener("submit", event => {
  event.preventDefault();
  const time = parseTimecode($("jump-time").value);
  if (time === null) { $("jump-message").textContent = "请输入 分:秒，例如 01:05，也支持 时:分:秒。"; return; }
  if (!track || !Number.isFinite(audio.duration)) return;
  if (time > audio.duration) { $("jump-message").textContent = `超出当前音频，请输入 00:00 至 ${formatTime(audio.duration)}。`; return; }
  audio.currentTime = time;
  $("jump-message").textContent = `已跳至 ${formatTime(time)}`;
  update();
});
tabs.forEach((tab, i) => {
  tab.addEventListener("click", () => selectTab(tab.id));
  tab.addEventListener("keydown", event => {
    const next = event.key === "ArrowRight" ? (i + 1) % tabs.length : event.key === "ArrowLeft" ? (i + tabs.length - 1) % tabs.length : event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : -1;
    if (next >= 0) { event.preventDefault(); selectTab(tabs[next].id, true); }
  });
});
$("show-transcript").addEventListener("click", () => selectTab("tab-transcript", true));
for (const id of ["outline-open", "outline-secondary"]) $(id).addEventListener("click", () => { $("outline-dialog").showModal(); $("outline-dialog").scrollTop = 0; });
$("outline-close").addEventListener("click", () => $("outline-dialog").close());
$("outline-dialog").addEventListener("click", event => {
  const rect = $("outline-dialog").getBoundingClientRect();
  if (event.target === $("outline-dialog") && (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom)) $("outline-dialog").close();
});
audio.addEventListener("loadedmetadata", () => { if (!track) return; ready(true); status("音频就绪"); update(); });
for (const event of ["timeupdate", "durationchange", "seeked"]) audio.addEventListener(event, update);
audio.addEventListener("play", () => { status("正在播放"); update(); });
audio.addEventListener("pause", () => { if (track) status(audio.ended ? "播放完毕" : "已暂停"); update(); });
audio.addEventListener("ended", () => { status("播放完毕"); update(); });
audio.addEventListener("waiting", () => { if (track) status("正在缓冲…"); });
audio.addEventListener("playing", () => { status("正在播放"); update(); });
audio.addEventListener("error", () => { if (track) { ready(false); status("音频读取失败，请刷新页面或下载 MP3。"); } });
document.addEventListener("keydown", event => {
  if ($("outline-dialog").open || event.target.matches("input,button,a,select,textarea") || !track || $("play").disabled) return;
  if (event.code === "Space") { event.preventDefault(); togglePlay(); }
  if (event.code === "ArrowLeft" || event.code === "ArrowRight") { event.preventDefault(); seek((event.code === "ArrowRight" ? 1 : -1) * (event.shiftKey ? .25 : 5), event.shiftKey); }
});
try {
  const response = await fetch("/weekly.json");
  if (!response.ok) throw new Error("Catalog unavailable");
  catalog = validateCatalog(await response.json());
  $("week-select").replaceChildren();
  for (const item of catalog.weeks) {
    const option = document.createElement("option");
    option.value = item.id;
    option.textContent = `${item.date.replaceAll("-", ".")} · ${item.audioStatus === "full_candidate" ? "整篇待审" : item.tracks.length ? "可试听" : "待配音"}`;
    $("week-select").append(option);
  }
  $("week-select").disabled = false;
  renderVoiceBank();
  selectWeek(new URLSearchParams(location.search).get("week"));
  const initialTab = new URLSearchParams(location.search).get("tab");
  if (["voices", "production", "transcript"].includes(initialTab)) selectTab(`tab-${initialTab}`);
} catch {
  ready(false);
  $("title").textContent = "暂时无法读取本周信息";
  status("加载失败，请检查网络后刷新。");
  $("current-text").textContent = "内容加载失败，请刷新后再试。";
}
