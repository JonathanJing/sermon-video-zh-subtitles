import { boundedTime, formatTime, cueIndex } from "/timing.mjs";
import { validateCatalog, chooseWeek, parseTimecode, downloadFilename, engagementWeek, weekOptionLabel, bilingualCueRows, isFormalPlayback } from "/catalog.mjs";
import { createFeedback } from "/feedback.mjs";
import { createUsage } from "/usage.mjs";
import { mountFingerprintUI, playAlignmentAudio } from "/fingerprint-ui.mjs";
import { PlaybackMemory } from "/playback-memory.mjs";

const $ = id => document.getElementById(id);
const audio = $("audio");
let catalog, week, track, fineOffset = 0, lastCue = -2, generation = 0;
let activeSource = null, pendingResume = null, positionTouched = false, undoPoint = null, scrubbing = false, lastSavedAt = 0;
let metadataReady = false, playPending = false, playFailed = false, resumeOnMetadata = false, playAttempt = 0, startupTimer = null;
let activeView = "tab-listen";
let alignmentPlayAttempt = 0;
let localPlaybackStorage; try { localPlaybackStorage = localStorage; } catch { localPlaybackStorage = null; }
const playbackMemory = new PlaybackMemory({ storage: localPlaybackStorage });
let feedback = { select() {}, count() {}, error() {}, statisticsEnabled: () => false };
let usage = { setEnabled() {}, record() {} };
const controls = [$("play"), $("back"), $("forward"), $("progress"), $("jump-time"), $("jump"), $("precision-open"), ...document.querySelectorAll("[data-nudge],[data-play-toggle]")];
const tabs = [...document.querySelectorAll('[role="tab"],[data-view]')];
const primaryTabs = tabs.filter(tab => tab.getAttribute("role") === "tab");
const fieldAlignment = mountFingerprintUI({
  context: () => ({ week, track, generation, ready: metadataReady && audioIsCurrent() }),
  pause: () => { stopStartup(); audio.pause(); document.querySelectorAll(".voice-card audio").forEach(sample => sample.pause()); update(); },
  position: () => audio.currentTime,
  seek: (time, { correction = false } = {}) => setPosition(time, { offset: 0, alignment: true, undo: !correction }),
  play: options => startAlignmentPlayback(options),
});
function status(text) { $("status").textContent = text; }
function ready(value) {
  metadataReady = value;
  controls.forEach(control => { control.disabled = !value; });
  // A user gesture may be required before WebViews fetch any audio metadata.
  [$("play"), ...document.querySelectorAll("[data-play-toggle]")].forEach(control => { control.disabled = !track; });
  document.querySelectorAll(".cue-button").forEach(control => { control.disabled = !value; });
  $("resume-position").disabled = !value;
  $("restart-position").disabled = !track || (!value && !pendingResume);
}
function showResume() {
  $("resume-card").hidden = !pendingResume || activeView === "tab-voices";
  $("restart-position").disabled = !track || (!metadataReady && !pendingResume);
  if (!pendingResume) return;
  $("resume-message").textContent = `上次听到 ${formatTime(pendingResume.positionSeconds)}，可恢复位置与微调。`;
  $("resume-position").textContent = `恢复到 ${formatTime(pendingResume.positionSeconds)}`;
}
function stopStartup() {
  clearTimeout(startupTimer); startupTimer = null;
  playPending = false; resumeOnMetadata = false; playAttempt += 1;
}
function audioIsCurrent() {
  return track && audio.readyState >= 1 && audio.currentSrc === new URL(track.audioUrl, location.href).href;
}
function failStartup(message) {
  stopStartup(); audio.pause(); playFailed = true;
  ready(audioIsCurrent() && Number.isFinite(audio.duration));
  status(message); update();
}
function currentDuration() { return Number.isFinite(audio.duration) ? audio.duration : track?.durationSeconds || 0; }
function sourceTime(relativeTime) {
  if (!Number.isFinite(week?.sourceStartSeconds) || week.sourceStartSeconds < 0) return null;
  const seconds = Math.max(0, Math.floor(relativeTime + week.sourceStartSeconds));
  if (seconds < 3600) return formatTime(seconds);
  return `${Math.floor(seconds / 3600)}:${formatTime(seconds % 3600)}`;
}
function downloadUrl(value, extension) {
  if (typeof value !== "string" || !value.trim()) return null;
  const relative = value.trim();
  if (/^(?:[a-z][a-z0-9+.-]*:|\/\/)/i.test(relative) || /[\\\u0000-\u001f\u007f]/.test(relative)) return null;
  try {
    const url = new URL(relative, location.href);
    return url.origin === location.origin && url.pathname.toLowerCase().endsWith(extension) ? relative : null;
  } catch { return null; }
}
function renderDownloads() {
  const list = $("week-download-links");
  list.replaceChildren();
  for (const [key, label, extension] of [
    ["readingPdf", "阅读版 PDF", ".pdf"],
    ["companionPdf", "同行版 PDF", ".pdf"],
    ["fullVideoMp3", "原视频时间轴 MP3", ".mp3"],
    ["fullVideoSrt", "原视频时间轴 SRT", ".srt"],
  ]) {
    const url = downloadUrl(week?.downloads?.[key], extension);
    if (!url) continue;
    const link = document.createElement("a");
    link.href = url; link.download = ""; link.textContent = label;
    list.append(link);
  }
  $("week-downloads").hidden = !list.children.length;
}
function update() {
  const duration = track ? currentDuration() : 0;
  const time = track ? audio.currentTime : 0;
  $("progress").max = duration || 1;
  if (!scrubbing) $("progress").value = time;
  if (!scrubbing) $("progress").setAttribute("aria-valuetext", `${formatTime(time)}，共 ${formatTime(duration)}`);
  $("elapsed").textContent = formatTime(time);
  $("duration").textContent = formatTime(duration);
  const sourceClock = track ? sourceTime(time) : null;
  $("source-clock").hidden = sourceClock === null;
  $("source-clock").textContent = sourceClock === null ? "" : `原视频 ${sourceClock}`;
  $("play-icon").textContent = audio.paused ? "▶" : "Ⅱ";
  const playLabel = !track ? "配音准备中" : playPending ? "取消加载" : playFailed ? "重试播放" : pendingResume ? "继续上次收听" : audio.ended ? "重新播放" : audio.paused ? "开始播放" : "暂停播放";
  $("play-label").textContent = playLabel;
  document.querySelectorAll("[data-play-label]").forEach(label => { label.textContent = playLabel; });
  document.querySelectorAll("[data-mini-time]").forEach(label => { label.textContent = `${formatTime(time)} / ${formatTime(duration)}`; });
  if (!track) return;
  const index = cueIndex(track.cues, time);
  const display = index < 0 ? Math.max(0, track.cues.findLastIndex(cue => cue.start <= time)) : index;
  if (display !== lastCue) {
    $("current-text").textContent = track.cues[display]?.text || "";
    const next = track.cues[display + 1]?.text;
    $("next-text").textContent = next ? `接下来 · ${next.slice(0, 42)}${next.length > 42 ? "…" : ""}` : "";
    $("cue-count").textContent = `${display + 1} / ${track.cues.length}`;
    document.querySelectorAll(".cue-button").forEach((b, i) => b.setAttribute("aria-current", String(i === display)));
    document.querySelectorAll(".cue-row").forEach((row, i) => row.setAttribute("aria-current", String(i === display)));
    lastCue = display;
  }
}
function selectTab(id, focus = false, scroll = false) {
  fieldAlignment.invalidate();
  activeView = id;
  const voices = id === "tab-voices";
  $("edition-label").textContent = !voices && isFormalPlayback(week) ? "正式播放版" : "试听版";
  document.querySelector(".sermon-banner").hidden = voices;
  document.querySelector(".content-layout").hidden = voices;
  $("source-link").hidden = voices;
  $("field-controls").hidden = voices;
  $("resume-card").hidden = voices || !pendingResume;
  if (voices) { stopStartup(); audio.pause(); update(); }
  else document.querySelectorAll(".voice-card audio").forEach(item => item.pause());
  const url = new URL(location.href);
  if (id === "tab-listen") url.searchParams.delete("tab");
  else url.searchParams.set("tab", id.replace("tab-", ""));
  history.replaceState(null, "", url);
  if (week) document.title = `${voices ? "讲员音色" : week.title} · 同行 · 证道中文听译`;
  for (const tab of tabs) {
    const selected = tab.id === id;
    if (tab.getAttribute("role") === "tab") {
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
    } else tab.setAttribute("aria-pressed", String(selected));
    $(tab.getAttribute("aria-controls")).hidden = !selected;
    if (selected && focus && tab.getAttribute("role") === "tab") tab.focus();
  }
  if (!primaryTabs.some(tab => tab.getAttribute("aria-selected") === "true")) primaryTabs[0].tabIndex = 0;
  setMore(false);
  const panel = $(id.replace("tab-", "panel-"));
  if (scroll && panel) { panel.scrollIntoView({ block: "start" }); panel.focus({ preventScroll: true }); }
  syncDockHeight();
  if (id === "tab-transcript" && track && !audio.paused && !audio.ended) {
    update();
    const row = document.querySelector('.cue-row[aria-current="true"]');
    if (row) row.scrollIntoView({ block: "center" });
  }
}
function setMore(open) {
  $("more-options").hidden = !open;
  $("more-toggle").setAttribute("aria-expanded", String(open));
}
function syncDockHeight() {
  document.documentElement.style.setProperty("--dock-height", `${$("field-controls").hidden ? 0 : $("field-controls").getBoundingClientRect().height}px`);
}
if (typeof ResizeObserver !== "undefined") new ResizeObserver(syncDockHeight).observe($("field-controls"));
window.addEventListener("resize", syncDockHeight);
function saveProgress(force = false) {
  if (!activeSource || !track || !positionTouched || pendingResume || !Number.isFinite(audio.duration)) return;
  if (!force && Date.now() - lastSavedAt < 4000) return;
  playbackMemory.save(activeSource, { positionSeconds: audio.currentTime, fineOffset, durationSeconds: audio.duration });
  lastSavedAt = Date.now();
}
function updateUndo() {
  $("undo-row").hidden = !undoPoint;
  $("undo-message").textContent = undoPoint ? `可返回 ${formatTime(undoPoint.time)}` : "";
  document.querySelectorAll("[data-seek-undo]").forEach(button => { button.hidden = !undoPoint; });
}
function setPosition(time, { fine = false, undo = true, offset, alignment = false } = {}) {
  if (!alignment) fieldAlignment.invalidate();
  if (!track || !metadataReady || !Number.isFinite(audio.duration)) return false;
  const next = boundedTime(time, audio.duration), previous = audio.currentTime;
  if (undo && (Math.abs(next - previous) > .01 || (offset !== undefined && offset !== fineOffset))) undoPoint = { time: previous, offset: fineOffset };
  if (fine) { fineOffset += next - previous; feedback.count("nudges"); }
  if (offset !== undefined) fineOffset = offset;
  audio.currentTime = next;
  positionTouched = true;
  pendingResume = null;
  resumeOnMetadata = false;
  $("resume-card").hidden = true;
  $("offset").textContent = `${fineOffset > 0 ? "+" : ""}${fineOffset.toFixed(2)} 秒`;
  $("jump-message").textContent = `已定位 ${formatTime(next)}`;
  $("seek-preview").textContent = "";
  scrubbing = false;
  updateUndo(); update(); saveProgress(true);
  return true;
}
function restorePosition() {
  if (!pendingResume) return false;
  const saved = pendingResume;
  if (!setPosition(saved.positionSeconds, { offset: saved.fineOffset })) return false;
  status("已恢复上次位置；如需对照原视频，请再手动对齐。");
  return true;
}
function restartPosition() {
  if (!track) return;
  if (metadataReady) {
    if (!setPosition(0, { offset: 0 })) return;
  } else {
    if (!pendingResume) return;
    // Discarding a bookmark needs no media seek or network response.
    stopStartup(); audio.pause();
    pendingResume = null; fineOffset = 0; positionTouched = true;
    showResume(); update();
  }
  playbackMemory.clear(activeSource);
  status("从头开始；如需对照原视频，请手动调整起点。");
}
function undoSeek() {
  if (!undoPoint) return;
  const point = undoPoint;
  if (setPosition(point.time, { offset: point.offset, undo: false })) {
    undoPoint = null; updateUndo(); status(`已返回 ${formatTime(point.time)}`);
  }
}
function renderTranscript() {
  $("transcript-list").replaceChildren();
  if (!track) {
    $("transcript-description").textContent = "本周配音尚未生成。可先打开证道大纲，阅读大纲与默想。";
    return;
  }
  const bilingual = bilingualCueRows(week, track);
  const guidance = ["点击时间定位；正文可直接阅读。"];
  if (bilingual.hasEnglish) guidance.push("中文优先阅读；点击段末的「英文对照」展开参考。");
  if (bilingual.missingEnglish) guidance.push(bilingual.hasEnglish ? "部分段落未提供可关联的英文原文，保留中文显示。" : "英文原文暂缺，保留中文显示。");
  $("transcript-description").textContent = guidance.join(" ");
  bilingual.rows.forEach(({ cue, english }) => {
    const row = document.createElement("article"); row.className = "cue-row"; row.tabIndex = -1;
    const button = document.createElement("button"); button.className = "cue-button"; button.disabled = true;
    button.setAttribute("aria-label", `跳至 ${formatTime(cue.start)}`);
    const time = document.createElement("time"); time.textContent = formatTime(cue.start);
    const text = document.createElement("span"); text.textContent = cue.text;
    button.append(time);
    const originalTime = Number.isFinite(week?.sourceStartSeconds) ? sourceTime(cue.start) : null;
    if (originalTime !== null) {
      const sourceLabel = document.createElement("small");
      sourceLabel.className = "cue-source-time";
      sourceLabel.textContent = `原视频 ${originalTime}`;
      button.append(sourceLabel);
      button.setAttribute("aria-label", `跳至音频 ${formatTime(cue.start)}，原视频 ${originalTime}`);
    }
    row.append(button, text);
    text.lang = "zh-Hans";
    if (english != null) {
      const details = document.createElement("details"); details.className = "english-reference";
      const summary = document.createElement("summary"); summary.textContent = "英文对照";
      const original = document.createElement("p"); original.lang = "en"; original.textContent = english;
      details.append(summary, original); row.append(details);
    }
    button.addEventListener("click", () => setPosition(cue.start));
    $("transcript-list").append(row);
  });
}
function selectTrack(id) {
  const nextTrack = week.tracks.find(t => t.id === id) || null;
  const nextSource = nextTrack ? { week: engagementWeek(week).id, trackId: nextTrack.id, audioSha256: nextTrack.sha256 } : null;
  if (activeSource && nextSource && JSON.stringify(activeSource) === JSON.stringify(nextSource)) return;
  saveProgress(true);
  generation += 1;
  stopStartup(); playFailed = false;
  audio.pause();
  track = nextTrack;
  fieldAlignment.refresh();
  ready(false);
  activeSource = nextSource; pendingResume = null; positionTouched = false; undoPoint = null; scrubbing = false;
  $("resume-card").hidden = true; updateUndo();
  feedback.select(engagementWeek(week), track);
  fineOffset = 0;
  lastCue = -2;
  $("offset").textContent = "0.00 秒";
  $("jump-time").value = "";
  $("jump-message").textContent = "";
  $("download").hidden = !track;
  $("feedback-quick").disabled = !track;
  $("audio-scope").textContent = isFormalPlayback(week) && track ? "正式播放版" : week.humanContentReview === "approved" && track ? "整篇中文" : track?.scope === "full_candidate" ? "整篇待审" : track?.scope === "full_reviewed" ? "整篇中文" : track ? "样片" : "待配音";
  $("voice").textContent = track?.voiceLabel || "本周中文语音尚未就绪";
  renderTranscript();
  for (const button of $("variants").children) button.setAttribute("aria-pressed", String(button.dataset.id === track?.id));
  if (track) {
    pendingResume = playbackMemory.read(activeSource, track.durationSeconds);
    showResume();
    status(pendingResume ? "点击继续收听，将恢复上次位置" : "点击播放开始收听");
    audio.src = track.audioUrl;
    audio.load();
    $("download").href = `${track.audioUrl}?download=1`;
    $("download").download = downloadFilename(week, track);
    $("download").title = $("download").download;
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
    $("download").removeAttribute("download");
    $("download").removeAttribute("title");
  }
  update();
}
function renderOutline() {
  $("outline-title").textContent = "证道大纲";
  $("outline-meta").textContent = `${week.title} · ${week.date.replaceAll("-", ".")} · ${week.speaker} · ${week.scripture}`;
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
  $("outline-review").textContent = `${week.contentReview}。${week.audioStatus?.startsWith("full_") ? "大纲与整篇中文配音对应同一篇证道。" : "大纲覆盖整篇证道，播放样片仅覆盖其中一小段。"}`;
}
function renderProduction() {
  const stages = week.productionStages || [
    { label: "周六阅读稿与证道大纲", status: "pass", detail: "本周大纲已就绪" },
    { label: "中文配音", status: week.tracks.length ? "review" : "pending", detail: week.tracks.length ? "当前提供片段试听" : "等待完整中文配音" },
    { label: "试听与视频同步审核", status: "pending", detail: "核对整篇中文、讲员音色与同一份视频的时间" },
    { label: "周日版本发布", status: "pending", detail: "审核通过后提供本周中文配音" },
  ];
  $("production-stages").replaceChildren();
  for (const original of stages) {
    let item = original;
    if (isFormalPlayback(week)) {
      if (original.label === "周日版本发布") item = { ...original, status: "pass", detail: "已按用户发布授权提供正式播放版。" };
      else if (/视频同步|人工试听/.test(original.label)) item = { ...original, detail: "已完成机器时间轴检查与同步装配；人工试听和现场同视频验收尚未记录。" };
      else if (original.label === "配音检查") item = { ...original, detail: `已完成机器配音检查；${original.detail}` };
      else if (original.label === "中文配音" && week.tracks.length) item = { ...original, detail: "整篇中文配音已生成。" };
    }
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
      sample.addEventListener("play", () => { fieldAlignment.invalidate(); document.querySelectorAll("audio").forEach(other => { if (other !== sample) other.pause(); }); });
      for (const event of ["play", "pause"]) sample.addEventListener(event, () => usage.record(`voice_${key}_${event}`, { speakerId: speaker.id, trackId: null, positionSeconds: null }));
      card.append(label, sample);
    }
    const note = document.createElement("p");
    note.className = "voice-card-note";
    note.textContent = speaker.humanListeningStatus === "accepted" ? "已获人工试听认可" : "等待试听确认音色与中文流畅度";
    card.append(note);
    $("voice-grid").append(card);
  }
}
function selectWeek(id) {
  fieldAlignment.invalidate();
  const nextWeek = chooseWeek(catalog, id);
  if (week?.id === nextWeek.id) return;
  week = nextWeek;
  $("week-select").value = week.id;
  $("title").textContent = week.title;
  $("series").textContent = [week.series, week.sourceLabel].filter(Boolean).join(" · ");
  $("speaker").textContent = week.speaker;
  $("scripture").textContent = week.scripture;
  $("cover-number").textContent = week.number;
  $("date").textContent = week.date.replaceAll("-", ".");
  $("edition-label").textContent = isFormalPlayback(week) ? "正式播放版" : "试听版";
  $("week-status").textContent = isFormalPlayback(week) ? "正式播放版 · 中文音频已就绪" : week.humanContentReview === "approved" ? "整篇中文已就绪" : week.audioStatus === "full_candidate" ? "整篇中文 · 待审核" : week.audioStatus === "full_reviewed" ? "整篇中文已就绪" : week.tracks.length ? "中文样片可试听" : "大纲已就绪 · 待配音";
  $("central-message").textContent = week.centralMessage;
  $("audio-notice").textContent = week.audioNotice;
  $("source-link").href = week.sourceUrl;
  $("source-link").textContent = week.sourceLabel ? `${week.sourceLabel} · 查看原视频 ↗` : "查看原证道视频 ↗";
  $("source-link").hidden = false;
  $("variants").replaceChildren();
  $("variants").hidden = !week.tracks.length;
  for (const item of week.tracks) {
    const button = document.createElement("button");
    button.textContent = isFormalPlayback(week) ? "正式播放版" : item.label;
    button.dataset.id = item.id;
    button.addEventListener("click", () => selectTrack(item.id));
    $("variants").append(button);
  }
  renderOutline();
  renderProduction();
  renderDownloads();
  $("outline-open").disabled = false;
  $("outline-secondary").disabled = false;
  selectTrack(week.tracks[0]?.id);
  if (activeView === "tab-voices") selectTab("tab-listen");
  const url = new URL(location.href);
  url.searchParams.set("week", week.id);
  history.replaceState(null, "", url);
  document.title = `${week.title} · 同行 · 证道中文听译`;
}
async function startAlignmentPlayback({ signal } = {}) {
  if (signal?.aborted) throw new DOMException("Alignment cancelled", "AbortError");
  stopStartup();
  const token = generation, attempt = ++alignmentPlayAttempt;
  playPending = true; playFailed = false; positionTouched = true;
  document.querySelectorAll(".voice-card audio").forEach(sample => sample.pause());
  status("已对齐，正在开始中文播放…"); update();
  try {
    // Explicit play, never a toggle; preserve the helper's failure for the controller.
    await playAlignmentAudio(audio, { signal });
    if (!signal?.aborted && token === generation && attempt === alignmentPlayAttempt) {
      stopStartup(); status("正在播放"); update();
    }
  } catch (error) {
    if (!signal?.aborted && token === generation && attempt === alignmentPlayAttempt) {
      stopStartup(); audio.pause(); playFailed = true;
      status("已定位，但播放未能开始。请手动播放，并微调跟上原声。"); update();
    }
    throw error;
  }
}
async function togglePlay(fromAlignment = false) {
  if (fromAlignment !== true) fieldAlignment.invalidate();
  if (!track || $("play").disabled) return;
  if (playPending) { stopStartup(); audio.pause(); status("已取消加载，可再次点击播放"); update(); return; }
  if (!audio.paused) { audio.pause(); return; }
  const retry = playFailed || Boolean(audio.error);
  if (retry) {
    saveProgress(true);
    pendingResume = playbackMemory.read(activeSource, currentDuration()) || pendingResume;
    ready(false); audio.load(); showResume();
  }
  if (pendingResume) {
    usage.record("position_restore");
    if (metadataReady) restorePosition();
    else resumeOnMetadata = true;
  }
  if (audio.ended) setPosition(0);
  positionTouched = true;
  document.querySelectorAll(".voice-card audio").forEach(sample => sample.pause());
  const token = generation, attempt = ++playAttempt;
  playPending = true; playFailed = false;
  status("正在连接音频… 可再次点击取消"); update();
  startupTimer = setTimeout(() => {
    if (token !== generation || attempt !== playAttempt) return;
    failStartup("音频连接较慢，请重试；仍无法播放时，可用浏览器打开或下载 MP3。");
    feedback.error("audio_play");
  }, 15000);
  // Keep play() inside the original click; never await metadata/network first.
  try {
    await audio.play();
    if (token === generation && attempt === playAttempt) { stopStartup(); update(); }
  } catch {
    if (token === generation && attempt === playAttempt) {
      failStartup("无法开始播放，请重试；也可用浏览器打开或下载 MP3。"); feedback.error("audio_play");
    }
  }
}
function seek(delta, fine = false) { setPosition(audio.currentTime + delta, { fine }); }
audio.addEventListener("play", () => fieldAlignment.playbackStarted());
$("week-select").addEventListener("change", event => selectWeek(event.target.value));
$("play").addEventListener("click", togglePlay);
document.querySelectorAll("[data-play-toggle]").forEach(button => button.addEventListener("click", togglePlay));
$("resume-position").addEventListener("click", restorePosition);
$("restart-position").addEventListener("click", restartPosition);
$("undo-seek").addEventListener("click", undoSeek);
document.querySelectorAll("[data-seek-undo]").forEach(button => button.addEventListener("click", undoSeek));
$("more-toggle").addEventListener("click", () => setMore($("more-options").hidden));
$("precision-open").addEventListener("click", () => { $("precision-dialog").showModal(); $("precision-dialog").scrollTop = 0; update(); });
$("precision-close").addEventListener("click", () => $("precision-dialog").close());
$("feedback-quick").addEventListener("click", () => $("feedback-point").click());
$("transcript-current").addEventListener("click", () => {
  if (activeView === "tab-transcript") {
    const row = document.querySelector('.cue-row[aria-current="true"]');
    if (row) { row.scrollIntoView({ block: "center" }); row.focus({ preventScroll: true }); }
  } else selectTab("tab-listen", false, true);
});
$("back").addEventListener("click", () => seek(-5));
$("forward").addEventListener("click", () => seek(5));
document.querySelectorAll("[data-nudge]").forEach(button => button.addEventListener("click", () => seek(Number(button.dataset.nudge), true)));
$("progress").addEventListener("input", event => {
  scrubbing = true;
  const preview = formatTime(Number(event.target.value));
  event.target.setAttribute("aria-valuetext", `${preview}，松开后跳转`);
  $("seek-preview").textContent = `准备跳至 ${preview}，松开后生效`;
});
$("progress").addEventListener("change", event => setPosition(Number(event.target.value)));
$("progress").addEventListener("pointercancel", () => { scrubbing = false; $("seek-preview").textContent = ""; update(); });
$("jump-form").addEventListener("submit", event => {
  event.preventDefault();
  const time = parseTimecode($("jump-time").value);
  if (time === null) { $("jump-message").textContent = "请输入 分:秒，例如 01:05，也支持 时:分:秒。"; return; }
  if (!track || !Number.isFinite(audio.duration)) return;
  if (time > audio.duration) { $("jump-message").textContent = `超出当前音频，请输入 00:00 至 ${formatTime(audio.duration)}。`; return; }
  setPosition(time);
});
tabs.forEach(tab => { tab.addEventListener("click", () => selectTab(tab.id, false, true)); });
primaryTabs.forEach((tab, i) => {
  tab.addEventListener("keydown", event => {
    const next = event.key === "ArrowRight" ? (i + 1) % primaryTabs.length : event.key === "ArrowLeft" ? (i + primaryTabs.length - 1) % primaryTabs.length : event.key === "Home" ? 0 : event.key === "End" ? primaryTabs.length - 1 : -1;
    if (next >= 0) { event.preventDefault(); selectTab(primaryTabs[next].id, true); usage.record(primaryTabs[next].id.replace('tab-', 'tab_')); }
  });
});
$("show-transcript").addEventListener("click", () => selectTab("tab-transcript", false, true));
for (const id of ["outline-open", "outline-secondary"]) $(id).addEventListener("click", () => { $("outline-dialog").showModal(); $("outline-dialog").scrollTop = 0; feedback.count("outlineViews"); });
$("download").addEventListener("click", () => feedback.count("downloadClicks"));
$("outline-close").addEventListener("click", () => $("outline-dialog").close());
$("outline-dialog").addEventListener("click", event => {
  const rect = $("outline-dialog").getBoundingClientRect();
  if (event.target === $("outline-dialog") && (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom)) $("outline-dialog").close();
});
audio.addEventListener("loadedmetadata", () => {
  if (!audioIsCurrent() || !Number.isFinite(audio.duration)) return;
  ready(true);
  if (pendingResume || !positionTouched) pendingResume = playbackMemory.read(activeSource, audio.duration);
  if (resumeOnMetadata && pendingResume) restorePosition();
  resumeOnMetadata = false;
  showResume();
  if (!playFailed) status(playPending ? "正在连接音频… 可再次点击取消" : pendingResume ? "已找到上次位置" : "音频就绪 · 可开始收听");
  update();
});
for (const event of ["timeupdate", "durationchange", "seeked"]) audio.addEventListener(event, update);
audio.addEventListener("timeupdate", () => saveProgress());
audio.addEventListener("pause", () => saveProgress(true));
window.addEventListener("pagehide", () => saveProgress(true));
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "hidden") saveProgress(true); });
audio.addEventListener("play", () => { if (!playPending) status("正在播放"); update(); });
audio.addEventListener("pause", () => {
  // A queued pause from a cancelled attempt can arrive after play() restarts.
  if (!audio.paused) return;
  if (playPending) stopStartup();
  if (track && !playFailed) status(audio.ended ? "播放完毕" : "已暂停");
  update();
});
audio.addEventListener("ended", () => { status("播放完毕"); update(); });
audio.addEventListener("waiting", () => { if (track) status("正在缓冲…"); });
audio.addEventListener("playing", () => { if (!audioIsCurrent()) return; stopStartup(); playFailed = false; status("正在播放"); update(); });
audio.addEventListener("error", () => { if (track && audio.error) { failStartup("音频读取失败，请点击重试；也可用浏览器打开或下载 MP3。"); ready(false); feedback.error("audio_load"); } });
document.addEventListener("keydown", event => {
  if (activeView === "tab-voices" || event.target.closest("audio") || $("outline-dialog").open || $("feedback-dialog").open || $("precision-dialog").open || $("fingerprint-dialog").open || event.target.matches("input,button,a,select,textarea") || !track || $("play").disabled) return;
  if (event.code === "Space") { event.preventDefault(); usage.record(audio.paused ? 'play_click' : 'pause_click'); togglePlay(); }
  if (event.code === "ArrowLeft" || event.code === "ArrowRight") {
    event.preventDefault();
    usage.record(event.shiftKey ? (event.code === 'ArrowRight' ? 'nudge_forward_quarter_click' : 'nudge_back_quarter_click') : (event.code === 'ArrowRight' ? 'forward_5_click' : 'back_5_click'));
    seek((event.code === "ArrowRight" ? 1 : -1) * (event.shiftKey ? .25 : 5), event.shiftKey);
  }
});
async function initializeEngagement() {
  try {
    const engagement = await fetch("/engagement.json");
    if (engagement.ok) {
      const config = await engagement.json();
      usage = createUsage({ catalog: { ...catalog, weeks: catalog.weeks.map(engagementWeek) }, config, audio,
        context: () => ({ week: engagementWeek(week), track, panel: activeView.replace('tab-', '') }),
        onError: () => { if ($('statistics-opt-in').checked) $('statistics-status').textContent = '部分匿名使用记录暂未送达，稍后会重试；播放不受影响。'; },
      });
      feedback = createFeedback(audio, config, { usage });
      // The listener may have switched sources while the optional request ran.
      feedback.select(engagementWeek(week), track);
      $("feedback-quick").hidden = !config.enabled;
      usage.setEnabled(feedback.statisticsEnabled());
    }
  } catch { /* Optional feedback must never prevent playback. */ }
}
try {
  const response = await fetch("/weekly.json");
  if (!response.ok) throw new Error("Catalog unavailable");
  catalog = validateCatalog(await response.json());
  $("week-select").replaceChildren();
  for (const item of catalog.weeks) {
    const option = document.createElement("option");
    option.value = item.id;
    option.textContent = weekOptionLabel(item);
    $("week-select").append(option);
  }
  $("week-select").disabled = false;
  renderVoiceBank();
  selectWeek(new URLSearchParams(location.search).get("week"));
  const initialTab = new URLSearchParams(location.search).get("tab");
  if (["voices", "production", "transcript"].includes(initialTab)) selectTab(`tab-${initialTab}`);
  syncDockHeight();
  void initializeEngagement();
} catch {
  ready(false);
  $("title").textContent = "暂时无法读取本周信息";
  status("加载失败，请检查网络后刷新。");
  $("current-text").textContent = "内容加载失败，请刷新后再试。";
}
