(function () {
  const captions = [
    {
      en: "Today we are looking at Numbers 16, where rebellion rises against Moses and Aaron.",
      zh: "今天我们来看《民数记》十六章：悖逆兴起，起来攻击摩西和亚伦。",
      draft: "今天我们看民数记十六章，悖逆兴起...",
      ref: "Numbers 16",
      note: "同篇证道锚定经文，优先固定为 exact reference。",
      confidence: 92,
      duration: 5200
    },
    {
      en: "The people questioned God's appointed leadership, but the deeper issue was their heart before the Lord.",
      zh: "他们质疑神所设立的带领，但更深的问题，是他们在主面前的心。",
      draft: "他们质疑神设立的领袖，但更深处是心的问题。",
      ref: "Leadership",
      note: "术语候选：appointed leadership 可译为“神所设立的带领”。",
      confidence: 88,
      duration: 6100
    },
    {
      en: "Aaron stood between the dead and the living, interceding for the people.",
      zh: "亚伦站在死人和活人中间，为百姓代求。",
      draft: "亚伦站在死人和活人中间，为百姓代求。",
      ref: "Numbers 16:48",
      note: "明确经文画面，可在 sidebar 显示具体章节。",
      confidence: 95,
      duration: 4700
    },
    {
      en: "Every one of us needs a mediator who can stand between us and death.",
      zh: "我们每个人都需要一位中保，站在我们和死亡之间。",
      draft: "我们都需要一位中保，站在我们和死亡之间。",
      ref: "Mediator",
      note: "核心神学术语：Mediator -> 中保。",
      confidence: 91,
      duration: 5200
    },
    {
      en: "Jesus is the greater mediator, the one who stands in our place and brings mercy.",
      zh: "耶稣是那位更大的中保，祂站在我们的位置上，把怜悯带给我们。",
      draft: "耶稣是更大的中保，站在我们的位置上...",
      ref: "Jesus as Mediator",
      note: "金句候选：必须保留英文 source segment 和 timecode。",
      confidence: 90,
      duration: 6200
    }
  ];

  const state = {
    selectedService: "830",
    monitoring: false,
    captioning: false,
    paused: false,
    frozen: false,
    fallback: false,
    sourceReady: false,
    captionRequested: false,
    sidebarOpen: true,
    offsetMs: 0,
    nextStartMs: 0,
    captionIndex: 0,
    playbackIndex: 0,
    currentSegmentId: null,
    segments: [],
    playbackSegments: [],
    monitorTimers: [],
    streamTimer: null,
    playbackTimer: null,
    clockTimer: null,
    progressTimer: null,
    startedAt: null,
    playbackStartedAt: null,
    playbackBaseMs: 0,
    playbackSpeed: 18,
    lastExport: null,
    segmentAutoFollow: true,
    segmentScrollProgrammatic: false,
    adminSettings: {
      sunday: "2026-06-21",
      manualLiveUrl: "",
      approxStartTime: "",
      captureMode: "automatic"
    }
  };

  const el = {
    shell: document.querySelector(".app-shell"),
    clock: document.getElementById("clock"),
    sourceStatus: document.getElementById("sourceStatus"),
    slaStatus: document.getElementById("slaStatus"),
    sourceList: document.getElementById("sourceList"),
    adminSettings: document.getElementById("adminSettings"),
    captureMode: document.getElementById("captureMode"),
    sundaySelect: document.getElementById("sundaySelect"),
    manualLiveUrl: document.getElementById("manualLiveUrl"),
    approxStartTime: document.getElementById("approxStartTime"),
    autoDiscoveryStatus: document.getElementById("autoDiscoveryStatus"),
    publicSliceLabel: document.getElementById("publicSliceLabel"),
    draftCaption: document.getElementById("draftCaption"),
    stableCaption: document.getElementById("stableCaption"),
    englishSidecar: document.getElementById("englishSidecar"),
    confidenceMeter: document.getElementById("confidenceMeter"),
    sermonTitle: document.getElementById("sermonTitle"),
    sermonMeta: document.getElementById("sermonMeta"),
    generationStatus: document.getElementById("generationStatus"),
    segmentList: document.getElementById("segmentList"),
    segmentCount: document.getElementById("segmentCount"),
    returnLiveButton: document.getElementById("returnLiveButton"),
    scriptureCandidates: document.getElementById("scriptureCandidates"),
    termList: document.getElementById("termList"),
    noteBlock: document.getElementById("noteBlock"),
    eventLog: document.getElementById("eventLog"),
    sessionLabel: document.getElementById("sessionLabel"),
    deadlineLabel: document.getElementById("deadlineLabel"),
    timelineFill: document.getElementById("timelineFill"),
    timelineCursor: document.getElementById("timelineCursor"),
    offsetInput: document.getElementById("offsetInput")
  };

  function init() {
    document.addEventListener("click", onActionClick);
    if (el.adminSettings) {
      el.adminSettings.addEventListener("submit", (event) => event.preventDefault());
    }
    if (el.sundaySelect) {
      el.sundaySelect.addEventListener("change", () => {
        saveAdminSettings({ quiet: true });
        log(`会众页面已切换到 ${state.adminSettings.sunday} 周日切片；所有普通用户看到同一份发布内容。`);
      });
    }
    el.segmentList.addEventListener("scroll", onSegmentTrackScroll, { passive: true });
    el.segmentList.addEventListener("click", onSegmentTrackClick);
    el.clock.textContent = formatClock();
    state.clockTimer = window.setInterval(() => {
      el.clock.textContent = formatClock();
    }, 1000);
    setStatus("等待监控", "watching");
    setSla("11:30 会众可用", "ready");
    log("控制台已就绪：目标是在 11:30 场开始时，为正在听道的会众提供可用中文字幕。");
    loadPlaybackSimulation();
    syncAdminSettings();
    updateSourceCards("idle");
    updateTimeline();
  }

  function loadPlaybackSimulation() {
    const simulation = window.SERMON_PLAYBACK_SIMULATION;
    if (!simulation || !Array.isArray(simulation.segments) || !simulation.segments.length) {
      log("未检测到直播链接回放数据，当前使用内置 mock 字幕流。");
      return;
    }

    state.playbackSegments = simulation.segments
      .map((segment, index) => normalizePlaybackSegment(segment, index))
      .filter(Boolean);
    state.playbackSpeed = Number(simulation.playbackSpeed) || 18;
    if (!state.playbackSegments.length) {
      log("直播链接回放数据为空，当前使用内置 mock 字幕流。");
      return;
    }

    const liveTitle = simulation.live?.title || "live archive";
    const sermonTitle = simulation.sermonTitle || simulation.sermonCandidate?.title || liveTitle;
    const start = simulation.sermonStart?.timecode || "unknown";
    state.adminSettings.manualLiveUrl = simulation.live?.url || state.adminSettings.manualLiveUrl;
    state.adminSettings.approxStartTime = start !== "unknown" ? start : state.adminSettings.approxStartTime;
    updateSermonMeta({
      title: sermonTitle,
      meta: `${simulation.live?.url || "直播链接已加载"} · 证道开始 ${start}`,
      status: "已加载",
      tone: "ready"
    });
    log(`已加载直播链接回放数据：${liveTitle}；证道开始 ${start}；${state.playbackSegments.length} 个片段。`);
    if (simulation.translationStatus === "needs_translation") {
      log("当前 POC 片段为英文字幕源，中文字幕位置将显示 AI 待生成状态，用于验证播放和对齐。");
    }
  }

  function normalizePlaybackSegment(segment, index) {
    const startMs = Number(segment.startMs);
    const endMs = Number(segment.endMs);
    if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || endMs <= startMs) return null;
    const en = String(segment.en || "").trim();
    const zh = String(segment.zh || segment.text || en || "").trim();
    return {
      id: segment.id || `sim_${String(index + 1).padStart(4, "0")}`,
      startMs,
      endMs,
      zh: zh || "AI 中文待生成",
      draft: String(segment.draft || zh || "正在生成中文字幕..."),
      en,
      ref: segment.ref || "",
      note: segment.note || "直播链接模拟播放片段。",
      confidence: Number(segment.confidence) || 70,
      locked: false,
      marked: false,
      offsetMs: 0,
      translationStatus: segment.translationStatus || "unknown"
    };
  }

  function onActionClick(event) {
    const control = event.target.closest("[data-action]");
    if (!control) return;

    const action = control.dataset.action;
    if (action === "select-service") selectService(control.dataset.service);
    if (action === "start-monitor") startMonitor();
    if (action === "start-caption") startCaptioning();
    if (action === "start-playback") startPlaybackSimulation();
    if (action === "use-fallback") useFallback();
    if (action === "save-admin-settings") saveAdminSettings();
    if (action === "trigger-manual-ingest") triggerManualIngest();
    if (action === "run-auto-discovery") runAutoDiscovery();
    if (action === "clear-log") clearLog();
    if (action === "mark-segment") markCurrentSegment();
    if (action === "lock-segment") lockCurrentSegment();
    if (action === "toggle-stream") toggleStream(control);
    if (action === "toggle-sidebar") toggleSidebar();
    if (action === "select-tab") selectTab(control.dataset.tab);
    if (action === "apply-offset") applyOffset();
    if (action === "freeze-review") freezeReview();
    if (action === "export-vtt") exportCaptions("vtt");
    if (action === "export-srt") exportCaptions("srt");
    if (action === "return-live") returnToLive();
  }

  function selectService(service) {
    state.selectedService = service;
    state.sourceReady = false;
    syncServiceButtons();
    const label = serviceLabel(service);
    log(`已切换监控场次：${label}。`);
    if (state.monitoring) {
      startMonitor();
    }
  }

  function syncServiceButtons() {
    document.querySelectorAll("[data-action='select-service']").forEach((button) => {
      const active = button.dataset.service === state.selectedService;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-selected", String(active));
      button.setAttribute("aria-pressed", String(active));
    });
  }

  function startMonitor() {
    saveAdminSettings({ quiet: true });
    clearMonitorTimers();
    state.monitoring = true;
    state.fallback = state.selectedService === "1000" || state.selectedService === "manual";
    state.frozen = false;
    state.sourceReady = false;
    const label = serviceLabel(state.selectedService);
    setStatus(`监控中 ${label}`, "watching");
    setSla("等待会前字幕源", "warning");
    el.sessionLabel.textContent = `Session: monitor-${state.selectedService}`;
    updateSourceCards("checking");
    log(`开始监控 ${label} 直播源，用于提前准备 11:30 会众字幕。`);

    state.monitorTimers.push(window.setTimeout(() => {
      setSourceState("mariners-online", "checking", "探测中");
      setSourceState("youtube-streams", "checking", "探测中");
      log("正在检查 Mariners Online 和 YouTube streams。");
    }, 450));

    state.monitorTimers.push(window.setTimeout(() => {
      if (state.selectedService === "manual") {
        confirmManualLiveSource();
        return;
      }
      if (state.selectedService === "830") {
        failPrimaryAndFallback();
        return;
      }
      confirmLiveSource(state.selectedService);
    }, 1400));
  }

  function failPrimaryAndFallback() {
    setSourceState("mariners-online", "error", "8:30 失败");
    setSourceState("youtube-streams", "warning", "同篇未确认");
    setSourceState("operator-audio", "idle", "可备用");
    setStatus("8:30 未确认，转 10:00", "warning");
    setSla("兜底准备 11:30 字幕", "warning");
    log("8:30 live source 未通过同篇证道 gate，自动切换到 10:00 兜底，确保 11:30 会众仍有字幕。");
    state.selectedService = "1000";
    state.fallback = true;
    syncServiceButtons();

    state.monitorTimers.push(window.setTimeout(() => {
      setSourceState("mariners-online", "checking", "10:00 探测中");
      setSourceState("youtube-streams", "checking", "10:00 探测中");
      log("正在检查 10:00 Mariners Online 和 YouTube streams。");
    }, 450));

    state.monitorTimers.push(window.setTimeout(() => {
      confirmLiveSource("1000");
    }, 1200));
  }

  function confirmLiveSource(service) {
    const label = serviceLabel(service);
    state.selectedService = service;
    state.sourceReady = true;
    syncServiceButtons();
    setSourceState("mariners-online", "live", "可接入");
    setSourceState("youtube-streams", "warning", "候选");
    setSourceState("operator-audio", "idle", "可备用");
    setStatus(`${label} 源已确认`, "ready");
    setSla(service === "830" ? "8:30 准备余量最大" : "10:00 可准备会众字幕", "ready");
    log(`${label} live source 已确认，可以开始生成 11:30 会众可用字幕。`);
    if (state.captionRequested) {
      state.captionRequested = false;
      startCaptioning();
    }
  }

  function confirmManualLiveSource() {
    saveAdminSettings({ quiet: true });
    const url = state.adminSettings.manualLiveUrl;
    if (!isProbablyUrl(url)) {
      useOperatorAudio();
      log("手动模式没有可用直播链接，已降级为 operator audio 兜底。");
      return;
    }

    state.selectedService = "manual";
    state.sourceReady = true;
    state.fallback = false;
    syncServiceButtons();
    setSourceState("mariners-online", "warning", "手动跳过");
    setSourceState("youtube-streams", "live", "手动链接");
    setSourceState("operator-audio", "idle", "可备用");
    setStatus("手动直播链接已确认", "ready");
    setSla("快速定位证道开始", "ready");
    updateCaptureMode("manual");
    updateSermonMeta({
      title: "手动 live archive / live source",
      meta: `${url} · 大致开始 ${state.adminSettings.approxStartTime || "待自动判断"}`,
      status: "待生成",
      tone: "ready"
    });
    log(`已确认手动直播链接：${url}${state.adminSettings.approxStartTime ? `；证道大致开始 ${state.adminSettings.approxStartTime}` : "；将自动判断证道开始" }。`);
    if (state.captionRequested) {
      state.captionRequested = false;
      startCaptioning();
    }
  }

  function startCaptioning() {
    saveAdminSettings({ quiet: true });
    if (!state.sourceReady) {
      if (state.monitoring) {
        state.captionRequested = true;
        log("会众字幕生成请求已排队，将在 live source 确认后自动启动。");
        setStatus("会众字幕待启动", "warning");
        return;
      }
      log("请先开始监控并等待 8:30/10:00 live source 确认，或选择手动音频，才能为 11:30 会众生成字幕。");
      setStatus("等待直播源确认", "error");
      return;
    }

    state.captioning = true;
    state.paused = false;
    state.frozen = false;
    stopStreamingTimers();
    state.playbackStartedAt = null;
    state.startedAt = state.startedAt || Date.now();
    setStatus("会众字幕生成中", "live");
    setSla("11:25 前发布会众视图", "live");
    el.sessionLabel.textContent = `Session: ${sessionSliceId()}-${state.selectedService}`;
    log("会众字幕 session 已启动，开始模拟低延迟字幕流。");
    scheduleNextCaption(300);
    startProgress();
  }

  function startPlaybackSimulation() {
    if (!state.playbackSegments.length) {
      log("没有可播放的直播链接模拟数据。请先运行 scripts/build_playback_simulation.py 生成 web/playback-simulation.generated.js。");
      setStatus("缺少回放数据", "error");
      return;
    }

    stopStreamingTimers();
    state.captioning = true;
    state.paused = false;
    state.frozen = false;
    state.sourceReady = true;
    state.playbackIndex = 0;
    state.segments = [];
    state.currentSegmentId = null;
    state.playbackBaseMs = state.playbackSegments[0].startMs;
    state.playbackStartedAt = Date.now();
    setSourceState("mariners-online", "live", "回放中");
    setSourceState("youtube-streams", "live", "live link");
    setSourceState("operator-audio", "idle", "可备用");
    setStatus("直播链接模拟播放", "live");
    setSla("验证 11:30 会众视图", "live");
    el.sessionLabel.textContent = `Session: playback-${sessionSliceId()}`;
    updateSermonMeta({
      title: window.SERMON_PLAYBACK_SIMULATION?.sermonTitle || "直播链接证道",
      meta: `正在根据直播链接时间轴生成字幕 · ${state.playbackSegments.length} 个候选片段`,
      status: "正在生成",
      tone: "live"
    });
    log(`开始按真实 live-aligned 时间轴模拟播放，速度 ${state.playbackSpeed}x。`);
    tickPlayback();
    startProgress();
  }

  function saveAdminSettings(options = {}) {
    const sunday = el.sundaySelect?.value || state.adminSettings.sunday;
    const manualLiveUrl = (el.manualLiveUrl?.value || "").trim();
    const approxStartTime = (el.approxStartTime?.value || "").trim();
    state.adminSettings = {
      ...state.adminSettings,
      sunday,
      manualLiveUrl,
      approxStartTime
    };
    syncAdminSettings();
    if (!options.quiet) {
      log(`Admin settings 已保存：${sunday} 周日切片${manualLiveUrl ? "；手动 live link 已设置" : "；等待自动抓取 live link"}。`);
    }
  }

  function triggerManualIngest() {
    saveAdminSettings({ quiet: true });
    state.selectedService = "manual";
    syncServiceButtons();
    updateCaptureMode("manual");
    if (!isProbablyUrl(state.adminSettings.manualLiveUrl)) {
      setStatus("需要直播链接", "error");
      setSla("手动触发未启动", "warning");
      log("手动触发需要先输入直播链接；如果现场没有链接，可以使用 operator audio 兜底。");
      return;
    }
    clearMonitorTimers();
    state.monitoring = true;
    state.sourceReady = false;
    setStatus("手动抓取中", "watching");
    setSla("定位证道开始", "warning");
    setSourceState("mariners-online", "warning", "跳过");
    setSourceState("youtube-streams", "checking", "抓取中");
    setSourceState("operator-audio", "idle", "可备用");
    el.sessionLabel.textContent = `Session: manual-${sessionSliceId()}`;
    log(`手动触发 live link ingest：${state.adminSettings.manualLiveUrl}。后端会优先使用大致开始时间定位证道。`);
    state.monitorTimers.push(window.setTimeout(confirmManualLiveSource, 800));
  }

  function runAutoDiscovery() {
    saveAdminSettings({ quiet: true });
    updateCaptureMode("automatic");
    state.selectedService = "830";
    syncServiceButtons();
    setStatus("自动抓取排程", "watching");
    setSla("周日 08:20 开始", "ready");
    el.sessionLabel.textContent = `Session: auto-${sessionSliceId()}`;
    log(`自动抓取模拟已排程：${state.adminSettings.sunday} 08:20 PT 探测 8:30，失败则 09:50 探测 10:00。`);
    startMonitor();
  }

  function tickPlayback() {
    window.clearTimeout(state.playbackTimer);
    if (!state.captioning || state.paused || state.frozen) return;

    const elapsedMs = (Date.now() - state.playbackStartedAt) * state.playbackSpeed;
    const playheadMs = state.playbackBaseMs + elapsedMs;
    let pushed = 0;
    while (
      state.playbackIndex < state.playbackSegments.length &&
      state.playbackSegments[state.playbackIndex].startMs <= playheadMs
    ) {
      pushPlaybackSegment(state.playbackSegments[state.playbackIndex]);
      state.playbackIndex += 1;
      pushed += 1;
    }

    updateTimeline(playbackProgressPercent(playheadMs));
    if (state.playbackIndex >= state.playbackSegments.length) {
      setStatus("回放模拟完成", "ready");
      setSla("可复核对齐", "ready");
      state.captioning = false;
      setGenerationStatus("可复核", "ready");
      log(`直播链接模拟播放完成，共推出 ${state.segments.length} 个片段。`);
      return;
    }

    const nextStart = state.playbackSegments[state.playbackIndex].startMs;
    const delay = Math.max(80, Math.min(1200, (nextStart - playheadMs) / state.playbackSpeed));
    state.playbackTimer = window.setTimeout(tickPlayback, pushed ? 80 : delay);
  }

  function pushPlaybackSegment(source) {
    const segment = {
      ...source,
      id: source.id || `sim_${String(state.segments.length + 1).padStart(4, "0")}`,
      locked: Boolean(source.locked),
      marked: Boolean(source.marked),
      offsetMs: Number(source.offsetMs) || 0
    };
    state.currentSegmentId = segment.id;
    state.segments.push(segment);
    el.draftCaption.textContent = segment.draft;
    el.stableCaption.textContent = segment.zh;
    el.englishSidecar.textContent = segment.en || "字幕源为中文或暂无英文 sidecar。";
    el.confidenceMeter.textContent = `${segment.confidence}%`;
    renderSegments();
    addScriptureCandidate(segment);
    updateNotes();
  }

  function scheduleNextCaption(delay) {
    window.clearTimeout(state.streamTimer);
    state.streamTimer = window.setTimeout(() => {
      if (!state.captioning || state.paused || state.frozen) return;
      pushCaption();
      scheduleNextCaption(2800);
    }, delay);
  }

  function pushCaption() {
    const item = captions[state.captionIndex % captions.length];
    const startMs = state.nextStartMs;
    const endMs = startMs + item.duration;
    const segment = {
      id: `seg_${String(state.segments.length + 1).padStart(4, "0")}`,
      startMs,
      endMs,
      zh: item.zh,
      en: item.en,
      ref: item.ref,
      note: item.note,
      confidence: item.confidence,
      locked: false,
      marked: false,
      offsetMs: 0
    };

    state.nextStartMs = endMs + 450;
    state.captionIndex += 1;
    state.currentSegmentId = segment.id;
    state.segments.push(segment);

    el.draftCaption.textContent = item.draft;
    el.stableCaption.textContent = item.zh;
    el.englishSidecar.textContent = item.en;
    el.confidenceMeter.textContent = `${item.confidence}%`;
    renderSegments();
    addScriptureCandidate(segment);
    updateNotes();
    updateTimeline();
  }

  function renderSegments() {
    const previousScrollTop = el.segmentList.scrollTop;
    const shouldFollow = state.segmentAutoFollow || segmentTrackNearBottom();
    el.segmentList.textContent = "";
    state.segments.slice(-40).forEach((segment) => {
      const item = document.createElement("li");
      item.dataset.segmentId = segment.id;
      const flags = [
        segment.locked ? "锁定" : "",
        segment.marked ? "已标记" : "",
        segment.ref ? segment.ref : ""
      ].filter(Boolean);
      item.textContent = `${msToClock(segmentStart(segment))} ${segment.zh}${flags.length ? ` (${flags.join(" / ")})` : ""}`;
      if (segment.id === state.currentSegmentId) item.classList.add("is-active");
      el.segmentList.appendChild(item);
    });
    el.segmentCount.textContent = `${state.segments.length} segments`;
    if (shouldFollow) {
      scrollSegmentTrackToLive();
    } else {
      el.segmentList.scrollTop = previousScrollTop;
    }
    updateReturnLiveButton();
  }

  function onSegmentTrackScroll() {
    if (state.segmentScrollProgrammatic) return;
    state.segmentAutoFollow = segmentTrackNearBottom();
    updateReturnLiveButton();
  }

  function onSegmentTrackClick(event) {
    const item = event.target.closest("[data-segment-id]");
    if (!item) return;
    const segment = state.segments.find((candidate) => candidate.id === item.dataset.segmentId);
    if (!segment) return;
    state.segmentAutoFollow = false;
    state.currentSegmentId = segment.id;
    el.draftCaption.textContent = segment.draft || "正在查看历史字幕片段。";
    el.stableCaption.textContent = segment.zh;
    el.englishSidecar.textContent = segment.en || "字幕源为中文或暂无英文 sidecar。";
    el.confidenceMeter.textContent = `${segment.confidence || "--"}%`;
    renderSegments();
    log(`已查看历史字幕片段 ${segment.id}；点“回到实时”恢复自动跟随。`);
  }

  function returnToLive() {
    state.segmentAutoFollow = true;
    const latest = state.segments[state.segments.length - 1];
    if (latest) {
      state.currentSegmentId = latest.id;
      el.draftCaption.textContent = latest.draft || "正在跟随实时字幕。";
      el.stableCaption.textContent = latest.zh;
      el.englishSidecar.textContent = latest.en || "字幕源为中文或暂无英文 sidecar。";
      el.confidenceMeter.textContent = `${latest.confidence || "--"}%`;
    }
    renderSegments();
    scrollSegmentTrackToLive();
    log("已回到实时字幕轨道，后续片段会自动跟随。");
  }

  function segmentTrackNearBottom() {
    const remaining = el.segmentList.scrollHeight - el.segmentList.clientHeight - el.segmentList.scrollTop;
    return remaining <= 24;
  }

  function scrollSegmentTrackToLive() {
    state.segmentScrollProgrammatic = true;
    el.segmentList.scrollTop = el.segmentList.scrollHeight;
    window.setTimeout(() => {
      state.segmentScrollProgrammatic = false;
    }, 0);
  }

  function updateReturnLiveButton() {
    const show = state.segments.length > 0 && !state.segmentAutoFollow;
    el.returnLiveButton.classList.toggle("is-hidden", !show);
  }

  function addScriptureCandidate(segment) {
    if (!segment.ref) return;
    const card = document.createElement("article");
    card.className = "scripture-card";
    card.innerHTML = `
      <span>${segment.ref.includes(":") || segment.ref.includes("Numbers") ? "Exact" : "Candidate"}</span>
      <h3>${escapeHtml(segment.ref)}</h3>
      <p>${escapeHtml(segment.note)}</p>
    `;
    el.scriptureCandidates.prepend(card);
    while (el.scriptureCandidates.children.length > 5) {
      el.scriptureCandidates.removeChild(el.scriptureCandidates.lastElementChild);
    }
  }

  function updateNotes() {
    if (!state.segments.length) return;
    const latest = state.segments[state.segments.length - 1];
    el.noteBlock.innerHTML = `
      <h3>证道笔记草稿</h3>
      <p>当前主线：${escapeHtml(latest.zh)}</p>
      <p>已积累 ${state.segments.length} 个 stable segments。离线阶段会生成摘要、大纲、应用问题和金句。</p>
    `;
  }

  function useFallback() {
    state.selectedService = "1000";
    syncServiceButtons();
    state.fallback = true;
    log("Operator 手动切换到 10:00 兜底监控。");
    startMonitor();
  }

  function useOperatorAudio() {
    clearMonitorTimers();
    state.monitoring = true;
    state.fallback = true;
    state.sourceReady = true;
    state.captionRequested = false;
    state.selectedService = "manual";
    syncServiceButtons();
    setSourceState("mariners-online", "warning", "跳过");
    setSourceState("youtube-streams", "warning", "跳过");
    setSourceState("operator-audio", "live", "使用中");
    setStatus("Operator Audio", "ready");
    setSla("兜底源可准备会众字幕", "warning");
    log("已切换到 operator audio 兜底输入，目标仍是服务 11:30 场会众。");
  }

  function markCurrentSegment() {
    const segment = currentSegment();
    if (!segment) {
      log("还没有可标记的 stable segment。");
      return;
    }
    segment.marked = !segment.marked;
    log(`${segment.id} ${segment.marked ? "已标记为 review 重点" : "已取消标记"}。`);
    renderSegments();
  }

  function lockCurrentSegment() {
    const segment = currentSegment();
    if (!segment) {
      log("还没有可锁定的 stable segment。");
      return;
    }
    segment.locked = !segment.locked;
    log(`${segment.id} ${segment.locked ? "已锁定，不再被自动覆盖" : "已解除锁定"}。`);
    renderSegments();
  }

  function toggleStream(button) {
    if (!state.captioning) {
      log("字幕流尚未启动。");
      return;
    }
    state.paused = !state.paused;
    button.classList.toggle("is-active", state.paused);
    button.setAttribute("aria-pressed", String(state.paused));
    button.textContent = state.paused ? "续" : "停";
    setStatus(state.paused ? "字幕已暂停" : "会众字幕生成中", state.paused ? "warning" : "live");
    log(state.paused ? "已暂停会众字幕流。" : "已继续会众字幕流。");
    if (!state.paused) {
      if (state.playbackSegments.length && state.playbackStartedAt) {
        tickPlayback();
      } else {
        scheduleNextCaption(400);
      }
    }
  }

  function toggleSidebar() {
    state.sidebarOpen = !state.sidebarOpen;
    el.shell.dataset.sidebar = state.sidebarOpen ? "open" : "closed";
    log(state.sidebarOpen ? "已打开经文侧栏。" : "已收起经文侧栏。");
  }

  function selectTab(tabName) {
    document.querySelectorAll("[data-action='select-tab']").forEach((button) => {
      const active = button.dataset.tab === tabName;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-selected", String(active));
    });
    document.querySelectorAll("[data-tab-panel]").forEach((panel) => {
      panel.classList.toggle("is-hidden", panel.dataset.tabPanel !== tabName);
    });
  }

  function applyOffset() {
    const value = Number(el.offsetInput.value);
    const delta = Number.isFinite(value) ? value : 0;
    if (delta === 0) {
      log("时间轴平移为 0 ms，未修改字幕片段。");
      return;
    }

    let shifted = 0;
    let skipped = 0;
    state.segments.forEach((segment) => {
      if (segment.locked) {
        skipped += 1;
        return;
      }
      segment.offsetMs += delta;
      shifted += 1;
    });
    state.offsetMs += delta;
    log(`已批量平移 ${shifted} 个片段：${delta} ms${skipped ? `；跳过 ${skipped} 个锁定片段` : ""}。`);
    renderSegments();
  }

  function freezeReview() {
    if (!state.segments.length) {
      log("还没有字幕片段，不能冻结 review。");
      return;
    }
    state.frozen = true;
    state.captioning = false;
    stopStreamingTimers();
    setStatus("会众视图已发布", "ready");
    setSla("11:30 会众可用", "ready");
    setGenerationStatus("已发布", "ready");
    log("已冻结并发布会众字幕视图；VTT/SRT 可作为兜底和归档导出。");
    updateTimeline(100);
  }

  function exportCaptions(type) {
    if (!state.segments.length) {
      log("没有可导出的字幕片段。");
      return;
    }
    const content = type === "srt" ? buildSrt() : buildVtt();
    const blob = new Blob([content], { type: type === "srt" ? "application/x-subrip;charset=utf-8" : "text/vtt;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `sermon-zh-${dateStamp()}.${type}`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 500);
    state.lastExport = { type, count: state.segments.length, frozen: state.frozen, offsetMs: state.offsetMs };
    log(`已生成 ${type.toUpperCase()} 导出文件。`);
  }

  function buildVtt() {
    const rows = ["WEBVTT", ""];
    state.segments.forEach((segment) => {
      rows.push(`${formatVttTime(segmentStart(segment))} --> ${formatVttTime(segmentEnd(segment))}`);
      rows.push(segment.zh);
      rows.push("");
    });
    return rows.join("\n");
  }

  function buildSrt() {
    const rows = [];
    state.segments.forEach((segment, index) => {
      rows.push(String(index + 1));
      rows.push(`${formatSrtTime(segmentStart(segment))} --> ${formatSrtTime(segmentEnd(segment))}`);
      rows.push(segment.zh);
      rows.push("");
    });
    return rows.join("\n");
  }

  function startProgress() {
    window.clearInterval(state.progressTimer);
    state.progressTimer = window.setInterval(() => updateTimeline(), 1000);
  }

  function updateTimeline(forcedPercent) {
    const percent = forcedPercent ?? Math.min(100, Math.max(0, state.segments.length * 12));
    document.documentElement.style.setProperty("--timeline-progress", `${percent}%`);
    document.documentElement.style.setProperty("--timeline-cursor", `${percent}%`);
    if (el.deadlineLabel) {
      el.deadlineLabel.textContent = state.frozen ? "Published: congregation view ready" : "Publish target: 11:25 PT";
    }
  }

  function playbackProgressPercent(playheadMs) {
    if (!state.playbackSegments.length) return 0;
    const first = state.playbackSegments[0].startMs;
    const last = state.playbackSegments[state.playbackSegments.length - 1].endMs;
    if (last <= first) return 0;
    return Math.min(100, Math.max(0, ((playheadMs - first) / (last - first)) * 100));
  }

  function updateSourceCards(mode) {
    const labels = {
      idle: ["待检测", "待检测", "可备用"],
      checking: ["排队", "排队", "可备用"]
    };
    const [online, youtube, audio] = labels[mode] || labels.idle;
    setSourceState("mariners-online", mode === "checking" ? "warning" : "idle", online);
    setSourceState("youtube-streams", mode === "checking" ? "warning" : "idle", youtube);
    setSourceState("operator-audio", "idle", audio);
  }

  function setSourceState(source, stateName, label) {
    const card = document.querySelector(`[data-source="${source}"]`);
    if (!card) return;
    const labelEl = card.querySelector(".source-state");
    card.dataset.state = stateName;
    card.classList.toggle("is-live", stateName === "live");
    card.classList.toggle("is-warning", stateName === "warning" || stateName === "checking");
    card.classList.toggle("is-error", stateName === "error");
    if (labelEl) labelEl.textContent = label;
  }

  function setStatus(text, tone) {
    setPill(el.sourceStatus, text, tone);
  }

  function setSla(text, tone) {
    setPill(el.slaStatus, text, tone);
  }

  function setPill(node, text, tone) {
    node.textContent = text;
    node.className = "status-pill";
    node.classList.add(`status-pill--${tone || "ready"}`);
  }

  function syncAdminSettings() {
    if (el.sundaySelect) el.sundaySelect.value = state.adminSettings.sunday;
    if (el.manualLiveUrl) el.manualLiveUrl.value = state.adminSettings.manualLiveUrl;
    if (el.approxStartTime) el.approxStartTime.value = state.adminSettings.approxStartTime;
    if (el.publicSliceLabel) el.publicSliceLabel.textContent = state.adminSettings.sunday;
    if (el.autoDiscoveryStatus) {
      el.autoDiscoveryStatus.textContent = state.adminSettings.captureMode === "manual"
        ? "手动链接优先"
        : "08:20/09:50 PT";
    }
    updateCaptureMode(state.adminSettings.captureMode);
  }

  function updateCaptureMode(mode) {
    state.adminSettings.captureMode = mode === "manual" ? "manual" : "automatic";
    if (!el.captureMode) return;
    const manual = state.adminSettings.captureMode === "manual";
    el.captureMode.textContent = manual ? "手动触发" : "自动抓取";
    el.captureMode.classList.toggle("is-manual", manual);
    if (el.autoDiscoveryStatus) {
      el.autoDiscoveryStatus.textContent = manual ? "手动链接优先" : "08:20/09:50 PT";
    }
  }

  function updateSermonMeta({ title, meta, status, tone }) {
    if (el.sermonTitle) el.sermonTitle.textContent = title || "等待直播链接";
    if (el.sermonMeta) el.sermonMeta.textContent = meta || "准备直播链接后，会在这里显示证道标题和开始时间。";
    setGenerationStatus(status || "待开始", tone || "pending");
  }

  function setGenerationStatus(text, tone) {
    if (!el.generationStatus) return;
    el.generationStatus.textContent = text;
    el.generationStatus.className = "generation-badge";
    if (tone === "live") el.generationStatus.classList.add("is-live");
    if (tone === "ready") el.generationStatus.classList.add("is-ready");
  }

  function log(message) {
    const item = document.createElement("li");
    item.textContent = `${formatClock()} ${message}`;
    el.eventLog.prepend(item);
    while (el.eventLog.children.length > 12) {
      el.eventLog.removeChild(el.eventLog.lastElementChild);
    }
  }

  function clearLog() {
    el.eventLog.textContent = "";
    log("日志已清空。");
  }

  function currentSegment() {
    return state.segments.find((segment) => segment.id === state.currentSegmentId);
  }

  function clearMonitorTimers() {
    state.monitorTimers.forEach((timer) => window.clearTimeout(timer));
    state.monitorTimers = [];
  }

  function stopStreamingTimers() {
    window.clearTimeout(state.streamTimer);
    window.clearTimeout(state.playbackTimer);
  }

  function serviceLabel(service) {
    if (service === "830") return "8:30 PT";
    if (service === "1000") return "10:00 PT";
    return state.adminSettings.manualLiveUrl ? "手动直播链接" : "手动音频";
  }

  function isProbablyUrl(value) {
    if (!value) return false;
    try {
      const parsed = new URL(value);
      return parsed.protocol === "https:" || parsed.protocol === "http:";
    } catch (_error) {
      return false;
    }
  }

  function sessionSliceId() {
    return `sunday-${state.adminSettings.sunday.replaceAll("-", "")}`;
  }

  function formatClock() {
    return new Intl.DateTimeFormat("en-US", {
      timeZone: "America/Los_Angeles",
      hour12: false,
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit"
    }).format(new Date()) + " PT";
  }

  function dateStamp() {
    const now = new Date();
    return `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, "0")}${String(now.getDate()).padStart(2, "0")}`;
  }

  function msToClock(ms) {
    const safeMs = Math.max(0, ms);
    const totalSeconds = Math.floor(safeMs / 1000);
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  }

  function segmentStart(segment) {
    return Math.max(0, segment.startMs + (segment.offsetMs || 0));
  }

  function segmentEnd(segment) {
    const duration = Math.max(300, segment.endMs - segment.startMs);
    return segmentStart(segment) + duration;
  }

  function formatVttTime(ms) {
    return formatSubtitleTime(ms, ".");
  }

  function formatSrtTime(ms) {
    return formatSubtitleTime(ms, ",");
  }

  function formatSubtitleTime(ms, separator) {
    const safeMs = Math.max(0, ms);
    const hours = Math.floor(safeMs / 3600000);
    const minutes = Math.floor((safeMs % 3600000) / 60000);
    const seconds = Math.floor((safeMs % 60000) / 1000);
    const milli = Math.floor(safeMs % 1000);
    return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}${separator}${String(milli).padStart(3, "0")}`;
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  window.SermonCaptionPrototype = {
    state,
    startMonitor,
    startCaptioning,
    startPlaybackSimulation,
    selectService,
    useFallback,
    useOperatorAudio,
    freezeReview,
    exportCaptions,
    applyOffset
  };

  init();
})();
