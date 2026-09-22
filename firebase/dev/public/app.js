const languageNames = {
  en: { native: "English", code: "EN", detail: "英文原文" },
  "zh-Hans": { native: "简体中文", code: "ZH", detail: "中文（简体）" },
  ko: { native: "한국어", code: "KO", detail: "韩语" },
  es: { native: "Español", code: "ES", detail: "西班牙语" },
  vi: { native: "Tiếng Việt", code: "VI", detail: "越南语" }
};

const interfaceCopy = {
  zh: {
    banner: "9 月 20 日证道片段 POC；可切换英文原文和四种目标语言对照。", brand: "多语言证道", languageCard: "证道语言",
    mockTitle: "真实 Layer 2 + Layer 3 POC", mockBody: "六个英文源句分别翻译并经 GPT 语义裁判；Eric 克隆音色仅供 Dev App 测试。",
    sourceTitle: "Layer 1 英文原文", sourceBody: "使用同一来源窗口的英文 anchor 和 Eric 原始录音，作为四种译文与克隆音频的对照。",
    tabs: ["收听", "字幕全文", "大纲"], now: "正在讲述", transcript: "字幕全文", outline: "证道大纲",
    playerNote: "机器生成的讲员克隆音色；非原始录音、非正式配音，人工听审待完成。", sourcePlayerNote: "讲员原始英文录音片段；英文 anchor 仍保留其 Layer 1 机器边界审核状态。", release: "发布包状态", text: "文字", audio: "音频",
    mock: "机器审核通过 · 待人工", tone: "克隆音频 · 待听审", dialogTitle: "选择证道语言", dialogHint: "界面语言、内容语言和音频语言分别管理。",
    dialogFoot: "英文是 Layer 1 来源对照；四种目标语言均为开发 POC。越南语 ASR 筛查低于门线。",
    footer: "独立个人开发项目，与 Mariners Church 无隶属或背书关系。", switchInterface: "切换界面为英文",
    themeDark: "深色", themeLight: "浅色", audioVariant: "校对音频版本", capabilities: "机器译文 · 估算字幕 · 克隆音频", sourceCapabilities: "英文原文 · 原始录音 · 来源时间轴", loadError: "Dev 内容暂时无法载入"
  },
  en: {
    banner: "September 20 sermon-fragment POC; switch between the English source and four target languages.", brand: "Multilingual Sermons", languageCard: "Sermon language",
    mockTitle: "Real Layer 2 + Layer 3 POC", mockBody: "Six English source units were translated and GPT-judged; Eric's cloned voice is for Dev App testing only.",
    sourceTitle: "Layer 1 English source", sourceBody: "The aligned English anchors and Eric's original recording provide the reference for all four translations and cloned voices.",
    tabs: ["Listen", "Transcript", "Outline"], now: "Now speaking", transcript: "Full transcript", outline: "Sermon outline",
    playerNote: "Machine-generated speaker clone; not the original recording or production dubbing. Human listening is pending.", sourcePlayerNote: "Original English speaker audio; the English anchors retain their Layer 1 machine-boundary review state.", release: "Release package status", text: "Text", audio: "Audio",
    mock: "Machine pass · human pending", tone: "Cloned audio · listening pending", dialogTitle: "Choose sermon language", dialogHint: "Interface, content, and audio languages are managed separately.",
    dialogFoot: "English is the Layer 1 source reference. All four target languages are development POCs; Vietnamese remains below the ASR threshold.",
    footer: "Independent personal development project; not affiliated with or endorsed by Mariners Church.", switchInterface: "Switch interface to Chinese",
    themeDark: "Dark", themeLight: "Light", audioVariant: "Review audio version", capabilities: "Machine text · Estimated captions · Cloned audio", sourceCapabilities: "English source · Original audio · Source timeline", loadError: "Dev content is temporarily unavailable"
  }
};

const state = {
  catalog: null, page: null, locale: null, release: null, content: null, audioVariant: null,
  ui: localStorage.getItem("tongxing-dev-ui") === "en" ? "en" : "zh", activeTab: "listen"
};
const $ = (id) => document.getElementById(id);
const audio = $("audio");

async function loadJSON(path) {
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  return response.json();
}

function availableAudioVariants() {
  if (state.release?.audioVariants?.length) return state.release.audioVariants;
  return state.release ? [{
    id: "default",
    label: languageNames[state.locale]?.native || "Audio",
    labelEn: languageNames[state.locale]?.native || "Audio",
    description: "",
    descriptionEn: "",
    audioUrl: state.release.audioUrl,
    audioSha256: state.release.audioSha256,
    durationSeconds: state.content?.durationSeconds
  }] : [];
}

