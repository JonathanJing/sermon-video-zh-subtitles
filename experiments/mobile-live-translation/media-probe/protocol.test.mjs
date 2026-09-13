import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import vm from "node:vm";
import { encodeFrame, decodeFrame, syntheticFrame, WIRE_BYTES, sampleStats,
  boundedMapSet, outputEstimate } from "./protocol.mjs";

test("PCM wire format has a network-order identity and little-endian samples", () => {
  const pcm = new Int16Array(1600); pcm[0] = -32768; pcm[1] = 32767;
  const wire = encodeFrame(4, 258, pcm);
  assert.equal(wire.byteLength, WIRE_BYTES);
  assert.deepEqual([...new Uint8Array(wire).slice(0, 12)], [77, 80, 48, 49, 0, 0, 0, 4, 0, 0, 1, 2]);
  assert.deepEqual([...new Uint8Array(wire).slice(12, 16)], [0, 128, 255, 127]);
  const decoded = decodeFrame(wire);
  assert.equal(decoded.epoch, 4); assert.equal(decoded.sequence, 258);
  assert.equal(decoded.pcm[0], -1); assert.equal(decoded.pcm[1], 32767 / 32768);
  assert.throws(() => encodeFrame(0, 1, pcm));
  assert.throws(() => decodeFrame(new ArrayBuffer(2)));
  new Uint8Array(wire)[0] = 0;
  assert.throws(() => decodeFrame(wire));
});

test("synthetic audio is deterministic, shaped and bounded", () => {
  const a = syntheticFrame(1), b = syntheticFrame(1), c = syntheticFrame(2);
  assert.deepEqual(a, b); assert.notDeepEqual(a, c);
  assert.equal(a.length, 1600);
  assert.ok(Math.max(...a.map(Math.abs)) <= 1000);
  assert.ok(a.some((sample) => sample !== 0));
  assert.ok(a.slice(640).every((sample) => sample === 0));
});

test("explicit silent input retains full PCM framing with exclusively zero samples", () => {
  const pcm = syntheticFrame(17, { silent: true });
  assert.equal(pcm.byteLength, 3200);
  assert.ok(pcm.every((sample) => sample === 0));
  const wire = encodeFrame(2, 17, pcm);
  assert.equal(wire.byteLength, WIRE_BYTES);
  assert.ok(decodeFrame(wire).pcm.every((sample) => sample === 0));
});

test("silent PCM receives Worklet processing acknowledgements without nonzero output", async () => {
  const { instance, emitted } = await worklet("./playback-worklet.js");
  instance.port.onmessage({ data: { type: "reset", epoch: 1 } });
  for (const sequence of [1, 2]) {
    instance.port.onmessage({ data: { type: "frame", epoch: 1, sequence, pcm: new Float32Array(1600) } });
  }
  const output = new Float32Array(128).fill(1);
  instance.process([], [[output]]);
  assert.ok(output.every((sample) => sample === 0));
  assert.equal(emitted.filter((event) => event.type === "played").length, 1);
});

test("missing timing stays null and pending frame bookkeeping is bounded", () => {
  assert.equal(sampleStats([]).p50, null);
  assert.deepEqual(sampleStats([4, 1, 3, 2]), { count: 4, p50: 2.5, p95: 4 });
  const map = new Map();
  for (let i = 0; i < 50; i += 1) boundedMapSet(map, i, i, 4);
  assert.equal(map.size, 4); assert.deepEqual([...map.keys()], [46, 47, 48, 49]);
  assert.equal(outputEstimate({}, 1, 2), null);
  assert.equal(outputEstimate({ getOutputTimestamp: () => ({ contextTime: 0, performanceTime: 0 }) }, 1, 2), null);
  const estimated = outputEstimate({ getOutputTimestamp: () => ({ contextTime: 3, performanceTime: 1000 }) }, 3.1, 990);
  assert.ok(Math.abs(estimated - 110) < .001);
});

async function worklet(filename) {
  const emitted = [];
  let Processor;
  const sandbox = {
    sampleRate: 48000, currentTime: 0, Float32Array, Int16Array,
    AudioWorkletProcessor: class { constructor() { this.port = { postMessage: (event) => emitted.push(event) }; } },
    registerProcessor: (_name, Constructor) => { Processor = Constructor; },
  };
  vm.runInNewContext(await readFile(new URL(filename, import.meta.url), "utf8"), sandbox);
  return { instance: new Processor(), emitted, sandbox };
}

