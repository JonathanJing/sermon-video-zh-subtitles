import { useEffect, useMemo, useRef, useState } from "react";

const GATEWAY_URL = import.meta.env.VITE_GATEWAY_URL || "http://127.0.0.1:8766";

const DEMO_TRANSCRIPTS = [
  {
    segmentId: "demo_0001",
    en: "God's people are standing at the edge of the promised land.",
  },
  {
    segmentId: "demo_0002",
    en: "The question is not only where we are going, but who we are becoming.",
  },
  {
    segmentId: "demo_0003",
    en: "Grace does not ignore the truth; grace leads us through it.",
  },
];

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

  const streamRef = useRef(null);
  const recorderRef = useRef(null);
  const chunksRef = useRef([]);
  const eventsRef = useRef([]);
  const timerRef = useRef(null);
  const captionTimerRef = useRef(null);
  const startTimeRef = useRef(0);
  const audioContextRef = useRef(null);
  const meterFrameRef = useRef(null);
  const sessionTokenRef = useRef(0);
  const cursorSequenceRef = useRef(null);

  const isRunning = phase === "running";
  const isBusy = phase === "requesting";

  const status = useMemo(() => {
    if (phase === "running") return "正在录音 · A0 本地翻译";
    if (phase === "requesting") return "正在连接麦克风";
    if (phase === "stopped") return "本次录音已停止";
    if (phase === "error") return "需要处理麦克风问题";
    return "准备开始";
  }, [phase]);

  function appendEvent(type, detail = {}) {
    eventsRef.current.push({
      schemaVersion: 1,
      sequence: eventsRef.current.length + 1,
      at: nowIso(),
      elapsedMs: startTimeRef.current ? Date.now() - startTimeRef.current : 0,
      type,
      ...detail,
    });
    setEventCount(eventsRef.current.length);
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
      const response = await fetch(`${GATEWAY_URL}/api/health`);
      if (!response.ok) throw new Error(`Gateway HTTP ${response.status}`);
      const health = await response.json();
      setGatewayHealth(health);
      return health;
    } catch (caught) {
      setGatewayHealth({ status: "offline", message: caught?.message || "Gateway unavailable" });
      return null;
    }
  }

  useEffect(() => {
    refreshDevices().catch(() => {});
    refreshGatewayHealth();
    return () => stopResources(false);
  }, []);

  function stopResources(updatePhase = true) {
    window.clearInterval(timerRef.current);
    window.clearTimeout(captionTimerRef.current);
    window.cancelAnimationFrame(meterFrameRef.current);
    timerRef.current = null;
    captionTimerRef.current = null;
    meterFrameRef.current = null;

    if (recorderRef.current?.state === "recording") recorderRef.current.stop();
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    audioContextRef.current?.close().catch(() => {});
    audioContextRef.current = null;
    sessionTokenRef.current += 1;
    setLevel(0);
    setTranslationState("idle");
    if (updatePhase) setPhase("stopped");
  }

  async function translateStableTranscript(transcript, sessionToken) {
    if (sessionToken !== sessionTokenRef.current) return;
    const requestStartedAt = performance.now();
    setCaption({ en: transcript.en, zh: "正在生成中文字幕…" });
    setTranslationState("requesting");
    appendEvent("stable_transcript_final", {
      segmentId: transcript.segmentId,
      source: "demo_replay",
      sourceTextEn: transcript.en,
    });
    appendEvent("translation_requested", {
      segmentId: transcript.segmentId,
      contextPolicy: "none",
      cursorSequence: cursorSequenceRef.current,
    });

    try {
      const response = await fetch(`${GATEWAY_URL}/api/translate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sourceTextEn: transcript.en,
          cursorSequence: cursorSequenceRef.current,
          contextPolicy: "none",
        }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.message || `Translation HTTP ${response.status}`);
      if (sessionToken !== sessionTokenRef.current) return;
      const latencyMs = Math.round(performance.now() - requestStartedAt);
      setCaption({ en: transcript.en, zh: result.targetTextZh || "翻译结果为空。" });
      setTranslationState("ready");
      if (result.alignment?.confidence === "high" || result.alignment?.confidence === "exact") {
        cursorSequenceRef.current = result.alignment.suggestedCursor;
      }
      appendEvent("translation_completed", {
        segmentId: transcript.segmentId,
        sourceTextEn: transcript.en,
        targetTextZh: result.targetTextZh,
        latencyMs,
        model: result.model,
        promptVersion: result.promptVersion,
        requestedContextPolicy: result.requestedContextPolicy,
        contextPolicy: result.contextPolicy,
        contextHitIds: result.contextHitIds,
        alignment: result.alignment,
        modelMetrics: result.metrics,
      });
    } catch (caught) {
      if (sessionToken !== sessionTokenRef.current) return;
      const latencyMs = Math.round(performance.now() - requestStartedAt);
      const message = caught?.message || "本地翻译不可用";
      setCaption({ en: transcript.en, zh: "翻译暂时不可用，请查看英文原文。" });
      setTranslationState("error");
      appendEvent("translation_failed", {
        segmentId: transcript.segmentId,
        latencyMs,
        message,
        recordingShouldContinue: true,
      });
    }
  }

  async function runDemoTranscriptLoop(sessionToken, index = 0) {
    await translateStableTranscript(DEMO_TRANSCRIPTS[index], sessionToken);
    if (sessionToken !== sessionTokenRef.current) return;
    captionTimerRef.current = window.setTimeout(() => {
      runDemoTranscriptLoop(sessionToken, (index + 1) % DEMO_TRANSCRIPTS.length);
    }, 1800);
  }

  function startMeter(stream) {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) return;
    const context = new AudioContextClass();
    const source = context.createMediaStreamSource(stream);
    const analyser = context.createAnalyser();
    analyser.fftSize = 512;
    analyser.smoothingTimeConstant = 0.78;
    source.connect(analyser);
    const samples = new Uint8Array(analyser.fftSize);
    audioContextRef.current = context;

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
    cursorSequenceRef.current = null;
    setPhase("requesting");
    eventsRef.current = [];
    setEventCount(0);

    try {
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error("当前浏览器不支持麦克风采集。请使用最新版 Safari 或 Chrome。");
      }
      const audio = selectedDeviceId
        ? { deviceId: { exact: selectedDeviceId }, echoCancellation: true, noiseSuppression: true }
        : { echoCancellation: true, noiseSuppression: true };
      const stream = await requestAudioStream({ audio, video: false });
      streamRef.current = stream;
      await refreshDevices();
      startMeter(stream);

      chunksRef.current = [];
      if (window.MediaRecorder) {
        const recorder = new MediaRecorder(stream);
        recorderRef.current = recorder;
        recorder.addEventListener("dataavailable", (event) => {
          if (event.data.size > 0) chunksRef.current.push(event.data);
        });
        recorder.addEventListener("stop", () => {
          const mimeType = recorder.mimeType || "audio/webm";
          const blob = new Blob(chunksRef.current, { type: mimeType });
          setRecordingBytes(blob.size);
          setRecordingUrl(URL.createObjectURL(blob));
        });
        recorder.start(1000);
      }

      startTimeRef.current = Date.now();
      const sessionToken = sessionTokenRef.current + 1;
      sessionTokenRef.current = sessionToken;
      appendEvent("session_started", {
        mode: "local_translation_demo",
        asrSource: "demo_replay",
        translationGateway: GATEWAY_URL,
        contextPolicy: "none",
        audioDeviceId: stream.getAudioTracks()[0]?.getSettings().deviceId || "default",
      });
      const health = await refreshGatewayHealth();
      appendEvent("gateway_health", { health });
      setPhase("running");
      timerRef.current = window.setInterval(() => {
        setElapsed(Date.now() - startTimeRef.current);
      }, 250);
      runDemoTranscriptLoop(sessionToken);
    } catch (caught) {
      stopResources(false);
      const message = caught?.name === "NotAllowedError"
        ? "麦克风权限被拒绝。请在浏览器地址栏或系统设置中允许此页面使用麦克风。"
        : caught?.message || "无法启动麦克风。";
      setError(message);
      setPhase("error");
      appendEvent("session_error", { message });
    }
  }

  function stopSession() {
    appendEvent("session_stopped", { durationMs: Date.now() - startTimeRef.current });
    const manifest = {
      schemaVersion: 1,
      mode: "local_translation_demo",
      warning: "Chinese is local-model output; English is demo replay until local ASR is connected.",
      startedAt: eventsRef.current[0]?.at || nowIso(),
      stoppedAt: nowIso(),
      durationMs: Date.now() - startTimeRef.current,
      eventCount: eventsRef.current.length,
      events: eventsRef.current,
    };
    setLogUrl(downloadUrl(`${JSON.stringify(manifest, null, 2)}\n`, "application/json"));
    stopResources(true);
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
            {isRunning ? "测试英文回放 · MiLMMT A0 本地翻译" : "麦克风录音 + 本地模型集成 POC"}
          </span>
        </div>

        <div className="caption-copy" aria-live="polite" aria-atomic="true">
          <p className="zh-caption" lang="zh-CN">
            {phase === "idle" || phase === "error"
              ? "选择麦克风，然后开始录音。"
              : phase === "requesting"
                ? "正在连接麦克风…"
                : phase === "stopped"
                  ? "本次录音已经安全停止。"
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
          <span data-state="pending">ASR 测试英文回放</span>
          <span data-state={translationState === "ready" ? "active" : translationState === "error" ? "pending" : "idle"}>
            翻译 {translationState === "ready" ? "MiLMMT A0" : translationState === "requesting" ? "生成中" : translationState === "error" ? "已降级" : "待机"}
          </span>
          <span data-state={gatewayHealth?.status === "ready" ? "active" : "pending"}>
            Gateway {gatewayHealth?.status === "ready" ? "就绪" : gatewayHealth?.status === "offline" ? "离线" : "未就绪"}
          </span>
          <span>Context A0 / none</span>
        </div>
        <div className="evidence">
          <span>事件 {eventCount}</span>
          {recordingUrl && (
            <a href={recordingUrl} download={`local-live-${Date.now()}.webm`}>
              下载录音 {recordingBytes > 0 ? `${Math.max(1, Math.round(recordingBytes / 1024))} KB` : ""}
            </a>
          )}
          {logUrl && <a href={logUrl} download={`local-live-${Date.now()}.json`}>下载日志</a>}
        </div>
      </footer>
    </main>
  );
}
