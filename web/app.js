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
    currentSegmentId: null,
    segments: [],
    monitorTimers: [],
    streamTimer: null,
    clockTimer: null,
    progressTimer: null,
    startedAt: null,
    lastExport: null
  };

  const el = {
    shell: document.querySelector(".app-shell"),
    clock: document.getElementById("clock"),
    sourceStatus: document.getElementById("sourceStatus"),
    slaStatus: document.getElementById("slaStatus"),
    sourceList: document.getElementById("sourceList"),
    draftCaption: document.getElementById("draftCaption"),
    stableCaption: document.getElementById("stableCaption"),
    englishSidecar: document.getElementById("englishSidecar"),
    confidenceMeter: document.getElementById("confidenceMeter"),
    segmentList: document.getElementById("segmentList"),
    segmentCount: document.getElementById("segmentCount"),
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
    el.clock.textContent = formatClock();
    state.clockTimer = window.setInterval(() => {
      el.clock.textContent = formatClock();
    }, 1000);
    setStatus("等待监控", "watching");
    setSla("11:30 会众可用", "ready");
    log("控制台已就绪：目标是在 11:30 场开始时，为正在听道的会众提供可用中文字幕。");
    updateSourceCards("idle");
    updateTimeline();
  }

  function onActionClick(event) {
    const control = event.target.closest("[data-action]");
    if (!control) return;

    const action = control.dataset.action;
    if (action === "select-service") selectService(control.dataset.service);
    if (action === "start-monitor") startMonitor();
    if (action === "start-caption") startCaptioning();
    if (action === "use-fallback") useFallback();
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
    clearMonitorTimers();
    state.monitoring = true;
    state.fallback = state.selectedService === "1000";
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
        useOperatorAudio();
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

  function startCaptioning() {
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
    state.startedAt = state.startedAt || Date.now();
    setStatus("会众字幕生成中", "live");
    setSla("11:25 前发布会众视图", "live");
    el.sessionLabel.textContent = `Session: rt-${dateStamp()}-${state.selectedService}`;
    log("会众字幕 session 已启动，开始模拟低延迟字幕流。");
    scheduleNextCaption(300);
    startProgress();
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
    el.segmentList.textContent = "";
    state.segments.slice(-8).forEach((segment) => {
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
    if (!state.paused) scheduleNextCaption(400);
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
    window.clearTimeout(state.streamTimer);
    setStatus("会众视图已发布", "ready");
    setSla("11:30 会众可用", "ready");
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

  function serviceLabel(service) {
    if (service === "830") return "8:30 PT";
    if (service === "1000") return "10:00 PT";
    return "手动音频";
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
    selectService,
    useFallback,
    useOperatorAudio,
    freezeReview,
    exportCaptions,
    applyOffset
  };

  init();
})();