test("playback waits for jitter buffer and acknowledges only actual process output", async () => {
  const { instance, emitted, sandbox } = await worklet("./playback-worklet.js");
  instance.port.onmessage({ data: { type: "reset", epoch: 2 } });
  const pcm = new Float32Array(1600).fill(.1);
  instance.port.onmessage({ data: { type: "frame", epoch: 2, sequence: 1, pcm } });
  let out = new Float32Array(128);
  instance.process([], [[out]]);
  assert.ok(out.every((sample) => sample === 0)); assert.equal(emitted.length, 0);
  instance.port.onmessage({ data: { type: "frame", epoch: 2, sequence: 2, pcm } });
  for (let i = 0; i < 80; i += 1) {
    sandbox.currentTime = i * 128 / 48000;
    out = new Float32Array(128);
    instance.process([], [[out]]);
    if (i === 0) assert.ok(out.some((sample) => sample > 0));
  }
  const played = emitted.filter((event) => event.type === "played");
  assert.deepEqual(played.map((event) => event.sequence), [1, 2]);
  assert.equal(played[0].renderedAudioTime, 0);
  assert.ok(played[1].renderedAudioTime >= .099 && played[1].renderedAudioTime < .101);
});

test("Stop and a new epoch clear all queued playback; stale frames cannot resume it", async () => {
  const { instance, emitted } = await worklet("./playback-worklet.js");
  instance.port.onmessage({ data: { type: "reset", epoch: 7 } });
  const pcm = new Float32Array(1600).fill(.1);
  for (let sequence = 1; sequence <= 3; sequence += 1) instance.port.onmessage({ data: { type: "frame", epoch: 7, sequence, pcm } });
  instance.port.onmessage({ data: { type: "reset", epoch: 0 } });
  instance.port.onmessage({ data: { type: "frame", epoch: 7, sequence: 4, pcm } });
  const out = new Float32Array(128).fill(1);
  instance.process([], [[out]]);
  assert.ok(out.every((sample) => sample === 0)); assert.equal(emitted.length, 0);
  instance.port.onmessage({ data: { type: "reset", epoch: 8 } });
  instance.port.onmessage({ data: { type: "frame", epoch: 7, sequence: 5, pcm } });
  assert.equal(instance.queue.length, 0);
});

test("playback queue evicts old frames at a fixed eight-frame bound", async () => {
  const { instance, emitted } = await worklet("./playback-worklet.js");
  instance.port.onmessage({ data: { type: "reset", epoch: 1 } });
  for (let sequence = 1; sequence <= 20; sequence += 1) {
    instance.port.onmessage({ data: { type: "frame", epoch: 1, sequence, pcm: new Float32Array(1600) } });
  }
  assert.equal(instance.queue.length, 8);
  assert.equal(emitted.filter((event) => event.type === "dropped").length, 12);
  assert.equal(instance.queue[0].sequence, 13);
});

test("microphone worklet emits exact 100 ms PCM frames and honors Stop", async () => {
  const { instance, emitted } = await worklet("./capture-worklet.js");
  const input = new Float32Array(128).fill(.1);
  for (let i = 0; i < 38; i += 1) instance.process([[input]]);
  assert.equal(emitted.length, 1); assert.equal(emitted[0].byteLength, 3200);
  assert.ok(new Int16Array(emitted[0]).every((sample) => sample >= 3276 && sample <= 3277));
  instance.port.onmessage({ data: { type: "stop" } });
  for (let i = 0; i < 100; i += 1) instance.process([[input]]);
  assert.equal(emitted.length, 1);
});

