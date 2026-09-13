import { SCHEMA, WIRE_BYTES, encodeFrame, decodeFrame, syntheticFrame, sampleStats,
  boundedMapSet, outputEstimate } from "./protocol.mjs";

const $ = (id) => document.getElementById(id);
const fragment = new URLSearchParams(location.hash.slice(1));
if (fragment.get("token")) $("token").value = fragment.get("token");
if (["loopback", "admin", "user"].includes(fragment.get("role"))) $("role").value = fragment.get("role");
history.replaceState(null, "", location.pathname);

let socket = null, authenticated = false, role = "", epoch = 0, running = false, starting = false;
let outputContext = null, playbackNode = null, inputContext = null, captureNode = null, microphone = null;
let pingTimer = null, synthTimer = null, clockTimer = null, runStartedAt = 0, pingId = 0, sequence = 0;
let lastSummary = null, peers = [], inputDrops = 0, sent = 0, received = 0, played = 0;
let startGeneration = 0;
let authenticationTimer = null, lastPongAt = 0;
const MAX_SEND_BUFFER_BYTES = 64 * 1024;
const PONG_TIMEOUT_MS = 8000;
const pendingPings = new Map(), sourceFrames = new Map(), receiveTimes = new Map();
const liveMetrics = { transportRttMs: [], mediaReceiveAckRttMs: [], mediaPlaybackAckRttMs: [], playbackAckMinusReceiveAckMs: [] };

function status(message) { $("status").textContent = message; }
function terminateTransport(reason) {
  const closingSocket = socket;
  // This path must never enqueue stream.stop or another control message.
  disconnected();
  if (closingSocket && closingSocket.readyState < WebSocket.CLOSING) {
    try { closingSocket.close(1008, reason); } catch { /* Already unavailable. */ }
  }
  status(reason === "pong_timeout" ? "8 秒未收到 pong；已停止探针、清空队列并关闭连接。"
    : reason === "send_buffer_limit" ? "发送缓存超过预算；已停止探针、清空队列并关闭连接。"
    : "媒体连接未能保持就绪；已停止探针并清空队列，请重新连接。");
}
function send(value) {
  if (!authenticated) return false;
  if (socket?.readyState !== WebSocket.OPEN) { terminateTransport("socket_not_open"); return false; }
  const wire = JSON.stringify(value);
  const bytes = new TextEncoder().encode(wire).byteLength;
  if (bytes > 2048 || socket.bufferedAmount + bytes > MAX_SEND_BUFFER_BYTES) {
    terminateTransport("send_buffer_limit");
    return false;
  }
  try { socket.send(wire); return true; }
  catch { terminateTransport("socket_send_failed"); return false; }
}
function startHeartbeat() {
  clearInterval(pingTimer);
  lastPongAt = performance.now();
  pingTimer = setInterval(() => {
    if (!authenticated) { clearInterval(pingTimer); pingTimer = null; return; }
    if (performance.now() - lastPongAt >= PONG_TIMEOUT_MS) { terminateTransport("pong_timeout"); return; }
    const id = ++pingId;
    boundedMapSet(pendingPings, id, performance.now(), 32);
    send({ type: "ping", id });
  }, 500);
}
function addMetric(name, value) {
  if (!Number.isFinite(value)) return;
  const list = liveMetrics[name];
  if (!list) return;
  if (list.length >= 1200) list.shift();
  list.push(value);
}
function refreshMetrics() {
  for (const [id, key] of [["rtt", "transportRttMs"], ["receive-rtt", "mediaReceiveAckRttMs"], ["play-rtt", "mediaPlaybackAckRttMs"], ["ack-delta", "playbackAckMinusReceiveAckMs"]]) {
    const summary = sampleStats(liveMetrics[key]);
    $(id).textContent = summary.count ? `${summary.p50.toFixed(1)} ms` : "—";
  }
  $("counts").textContent = `发送 ${sent} · 接收 ${received} · 播放处理回执 ${played} · 本端发送丢弃 ${inputDrops}`;
}
function refreshButtons() {
  const source = role === "admin" || role === "loopback";
  const receiverReady = role === "loopback" ? outputContext?.state === "running"
    : peers.some((peer) => peer.role === "user" && peer.playbackReady);
  $("connect").disabled = Boolean(socket);
  $("disconnect").disabled = !socket;
  for (const id of ["role", "device", "network", "token", "token-file"]) $(id).disabled = Boolean(socket);
  $("audio").disabled = !authenticated || role === "admin" || outputContext?.state === "running";
  $("start").disabled = !authenticated || !source || running || starting || !receiverReady;
  $("stop").disabled = !running && !starting;
  $("input-mode").disabled = running || starting || role === "user";
  $("duration").disabled = running || starting || role === "user";
}
function stopInput() {
  clearInterval(synthTimer); synthTimer = null;
  captureNode?.port.postMessage({ type: "stop" });
  captureNode?.disconnect(); captureNode = null;
  microphone?.getTracks().forEach((track) => track.stop()); microphone = null;
  inputContext?.close().catch(() => {}); inputContext = null;
}
function resetPlayback(nextEpoch = 0) {
  playbackNode?.port.postMessage({ type: "reset", epoch: nextEpoch });
  receiveTimes.clear();
}
function stopLocal(notify = true) {
  startGeneration += 1;
  running = false; starting = false;
  stopInput(); resetPlayback();
  clearInterval(clockTimer); clockTimer = null;
  if (notify) send({ type: "stop" });
  epoch = 0;
  sourceFrames.clear();
  refreshButtons();
}
function disconnected() {
  stopLocal(false);
  clearInterval(pingTimer); pingTimer = null;
  clearTimeout(authenticationTimer); authenticationTimer = null;
  pendingPings.clear();
  authenticated = false; socket = null; peers = [];
  outputContext?.close().catch(() => {}); outputContext = null; playbackNode = null;
  status("连接已关闭；探针与待播队列已停止。可重新连接或下载已有摘要。");
  refreshButtons();
}

