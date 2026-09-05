import assert from "node:assert/strict";
import test from "node:test";

import {
  appendAudioChunk,
  restartGateway,
  startLocalSession,
  translateCaption,
} from "../../src/gatewayClient.js";
import { encodePcmFrame, LiveCaptionSocket, PCM_BYTES_PER_FRAME } from "../../src/liveSocket.js";
import { V41_TRANSLATION_PROVIDER as V41 } from "../../src/translationProvider.js";

function response(payload, { ok = true, status = 200 } = {}) {
  return {
    ok,
    status,
    json: async () => payload,
  };
}

test("startLocalSession sends one JSON request", async () => {
  let observed;
  const result = await startLocalSession(
    { audioMimeType: "audio/webm" },
    async (url, options) => {
      observed = { url, options };
      return response({ sessionId: "session-1" }, { status: 201 });
    },
  );

  assert.equal(result.sessionId, "session-1");
  assert.match(observed.url, /\/api\/sessions\/start$/);
  assert.equal(observed.options.method, "POST");
  assert.deepEqual(JSON.parse(observed.options.body), { audioMimeType: "audio/webm" });
});

test("restartGateway requests a supervised local restart", async () => {
  let observed;
  const result = await restartGateway(async (url, options) => {
    observed = { url, options };
    return response({ status: "restarting" }, { status: 202 });
  });

  assert.equal(result.status, "restarting");
  assert.match(observed.url, /\/api\/runtime\/restart$/);
  assert.equal(observed.options.method, "POST");
  assert.deepEqual(JSON.parse(observed.options.body), {});
});

test("appendAudioChunk preserves sequence, content type, and body", async () => {
  const chunk = new Blob(["audio"]);
  let observed;
  await appendAudioChunk("session-1", 3, chunk, "audio/webm;codecs=opus", async (url, options) => {
    observed = { url, options };
    return response({ audioChunkCount: 3 });
  });

  assert.match(observed.url, /\/api\/sessions\/session-1\/audio\?sequence=3$/);
  assert.equal(observed.options.headers["Content-Type"], "audio/webm;codecs=opus");
  assert.equal(observed.options.body, chunk);
});

test("translation errors expose the gateway message", async () => {
  await assert.rejects(
    translateCaption(
      { sourceTextEn: "Grace leads us." },
      async () => response({ message: "model unavailable" }, { ok: false, status: 503 }),
    ),
    /model unavailable/,
  );
});

test("encodePcmFrame prefixes a network-order sequence", () => {
  const pcm = new ArrayBuffer(PCM_BYTES_PER_FRAME);
  new Uint8Array(pcm)[0] = 42;
  const encoded = encodePcmFrame(258, pcm);
  assert.equal(encoded.byteLength, PCM_BYTES_PER_FRAME + 4);
  assert.equal(new DataView(encoded).getUint32(0, false), 258);
  assert.equal(new Uint8Array(encoded)[4], 42);
});

class FakeWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  static instances = [];
  static startReply = { type: "stream.ready" };

  constructor() {
    this.readyState = FakeWebSocket.CONNECTING;
    this.bufferedAmount = 0;
    this.listeners = new Map();
    this.sent = [];
    FakeWebSocket.instances.push(this);
    queueMicrotask(() => {
      if (this.readyState !== FakeWebSocket.CONNECTING) return;
      this.readyState = FakeWebSocket.OPEN;
      this.emit("open", {});
    });
  }

  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) || [];
    listeners.push(listener);
    this.listeners.set(type, listeners);
  }

  emit(type, event) {
    for (const listener of this.listeners.get(type) || []) listener(event);
  }

  send(payload) {
    this.sent.push(payload);
    if (typeof payload === "string" && JSON.parse(payload).type === "stream.start" && FakeWebSocket.startReply) {
      queueMicrotask(() => this.emit("message", { data: JSON.stringify(FakeWebSocket.startReply) }));
    }
  }

  close(code = 1000) {
    this.readyState = FakeWebSocket.CLOSED;
    this.emit("close", { code });
  }
}

async function withFakeWebSocket(run) {
  const previousWindow = globalThis.window;
  const previousWebSocket = globalThis.WebSocket;
  globalThis.window = { setTimeout, clearTimeout };
  globalThis.WebSocket = FakeWebSocket;
  FakeWebSocket.instances = [];
  FakeWebSocket.startReply = { type: "stream.ready" };
  try {
    await run();
  } finally {
    globalThis.window = previousWindow;
    globalThis.WebSocket = previousWebSocket;
  }
}

