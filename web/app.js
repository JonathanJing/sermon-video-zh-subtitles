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
  const NOTE_SLICE_TARGET_MS = 5 * 60 * 1000;
  const NOTE_SLICE_MAX_CHARS = 900;
  const NOTE_SLICE_MIN_CHARS = 120;
  const NOTE_PREVIEW_MAX_CHARS = 120;
  const NOTE_AI_CONFIG = Object.freeze({
    provider: "openai",
    model: "gpt-5.4-mini",
    displayName: "OpenAI GPT-5.5 mini",
    reasoningEffort: "medium"
  });
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
    rawSegments: [],
    reviewSegments: [],
    monitorTimers: [],
    streamTimer: null,
    playbackTimer: null,
    clockTimer: null,
    progressTimer: null,
    adminProgressTimer: null,
    livePlaybackTimer: null,
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
      sunday: "2026-06-25",
      manualLiveUrl: "https://www.youtube.com/watch?v=A__MCqbAKYc",
      approxStartTime: "17:08",
      approxEndTime: "49:15",
      captureMode: "automatic"
    },
    adminStatus: null,
    adminProgress: null,
    livePlayback: null,
    livePlaybackFetchedAt: null,
    livePlaybackAppliedMode: "",
    testRun: null,
    micStream: null,
    recognition: null,
    micTranscriptIndex: 0,
    realtime: null,
    realtimeEventSource: null
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
    approxEndTime: document.getElementById("approxEndTime"),
    autoDiscoveryStatus: document.getElementById("autoDiscoveryStatus"),
    publicSliceLabel: document.getElementById("publicSliceLabel"),
    captionWindow: document.getElementById("captionWindow"),
    draftCaption: document.getElementById("draftCaption"),
    stableCaption: document.getElementById("stableCaption"),
    nextCaption: document.getElementById("nextCaption"),
    currentEnglishCaption: document.getElementById("currentEnglishCaption"),
    englishSidecar: document.getElementById("englishSidecar"),
    confidenceMeter: document.getElementById("confidenceMeter"),
    sermonTitle: document.getElementById("sermonTitle"),
    sermonMeta: document.getElementById("sermonMeta"),
    generationStatus: document.getElementById("generationStatus"),
    segmentList: document.getElementById("segmentList"),
    segmentCount: document.getElementById("segmentCount"),
    segmentCountNote: document.getElementById("segmentCountNote"),
    segmentCoverage: document.getElementById("segmentCoverage"),
    returnLiveButton: document.getElementById("returnLiveButton"),
    scriptureCandidates: document.getElementById("scriptureCandidates"),
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
    evidenceDevices: document.getElementById("evidenceDevices"),
    testReadiness: document.getElementById("testReadiness"),
    latencyMode: document.getElementById("latencyMode"),
    latencyCaptureStart: document.getElementById("latencyCaptureStart"),
    latencyFirstEnglish: document.getElementById("latencyFirstEnglish"),
    latencyFirstChinese: document.getElementById("latencyFirstChinese"),
    latencyMedian: document.getElementById("latencyMedian"),
    latencyWorst: document.getElementById("latencyWorst"),
    latencySegments: document.getElementById("latencySegments"),
    latencyPassState: document.getElementById("latencyPassState"),
    latencyNote: document.getElementById("latencyNote"),
    cloudRunTestState: document.getElementById("cloudRunTestState"),
    cloudRunTestDate: document.getElementById("cloudRunTestDate"),
    cloudRunTestResult: document.getElementById("cloudRunTestResult"),
    cloudRunPublicLink: document.getElementById("cloudRunPublicLink"),
    cloudRunAdminLink: document.getElementById("cloudRunAdminLink"),
    livePlaybackStatus: document.getElementById("livePlaybackStatus")
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
        loadCloudRunDatePlayback(state.adminSettings.sunday);
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
    applyDateFromRoute();
    loadPlaybackSimulation();
    syncAdminSettings();
    updateSourceCards("idle");
    updateTimeline();
    loadPublicPublishedSnapshot();
    loadCloudRunDatePlayback(state.viewMode === "admin" ? state.adminSettings.sunday : (targetDateFromRoute() || "current"));
    startLivePlaybackPolling();
    if (state.viewMode === "admin") {
      refreshAdminStatus();
      startAdminProgressPolling();
      updatePipelineForState(state.segments.length ? "ready" : "idle");
      updateAdminEvidence("pageView", "管理端访问记录已启用；会众访问会记录为 congregation_page_view。");
    } else {
      connectPublicRealtimeEvents();
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

  function applyDateFromRoute() {
    const targetDate = targetDateFromRoute();
    if (!targetDate) return;
    state.adminSettings.sunday = targetDate;
    if (el.publicSliceLabel) el.publicSliceLabel.textContent = targetDate;
  }

  function targetDateFromRoute() {
    const params = new URLSearchParams(window.location.search);
    const queryDate = params.get("sunday") || params.get("date");
    if (isIsoDate(queryDate)) return queryDate;
    const match = window.location.pathname.match(/\/sundays\/(\d{4}-\d{2}-\d{2})(?:\/|$)/);
    return match ? match[1] : "";
  }

  function currentIsoDate() {
    const formatter = new Intl.DateTimeFormat("en-CA", {
      timeZone: "America/Los_Angeles",
      year: "numeric",
      month: "2-digit",
      day: "2-digit"
    });
    const parts = Object.fromEntries(formatter.formatToParts(new Date()).map((part) => [part.type, part.value]));
    return `${parts.year}-${parts.month}-${parts.day}`;
  }

  function isIsoDate(value) {
    return /^\d{4}-\d{2}-\d{2}$/.test(String(value || ""));
  }

  function loadPublicPublishedSnapshot() {
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
    renderDefaultScriptureCard();
    state.segments.forEach(addScriptureCandidate);
    updateNotes();
    updateTimeline(100);
  }

  async function loadCloudRunDatePlayback(dateOverride = "") {
    const targetDate = dateOverride || targetDateFromRoute();
    if (!targetDate) return;
    if (state.viewMode === "admin" && !state.segments.length) {
      setCaptionEmptyState(`正在读取 ${targetDate} 日期页面的已发布字幕...`);
    }
    try {
      const sliceResponse = await fetch(`/api/sundays/${encodeURIComponent(targetDate)}`, { cache: "no-store" });
      if (!sliceResponse.ok) throw new Error(`日期页面清单读取失败：HTTP ${sliceResponse.status}`);
      const slice = await sliceResponse.json();
      const playbackArtifact = (slice.artifacts || []).find((item) => item.key === "playback-js");
      if (!playbackArtifact?.apiPath) throw new Error("日期页面没有 playback-js artifact");
      const playbackResponse = await fetch(playbackArtifact.apiPath, { cache: "no-store" });
      if (!playbackResponse.ok) throw new Error(`playback-js 读取失败：HTTP ${playbackResponse.status}`);
      const simulation = parsePlaybackSimulationJs(await playbackResponse.text());
      window.SERMON_PLAYBACK_SIMULATION = simulation;
      state.playbackSegments = [];
      loadPlaybackSimulation();
      loadPublicPublishedSnapshot();
      if (state.viewMode === "admin") {
        updateCloudRunTestStatus("已加载", `${targetDate} 已发布：${slice.sermonTitle || "测试字幕"}，${slice.translatedSegments || 0}/${slice.totalSegments || 0} 已翻译。`, "ready");
      }
      log(`已从 Cloud Run 日期页面加载 ${targetDate} 的发布字幕。`);
    } catch (error) {
      if (state.viewMode === "admin") {
        updateCloudRunTestStatus("未发布", `${targetDate} 还没有可读 playback-js：${error.message || error}`, "manual");
        if (!state.segments.length) {
          setCaptionEmptyState(`${targetDate} 暂无已发布字幕。请选择已发布回放日期，或用左侧链接生成测试页。`);
        }
      }
      log(`日期页面 ${targetDate} 尚未加载发布字幕：${error.message || error}。`);
    }
  }

  function loadPlaybackSimulation() {
    const simulation = window.SERMON_PLAYBACK_SIMULATION;
    if (!simulation || !Array.isArray(simulation.segments) || !simulation.segments.length) {
      log("未检测到直播链接回放数据，当前使用内置 mock 字幕流。");
      return;
    }

    const playbackSource = Array.isArray(simulation.displaySegments) && simulation.displaySegments.length
      ? simulation.displaySegments
      : simulation.segments;
    state.rawSegments = Array.isArray(simulation.rawSegments) ? simulation.rawSegments : [];
    state.reviewSegments = Array.isArray(simulation.reviewSegments) ? simulation.reviewSegments : [];
    state.playbackSegments = playbackSource
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
    const end = simulation.sermonEnd?.timecode || state.adminSettings.approxEndTime || "";
    const simulationLiveUrl = simulation.live?.url || "";
    state.adminSettings.manualLiveUrl = state.adminSettings.manualLiveUrl || simulationLiveUrl;
    state.adminSettings.approxStartTime = state.adminSettings.approxStartTime || (start !== "unknown" ? start : "");
    state.adminSettings.approxEndTime = state.adminSettings.approxEndTime || end;
    updateSermonMeta({
      title: sermonTitle,
      meta: `${simulation.live?.url || "直播链接已加载"} · 证道 ${start}${end ? `-${end}` : ""}`,
      status: "已加载",
      tone: "ready"
    });
    log(`已加载直播链接回放数据：${liveTitle}；证道 ${start}${end ? `-${end}` : ""}；${state.playbackSegments.length} 个片段。`);
    if (simulation.translationStatus === "needs_translation") {
      log("当前 POC 片段为英文字幕源，中文字幕位置将显示 AI 待生成状态，用于验证播放和对齐。");
    }
    updateSegmentCountNote();
  }

  function parsePlaybackSimulationJs(text) {
    const prefix = "window.SERMON_PLAYBACK_SIMULATION = ";
    if (!String(text || "").startsWith(prefix)) {
      throw new Error("playback-simulation.generated.js 格式不正确");
    }
    let payload = String(text).slice(prefix.length).trim();
    if (payload.endsWith(";")) payload = payload.slice(0, -1);
    return JSON.parse(payload);
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
      translationStatus: segment.translationStatus || "unknown",
      realtimeStage: segment.realtimeStage || "",
      realtimeStages: Array.isArray(segment.realtimeStages) ? segment.realtimeStages.map(String) : [],
      sourceSegmentIds: Array.isArray(segment.sourceSegmentIds) ? segment.sourceSegmentIds.map(String) : [],
      sourceCueCount: Number(segment.sourceCueCount) || 0,
      sourceCueRange: segment.sourceCueRange || ""
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
    if (action === "live-playback-start") startLivePlayback();
    if (action === "live-playback-pause") postLivePlaybackAction("pause");
    if (action === "live-playback-resume") postLivePlaybackAction("resume");
    if (action === "live-playback-end") postLivePlaybackAction("end");
    if (action === "live-playback-adjust") adjustLivePlayback(Number(control.dataset.deltaMs) || 0);
    if (action === "live-playback-jump") jumpLivePlaybackToCurrentSegment();
    if (action === "freeze-review") freezeReview();
    if (action === "export-vtt") exportCaptions("vtt");
    if (action === "export-srt") exportCaptions("srt");
    if (action === "return-live") returnToLive();
    if (action === "start-archive-latency-test") startArchiveLatencyTest();
    if (action === "start-mic-latency-test") startMicLatencyTest();
    if (action === "stop-mic-latency-test") stopMicLatencyTest("operator");
    if (action === "mark-sermon-start") markSermonStartForTest();
    if (action === "export-test-report") exportTestReport();
  }

  function selectService(service) {
    state.selectedService = service;
    state.sourceReady = false;
    syncServiceButtons();
    updateCaptureMode(service === "manual" ? "manual" : "automatic");
    const label = serviceLabel(service);
    setStatus(`已选择 ${label}`, "watching");
    setSla(service === "830" ? "优先 8:30 源" : service === "1000" ? "10:00 兜底源" : "手动链接优先", "warning");
    previewSelectedService(service);
    log(`已切换监控场次：${label}。`);
    if (state.monitoring) {
      startMonitor();
    }
  }

  function previewSelectedService(service) {
    updateSourceCards("idle");
    if (service === "830") {
      setSourceState("mariners-online", "idle", "8:30 待检查");
      setSourceState("youtube-streams", "idle", "8:30 候选");
      setSourceState("operator-audio", "idle", "可备用");
      return;
    }
    if (service === "1000") {
      setSourceState("mariners-online", "warning", "10:00 兜底");
      setSourceState("youtube-streams", "warning", "10:00 候选");
      setSourceState("operator-audio", "idle", "可备用");
      return;
    }
    setSourceState("mariners-online", "warning", "手动跳过");
    setSourceState("youtube-streams", "idle", "等待链接");
    setSourceState("operator-audio", "idle", "可备用");
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

  function startLivePlaybackPolling() {
    window.clearInterval(state.livePlaybackTimer);
    refreshLivePlayback({ quiet: true });
    state.livePlaybackTimer = window.setInterval(() => refreshLivePlayback({ quiet: true }), 1000);
  }

  async function refreshLivePlayback(options = {}) {
    const sunday = livePlaybackSunday();
    if (!sunday) return;
    try {
      const response = await fetch(`/api/sundays/${encodeURIComponent(sunday)}/live-playback`, { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const playback = await response.json();
      state.livePlayback = playback;
      state.livePlaybackFetchedAt = Date.now();
      updateLivePlaybackStatus(playback);
      applyLivePlaybackState(playback);
    } catch (error) {
      if (!options.quiet) log(`现场同步状态读取失败：${error.message || error}`);
      if (el.livePlaybackStatus) el.livePlaybackStatus.textContent = "现场同步状态未知";
    }
  }

  function applyLivePlaybackState(playback) {
    if (!playback) return;
    const previousMode = state.livePlaybackAppliedMode;
    state.livePlaybackAppliedMode = playback.mode;
    if (["idle", "ended"].includes(playback.mode)) {
      if (["live", "paused"].includes(previousMode) && state.playbackSegments.length) {
        loadPublicPublishedSnapshot();
      }
      return;
    }
    if (!["live", "paused"].includes(playback.mode) || !state.playbackSegments.length) return;
    if (!state.segments.length || state.segments.length !== state.playbackSegments.length) {
      state.segments = state.playbackSegments.map((segment) => ({ ...segment }));
    }
    const playheadMs = livePlaybackPlayheadMs(playback);
    const segment = segmentForPlayhead(playheadMs) || state.playbackSegments[0];
    if (!segment) return;
    state.currentSegmentId = segment.id;
    setCaptionWindow(segment);
    setEnglishSidecar(segment.en || "字幕源为中文，暂无英文原文。", segment.confidence);
    setStatus(playback.mode === "paused" ? "现场同步已暂停" : "现场同步播放中", playback.mode === "paused" ? "warning" : "live");
    setSla("跟随现场视频", playback.mode === "paused" ? "warning" : "live");
    setGenerationStatus(playback.mode === "paused" ? "已暂停" : "现场同步", playback.mode === "paused" ? "warning" : "live");
    updateTimeline(playbackProgressPercent(playheadMs));
    renderSegments();
  }

  function livePlaybackPlayheadMs(playback) {
    const base = Number(playback.baseCaptionMs) || 0;
    const offset = Number(playback.offsetMs) || 0;
    const serverNow = Date.parse(playback.serverNow || "");
    const startedAt = Date.parse(playback.startedAt || "");
    const pausedAt = Date.parse(playback.pausedAt || "");
    if (!Number.isFinite(startedAt)) return Math.max(0, base + offset);
    const serverElapsed = Number.isFinite(serverNow) ? Math.max(0, serverNow - startedAt) : 0;
    if (playback.mode === "paused") {
      const pausedElapsed = Number.isFinite(pausedAt) ? Math.max(0, pausedAt - startedAt) : serverElapsed;
      return Math.max(0, base + offset + pausedElapsed);
    }
    const clientElapsed = state.livePlaybackFetchedAt ? Math.max(0, Date.now() - state.livePlaybackFetchedAt) : 0;
    return Math.max(0, base + offset + serverElapsed + clientElapsed);
  }

  function segmentForPlayhead(playheadMs) {
    return state.playbackSegments.find((segment) => segment.startMs <= playheadMs && segment.endMs > playheadMs)
      || [...state.playbackSegments].reverse().find((segment) => segment.startMs <= playheadMs)
      || null;
  }

  async function startLivePlayback() {
    if (state.viewMode !== "admin") return;
    if (!state.playbackSegments.length) {
      log("没有可现场同步的已发布字幕。请先加载日期页面或生成 playback-js。");
      return;
    }
    const segment = state.playbackSegments[0];
    await postLivePlaybackAction("start", {
      baseCaptionMs: segment.startMs,
      currentSegmentId: segment.id,
      source: livePlaybackSource()
    });
  }

  async function adjustLivePlayback(deltaMs) {
    if (state.viewMode !== "admin" || !deltaMs) return;
    await postLivePlaybackAction("adjustOffset", { deltaMs });
  }

  async function jumpLivePlaybackToCurrentSegment() {
    if (state.viewMode !== "admin") return;
    const segment = currentOrFirstPlaybackSegment();
    if (!segment) {
      log("还没有可跳转的字幕片段。");
      return;
    }
    await postLivePlaybackAction("jumpToSegment", {
      baseCaptionMs: segment.startMs,
      currentSegmentId: segment.id,
      source: livePlaybackSource()
    });
  }

  async function postLivePlaybackAction(action, extra = {}) {
    if (state.viewMode !== "admin") return null;
    const sunday = livePlaybackSunday();
    const payload = { action, ...extra };
    let response = await fetch(`/api/admin/sundays/${encodeURIComponent(sunday)}/live-playback`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...adminAuthHeaders()
      },
      body: JSON.stringify(payload)
    });
    if (response.status === 401) {
      const token = requestAdminToken();
      if (token) {
        response = await fetch(`/api/admin/sundays/${encodeURIComponent(sunday)}/live-playback`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Authorization": `Bearer ${token}`
          },
          body: JSON.stringify(payload)
        });
      }
    }
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      log(`现场同步操作失败：${body.error || `HTTP ${response.status}`}`);
      return null;
    }
    state.livePlayback = body;
    state.livePlaybackFetchedAt = Date.now();
    updateLivePlaybackStatus(body);
    applyLivePlaybackState(body);
    log(`现场同步已更新：${livePlaybackActionLabel(action)}。`);
    return body;
  }

  function currentOrFirstPlaybackSegment() {
    return state.playbackSegments.find((segment) => segment.id === state.currentSegmentId)
      || state.playbackSegments[0]
      || null;
  }

  function livePlaybackSunday() {
    return state.viewMode === "admin"
      ? state.adminSettings.sunday
      : (targetDateFromRoute() || "current");
  }

  function livePlaybackSource() {
    return {
      sunday: livePlaybackSunday(),
      artifactKey: "playback-js",
      artifactDate: livePlaybackSunday()
    };
  }

  function updateLivePlaybackStatus(playback) {
    if (!el.livePlaybackStatus || !playback) return;
    const playhead = ["live", "paused"].includes(playback.mode) ? ` · ${msToClock(livePlaybackPlayheadMs(playback))}` : "";
    const offset = Number(playback.offsetMs) || 0;
    const labels = {
      idle: "现场同步未启动",
      live: `现场同步中${playhead} · offset ${offset}ms`,
      paused: `现场同步暂停${playhead} · offset ${offset}ms`,
      ended: "现场同步已结束"
    };
    el.livePlaybackStatus.textContent = labels[playback.mode] || "现场同步状态未知";
  }

  function livePlaybackActionLabel(action) {
    const labels = {
      start: "开始",
      pause: "暂停",
      resume: "继续",
      adjustOffset: "调整 offset",
      jumpToSegment: "跳到当前句",
      end: "结束"
    };
    return labels[action] || action;
  }

  function startArchiveLatencyTest() {
    if (state.viewMode !== "admin") return;
    beginTestRun("archive-link", "离线链接/回放");
    if (!state.playbackSegments.length) {
      recordTestNote("当前部署缺少 playback-simulation.generated.js 片段，无法完成离线链接回放测试。");
      updateTestPassState("失败：缺少回放数据", "error");
      setStatus("离线测试缺少数据", "error");
      return;
    }
    recordTestNote(`开始离线链接延时测试：${state.playbackSegments.length} 个片段，回放速度 ${state.playbackSpeed}x。`);
    updateAdminEvidence("triggered", `离线链接测试已启动 · ${formatClock()}`);
    startPlaybackSimulation();
  }

  async function startMicLatencyTest() {
    if (state.viewMode !== "admin") return;
    beginTestRun("ipad-mic", "iPad 麦克风实时");
    updateCaptureMode("operator-audio");
    useOperatorAudio();
    setStatus("请求麦克风权限", "watching");
    setSla("现场实时字幕测试", "live");
    recordTestNote("正在请求麦克风权限并创建 OpenAI Realtime 翻译 session；iPad Safari/Chrome 需要 HTTPS 环境。");

    try {
      await startRealtimeTranslationMicTest();
      return;
    } catch (error) {
      recordTestNote(`OpenAI Realtime 未启动，本次实时翻译测试失败；不使用浏览器本地听写代替 gpt-realtime-translate：${error.message || error}`);
      updatePipelineStage("translation", "error", "Realtime 未启动");
      updateTestPassState("失败：Realtime 翻译未启动", "error");
      setStatus("Realtime 翻译未启动", "error");
      stopMicLatencyTest("realtime-startup-failed");
    }
  }

  async function startRealtimeTranslationMicTest() {
    if (!navigator.mediaDevices?.getUserMedia || !window.RTCPeerConnection) {
      throw new Error("当前浏览器不支持 getUserMedia 或 WebRTC");
    }
    state.micStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true
      }
    });
    recordLatency("captureStart", Date.now());
    updatePipelineStage("live-capture", "done", "麦克风已接入");
    updatePipelineStage("transcript", "active", "Realtime 听写中");
    updatePipelineStage("translation", "active", "Realtime 翻译中");
    setStatus("OpenAI Realtime 翻译中", "live");
    recordTestNote("麦克风已接入，正在通过 WebRTC 发送到 gpt-realtime-translate。");

    const session = await createRealtimeSession();
    const pc = new RTCPeerConnection();
    const dataChannel = pc.createDataChannel("oai-events");
    state.micStream.getAudioTracks().forEach((track) => pc.addTrack(track, state.micStream));
    state.realtime = {
      sessionId: session.sessionId,
      eventToken: session.eventToken,
      peerConnection: pc,
      dataChannel,
      startedAt: Date.now(),
      currentSegmentId: null,
      partialZh: "",
      partialEn: "",
      backendPersistedEvents: 0,
      backendPersistFailures: 0
    };

    dataChannel.addEventListener("open", () => {
      recordTestNote("OpenAI Realtime data channel 已打开，等待中文 transcript delta。");
      updateAdminEvidence("worker", `Realtime session ${session.sessionId} 已连接`);
    });
    dataChannel.addEventListener("message", (event) => handleRealtimeDataChannelMessage(event.data));
    dataChannel.addEventListener("error", () => {
      recordTestNote("OpenAI Realtime data channel 出错。");
    });
    pc.addEventListener("connectionstatechange", () => {
      if (pc.connectionState === "connected") {
        setStatus("Realtime 翻译已连接", "live");
      }
      if (["failed", "disconnected", "closed"].includes(pc.connectionState)) {
        recordTestNote(`Realtime WebRTC 状态：${pc.connectionState}`);
      }
    });

    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    const sdpResponse = await fetch(session.webrtc.url, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${session.clientSecret.value}`,
        "Content-Type": "application/sdp"
      },
      body: offer.sdp
    });
    if (!sdpResponse.ok) {
      throw new Error(`OpenAI WebRTC SDP 交换失败：HTTP ${sdpResponse.status}`);
    }
    await pc.setRemoteDescription({ type: "answer", sdp: await sdpResponse.text() });
    log(`OpenAI Realtime 翻译 session 已启动：${session.sessionId}。`);
  }

  async function createRealtimeSession() {
    const payload = {
      sunday: state.adminSettings.sunday,
      model: "gpt-realtime-translate",
      targetLanguage: "zh",
      audioSourceKind: "ipad_mic",
      source: "ipad-mic"
    };
    let response = await fetch("/api/admin/realtime/sessions", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...adminAuthHeaders()
      },
      body: JSON.stringify(payload)
    });
    if (response.status === 401) {
      const token = requestAdminToken();
      if (token) {
        response = await fetch("/api/admin/realtime/sessions", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Authorization": `Bearer ${token}`
          },
          body: JSON.stringify(payload)
        });
      }
    }
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(body.message || body.error || `Realtime session 请求失败：HTTP ${response.status}`);
    }
    if (!body.clientSecret?.value || !body.eventToken || !body.sessionId) {
      throw new Error("Realtime session 响应缺少 client secret 或 event token");
    }
    return body;
  }

  function adminAuthHeaders() {
    try {
      const token = window.sessionStorage.getItem("sermonOperatorAdminToken");
      return token ? { "Authorization": `Bearer ${token}` } : {};
    } catch {
      return {};
    }
  }

  function requestAdminToken() {
    const token = window.prompt("请输入管理端 token，用于执行 Cloud Run 管理操作。");
    const clean = String(token || "").trim();
    if (!clean) return "";
    try {
      window.sessionStorage.setItem("sermonOperatorAdminToken", clean);
    } catch {}
    return clean;
  }

  async function startBrowserSpeechMicFallback() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!navigator.mediaDevices?.getUserMedia || !SpeechRecognition) {
      recordTestNote("当前浏览器不支持 getUserMedia 或 Web Speech Recognition，不能完成 iPad 麦克风实时测试。");
      updateTestPassState("失败：浏览器不支持听写", "error");
      setStatus("浏览器不支持麦克风听写", "error");
      return;
    }

    try {
      state.micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      recordLatency("captureStart", Date.now());
      updatePipelineStage("live-capture", "done", "麦克风已接入");
      updatePipelineStage("transcript", "active", "听写中");
      setStatus("麦克风听写中", "live");
      recordTestNote("麦克风已接入，开始听写英文并生成测试中文字幕。");

      const recognition = new SpeechRecognition();
      recognition.lang = "en-US";
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.maxAlternatives = 1;
      recognition.onresult = handleSpeechRecognitionResult;
      recognition.onerror = (event) => {
        recordTestNote(`听写错误：${event.error || "unknown"}`);
        updateTestPassState("需复测：听写错误", "warning");
      };
      recognition.onend = () => {
        if (state.testRun?.mode === "ipad-mic" && state.testRun.active && !state.paused) {
          try {
            recognition.start();
          } catch (_error) {
            recordTestNote("听写服务已停止，需手动重新开始麦克风测试。");
          }
        }
      };
      state.recognition = recognition;
      recognition.start();
    } catch (error) {
      recordTestNote(`麦克风权限或设备失败：${error.message || error}`);
      updateTestPassState("失败：麦克风不可用", "error");
      setStatus("麦克风不可用", "error");
    }
  }

  function handleRealtimeDataChannelMessage(raw) {
    let event;
    try {
      event = JSON.parse(raw);
    } catch {
      return;
    }
    const captionEvent = realtimeCaptionEventFromOpenAI(event);
    if (!captionEvent) return;
    handleRealtimeCaptionEvent(captionEvent);
    postRealtimeSessionEvent(captionEvent);
  }

  function realtimeCaptionEventFromOpenAI(event) {
    const type = String(event.type || "");
    const transcript = extractRealtimeTranscriptText(event);
    const delta = transcript.delta;
    const text = transcript.text;
    if (!text) return null;
    const isFinal = type.endsWith(".done") || type.includes("final") || type.includes("completed");
    const isInput = type.includes("input_transcript") || type.includes("input_audio_transcription");
    const isOutput = type.includes("output_transcript") || type.includes("audio_transcript") || type.includes("translation");
    if (!isInput && !isOutput) return null;
    const payload = {
      type: isInput
        ? isFinal ? "input_transcript_final" : "input_transcript_delta"
        : isFinal ? "caption_final" : "caption_delta",
      delta,
      text,
      final: isFinal,
      segmentId: realtimeSegmentIdFromOpenAI(event),
      openaiEventType: type,
      source: "openai-realtime-webrtc"
    };
    if (isInput) {
      payload.en = text;
    } else {
      payload.zh = text;
    }
    return payload;
  }

  function extractRealtimeTranscriptText(event) {
    const delta = firstRealtimeText([
      event.delta,
      event.text_delta,
      event.transcript_delta,
      event.input_transcript_delta,
      event.output_transcript_delta,
      event.input_audio_transcription_delta,
      event.audio_transcript_delta,
      event.input_transcript?.delta,
      event.output_transcript?.delta,
      event.input_audio_transcription?.delta,
      event.audio_transcript?.delta,
      ...nestedRealtimeTranscriptValues(event.input_transcript, "delta"),
      ...nestedRealtimeTranscriptValues(event.output_transcript, "delta"),
      ...nestedRealtimeTranscriptValues(event.input_audio_transcription, "delta"),
      ...nestedRealtimeTranscriptValues(event.audio_transcript, "delta"),
      ...nestedRealtimeTranscriptValues(event.part, "delta"),
      ...nestedRealtimeTranscriptValues(event.item, "delta"),
      ...nestedRealtimeTranscriptValues(event.response, "delta")
    ]);
    const finalText = firstRealtimeText([
      event.text,
      event.transcript,
      event.output_text,
      event.input_transcript,
      event.output_transcript,
      event.input_audio_transcription,
      event.audio_transcript,
      event.part?.text,
      event.part?.transcript,
      event.item?.text,
      event.item?.transcript,
      event.response?.text,
      event.response?.transcript,
      ...nestedRealtimeTranscriptValues(event.input_transcript, "text"),
      ...nestedRealtimeTranscriptValues(event.output_transcript, "text"),
      ...nestedRealtimeTranscriptValues(event.input_audio_transcription, "text"),
      ...nestedRealtimeTranscriptValues(event.audio_transcript, "text"),
      ...realtimeContentTexts(event.item?.content),
      ...realtimeOutputTexts(event.response?.output)
    ]);
    return {
      delta: delta || finalText,
      text: finalText || delta
    };
  }

  function realtimeContentTexts(content) {
    if (!Array.isArray(content)) return [];
    return content.flatMap((item) => [
      item?.text,
      item?.transcript,
      item?.input_transcript,
      item?.output_text,
      item?.output_transcript,
      item?.input_audio_transcription,
      item?.audio_transcript
    ]);
  }

  function realtimeOutputTexts(output) {
    if (!Array.isArray(output)) return [];
    return output.flatMap((item) => [
      item?.text,
      item?.transcript,
      ...realtimeContentTexts(item?.content)
    ]);
  }

  function nestedRealtimeTranscriptValues(value, mode) {
    if (!value || typeof value !== "object") return [];
    const fields = mode === "delta"
      ? ["delta", "text_delta", "transcript_delta", "input_transcript_delta", "output_transcript_delta", "input_audio_transcription_delta", "audio_transcript_delta"]
      : ["text", "transcript", "output_text", "input_transcript", "output_transcript", "input_audio_transcription", "audio_transcript"];
    const values = fields.map((field) => value?.[field]);
    if (Array.isArray(value.content)) {
      value.content.forEach((item) => values.push(...nestedRealtimeTranscriptValues(item, mode)));
    }
    if (Array.isArray(value.output)) {
      value.output.forEach((item) => values.push(...nestedRealtimeTranscriptValues(item, mode)));
    }
    return values;
  }

  function firstRealtimeText(values) {
    for (const value of values) {
      if (typeof value === "string" && value.trim()) return value.trim();
      if (typeof value === "number" && Number.isFinite(value)) return String(value);
    }
    return "";
  }

  function realtimeSegmentIdFromOpenAI(event) {
    return event.item_id
      || event.content_index
      || event.response_id
      || event.event_id
      || event.item?.id
      || event.response?.id
      || null;
  }

  function handleRealtimeCaptionEvent(event) {
    if (!event || !realtimeEventText(event)) return;
    const isInput = String(event.type || "").startsWith("input_transcript");
    const text = realtimeEventText(event);
    if (isInput) {
      updateRealtimeEnglish(text, event);
      return;
    }
    upsertRealtimeChineseSegment(text, event);
  }

  function realtimeEventText(event) {
    return String(event.text || event.delta || event.zh || event.en || event.transcript || "").trim();
  }

  function updateRealtimeEnglish(text, event) {
    if (!state.realtime) state.realtime = {};
    state.realtime.partialEn = event.final ? text : `${state.realtime.partialEn || ""}${event.delta || text}`;
    setEnglishSidecar(state.realtime.partialEn || text, event.final ? 86 : 65);
    recordLatency("firstEnglish", Date.now());
    updatePipelineStage("transcript", event.final ? "done" : "active", event.final ? "英文已确认" : "英文生成中");
  }

  function upsertRealtimeChineseSegment(text, event) {
    if (!state.realtime) state.realtime = {};
    const now = Date.now();
    const startMs = state.testRun?.startedAt ? now - state.testRun.startedAt : state.nextStartMs;
    const eventSegmentId = String(event.segmentId || "").trim();
    let segment = eventSegmentId ? state.segments.find((item) => item.id === eventSegmentId) : null;
    if (!segment) {
      segment = state.segments.find((item) => item.id === state.realtime.currentSegmentId);
    }
    if (!segment || (segment.final && !eventSegmentId)) {
      segment = {
        id: eventSegmentId || `rt_${String(state.micTranscriptIndex + 1).padStart(4, "0")}`,
        startMs,
        endMs: startMs + 2400,
        zh: "",
        en: state.realtime.partialEn || "",
        refs: [],
        note: "OpenAI Realtime WebRTC 现场麦克风翻译片段。",
        confidence: 78,
        locked: false,
        marked: false,
        offsetMs: 0,
        sourceMode: "openai-realtime",
        realtimeStage: "draft",
        final: false
      };
      state.micTranscriptIndex += 1;
      state.segments.push(segment);
      state.realtime.currentSegmentId = segment.id;
    }
    const isStableCommit = event.type === "caption_stable" || event.stability === "stable";
    const isStableCorrection = String(event.source || "").includes("stable-correction");
    const realtimeStage = isStableCorrection ? "final" : isStableCommit ? "stable" : event.final ? "final" : "draft";
    segment.zh = event.final || isStableCorrection || isStableCommit ? text : `${segment.zh || ""}${event.delta || text}`;
    segment.en = state.realtime.partialEn || segment.en || "";
    if (event.en) segment.en = event.en;
    segment.endMs = Math.max(segment.endMs, startMs + Math.max(1800, Math.min(8000, segment.zh.length * 90)));
    segment.final = Boolean(event.final || isStableCorrection);
    segment.stable = Boolean(segment.stable || isStableCorrection || isStableCommit);
    segment.realtimeStage = realtimeStage;
    appendRealtimeStage(segment, realtimeStage, event);
    if (event.stabilizerWindow && typeof event.stabilizerWindow === "object") {
      segment.stabilizerWindow = event.stabilizerWindow;
    }
    if (isStableCorrection) {
      segment.note = "gpt-5.4-mini 稳定修正版。";
      segment.confidence = Math.max(Number(segment.confidence) || 0, 88);
    } else if (isStableCommit) {
      segment.note = "Realtime 稳定字幕，等待最终轻量修正。";
      segment.confidence = Math.max(Number(segment.confidence) || 0, 84);
    }
    segment.refs = normalizeSegmentReferences(segment, [segment.en, segment.zh]);
    state.currentSegmentId = segment.id;
    setCaptionWindow(segment);
    renderSegments();
    addScriptureCandidate(segment);
    updateNotes();
    recordLatency("firstChinese", now);
    recordLatencySample(Number(event.latencyMs) || 1200);
    updatePipelineStage(
      "translation",
      event.final || isStableCorrection ? "done" : isStableCommit ? "active" : "active",
      event.final || isStableCorrection ? "中文已确认" : isStableCommit ? "中文已稳定" : "中文显示中"
    );
    setGenerationStatus("Realtime 翻译", "live");
    updateTestPassStateFromMetrics();
    if (event.final) {
      state.realtime.currentSegmentId = null;
      state.realtime.partialZh = "";
    }
  }

  function appendRealtimeStage(segment, stage, event) {
    if (!stage) return;
    const stages = Array.isArray(segment.realtimeStages) ? segment.realtimeStages : [];
    if (!stages.includes(stage)) stages.push(stage);
    segment.realtimeStages = stages;
    segment.realtimeStageEvents = Array.isArray(segment.realtimeStageEvents) ? segment.realtimeStageEvents : [];
    segment.realtimeStageEvents.push({
      stage,
      type: event.type || "",
      source: event.source || "",
      latencyMs: Number(event.latencyMs) || 0
    });
  }

  function postRealtimeSessionEvent(event) {
    const rt = state.realtime;
    if (!rt?.sessionId || !rt.eventToken) return;
    fetch(`/api/realtime/sessions/${encodeURIComponent(rt.sessionId)}/events`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Realtime-Event-Token": rt.eventToken
      },
      body: JSON.stringify(event),
      keepalive: true
    }).then((response) => {
      if (!state.realtime || state.realtime.sessionId !== rt.sessionId) return;
      if (response.ok) {
        state.realtime.backendPersistedEvents = (state.realtime.backendPersistedEvents || 0) + 1;
        state.realtime.backendPersistFailures = 0;
        if (state.realtime.backendPersistedEvents === 1 || event.final) {
          updateAdminEvidence("worker", `Realtime deltas 已保存 ${state.realtime.backendPersistedEvents} 条`);
        }
        return;
      }
      state.realtime.backendPersistFailures = (state.realtime.backendPersistFailures || 0) + 1;
      recordTestNote(`后台保存 realtime delta 失败：HTTP ${response.status}`);
      updateAdminEvidence("worker", `Realtime deltas 保存失败 HTTP ${response.status}`);
    }).catch((error) => {
      if (!state.realtime || state.realtime.sessionId !== rt.sessionId) return;
      state.realtime.backendPersistFailures = (state.realtime.backendPersistFailures || 0) + 1;
      recordTestNote(`后台保存 realtime delta 失败：${error.message || error}`);
      updateAdminEvidence("worker", "Realtime deltas 保存失败，检查后台连接");
    });
  }

  function connectPublicRealtimeEvents() {
    if (!window.EventSource || state.realtimeEventSource) return;
    const source = new EventSource("/api/realtime/sessions/current/events");
    state.realtimeEventSource = source;
    const onCaption = (event) => {
      try {
        const payload = JSON.parse(event.data);
        state.captioning = true;
        state.sourceReady = true;
        setStatus("实时字幕更新中", "live");
        setSla("现场实时字幕", "live");
        handleRealtimeCaptionEvent(payload);
      } catch (_error) {}
    };
    ["caption_delta", "caption_stable", "caption_final", "input_transcript_delta", "input_transcript_final"].forEach((type) => {
      source.addEventListener(type, onCaption);
    });
    source.onerror = () => {
      source.close();
      state.realtimeEventSource = null;
      window.setTimeout(connectPublicRealtimeEvents, 5000);
    };
  }

  function handleSpeechRecognitionResult(event) {
    let finalText = "";
    let interimText = "";
    for (let index = event.resultIndex; index < event.results.length; index += 1) {
      const result = event.results[index];
      const transcript = result[0]?.transcript || "";
      if (result.isFinal) {
        finalText += transcript;
      } else {
        interimText += transcript;
      }
    }
    const displayText = (finalText || interimText).trim();
    if (!displayText) return;
    setEnglishSidecar(displayText, finalText ? 82 : 58);
    if (!finalText) return;
    pushMicTranscriptSegment(finalText.trim());
  }

  function pushMicTranscriptSegment(text) {
    if (!text) return;
    const now = Date.now();
    const startMs = state.testRun?.startedAt ? now - state.testRun.startedAt : state.nextStartMs;
    const zh = translateForLiveTest(text);
    const segment = {
      id: `mic_${String(state.micTranscriptIndex + 1).padStart(4, "0")}`,
      startMs,
      endMs: startMs + Math.max(1800, Math.min(8000, text.length * 90)),
      zh,
      en: text,
      refs: normalizeSegmentReferences({ en: text, zh }, [text, zh]),
      note: "iPad 麦克风实时测试片段；中文为浏览器测试翻译占位，用于验证端到端延时记录。",
      confidence: 82,
      locked: false,
      marked: false,
      offsetMs: 0,
      sourceMode: "ipad-mic"
    };
    state.micTranscriptIndex += 1;
    state.currentSegmentId = segment.id;
    state.segments.push(segment);
    setCaptionWindow(segment);
    renderSegments();
    addScriptureCandidate(segment);
    updateNotes();
    recordLatency("firstEnglish", now);
    recordLatency("firstChinese", now + 250);
    recordLatencySample(250);
    updatePipelineStage("transcript", "done", "英文已出现");
    updatePipelineStage("translation", "active", "中文显示中");
    setGenerationStatus("正在生成", "live");
    updateTestPassStateFromMetrics();
    log(`麦克风听写片段 ${segment.id} 已显示，测试中文字幕延时约 0.3 秒。`);
  }

  function stopMicLatencyTest(reason = "operator") {
    stopRealtimeSession();
    if (state.recognition) {
      state.recognition.onend = null;
      try {
        state.recognition.stop();
      } catch (_error) {}
      state.recognition = null;
    }
    if (state.micStream) {
      state.micStream.getTracks().forEach((track) => track.stop());
      state.micStream = null;
    }
    if (state.testRun?.mode === "ipad-mic") {
      state.testRun.active = false;
      recordTestNote(reason === "operator" ? "操作者已停止麦克风测试。" : "麦克风测试已停止。");
      if (reason !== "realtime-startup-failed") {
        updateTestPassStateFromMetrics();
      }
    }
    if (reason === "realtime-startup-failed") {
      setStatus("Realtime 翻译未启动", "error");
    } else {
      setStatus("麦克风测试已停止", "ready");
    }
  }

  function stopRealtimeSession() {
    if (!state.realtime) return;
    try {
      state.realtime.dataChannel?.close();
    } catch (_error) {}
    try {
      state.realtime.peerConnection?.close();
    } catch (_error) {}
    state.realtime = null;
  }

  function markSermonStartForTest() {
    saveAdminSettings({ quiet: true });
    const timecode = state.adminSettings.approxStartTime || msToClock(state.playbackBaseMs || 0);
    if (!state.testRun) beginTestRun("manual-marker", "手动证道起点");
    state.testRun.sermonStartMarkedAt = Date.now();
    state.testRun.sermonStartTimecode = timecode;
    updatePipelineStage("sermon-start", "done", timecode);
    recordTestNote(`已确认证道开始：${timecode}。`);
    log(`测试记录已标注证道开始：${timecode}。`);
  }

  function saveAdminSettings(options = {}) {
    const sunday = el.sundaySelect?.value || state.adminSettings.sunday;
    const manualLiveUrl = (el.manualLiveUrl?.value || "").trim();
    const approxStartTime = (el.approxStartTime?.value || "").trim();
    const approxEndTime = (el.approxEndTime?.value || "").trim();
    state.adminSettings = {
      ...state.adminSettings,
      sunday,
      manualLiveUrl,
      approxStartTime,
      approxEndTime
    };
    syncAdminSettings();
    if (!options.quiet) {
      log(`管理端设置已保存：${sunday} 日期页面${manualLiveUrl ? "；手动直播链接已设置" : "；等待自动抓取直播链接"}。`);
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
    log(`手动触发直播链接抓取：${state.adminSettings.manualLiveUrl}。后端会优先使用证道开始/结束时间裁剪离线字幕。`);
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
    updateCloudRunTestStatus("请求中", "正在请求 Cloud Run 生成日期测试页。", "manual");
    try {
      let response = await requestManualGeneration();
      if (response.status === 401) {
        const token = requestAdminToken();
        if (token) response = await requestManualGeneration(token);
      }
      const body = await response.json().catch(() => ({}));
      if (response.ok) {
        const status = body.status || "accepted";
        updateAdminEvidence("triggered", `直播抓取已触发 · ${status} · ${body.sessionId || "任务待创建"}`);
        updateAdminEvidence("worker", body.prefix ? `计划写入路径：${body.prefix}` : "后台计划已接收");
        await refreshAdminProgress({ quiet: true });
        if (status === "completed") {
          updateCloudRunTestStatus("完成", `已发布到 ${state.adminSettings.sunday} 日期页面；用户页和 Admin 页可打开查看。`, "ready");
          updatePipelineForState("ready");
          await refreshAdminStatus();
          await loadCloudRunDatePlayback(state.adminSettings.sunday);
        } else {
          const commandCount = Array.isArray(body.commands) ? body.commands.length : body.commandCount;
          updateCloudRunTestStatus("已排程", `后端返回 ${status}；${commandCount || 0} 个 worker 步骤。若 Cloud Run 未启用 inline worker，需要用返回计划启动 Job。`, "manual");
        }
        log(`后端已接收手动触发请求：${status}。`);
        return;
      }
      if (response.status === 401) {
        updateAdminEvidence("triggered", "后端已保护：需要操作者 token / OIDC，未执行真实触发。");
        updateCloudRunTestStatus("需授权", "请输入管理端 token 后再触发生成。", "manual");
        log("后端 generate endpoint 已启用鉴权；本页没有可用 token，因此只保留本地模拟状态。");
        return;
      }
      updateAdminEvidence("triggered", `后端返回 ${response.status}: ${body.error || "请求失败"}`);
      updateCloudRunTestStatus("失败", body.error || `HTTP ${response.status}`, "manual");
      log(`手动触发请求失败：${body.error || response.status}。`);
    } catch (error) {
      updateAdminEvidence("triggered", "无法连接后端，当前仅显示本地模拟状态。");
      updateCloudRunTestStatus("未送达", error.message || String(error), "manual");
      log(`手动触发请求未送达：${error.message || error}。`);
    }
  }

  function requestManualGeneration(token) {
    return fetch(`/api/admin/sundays/${encodeURIComponent(state.adminSettings.sunday)}/generate`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { "Authorization": `Bearer ${token}` } : adminAuthHeaders())
      },
      body: JSON.stringify({
        triggerSource: "operator-cloud-run-test",
        liveUrl: state.adminSettings.manualLiveUrl,
        sermonStart: state.adminSettings.approxStartTime || undefined,
        sermonEnd: state.adminSettings.approxEndTime || undefined,
        maxSegments: 80,
        playbackSpeed: 18
      })
    });
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
    const now = Date.now();
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
    recordLatency("firstEnglish", now);
    recordLatency("firstChinese", now);
    if (state.testRun?.mode === "archive-link" && state.playbackStartedAt) {
      const expectedAt = state.playbackStartedAt + ((segment.startMs - state.playbackBaseMs) / state.playbackSpeed);
      recordLatencySample(Math.max(0, now - expectedAt));
      updateTestPassStateFromMetrics();
    }
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
    const now = Date.now();
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
    recordLatency("firstEnglish", now);
    recordLatency("firstChinese", now + 300);
    recordLatencySample(300);
    updateTestPassStateFromMetrics();
  }

  function renderSegments() {
    if (!el.segmentList) return;
    const previousScrollTop = el.segmentList.scrollTop;
    const shouldFollow = state.segmentAutoFollow || segmentTrackNearBottom();
    el.segmentList.textContent = "";
    const reviewGroups = reviewGroupsForRender();
    reviewGroups.forEach((group) => {
      const item = document.createElement("li");
      item.dataset.segmentId = group.liveSegmentId;
      item.dataset.segmentRange = group.segmentIds.join(",");
      const flags = group.flags;
      item.innerHTML = `
        <span class="segment-time">${escapeHtml(group.timeLabel)}</span>
        <span class="segment-zh">${escapeHtml(group.zh || "等待中文字幕")}</span>
        <span class="segment-en">${escapeHtml(group.en || "暂无英文原文")}</span>
        ${flags.length ? `<small>${escapeHtml(flags.join(" / "))}</small>` : ""}
      `;
      if (group.segmentIds.includes(state.currentSegmentId)) item.classList.add("is-active");
      el.segmentList.appendChild(item);
    });
    if (el.segmentCount) {
      const rawCount = state.rawSegments.length || state.segments.length;
      el.segmentCount.textContent = state.viewMode === "admin"
        ? `${reviewGroups.length} 组 / ${rawCount} 原始 cue`
        : "已加载";
    }
    updateSegmentCountNote();
    updateSegmentCoverage(reviewGroups);
    if (shouldFollow) {
      scrollSegmentTrackToLive();
    } else {
      el.segmentList.scrollTop = previousScrollTop;
    }
    updateReturnLiveButton();
  }

  function reviewGroupsForRender() {
    if (state.reviewSegments.length) {
      const byDisplayId = new Map(state.segments.map((segment) => [segment.id, segment]));
      return state.reviewSegments
        .map((review, index) => normalizeReviewSegment(review, index, byDisplayId))
        .filter(Boolean);
    }
    return groupedReviewSegments(state.segments);
  }

  function normalizeReviewSegment(review, index, byDisplayId) {
    const displayId = String(review.displaySegmentId || review.id || "");
    const display = byDisplayId.get(displayId);
    const ids = Array.isArray(review.sourceSegmentIds) ? review.sourceSegmentIds.map(String) : display?.sourceSegmentIds || [];
    const refs = Array.isArray(review.refs) ? review.refs : display?.refs || [];
    return {
      liveSegmentId: displayId || display?.id || `review_${index + 1}`,
      segmentIds: [displayId || display?.id || `review_${index + 1}`],
      sourceSegmentIds: ids,
      startMs: Number(review.startMs ?? display?.startMs ?? 0),
      endMs: Number(review.endMs ?? display?.endMs ?? 0),
      flags: [
        ids.length ? `${ids.length} 个原始 cue` : "",
        realtimeStageHistoryLabel(display?.realtimeStages || review.realtimeStages || [], display?.realtimeStage || review.realtimeStage || ""),
        ...refs.map((ref) => ref?.canonicalRef || "").filter(Boolean)
      ].filter(Boolean),
      zh: review.zh || display?.zh || "",
      en: review.en || display?.en || "",
      timeLabel: `${msToClock(Number(review.startMs ?? display?.startMs ?? 0))}-${msToClock(Number(review.endMs ?? display?.endMs ?? 0))}`,
    };
  }

  function groupedReviewSegments(segments) {
    const groups = [];
    let current = null;
    segments
      .slice()
      .sort((a, b) => segmentStart(a) - segmentStart(b))
      .forEach((segment) => {
        if (!current) {
          current = createReviewGroup(segment);
          return;
        }
        if (shouldStartReviewGroup(current, segment)) {
          groups.push(finalizeReviewGroup(current));
          current = createReviewGroup(segment);
          return;
        }
        addSegmentToReviewGroup(current, segment);
      });
    if (current) groups.push(finalizeReviewGroup(current));
    return groups;
  }

  function createReviewGroup(segment) {
    return {
      startMs: segmentStart(segment),
      endMs: segmentEnd(segment),
      zhParts: [segment.zh || ""].filter(Boolean),
      enParts: [segment.en || ""].filter(Boolean),
      refs: new Set(segment.ref ? [segment.ref] : []),
      realtimeStage: segment.realtimeStage || (segment.final ? "final" : segment.stable ? "stable" : ""),
      realtimeStages: Array.isArray(segment.realtimeStages) ? segment.realtimeStages.slice() : [],
      marked: Boolean(segment.marked),
      locked: Boolean(segment.locked),
      segmentIds: [segment.id],
      liveSegmentId: segment.id
    };
  }

  function addSegmentToReviewGroup(group, segment) {
    group.endMs = Math.max(group.endMs, segmentEnd(segment));
    if (segment.zh) group.zhParts.push(segment.zh);
    if (segment.en) group.enParts.push(segment.en);
    if (segment.ref) group.refs.add(segment.ref);
    group.realtimeStage = strongestRealtimeStage(
      group.realtimeStage,
      segment.realtimeStage || (segment.final ? "final" : segment.stable ? "stable" : "")
    );
    mergeRealtimeStages(group.realtimeStages, segment.realtimeStages || []);
    group.marked = group.marked || Boolean(segment.marked);
    group.locked = group.locked || Boolean(segment.locked);
    group.segmentIds.push(segment.id);
    group.liveSegmentId = segment.id;
  }

  function finalizeReviewGroup(group) {
    const flags = [
      group.locked ? "锁定" : "",
      group.marked ? "已标记" : "",
      realtimeStageHistoryLabel(group.realtimeStages, group.realtimeStage),
      ...Array.from(group.refs)
    ].filter(Boolean);
    return {
      ...group,
      zh: compactJoinedCaption(group.zhParts),
      en: compactJoinedCaption(group.enParts),
      flags,
      timeLabel: group.endMs > group.startMs ? `${msToClock(group.startMs)}-${msToClock(group.endMs)}` : msToClock(group.startMs)
    };
  }

  function shouldStartReviewGroup(group, segment) {
    const gapMs = segmentStart(segment) - group.endMs;
    const zhText = compactJoinedCaption(group.zhParts);
    const enText = compactJoinedCaption(group.enParts);
    if (gapMs > 2600) return true;
    if (zhText.length >= 600 || enText.length >= 900) return true;
    if (group.zhParts.length >= 10) return true;
    const zhEnds = endsSentence(zhText);
    const enEnds = endsSentence(enText);
    return (zhEnds && (!enText || enEnds)) || (enEnds && (!zhText || zhEnds));
  }

  function compactJoinedCaption(parts) {
    return parts.join(" ").replace(/\s+/g, " ").replace(/\s+([，。！？；：,.!?;:])/g, "$1").trim();
  }

  function endsSentence(text) {
    return /(?:[。！？；]|\.\s*|[!?]\s*|……)$/.test(String(text || "").trim());
  }

  function realtimeStageLabel(stage) {
    if (stage === "final") return "最终";
    if (stage === "stable") return "稳定";
    if (stage === "draft") return "草稿";
    return "";
  }

  function realtimeStageHistoryLabel(stages, fallbackStage = "") {
    const ordered = ["draft", "stable", "final"].filter((stage) => Array.isArray(stages) && stages.includes(stage));
    if (!ordered.length && fallbackStage) ordered.push(fallbackStage);
    const labels = ordered.map(realtimeStageLabel).filter(Boolean);
    return labels.length > 1 ? labels.join(" / ") : labels[0] || "";
  }

  function mergeRealtimeStages(target, stages) {
    if (!Array.isArray(target) || !Array.isArray(stages)) return;
    ["draft", "stable", "final"].forEach((stage) => {
      if (stages.includes(stage) && !target.includes(stage)) target.push(stage);
    });
  }

  function strongestRealtimeStage(current, next) {
    const rank = { "": 0, draft: 1, stable: 2, final: 3 };
    return (rank[next] || 0) > (rank[current] || 0) ? next : current;
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
    const context = captionContextFor(segment);
    const mode = captionDisplayMode(segment);
    if (el.captionWindow) {
      el.captionWindow.dataset.contextMode = mode;
      el.captionWindow.classList.toggle("has-previous", Boolean(context.previous));
      el.captionWindow.classList.toggle("has-next", Boolean(context.next) && mode === "offline");
    }
    setCaptionLine(el.draftCaption, context.previous, "等待上一句中文字幕...");
    setCaptionLine(el.stableCaption, context.current, "等待中文字幕...");
    setCaptionLine(el.currentEnglishCaption, segment?.en || "", "Waiting for English transcript...");
    setCaptionLine(el.nextCaption, mode === "offline" ? context.next : "", "等待下一句中文字幕...");
  }

  function setCaptionEmptyState(message) {
    if (el.captionWindow) {
      el.captionWindow.dataset.contextMode = "offline";
      el.captionWindow.classList.remove("has-previous", "has-next");
    }
    setCaptionLine(el.draftCaption, "", "");
    setCaptionLine(el.stableCaption, message, message);
    setCaptionLine(el.currentEnglishCaption, "", "");
    setCaptionLine(el.nextCaption, "", "");
  }

  function captionContextFor(segment) {
    const index = state.segments.findIndex((candidate) => candidate.id === segment?.id);
    const previous = index > 0 ? state.segments[index - 1] : null;
    const next = index >= 0 && index < state.segments.length - 1 ? state.segments[index + 1] : null;
    return {
      previous: captionText(previous),
      current: captionText(segment),
      next: captionText(next)
    };
  }

  function captionDisplayMode(segment) {
    if (state.frozen || !state.captioning) return "offline";
    const index = state.segments.findIndex((candidate) => candidate.id === segment?.id);
    return index >= 0 && index < state.segments.length - 1 ? "offline" : "realtime";
  }

  function captionText(segment) {
    return segment?.zh || "";
  }

  function setCaptionLine(node, text, fallback) {
    if (!node) return;
    const display = text || fallback;
    node.textContent = display;
    node.classList.toggle("is-empty", !text);
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

  function renderDefaultScriptureCard() {
    if (!el.scriptureCandidates || el.scriptureCandidates.children.length) return;
    const ref = canonicalChapterRef("Numbers 16");
    const scripture = scriptureReferences["Numbers 16"];
    if (!ref || !scripture || state.scriptureKeys.has(ref.canonicalRef)) return;
    state.scriptureKeys.add(ref.canonicalRef);
    const card = document.createElement("details");
    card.className = "scripture-card is-exact";
    card.dataset.scriptureKey = ref.canonicalRef;
    card.open = true;
    card.innerHTML = renderScriptureCard(ref, scripture, null);
    renderScriptureSourceNote(scripture);
    el.scriptureCandidates.prepend(card);
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
    renderScriptureSourceNote(scripture);
    el.scriptureCandidates.prepend(card);
    if (!scripture) refreshScriptureFromApi(ref);
  }

  function renderScriptureCard(ref, scripture, segment) {
    const title = scripture?.title || ref.title || displayReference(ref.canonicalRef);
    const summary = displayScriptureSummary(scripture?.summary);
    const timestamp = segment ? msToClock(segmentStart(segment)) : "";
    return `
      <summary>
        <span>${escapeHtml(scripture?.badge || "经文")}</span>
        <h3>${escapeHtml(title)}</h3>
        ${timestamp ? `<small>${escapeHtml(timestamp)}</small>` : ""}
      </summary>
      <div class="scripture-card-body">
        ${summary ? `<p>${escapeHtml(summary)}</p>` : ""}
        ${scripture ? renderScripturePassage(scripture) : `<p class="scripture-loading">${escapeHtml(scriptureLoadingMessage(ref))}</p>`}
      </div>
    `;
  }

  function scriptureLoadingMessage(ref) {
    const reference = ref?.title || displayReference(ref?.canonicalRef || "");
    if (window.location.protocol === "file:" || window.location.port === "8092") {
      return `${reference} 已在字幕中识别；当前是静态预览，未连接经文 API。Cloud Run 或本地后端启动后会加载这一章。`;
    }
    return "正在加载这一章经文...";
  }

  function renderScriptureSourceNote(scripture) {
    if (!el.scriptureCandidates) return;
    const source = scripture?.source || "中文圣经：新标点和合本（简体） · eBible.org cmn-cu89s · Public Domain";
    const parent = el.scriptureCandidates.parentElement;
    if (!parent) return;
    let note = document.getElementById("scriptureSourceNote");
    if (!note) {
      note = document.createElement("p");
      note.id = "scriptureSourceNote";
      note.className = "scripture-source scripture-source-note";
      parent.insertBefore(note, el.scriptureCandidates);
    }
    note.textContent = source;
  }

  function displayScriptureSummary(summary) {
    const text = String(summary || "").trim();
    if (text.includes("系统会在实时字幕中")) return "";
    const templateSummaries = new Set([
      "讲道中提到的完整经文章节。",
      "讲道中提到的完整经文章节。经文由 Cloud Run 后端完整 Bible index 返回。",
      "讲道中提到的明确经文章节。"
    ]);
    return templateSummaries.has(text) ? "" : text;
  }

  function buildNoteSlices(segments) {
    const slices = [];
    let current = null;
    const noteSegments = noteSegmentParts(segments);

    noteSegments.forEach((item) => {
      if (!current) {
        current = createNoteSlice(item);
        return;
      }

      const combinedChars = current.charCount + item.text.length + 1;
      const combinedDuration = Math.max(current.endMs, item.endMs) - current.startMs;
      const shouldSplitByChars = combinedChars > NOTE_SLICE_MAX_CHARS;
      const shouldSplitByTime = combinedDuration > NOTE_SLICE_TARGET_MS && current.charCount >= NOTE_SLICE_MIN_CHARS;

      if (shouldSplitByChars || shouldSplitByTime) {
        slices.push(finalizeNoteSlice(current, slices.length));
        current = createNoteSlice(item);
        return;
      }

      addItemToNoteSlice(current, item);
    });

    if (current) slices.push(finalizeNoteSlice(current, slices.length));
    return slices;
  }

  function buildNoteGenerationPayload(segments) {
    const slices = buildNoteSlices(segments);
    return {
      provider: NOTE_AI_CONFIG.provider,
      model: NOTE_AI_CONFIG.model,
      reasoningEffort: NOTE_AI_CONFIG.reasoningEffort,
      tasks: ["summary_zh", "outline_zh", "application_questions_zh", "quotes_zh"],
      slices: slices.map((slice) => ({
        index: slice.index,
        startMs: slice.startMs,
        endMs: slice.endMs,
        text: slice.text,
        refs: slice.refs
      }))
    };
  }

  function noteSegmentParts(segments) {
    const parts = [];
    segments
      .map((segment, index) => ({ segment, index }))
      .filter(({ segment }) => noteTextForSegment(segment))
      .sort((a, b) => segmentStart(a.segment) - segmentStart(b.segment))
      .forEach(({ segment, index }) => {
        splitNoteText(noteTextForSegment(segment)).forEach((text, partIndex) => {
          parts.push({
            segment,
            index,
            partIndex,
            text,
            startMs: segmentStart(segment),
            endMs: segmentEnd(segment)
          });
        });
      });
    return parts;
  }

  function createNoteSlice(item) {
    const slice = {
      startMs: item.startMs,
      endMs: item.endMs,
      texts: [],
      segmentIds: [],
      refs: [],
      charCount: 0
    };
    addItemToNoteSlice(slice, item);
    return slice;
  }

  function addItemToNoteSlice(slice, item) {
    slice.startMs = Math.min(slice.startMs, item.startMs);
    slice.endMs = Math.max(slice.endMs, item.endMs);
    slice.texts.push(item.text);
    slice.charCount += item.text.length;
    const segmentId = item.segment?.id || `segment-${item.index}`;
    if (!slice.segmentIds.includes(segmentId)) slice.segmentIds.push(segmentId);
    referencesForSegment(item.segment).forEach((ref) => {
      const label = ref.title || ref.canonicalRef;
      if (label && !slice.refs.includes(label)) slice.refs.push(label);
    });
  }

  function finalizeNoteSlice(slice, index) {
    const text = compactText(slice.texts.join(" "));
    return {
      index: index + 1,
      startMs: slice.startMs,
      endMs: slice.endMs,
      text,
      preview: notePreview(text),
      segmentCount: slice.segmentIds.length,
      charCount: text.length,
      refs: slice.refs
    };
  }

  function noteTextForSegment(segment) {
    return compactText(segment?.zh || segment?.draft || segment?.text || segment?.en || "");
  }

  function splitNoteText(text) {
    const chunks = [];
    let remaining = compactText(text);
    while (remaining.length > NOTE_SLICE_MAX_CHARS) {
      const breakAt = noteTextBreakIndex(remaining, NOTE_SLICE_MAX_CHARS);
      chunks.push(remaining.slice(0, breakAt).trim());
      remaining = remaining.slice(breakAt).trim();
    }
    if (remaining) chunks.push(remaining);
    return chunks;
  }

  function noteTextBreakIndex(text, limit) {
    const floor = Math.max(NOTE_SLICE_MIN_CHARS, limit - 240);
    for (let index = Math.min(limit, text.length); index > floor; index -= 1) {
      if (/[。！？；，,]/.test(text[index - 1])) return index;
    }
    return Math.min(limit, text.length);
  }

  function notePreview(text) {
    const compact = compactText(text);
    if (compact.length <= NOTE_PREVIEW_MAX_CHARS) return compact;
    const breakAt = noteTextBreakIndex(compact, NOTE_PREVIEW_MAX_CHARS);
    return `${compact.slice(0, breakAt).trim()}...`;
  }

  function compactText(text) {
    return String(text || "").replace(/\s+/g, " ").trim();
  }

  async function refreshScriptureFromApi(ref) {
    if (state.scriptureFetches.has(ref.canonicalRef)) return;
    state.scriptureFetches.add(ref.canonicalRef);
    try {
      const response = await fetch(`/api/scripture/cmn-cu89s/${encodeURIComponent(ref.book)}/${encodeURIComponent(ref.chapter)}`, {
        headers: { "Accept": "application/json" }
      });
      if (!response.ok) {
        markScriptureLoadUnavailable(ref);
        return;
      }
      const payload = await response.json();
      const scripture = scriptureFromApiPayload(payload);
      if (!scripture) return;
      scriptureReferences[scripture.canonicalRef] = scripture;
      const card = findScriptureCard(scripture.canonicalRef);
      if (!card) return;
      card.classList.add("is-exact");
      card.innerHTML = renderScriptureCard(ref, scripture, null);
      renderScriptureSourceNote(scripture);
    } catch {
      markScriptureLoadUnavailable(ref);
    }
  }

  function markScriptureLoadUnavailable(ref) {
    const card = findScriptureCard(ref.canonicalRef);
    const loading = card?.querySelector(".scripture-loading");
    if (loading) loading.textContent = scriptureLoadingMessage(ref);
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
      `<span><strong>${escapeHtml(displayVerseNumber(passage.verse))}</strong> ${escapeHtml(passage.text)}</span>`
    )).join(" ");
    const fullClass = scripture.verses && scripture.verses.length > 8 ? " scripture-passage--full" : "";
    return `<div class="scripture-passage${fullClass}"><p>${body}</p></div>`;
  }

  function displayVerseNumber(value) {
    const text = String(value || "").trim();
    const chapterVerse = text.match(/^\d+\s*[:：]\s*(.+)$/);
    return chapterVerse ? chapterVerse[1] : text;
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
    if (!el.noteBlock) return;
    const slices = buildNoteSlices(state.segments);
    if (!slices.length) {
      el.noteBlock.innerHTML = `
        <h3>证道笔记草稿</h3>
        <p>等待稳定字幕片段。</p>
      `;
      return;
    }
    const totalChars = slices.reduce((sum, slice) => sum + slice.charCount, 0);
    el.noteBlock.innerHTML = `
      <h3>证道笔记草稿</h3>
      <p>已积累 ${state.segments.length} 个稳定字幕片段，切成 ${slices.length} 段，约 ${totalChars} 字。</p>
      <p class="note-model">模型：${escapeHtml(NOTE_AI_CONFIG.displayName)} · reasoning ${escapeHtml(NOTE_AI_CONFIG.reasoningEffort)}</p>
      <ol class="note-slice-list">
        ${slices.map(renderNoteSlice).join("")}
      </ol>
    `;
  }

  function renderNoteSlice(slice) {
    const refs = slice.refs.length
      ? `<span>经文：${escapeHtml(slice.refs.slice(0, 3).join("、"))}</span>`
      : "";
    return `
      <li>
        <strong>${escapeHtml(msToClock(slice.startMs))} - ${escapeHtml(msToClock(slice.endMs))}</strong>
        <p>${escapeHtml(slice.preview)}</p>
        <small>
          <span>${slice.segmentCount} 个字幕片段</span>
          <span>约 ${slice.charCount} 字</span>
          ${refs}
          <span>待 ${escapeHtml(NOTE_AI_CONFIG.displayName)} 总结</span>
        </small>
      </li>
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
    if (state.viewMode === "admin" && state.livePlayback && ["live", "paused"].includes(state.livePlayback.mode)) {
      adjustLivePlayback(delta);
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

  function startAdminProgressPolling() {
    if (state.viewMode !== "admin") return;
    window.clearInterval(state.adminProgressTimer);
    refreshAdminProgress({ quiet: true });
    state.adminProgressTimer = window.setInterval(() => refreshAdminProgress({ quiet: true }), 5000);
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
    if (el.approxEndTime) el.approxEndTime.value = state.adminSettings.approxEndTime;
    if (el.publicSliceLabel) el.publicSliceLabel.textContent = state.adminSettings.sunday;
    updateCloudRunTestLinks();
    if (el.autoDiscoveryStatus) {
      el.autoDiscoveryStatus.textContent = state.adminSettings.captureMode === "manual"
        ? "手动链接优先"
        : "08:20/09:50 PT";
    }
    updateCaptureMode(state.adminSettings.captureMode);
    updateAdminStatusSummary();
  }

  function updateCloudRunTestLinks() {
    const sunday = state.adminSettings.sunday || currentIsoDate();
    setOptionalText(el.cloudRunTestDate, sunday);
    if (el.cloudRunPublicLink) {
      el.cloudRunPublicLink.href = `/sundays/${encodeURIComponent(sunday)}`;
      el.cloudRunPublicLink.textContent = `/sundays/${sunday}`;
    }
    if (el.cloudRunAdminLink) {
      el.cloudRunAdminLink.href = `/admin.html?sunday=${encodeURIComponent(sunday)}`;
      el.cloudRunAdminLink.textContent = `/admin.html?sunday=${sunday}`;
    }
  }

  function updateCloudRunTestStatus(label, detail, tone = "manual") {
    setOptionalText(el.cloudRunTestState, label);
    if (el.cloudRunTestState) el.cloudRunTestState.classList.toggle("is-manual", tone !== "ready");
    setOptionalText(el.cloudRunTestResult, detail);
    updateCloudRunTestLinks();
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
      updateAdminStatusSummary();
      log("已读取后端管理状态摘要。");
    } catch (error) {
      state.adminStatus = {
        artifact: { manifestStatus: "unavailable", manifestError: error.message || String(error) },
        captions: { translationStatus: "unknown" },
        readiness: { state: "unavailable", publicArtifactsReady: false, fallback: false },
        settings: { provider: "openai", readinessDeadline: "11:50 PT" },
        secrets: { openaiApiKey: "unavailable", operatorAdminToken: "unknown", internalTaskToken: "unknown" }
      };
      updateAdminStatusSummary();
      log(`管理状态读取失败：${error.message || error}。`);
    }
  }

  async function refreshAdminProgress(options = {}) {
    if (state.viewMode !== "admin") return;
    const sunday = encodeURIComponent(state.adminSettings.sunday || "current");
    try {
      const response = await fetch(`/api/admin/sundays/${sunday}/progress`, { headers: { "Accept": "application/json" } });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      state.adminProgress = await response.json();
      updatePipelineFromAdminProgress(state.adminProgress);
      if (!options.quiet) log("已读取后端生成进度。");
    } catch (error) {
      if (!options.quiet) log(`生成进度读取失败：${error.message || error}。`);
    }
  }

  function updateAdminStatusSummary() {
    if (state.viewMode !== "admin") return;
    const status = state.adminStatus || {};
    const artifact = status.artifact || {};
    const captionsStatus = status.captions || {};
    const readiness = status.readiness || {};
    const settings = status.settings || {};
    const secrets = status.secrets || {};
    const realtime = status.realtime || {};
    const eventArchive = realtime.eventArchive || {};
    const sunday = status.sunday || state.adminSettings.sunday;
    setOptionalText(el.adminSunday, sunday || "--");
    setOptionalText(el.adminManifestStatus, statusLabel(artifact.manifestStatus || "unchecked"));
    setOptionalText(el.adminManifestDetail, artifact.manifestError
      ? `读取失败：${artifact.manifestError}`
      : manifestDetailText(artifact));
    const readinessState = readiness.state || captionsStatus.translationStatus || "unknown";
    setOptionalText(el.adminCaptionStatus, statusLabel(readinessState));
    setOptionalText(el.adminCaptionDetail, captionCountText(captionsStatus));
    setOptionalText(el.adminReadyTime, captionsStatus.publishedAt || captionsStatus.readyTime || readiness.publishedAt || readiness.readyTime || "待发布");
    setOptionalText(el.adminUpdatedAt, `最后更新 ${captionsStatus.lastUpdated || formatClock()}`);
    setOptionalText(el.adminBucket, artifact.bucket || "未配置");
    setOptionalText(el.adminPrefix, artifact.prefix || "sundays");
    setOptionalText(el.adminProvider, providerLabel(settings.provider || "openai"));
    setOptionalText(el.adminDeadline, settings.readinessDeadline || "11:50 PT");
    const secretReady = secrets.openaiApiKey === "configured";
    if (el.adminSecretStatus) {
      el.adminSecretStatus.textContent = secretReady
        ? "OpenAI 密钥已配置"
        : secrets.openaiApiKey === "missing"
          ? "OpenAI 密钥缺失"
          : "本地预览未检查密钥";
      el.adminSecretStatus.classList.toggle("is-manual", !secretReady);
    }
    if (eventArchive.enabled) {
      updateAdminEvidence("worker", `Realtime deltas 写入 ${eventArchive.directory || "backend JSONL archive"}`);
    }
  }

  function captionCountText(captionsStatus) {
    const total = captionsStatus.totalSegments;
    const translated = captionsStatus.translatedSegments;
    if (Number.isFinite(total) && Number.isFinite(translated)) {
      return `发布清单统计：${translated} 个已翻译 / 共 ${total} 个片段`;
    }
    if (state.segments.length) {
      return `${state.segments.length} 个本地片段`;
    }
    return "等待发布清单回报";
  }

  function manifestDetailText(artifact) {
    const count = Number(artifact.artifactCount) || 0;
    if (!count) return "还没有读到会众页发布文件";
    return `发布清单包含 ${count} 个文件：字幕、回放数据、报告等会众页资源`;
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
      needs_translation: "待翻译",
      source_detected: "已发现源",
      caption_generating: "字幕生成中",
      needs_review: "待复核",
      published: "已发布",
      fallback: "兜底"
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

  function beginTestRun(mode, label) {
    const now = Date.now();
    state.testRun = {
      mode,
      label,
      active: true,
      startedAt: now,
      captureStartAt: null,
      firstEnglishAt: null,
      firstChineseAt: null,
      samples: [],
      notes: [],
      segmentCount: 0,
      sermonStartMarkedAt: null,
      sermonStartTimecode: state.adminSettings.approxStartTime || null
    };
    state.segments = mode === "ipad-mic" ? [] : state.segments;
    state.currentSegmentId = mode === "ipad-mic" ? null : state.currentSegmentId;
    updateTestReadiness("测试中");
    updateLatencyUi();
    log(`${label}测试已开始，正在记录首条英文、首条中文和稳定延时。`);
  }

  function recordLatency(kind, atMs) {
    if (!state.testRun) return;
    if (kind === "captureStart" && !state.testRun.captureStartAt) state.testRun.captureStartAt = atMs;
    if (kind === "firstEnglish" && !state.testRun.firstEnglishAt) state.testRun.firstEnglishAt = atMs;
    if (kind === "firstChinese" && !state.testRun.firstChineseAt) state.testRun.firstChineseAt = atMs;
    state.testRun.segmentCount = Math.max(state.testRun.segmentCount, state.segments.length);
    updateLatencyUi();
  }

  function recordLatencySample(delayMs) {
    if (!state.testRun || !Number.isFinite(delayMs)) return;
    state.testRun.samples.push(Math.max(0, Math.round(delayMs)));
    state.testRun.segmentCount = Math.max(state.testRun.segmentCount, state.segments.length);
    updateLatencyUi();
  }

  function recordTestNote(note) {
    if (state.testRun) state.testRun.notes.push({ at: new Date().toISOString(), note });
    setOptionalText(el.latencyNote, note);
    log(note);
  }

  function updateLatencyUi() {
    const run = state.testRun;
    setOptionalText(el.latencyMode, run ? run.label : "未开始");
    setOptionalText(el.latencyCaptureStart, run?.captureStartAt ? elapsedLabel(run.captureStartAt - run.startedAt) : "--");
    setOptionalText(el.latencyFirstEnglish, run?.firstEnglishAt ? elapsedLabel(run.firstEnglishAt - run.startedAt) : "--");
    setOptionalText(el.latencyFirstChinese, run?.firstChineseAt ? elapsedLabel(run.firstChineseAt - run.startedAt) : "--");
    setOptionalText(el.latencyMedian, run?.samples?.length ? elapsedLabel(median(run.samples)) : "--");
    setOptionalText(el.latencyWorst, run?.samples?.length ? elapsedLabel(Math.max(...run.samples)) : "--");
    setOptionalText(el.latencySegments, String(run?.segmentCount || 0));
  }

  function updateTestPassState(text, tone = "ready") {
    setOptionalText(el.latencyPassState, text);
    updateTestReadiness(text, tone);
  }

  function updateTestPassStateFromMetrics() {
    const run = state.testRun;
    if (!run) return;
    const firstChineseMs = run.firstChineseAt ? run.firstChineseAt - run.startedAt : Infinity;
    const worst = run.samples.length ? Math.max(...run.samples) : 0;
    const minSegments = run.mode === "ipad-mic" ? 1 : 3;
    if (run.segmentCount >= minSegments && firstChineseMs <= 15000 && worst <= 30000) {
      updateTestPassState("通过：可进入复测", "ready");
      return;
    }
    if (run.segmentCount > 0) {
      updateTestPassState("进行中：已有字幕", "watching");
      return;
    }
    updateTestPassState("等待首条字幕", "watching");
  }

  function updateTestReadiness(text, tone = "watching") {
    if (!el.testReadiness) return;
    el.testReadiness.textContent = text;
    el.testReadiness.dataset.state = tone;
  }

  function median(values) {
    const sorted = values.slice().sort((a, b) => a - b);
    const middle = Math.floor(sorted.length / 2);
    return sorted.length % 2 ? sorted[middle] : Math.round((sorted[middle - 1] + sorted[middle]) / 2);
  }

  function elapsedLabel(ms) {
    if (!Number.isFinite(ms)) return "--";
    if (ms < 1000) return `${Math.max(0, Math.round(ms))} ms`;
    return `${(Math.max(0, ms) / 1000).toFixed(1)} s`;
  }

  function translateForLiveTest(text) {
    const clean = String(text || "").trim();
    const lower = clean.toLowerCase();
    const phraseMap = [
      ["jesus", "耶稣"],
      ["god", "神"],
      ["lord", "主"],
      ["grace", "恩典"],
      ["mercy", "怜悯"],
      ["rebellion", "悖逆"],
      ["mediator", "中保"],
      ["pray", "祷告"],
      ["scripture", "经文"],
      ["numbers", "民数记"]
    ];
    const hits = phraseMap.filter(([source]) => lower.includes(source)).map(([, zh]) => zh);
    if (hits.length) {
      return `测试翻译：这句话提到${hits.join("、")}。英文原文：${clean}`;
    }
    return `测试翻译：${clean}`;
  }

  function exportTestReport() {
    if (!state.testRun) {
      log("还没有测试记录可导出。");
      return;
    }
    const run = state.testRun;
    const report = {
      mode: run.mode,
      label: run.label,
      sunday: state.adminSettings.sunday,
      liveUrl: state.adminSettings.manualLiveUrl || window.SERMON_PLAYBACK_SIMULATION?.live?.url || null,
      sermonStartTimecode: run.sermonStartTimecode,
      startedAt: new Date(run.startedAt).toISOString(),
      captureStartLatencyMs: run.captureStartAt ? run.captureStartAt - run.startedAt : null,
      firstEnglishLatencyMs: run.firstEnglishAt ? run.firstEnglishAt - run.startedAt : null,
      firstChineseLatencyMs: run.firstChineseAt ? run.firstChineseAt - run.startedAt : null,
      stableMedianLatencyMs: run.samples.length ? median(run.samples) : null,
      worstLatencyMs: run.samples.length ? Math.max(...run.samples) : null,
      segmentCount: run.segmentCount,
      notes: run.notes,
      segments: state.segments.slice(-20).map((segment) => ({
        id: segment.id,
        startMs: segment.startMs,
        endMs: segment.endMs,
        en: segment.en,
        zh: segment.zh,
        confidence: segment.confidence
      }))
    };
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `sermon-caption-test-${run.mode}-${dateStamp()}.json`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 500);
    log("已导出测试记录 JSON。");
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
    if (mode === "ready" && state.playbackSegments.length) {
      setOptionalText(el.pipelineSummary, "本地回放可复核");
      updatePipelineStage("source-discovery", "done", "已加载");
      updatePipelineStage("live-capture", "done", "回放");
      updatePipelineStage("sermon-start", "done", state.adminSettings.approxStartTime || "已定位");
      updatePipelineStage("transcript", "done", "英文可见");
      updatePipelineStage("translation", "done", "中文可见");
      updatePipelineStage("scripture", "active", "待经文库");
      updatePipelineStage("promotion", "waiting", "Cloud Run");
      updatePipelineStage("public-ready", "waiting", "未验证");
    }
  }

  function updatePipelineFromAdminProgress(progress) {
    if (!el.pipelineList || !progress || progress.status === "missing") return;
    const stages = Array.isArray(progress.pipelineStages) ? progress.pipelineStages : [];
    stages.forEach((stage) => {
      if (!stage || !stage.id) return;
      const stateName = ["waiting", "active", "done", "failed"].includes(stage.state)
        ? stage.state
        : "waiting";
      updatePipelineStage(stage.id, stateName, stage.statusLabel || pipelineFallbackLabel(stateName));
    });
    setOptionalText(el.pipelineSummary, adminProgressSummary(progress));
    if (progress.status === "failed" && progress.error) {
      updateAdminEvidence("worker", `生成失败：${progress.failedCommandStage || "unknown"} · ${progress.error}`);
    } else if (progress.currentCommandStage) {
      updateAdminEvidence("worker", `后台阶段进行中：${progress.currentCommandStage}`);
    } else if (progress.status === "completed") {
      updateAdminEvidence("ready", `字幕已发布 · ${progress.sunday || state.adminSettings.sunday}`);
    } else if (progress.status === "planned") {
      updateAdminEvidence("worker", `后台计划已记录：${progress.sessionId || "等待 session"}`);
    }
  }

  function pipelineFallbackLabel(stateName) {
    if (stateName === "done") return "完成";
    if (stateName === "active") return "进行中";
    if (stateName === "failed") return "失败";
    return "等待";
  }

  function adminProgressSummary(progress) {
    const status = String(progress.status || "");
    if (status === "completed") return "已发布";
    if (status === "failed") return "失败";
    if (status === "running") return "生成中";
    if (status === "planned") return "已排程";
    return statusLabel(status || "unknown");
  }

  function updateSegmentCountNote() {
    if (!el.segmentCountNote) return;
    if (!state.segments.length && !state.playbackSegments.length) {
      el.segmentCountNote.textContent = "等待字幕时间轴";
      return;
    }
    const count = state.playbackSegments.length || state.segments.length;
    const rawCount = state.rawSegments.length || count;
    const isGeneratedSample = Boolean(window.SERMON_PLAYBACK_SIMULATION?.generatedFrom);
    el.segmentCountNote.textContent = isGeneratedSample
      ? `显示全部成品断句；${rawCount} 个原始 cue 保留用于追溯和导出`
      : "显示全部成品断句；原始 cue 由 VTT/实时字幕时间码决定";
  }

  function updateSegmentCoverage(reviewGroups) {
    if (!el.segmentCoverage) return;
    if (!reviewGroups.length) {
      el.segmentCoverage.textContent = "等待覆盖范围";
      return;
    }
    const starts = reviewGroups
      .map((group) => Number(group.startMs))
      .filter(Number.isFinite);
    const ends = reviewGroups
      .map((group) => Number(group.endMs))
      .filter(Number.isFinite);
    if (!starts.length || !ends.length) {
      el.segmentCoverage.textContent = "已显示全部可用字幕";
      return;
    }
    el.segmentCoverage.textContent = `覆盖 ${msToClock(Math.min(...starts))}-${msToClock(Math.max(...ends))}`;
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
    if (el.confidenceMeter) {
      const label = confidence ? `听写把握 ${confidence}%` : "听写把握 --%";
      el.confidenceMeter.textContent = label;
      if (typeof el.confidenceMeter.setAttribute === "function") {
        el.confidenceMeter.setAttribute("aria-label", `${label}，表示当前英文听写的模型把握度`);
      }
    }
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
    applyOffset,
    buildNoteSlices,
    buildNoteGenerationPayload,
    createRealtimeSession,
    handleRealtimeDataChannelMessage,
    postRealtimeSessionEvent,
    normalizeRealtimeOpenAIEvent: realtimeCaptionEventFromOpenAI,
    pushRealtimeEvent: handleRealtimeCaptionEvent
  };

  init();
})();
