import test from 'node:test';
import assert from 'node:assert/strict';
import { ListeningSummary, mergeRanges } from './listening.mjs';

test('a jump to the end is not a completed listen', () => {
  const s = new ListeningSummary(100);
  s.observe(0, 0, true); s.observe(1, 1000, true); s.observe(99, 2000, true);
  assert.equal(s.snapshot().listenedSeconds, 1);
  assert.deepEqual(s.snapshot().ranges, [[0, 1]]);
});
test('repeated audio adds listening time but not duplicate coverage', () => {
  const s = new ListeningSummary(100);
  s.observe(0, 0, true); s.observe(2, 2000, true);
  s.resetSample(); s.observe(0, 3000, true); s.observe(2, 5000, true);
  assert.equal(s.snapshot().listenedSeconds, 4);
  assert.deepEqual(s.snapshot().ranges, [[0, 2]]);
});
test('pauses and suspended pages do not add listening time', () => {
  const s = new ListeningSummary(100);
  s.observe(0, 0, true); s.observe(0, 10000, false);
  s.observe(0, 20000, true); s.observe(40, 60000, true);
  assert.equal(s.snapshot().listenedSeconds, 0);
});
test('coverage keeps real gaps and never expands across unplayed audio', () => {
  assert.deepEqual(mergeRanges([[3, 4], [0, 1], [.5, 2], [4, 5]], 4.5), [[0, 2], [3, 4.5]]);
});
