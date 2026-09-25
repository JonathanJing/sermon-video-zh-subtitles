import { t, getLocale, setLocale, onLocaleChange, localizeDOM } from "/i18n.mjs";
import { localizeWeek } from "/content-locales.mjs";
import { messages as appMessages } from "/locales-app.mjs";
import { boundedTime, formatTime, cueIndex } from "/timing.mjs";
import { validateCatalog, chooseWeek, parseTimecode, downloadFilename, engagementWeek, weekOptionLabel, bilingualCueRows, isFormalPlayback } from "/catalog.mjs";
import { createFeedback } from "/feedback.mjs";
import { createUsage } from "/usage.mjs";
import { mountFingerprintUI, playAlignmentAudio } from "/fingerprint-ui.mjs";
import { PlaybackMemory } from "/playback-memory.mjs";
import { createMediaSession } from "/media-session.mjs";

const $ = id => document.getElementById(id);
for (const id of ["week-select", "series", "title", "speaker", "scripture", "central-message", "current-text", "transcript-list", "outline-meta", "outline-summary", "outline-content", "reflection-questions"]) {
  $(id).lang = "zh-Hans";
}
const audio = $("audio");
let catalog, week, track, fineOffset = 0, lastCue = -2, generation = 0;
let activeSource = null, pendingResume = null, positionTouched = false, undoPoint = null, scrubbing = false, lastSavedAt = 0;
let metadataReady = false, playPending = false, playFailed = false, resumeOnMetadata = false, playAttempt = 0, startupTimer = null;
let activeView = "tab-listen";
let alignmentPlayAttempt = 0;
let localPlaybackStorage; try { localPlaybackStorage = localStorage; } catch { localPlaybackStorage = null; }
const playbackMemory = new PlaybackMemory({ storage: localPlaybackStorage });
let bilingualDisplay = false, englishByCue = [], englishDetails = [], transcriptRows = [], voiceLabels = [];
let lastStatus = null;
try { bilingualDisplay = localPlaybackStorage?.getItem("sermon-audio-subtitles") === "bilingual"; } catch { /* Default to Chinese. */ }
function updateLanguageControl() {
  $("subtitle-label").textContent = bilingualDisplay ? t("app.subtitle.bilingual") : t("app.subtitle.chinese");
  $("subtitle-toggle").setAttribute("aria-pressed", String(bilingualDisplay));
  $("subtitle-toggle").setAttribute("aria-label", t(bilingualDisplay ? "app.subtitle.hide" : "app.subtitle.show"));
  $("subtitle-toggle").title = t(bilingualDisplay ? "app.subtitle.hideTitle" : "app.subtitle.showTitle");
}
function updateCurrentEnglish(index) {
  const english = englishByCue[index];
  $("current-english").hidden = !bilingualDisplay || !track;
  $("current-english-label").textContent = t("app.transcript.englishReference");
  $("current-english-text").textContent = english || t("app.subtitle.missing");
  $("current-english-text").lang = english ? "en" : "zh-Hans";
}
updateLanguageControl();
$("subtitle-toggle").addEventListener("click", () => {
  bilingualDisplay = !bilingualDisplay;
  try { localPlaybackStorage?.setItem("sermon-audio-subtitles", bilingualDisplay ? "bilingual" : "chinese"); } catch { /* The current page still switches. */ }
  updateLanguageControl();
  englishDetails.forEach(details => { details.open = bilingualDisplay; });
  updateCurrentEnglish(lastCue);
});
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
const mediaSession = createMediaSession({
  audio,
  getSelection: () => activeView !== "tab-voices" && week && track ? { week, track } : null,
  play: () => { if (audio.paused && !playPending) void togglePlay(); },
  pause: () => { if (!audio.paused) audio.pause(); },
  seek: time => setPosition(time),
});
function status(key, params) {
  lastStatus = [key, params];
  $("status").textContent = key.startsWith("app.") ? t(key, params) : appText(key);
}
function appText(value) {
  for (const [key, source] of Object.entries(appMessages.zh)) {
    if (value === source || value === appMessages.en[key]) return t(key);
  }
  return value;
}
// These nine legacy weeks have only approved Chinese content and audio.
function displayWeek() { return localizeWeek(week, "zh"); }
function renderWeekOptions() {
  $("week-select").replaceChildren();
  for (const original of catalog.weeks) {
    const option = document.createElement("option");
    option.value = original.id;
    option.textContent = weekOptionLabel(original);
    $("week-select").append(option);
  }
  if (week) $("week-select").value = week.id;
}
function renderWeekLabels() {
  if (!week) return;
  const view = displayWeek();
  $("title").textContent = view.title;
  $("series").textContent = [view.series, view.sourceLabel].filter(Boolean).join(" · ");
  $("speaker").textContent = view.speaker; $("scripture").textContent = view.scripture;
  $("central-message").textContent = view.centralMessage;
  $("audio-notice").textContent = view.audioNotice;
  $("review").textContent = t("app.content.disclosure");
  $("edition-label").textContent = activeView === "tab-voices" ? t("app.release.preview") : isFormalPlayback(week) ? t("app.release.formal") : t("app.release.preview");
  $("week-status").textContent = isFormalPlayback(week) ? t("app.week.published") : week.humanContentReview === "approved" || week.audioStatus === "full_reviewed" ? t("app.week.ready") : week.audioStatus === "full_candidate" ? t("app.week.review") : week.tracks.length ? t("app.week.sample") : t("app.week.outline");
  $("audio-scope").textContent = isFormalPlayback(week) && track ? t("app.release.formal") : week.humanContentReview === "approved" && track ? t("app.release.full") : track?.scope === "full_candidate" ? t("app.release.review") : track?.scope === "full_reviewed" ? t("app.release.full") : track ? t("app.release.sample") : t("app.release.pending");
  $("voice").textContent = track ? t("app.voice.active", { speaker: week.speaker }) : t("app.voice.pending");
  $("source-link").textContent = view.sourceLabel ? t("app.source.link", { label: view.sourceLabel }) : t("app.source.open");
  for (const button of $("variants").children) button.textContent = isFormalPlayback(week) ? t("app.release.formal") : getLocale() !== "zh" ? t("app.voice.active", { speaker: week.speaker }) : week.tracks.find(item => item.id === button.dataset.id)?.label || "";
  $("subtitle-note").textContent = t("app.subtitle.follow");
  document.title = `${activeView === "tab-voices" ? t("app.voices.title") : view.title} · ${t("app.brand")}`;
}

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
  $("resume-message").textContent = t("app.resume.message", { time: formatTime(pendingResume.positionSeconds) });
  $("resume-position").textContent = t("app.resume.button", { time: formatTime(pendingResume.positionSeconds) });
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
    ["readingPdf", t("app.download.reading"), ".pdf"],
    ["companionPdf", t("app.download.companion"), ".pdf"],
    ["fullVideoMp3", t("app.download.mp3"), ".mp3"],
    ["fullVideoSrt", t("app.download.srt"), ".srt"],
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
  if (!scrubbing) $("progress").setAttribute("aria-valuetext", t("app.progress", { time: formatTime(time), duration: formatTime(duration) }));
  $("elapsed").textContent = formatTime(time);
  $("duration").textContent = formatTime(duration);
  const sourceClock = track ? sourceTime(time) : null;
  $("source-clock").hidden = sourceClock === null;
  $("source-clock").textContent = sourceClock === null ? "" : t("app.source.clock", { time: sourceClock });
  $("play-icon").textContent = audio.paused ? "▶" : "Ⅱ";
  const playLabel = !track ? t("app.audio.preparing") : playPending ? t("app.audio.cancel") : playFailed ? t("app.audio.retry") : pendingResume ? t("app.audio.continue") : audio.ended ? t("app.audio.replay") : audio.paused ? t("app.audio.play") : t("app.audio.pause");
  $("play-label").textContent = playLabel;
  document.querySelectorAll("[data-play-label]").forEach(label => { label.textContent = playLabel; });
  document.querySelectorAll("[data-mini-time]").forEach(label => { label.textContent = `${formatTime(time)} / ${formatTime(duration)}`; });
  mediaSession.update();
  if (!track) return;
  const index = cueIndex(track.cues, time);
  const display = index < 0 ? Math.max(0, track.cues.findLastIndex(cue => cue.start <= time)) : index;
  if (display !== lastCue) {
    $("current-text").textContent = track.cues[display]?.text || "";
    $("current-text").lang = "zh-Hans";
    const next = track.cues[display + 1]?.text;
    $("next-text").textContent = next ? t("app.next", { text: next.slice(0, 42) + (next.length > 42 ? "…" : "") }) : "";
    $("cue-count").textContent = `${display + 1} / ${track.cues.length}`;
    transcriptRows.forEach(({ row, button, start, end }) => {
      const active = start <= display && display <= end;
      row.setAttribute("aria-current", String(active)); button.setAttribute("aria-current", String(active));
    });
    updateCurrentEnglish(display);
    lastCue = display;
  }
}
function selectTab(id, focus = false, scroll = false) {
  fieldAlignment.invalidate();
  activeView = id;
  const voices = id === "tab-voices";
  $("edition-label").textContent = !voices && isFormalPlayback(week) ? t("app.release.formal") : t("app.release.preview");
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
  if (week) document.title = `${voices ? t("app.voices.title") : displayWeek().title} · ${t("app.brand")}`;
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
  $("undo-message").textContent = undoPoint ? t("app.undo", { time: formatTime(undoPoint.time) }) : "";
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
  $("offset").textContent = t("app.offset", { value: `${fineOffset > 0 ? "+" : ""}${fineOffset.toFixed(2)}` });
  $("jump-message").textContent = t("app.seek.position", { time: formatTime(next) });
  $("seek-preview").textContent = "";
  scrubbing = false;
  updateUndo(); update(); saveProgress(true);
  return true;
}
function restorePosition() {
  if (!pendingResume) return false;
  const saved = pendingResume;
  if (!setPosition(saved.positionSeconds, { offset: saved.fineOffset })) return false;
  status("app.resume.restored");
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
  status("app.resume.restart");
}
function undoSeek() {
  if (!undoPoint) return;
  const point = undoPoint;
  if (setPosition(point.time, { offset: point.offset, undo: false })) {
    undoPoint = null; updateUndo(); status("app.seek.returned", { time: formatTime(point.time) });
  }
}
function renderTranscript() {
  $("transcript-list").replaceChildren();
  englishByCue = []; englishDetails = []; transcriptRows = [];
  updateCurrentEnglish(-1);
  if (!track) {
    $("transcript-description").textContent = t("app.transcript.pending");
    return;
  }
  const bilingual = bilingualCueRows(week, track);
  // Reuse the validated block association, never infer English from cue timing.
  const originals = new Map(bilingual.rows.filter(row => row.english != null).map(row => [String(row.cue.blockId), row.english]));
  englishByCue = track.cues.map(cue => cue.blockId == null ? null : originals.get(String(cue.blockId)) || null);
  const guidance = [t("app.transcript.guide")];
  if (bilingual.hasEnglish) guidance.push(t("app.transcript.displayGuide"));
  if (bilingual.missingEnglish) guidance.push(bilingual.hasEnglish ? t("app.transcript.partial") : t("app.transcript.missing"));
  $("transcript-description").textContent = guidance.join(" ");
  bilingual.rows.forEach(({ cue, english, index }) => {
    const end = index;
    const row = document.createElement("article"); row.className = "cue-row"; row.tabIndex = -1;
    const button = document.createElement("button"); button.className = "cue-button"; button.disabled = true;
    button.setAttribute("aria-label", t("app.seek.to", { time: formatTime(cue.start) }));
    const time = document.createElement("time"); time.textContent = formatTime(cue.start);
    const text = document.createElement("span"); text.textContent = cue.text;
    button.append(time);
    const originalTime = Number.isFinite(week?.sourceStartSeconds) ? sourceTime(cue.start) : null;
    if (originalTime !== null) {
      const sourceLabel = document.createElement("small");
      sourceLabel.className = "cue-source-time";
      sourceLabel.textContent = t("app.source.clock", { time: originalTime });
      button.append(sourceLabel);
      button.setAttribute("aria-label", t("app.seek.source", { time: formatTime(cue.start), source: originalTime }));
    }
    row.append(button, text);
    text.lang = "zh-Hans";
    if (english != null) {
      const details = document.createElement("details"); details.className = "english-reference";
      const summary = document.createElement("summary"); summary.textContent = t("app.transcript.reference");
      const original = document.createElement("p"); original.lang = "en"; original.textContent = english;
      details.open = bilingualDisplay; englishDetails.push(details);
      details.append(summary, original); row.append(details);
    }
    button.addEventListener("click", () => setPosition(cue.start));
    transcriptRows.push({ row, button, start: index, end });
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
  $("offset").textContent = t("app.offset", { value: "0.00" });
  $("jump-time").value = "";
  $("jump-message").textContent = "";
  $("download").hidden = !track;
  $("feedback-quick").disabled = !track;
  $("audio-scope").textContent = isFormalPlayback(week) && track ? t("app.release.formal") : week.humanContentReview === "approved" && track ? t("app.release.full") : track?.scope === "full_candidate" ? t("app.release.review") : track?.scope === "full_reviewed" ? t("app.release.full") : track ? t("app.release.sample") : t("app.release.pending");
  $("voice").textContent = track ? t("app.voice.active", { speaker: week.speaker }) : t("app.voice.pending");
  renderTranscript();
  for (const button of $("variants").children) button.setAttribute("aria-pressed", String(button.dataset.id === track?.id));
  if (track) {
    pendingResume = playbackMemory.read(activeSource, track.durationSeconds);
    showResume();
    status(pendingResume ? "app.resume.start" : "app.audio.start");
    audio.src = track.audioUrl;
    audio.load();
    $("download").href = `${track.audioUrl}?download=1`;
    $("download").download = downloadFilename(week, track);
    $("download").title = $("download").download;
    $("subtitle-note").textContent = t("app.subtitle.follow");
  } else {
    audio.removeAttribute("src");
    audio.load();
    status("app.audio.weekPending");
    $("current-text").textContent = t("app.content.pending");
    $("next-text").textContent = t("app.content.otherWeeks");
    $("cue-count").textContent = "";
    $("subtitle-note").textContent = t("app.subtitle.pending");
    $("download").removeAttribute("href");
    $("download").removeAttribute("download");
    $("download").removeAttribute("title");
  }
  update();
}
function renderOutline() {
  const content = displayWeek();
  $("outline-title").textContent = t("app.outline.title");
  $("outline-meta").textContent = `${content.title} · ${week.date.replaceAll("-", ".")} · ${week.speaker} · ${content.scripture}`;
  $("outline-summary").textContent = content.summary;
  $("outline-content").replaceChildren();
  for (const item of content.outline) {
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
  for (const question of content.questions) { const li = document.createElement("li"); li.textContent = question; $("reflection-questions").append(li); }
  document.querySelector(".reflection").hidden = !content.questions.length;
  $("outline-review").textContent = `${content.contentReview}。${week.audioStatus?.startsWith("full_") ? t("app.outline.full") : t("app.outline.sample")}`;
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
      else if (original.label === "配音检查") item = { ...original, detail: original.detail };
      else if (original.label === "中文配音" && week.tracks.length) item = { ...original, detail: "整篇中文配音已生成。" };
    }
    const li = document.createElement("li");
    li.dataset.status = item.status;
    const mark = document.createElement("span");
    mark.className = "stage-mark";
    mark.textContent = item.status === "pass" ? "✓" : item.status === "review" ? "◐" : "○";
    const body = document.createElement("div"), heading = document.createElement("h3"), detail = document.createElement("p"), state = document.createElement("small");
    heading.textContent = appText(item.label);
    detail.textContent = appText(item.detail);
    state.textContent = t(item.status === "pass" ? "app.stage.complete" : item.status === "review" ? "app.stage.reviewPending" : "app.stage.pending");
    body.append(heading, detail);
    li.append(mark, body, state);
    $("production-stages").append(li);
  }
}
function renderVoiceBank() {
  const bank = catalog.voiceBank;
  voiceLabels = [];
  const bankLabels = () => { $("voice-bank-notice").textContent = bank?.speakers?.length ? t("app.voices.notice") : t("app.voices.pending"); };
  voiceLabels.push(bankLabels); bankLabels();
  $("probe-text").textContent = bank?.probeText?.join("\n\n") || "";
  $("probe-text").lang = "zh-Hans";
  $("voice-grid").replaceChildren();
  for (const speaker of bank?.speakers || []) {
    const card = document.createElement("article");
    card.className = "voice-card";
    const heading = document.createElement("h3"), meta = document.createElement("p");
    heading.textContent = speaker.name;
    meta.className = "voice-card-meta";
    const metaLabel = () => { meta.textContent = t("app.voices.meta", { english: formatTime(speaker.reference.durationSeconds), chinese: formatTime(speaker.chinese.durationSeconds) }); };
    voiceLabels.push(metaLabel); metaLabel();
    card.append(heading, meta);
    for (const key of ["reference", "chinese"]) {
      const label = document.createElement("p"), sample = document.createElement("audio");
      label.className = "sample-label";
      const sampleLabel = () => { label.textContent = t(key === "reference" ? "app.voices.english" : "app.voices.chinese"); sample.setAttribute("aria-label", `${speaker.name} ${label.textContent.slice(4)}`); };
      voiceLabels.push(sampleLabel); sampleLabel();
      sample.controls = true;
      sample.preload = "metadata";
      sample.src = speaker[key].audioUrl;
      sample.setAttribute("aria-label", `${speaker.name} ${label.textContent.slice(4)}`);
      sample.addEventListener("play", () => { fieldAlignment.invalidate(); document.querySelectorAll("audio").forEach(other => { if (other !== sample) other.pause(); }); });
      for (const event of ["play", "pause"]) sample.addEventListener(event, () => usage.record(`voice_${key}_${event}`, { speakerId: speaker.id, trackId: null, positionSeconds: null }));
      card.append(label, sample);
    }
    if (typeof speaker.referenceSourceUrl === "string" && speaker.referenceSourceUrl.startsWith("https://")) {
      const sourceLink = document.createElement("a");
      sourceLink.className = "voice-source-link"; sourceLink.href = speaker.referenceSourceUrl;
      sourceLink.target = "_blank"; sourceLink.rel = "noopener noreferrer";
      const sourceLabel = () => { sourceLink.textContent = t("app.voices.source"); };
      voiceLabels.push(sourceLabel); sourceLabel(); card.append(sourceLink);
    }
    const note = document.createElement("p");
    note.className = "voice-card-note";
    const noteLabel = () => { note.textContent = t(speaker.humanListeningStatus === "accepted" ? "app.voices.accepted" : "app.voices.review"); };
    voiceLabels.push(noteLabel); noteLabel();
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
  $("edition-label").textContent = isFormalPlayback(week) ? t("app.release.formal") : t("app.release.preview");
  $("week-status").textContent = isFormalPlayback(week) ? t("app.week.published") : week.humanContentReview === "approved" ? t("app.week.ready") : week.audioStatus === "full_candidate" ? t("app.week.review") : week.audioStatus === "full_reviewed" ? t("app.week.ready") : week.tracks.length ? t("app.week.sample") : t("app.week.outline");
  $("central-message").textContent = week.centralMessage;
  $("audio-notice").textContent = week.audioNotice;
  $("source-link").href = week.sourceUrl;
  $("source-link").textContent = week.sourceLabel ? t("app.source.link", { label: week.sourceLabel }) : t("app.source.open");
  $("source-link").hidden = false;
  $("variants").replaceChildren();
  $("variants").hidden = !week.tracks.length;
  for (const item of week.tracks) {
    const button = document.createElement("button");
    button.textContent = isFormalPlayback(week) ? t("app.release.formal") : item.label;
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
  renderWeekLabels();
}
async function startAlignmentPlayback({ signal } = {}) {
  if (signal?.aborted) throw new DOMException("Alignment cancelled", "AbortError");
  stopStartup();
  const token = generation, attempt = ++alignmentPlayAttempt;
  playPending = true; playFailed = false; positionTouched = true;
  document.querySelectorAll(".voice-card audio").forEach(sample => sample.pause());
  status("app.align.start"); update();
  try {
    // Explicit play, never a toggle; preserve the helper's failure for the controller.
    await playAlignmentAudio(audio, { signal });
    if (!signal?.aborted && token === generation && attempt === alignmentPlayAttempt) {
      stopStartup(); status("app.audio.playing"); update();
    }
  } catch (error) {
    if (!signal?.aborted && token === generation && attempt === alignmentPlayAttempt) {
      stopStartup(); audio.pause(); playFailed = true;
      status("app.align.failed"); update();
    }
    throw error;
  }
}
async function togglePlay(fromAlignment = false) {
  if (fromAlignment !== true) fieldAlignment.invalidate();
  if (!track || $("play").disabled) return;
  if (playPending) { stopStartup(); audio.pause(); status("app.audio.cancelled"); update(); return; }
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
  status("app.audio.connecting"); update();
  startupTimer = setTimeout(() => {
    if (token !== generation || attempt !== playAttempt) return;
    failStartup("app.audio.slow");
    feedback.error("audio_play");
  }, 15000);
  // Keep play() inside the original click; never await metadata/network first.
  try {
    await audio.play();
    if (token === generation && attempt === playAttempt) { stopStartup(); update(); }
  } catch {
    if (token === generation && attempt === playAttempt) {
      failStartup("app.audio.failed"); feedback.error("audio_play");
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
  event.target.setAttribute("aria-valuetext", t("app.seek.release", { time: preview }));
  $("seek-preview").textContent = t("app.seek.preview", { time: preview });
});
$("progress").addEventListener("change", event => setPosition(Number(event.target.value)));
$("progress").addEventListener("pointercancel", () => { scrubbing = false; $("seek-preview").textContent = ""; update(); });
$("jump-form").addEventListener("submit", event => {
  event.preventDefault();
  const time = parseTimecode($("jump-time").value);
  if (time === null) { $("jump-message").textContent = t("app.seek.invalid"); return; }
  if (!track || !Number.isFinite(audio.duration)) return;
  if (time > audio.duration) { $("jump-message").textContent = t("app.seek.range", { duration: formatTime(audio.duration) }); return; }
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
  if (!playFailed) status(playPending ? "app.audio.connecting" : pendingResume ? "app.resume.found" : "app.audio.ready");
  update();
});
for (const event of ["timeupdate", "durationchange", "seeked"]) audio.addEventListener(event, update);
audio.addEventListener("timeupdate", () => saveProgress());
audio.addEventListener("pause", () => saveProgress(true));
window.addEventListener("pagehide", () => saveProgress(true));
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "hidden") saveProgress(true); });
audio.addEventListener("play", () => { if (!playPending) status("app.audio.playing"); update(); });
audio.addEventListener("pause", () => {
  // A queued pause from a cancelled attempt can arrive after play() restarts.
  if (!audio.paused) return;
  if (playPending) stopStartup();
  if (track && !playFailed) status(audio.ended ? "app.audio.finished" : "app.audio.paused");
  update();
});
audio.addEventListener("ended", () => { status("app.audio.finished"); update(); });
audio.addEventListener("waiting", () => { if (track) status("app.audio.buffering"); });
audio.addEventListener("playing", () => { if (!audioIsCurrent()) return; stopStartup(); playFailed = false; status("app.audio.playing"); update(); });
audio.addEventListener("error", () => { if (track && audio.error) { failStartup("app.audio.loadFailed"); ready(false); feedback.error("audio_load"); } });
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
        onError: () => { if ($('statistics-opt-in').checked) feedback.usageDeliveryError?.(); },
      });
      feedback = createFeedback(audio, config, { usage });
      // The listener may have switched sources while the optional request ran.
      feedback.select(engagementWeek(week), track);
      $("feedback-quick").hidden = !config.enabled;
      usage.setEnabled(feedback.statisticsEnabled());
    }
  } catch { /* Optional feedback must never prevent playback. */ }
}
$("language-toggle").addEventListener("click", () => {
  const locales = ["zh", "en", "ko", "es"];
  setLocale(locales[(locales.indexOf(getLocale()) + 1) % locales.length]);
});
onLocaleChange(() => {
  $("interface-language").value = getLocale();
  updateLanguageControl();
  if (!catalog || !week) return;
  renderWeekOptions(); renderWeekLabels(); renderOutline(); renderProduction(); renderDownloads();
  renderTranscript(); ready(metadataReady); showResume(); updateUndo();
  voiceLabels.forEach(refresh => refresh());
  $("offset").textContent = t("app.offset", { value: `${fineOffset > 0 ? "+" : ""}${fineOffset.toFixed(2)}` });
  if (lastStatus) status(...lastStatus);
  $("jump-message").textContent = ""; $("seek-preview").textContent = "";
  lastCue = -2; update(); syncDockHeight();
});
$("interface-language").value = getLocale();
$("interface-language").addEventListener("change", event => setLocale(event.target.value));
localizeDOM();
try {
  const response = await fetch("/weekly.json");
  if (!response.ok) throw new Error("Catalog unavailable");
  catalog = validateCatalog(await response.json());
  renderWeekOptions();
  $("week-select").disabled = false;
  renderVoiceBank();
  selectWeek(new URLSearchParams(location.search).get("week"));
  const initialTab = new URLSearchParams(location.search).get("tab");
  if (["voices", "production", "transcript"].includes(initialTab)) selectTab(`tab-${initialTab}`);
  syncDockHeight();
  void initializeEngagement();
} catch {
  ready(false);
  $("title").textContent = t("app.load.title");
  status("app.load.failed");
  $("current-text").textContent = t("app.load.content");
}
