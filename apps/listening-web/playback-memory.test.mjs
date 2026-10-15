import test from 'node:test';
import assert from 'node:assert/strict';
import { PlaybackMemory, PLAYBACK_MEMORY_KEY } from './playback-memory.mjs';

const DAY = 86_400_000, start = Date.parse('2026-09-05T12:00:00Z');
const source = { week: '2026-08-30', trackId: 'full_candidate', audioSha256: 'a'.repeat(64) };
const bookmark = { positionSeconds: 123.5, fineOffset: -.75, durationSeconds: 1770 };
function store() {
  const values = new Map();
  return { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) };
}

test('restores the exact saved position after a reload without advancing a live clock', () => {
  const storage = store();
  assert.equal(new PlaybackMemory({ storage, now: () => start }).save(source, bookmark), true);
  const memory = new PlaybackMemory({ storage, now: () => start + DAY });
  assert.deepEqual(memory.read(source, 1770), { positionSeconds: 123.5, fineOffset: -.75, savedAt: start });
  const result = memory.read(source, 1770);
  result.positionSeconds = 999;
  assert.equal(memory.read(source, 1770).positionSeconds, 123.5);
});

test('week, track and full audio hash are independent source boundaries', () => {
  const memory = new PlaybackMemory({ now: () => start });
  memory.save(source, bookmark);
  for (const other of [{ ...source, week: '2026-09-06' }, { ...source, trackId: 'another_track' }, { ...source, audioSha256: 'b'.repeat(64) }]) {
    assert.equal(memory.read(other, 1770), null);
    memory.save(other, { ...bookmark, positionSeconds: 200 });
    assert.equal(memory.read(other, 1770).positionSeconds, 200);
  }
  memory.clear({ ...source, week: '2026-09-06' });
  assert.equal(memory.read(source, 1770).positionSeconds, 123.5);
  assert.equal(memory.read({ ...source, week: '2026-09-06' }, 1770), null);
});

test('bookmarks expire at 30 days and expired persistent entries are removed', () => {
  const storage = store(); let clock = start;
  const memory = new PlaybackMemory({ storage, now: () => clock });
  memory.save(source, bookmark);
  clock = start + 30 * DAY - 1;
  assert.ok(memory.read(source, 1770));
  clock += 1;
  assert.equal(memory.read(source, 1770), null);
  assert.deepEqual(JSON.parse(storage.getItem(PLAYBACK_MEMORY_KEY)).entries, []);
  clock = start;
  memory.save(source, bookmark);
  assert.equal(new PlaybackMemory({ storage, now: () => start + 31 * DAY }).read(source, 1770), null);
  assert.deepEqual(JSON.parse(storage.getItem(PLAYBACK_MEMORY_KEY)).entries, []);
});

test('beginning and ending positions clear a prior prompt; exact 2-second lower boundary remains usable', () => {
  const memory = new PlaybackMemory({ now: () => start });
  for (const positionSeconds of [0, 1.999, 1768, 1769, 1770]) {
    memory.save(source, bookmark);
    assert.equal(memory.save(source, { ...bookmark, positionSeconds }), false);
    assert.equal(memory.read(source, 1770), null);
  }
  assert.equal(memory.save(source, { ...bookmark, positionSeconds: 2 }), true);
  assert.equal(memory.read(source, 1770).positionSeconds, 2);
  assert.equal(memory.save(source, { positionSeconds: 2, fineOffset: 0, durationSeconds: 4 }), false);
});

test('invalid numeric input cannot overwrite a good bookmark; current duration is checked again on read', () => {
  const memory = new PlaybackMemory({ now: () => start });
  memory.save(source, bookmark);
  for (const change of [{ positionSeconds: NaN }, { positionSeconds: Infinity }, { positionSeconds: -1 }, { positionSeconds: 1771 }, { positionSeconds: '123' },
    { fineOffset: NaN }, { fineOffset: Infinity }, { fineOffset: 2000 }, { durationSeconds: 0 }, { durationSeconds: Infinity }, { durationSeconds: -1 }]) {
    assert.equal(memory.save(source, { ...bookmark, ...change }), false);
    assert.equal(memory.read(source, 1770).positionSeconds, 123.5);
  }
  assert.equal(memory.read(source, NaN), null);
  assert.ok(memory.read(source, 1770));
  assert.equal(memory.read(source, 124), null);
  assert.equal(memory.read(source, 1770), null);
});

