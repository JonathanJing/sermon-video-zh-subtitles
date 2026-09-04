export const PCM_BYTES_PER_FRAME = 3200;
export const MAX_BUFFERED_PCM_BYTES = PCM_BYTES_PER_FRAME * 20;

export function encodePcmFrame(sequence, pcmBuffer) {
  if (!Number.isInteger(sequence) || sequence < 1) {
    throw new Error("PCM sequence must be a positive integer");
  }
  if (!(pcmBuffer instanceof ArrayBuffer) || pcmBuffer.byteLength !== PCM_BYTES_PER_FRAME) {
    throw new Error(`PCM frame must contain ${PCM_BYTES_PER_FRAME} bytes`);
  }
  const wire = new ArrayBuffer(PCM_BYTES_PER_FRAME + 4);
  new DataView(wire).setUint32(0, sequence, false);
  new Uint8Array(wire, 4).set(new Uint8Array(pcmBuffer));
  return wire;
}

export class LiveCaptionSocket {
  constructor(url, { onEvent = () => {}, onLocalEvent = () => {} } = {}) {
    this.url = url;
    this.onEvent = onEvent;
    this.onLocalEvent = onLocalEvent;
    this.socket = null;
    this.sequence = 0;
    this.closedResolver = null;
    this.closedTimer = null;
    this.stopping = false;
    this.disconnectReported = false;
  }

  resolveClosed(result) {
    window.clearTimeout(this.closedTimer);
    this.closedTimer = null;
    const resolver = this.closedResolver;
    this.closedResolver = null;
    resolver?.(result);
  }

  connect(sessionId, contextPolicy = "none", timeoutMs = 5000) {
    return new Promise((resolve, reject) => {
      const socket = new WebSocket(this.url);
      this.socket = socket;
      this.stopping = false;
      this.disconnectReported = false;
      let settled = false;
      socket.binaryType = "arraybuffer";
      const timeout = window.setTimeout(() => {
        if (settled) return;
        settled = true;
        socket.close();
        reject(new Error("实时音频连接超时"));
      }, timeoutMs);
      socket.addEventListener("open", () => {
        if (settled) return;
        settled = true;
        window.clearTimeout(timeout);
        socket.send(JSON.stringify({
          type: "stream.start",
          schemaVersion: 1,
          sessionId,
          contextPolicy,
          encoding: "pcm_s16le",
          sampleRateHz: 16000,
          channels: 1,
          frameDurationMs: 100,
        }));
        resolve();
      }, { once: true });
      socket.addEventListener("message", (message) => {
        if (typeof message.data !== "string") return;
        try {
          const event = JSON.parse(message.data);
          this.onEvent(event);
          if (event.type === "stream.closed") this.resolveClosed(event);
        } catch {
          this.onLocalEvent({ type: "stream.invalid_event" });
        }
      });
      socket.addEventListener("error", () => {
        window.clearTimeout(timeout);
        if (!settled) {
          settled = true;
          reject(new Error("无法连接本地实时字幕 Gateway"));
        } else if (!this.stopping && !this.disconnectReported) {
          this.disconnectReported = true;
          this.onLocalEvent({ type: "stream.disconnected", reason: "socket_error" });
        }
      });
      socket.addEventListener("close", (event) => {
        if (!this.stopping && !this.disconnectReported) {
          this.disconnectReported = true;
          this.onLocalEvent({
            type: "stream.disconnected",
            reason: "socket_closed",
            code: event.code,
          });
        }
        this.resolveClosed({
          type: "stream.closed",
          workerDrained: false,
          reason: "socket_closed_before_drain_confirmation",
        });
      });
    });
  }

  sendPcm(pcmBuffer) {
    this.sequence += 1;
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) return false;
    if (this.socket.bufferedAmount > MAX_BUFFERED_PCM_BYTES) {
      this.onLocalEvent({
        type: "audio.stream_overrun",
        frameSequence: this.sequence,
        bufferedBytes: this.socket.bufferedAmount,
      });
      return false;
    }
    this.socket.send(encodePcmFrame(this.sequence, pcmBuffer));
    return true;
  }

  async stop(timeoutMs = 95000) {
    const socket = this.socket;
    if (!socket || socket.readyState > WebSocket.OPEN) {
      return { type: "stream.closed", workerDrained: false, reason: "socket_not_open" };
    }
    this.stopping = true;
    const drained = new Promise((resolve) => {
      this.closedResolver = resolve;
      this.closedTimer = window.setTimeout(() => resolve({
        type: "stream.closed",
        workerDrained: false,
        reason: "drain_timeout",
      }), timeoutMs);
    });
    if (socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "stream.stop" }));
    }
    const result = await drained;
    if (socket.readyState < WebSocket.CLOSING) socket.close(1000, "session stopped");
    this.socket = null;
    this.resolveClosed(result);
    return result;
  }
}