function v41StreamReady() {
  return {
    type: "stream.ready",
    translationProvider: V41,
    translationSelectionSchema: "local-live-translation-selection-v1",
    experimental: true,
    viewer: { disabledReason: "experimental_local_only", urls: [], publicUrl: null },
  };
}

test("PCM and caption callbacks wait for a valid handshake for every provider", async () => {
  for (const provider of ["ollama", V41]) {
    await withFakeWebSocket(async () => {
      FakeWebSocket.startReply = null;
      const events = [];
      const live = new LiveCaptionSocket("ws://test/api/live", { onEvent: (event) => events.push(event) });
      const pcm = new ArrayBuffer(PCM_BYTES_PER_FRAME);
      assert.equal(live.sendPcm(pcm), false);
      const connecting = live.connect("session-1", "none", 5000, provider);
      const socket = FakeWebSocket.instances[0];
      assert.equal(live.sendPcm(pcm), false);
      await new Promise((resolve) => setImmediate(resolve));
      assert.equal(socket.readyState, FakeWebSocket.OPEN);
      assert.equal(live.sendPcm(pcm), false);
      socket.emit("message", { data: JSON.stringify({ type: "translation.final", targetTextZh: "未确认的字幕" }) });
      assert.deepEqual(events, []);
      assert.equal(socket.sent.filter((payload) => payload instanceof ArrayBuffer).length, 0);

      const start = JSON.parse(socket.sent[0]);
      assert.equal(start.type, "stream.start");
      assert.equal(start.contextPolicy, "none");
      if (provider === V41) {
        assert.equal(start.translationProvider, V41);
        assert.equal(start.translationSelectionSchema, "local-live-translation-selection-v1");
      } else {
        assert.equal("translationProvider" in start, false);
        assert.equal("translationSelectionSchema" in start, false);
      }
      const ready = provider === V41 ? v41StreamReady() : { type: "stream.ready" };
      socket.emit("message", { data: JSON.stringify(ready) });
      await connecting;
      assert.deepEqual(events, [ready]);
      assert.equal(live.sendPcm(pcm, 258), true);
      const frames = socket.sent.filter((payload) => payload instanceof ArrayBuffer);
      assert.equal(frames.length, 1);
      assert.equal(new DataView(frames[0]).getUint32(0, false), 258);
      const final = { type: "translation.final", targetTextZh: "已确认的字幕" };
      socket.emit("message", { data: JSON.stringify(final) });
      assert.deepEqual(events, [ready, final]);
      socket.close();
      assert.equal(live.sendPcm(pcm), false);
    });
  }
});

test("v4.1 rejects legacy, forged or shareable stream.ready without PCM or caption callbacks", async () => {
  const variants = [
    ["legacy handshake", () => ({ type: "stream.ready" })],
    ["missing provider", (ready) => { delete ready.translationProvider; return ready; }],
    ["wrong provider", (ready) => ({ ...ready, translationProvider: "ollama" })],
    ["missing selection schema", (ready) => { delete ready.translationSelectionSchema; return ready; }],
    ["wrong selection schema", (ready) => ({ ...ready, translationSelectionSchema: "local-live-translation-selection-v999" })],
    ["missing experimental status", (ready) => { delete ready.experimental; return ready; }],
    ["non-experimental status", (ready) => ({ ...ready, experimental: false })],
    ["missing viewer restrictions", (ready) => { delete ready.viewer; return ready; }],
    ["wrong disabled reason", (ready) => ({ ...ready, viewer: { ...ready.viewer, disabledReason: "disabled" } })],
    ["missing LAN URL list", (ready) => { delete ready.viewer.urls; return ready; }],
    ["LAN sharing URL", (ready) => ({ ...ready, viewer: { ...ready.viewer, urls: ["http://192.0.2.1/viewer/token"] } })],
    ["public sharing URL", (ready) => ({ ...ready, viewer: { ...ready.viewer, publicUrl: "https://example.invalid/viewer/token" } })],
    ["missing public sharing restriction", (ready) => { delete ready.viewer.publicUrl; return ready; }],
  ];
  for (const [label, mutate] of variants) {
    await withFakeWebSocket(async () => {
      FakeWebSocket.startReply = null;
      const events = [];
      const live = new LiveCaptionSocket("ws://test/api/live", { onEvent: (event) => events.push(event) });
      const connecting = assert.rejects(live.connect("candidate-session", "none", 5000, V41), /Gateway 未确认 v4\.1 本机实验协议/, label);
      await new Promise((resolve) => setImmediate(resolve));
      const socket = FakeWebSocket.instances[0];
      assert.equal(live.sendPcm(new ArrayBuffer(PCM_BYTES_PER_FRAME)), false, label);
      socket.emit("message", { data: JSON.stringify(mutate(v41StreamReady())) });
      await connecting;
      assert.equal(socket.readyState, FakeWebSocket.CLOSED, label);
      assert.equal(live.sendPcm(new ArrayBuffer(PCM_BYTES_PER_FRAME)), false, label);
      socket.emit("message", { data: JSON.stringify({ type: "translation.final", targetTextZh: "拒绝后字幕" }) });
      assert.deepEqual(events, [], label);
      assert.equal(socket.sent.filter((payload) => payload instanceof ArrayBuffer).length, 0, label);
    });
  }
});