async function enableOutput() {
  const Context = window.AudioContext || window.webkitAudioContext;
  if (!Context) throw new Error("浏览器不支持 WebAudio");
  outputContext = outputContext || new Context();
  await outputContext.resume();
  if (!playbackNode) {
    await outputContext.audioWorklet.addModule("/playback-worklet.js");
    playbackNode = new AudioWorkletNode(outputContext, "media-probe-playback", { numberOfInputs: 0, numberOfOutputs: 1, outputChannelCount: [1] });
    playbackNode.connect(outputContext.destination);
    playbackNode.port.onmessage = ({ data }) => {
      if (!running || data.epoch !== epoch) return;
      if (data.type === "underrun") {
        send({ type: "playback_underrun", epoch });
        return;
      }
      if (data.type === "dropped") {
        receiveTimes.delete(data.sequence);
        send({ type: "playback_drop", epoch, sequence: data.sequence });
        return;
      }
      if (data.type !== "played") return;
      const receivedAt = receiveTimes.get(data.sequence);
      if (receivedAt === undefined) return;
      receiveTimes.delete(data.sequence);
      played += 1;
      send({ type: "played", epoch, sequence: data.sequence,
        receiveToRenderCallbackMs: performance.now() - receivedAt,
        receiveToOutputEstimateMs: outputEstimate(outputContext, data.renderedAudioTime, receivedAt),
        baseLatencyMs: Number.isFinite(outputContext.baseLatency) ? outputContext.baseLatency * 1000 : null,
        outputLatencyMs: Number.isFinite(outputContext.outputLatency) ? outputContext.outputLatency * 1000 : null });
      refreshMetrics();
    };
    outputContext.addEventListener("statechange", () => {
      const ready = outputContext?.state === "running";
      if (!ready && running) { stopLocal(); status("音频输出已暂停；本轮探针已停止。"); }
      send({ type: "playback_ready", ready });
      refreshButtons();
    });
  }
  if (outputContext.state !== "running") throw new Error("请再次点击启用播放，允许浏览器输出音频。");
  send({ type: "playback_ready", ready: true });
  status("接收播放已启用。准备开始探针。");
  refreshButtons();
}

async function prepareMicrophone(ticket) {
  const Context = window.AudioContext || window.webkitAudioContext;
  const requestedStream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1,
    echoCancellation: true, noiseSuppression: false, autoGainControl: false }, video: false });
  if (ticket !== startGeneration || !starting || !authenticated) {
    requestedStream.getTracks().forEach((track) => track.stop());
    return false;
  }
  microphone = requestedStream;
  inputContext = new Context();
  const requestedContext = inputContext;
  await requestedContext.resume();
  await requestedContext.audioWorklet.addModule("/capture-worklet.js");
  if (ticket !== startGeneration || !starting || !authenticated) {
    requestedStream.getTracks().forEach((track) => track.stop());
    requestedContext.close().catch(() => {});
    return false;
  }
  const source = inputContext.createMediaStreamSource(microphone);
  captureNode = new AudioWorkletNode(inputContext, "media-probe-capture", { channelCount: 1, channelCountMode: "explicit" });
  const mute = inputContext.createGain(); mute.gain.value = 0;
  source.connect(captureNode); captureNode.connect(mute); mute.connect(inputContext.destination);
  captureNode.port.onmessage = ({ data }) => {
    if (running && data instanceof ArrayBuffer) emitPcm(new Int16Array(data));
  };
  microphone.getAudioTracks().forEach((track) => track.addEventListener("ended", () => {
    if (running) { stopLocal(); status("麦克风已断开；本轮探针已停止。"); }
  }));
  return true;
}

