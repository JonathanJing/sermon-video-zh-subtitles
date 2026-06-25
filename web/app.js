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

  const fallbackScriptureReferences = {
    "Numbers 16": {
      badge: "经文",
      title: "民数记 16",
      source: "中文圣经：新标点和合本（简体） · eBible.org cmn-cu89s · Public Domain",
      summary: "可拉一党背叛，摩西与亚伦为百姓代求。系统会在实时字幕中优先固定明确经文，并显示完整章节经文。",
      passages: [
        {
          verse: "16:1-3",
          text: "可拉、大坍、亚比兰等人聚集攻击摩西、亚伦，说：“你们擅自专权！全会众个个既是圣洁，耶和华也在他们中间。”"
        },
        {
          verse: "16:20-22",
          text: "耶和华吩咐摩西和亚伦离开会众，摩西与亚伦却俯伏在地，为百姓代求。"
        },
        {
          verse: "16:31-35",
          text: "地开口吞下叛逆的人，又有火从耶和华那里出来，烧灭献香的二百五十个人。"
        },
        {
          verse: "16:46-48",
          text: "摩西吩咐亚伦拿香炉为百姓赎罪；他站在活人死人中间，瘟疫就止住了。"
        }
      ]
    },
    "Numbers 16:48": {
      badge: "经文",
      title: "民数记 16:48",
      source: "中文圣经：新标点和合本（简体） · eBible.org cmn-cu89s · Public Domain",
      summary: "亚伦为百姓赎罪；他站在活人死人中间，瘟疫就止住了。",
      passages: [
        {
          verse: "16:48",
          text: "他站在活人死人中间，瘟疫就止住了。"
        }
      ]
    }
  };
  const scriptureReferences = {
    ...fallbackScriptureReferences,
    ...((window.SERMON_SCRIPTURE_INDEX && window.SERMON_SCRIPTURE_INDEX.references) || {})
  };
  const scriptureBooks = [
    ["Genesis", "创世记"], ["Exodus", "出埃及记"], ["Leviticus", "利未记"], ["Numbers", "民数记"], ["Deuteronomy", "申命记"],
    ["Joshua", "约书亚记"], ["Judges", "士师记"], ["Ruth", "路得记"], ["1 Samuel", "撒母耳记上"], ["2 Samuel", "撒母耳记下"],
    ["1 Kings", "列王纪上"], ["2 Kings", "列王纪下"], ["1 Chronicles", "历代志上"], ["2 Chronicles", "历代志下"],
    ["Ezra", "以斯拉记"], ["Nehemiah", "尼希米记"], ["Esther", "以斯帖记"], ["Job", "约伯记"], ["Psalms", "诗篇"],
    ["Proverbs", "箴言"], ["Ecclesiastes", "传道书"], ["Song of Songs", "雅歌"], ["Isaiah", "以赛亚书"], ["Jeremiah", "耶利米书"],
    ["Lamentations", "耶利米哀歌"], ["Ezekiel", "以西结书"], ["Daniel", "但以理书"], ["Hosea", "何西阿书"], ["Joel", "约珥书"],
    ["Amos", "阿摩司书"], ["Obadiah", "俄巴底亚书"], ["Jonah", "约拿书"], ["Micah", "弥迦书"], ["Nahum", "那鸿书"],
    ["Habakkuk", "哈巴谷书"], ["Zephaniah", "西番雅书"], ["Haggai", "哈该书"], ["Zechariah", "撒迦利亚书"],
    ["Malachi", "玛拉基书"], ["Matthew", "马太福音"], ["Mark", "马可福音"], ["Luke", "路加福音"], ["John", "约翰福音"],
    ["Acts", "使徒行传"], ["Romans", "罗马书"], ["1 Corinthians", "哥林多前书"], ["2 Corinthians", "哥林多后书"],
    ["Galatians", "加拉太书"], ["Ephesians", "以弗所书"], ["Philippians", "腓立比书"], ["Colossians", "歌罗西书"],
    ["1 Thessalonians", "帖撒罗尼迦前书"], ["2 Thessalonians", "帖撒罗尼迦后书"], ["1 Timothy", "提摩太前书"],
    ["2 Timothy", "提摩太后书"], ["Titus", "提多书"], ["Philemon", "腓利门书"], ["Hebrews", "希伯来书"],
    ["James", "雅各书"], ["1 Peter", "彼得前书"], ["2 Peter", "彼得后书"], ["1 John", "约翰一书"],
    ["2 John", "约翰二书"], ["3 John", "约翰三书"], ["Jude", "犹大书"], ["Revelation", "启示录"]
  ].map(([book, bookZh]) => ({ book, bookZh }));
  const scriptureAliases = buildScriptureAliases();

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
    scriptureKeys: new Set(),
    scriptureFetches: new Set(),
    segmentAutoFollow: true,
    segmentScrollProgrammatic: false,
    viewMode: "congregation",
    adminSettings: {
      sunday: "2026-06-21",
      manualLiveUrl: "",
      approxStartTime: "",
      captureMode: "automatic"
    },
    adminStatus: null
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
    offsetInput: document.getElementById("offsetInput"),
    adminSunday: document.getElementById("adminSunday"),
    adminManifestStatus: document.getElementById("adminManifestStatus"),
    adminManifestDetail: document.getElementById("adminManifestDetail"),
    adminCaptionStatus: document.getElementById("adminCaptionStatus"),
    adminCaptionDetail: document.getElementById("adminCaptionDetail"),
    adminReadyTime: document.getElementById("adminReadyTime"),
    adminUpdatedAt: document.getElementById("adminUpdatedAt"),
    adminBucket: document.getElementById("adminBucket"),
    adminPrefix: document.getElementById("adminPrefix"),
    adminProvider: document.getElementById("adminProvider"),
    adminDeadline: document.getElementById("adminDeadline"),
    adminSecretStatus: document.getElementById("adminSecretStatus"),
    pipelineSummary: document.getElementById("pipelineSummary"),
    pipelineList: document.getElementById("pipelineList"),
    evidenceTriggered: document.getElementById("evidenceTriggered"),
    evidenceWorker: document.getElementById("evidenceWorker"),
    evidenceReady: document.getElementById("evidenceReady"),
    evidencePageViews: document.getElementById("evidencePageViews"),
    evidenceDevices: document.getElementById("evidenceDevices")
  };

  function init() {
    configureViewMode();
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
    if (el.segmentList) {
      el.segmentList.addEventListener("scroll", onSegmentTrackScroll, { passive: true });
      el.segmentList.addEventListener("click", onSegmentTrackClick);
    }
    if (el.clock) {
      el.clock.textContent = formatClock();
      state.clockTimer = window.setInterval(() => {
        el.clock.textContent = formatClock();
      }, 1000);
    }
    setStatus("等待监控", "watching");
    setSla("11:30 会众可用", "ready");
    log(state.viewMode === "admin"
      ? "管理端已就绪：检查 11:30 会众字幕生成状态，并保留手动触发入口。"
      : "会众页已就绪：正在加载本周日可用中文字幕。");
    loadPlaybackSimulation();
    syncAdminSettings();
    updateSourceCards("idle");
    updateTimeline();
    loadPublicPublishedSnapshot();
    if (state.viewMode === "admin") {
      refreshAdminStatus();
      updatePipelineForState("idle");
      updateAdminEvidence("pageView", "管理端访问记录已启用；会众访问会记录为 congregation_page_view。");
    }
    reportPageView();
  }

  function configureViewMode() {
    const params = new URLSearchParams(window.location.search);
    const modeParam = (params.get("mode") || "").toLowerCase();
    const path = window.location.pathname.toLowerCase();
    state.viewMode = path.endsWith("/admin") || path.endsWith("/admin/") || path.endsWith("/admin.html") || modeParam === "admin"
      ? "admin"
      : "congregation";
    el.shell.dataset.viewMode = state.viewMode;
    document.title = state.viewMode === "admin"
      ? "管理端 | 11:30 会众中文字幕"
      : "11:30 会众中文字幕";
  }

  function loadPublicPublishedSnapshot() {
    if (state.viewMode !== "congregation") return;
    if (!state.playbackSegments.length) return;
    stopStreamingTimers();
    state.captioning = false;
    state.paused = false;
    state.frozen = false;
    state.sourceReady = true;
    state.playbackIndex = state.playbackSegments.length;
    state.segments = state.playbackSegments.map((segment) => ({
      ...segment,
      locked: Boolean(segment.locked),
      marked: Boolean(segment.marked),
      offsetMs: Number(segment.offsetMs) || 0
    }));

    const latest = state.segments[state.segments.length - 1];
    if (!latest) return;
    state.currentSegmentId = latest.id;
    setCaptionWindow(latest);
    setEnglishSidecar(latest.en || "字幕源为中文，暂无英文原文。", latest.confidence);
    setStatus("字幕已加载", "ready");
    setSla("11:30 会众视图", "ready");
    updateSermonMeta({
      title: window.SERMON_PLAYBACK_SIMULATION?.sermonTitle || "直播链接证道",
      meta: "正在显示本周日发布的中文字幕",
      status: "已加载",
      tone: "ready"
    });
    renderSegments();
    state.segments.forEach(addScriptureCandidate);
    updateNotes();
    updateTimeline(100);
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

    const liveTitle = simulation.live?.title || "直播归档";
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
    const refs = normalizeSegmentReferences(segment, [en, zh, segment.draft, segment.text]);
    return {
      id: segment.id || `sim_${String(index + 1).padStart(4, "0")}`,
      startMs,
      endMs,
      zh: zh || "AI 中文待生成",
      draft: String(segment.draft || zh || "正在生成中文字幕..."),
      en,
      ref: refs[0]?.canonicalRef || segment.ref || "",
      refs,
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
    if (el.sessionLabel) el.sessionLabel.textContent = `任务：监控 ${state.selectedService}`;
    updateSourceCards("checking");
    updatePipelineForState("source");
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
    log("8:30 直播源未通过同篇证道检查，自动切换到 10:00 兜底，确保 11:30 会众仍有字幕。");
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
    updatePipelineStage("source-discovery", "done", "已确认");
    updatePipelineStage("live-capture", "active", "可接入");
    log(`${label} 直播源已确认，可以开始生成 11:30 会众可用字幕。`);
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
      log("手动模式没有可用直播链接，已降级为现场音频兜底。");
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
    updatePipelineStage("source-discovery", "done", "手动链接");
    updatePipelineStage("live-capture", "active", "抓取中");
    updateSermonMeta({
      title: "手动直播链接",
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
        log("会众字幕生成请求已排队，将在直播源确认后自动启动。");
        setStatus("会众字幕待启动", "warning");
        return;
      }
      log("请先开始监控并等待 8:30/10:00 直播源确认，或选择手动音频，才能为 11:30 会众生成字幕。");
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
    if (el.sessionLabel) el.sessionLabel.textContent = `任务：${sessionSliceId()}-${state.selectedService}`;
    updatePipelineForState("captioning");
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
    setStatus(state.viewMode === "admin" ? "直播链接模拟播放" : "字幕正在更新", "live");
    setSla(state.viewMode === "admin" ? "验证 11:30 会众视图" : "11:30 会众视图", "live");
    if (el.sessionLabel) el.sessionLabel.textContent = `任务：回放测试 ${sessionSliceId()}`;
    updatePipelineForState("captioning");
    updateSermonMeta({
      title: window.SERMON_PLAYBACK_SIMULATION?.sermonTitle || "直播链接证道",
      meta: state.viewMode === "admin"
        ? `正在根据直播链接时间轴生成字幕 · ${state.playbackSegments.length} 个候选片段`
        : "正在显示本周日发布的中文字幕",
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
      log(`管理端设置已保存：${sunday} 周日切片${manualLiveUrl ? "；手动直播链接已设置" : "；等待自动抓取直播链接"}。`);
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
      log("手动触发需要先输入直播链接；如果现场没有链接，可以使用现场音频兜底。");
      return;
    }
    clearMonitorTimers();
    state.monitoring = true;
    state.sourceReady = false;
    setStatus("手动抓取中", "watching");
    setSla("定位证道开始", "warning");
    updateAdminEvidence("triggered", "操作者已请求手动触发");
    updatePipelineForState("source");
    setSourceState("mariners-online", "warning", "跳过");
    setSourceState("youtube-streams", "checking", "抓取中");
    setSourceState("operator-audio", "idle", "可备用");
    if (el.sessionLabel) el.sessionLabel.textContent = `任务：手动链接 ${sessionSliceId()}`;
    log(`手动触发直播链接抓取：${state.adminSettings.manualLiveUrl}。后端会优先使用大致开始时间定位证道。`);
    postManualGenerateRequest();
    state.monitorTimers.push(window.setTimeout(confirmManualLiveSource, 800));
  }

  function runAutoDiscovery() {
    saveAdminSettings({ quiet: true });
    updateCaptureMode("automatic");
    state.selectedService = "830";
    syncServiceButtons();
    setStatus("自动抓取排程", "watching");
    setSla("周日 08:20 开始", "ready");
    if (el.sessionLabel) el.sessionLabel.textContent = `任务：自动抓取 ${sessionSliceId()}`;
    updateAdminEvidence("triggered", "自动抓取模拟已排程");
    log(`自动抓取模拟已排程：${state.adminSettings.sunday} 08:20 PT 探测 8:30，失败则 09:50 探测 10:00。`);
    startMonitor();
  }

  async function postManualGenerateRequest() {
    if (state.viewMode !== "admin") return;
    try {
      const response = await fetch(`/api/admin/sundays/${encodeURIComponent(state.adminSettings.sunday)}/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          triggerSource: "operator",
          liveUrl: state.adminSettings.manualLiveUrl,
          sermonStart: state.adminSettings.approxStartTime || undefined
        })
      });
      const body = await response.json().catch(() => ({}));
      if (response.ok) {
        updateAdminEvidence("triggered", `直播抓取已触发 · ${body.status || "已接收"} · ${body.sessionId || "任务待创建"}`);
        updateAdminEvidence("worker", body.prefix ? `计划写入路径：${body.prefix}` : "后台计划已接收");
        log(`后端已接收手动触发请求：${body.status || response.status}。`);
        return;
      }
      if (response.status === 401) {
        updateAdminEvidence("triggered", "后端已保护：需要操作者 token / OIDC，未执行真实触发。");
        log("后端 generate endpoint 已启用鉴权；本页没有发送 token，因此只保留本地模拟状态。");
        return;
      }
      updateAdminEvidence("triggered", `后端返回 ${response.status}: ${body.error || "请求失败"}`);
      log(`手动触发请求失败：${body.error || response.status}。`);
    } catch (error) {
      updateAdminEvidence("triggered", "无法连接后端，当前仅显示本地模拟状态。");
      log(`手动触发请求未送达：${error.message || error}。`);
    }
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
    setCaptionWindow(segment);
    setEnglishSidecar(segment.en || "字幕源为中文，暂无英文原文。", segment.confidence);
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
      refs: normalizeSegmentReferences(item, [item.en, item.zh, item.draft]),
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

    setCaptionWindow(segment);
    setEnglishSidecar(item.en, item.confidence);
    renderSegments();
    addScriptureCandidate(segment);
    updateNotes();
    updateTimeline();
  }

  function renderSegments() {
    if (!el.segmentList) return;
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
    if (el.segmentCount) {
      el.segmentCount.textContent = state.viewMode === "admin" ? `${state.segments.length} 个片段` : "已加载";
    }
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
    setCaptionWindow(segment);
    setEnglishSidecar(segment.en || "字幕源为中文，暂无英文原文。", segment.confidence);
    renderSegments();
    log(`已查看历史字幕片段 ${segment.id}；点“回到实时”恢复自动跟随。`);
  }

  function returnToLive() {
    state.segmentAutoFollow = true;
    const latest = state.segments[state.segments.length - 1];
    if (latest) {
      state.currentSegmentId = latest.id;
      setCaptionWindow(latest);
      setEnglishSidecar(latest.en || "字幕源为中文，暂无英文原文。", latest.confidence);
    }
    renderSegments();
    scrollSegmentTrackToLive();
    log("已回到实时字幕轨道，后续片段会自动跟随。");
  }

  function setCaptionWindow(segment) {
    el.draftCaption.textContent = sourceTranscriptText(segment);
    el.stableCaption.textContent = segment.zh || "等待中文字幕...";
  }

  function sourceTranscriptText(segment) {
    return segment.en || segment.draft || "等待英文听写...";
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

  function buildScriptureAliases() {
    const aliases = new Map();
    scriptureBooks.forEach(({ book, bookZh }) => {
      const values = [
        book,
        bookZh,
        book.replace(/\s+/g, ""),
        bookZh.replace(/\s+/g, "")
      ];
      values.forEach((value) => aliases.set(normalizeScriptureName(value), { book, bookZh }));
    });
    aliases.set("num", { book: "Numbers", bookZh: "民数记" });
    aliases.set("numbers", { book: "Numbers", bookZh: "民数记" });
    aliases.set("民数记", { book: "Numbers", bookZh: "民数记" });
    return aliases;
  }

  function referencesForSegment(segment) {
    const values = [
      segment?.ref,
      segment?.en,
      segment?.zh,
      segment?.draft,
      segment?.note
    ].filter(Boolean);
    const seen = new Set();
    const refs = [];
    values.forEach((value) => {
      extractScriptureRefs(String(value)).forEach((ref) => {
        if (seen.has(ref.canonicalRef)) return;
        seen.add(ref.canonicalRef);
        refs.push(ref);
      });
    });
    return refs;
  }

  function extractScriptureRefs(text) {
    const refs = [];
    scriptureBooks.forEach(({ book, bookZh }) => {
      const names = [book, bookZh, book.replace(/\s+/g, "\\s+")]
        .map(escapeRegExp)
        .map((name) => name.replaceAll("\\\\s\\+", "\\s+"));
      const pattern = new RegExp(`(?:${names.join("|")})\\s*(\\d+)(?::(\\d+)(?:-(\\d+))?)?`, "gi");
      let match;
      while ((match = pattern.exec(text))) {
        const parsed = canonicalChapterRef(`${book} ${match[1]}${match[2] ? `:${match[2]}${match[3] ? `-${match[3]}` : ""}` : ""}`);
        if (parsed) refs.push(parsed);
      }
    });
    return refs;
  }

  function canonicalChapterRef(value) {
    if (!value) return null;
    const clean = String(value).trim();
    const match = clean.match(/^(.+?)\s*(\d+)(?::(\d+)(?:-(\d+))?)?$/i);
    if (!match) return null;
    const [, rawBook, rawChapter, rawVerse] = match;
    const bookInfo = scriptureAliases.get(normalizeScriptureName(rawBook));
    if (!bookInfo) return null;
    const chapter = Number(rawChapter);
    if (!Number.isFinite(chapter)) return null;
    const canonicalRef = `${bookInfo.book} ${chapter}`;
    const title = `${bookInfo.bookZh} ${chapter}`;
    return {
      canonicalRef,
      title: rawVerse ? `${title}:${rawVerse}` : title,
      book: bookInfo.book,
      bookZh: bookInfo.bookZh,
      chapter
    };
  }

  function normalizeScriptureName(value) {
    return String(value || "").toLowerCase().replace(/\s+/g, "");
  }

  function cssEscape(value) {
    if (window.CSS && typeof window.CSS.escape === "function") {
      return window.CSS.escape(value);
    }
    return String(value).replace(/["\\]/g, "\\$&");
  }

  function escapeRegExp(value) {
    return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  function addScriptureCandidate(segment) {
    if (!el.scriptureCandidates) return;
    referencesForSegment(segment).forEach((ref) => addScriptureChapter(ref, segment));
  }

  function addScriptureChapter(ref, segment) {
    const key = ref.canonicalRef;
    if (!key || state.scriptureKeys.has(key)) return;
    state.scriptureKeys.add(key);
    const scripture = scriptureReferenceFor(ref);
    const card = document.createElement("details");
    card.className = `scripture-card${scripture ? " is-exact" : ""}`;
    card.dataset.scriptureKey = key;
    card.innerHTML = renderScriptureCard(ref, scripture, segment);
    el.scriptureCandidates.prepend(card);
    if (!scripture) refreshScriptureFromApi(ref);
  }

  function renderScriptureCard(ref, scripture, segment) {
    const title = scripture?.title || ref.title || displayReference(ref.canonicalRef);
    const source = scripture?.source || "中文圣经：新标点和合本（简体） · eBible.org cmn-cu89s · Public Domain";
    const summary = scripture?.summary || "讲道中提到的完整经文章节。";
    const timestamp = segment ? msToClock(segmentStart(segment)) : "";
    return `
      <summary>
        <span>${escapeHtml(scripture?.badge || "经文")}</span>
        <h3>${escapeHtml(title)}</h3>
        ${timestamp ? `<small>${escapeHtml(timestamp)}</small>` : ""}
      </summary>
      <div class="scripture-card-body">
        <p class="scripture-source">${escapeHtml(source)}</p>
        <p>${escapeHtml(summary)}</p>
        ${scripture ? renderScripturePassage(scripture) : '<p class="scripture-loading">正在加载这一章经文...</p>'}
      </div>
    `;
  }

  async function refreshScriptureFromApi(ref) {
    if (state.scriptureFetches.has(ref.canonicalRef)) return;
    state.scriptureFetches.add(ref.canonicalRef);
    try {
      const response = await fetch(`/api/scripture/cmn-cu89s/${encodeURIComponent(ref.book)}/${encodeURIComponent(ref.chapter)}`, {
        headers: { "Accept": "application/json" }
      });
      if (!response.ok) return;
      const payload = await response.json();
      const scripture = scriptureFromApiPayload(payload);
      if (!scripture) return;
      scriptureReferences[scripture.canonicalRef] = scripture;
      const card = findScriptureCard(scripture.canonicalRef);
      if (!card) return;
      card.classList.add("is-exact");
      card.innerHTML = renderScriptureCard(ref, scripture, null);
    } catch {
      // Static preview servers do not expose /api/scripture; keep generated fallback when present.
    }
  }

  function scriptureFromApiPayload(payload) {
    const reference = payload?.reference || {};
    const translation = payload?.translation || {};
    const verses = Array.isArray(payload?.verses) ? payload.verses : [];
    if (!reference.title || !verses.length) return null;
    return {
      badge: "经文",
      title: reference.title,
      source: `中文圣经：${translation.nameZh || "新标点和合本（简体）"} · eBible.org cmn-cu89s · ${translation.license || "Public Domain"}`,
      summary: "讲道中提到的完整经文章节。经文由 Cloud Run 后端完整 Bible index 返回。",
      canonicalRef: reference.canonicalRef,
      book: reference.book,
      bookZh: reference.bookZh,
      chapter: reference.chapter,
      verses
    };
  }

  function renderScripturePassage(scripture) {
    const passages = scripture.verses || scripture.passages || [];
    if (!passages.length) return "";
    const body = passages.map((passage) => (
      `<span><strong>${escapeHtml(passage.verse)}</strong> ${escapeHtml(passage.text)}</span>`
    )).join(" ");
    const fullClass = scripture.verses && scripture.verses.length > 8 ? " scripture-passage--full" : "";
    return `<div class="scripture-passage${fullClass}"><p>${body}</p></div>`;
  }

  function scriptureReferenceFor(ref) {
    const canonical = typeof ref === "string" ? canonicalChapterRef(ref)?.canonicalRef : ref?.canonicalRef;
    if (canonical && scriptureReferences[canonical]) return scriptureReferences[canonical];
    if (typeof ref === "string" && scriptureReferences[ref]) return scriptureReferences[ref];
    return null;
  }

  function isExactScriptureRef(ref) {
    return Boolean(canonicalChapterRef(ref));
  }

  function displayReference(ref) {
    const parsed = canonicalChapterRef(ref);
    if (parsed) return parsed.title;
    return ref;
  }

  function normalizeSegmentReferences(segment, textCandidates = []) {
    const refs = [];
    const seen = new Set();
    const add = (candidate) => {
      const parsed = normalizeScriptureRefCandidate(candidate);
      if (!parsed || seen.has(parsed.canonicalRef)) return;
      seen.add(parsed.canonicalRef);
      refs.push(parsed);
    };

    if (Array.isArray(segment?.refs)) segment.refs.forEach(add);
    if (Array.isArray(segment?.scriptureRefs)) segment.scriptureRefs.forEach(add);
    if (segment?.ref) add(segment.ref);
    textCandidates.filter(Boolean).forEach((text) => {
      detectScriptureReferencesInText(String(text)).forEach(add);
    });
    return refs;
  }

  function referencesForSegment(segment) {
    if (Array.isArray(segment.refs) && segment.refs.length) {
      return normalizeSegmentReferences(segment, []);
    }
    return normalizeSegmentReferences(segment, [segment.en, segment.zh, segment.draft, segment.text, segment.note, segment.ref]);
  }

  function normalizeScriptureRefCandidate(candidate) {
    if (!candidate) return null;
    if (typeof candidate === "object") {
      if (candidate.canonicalRef) {
        const parsed = canonicalChapterRef(candidate.canonicalRef);
        if (parsed) return { ...parsed, ...candidate, canonicalRef: parsed.canonicalRef, chapter: parsed.chapter };
      }
      if (candidate.book && candidate.chapter) {
        const book = scriptureBookFor(candidate.book);
        const chapter = parseChapterNumber(String(candidate.chapter));
        if (book && chapter) return scriptureRef(book, chapter);
      }
      return null;
    }
    return canonicalChapterRef(String(candidate));
  }

  function detectScriptureReferencesInText(text) {
    const refs = [];
    const seen = new Set();
    scriptureAliases.forEach((alias) => {
      chaptersForAlias(text, alias).forEach((chapter) => {
        const ref = scriptureRef(alias, chapter);
        if (seen.has(ref.canonicalRef)) return;
        seen.add(ref.canonicalRef);
        refs.push(ref);
      });
    });
    return refs;
  }

  function canonicalChapterRef(value) {
    const text = String(value || "").trim();
    if (!text) return null;
    const direct = detectScriptureReferencesInText(text)[0];
    return direct || null;
  }

  function scriptureRef(book, chapter) {
    return {
      canonicalRef: `${book.book} ${chapter}`,
      book: book.book,
      bookZh: book.bookZh,
      chapter,
      title: `${book.bookZh} ${chapter}`
    };
  }

  function scriptureBookFor(value) {
    const normalized = normalizeBookKey(String(value));
    return scriptureAliases.find((alias) => normalizeBookKey(alias.label) === normalized)
      || scriptureBooks.find((book) => normalizeBookKey(book.book) === normalized || normalizeBookKey(book.bookZh) === normalized)
      || null;
  }

  function buildScriptureAliases() {
    const aliases = [];
    scriptureBooks.forEach((book) => {
      aliases.push({ ...book, label: book.book });
      aliases.push({ ...book, label: book.bookZh });
    });
    [
      ["Numbers", "民数记", "Num"],
      ["Psalms", "诗篇", "Psalm"],
      ["Song of Songs", "雅歌", "Song of Solomon"],
      ["1 Corinthians", "哥林多前书", "1 Cor"],
      ["2 Corinthians", "哥林多后书", "2 Cor"],
      ["1 Thessalonians", "帖撒罗尼迦前书", "1 Thess"],
      ["2 Thessalonians", "帖撒罗尼迦后书", "2 Thess"],
      ["1 Timothy", "提摩太前书", "1 Tim"],
      ["2 Timothy", "提摩太后书", "2 Tim"],
      ["1 Peter", "彼得前书", "1 Pet"],
      ["2 Peter", "彼得后书", "2 Pet"],
      ["1 John", "约翰一书", "1 John"],
      ["2 John", "约翰二书", "2 John"],
      ["3 John", "约翰三书", "3 John"]
    ].forEach(([bookName, bookZh, label]) => {
      aliases.push({ book: bookName, bookZh, label });
    });
    return aliases.sort((a, b) => b.label.length - a.label.length);
  }

  function chaptersForAlias(text, alias) {
    const pattern = containsCjk(alias.label)
      ? new RegExp(`${escapeRegExp(alias.label)}\\s*([0-9一二两三四五六七八九十百]+)\\s*(?:章|[:：]\\s*\\d+)?`, "g")
      : new RegExp(`\\b(?:book\\s+of\\s+)?${escapeRegExp(alias.label)}\\b\\s*(?:chapter\\s+)?([0-9]+|${englishChapterWords().join("|")})(?::\\d+(?:-\\d+)?)?\\b`, "gi");
    const chapters = [];
    let match;
    while ((match = pattern.exec(text)) !== null) {
      if (!containsCjk(alias.label) && !startsWithNumber(alias.label) && precededByNumberedBook(text, match.index)) continue;
      const parsed = parseChapterNumber(match[1]);
      if (parsed) chapters.push(parsed);
    }
    return chapters;
  }

  function englishChapterWords() {
    return [
      "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
      "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
      "eighteen", "nineteen", "twenty"
    ];
  }

  function parseChapterNumber(value) {
    const text = String(value || "").trim().toLowerCase();
    if (/^\d+$/.test(text)) return Number(text);
    const wordIndex = englishChapterWords().indexOf(text);
    if (wordIndex >= 0) return wordIndex + 1;
    return chineseNumberToInt(text);
  }

  function chineseNumberToInt(value) {
    const digits = { "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9 };
    if (!value || /[^零一二两三四五六七八九十百]/.test(value)) return null;
    if (value.includes("百")) {
      const [left, right = ""] = value.split("百");
      return (digits[left] || 1) * 100 + (right ? chineseNumberToInt(right) || 0 : 0);
    }
    if (value.includes("十")) {
      const [left, right = ""] = value.split("十");
      return (digits[left] || 1) * 10 + (right ? digits[right] || 0 : 0);
    }
    return digits[value] || null;
  }

  function normalizeBookKey(value) {
    return value.toLowerCase().replace(/[\s_.-]+/g, "");
  }

  function containsCjk(value) {
    return /[\u4e00-\u9fff]/.test(value);
  }

  function startsWithNumber(value) {
    return /^[1-3]/.test(value);
  }

  function precededByNumberedBook(text, index) {
    return /\b[1-3]\s*$/.test(text.slice(Math.max(0, index - 4), index));
  }

  function findScriptureCard(key) {
    return Array.from(el.scriptureCandidates?.children || [])
      .find((card) => card.dataset.scriptureKey === key);
  }

  function escapeRegExp(value) {
    return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  function updateNotes() {
    if (!state.segments.length || !el.noteBlock) return;
    const latest = state.segments[state.segments.length - 1];
    el.noteBlock.innerHTML = `
      <h3>证道笔记草稿</h3>
      <p>当前主线：${escapeHtml(latest.zh)}</p>
      <p>已积累 ${state.segments.length} 个稳定字幕片段。离线阶段会生成摘要、大纲、应用问题和金句。</p>
    `;
  }

  function useFallback() {
    state.selectedService = "1000";
    syncServiceButtons();
    state.fallback = true;
    log("已手动切换到 10:00 兜底监控。");
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
    setStatus("现场音频兜底", "ready");
    setSla("兜底源可准备会众字幕", "warning");
    log("已切换到现场音频兜底输入，目标仍是服务 11:30 场会众。");
  }

  function markCurrentSegment() {
    const segment = currentSegment();
    if (!segment) {
      log("还没有可标记的稳定字幕片段。");
      return;
    }
    segment.marked = !segment.marked;
    log(`${segment.id} ${segment.marked ? "已标记为复核重点" : "已取消标记"}。`);
    renderSegments();
  }

  function lockCurrentSegment() {
    const segment = currentSegment();
    if (!segment) {
      log("还没有可锁定的稳定字幕片段。");
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
    button.textContent = state.paused ? "继续" : "暂停";
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
    if (!el.offsetInput) return;
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
      log("还没有字幕片段，不能冻结会众版本。");
      return;
    }
    state.frozen = true;
    state.captioning = false;
    stopStreamingTimers();
    setStatus("会众视图已发布", "ready");
    setSla("11:30 会众可用", "ready");
    setGenerationStatus("已发布", "ready");
    updatePipelineForState("ready");
    updateAdminEvidence("ready", `字幕已发布 · ${state.adminSettings.sunday} · ${formatClock()}`);
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
      el.deadlineLabel.textContent = state.frozen
        ? "已发布：会众页面可用"
        : "目标：11:30 PT 可用 · 最晚 11:50 PT";
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
    if (!node) return;
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
    updateAdminStatusSummary();
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
    if (!el.eventLog) return;
    const item = document.createElement("li");
    item.textContent = `${formatClock()} ${message}`;
    el.eventLog.prepend(item);
    while (el.eventLog.children.length > 12) {
      el.eventLog.removeChild(el.eventLog.lastElementChild);
    }
  }

  function clearLog() {
    if (!el.eventLog) return;
    el.eventLog.textContent = "";
    log("日志已清空。");
  }

  async function refreshAdminStatus() {
    try {
      const response = await fetch("/api/admin/status", { headers: { "Accept": "application/json" } });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      state.adminStatus = await response.json();
      if (state.adminStatus?.sunday) {
        state.adminSettings.sunday = state.adminStatus.sunday;
      }
      updateAdminStatusSummary();
      log("已读取后端管理状态摘要。");
    } catch (error) {
      state.adminStatus = {
        artifact: { manifestStatus: "unavailable", manifestError: error.message || String(error) },
        captions: { translationStatus: "unknown" },
        settings: { provider: "openai", readinessDeadline: "11:50 PT" },
        secrets: { openaiApiKey: "unknown", operatorAdminToken: "unknown", internalTaskToken: "unknown" }
      };
      updateAdminStatusSummary();
      log(`管理状态读取失败：${error.message || error}。`);
    }
  }

  function updateAdminStatusSummary() {
    if (state.viewMode !== "admin") return;
    const status = state.adminStatus || {};
    const artifact = status.artifact || {};
    const captionsStatus = status.captions || {};
    const settings = status.settings || {};
    const secrets = status.secrets || {};
    const sunday = status.sunday || state.adminSettings.sunday;
    setOptionalText(el.adminSunday, sunday || "--");
    setOptionalText(el.adminManifestStatus, statusLabel(artifact.manifestStatus || "unchecked"));
    setOptionalText(el.adminManifestDetail, artifact.manifestError
      ? `读取失败：${artifact.manifestError}`
      : `${artifact.artifactCount || 0} 个会众页面文件`);
    setOptionalText(el.adminCaptionStatus, statusLabel(captionsStatus.translationStatus || "unknown"));
    setOptionalText(el.adminCaptionDetail, captionCountText(captionsStatus));
    setOptionalText(el.adminReadyTime, captionsStatus.readyTime || "待发布");
    setOptionalText(el.adminUpdatedAt, `最后更新 ${captionsStatus.lastUpdated || formatClock()}`);
    setOptionalText(el.adminBucket, artifact.bucket || "未配置");
    setOptionalText(el.adminPrefix, artifact.prefix || "sundays");
    setOptionalText(el.adminProvider, providerLabel(settings.provider || "openai"));
    setOptionalText(el.adminDeadline, settings.readinessDeadline || "11:50 PT");
    const secretReady = secrets.openaiApiKey === "configured";
    if (el.adminSecretStatus) {
      el.adminSecretStatus.textContent = secretReady ? "OpenAI 密钥已配置" : "OpenAI 密钥缺失";
      el.adminSecretStatus.classList.toggle("is-manual", !secretReady);
    }
  }

  function captionCountText(captionsStatus) {
    const total = captionsStatus.totalSegments;
    const translated = captionsStatus.translatedSegments;
    if (Number.isFinite(total) && Number.isFinite(translated)) {
      return `${translated} / ${total} 已翻译`;
    }
    if (state.segments.length) {
      return `${state.segments.length} 个本地片段`;
    }
    return "等待发布清单回报";
  }

  function statusLabel(value) {
    const normalized = String(value || "").toLowerCase();
    const labels = {
      unchecked: "未检查",
      unavailable: "不可用",
      unknown: "未知",
      missing: "缺失",
      configured: "已配置",
      ready: "可用",
      complete: "完成",
      completed: "完成",
      pending: "等待中",
      processing: "处理中",
      running: "运行中",
      translated: "已翻译",
      needs_translation: "待翻译"
    };
    return labels[normalized] || String(value || "未知");
  }

  function providerLabel(value) {
    const normalized = String(value || "").toLowerCase();
    const labels = {
      openai: "OpenAI 翻译链路",
      google: "Google 翻译链路",
      gemini: "Gemini 翻译链路",
      manual: "手动导入"
    };
    return labels[normalized] || String(value || "未配置");
  }

  function updateAdminEvidence(kind, text) {
    const target = {
      triggered: el.evidenceTriggered,
      worker: el.evidenceWorker,
      ready: el.evidenceReady,
      pageView: el.evidencePageViews,
      devices: el.evidenceDevices
    }[kind];
    setOptionalText(target, text);
  }

  function updatePipelineForState(mode) {
    if (!el.pipelineList) return;
    const states = {
      idle: [],
      source: ["source-discovery"],
      captioning: ["source-discovery", "live-capture", "sermon-start", "transcript", "translation"],
      ready: ["source-discovery", "live-capture", "sermon-start", "transcript", "translation", "scripture", "promotion", "public-ready"]
    };
    const done = new Set(states[mode] || []);
    el.pipelineList.querySelectorAll("[data-stage]").forEach((item) => {
      const active = mode === "source" && item.dataset.stage === "source-discovery"
        || mode === "captioning" && item.dataset.stage === "translation";
      const completed = done.has(item.dataset.stage) && !active;
      item.dataset.state = completed ? "done" : active ? "active" : "waiting";
      const label = item.querySelector("em");
      if (label) label.textContent = completed ? "完成" : active ? "进行中" : "等待";
    });
    setOptionalText(el.pipelineSummary, mode === "ready" ? "可用" : mode === "captioning" ? "生成中" : mode === "source" ? "找源中" : "等待");
  }

  function updatePipelineStage(stage, stateName, labelText) {
    const item = el.pipelineList?.querySelector(`[data-stage="${stage}"]`);
    if (!item) return;
    item.dataset.state = stateName;
    const label = item.querySelector("em");
    if (label) label.textContent = labelText;
  }

  function setOptionalText(node, value) {
    if (node) node.textContent = value;
  }

  function setEnglishSidecar(text, confidence) {
    if (el.englishSidecar) el.englishSidecar.textContent = text;
    if (el.confidenceMeter) el.confidenceMeter.textContent = `${confidence || "--"}%`;
  }

  function reportPageView() {
    const payload = {
      anonymousDeviceId: anonymousDeviceId(),
      visitId: visitId(),
      sunday: state.adminSettings.sunday,
      viewMode: state.viewMode,
      path: window.location.pathname,
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      language: navigator.language,
      viewport: {
        width: window.innerWidth,
        height: window.innerHeight,
        devicePixelRatio: window.devicePixelRatio || 1
      },
      screen: {
        width: window.screen?.width,
        height: window.screen?.height
      }
    };
    const body = JSON.stringify(payload);
    if (navigator.sendBeacon) {
      const blob = new Blob([body], { type: "application/json" });
      if (navigator.sendBeacon("/api/telemetry/page-view", blob)) return;
    }
    fetch("/api/telemetry/page-view", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
      keepalive: true
    }).catch(() => {});
  }

  function anonymousDeviceId() {
    const key = "sermonCaptionAnonymousDeviceId";
    try {
      const existing = window.localStorage.getItem(key);
      if (existing) return existing;
      const created = `dev_${randomId()}`;
      window.localStorage.setItem(key, created);
      return created;
    } catch {
      return `dev_${randomId()}`;
    }
  }

  function visitId() {
    const key = "sermonCaptionVisitId";
    try {
      const existing = window.sessionStorage.getItem(key);
      if (existing) return existing;
      const created = `visit_${randomId()}`;
      window.sessionStorage.setItem(key, created);
      return created;
    } catch {
      return `visit_${randomId()}`;
    }
  }

  function randomId() {
    if (window.crypto?.randomUUID) return window.crypto.randomUUID();
    return `${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 12)}`;
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
    return `周日-${state.adminSettings.sunday.replaceAll("-", "")}`;
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
