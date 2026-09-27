// The complete translated transcript remains in page-data.js. This module
// presents separately reviewed spoken captions only while a dub is selected.
const PAGE_ID = "2026-09-27-weekend-sermon-drive-530";
const PAGE_DATA_SHA256 = "fa071d1b7678eeaad7c5ae4c1539d2b6f8b908322b2e12283881b0be304362f3";
const LOCALES = ["zh-Hans", "ko", "es"];
const LABELS = { "zh-Hans": "中文配音", ko: "한국어 더빙", es: "Doblaje español" };
const SHA = /^[a-f0-9]{64}$/;

function exactKeys(value, keys) {
  return value && typeof value === "object" && !Array.isArray(value)
    && Object.keys(value).sort().join("|") === [...keys].sort().join("|");
}

export function validateAudioExtension(manifest, pageData) {
  if (!exactKeys(manifest, ["schemaVersion", "pageId", "englishSourcePackageJsonSha256",
    "sourceMediaSha256", "pageDataSha256", "status", "locales"])
    || manifest.schemaVersion !== "sermon-full-video-audio-extension-v1"
    || manifest.pageId !== PAGE_ID || pageData?.pageId !== PAGE_ID
    || manifest.sourceMediaSha256 !== pageData.sourceSha256
    || manifest.pageDataSha256 !== PAGE_DATA_SHA256
    || manifest.status !== "three_locale_audio_human_reviewed_candidate"
    || !SHA.test(manifest.englishSourcePackageJsonSha256)
    || !exactKeys(manifest.locales, LOCALES)) throw new Error("Invalid full-video audio extension identity");
  for (const locale of LOCALES) {
    const row = manifest.locales[locale];
    if (!exactKeys(row, ["displayCandidateJsonSha256", "displayContentSha256",
      "spokenCandidateJsonSha256", "audioPackageJsonSha256",
      "audioHumanReviewReceiptJsonSha256", "machineScreeningReceiptJsonSha256",
      "audio", "captions", "durationSeconds", "spokenCueCount"])
      || !["displayCandidateJsonSha256", "displayContentSha256",
        "spokenCandidateJsonSha256", "audioPackageJsonSha256",
        "audioHumanReviewReceiptJsonSha256", "machineScreeningReceiptJsonSha256"]
        .every(key => SHA.test(row[key]))
      || !["audio", "captions"].every(key => exactKeys(row[key], ["path", "sha256"])
        && SHA.test(row[key].sha256) && row[key].path.startsWith("/")
        && !row[key].path.startsWith("//"))
      || !row.audio.path.endsWith(".mp3") || !row.captions.path.endsWith(".json")
      || !Number.isFinite(row.durationSeconds) || row.durationSeconds <= 0
      || Math.abs(row.durationSeconds - pageData.duration) > 0.2
      || !Number.isInteger(row.spokenCueCount) || row.spokenCueCount < 1)
      throw new Error(`Invalid reviewed spoken audio for ${locale}`);
  }
  return manifest;
}

export function validateSpokenCaptions(captions, count, duration) {
  if (!exactKeys(captions, ["cues"]) || !Array.isArray(captions.cues)
    || captions.cues.length !== count) throw new Error("Invalid spoken caption count");
  let previousEnd = 0;
  for (const cue of captions.cues) {
    if (!exactKeys(cue, ["textGroupId", "text", "start", "end"])
      || typeof cue.textGroupId !== "string" || !cue.textGroupId
      || typeof cue.text !== "string" || !cue.text.trim()
      || !Number.isFinite(cue.start) || !Number.isFinite(cue.end)
      || cue.start < previousEnd - 0.02 || cue.end <= cue.start
      || cue.end > duration + 0.1) throw new Error("Invalid spoken caption timing");
    previousEnd = cue.end;
  }
  return captions.cues;
}

export function audioAvailabilityMessage(state) {
  return {
    loading: "配音加载中…",
    ready: "配音已就绪",
    unavailable: "配音暂不可用，请使用英文原声。",
  }[state] || "";
}

export function dubOutputFromVideo(volume, intendedMuted) {
  if (!Number.isFinite(volume) || volume < 0 || volume > 1)
    throw new Error("Invalid video volume");
  return { volume, muted: Boolean(intendedMuted) };
}