function activeCues() {
  return state.audioVariant?.cues?.length ? state.audioVariant.cues : (state.content?.cues || []);
}

function effectiveDuration() {
  if (Number.isFinite(audio.duration)) return audio.duration;
  return state.audioVariant?.durationSeconds || state.content?.durationSeconds || 24;
}

function loadAudioVariant(variant, { remember = true } = {}) {
  if (!variant) return;
  state.audioVariant = variant;
  audio.pause();
  const audioUrl = new URL(variant.audioUrl, location.origin);
  if (variant.audioSha256) audioUrl.searchParams.set("sha256", variant.audioSha256);
  audio.src = audioUrl.href;
  audio.load();
  if (remember) localStorage.setItem(`tongxing-dev-audio-${state.page.id}-${state.locale}`, variant.id);
}

function routeLocale() {
  const match = location.pathname.match(/\/pages\/2026-09-20-lion-of-judah-poc\/(en|zh-Hans|ko|es|vi)\/?$/);
  return match?.[1] || new URLSearchParams(location.search).get("lang");
}

async function selectLocale(locale, { navigate = true } = {}) {
  const target = state.page.targets[locale];
  if (!target) return;
  const release = await loadJSON(target.releasePackageUrl);
  const validSchema = ["sermon-source-language-demo-package-v1", "sermon-target-language-demo-package-v1"].includes(release.schemaVersion);
  if (!validSchema || release.environment !== "development" || !release.poc) {
    throw new Error("Invalid development release package");
  }
  const content = await loadJSON(release.contentUrl);
  state.locale = locale;
  state.release = release;
  state.content = content;
  const variants = availableAudioVariants();
  const savedVariant = localStorage.getItem(`tongxing-dev-audio-${state.page.id}-${locale}`);
  const variant = variants.find(item => item.id === savedVariant)
    || variants.find(item => item.id === release.defaultAudioVariantId)
    || variants[0];
  loadAudioVariant(variant, { remember: false });
  localStorage.setItem(`tongxing-dev-content-${state.page.id}`, locale);
  if (navigate) history.pushState({ locale }, "", release.pageUrl);
  render();
  if ($("languageDialog").open) $("languageDialog").close();
}

function render() {
  const content = state.content;
  const copy = interfaceCopy[state.ui];
  document.documentElement.lang = state.locale;
  document.title = `${content.title} · 同行 Dev`;
  $("seriesLabel").textContent = content.series;
  $("sermonTitle").textContent = content.title;
  $("sermonMeta").replaceChildren(...[content.speaker, content.scripture, content.date].map(value => {
    const span = document.createElement("span");
    span.textContent = value;
    return span;
  }));
  $("sermonSummary").textContent = content.summary;
  $("languageName").textContent = languageNames[state.locale].native;
  $("languageCapabilities").textContent = state.locale === "en" ? copy.sourceCapabilities : copy.capabilities;
  $("currentCaption").textContent = currentCue()?.text || activeCues()[0]?.text || "";
  $("sourceCaption").textContent = state.locale === "en" ? "" : (currentCue()?.source || activeCues()[0]?.source || "");
  $("sourceCaption").hidden = state.locale === "en";
  renderAudioVariantPicker();
  renderTranscript();
  renderOutline();
  renderLanguageList();
  renderInterfaceCopy();
  syncPlayer();
}

function renderAudioVariantPicker() {
  const variants = availableAudioVariants();
  const picker = $("audioVariantPicker");
  picker.hidden = variants.length < 2;
  if (picker.hidden) return;
  const select = $("audioVariantSelect");
  select.replaceChildren(...variants.map(variant => {
    const option = document.createElement("option");
    option.value = variant.id;
    option.textContent = state.ui === "en" ? (variant.labelEn || variant.label) : variant.label;
    option.selected = variant.id === state.audioVariant?.id;
    return option;
  }));
  $("audioVariantDescription").textContent = state.ui === "en"
    ? (state.audioVariant?.descriptionEn || state.audioVariant?.description || "")
    : (state.audioVariant?.description || "");
}