test("unexpected WebSocket close emits a visible disconnect event", async () => {
  await withFakeWebSocket(async () => {
    const localEvents = [];
    const live = new LiveCaptionSocket("ws://test/api/live", {
      onLocalEvent: (event) => localEvents.push(event),
    });
    await live.connect("session-1");
    FakeWebSocket.instances[0].close(1006);
    assert.equal(localEvents[0].type, "stream.disconnected");
    assert.equal(localEvents[0].code, 1006);
  });
});

test("stop returns the backend drain confirmation", async () => {
  await withFakeWebSocket(async () => {
    const live = new LiveCaptionSocket("ws://test/api/live");
    await live.connect("session-1");
    const socket = FakeWebSocket.instances[0];
    const stopping = live.stop(100);
    socket.emit("message", {
      data: JSON.stringify({ type: "stream.closed", workerDrained: true, storageHealthy: true }),
    });
    const result = await stopping;
    assert.equal(result.workerDrained, true);
    assert.equal(result.storageHealthy, true);
  });
});

test("stop timeout returns an incomplete drain result", async () => {
  await withFakeWebSocket(async () => {
    const live = new LiveCaptionSocket("ws://test/api/live");
    await live.connect("session-1");
    const result = await live.stop(10);
    assert.equal(result.workerDrained, false);
    assert.equal(result.reason, "drain_timeout");
  });
});

test("connect waits for the gateway session handshake after the WebSocket opens", async () => {
  await withFakeWebSocket(async () => {
    FakeWebSocket.startReply = null;
    const live = new LiveCaptionSocket("ws://test/api/live");
    let connected = false;
    const connecting = live.connect("session-1").then(() => { connected = true; });
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(connected, false);
    const socket = FakeWebSocket.instances[0];
    assert.equal(JSON.parse(socket.sent[0]).type, "stream.start");
    socket.emit("message", { data: JSON.stringify({ type: "stream.ready" }) });
    await connecting;
    assert.equal(connected, true);
    socket.close();
  });
});

test("connect rejects stream.error and stream.closed before ready", async () => {
  for (const reply of [{ type: "stream.error", message: "session already active" }, { type: "stream.closed" }]) {
    await withFakeWebSocket(async () => {
      FakeWebSocket.startReply = reply;
      const live = new LiveCaptionSocket("ws://test/api/live");
      await assert.rejects(live.connect("session-1"), /session already active|就绪前关闭/);
      assert.equal(FakeWebSocket.instances[0].readyState, FakeWebSocket.CLOSED);
    });
  }
});

test("connect rejects a transport close before stream.ready", async () => {
  await withFakeWebSocket(async () => {
    FakeWebSocket.startReply = null;
    const live = new LiveCaptionSocket("ws://test/api/live");
    const connecting = live.connect("session-1");
    FakeWebSocket.instances[0].close(1006);
    await assert.rejects(connecting, /就绪前关闭/);
  });
});

test("explicit PCM sequence preserves a resumed session and a dropped-frame gap", async () => {
  await withFakeWebSocket(async () => {
    const localEvents = [];
    const live = new LiveCaptionSocket("ws://test/api/live", { onLocalEvent: (event) => localEvents.push(event) });
    await live.connect("resumed-session");
    const socket = FakeWebSocket.instances[0];
    assert.equal(live.sendPcm(new ArrayBuffer(PCM_BYTES_PER_FRAME), 258), true);
    socket.bufferedAmount = PCM_BYTES_PER_FRAME * 21;
    assert.equal(live.sendPcm(new ArrayBuffer(PCM_BYTES_PER_FRAME), 259), false);
    socket.bufferedAmount = 0;
    assert.equal(live.sendPcm(new ArrayBuffer(PCM_BYTES_PER_FRAME)), true);
    const sequences = socket.sent.filter((payload) => payload instanceof ArrayBuffer)
      .map((payload) => new DataView(payload).getUint32(0, false));
    assert.deepEqual(sequences, [258, 260]);
    assert.equal(localEvents[0].frameSequence, 259);
    socket.close();
  });
});
