import { useEffect, useMemo, useRef, useState } from "react";
import {
  GATEWAY_URL,
  appendAudioChunk,
  appendSessionEvent,
  finalizeLocalSession,
  getGatewayHealth,
  restartGateway,
  startLocalSession,
} from "./gatewayClient.js";
import { LiveCaptionSocket } from "./liveSocket.js";

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
  const [elapsed, setElapsed] = useState(0);
  const [level, setLevel] = useState(0);
  const [caption, setCaption] = useState({ en: "", zh: "选择麦克风，然后开始录音。" });
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
  const pcmClockStartedAtRef = useRef(0);
  const recoverableAsrErrorRef = useRef(false);

  const isRunning = phase === "running";
  const isBusy = phase === "requesting" || phase === "stopping";
  const asrModelName = compactModelName(
    gatewayHealth?.asr?.modelPath || gatewayHealth?.asr?.provider,
    "ASR",
  );
  const translationModelName = compactModelName(
    gatewayHealth?.ollama?.configuredModel,
    "MiLMMT",
  );

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
      return health;
    } catch (caught) {
      setGatewayHealth({ status: "offline", message: caught?.message || "Gateway unavailable" });
      return null;
    }
  }

  async function restartBackend() {
    if (runtimeRestartState === "restarting") return;
    if (recordingActiveRef.current && !window.confirm(
      "浏览器录音会继续，但当前后台会话可能不完整。建议重启成功后停止并保存，再开始新录音。仍要重启后台吗？",
    )) return;

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
        setLocalSaveState("incomplete");
        setError("后台已重启，浏览器录音仍在继续；请停止并保存，然后开始新录音。");
      }
    } catch (caught) {
      setRuntimeRestartState("error");
      setError(`后台重启失败：${caught?.message || "无法连接 Gateway"}。请使用一键停止后重新启动。`);
      appendEvent("runtime_restart_failed", { message: caught?.message || "Gateway unavailable" }, false);
    }
  }

  useEffect(() => {
    refreshDevices().catch(() => {});
    refreshGatewayHealth();
    healthTimerRef.current = window.setInterval(async () => {
      const health = await refreshGatewayHealth();
      if (recordingActiveRef.current && health?.status !== "ready") {
        setError((current) => current || "本地字幕服务已降级；录音仍在继续，请查看底部状态。");
      }
    }, 5000);
    return () => {
      window.clearInterval(healthTimerRef.current);
      stopResources(false);
    };
  }, []);

  function stopResources(updatePhase = true) {
    recordingActiveRef.current = false;
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
    window.requestAnimationFrame(() => {
      const renderedAtMs = Date.now();
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
      });
    });
  }

  function handleLiveEvent(event) {
    recordGatewayEvent(event);
    if (event.persistenceFailed || event.type === "storage.failed") {
      recoverableAsrErrorRef.current = false;
      setLocalSaveState("error");
      setError("本地增量保存失败；浏览器录音仍在继续，请勿刷新页面。");
    }
    if (event.type === "stream.ready") {
      setCaption({ en: "Listening for English speech…", zh: "请开始讲话。" });
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
      activeTranslationSegmentRef.current = event.segmentId || "";
      partialTranslationRef.current = { segmentId: event.segmentId || "", text: "" };
      setCaption((current) => ({ en: event.sourceTextEn || "", zh: current.zh }));
      setTranslationState("requesting");
      setLiveMetrics((current) => ({
        ...current,
        asrFinalMs: event.uxMetrics?.audioEndToAsrFinalMs,
      }));
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
      setCaption({ en: event.sourceTextEn || "", zh: nextText });
      setTranslationState("streaming");
      setLiveMetrics((current) => ({
        ...current,
        ttftMs: event.uxMetrics?.translationTtftMs ?? event.firstTokenLatencyMs,
        endToFirstTokenMs: event.uxMetrics?.audioEndToChineseFirstTokenMs,
      }));
      if (!renderedTranslationSegmentsRef.current.has(event.segmentId)) {
        renderedTranslationSegmentsRef.current.add(event.segmentId);
        recordCaptionRender(event, "chinese_first_token");
      }
    } else if (event.type === "translation.final") {
      if (event.segmentId !== activeTranslationSegmentRef.current) return;
      setCaption({ en: event.sourceTextEn || "", zh: event.targetTextZh || "翻译结果为空。" });
      setTranslationState("ready");
      setLiveMetrics({
        asrFinalMs: event.uxMetrics?.audioEndToAsrFinalMs,
        ttftMs: event.uxMetrics?.translationTtftMs ?? event.firstTokenLatencyMs,
        translationFinalMs: event.latencyMs,
        endToFirstTokenMs: event.uxMetrics?.audioEndToChineseFirstTokenMs,
        endToChineseFinalMs: event.uxMetrics?.audioEndToChineseFinalMs,
        tokensPerSecond: tokenRate(event.metrics),
      });
      recordCaptionRender(event, "chinese_final");
    } else if (event.type === "translation.failed") {
      setCaption({ en: event.sourceTextEn || "", zh: "翻译暂时不可用，请查看英文原文。" });
      setTranslationState("error");
    } else if (event.type === "translation.skipped") {
      setCaption({ en: event.sourceTextEn || "", zh: "翻译积压，暂时显示英文原文。" });
      setTranslationState("error");
    } else if (event.type === "asr.failed") {
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
      setError("实时字幕连接已中断；浏览器录音仍在继续。请停止并保存后重新开始。");
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
        liveSocketRef.current?.sendPcm(message.data);
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
    setCaption({ en: "", zh: "正在连接麦克风…" });
    setTranslationState("idle");
    setLiveMetrics({});
    setLocalSession(null);
    setLocalSaveState("creating");
    localSessionRef.current = null;
    audioChunkSequenceRef.current = 0;
    localWriteFailureRef.current = false;
    renderedTranslationSegmentsRef.current = new Set();
    pcmClockStartedAtRef.current = 0;
    setPhase("requesting");
    eventsRef.current = [];
    setEventCount(0);

    try {
      await serverWriteQueueRef.current;
      serverWriteQueueRef.current = Promise.resolve();
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
          contextPolicy: "none",
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
        if (!serverSession || localWriteFailureRef.current) return;
        const sequence = audioChunkSequenceRef.current + 1;
        audioChunkSequenceRef.current = sequence;
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
        contextPolicy: "none",
        localSessionId: serverSession?.sessionId || null,
        audioDeviceId: audioTrack?.getSettings().deviceId || "default",
        audioCaptureSettings,
      });
      const health = await refreshGatewayHealth();
      appendEvent("gateway_health", { health });
      if (serverSession && health?.liveStream?.webSocketUrl) {
        try {
          const liveSocket = new LiveCaptionSocket(health.liveStream.webSocketUrl, {
            onEvent: handleLiveEvent,
            onLocalEvent: handleLocalLiveEvent,
          });
          await liveSocket.connect(serverSession.sessionId, "none");
          liveSocketRef.current = liveSocket;
        } catch (caught) {
          recoverableAsrErrorRef.current = false;
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
    let livePipelineDrained = !liveSocket;
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
    await serverWriteQueueRef.current;
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
      warning: "English is local Whisper ASR and Chinese is local MiLMMT output; neither is human reviewed.",
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
            disabled={isRunning || isBusy}
          >
            {devices.length === 0 && <option value="">系统默认麦克风</option>}
            {devices.map((device, index) => (
              <option key={device.deviceId || index} value={device.deviceId}>
                {device.label || `麦克风 ${index + 1}`}
              </option>
            ))}
          </select>
        </label>

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
            <button className="primary-action" onClick={startSession} disabled={isBusy}>
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
            {isRunning ? `麦克风 · ${asrModelName} · ${translationModelName}` : "麦克风录音 + 本地模型集成 POC"}
          </span>
        </div>

        <div className="caption-copy" aria-live="polite" aria-atomic="true">
          <p className="zh-caption" lang="zh-CN">
            {phase === "idle" || phase === "error"
              ? "选择麦克风，然后开始录音。"
              : phase === "requesting"
                ? "正在连接麦克风…"
                : phase === "stopped"
                  ? localSaveState === "incomplete"
                    ? "录音已保存，但最后一段字幕不完整。"
                    : "本次录音已经安全停止。"
                  : caption.zh}
          </p>
          <p className="en-caption" lang="en">
            {isRunning ? caption.en : "English transcript will appear here."}
          </p>
        </div>

        {error && <p className="error-banner" role="alert">{error}</p>}
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
          <span data-state={gatewayHealth?.status === "ready" ? "active" : "pending"}>
            Gateway {gatewayHealth?.status === "ready" ? "就绪" : gatewayHealth?.status === "offline" ? "离线" : "未就绪"}
          </span>
          <span data-state={localSaveState === "saved" || localSaveState === "saving" ? "active" : localSaveState === "error" || localSaveState === "incomplete" ? "pending" : "idle"}>
            本地保存 {localSaveState === "creating" ? "建目录" : localSaveState === "saving" ? "增量写入" : localSaveState === "finalizing" ? "完成中" : localSaveState === "saved" ? "已完成" : localSaveState === "incomplete" ? "可恢复/不完整" : localSaveState === "error" ? "浏览器备份" : "待机"}
          </span>
          <span>
            Context none{gatewayHealth?.contentPack ? ` · Pack ${gatewayHealth.contentPack.packVersion} 可用` : ""}
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