function renderInterfaceCopy() {
  const copy = interfaceCopy[state.ui];
  $("devBannerText").textContent = copy.banner;
  $("brandSubtitle").textContent = copy.brand;
  $("languageCardLabel").textContent = copy.languageCard;
  $("mockNoticeTitle").textContent = state.locale === "en" ? copy.sourceTitle : copy.mockTitle;
  $("mockNoticeBody").textContent = state.locale === "en" ? copy.sourceBody : copy.mockBody;
  [$("listenTab"), $("transcriptTab"), $("outlineTab")].forEach((node, index) => node.textContent = copy.tabs[index]);
  $("nowHeading").textContent = copy.now;
  $("transcriptHeading").textContent = copy.transcript;
  $("outlineHeading").textContent = copy.outline;
  $("playerNote").textContent = state.locale === "en" ? copy.sourcePlayerNote : copy.playerNote;
  $("releaseTitle").textContent = copy.release;
  $("contentStatusLabel").textContent = copy.text;
  $("audioStatusLabel").textContent = copy.audio;
  $("contentStatus").textContent = state.release?.contentStatusLabel || copy.mock;
  $("audioStatus").textContent = state.release?.audioStatusLabel || copy.tone;
  $("languageDialogTitle").textContent = copy.dialogTitle;
  $("languageDialogHint").textContent = copy.dialogHint;
  $("languageDialogFoot").textContent = copy.dialogFoot;
  $("footerText").textContent = copy.footer;
  $("interfaceLanguage").textContent = state.ui === "zh" ? "EN" : "中";
  $("interfaceLanguage").setAttribute("aria-label", copy.switchInterface);
  $("themeToggle").textContent = document.documentElement.dataset.theme === "dark" ? copy.themeLight : copy.themeDark;
  $("audioVariantLabel").textContent = copy.audioVariant;
  renderAudioVariantPicker();
}

function renderLanguageList() {
  $("languageList").replaceChildren(...Object.keys(state.page.targets).map(locale => {
    const info = languageNames[locale];
    const button = document.createElement("button");
    button.type = "button";
    button.className = `language-option${locale === state.locale ? " is-selected" : ""}`;
    const target = state.page.targets[locale];
    const status = locale === "en" ? "SOURCE<br>REFERENCE" : target.machineScreening === "requires_review" ? "ASR REVIEW<br>REQUIRED" : "MACHINE<br>SCREENED";
    const media = locale === "en" ? "TEXT · ORIGINAL AUDIO" : "TEXT · CLONED AUDIO";
    button.innerHTML = `<span class="language-option-name"><span class="language-code">${info.code}</span><span><strong>${info.native}</strong><small>${info.detail}</small></span></span><span class="language-option-caps">${media}<br>${status}</span>`;
    button.addEventListener("click", () => selectLocale(locale).catch(showError));
    return button;
  }));
}

function renderTranscript() {
  $("transcriptList").replaceChildren(...activeCues().map((cue, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `transcript-item${currentCueIndex() === index ? " is-current" : ""}`;
    const source = state.locale === "en" || !cue.source || cue.source === cue.text ? "" : `<span lang="en">${escapeHTML(cue.source)}</span>`;
    button.innerHTML = `<span class="transcript-time">${formatTime(cue.start)}</span><span class="transcript-copy"><strong>${escapeHTML(cue.text)}</strong>${source}</span>`;
    button.addEventListener("click", () => {
      audio.currentTime = cue.start;
      switchTab("listen");
      audio.play().catch(() => {});
    });
    return button;
  }));
}

function renderOutline() {
  $("outlineList").replaceChildren(...state.content.outline.map(item => {
    const section = document.createElement("section");
    section.className = "outline-item";
    const title = document.createElement("h3"); title.textContent = item.title;
    const body = document.createElement("p"); body.textContent = item.body;
    section.append(title, body);
    return section;
  }));
}

function currentCueIndex() {
  if (!state.content) return 0;
  const cues = activeCues();
  const active = cues.findIndex(cue => audio.currentTime >= cue.start && audio.currentTime < cue.end);
  if (active >= 0) return active;
  let latest = 0;
  cues.forEach((cue, index) => { if (audio.currentTime >= cue.start) latest = index; });
  return latest;
}

function currentCue() { return activeCues()[currentCueIndex()]; }

function syncPlayer() {
  if (!state.content) return;
  const cue = currentCue();
  $("currentCaption").textContent = cue.text;
  $("sourceCaption").textContent = state.locale === "en" ? "" : cue.source;
  $("sourceCaption").hidden = state.locale === "en";
  $("cueCounter").textContent = `${currentCueIndex() + 1} / ${activeCues().length}`;
  const duration = effectiveDuration();
  const percent = Math.min(100, Math.max(0, audio.currentTime / duration * 100));
  $("progressFill").style.width = `${percent}%`;
  $("progressTrack").setAttribute("aria-valuenow", String(Math.round(percent)));
  $("elapsed").textContent = formatTime(audio.currentTime);
  $("duration").textContent = formatTime(duration);
  document.querySelectorAll(".transcript-item").forEach((item, index) => item.classList.toggle("is-current", index === currentCueIndex()));
}