function emitPcm(pcm) {
  if (!running || !epoch || socket?.readyState !== WebSocket.OPEN) return;
  sequence += 1;
  if (socket.bufferedAmount > WIRE_BYTES * 10) { inputDrops += 1; refreshMetrics(); return; }
  const sentAt = performance.now();
  boundedMapSet(sourceFrames, sequence, { sentAt, receivedAt: null, playedAt: null });
  socket.send(encodeFrame(epoch, sequence, pcm));
  sent += 1;
  refreshMetrics();
}

function handleBinary(wire) {
  if (!running || !playbackNode || outputContext?.state !== "running") return;
  const frame = decodeFrame(wire);
  if (frame.epoch !== epoch) return;
  boundedMapSet(receiveTimes, frame.sequence, performance.now());
  received += 1;
  send({ type: "received", epoch, sequence: frame.sequence });
  playbackNode.port.postMessage({ type: "frame", ...frame }, [frame.pcm.buffer]);
  refreshMetrics();
}

function observeFrameAck(event) {
  if (!running || event.epoch !== epoch) return;
  const frame = sourceFrames.get(event.sequence);
  if (!frame) return;
  const at = performance.now();
  const name = event.stage === "received" ? "mediaReceiveAckRttMs" : "mediaPlaybackAckRttMs";
  const value = at - frame.sentAt;
  addMetric(name, value);
  send({ type: "observation", epoch, sequence: event.sequence, name, value });
  if (event.stage === "received") frame.receivedAt = at;
  else frame.playedAt = at;
  if (frame.receivedAt !== null && frame.playedAt !== null) {
    const delta = frame.playedAt - frame.receivedAt;
    addMetric("playbackAckMinusReceiveAckMs", delta);
    send({ type: "observation", epoch, sequence: event.sequence, name: "playbackAckMinusReceiveAckMs", value: delta });
    sourceFrames.delete(event.sequence);
  }
  refreshMetrics();
}

function showSummary(summary) {
  if (!summary) return;
  lastSummary = summary;
  $("summary").textContent = JSON.stringify(summary, null, 2);
  $("download").disabled = false;
}

function onControl(event) {
  if (event.type === "authenticated") {
    authenticated = true;
    clearTimeout(authenticationTimer); authenticationTimer = null;
    status(`已连接 ${event.hostLabel} · ${event.role} · 令牌剩余约 ${event.expiresInSeconds} 秒`);
    // A protocol close can precede the queued stopped event; recover its saved
    // summary after reconnect. showSummary deliberately ignores an empty reply.
    if (!send({ type: "summary" })) return;
    startHeartbeat();
  } else if (event.type === "peers") {
    peers = event.peers;
    $("peers").textContent = peers.map((peer) => `${peer.role} · ${peer.deviceClaim} · ${peer.playbackReady ? "播放就绪" : "等待"}`).join(" / ");
  } else if (event.type === "pong") {
    const began = pendingPings.get(event.id);
    if (began !== undefined) {
      lastPongAt = performance.now();
      const value = performance.now() - began;
      pendingPings.delete(event.id); addMetric("transportRttMs", value);
      send({ type: "rtt", id: event.id, value }); refreshMetrics();
    }
  } else if (event.type === "started") {
    epoch = event.epoch; running = true; starting = false; sequence = 0;
    sent = 0; received = 0; played = 0; inputDrops = 0;
    sourceFrames.clear(); receiveTimes.clear();
    for (const values of Object.values(liveMetrics)) values.length = 0;
    resetPlayback(epoch);
    runStartedAt = performance.now();
    if (role !== "user" && ["synthetic", "synthetic_silent"].includes(event.mode)) {
      synthTimer = setInterval(() => emitPcm(syntheticFrame(sequence + 1, { silent: event.mode === "synthetic_silent" })), 100);
    }
    clockTimer = setInterval(() => {
      const elapsed = ((performance.now() - runStartedAt) / 1000).toFixed(1);
      status(`${event.hostLabel} · ${event.mode} · ${elapsed} / ${event.durationSeconds} 秒`);
    }, 250);
    refreshMetrics();
  } else if (event.type === "media_ack") {
    observeFrameAck(event);
  } else if (event.type === "stopped") {
    stopLocal(false); showSummary(event.summary);
    status(`本轮结束：${event.summary.stopReason}。${event.summarySaved ? "服务器已保存摘要。" : "服务器未保存摘要，请下载。"}`);
  } else if (event.type === "summary") {
    showSummary(event.summary);
  } else if (event.type === "notice") {
    starting = false; stopInput(); status("接收端尚未启用播放。请先点击启用接收播放。");
  }
  refreshButtons();
}

