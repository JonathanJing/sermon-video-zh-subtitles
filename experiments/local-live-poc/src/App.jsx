import { useEffect, useMemo, useRef, useState } from "react";

const DEMO_CAPTIONS = [
  {
    en: "God's people are standing at the edge of the promised land.",
    zh: "神的百姓正站在应许之地的边缘。",
  },
  {
    en: "The question is not only where we are going, but who we are becoming.",
    zh: "问题不只是我们要去哪里，更是我们正在成为怎样的人。",
  },
  {
    en: "Grace does not ignore the truth; grace leads us through it.",
    zh: "恩典并不回避真理，而是带领我们经过真理。",
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
  const [captionIndex, setCaptionIndex] = useState(0);
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

  const currentCaption = DEMO_CAPTIONS[captionIndex];
  const isRunning = phase === "running";
  const isBusy = phase === "requesting";

  const status = useMemo(() => {
    if (phase === "running") return "正在录音 · 界面演示";
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

  useEffect(() => {
    refreshDevices().catch(() => {});
    return () => stopResources(false);
  }, []);

  function stopResources(updatePhase = true) {
    window.clearInterval(timerRef.current);
    window.clearInterval(captionTimerRef.current);
    window.cancelAnimationFrame(meterFrameRef.current);
    timerRef.current = null;
    captionTimerRef.current = null;
    meterFrameRef.current = null;

    if (recorderRef.current?.state === "recording") recorderRef.current.stop();
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    audioContextRef.current?.close().catch(() => {});
    audioContextRef.current = null;
    setLevel(0);
    if (updatePhase) setPhase("stopped");
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
    setCaptionIndex(0);
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
      appendEvent("session_started", {
        mode: "ui_demo",
        audioDeviceId: stream.getAudioTracks()[0]?.getSettings().deviceId || "default",
      });
      setPhase("running");
      timerRef.current = window.setInterval(() => {
        setElapsed(Date.now() - startTimeRef.current);
      }, 250);
      captionTimerRef.current = window.setInterval(() => {
        setCaptionIndex((current) => {
          const next = (current + 1) % DEMO_CAPTIONS.length;
          appendEvent("demo_caption_final", DEMO_CAPTIONS[next]);
          return next;
        });
      }, 3200);
      appendEvent("demo_caption_final", DEMO_CAPTIONS[0]);
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
      mode: "ui_demo",
      warning: "Captions are interface demo data, not local model output.",
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
          <span className="demo-notice">界面演示数据 · 尚未连接本地模型</span>
        </div>

        <div className="caption-copy" aria-live="polite" aria-atomic="true">
          <p className="zh-caption">
            {phase === "idle" || phase === "error"
              ? "选择麦克风，然后开始录音。"
              : phase === "requesting"
                ? "正在连接麦克风…"
                : phase === "stopped"
                  ? "本次录音已经安全停止。"
                  : currentCaption.zh}
          </p>
          <p className="en-caption">
            {isRunning ? currentCaption.en : "English transcript will appear here."}
          </p>
        </div>

        {error && <p className="error-banner" role="alert">{error}</p>}
      </section>

      <footer className="health-bar" aria-label="运行状态">
        <div className="health-items">
          <span data-state={isRunning ? "active" : "idle"}>录音 {isRunning ? "进行中" : phase === "stopped" ? "已停止" : "待机"}</span>
          <span data-state="pending">ASR 待接本地服务</span>
          <span data-state="pending">翻译 待接本地服务</span>
          <span>Context 未配置</span>
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