async function sha256(bytes) {
  return [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))]
    .map(value => value.toString(16).padStart(2, "0")).join("");
}

async function fetchVerified(path, expectedHash, maxBytes) {
  const url = new URL(path, location.href);
  if (url.origin !== location.origin || !path.startsWith("/") || path.startsWith("//"))
    throw new Error("Audio extension asset must be same-origin");
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`Audio extension asset HTTP ${response.status}`);
  const bytes = await response.arrayBuffer();
  if (bytes.byteLength > maxBytes || await sha256(bytes) !== expectedHash)
    throw new Error("Audio extension asset hash mismatch");
  return bytes;
}

async function start() {
  const script = document.querySelector("script[data-audio-extension]");
  const pageData = window.fullVideoPageData;
  if (!script || !pageData || !SHA.test(script.dataset.manifestSha256 || "")) return;
  let manifest;
  try {
    const bytes = await fetchVerified(`/pages/${PAGE_ID}/audio-extension.json`,
      script.dataset.manifestSha256, 100_000);
    manifest = validateAudioExtension(JSON.parse(new TextDecoder().decode(bytes)), pageData);
  } catch (error) {
    // The original video and complete transcript remain usable.
    return;
  }
  const video = document.getElementById("video");
  const panel = document.createElement("div");
  panel.className = "dub-panel";
  panel.setAttribute("aria-label", "配音播放");
  const controls = document.createElement("div");
  controls.className = "dub-controls";
  const captionLabel = document.createElement("strong");
  captionLabel.textContent = "配音字幕";
  const caption = document.createElement("p");
  caption.className = "dub-caption";
  caption.hidden = true;
  const note = document.createElement("small");
  note.textContent = "完整译文保留在下方；配音字幕对应精简口播稿。";
  const original = document.createElement("button");
  original.type = "button";
  original.textContent = "英文原声";
  const dubMute = document.createElement("button");
  dubMute.type = "button";
  dubMute.hidden = true;
  const status = document.createElement("small");
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  status.hidden = true;
  controls.append(original, dubMute);
  panel.append(controls, status, captionLabel, caption, note);
  video.after(panel);
  const style = document.createElement("style");
  style.textContent = ".dub-panel{padding:12px 18px;border-top:1px solid #dce3e8;background:#f7faf9}"
    + ".dub-controls{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px}"
    + ".dub-controls button{font:inherit;border:1px solid #94bec0;background:white;border-radius:8px;padding:6px 10px;cursor:pointer}"
    + ".dub-controls button[aria-pressed=true]{background:#1d626c;color:white}"
    + ".dub-caption{min-height:2em;margin:6px 0;font-size:16px}.dub-panel small{color:#607082}";
  document.head.append(style);
  const audio = new Audio();
  audio.preload = "auto";
  let active = null;
  let originalMuted = video.muted;
  let dubMuted = video.muted;
  const cache = new Map();
  const pending = new Map();
  const buttons = new Map();
  const failed = new Set();
  const currentLocale = () => document.documentElement.lang;
  function showStatus(state) {
    status.textContent = audioAvailabilityMessage(state);
    status.hidden = !status.textContent;
  }
  function syncDubOutput() {
    const output = dubOutputFromVideo(video.volume, dubMuted);
    audio.volume = output.volume;
    audio.muted = output.muted;
    dubMute.textContent = dubMuted ? "取消配音静音" : "配音静音";
    dubMute.setAttribute("aria-pressed", String(dubMuted));
  }
  function showCaption() {
    if (!active) { caption.hidden = true; return; }
    const row = cache.get(active);
    const cue = row?.cues.find(item => item.start <= video.currentTime
      && video.currentTime < item.end);
    caption.textContent = cue?.text || "";
    caption.hidden = !cue;
  }
  function setOriginal() {
    audio.pause();
    active = null;
    dubMute.hidden = true;
    video.muted = originalMuted;
    original.setAttribute("aria-pressed", "true");
    for (const button of buttons.values()) button.setAttribute("aria-pressed", "false");
    showCaption();
  }
  async function loadLocale(locale) {
    if (cache.has(locale)) return cache.get(locale);
    if (pending.has(locale)) return pending.get(locale);
    const task = (async () => {
      const row = manifest.locales[locale];
      const [captionBytes, audioBytes] = await Promise.all([
        fetchVerified(row.captions.path, row.captions.sha256, 4_000_000),
        fetchVerified(row.audio.path, row.audio.sha256, 50_000_000),
      ]);
      const cues = validateSpokenCaptions(JSON.parse(new TextDecoder().decode(captionBytes)),
        row.spokenCueCount, row.durationSeconds);
      const data = { cues, url: URL.createObjectURL(new Blob([audioBytes], { type: "audio/mpeg" })) };
      cache.set(locale, data);
      return data;
    })();
    pending.set(locale, task);
    try { return await task; } finally { pending.delete(locale); }
  }
  async function select(locale) {
    const row = cache.get(locale);
    if (!row || locale !== currentLocale()) return;
    if (!active) {
      originalMuted = video.muted;
      dubMuted = video.muted;
    }
    audio.pause();
    active = locale;
    audio.src = row.url;
    audio.currentTime = video.currentTime;
    audio.playbackRate = video.playbackRate;
    syncDubOutput();
    video.muted = true;
    dubMute.hidden = false;
    original.setAttribute("aria-pressed", "false");
    for (const [key, button] of buttons) button.setAttribute("aria-pressed", String(key === locale));
    showCaption();
    if (!video.paused) {
      try { await audio.play(); } catch { setOriginal(); }
    }
  }
  async function showLocale() {
    const locale = currentLocale();
    const heading = document.querySelector(".transcript-top h3");
    if (heading) heading.textContent = locale === "en" ? "英文原文 · 点击句子跳转"
      : "完整译文 · 点击句子跳转";
    if (active && active !== locale) setOriginal();
    for (const [key, button] of buttons) button.hidden = key !== locale;
    if (!LOCALES.includes(locale)) { showStatus(""); return; }
    if (failed.has(locale)) { showStatus("unavailable"); return; }
    if (buttons.has(locale)) { showStatus("ready"); return; }
    showStatus("loading");
    try {
      await loadLocale(locale);
      if (locale !== currentLocale()) return;
      if (buttons.has(locale)) { showStatus("ready"); return; }
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = LABELS[locale];
      button.setAttribute("aria-pressed", "false");
      button.addEventListener("click", () => select(locale));
      buttons.set(locale, button);
      controls.append(button);
      showStatus("ready");
    } catch {
      failed.add(locale);
      if (locale === currentLocale()) showStatus("unavailable");
    }
  }
  original.addEventListener("click", setOriginal);
  dubMute.addEventListener("click", () => {
    if (!active) return;
    dubMuted = !dubMuted;
    syncDubOutput();
  });
  original.setAttribute("aria-pressed", "true");
  video.addEventListener("play", () => { if (active) audio.play().catch(setOriginal); });
  video.addEventListener("pause", () => audio.pause());
  video.addEventListener("seeking", () => { if (active) audio.currentTime = video.currentTime; });
  video.addEventListener("ratechange", () => { audio.playbackRate = video.playbackRate; });
  video.addEventListener("volumechange", () => {
    if (!active) return;
    if (!video.muted) {
      dubMuted = false;
      video.muted = true;
    }
    syncDubOutput();
  });
  video.addEventListener("timeupdate", () => {
    if (active && Math.abs(audio.currentTime - video.currentTime) > 0.3)
      audio.currentTime = video.currentTime;
    showCaption();
  });
  audio.addEventListener("error", () => {
    const locale = active;
    setOriginal();
    if (locale) {
      failed.add(locale);
      buttons.get(locale)?.remove();
      buttons.delete(locale);
      const data = cache.get(locale);
      if (data) URL.revokeObjectURL(data.url);
      cache.delete(locale);
      if (locale === currentLocale()) showStatus("unavailable");
    }
  });
  document.getElementById("tabs")?.addEventListener("click", () => queueMicrotask(showLocale));
  await showLocale();
}

if (typeof window !== "undefined" && typeof document !== "undefined") start();