$("connect").onclick = () => {
  const token = $("token").value.trim();
  if (!/^[A-Za-z0-9_-]{43,128}$/.test(token)) { status("请输入有效的短期令牌。"); return; }
  role = $("role").value;
  const connectingSocket = new WebSocket(`${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/ws`);
  socket = connectingSocket;
  connectingSocket.binaryType = "arraybuffer";
  authenticationTimer = setTimeout(() => {
    if (socket === connectingSocket && !authenticated) terminateTransport("authentication_timeout");
  }, PONG_TIMEOUT_MS);
  connectingSocket.onopen = () => {
    if (socket !== connectingSocket) return;
    try { connectingSocket.send(JSON.stringify({ type: "auth", schemaVersion: SCHEMA, token,
      role, device: $("device").value, network: $("network").value })); }
    catch { terminateTransport("authentication_send_failed"); }
  };
  connectingSocket.onmessage = ({ data }) => {
    if (socket !== connectingSocket) return;
    try { if (typeof data === "string") onControl(JSON.parse(data)); else handleBinary(data); }
    catch { stopLocal(); status("探针协议异常；本轮已停止。"); }
  };
  connectingSocket.onerror = () => { if (socket === connectingSocket) terminateTransport("socket_error"); };
  connectingSocket.onclose = () => { if (socket === connectingSocket) disconnected(); };
  status("正在建立媒体连接…"); refreshButtons();
};
$("audio").onclick = () => enableOutput().catch(() => { status("无法启用音频播放，请检查浏览器支持并再次点击。"); refreshButtons(); });
$("start").onclick = async () => {
  if (running || starting) return;
  starting = true; refreshButtons();
  const ticket = ++startGeneration;
  try {
    const mode = $("input-mode").value;
    if (mode === "microphone" && !await prepareMicrophone(ticket)) return;
    if (ticket !== startGeneration || !starting || !authenticated) return;
    send({ type: "start", mode, durationSeconds: Number($("duration").value) });
    status("正在开始探针…");
  } catch {
    if (ticket !== startGeneration) return;
    starting = false; stopInput(); status("麦克风无法启动；请检查权限或选择合成短音。"); refreshButtons();
  }
};
$("token-file").onchange = async () => {
  const file = $("token-file").files?.[0];
  if (!file || socket) return;
  if (file.size > 256) { status("令牌文件大小不符。"); return; }
  try {
    const token = (await file.text()).trim();
    if (!/^[A-Za-z0-9_-]{43,128}$/.test(token)) { status("令牌文件格式不符。"); return; }
    if (socket) return;
    $("token").value = token;
    status("已在本页导入令牌；文件未上传。");
  } catch { status("无法读取令牌文件。"); }
  finally { $("token-file").value = ""; }
};
$("stop").onclick = () => { stopLocal(); status("已清空本端采音与播放队列，正在保存摘要…"); };
$("disconnect").onclick = () => { stopLocal(); socket?.close(1000, "operator_disconnect"); };
$("copy-link").onclick = async () => {
  if (!/^[A-Za-z0-9_-]{43,128}$/.test($("token").value.trim())) { status("请先载入短期令牌。"); return; }
  const link = `${location.origin}/#${new URLSearchParams({ token: $("token").value.trim(), role: "user" })}`;
  try { await navigator.clipboard.writeText(link); status("已复制短期接收端链接；令牌在 URL fragment 中，不进入 HTTP 请求。"); }
  catch { status("浏览器不允许复制；请使用原始私有链接。"); }
};
$("download").onclick = () => {
  if (!lastSummary) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(lastSummary, null, 2) + "\n"], { type: "application/json" }));
  const anchor = document.createElement("a"); anchor.href = url; anchor.download = `media-probe-${lastSummary.hostLabel}-${lastSummary.runId}.json`;
  anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
};
document.addEventListener("visibilitychange", () => {
  if (document.hidden && (running || starting)) { stopLocal(); status("页面已进入后台，本轮已停止；未补发后台音频。"); }
});
window.addEventListener("pagehide", () => { stopLocal(); socket?.close(1000, "page_hidden"); });
refreshButtons();
