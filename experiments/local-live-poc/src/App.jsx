import { useEffect, useMemo, useRef, useState } from "react";
import { observeCaptionFrame } from "./captionObservation.js";
import { healthObservation } from "./healthObservation.js";
import {
  V41_TRANSLATION_PROVIDER, healthForTranslationProvider, initialTranslationProvider,
  providerContextPolicy, translationProviderStatus, assertTranslationSession,
} from "./translationProvider.js";
import QRCode from "qrcode";
import {
  GATEWAY_URL,
  appendAudioChunk,
  appendSessionEvent,
  finalizeLocalSession,
  getGatewayHealth,
  restartGateway,
  resumeLocalSession,
  startLocalSession,
  startV41TranslationRuntime,
} from "./gatewayClient.js";
import { LiveCaptionSocket } from "./liveSocket.js";
import { applyCaptionEvent, createCaptionState } from "./captionState.js";

function nowIso() {
  return new Date().toISOString();
}

function formatDuration(milliseconds) {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
  const hours = String(Math.floor(totalSeconds / 3600)).padStart(2, "0");
  const minutes = String(Math.floor((totalSeconds % 3600) / 60)).padStart(2, "0");
  const seconds = String(totalSeconds % 60).padStart(2, "0");
  return `${hours}:${minutes}:${seconds}`;
}

function downloadUrl(value, type) {
  return URL.createObjectURL(new Blob([value], { type }));
}

function compactModelName(value, fallback) {
  if (!value) return fallback;
  const name = String(value).split("/").filter(Boolean).pop() || fallback;
  return name
    .replace(":benchmark", "")
    .replace("qwen3-asr-0.6b-8bit-89e96d92", "Qwen3-ASR 0.6B 8-bit")
    .replace("milmmt-sermon-v41-experimental-mlx-q5", "MiLMMT v4.1 Q5 · 实验")
    .replace("sermon-milmmt-46-4b-v1-q8", "MiLMMT 4B Q8");
}

function tokenRate(metrics) {
  const tokens = Number(metrics?.evalCount);
  const durationNs = Number(metrics?.evalDurationNs);
  if (!Number.isFinite(tokens) || !Number.isFinite(durationNs) || durationNs <= 0) return null;
  return Math.round(tokens / (durationNs / 1_000_000_000));
}

function requestAudioStream(constraints, timeoutMs = 8000) {
  return new Promise((resolve, reject) => {
    let settled = false;
    const timeout = window.setTimeout(() => {
      settled = true;
      const error = new Error("麦克风授权没有响应。请改用最新版 Safari 或 Chrome，并允许本地页面使用麦克风。");
      error.name = "TimeoutError";
      reject(error);
    }, timeoutMs);

    navigator.mediaDevices.getUserMedia(constraints).then((stream) => {
      if (settled) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      settled = true;
      window.clearTimeout(timeout);
      resolve(stream);
    }).catch((error) => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timeout);
      reject(error);
    });
  });
}

