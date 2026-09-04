import test from "node:test";
import assert from "node:assert/strict";
import { observeCaptionFrame } from "../../src/captionObservation.js";

function observer(visible = true) {
  const scheduled = { visible, cancelled: [], cleared: [] };
  scheduled.promise = observeCaptionFrame({
    requestFrame: (callback) => { scheduled.frame = callback; return 1; },
    cancelFrame: (id) => scheduled.cancelled.push(id),
    setTimer: (callback, delay) => { scheduled.timeout = callback; scheduled.delay = delay; return 2; },
    clearTimer: (id) => scheduled.cleared.push(id),
    isVisible: () => scheduled.visible,
    now: () => 1234,
  });
  return scheduled;
}

test("visible animation frame is observed and clears the timeout", async () => {
  const o = observer();
  o.frame();
  assert.deepEqual(await o.promise, { observed: true, reason: null, atMs: 1234 });
  assert.deepEqual(o.cleared, [2]);
});

test("a suspended frame settles without pretending a caption was rendered", async () => {
  const o = observer();
  assert.equal(o.delay, 2000);
  o.timeout();
  assert.equal((await o.promise).reason, "animation_frame_timeout");
  o.frame();
  assert.equal((await o.promise).observed, false);
  assert.deepEqual(o.cancelled, [1]);
});

test("hidden tabs do not enqueue animation frames or claim a render", async () => {
  const o = observer(false);
  assert.equal((await o.promise).reason, "document_hidden");
  assert.equal(o.frame, undefined);
  assert.equal(o.timeout, undefined);
});

test("a tab hidden before its frame arrives is unobserved", async () => {
  const o = observer();
  o.visible = false;
  o.frame();
  assert.equal((await o.promise).observed, false);
});
