import test from "node:test";
import assert from "node:assert/strict";
import { boundedTime, nudge, cueIndex, formatTime } from "./timing.mjs";

test("fine adjustments report applied movement at both ends", () => {
  assert.deepEqual(nudge(0.1, -0.25, 20), { time: 0, applied: -0.1 });
  assert.deepEqual(nudge(19.9, 1, 20), { time: 20, applied: 20 - 19.9 });
  assert.deepEqual(nudge(8, 0.25, 20), { time: 8.25, applied: 0.25 });
});
test("no seek is fabricated for missing media metadata", () => {
  assert.equal(boundedTime(20, NaN), 0);
  assert.equal(boundedTime(Infinity, 20), 0);
});
test("utterance boundaries are half open and silence has no active cue", () => {
  const cues = [{ start: 0, end: 2 }, { start: 2.18, end: 5 }];
  assert.equal(cueIndex(cues, 2), -1);
  assert.equal(cueIndex(cues, 2.18), 1);
  assert.equal(cueIndex(cues, 5), -1);
});
test("duration display supports full sermons", () => {
  assert.equal(formatTime(3601.4), "60:01");
  assert.equal(formatTime(NaN), "00:00");
});
