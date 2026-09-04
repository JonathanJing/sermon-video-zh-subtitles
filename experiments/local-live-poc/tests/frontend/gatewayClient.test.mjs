import assert from "node:assert/strict";
import test from "node:test";

import {
  appendAudioChunk,
  restartGateway,
  startLocalSession,
  translateCaption,
} from "../../src/gatewayClient.js";
import { encodePcmFrame, LiveCaptionSocket, PCM_BYTES_PER_FRAME } from "../../src/liveSocket.js";

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

  constructor() {
    this.readyState = FakeWebSocket.CONNECTING;
    this.bufferedAmount = 0;
    this.listeners = new Map();
    this.sent = [];
    FakeWebSocket.instances.push(this);
    queueMicrotask(() => {
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
  try {
    await run();
  } finally {
    globalThis.window = previousWindow;
    globalThis.WebSocket = previousWebSocket;
  }
}

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
