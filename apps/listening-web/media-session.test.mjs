import test from 'node:test';
import assert from 'node:assert/strict';
import { createMediaSession } from './media-session.mjs';

test('media actions use the existing player, positions follow seeks, and metadata clears', () => {
  const handlers = {}, positions = [], seeks = []; let selection = { week: { title: 'Sermon', speaker: 'Speaker' }, track: { id: 'track' } };
  const audio = { paused: false, currentTime: 100, duration: 600, playbackRate: 1 };
  const session = { setActionHandler: (key, fn) => handlers[key] = fn, setPositionState: value => positions.push(value) };
  let plays = 0, pauses = 0;
  const controls = createMediaSession({ audio, session, getSelection: () => selection,
    play: () => plays++, pause: () => pauses++, seek: value => seeks.push(value) });
  controls.update(); assert.equal(session.metadata.title, 'Sermon'); assert.equal(session.playbackState, 'playing');
  handlers.play(); handlers.pause(); handlers.seekbackward({}); handlers.seekforward({ seekOffset: 10 }); handlers.seekto({ seekTime: 200 });
  assert.equal(plays, 1); assert.equal(pauses, 1); assert.deepEqual(seeks, [95, 110, 200]);
  audio.currentTime = 200; controls.update(); assert.equal(positions.at(-1).position, 200);
  selection = null; controls.update(); assert.equal(session.metadata, null); assert.equal(session.playbackState, 'none');
  assert.ok(Object.values(handlers).every(value => value === null));
  controls.dispose(); assert.ok(Object.values(handlers).every(value => value === null));
});

test('voice sample view releases sermon media actions and restores them on return', () => {
  const handlers = {}, seeks = [];
  let selection = { week: { title: 'Sermon', speaker: 'Speaker' }, track: { id: 'track' } };
  const audio = { paused: true, currentTime: 30, duration: 600, playbackRate: 1 };
  const session = { setActionHandler: (key, fn) => handlers[key] = fn, setPositionState() {} };
  const controls = createMediaSession({ audio, session, getSelection: () => selection,
    play() {}, pause() {}, seek: value => seeks.push(value) });
  controls.update();
  assert.equal(typeof handlers.seekforward, 'function');
  selection = null; // The voice sample view owns media controls now.
  controls.update();
  assert.equal(session.metadata, null);
  assert.ok(Object.values(handlers).every(value => value === null));
  selection = { week: { title: 'Sermon', speaker: 'Speaker' }, track: { id: 'track' } };
  controls.update();
  handlers.seekforward({ seekOffset: 5 });
  assert.deepEqual(seeks, [35]);
  controls.dispose();
});

test('unsupported browser and unsupported individual actions do not break audio', () => {
  createMediaSession({ session: null }).update();
  const controls = createMediaSession({ audio: { paused: true, duration: NaN, currentTime: 0 },
    getSelection: () => ({ week: { title: 'Title' }, track: {} }),
    session: { setActionHandler() { throw new Error('Unsupported'); }, setPositionState() { throw new Error('Unsupported'); } } });
  assert.doesNotThrow(() => controls.update()); assert.doesNotThrow(() => controls.dispose());
});

test('switching to a track awaiting duration clears the previous lock-screen position', () => {
  let selected = { week: { title: 'First', speaker: 'A' }, track: { id: 'first' } };
  const audio = { paused: false, currentTime: 400, duration: 600, playbackRate: 1 };
  let position;
  const session = { setActionHandler() {}, setPositionState(value) { position = value; } };
  const controls = createMediaSession({ audio, session, getSelection: () => selected });
  controls.update(); assert.equal(position.position, 400);
  selected = { week: { title: 'Second', speaker: 'B' }, track: { id: 'second' } };
  audio.duration = NaN; audio.currentTime = 0; audio.paused = true;
  controls.update();
  assert.equal(session.metadata.title, 'Second'); assert.equal(position, undefined);
  audio.duration = 180; controls.update();
  assert.deepEqual(position, { duration: 180, position: 0, playbackRate: 1 });
});