test('keeps at most 12 most recent sources, including saves in the same millisecond', () => {
  const storage = store(); let clock = start;
  const memory = new PlaybackMemory({ storage, now: () => clock });
  for (let i = 0; i < 15; i++) memory.save({ ...source, trackId: `track_${i}` }, bookmark);
  assert.equal(JSON.parse(storage.getItem(PLAYBACK_MEMORY_KEY)).entries.length, 12);
  for (let i = 0; i < 3; i++) assert.equal(memory.read({ ...source, trackId: `track_${i}` }, 1770), null);
  for (let i = 3; i < 15; i++) assert.ok(memory.read({ ...source, trackId: `track_${i}` }, 1770));
  clock += 1000;
  memory.save({ ...source, trackId: 'track_3' }, bookmark);
  memory.save({ ...source, trackId: 'track_15' }, bookmark);
  assert.ok(memory.read({ ...source, trackId: 'track_3' }, 1770));
  assert.equal(memory.read({ ...source, trackId: 'track_4' }, 1770), null);
});

test('corrupt, future, out-of-bounds and wrong-schema persisted data cannot produce a prompt', () => {
  const row = { source, ...bookmark, savedAt: start };
  for (const raw of ['broken JSON', 'null', JSON.stringify({ schemaVersion: 2, entries: [row] }), JSON.stringify({ schemaVersion: 1, entries: {} }),
    ...[{ savedAt: start + 1 }, { positionSeconds: -1 }, { positionSeconds: 2000 }, { fineOffset: '1' }, { durationSeconds: null }, { source: { ...source, audioSha256: 'wrong' } }].map(change => JSON.stringify({ schemaVersion: 1, entries: [{ ...row, ...change }] }))]) {
    const storage = store(); storage.setItem(PLAYBACK_MEMORY_KEY, raw);
    assert.equal(new PlaybackMemory({ storage, now: () => start }).read(source, 1770), null);
  }
});

test('valid rows survive beside bad rows and duplicate sources select the latest save', () => {
  const storage = store();
  storage.setItem(PLAYBACK_MEMORY_KEY, JSON.stringify({ schemaVersion: 1, entries: [null, { source, ...bookmark, savedAt: start - 1000 },
    { source, ...bookmark, positionSeconds: 220, savedAt: start }, { source, ...bookmark, positionSeconds: -2, savedAt: start }] }));
  const memory = new PlaybackMemory({ storage, now: () => start });
  assert.equal(memory.read(source, 1770).positionSeconds, 220);
  assert.equal(JSON.parse(storage.getItem(PLAYBACK_MEMORY_KEY)).entries.length, 1);
});

test('unavailable or quota-limited storage still supports memory save/read/clear without throwing', () => {
  for (const storage of [null, { getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); } }, { getItem() { return null; }, setItem() { throw new Error('quota'); } }]) {
    const memory = new PlaybackMemory({ storage, now: () => start });
    assert.equal(memory.save(source, bookmark), true);
    assert.equal(memory.read(source, 1770).positionSeconds, 123.5);
    assert.equal(memory.clear(source), true);
    assert.equal(memory.read(source, 1770), null);
  }
});

test('invalid sources and clocks fail quietly instead of blocking the player', () => {
  const memory = new PlaybackMemory({ now: () => start });
  for (const bad of [null, {}, { ...source, week: '2026-02-30' }, { ...source, trackId: '' }, { ...source, audioSha256: 'abc' }]) {
    assert.equal(memory.save(bad, bookmark), false);
    assert.equal(memory.read(bad, 1770), null);
    assert.equal(memory.clear(bad), false);
  }
  for (const now of [() => NaN, () => Infinity, () => -1, () => { throw new Error('clock failed'); }]) {
    const broken = new PlaybackMemory({ now });
    assert.equal(broken.save(source, bookmark), false);
    assert.equal(broken.read(source, 1770), null);
  }
});