async function appHarness() {
  const elements = new Map();
  const element = (id) => {
    if (!elements.has(id)) elements.set(id, { value: "", disabled: false, textContent: "" });
    return elements.get(id);
  };
  const sockets = [];
  const timers = new Map();
  let now = 0, nextTimerId = 0;
  const schedule = (callback, delay, repeat) => {
    const id = ++nextTimerId;
    timers.set(id, { callback, delay, next: now + delay, repeat });
    return id;
  };
  class FakeWebSocket {
    static OPEN = 1;
    static CLOSING = 2;
    constructor() { this.readyState = 1; this.bufferedAmount = 0; this.sent = []; this.closed = []; this.autoPong = false; sockets.push(this); }
    send(value) {
      const event = JSON.parse(value);
      this.sent.push(event);
      if (this.autoPong && event.type === "ping") this.onmessage({ data: JSON.stringify({ type: "pong", id: event.id }) });
    }
    close(code, reason) { this.readyState = 2; this.closed.push({ code, reason }); }
  }
  const sandbox = {
    SCHEMA: "mobile-media-probe-v1", WIRE_BYTES, encodeFrame, decodeFrame, syntheticFrame,
    sampleStats, boundedMapSet, outputEstimate,
    document: { getElementById: element, addEventListener() {} },
    window: { addEventListener() {} },
    location: { hash: "", pathname: "/", protocol: "https:", host: "probe.test" },
    history: { replaceState() {} }, URLSearchParams, TextEncoder, WebSocket: FakeWebSocket,
    performance: { now: () => now },
    setInterval: (callback, delay) => schedule(callback, delay, true), clearInterval: (id) => timers.delete(id),
    setTimeout: (callback, delay) => schedule(callback, delay, false), clearTimeout: (id) => timers.delete(id),
  };
  const source = (await readFile(new URL("./app.js", import.meta.url), "utf8"))
    .replace(/^import[\s\S]*?from "\.\/protocol\.mjs";\n/, "");
  vm.runInNewContext(source, sandbox);
  element("token").value = "a".repeat(43);
  element("role").value = "loopback";
  element("device").value = "desktop";
  element("network").value = "wifi";
  const connect = (authenticate = true) => {
    element("connect").onclick();
    const socket = sockets.at(-1);
    socket.onopen();
    if (authenticate) socket.onmessage({ data: JSON.stringify({ type: "authenticated", hostLabel: "macbook", role: "loopback", expiresInSeconds: 1800 }) });
    return socket;
  };
  const advance = (milliseconds) => {
    const end = now + milliseconds;
    while (true) {
      const entry = [...timers.entries()].sort((a, b) => a[1].next - b[1].next)[0];
      if (!entry || entry[1].next > end) break;
      const [id, timer] = entry;
      now = timer.next;
      if (timer.repeat) timer.next += timer.delay;
      else timers.delete(id);
      timer.callback();
    }
    now = end;
  };
  return { element, sockets, timers, connect, advance };
}

test("authenticated UI requests recovery summary and an empty reply preserves the previous one", async () => {
  const { element, connect } = await appHarness();
  const socket = connect();
  assert.equal(socket.sent.filter((event) => event.type === "summary").length, 1);
  const summary = { runId: "failed-run", stopReason: "protocol_or_rate_rejected" };
  socket.onmessage({ data: JSON.stringify({ type: "summary", summary }) });
  const displayed = element("summary").textContent;
  assert.deepEqual(JSON.parse(displayed), summary);
  socket.onmessage({ data: JSON.stringify({ type: "summary", summary: null }) });
  assert.equal(element("summary").textContent, displayed);
  assert.equal(element("download").disabled, false);
});

test("healthy matched ping/pong traffic stays connected throughout 120 seconds", async () => {
  const { element, connect, advance, timers } = await appHarness();
  const socket = connect();
  socket.autoPong = true;
  advance(120000);
  assert.equal(socket.closed.length, 0);
  assert.equal(socket.sent.filter((event) => event.type === "ping").length, 240);
  assert.equal(socket.sent.filter((event) => event.type === "rtt").length, 240);
  assert.equal(timers.size, 1);
  assert.equal(element("connect").disabled, true);
});

test("control-buffer overflow stops locally and closes even without a socket close event", async () => {
  const { element, connect, advance, timers } = await appHarness();
  const socket = connect();
  const before = socket.sent.length;
  socket.bufferedAmount = 64 * 1024;
  advance(500);
  assert.equal(socket.closed.length, 1);
  assert.equal(socket.closed[0].reason, "send_buffer_limit");
  assert.equal(socket.sent.length, before); // No recursive stop or final ping is enqueued.
  assert.equal(timers.size, 0);
  assert.equal(element("connect").disabled, false);
  assert.equal(element("stop").disabled, true);
  advance(120000);
  assert.equal(socket.sent.length, before);
});

test("an OPEN connection with no pong converges within eight seconds and stale close cannot break reconnect", async () => {
  const { element, connect, advance, timers } = await appHarness();
  const oldSocket = connect();
  advance(7500);
  assert.equal(oldSocket.closed.length, 0);
  advance(500);
  assert.equal(oldSocket.closed[0].reason, "pong_timeout");
  assert.equal(timers.size, 0);
  assert.equal(element("connect").disabled, false);
  const current = connect();
  current.autoPong = true;
  oldSocket.onclose();
  advance(1000);
  assert.equal(current.closed.length, 0);
  assert.equal(element("connect").disabled, true);
});

test("a connection that never authenticates also stops within eight seconds", async () => {
  const { element, connect, advance, timers } = await appHarness();
  const socket = connect(false);
  advance(8000);
  assert.equal(socket.closed[0].reason, "authentication_timeout");
  assert.equal(timers.size, 0);
  assert.equal(element("connect").disabled, false);
});