function switchTab(name) {
  state.activeTab = name;
  document.querySelectorAll("[data-tab]").forEach(button => {
    const active = button.dataset.tab === name;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", String(active));
  });
  document.querySelectorAll(".panel").forEach(panel => {
    const active = panel.id === `panel-${name}`;
    panel.hidden = !active;
    panel.classList.toggle("is-active", active);
  });
}

function formatTime(value) {
  const seconds = Math.max(0, Math.floor(value || 0));
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

function escapeHTML(value) {
  const span = document.createElement("span");
  span.textContent = value;
  return span.innerHTML;
}

function showError(error) {
  console.error(error);
  $("sermonTitle").textContent = interfaceCopy[state.ui].loadError;
  $("sermonSummary").textContent = error.message;
}

function bindEvents() {
  $("languageButton").addEventListener("click", () => $("languageDialog").showModal());
  $("closeLanguageDialog").addEventListener("click", () => $("languageDialog").close());
  $("languageDialog").addEventListener("click", event => { if (event.target === $("languageDialog")) $("languageDialog").close(); });
  $("audioVariantSelect").addEventListener("change", event => {
    const variant = availableAudioVariants().find(item => item.id === event.target.value);
    loadAudioVariant(variant);
    render();
  });
  document.querySelectorAll("[data-tab]").forEach(button => button.addEventListener("click", () => switchTab(button.dataset.tab)));
  $("playButton").addEventListener("click", () => audio.paused ? audio.play().catch(() => {}) : audio.pause());
  document.querySelectorAll("[data-skip]").forEach(button => button.addEventListener("click", () => {
      audio.currentTime = Math.max(0, Math.min(effectiveDuration(), audio.currentTime + Number(button.dataset.skip)));
  }));
  $("progressTrack").addEventListener("click", event => {
    const rect = event.currentTarget.getBoundingClientRect();
    audio.currentTime = effectiveDuration() * (event.clientX - rect.left) / rect.width;
  });
  $("progressTrack").addEventListener("keydown", event => {
    if (["ArrowLeft", "ArrowRight"].includes(event.key)) {
      event.preventDefault();
      audio.currentTime = Math.max(0, Math.min(effectiveDuration(), audio.currentTime + (event.key === "ArrowRight" ? 1 : -1)));
    }
  });
  audio.addEventListener("timeupdate", syncPlayer);
  audio.addEventListener("loadedmetadata", syncPlayer);
  audio.addEventListener("play", () => { $("playIcon").textContent = "❚❚"; $("playButton").setAttribute("aria-label", "暂停"); });
  audio.addEventListener("pause", () => { $("playIcon").textContent = "▶"; $("playButton").setAttribute("aria-label", "播放"); });
  $("interfaceLanguage").addEventListener("click", () => {
    state.ui = state.ui === "zh" ? "en" : "zh";
    localStorage.setItem("tongxing-dev-ui", state.ui);
    render();
  });
  $("themeToggle").addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    localStorage.setItem("tongxing-dev-theme", next);
    renderInterfaceCopy();
  });
  window.addEventListener("popstate", () => {
    const locale = routeLocale() || state.page.defaultTargetLocale;
    selectLocale(locale, { navigate: false }).catch(showError);
  });
}

async function init() {
  document.documentElement.dataset.theme = localStorage.getItem("tongxing-dev-theme") === "dark" ? "dark" : "light";
  bindEvents();
  renderInterfaceCopy();
  try {
    state.catalog = await loadJSON("/multilingual.json");
    if (state.catalog.schemaVersion !== "sermon-multilingual-demo-catalog-v1" || state.catalog.environment !== "development" || !state.catalog.poc) {
      throw new Error("Invalid Dev catalog");
    }
    state.page = state.catalog.pages.find(page => page.id === state.catalog.defaultPageId);
    const requested = routeLocale();
    const saved = localStorage.getItem(`tongxing-dev-content-${state.page.id}`);
    const locale = state.page.targets[requested] ? requested : state.page.targets[saved] ? saved : state.page.defaultTargetLocale;
    await selectLocale(locale, { navigate: location.pathname !== "/" });
  } catch (error) {
    showError(error);
  }
}

init();
