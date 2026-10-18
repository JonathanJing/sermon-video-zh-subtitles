import test from 'node:test';
import assert from 'node:assert/strict';
import { usageBootstrapWeek } from './usage.mjs';

const track = id => ({ id, sha256: id.repeat(64).slice(0, 64) });

test('usage bootstrap prefers the catalog default week when it is not first', () => {
  const first = { id: 'history', tracks: [track('a')] };
  const current = { id: 'current', tracks: [track('b')] };
  assert.equal(usageBootstrapWeek({ defaultWeekId: current.id, weeks: [first, current] }), current);
});

test('usage bootstrap falls back to the first playable week when the default has no track', () => {
  const defaultWeek = { id: 'text-only', tracks: [] };
  const playable = { id: 'playable', tracks: [track('c')] };
  assert.equal(usageBootstrapWeek({ defaultWeekId: defaultWeek.id, weeks: [defaultWeek, playable] }), playable);
});