export function App() {
  const [phase, setPhase] = useState("idle");
  const [devices, setDevices] = useState([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState("");
  const [selectedTranslationProvider, setSelectedTranslationProvider] = useState(
    () => initialTranslationProvider(window.location.search),
  );
  const [modelStartupState, setModelStartupState] = useState("idle");
  const translationProviderRef = useRef(selectedTranslationProvider);
  translationProviderRef.current = selectedTranslationProvider;
  const [elapsed, setElapsed] = useState(0);
  const [level, setLevel] = useState(0);
  const [captions, setCaptions] = useState(() => createCaptionState({
    zh: "选择麦克风，然后开始录音。",
  }));
  const [translationState, setTranslationState] = useState("idle");
  const [gatewayHealth, setGatewayHealth] = useState(null);
  const [error, setError] = useState("");
  const [recordingUrl, setRecordingUrl] = useState("");
  const [recordingBytes, setRecordingBytes] = useState(0);
  const [logUrl, setLogUrl] = useState("");
  const [eventCount, setEventCount] = useState(0);
  const [localSession, setLocalSession] = useState(null);
  const [localSaveState, setLocalSaveState] = useState("idle");
  const [liveMetrics, setLiveMetrics] = useState({});
  const [runtimeRestartState, setRuntimeRestartState] = useState("idle");
  const [viewerShare, setViewerShare] = useState(null);
  const [viewerQr, setViewerQr] = useState("");
  const [viewerRoute, setViewerRoute] = useState("public");
  const [liveRecoveryState, setLiveRecoveryState] = useState("idle");

  const streamRef = useRef(null);
  const recorderRef = useRef(null);
  const chunksRef = useRef([]);
  const eventsRef = useRef([]);
  const timerRef = useRef(null);
  const startTimeRef = useRef(0);
  const audioContextRef = useRef(null);
  const meterFrameRef = useRef(null);
  const workletNodeRef = useRef(null);
  const liveSocketRef = useRef(null);
  const localSessionRef = useRef(null);
  const serverWriteQueueRef = useRef(Promise.resolve());
  const audioChunkSequenceRef = useRef(0);
  const localWriteFailureRef = useRef(false);
  const recordingActiveRef = useRef(false);
  const healthTimerRef = useRef(null);
  const activeTranslationSegmentRef = useRef("");
  const partialTranslationRef = useRef({ segmentId: "", text: "" });
  const renderedTranslationSegmentsRef = useRef(new Set());
  const renderQueueRef = useRef(Promise.resolve());
  const pcmClockStartedAtRef = useRef(0);
  const recoverableAsrErrorRef = useRef(false);
  const pcmFrameSequenceRef = useRef(0);
  const recoveryInProgressRef = useRef(false);
  const recoveryNeededRef = useRef(false);
  const recoveryAttemptsRef = useRef(0);
  const viewerUrl = viewerRoute === "lan"
    ? viewerShare?.urls?.find((url) => url !== viewerShare?.publicUrl)
    : viewerShare?.publicUrl || viewerShare?.urls?.[0];

  const isRunning = phase === "running";
  const isBusy = phase === "requesting" || phase === "stopping";
  const modelStarting = modelStartupState === "starting";
  const isExperimentalTranslation = selectedTranslationProvider === V41_TRANSLATION_PROVIDER;
  const selectedModelStatus = translationProviderStatus(gatewayHealth, selectedTranslationProvider);
  const selectedGatewayHealth = healthForTranslationProvider(gatewayHealth, selectedTranslationProvider);
  const asrModelName = compactModelName(
    gatewayHealth?.asr?.modelPath || gatewayHealth?.asr?.provider,
    "ASR",
  );
  const translationModelName = compactModelName(
    selectedModelStatus.configuredModel,
    isExperimentalTranslation ? "MiLMMT v4.1 Q5 · 实验" : "MiLMMT",
  );
  const contextPolicy = providerContextPolicy(gatewayHealth, selectedTranslationProvider);
  const captionDemo = import.meta.env.DEV
    && new URLSearchParams(window.location.search).get("captionDemo") === "1";
  const visibleCaptions = captionDemo ? {
    previousFinal: {
      segmentId: "demo-previous",
      en: "We walk by faith, not by sight.",
      zh: "我们凭信心而行，不凭眼见。",
    },
    active: {
      segmentId: "demo-active",
      en: "That changes how we face tomorrow.",
      zh: "这改变了我们面对明天的方式。",
      phase: "streaming",
    },
  } : captions;

  useEffect(() => {
    const url = viewerUrl;
    if (!url) {
      setViewerQr("");
      return;
    }
    QRCode.toDataURL(url, { width: 220, margin: 1, errorCorrectionLevel: "M" })
      .then(setViewerQr)
      .catch(() => setViewerQr(""));
  }, [viewerUrl]);

  const status = useMemo(() => {
    if (phase === "running") return "正在录音 · 本地 ASR 与翻译";
    if (phase === "requesting") return "正在连接麦克风";
    if (phase === "stopping") return "正在完成最后一句并保存";
    if (phase === "stopped") return "本次录音已停止";
    if (phase === "error") return "需要处理麦克风问题";
    return "准备开始";
  }, [phase]);

  function appendEvent(type, detail = {}, persist = true) {
    const event = {
      schemaVersion: 1,
      sequence: eventsRef.current.length + 1,
      at: nowIso(),
      elapsedMs: startTimeRef.current ? Date.now() - startTimeRef.current : 0,
      type,
      ...detail,
    };
    eventsRef.current.push(event);
    setEventCount(eventsRef.current.length);
    if (persist && localSessionRef.current && !localWriteFailureRef.current) {
      const sessionId = localSessionRef.current.sessionId;
      enqueueServerWrite(async () => {
        await appendSessionEvent(sessionId, event);
      });
    }
    return event;
  }

  function recordLocalStorageFailure(caught) {
    if (localWriteFailureRef.current) return;
    localWriteFailureRef.current = true;
    recoverableAsrErrorRef.current = false;
    setLocalSaveState("error");
    appendEvent("local_storage_failed", {
      message: caught?.message || "Local session storage failed",
      browserDownloadFallbackAvailable: true,
    }, false);
  }

  function enqueueServerWrite(task) {
    serverWriteQueueRef.current = serverWriteQueueRef.current
      .then(task)
      .catch(recordLocalStorageFailure);
    return serverWriteQueueRef.current;
  }

  async function refreshDevices() {
    if (!navigator.mediaDevices?.enumerateDevices) return;
    const available = await navigator.mediaDevices.enumerateDevices();
    const inputs = available.filter((device) => device.kind === "audioinput");
    setDevices(inputs);
    setSelectedDeviceId((current) => current || inputs[0]?.deviceId || "");
  }

  async function refreshGatewayHealth() {
    try {
      const health = await getGatewayHealth();
      setGatewayHealth(health);
      return healthForTranslationProvider(health, translationProviderRef.current);
    } catch (caught) {
      setGatewayHealth({ status: "offline", message: caught?.message || "Gateway unavailable" });
      return null;
    }
  }

  async function startExperimentalModel() {
    if (isRunning || isBusy || modelStarting) return;
    setModelStartupState("starting");
    setError("");
    try {
      const result = await startV41TranslationRuntime();
      if (!result.ready) throw new Error("v4.1 尚未就绪，请查看本地模型启动日志。");
      setModelStartupState("ready");
      await refreshGatewayHealth();
    } catch (caught) {
      setModelStartupState("error");
      setError(caught?.message || "v4.1 启动失败，请重试。");
    }
  }

  async function restartBackend() {
    if (runtimeRestartState === "restarting") return;

    setRuntimeRestartState("restarting");
    recoverableAsrErrorRef.current = false;
    setError("");
    appendEvent("runtime_restart_requested", { recordingActive: recordingActiveRef.current }, false);
    try {
      await restartGateway();
      let health = null;
      for (let attempt = 0; attempt < 60; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 500));
        health = await refreshGatewayHealth();
        if (health?.status === "ready") break;
      }
      if (health?.status !== "ready") throw new Error("后台未能在 30 秒内恢复");
      setRuntimeRestartState("ready");
      appendEvent("runtime_restart_completed", { recordingActive: recordingActiveRef.current }, false);
      if (recordingActiveRef.current) {
        recoveryNeededRef.current = true;
        await recoverLiveCaptions();
      }
    } catch (caught) {
      setRuntimeRestartState("error");
      setError(`后台重启失败：${caught?.message || "无法连接 Gateway"}。请使用一键停止后重新启动。`);
      appendEvent("runtime_restart_failed", { message: caught?.message || "Gateway unavailable" }, false);
    }
  }

  async function recoverLiveCaptions() {
    if (!recordingActiveRef.current || !localSessionRef.current || recoveryInProgressRef.current) return;
    recoveryInProgressRef.current = true;
    recoveryAttemptsRef.current += 1;
    setLiveRecoveryState("recovering");
    // Pause writes, not the microphone or MediaRecorder. The durable count is
    // authoritative if a previous upload succeeded but its response was lost.
    localWriteFailureRef.current = true;
    let pendingSocket = null;
    try {
      await serverWriteQueueRef.current;
      if (!recordingActiveRef.current) return;
      const health = await refreshGatewayHealth();
      if (!health?.liveStream?.available) throw new Error("识别服务尚未就绪");
      const session = await resumeLocalSession(localSessionRef.current.sessionId, chunksRef.current.length, pcmFrameSequenceRef.current);
      localSessionRef.current = session;
      setLocalSession(session);
      let uploadedCount = session.audioChunkCount;
      const backfill = async () => {
        while (uploadedCount < chunksRef.current.length && recordingActiveRef.current) {
          await appendAudioChunk(session.sessionId, uploadedCount + 1, chunksRef.current[uploadedCount], recorderRef.current.mimeType);
          uploadedCount += 1;
        }
      };
      await backfill();
      if (!recordingActiveRef.current) return;
      const provider = translationProviderRef.current;
      assertTranslationSession(session, provider);
      const socket = new LiveCaptionSocket(health.liveStream.webSocketUrl, {
        onEvent: handleLiveEvent, onLocalEvent: handleLocalLiveEvent,
      });
      pendingSocket = socket;
      await socket.connect(session.sessionId, session.metadata?.contextPolicy || "none", 5000, provider);
      await backfill();
      if (socket.socket?.readyState !== WebSocket.OPEN || socket.disconnectReported) {
        throw new Error("录音补存期间字幕连接再次中断，请重试恢复");
      }
      if (!recordingActiveRef.current) {
        return;
      }
      liveSocketRef.current = socket;
      pendingSocket = null;
      audioChunkSequenceRef.current = chunksRef.current.length;
      localWriteFailureRef.current = false;
      recoveryNeededRef.current = false;
      recoveryAttemptsRef.current = 0;
      setLocalSaveState("saving");
      setLiveRecoveryState("recovered");
      setError("字幕连接已恢复，录音已补存；中断期间的字幕缺口已记入日志。");
      appendEvent("stream.resumed", { resumeCount: session.resumeCount, pcmFrameSequence: pcmFrameSequenceRef.current });
    } catch (caught) {
      setLiveRecoveryState("error");
      setError(`字幕恢复未完成：${caught?.message || "Gateway unavailable"}。录音保留在浏览器，请勿刷新；可再次恢复或停止后下载。`);
    } finally {
      try {
        if (pendingSocket) await pendingSocket.stop();
      } finally {
        recoveryInProgressRef.current = false;
      }
    }
  }

  useEffect(() => {
    refreshDevices().catch(() => {});
    refreshGatewayHealth();
    healthTimerRef.current = window.setInterval(async () => {
      const recordingStartedAt = recordingActiveRef.current ? startTimeRef.current : null;
      const health = await refreshGatewayHealth();
      if (recordingStartedAt !== null && recordingActiveRef.current
          && recordingStartedAt === startTimeRef.current) {
        appendEvent("gateway_health_sample", healthObservation(health));
      }
      if (recordingActiveRef.current && health?.status !== "ready") {
        setError((current) => current || "本地字幕服务已降级；录音仍在继续，请查看底部状态。");
      }
      if (recordingActiveRef.current && health?.status === "ready"
          && recoveryNeededRef.current && recoveryAttemptsRef.current < 3) {
        await recoverLiveCaptions();
      }
    }, 5000);
    return () => {
      window.clearInterval(healthTimerRef.current);
      stopResources(false);
    };
  }, []);

  function stopResources(updatePhase = true) {
    recordingActiveRef.current = false;
    recoveryNeededRef.current = false;
    window.clearInterval(timerRef.current);
    window.cancelAnimationFrame(meterFrameRef.current);
    timerRef.current = null;
    meterFrameRef.current = null;

    workletNodeRef.current?.disconnect();
    workletNodeRef.current = null;
    if (recorderRef.current?.state === "recording") recorderRef.current.stop();
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    audioContextRef.current?.close().catch(() => {});
    audioContextRef.current = null;
    setLevel(0);
    if (updatePhase) setPhase("stopped");
  }

  function recordGatewayEvent(event) {
    eventsRef.current.push({ ...event, receivedAt: nowIso(), source: "gateway" });
    setEventCount(eventsRef.current.length);
  }

  function recordCaptionRender(event, renderKind) {
    const receivedAtMs = Date.now();
    const observation = observeCaptionFrame().then(({ observed, reason, atMs: renderedAtMs }) => {
        if (!observed) {
          appendEvent("caption_render_unobserved", {
            segmentId: event.segmentId, renderKind, gatewayEventSequence: event.sequence,
            reason, browserReceivedAt: new Date(receivedAtMs).toISOString(),
          });
          return;
        }
        if (renderKind.startsWith("readable_")) {
          renderKind = `readable_${event.displayKind}${renderedTranslationSegmentsRef.current.has(event.segmentId) ? "" : "_first"}`;
        }
        renderedTranslationSegmentsRef.current.add(event.segmentId);
        appendEvent("caption_rendered", {
          segmentId: event.segmentId,
          renderKind,
          gatewayEventSequence: event.sequence,
          gatewayEventAt: event.at,
          browserReceivedAt: new Date(receivedAtMs).toISOString(),
          browserRenderedAt: new Date(renderedAtMs).toISOString(),
          gatewayToBrowserReceiveMs: event.at ? Math.max(0, receivedAtMs - Date.parse(event.at)) : null,
          browserReceiveToRenderMs: renderedAtMs - receivedAtMs,
          audioEndToBrowserRenderMs: pcmClockStartedAtRef.current && Number.isFinite(event.audioEndMs)
            ? renderedAtMs - pcmClockStartedAtRef.current - event.audioEndMs
            : null,
          presentationPolicy: event.presentationPolicy || null,
          presentationMetrics: event.presentationMetrics || null,
        });
    });
    // Start each bounded observation immediately. A hidden tab cannot build a
    // serial backlog of suspended animation frames that blocks Stop and save.
    renderQueueRef.current = Promise.all([renderQueueRef.current, observation]).then(() => {});
  }

  function handleLiveEvent(event) {
    recordGatewayEvent(event);
    if (event.persistenceFailed || event.type === "storage.failed") {
      recoverableAsrErrorRef.current = false;
      setLocalSaveState("error");
      setError("本地增量保存失败；浏览器录音仍在继续，请勿刷新页面。");
    }
    if (event.type === "stream.ready") {
      setViewerShare(event.viewer || null);
      if (event.displayEligible !== false) {
        setCaptions((current) => applyCaptionEvent(current, event));
      }
      setTranslationState("listening");
    } else if (event.type === "asr.processing") {
      setTranslationState("recognizing");
    } else if (event.type === "asr.empty" || event.type === "asr.suppressed") {
      setTranslationState("listening");
    } else if (event.type === "asr.final") {
      if (recoverableAsrErrorRef.current) {
        recoverableAsrErrorRef.current = false;
        setError("");
      }
      if (event.displayEligible !== false) {
        setCaptions((current) => applyCaptionEvent(current, event));
      }
      setTranslationState("requesting");
      setLiveMetrics((current) => ({
        ...current,
        asrFinalMs: event.uxMetrics?.audioEndToAsrFinalMs,
      }));
    } else if (event.type === "translation.started") {
      activeTranslationSegmentRef.current = event.segmentId || "";
      partialTranslationRef.current = { segmentId: event.segmentId || "", text: "" };
      if (event.displayEligible !== false) {
        setCaptions((current) => applyCaptionEvent(current, { ...event, type: "asr.final" }));
      }
    } else if (event.type === "translation.partial") {
      if (event.segmentId !== activeTranslationSegmentRef.current) {
        appendEvent("caption_partial_rejected", {
          segmentId: event.segmentId,
          reason: "stale_segment",
          gatewayEventSequence: event.sequence,
        });
        return;
      }
      const previous = partialTranslationRef.current;
      const nextText = event.targetTextZh || "";
      if (previous.segmentId === event.segmentId && !nextText.startsWith(previous.text)) {
        appendEvent("caption_partial_rejected", {
          segmentId: event.segmentId,
          reason: "non_append_update",
          gatewayEventSequence: event.sequence,
        });
        return;
      }
      partialTranslationRef.current = { segmentId: event.segmentId, text: nextText };
      if (event.displayEligible !== false) {
        setCaptions((current) => applyCaptionEvent(current, event));
      }
      setTranslationState("streaming");
      setLiveMetrics((current) => ({
        ...current,
        ttftMs: event.uxMetrics?.translationTtftMs ?? event.firstTokenLatencyMs,
        endToFirstTokenMs: event.uxMetrics?.audioEndToChineseFirstTokenMs,
      }));
      if (event.displayEligible !== false && !renderedTranslationSegmentsRef.current.has(event.segmentId)) {
        recordCaptionRender(event, "chinese_first_token");
      }
    } else if (event.type === "translation.final") {
      if (event.segmentId !== activeTranslationSegmentRef.current) return;
      if (event.displayEligible !== false) {
        setCaptions((current) => applyCaptionEvent(current, event));
      }
      setTranslationState("ready");
      setLiveMetrics({
        asrFinalMs: event.uxMetrics?.audioEndToAsrFinalMs,
        ttftMs: event.uxMetrics?.translationTtftMs ?? event.firstTokenLatencyMs,
        translationFinalMs: event.latencyMs,
        endToFirstTokenMs: event.uxMetrics?.audioEndToChineseFirstTokenMs,
        endToChineseFinalMs: event.uxMetrics?.audioEndToChineseFinalMs,
        tokensPerSecond: tokenRate(event.metrics),
      });
      if (event.displayEligible !== false) {
        recordCaptionRender(event, "chinese_final");
      }
    } else if (event.type === "caption.display") {
      setCaptions((current) => applyCaptionEvent(current, event));
      setTranslationState(event.phase === "error" ? "error" : event.displayKind === "final" ? "ready" : "streaming");
      const firstVisible = !renderedTranslationSegmentsRef.current.has(event.segmentId);
      recordCaptionRender(
        event,
        firstVisible
          ? `readable_${event.displayKind}_first`
          : `readable_${event.displayKind}`,
      );
    } else if (event.type === "translation.failed") {
      if (event.displayEligible !== false) {
        setCaptions((current) => applyCaptionEvent(current, event));
      }
      setTranslationState("error");
    } else if (event.type === "translation.skipped") {
      if (event.reason === "insufficient_lexical_content") {
        setTranslationState("listening");
        return;
      }
      if (event.displayEligible !== false) {
        setCaptions((current) => applyCaptionEvent(current, event));
      }
      setTranslationState("error");
    } else if (event.type === "asr.recovered") {
      if (recoverableAsrErrorRef.current) setError("");
      recoverableAsrErrorRef.current = false;
    } else if (event.type === "asr.failed" || event.type === "asr.degraded") {
      recoverableAsrErrorRef.current = true;
      setError(event.message || "本地英文识别暂时不可用；录音仍在继续。");
      setTranslationState("error");
    } else if (event.type === "stream.error" || event.type === "pipeline.failed") {
      recoverableAsrErrorRef.current = false;
      setError(event.message || "本地英文识别暂时不可用；录音仍在继续。");
      setTranslationState("error");
    }
  }

  function handleLocalLiveEvent(event) {
    appendEvent(event.type, event);
    if (event.type === "stream.disconnected") {
      recoverableAsrErrorRef.current = false;
      recoveryNeededRef.current = true;
      setLiveRecoveryState("disconnected");
      setError("实时字幕连接已中断；录音继续，后台就绪后会尝试恢复并补存录音。");
      setTranslationState("error");
    } else if (event.type === "audio.stream_overrun") {
      recoverableAsrErrorRef.current = false;
      setError("实时音频传输出现积压；录音仍在继续，日志已记录丢帧。");
    }
  }

  async function startAudioPipeline(stream) {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) throw new Error("当前浏览器不支持实时 PCM 音频处理。");
    const context = new AudioContextClass();
    await context.resume();
    await context.audioWorklet.addModule("/pcm-capture-worklet.js");
    const source = context.createMediaStreamSource(stream);
    const analyser = context.createAnalyser();
    const worklet = new AudioWorkletNode(context, "pcm-capture-processor", {
      channelCount: 1,
      channelCountMode: "explicit",
    });
    const mute = context.createGain();
    mute.gain.value = 0;
    analyser.fftSize = 512;
    analyser.smoothingTimeConstant = 0.78;
    source.connect(analyser);
    source.connect(worklet);
    worklet.connect(mute);
    mute.connect(context.destination);
    worklet.port.addEventListener("message", (message) => {
      if (message.data instanceof ArrayBuffer) {
        if (!pcmClockStartedAtRef.current) pcmClockStartedAtRef.current = Date.now() - 100;
        pcmFrameSequenceRef.current += 1;
        liveSocketRef.current?.sendPcm(message.data, pcmFrameSequenceRef.current);
      }
    });
    worklet.port.start();
    const samples = new Uint8Array(analyser.fftSize);
    audioContextRef.current = context;
    workletNodeRef.current = worklet;
    context.addEventListener("statechange", () => {
      if (recordingActiveRef.current && context.state !== "running") {
        recoverableAsrErrorRef.current = false;
        appendEvent("audio.context_interrupted", { state: context.state });
        setError("浏览器音频处理已暂停；录音仍在继续，请检查系统音频状态。");
        setTranslationState("error");
      }
    });

    const draw = () => {
      analyser.getByteTimeDomainData(samples);
      let energy = 0;
      for (const sample of samples) {
        const normalized = (sample - 128) / 128;
        energy += normalized * normalized;
      }
      setLevel(Math.min(100, Math.round(Math.sqrt(energy / samples.length) * 360)));
      meterFrameRef.current = window.requestAnimationFrame(draw);
    };
    draw();
  }

  async function startSession() {
    setError("");
    recoverableAsrErrorRef.current = false;
    setRecordingUrl((current) => {
      if (current) URL.revokeObjectURL(current);
      return "";
    });
    setLogUrl((current) => {
      if (current) URL.revokeObjectURL(current);
      return "";
    });
    setRecordingBytes(0);
    setElapsed(0);
    setCaptions(createCaptionState({ zh: "正在连接麦克风…", phase: "requesting" }));
    setTranslationState("idle");
    setLiveMetrics({});
    setViewerShare(null);
    setLocalSession(null);
    setLocalSaveState("creating");
    localSessionRef.current = null;
    audioChunkSequenceRef.current = 0;
    localWriteFailureRef.current = false;
    renderedTranslationSegmentsRef.current = new Set();
    renderQueueRef.current = Promise.resolve();
    pcmClockStartedAtRef.current = 0;
    pcmFrameSequenceRef.current = 0;
    recoveryNeededRef.current = false;
    recoveryAttemptsRef.current = 0;
    setLiveRecoveryState("idle");
    setPhase("requesting");
    eventsRef.current = [];
    setEventCount(0);

    try {
      await serverWriteQueueRef.current;
      serverWriteQueueRef.current = Promise.resolve();
      const health = await refreshGatewayHealth();
      const chosenTranslationProvider = translationProviderRef.current;
      const effectiveContextPolicy = providerContextPolicy(health, chosenTranslationProvider);
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error("当前浏览器不支持麦克风采集。请使用最新版 Safari 或 Chrome。");
      }
      if (!window.MediaRecorder) {
        throw new Error("当前浏览器不支持录音文件生成。请使用最新版 Safari 或 Chrome。");
      }
      const requestedAudioProcessing = {
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: false,
      };
      const audio = selectedDeviceId
        ? { deviceId: { exact: selectedDeviceId }, ...requestedAudioProcessing }
        : requestedAudioProcessing;
      const stream = await requestAudioStream({ audio, video: false });
      streamRef.current = stream;
      await refreshDevices();

      chunksRef.current = [];
      const recorder = new MediaRecorder(stream);
      recorderRef.current = recorder;
      const audioTrack = stream.getAudioTracks()[0];
      const trackSettings = audioTrack?.getSettings() || {};
      const audioCaptureSettings = {
        requested: requestedAudioProcessing,
        applied: {
          echoCancellation: trackSettings.echoCancellation ?? null,
          noiseSuppression: trackSettings.noiseSuppression ?? null,
          autoGainControl: trackSettings.autoGainControl ?? null,
          channelCount: trackSettings.channelCount ?? null,
          sampleRate: trackSettings.sampleRate ?? null,
        },
      };
      const audioMimeType = recorder.mimeType || "audio/webm";
      startTimeRef.current = Date.now();
      recordingActiveRef.current = true;
      audioTrack?.addEventListener("ended", () => {
        if (!recordingActiveRef.current) return;
        recoverableAsrErrorRef.current = false;
        appendEvent("audio.track_ended", {
          audioDeviceId: audioTrack.getSettings().deviceId || "default",
        });
        setError("麦克风连接已中断；请停止并保存本次录音，然后重新选择麦克风。");
        setTranslationState("error");
      });

      let serverSession = null;
      try {
        const result = await startLocalSession({
          mode: "local_live_asr_translation",
          audioMimeType,
          audioDeviceId: audioTrack?.getSettings().deviceId || "default",
          audioDeviceLabel: audioTrack?.label || "default",
          audioCaptureSettings,
          contextPolicy: effectiveContextPolicy,
          translationProvider: chosenTranslationProvider,
        });
        serverSession = result;
        localSessionRef.current = result;
        setLocalSession(result);
        setLocalSaveState("saving");
        appendEvent("local_session_created", {
          localSessionId: result.sessionId,
          localDirectory: result.directory,
        });
      } catch (caught) {
        recordLocalStorageFailure(caught);
      }

      recorder.addEventListener("dataavailable", (event) => {
        if (event.data.size < 1) return;
        chunksRef.current.push(event.data);
        audioChunkSequenceRef.current = chunksRef.current.length;
        if (!serverSession || localWriteFailureRef.current) return;
        const sequence = chunksRef.current.length;
        enqueueServerWrite(async () => {
          await appendAudioChunk(
            serverSession.sessionId,
            sequence,
            event.data,
            audioMimeType,
          );
        });
      });
      recorder.addEventListener("stop", () => {
        const blob = new Blob(chunksRef.current, { type: audioMimeType });
        setRecordingBytes(blob.size);
        setRecordingUrl(URL.createObjectURL(blob));
      });
      recorder.start(1000);

      appendEvent("session_started", {
        mode: "local_live_asr_translation",
        asrSource: "microphone_pcm_stream",
        translationGateway: GATEWAY_URL,
        contextPolicy: effectiveContextPolicy,
        translationProvider: chosenTranslationProvider,
        localSessionId: serverSession?.sessionId || null,
        audioDeviceId: audioTrack?.getSettings().deviceId || "default",
        audioCaptureSettings,
      });
      appendEvent("gateway_health", { health });
      if (serverSession && health?.liveStream?.webSocketUrl) {
        try {
          assertTranslationSession(serverSession, chosenTranslationProvider);
          const liveSocket = new LiveCaptionSocket(health.liveStream.webSocketUrl, {
            onEvent: handleLiveEvent,
            onLocalEvent: handleLocalLiveEvent,
          });
          await liveSocket.connect(serverSession.sessionId, effectiveContextPolicy, 5000, chosenTranslationProvider);
          liveSocketRef.current = liveSocket;
        } catch (caught) {
          recoverableAsrErrorRef.current = false;
          recoveryNeededRef.current = true;
          setLiveRecoveryState("disconnected");
          setError(`${caught?.message || "实时 ASR 连接失败"}；本次仍会保存录音。`);
        }
      } else {
        recoverableAsrErrorRef.current = false;
        setError("实时 ASR Gateway 未就绪；本次仍会保存录音。");
      }
      await startAudioPipeline(stream);
      setPhase("running");
      timerRef.current = window.setInterval(() => {
        setElapsed(Date.now() - startTimeRef.current);
      }, 250);
    } catch (caught) {
      recoverableAsrErrorRef.current = false;
      stopResources(false);
      const message = caught?.name === "NotAllowedError"
        ? "麦克风权限被拒绝。请在浏览器地址栏或系统设置中允许此页面使用麦克风。"
        : caught?.message || "无法启动麦克风。";
      setError(message);
      setPhase("error");
      appendEvent("session_error", { message });
    }
  }

  async function stopSession() {
    if (phase !== "running") return;
    setPhase("stopping");
    recordingActiveRef.current = false;
    recoveryNeededRef.current = false;
    const durationMs = Date.now() - startTimeRef.current;
    appendEvent("session_stopped", { durationMs });
    if (localSessionRef.current && !localWriteFailureRef.current) {
      setLocalSaveState("finalizing");
    }
    window.clearInterval(timerRef.current);
    window.cancelAnimationFrame(meterFrameRef.current);
    workletNodeRef.current?.disconnect();
    workletNodeRef.current = null;
    const recorder = recorderRef.current;
    const recorderStopped = recorder?.state === "recording"
      ? new Promise((resolve) => recorder.addEventListener("stop", resolve, { once: true }))
      : Promise.resolve();
    if (recorder?.state === "recording") recorder.stop();
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    audioContextRef.current?.close().catch(() => {});
    audioContextRef.current = null;
    setLevel(0);

    const liveSocket = liveSocketRef.current;
    let livePipelineDrained = false;
    let streamStopResult = null;
    try {
      streamStopResult = await liveSocket?.stop();
      if (liveSocket) {
        livePipelineDrained = streamStopResult?.workerDrained === true
          && streamStopResult?.storageHealthy !== false;
      }
    } catch (caught) {
      appendEvent("stream_stop_failed", { message: caught?.message || "stream stop failed" });
    }
    if (!livePipelineDrained) {
      appendEvent("stream_drain_incomplete", { streamStopResult });
      setError("最后一段字幕未能安全完成；录音将保存为可恢复但不完整的 session。");
    }
    liveSocketRef.current = null;
    await recorderStopped;
    while (recoveryInProgressRef.current) {
      await new Promise((resolve) => window.setTimeout(resolve, 100));
    }
    await renderQueueRef.current;
    await serverWriteQueueRef.current;
    if (localSessionRef.current && localWriteFailureRef.current) {
      try {
        // A stop during reconnect still saves all original chunks, including
        // MediaRecorder's final chunk. It never claims an uninterrupted stream.
        const restored = await resumeLocalSession(localSessionRef.current.sessionId, chunksRef.current.length);
        for (let index = restored.audioChunkCount; index < chunksRef.current.length; index += 1) {
          await appendAudioChunk(restored.sessionId, index + 1, chunksRef.current[index], recorder.mimeType);
        }
        localSessionRef.current = restored;
        localWriteFailureRef.current = false;
        livePipelineDrained = false;
      } catch (caught) {
        setLocalSaveState("error");
        setError(`录音尚未全部存入后台：${caught?.message || "Gateway unavailable"}。请下载浏览器录音与日志。`);
      }
    }
    if (localSessionRef.current && !localWriteFailureRef.current) {
      try {
        const result = await finalizeLocalSession(localSessionRef.current.sessionId, {
          durationMs,
          stoppedAt: nowIso(),
          status: livePipelineDrained ? "completed" : "incomplete",
        });
        localSessionRef.current = result;
        setLocalSession(result);
        setLocalSaveState(result.status === "completed" ? "saved" : "incomplete");
      } catch (caught) {
        recordLocalStorageFailure(caught);
      }
    }
    const manifest = {
      schemaVersion: 1,
      mode: "local_live_asr_translation",
      warning: "English is local ASR and Chinese is local MiLMMT output; neither is human reviewed.",
      startedAt: eventsRef.current[0]?.at || nowIso(),
      stoppedAt: nowIso(),
      durationMs: Date.now() - startTimeRef.current,
      eventCount: eventsRef.current.length,
      localSession: localSessionRef.current,
      events: eventsRef.current,
    };
    setLogUrl(downloadUrl(`${JSON.stringify(manifest, null, 2)}\n`, "application/json"));
    setTranslationState("idle");
    setPhase("stopped");
  }

  return (
    <main className="live-shell">
      <header className="control-bar" aria-label="现场字幕控制">
        <div className="identity">
          <span className="kicker">LOCAL LIVE CAPTION POC</span>
          <strong>本地证道字幕</strong>
        </div>

        <label className="device-field">
          <span>麦克风</span>
          <select
            value={selectedDeviceId}
            onChange={(event) => setSelectedDeviceId(event.target.value)}
            disabled={isRunning || isBusy || modelStarting}
          >
            {devices.length === 0 && <option value="">系统默认麦克风</option>}
            {devices.map((device, index) => (
              <option key={device.deviceId || index} value={device.deviceId}>
                {device.label || `麦克风 ${index + 1}`}
              </option>
            ))}
          </select>
        </label>

        <div className="translation-field">
          <label className="device-field" htmlFor="translation-provider">
            <span>翻译模型</span>
            <select id="translation-provider"
            value={selectedTranslationProvider}
            onChange={(event) => { setSelectedTranslationProvider(event.target.value); setError(""); }}
            disabled={isRunning || isBusy || modelStarting}
          >
            <option value="ollama">MiLMMT Q8 · 当前默认</option>
            <option value={V41_TRANSLATION_PROVIDER}>v4.1 Q5 · 实验候选</option>
            </select>
          </label>
          {isExperimentalTranslation && !selectedModelStatus.ready && !isRunning && (
            <button type="button" className="start-model" onClick={startExperimentalModel}
              disabled={isBusy || modelStarting || !selectedModelStatus.startSupported}>
              {modelStarting ? "模型加载中…" : selectedModelStatus.startSupported ? "启动 v4.1 模型"
                : gatewayHealth?.translationProviders ? "模型启动环境未就绪" : "等待 Gateway 连接"}
            </button>
          )}
        </div>

        <div className="level-block" aria-label={`麦克风音量 ${level}%`}>
          <span>输入</span>
          <div className="level-track" aria-hidden="true">
            <div className="level-value" style={{ width: `${Math.max(3, level)}%` }} />
          </div>
          <strong>{isRunning ? (level < 4 ? "过低" : level > 86 ? "过高" : "正常") : "待机"}</strong>
        </div>

        <div className="session-state" aria-live="polite">
          <span>{status}</span>
          <strong>{formatDuration(elapsed)}</strong>
        </div>

        <div className="actions">
          {!isRunning ? (
            <button className="primary-action" onClick={startSession} disabled={isBusy || modelStarting}>
              {isBusy ? "连接中…" : phase === "stopped" ? "开始新录音" : "开始录音与字幕"}
            </button>
          ) : (
            <button className="stop-action" onClick={stopSession}>停止并保存</button>
          )}
        </div>
      </header>

      <section className="caption-stage" aria-labelledby="caption-title">
        <div className="stage-meta">
          <span id="caption-title">实时字幕</span>
          <span className="demo-notice">
            {captionDemo
              ? "界面演示数据 · 非模型输出"
              : isRunning
                ? `麦克风 · ${asrModelName} · ${translationModelName}`
                : "麦克风录音 + 本地模型集成 POC"}
          </span>
        </div>

        {isExperimentalTranslation && <p className="experimental-notice" role="note">
          v4.1 实验候选 · 神学质量门未通过，译文未经人工确认。本次仅在本机显示与保存。
          {!selectedModelStatus.ready && " 模型未就绪，录音仍可独立保存。"}
        </p>}

        <div className={`caption-copy ${visibleCaptions.previousFinal ? "has-previous" : ""}`}>
          {visibleCaptions.previousFinal && (
            <div className="previous-caption" aria-label="前一句字幕">
              <p className="previous-zh" lang="zh-CN">{visibleCaptions.previousFinal.zh}</p>
              <p className="previous-en" lang="en">{visibleCaptions.previousFinal.en}</p>
            </div>
          )}
          {visibleCaptions.previousFinal && <div className="caption-divider" aria-hidden="true" />}
          <div className="active-caption" aria-live="polite" aria-atomic="true">
            <p className="zh-caption" lang="zh-CN">
              {captionDemo
                ? visibleCaptions.active.zh
                : phase === "idle" || phase === "error"
                  ? "选择麦克风，然后开始录音。"
                  : phase === "requesting"
                    ? "正在连接麦克风…"
                    : phase === "stopped"
                      ? localSaveState === "incomplete"
                        ? "录音已保存，但最后一段字幕不完整。"
                        : "本次录音已经安全停止。"
                      : visibleCaptions.active.zh || "正在翻译…"}
            </p>
            <p className="en-caption" lang="en">
              {captionDemo || isRunning
                ? visibleCaptions.active.en
                : "English transcript will appear here."}
            </p>
          </div>
        </div>

        {error && <p className="error-banner" role="alert">{error}</p>}
        {isRunning && ["disconnected", "error", "recovering"].includes(liveRecoveryState) && (
          <button type="button" onClick={recoverLiveCaptions} disabled={liveRecoveryState === "recovering"}>
            {liveRecoveryState === "recovering" ? "正在恢复字幕与保存…" : "恢复字幕与保存"}
          </button>
        )}
        {isRunning && viewerUrl && (
          <aside className="viewer-share" aria-label="手机字幕分享">
            {viewerQr && <img src={viewerQr} alt="手机字幕二维码" />}
            <div>
              <strong>{viewerRoute !== "lan" && viewerShare.publicUrl ? "手机公网字幕" : "手机局域网字幕"}</strong>
              <span>
                {viewerRoute !== "lan" && viewerShare.publicUrl
                  ? "可直接使用蜂窝网络扫码；这是只读页面，无法控制后台。"
                  : "连接同一 Wi-Fi 后扫码；这是只读页面，无法控制后台。"}
              </span>
              {viewerShare.publicUrl && viewerShare.urls.some((url) => url !== viewerShare.publicUrl) && (
                <label>连接方式 <select value={viewerRoute} onChange={(event) => setViewerRoute(event.target.value)}>
                  <option value="public">公网 / 蜂窝网络</option>
                  <option value="lan">局域网 / 同一 Wi-Fi</option>
                </select></label>
              )}
              <a href={viewerUrl} target="_blank" rel="noreferrer">{viewerUrl}</a>
            </div>
          </aside>
        )}
      </section>

      <footer className="health-bar" aria-label="运行状态">
        <div className="health-items">
          <span data-state={isRunning ? "active" : "idle"}>录音 {isRunning ? "进行中" : phase === "stopped" ? "已停止" : "待机"}</span>
          <span data-state={gatewayHealth?.asr?.available ? "active" : "pending"}>
            语音识别模型（ASR） {gatewayHealth?.asr?.available ? asrModelName : "未就绪"}
            {Number.isFinite(liveMetrics.asrFinalMs) ? ` · 识别完成 ${liveMetrics.asrFinalMs}ms` : ""}
          </span>
          <span data-state={translationState === "ready" || translationState === "streaming" ? "active" : translationState === "error" ? "pending" : "idle"}>
            翻译模型 {translationModelName}
            {Number.isFinite(liveMetrics.ttftMs) ? ` · 首字 ${liveMetrics.ttftMs}ms` : translationState === "requesting" ? " · 等待首字" : ""}
            {Number.isFinite(liveMetrics.tokensPerSecond) ? ` · ${liveMetrics.tokensPerSecond} token/秒` : ""}
            {Number.isFinite(liveMetrics.translationFinalMs) ? ` · 完整 ${liveMetrics.translationFinalMs}ms` : ""}
          </span>
          <span data-state={Number.isFinite(liveMetrics.endToFirstTokenMs) ? "active" : "idle"}>
            字幕延迟：{Number.isFinite(liveMetrics.endToFirstTokenMs) ? `首字 ${liveMetrics.endToFirstTokenMs}ms` : "开始讲话后显示"}
            {Number.isFinite(liveMetrics.endToChineseFinalMs) ? ` · 完整 ${liveMetrics.endToChineseFinalMs}ms` : ""}
          </span>
          <span data-state={selectedGatewayHealth?.status === "ready" ? "active" : "pending"}>
            Gateway {selectedGatewayHealth?.status === "ready" ? "就绪" : selectedGatewayHealth?.status === "offline" ? "离线" : "未就绪"}
          </span>
          <span
            data-state={!isExperimentalTranslation && gatewayHealth?.publicViewer?.configured && !gatewayHealth.publicViewer.lastError ? "active" : "idle"}
            title={isExperimentalTranslation ? "实验模型仅本机显示与保存" : gatewayHealth?.publicViewer?.lastError || ""}
          >
            公网分享 {isExperimentalTranslation ? "实验会话关闭" : gatewayHealth?.publicViewer?.configured
              ? gatewayHealth.publicViewer.lastError
                ? "降级"
                : "就绪"
              : "未配置"}
            {!isExperimentalTranslation && gatewayHealth?.publicViewer?.configured
              ? ` · 队列 ${gatewayHealth.publicViewer.queueDepth || 0}`
              : ""}
          </span>
          <span data-state={localSaveState === "saved" || localSaveState === "saving" ? "active" : localSaveState === "error" || localSaveState === "incomplete" ? "pending" : "idle"}>
            本地保存 {localSaveState === "creating" ? "建目录" : localSaveState === "saving" ? "增量写入" : localSaveState === "finalizing" ? "完成中" : localSaveState === "saved" ? "已完成" : localSaveState === "incomplete" ? "可恢复/不完整" : localSaveState === "error" ? "浏览器备份" : "待机"}
          </span>
          <span>
            Context {contextPolicy}{gatewayHealth?.contentPack ? ` · Pack ${gatewayHealth.contentPack.packVersion}` : ""}
          </span>
        </div>
        <div className="evidence">
          <span>事件 {eventCount}</span>
          {localSession && <span title={localSession.directory}>会话 {localSession.sessionId.slice(-8)}</span>}
          {recordingUrl && (
            <a href={recordingUrl} download={`local-live-${Date.now()}.webm`}>
              下载录音 {recordingBytes > 0 ? `${Math.max(1, Math.round(recordingBytes / 1024))} KB` : ""}
            </a>
          )}
          {logUrl && <a href={logUrl} download={`local-live-${Date.now()}.json`}>下载日志</a>}
          <button
            className="restart-backend"
            type="button"
            onClick={restartBackend}
            disabled={runtimeRestartState === "restarting"}
          >
            {runtimeRestartState === "restarting" ? "后台重启中…" : "重启后台"}
          </button>
        </div>
      </footer>
    </main>
  );
}
