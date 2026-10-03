import test from 'node:test';
import assert from 'node:assert/strict';
import { buildCatalogNavigation, catalogNavigationEnvironment, chooseWeek, weekOptionLabel, diagnosticPresentation } from './catalog.mjs';

const week = (id, extra = {}) => ({ id, date: '2026-09-27', title: '同名讲道', speaker: 'Eric',
  sourceLabel: '原片段 / 机器 ASR', tracks: [], ...extra });
const catalog = (weeks, defaultWeekId = weeks[0].id) => ({ schemaVersion: 'sermon-weekly-catalog-v1', defaultWeekId, weeks });
const dev = value => buildCatalogNavigation(value, { environment: 'development' });
const production = value => buildCatalogNavigation(value, { environment: 'production' });
const diagnostic = (id, extra = {}) => week(id, { diagnosticOnly: true, simulationOnly: true, ...extra });

test('navigation opts into development only for known Dev origins and local preview', () => {
  for (const origin of ['https://ai-for-god-sermon-audio-dev.web.app', 'https://ai-for-god-sermon-audio-dev.firebaseapp.com',
    'http://localhost:5000', 'http://127.0.0.1:8080', 'http://[::1]:5000']) {
    assert.equal(catalogNavigationEnvironment(origin), 'development');
  }
  for (const origin of ['https://ai-for-god-sermon-audio.web.app', 'https://example.test',
    'https://ai-for-god-sermon-audio-dev.web.app.evil.test', 'http://ai-for-god-sermon-audio-dev.web.app',
    'https://example.test/?environment=development', 'invalid', undefined]) {
    assert.equal(catalogNavigationEnvironment(origin), 'production');
  }
  assert.throws(() => buildCatalogNavigation(catalog([week('a')])));
  assert.throws(() => buildCatalogNavigation(catalog([week('a')]), { environment: 'unknown' }));
});

test('formal and legacy weeks stay together ahead of typed diagnostic and rehearsal groups', () => {
  const formal = week('formal', { releaseLabel: '正式播放版', date: '2026-09-28' });
  const legacy = week('legacy', { title: '[DEV 诊断] is a sermon title', date: '2026-09-01' });
  const simulation = week('simulation', { simulationOnly: true, date: '2026-09-30' });
  const source = catalog([simulation, legacy, diagnostic('diagnostic'), formal], formal.id);
  const before = structuredClone(source), result = dev(source);
  assert.deepEqual(result.groups.map(group => [group.id, group.items.map(item => item.week.id)]),
    [['sermons', ['formal', 'legacy']], ['diagnostics', ['diagnostic']], ['simulations', ['simulation']]]);
  assert.deepEqual(source, before);
  assert.equal(result.groups[0].items[0].week, formal);
  assert.deepEqual(production(source).catalog.weeks, [formal, legacy]);
});

test('same labels with different stable IDs remain independently selectable and keep locale/audio routes', () => {
  const track = { id: 'ko-track', audioUrl: '/media/ko.mp3', durationSeconds: 2, cues: [{ start: 0, end: 2, text: '한국어' }] };
  const variants = { ko: { id: 'diagnostic-long-id-a', targetLocale: 'ko', tracks: [track], sourceUrl: '/source-a.mp4' } };
  const a = diagnostic('diagnostic-long-id-a', { contentVariants: variants, defaultTargetLocale: 'ko' });
  const b = diagnostic('diagnostic-long-id-b');
  const result = dev(catalog([b, a]));
  const items = result.groups[0].items;
  assert.equal(new Set(items.map(item => item.label)).size, 2);
  for (const item of items) assert.ok(item.label.endsWith(`[ID: ${item.week.id}]`));
  assert.equal(chooseWeek(result.catalog, a.id), a);
  assert.equal(chooseWeek(result.catalog, b.id), b);
  assert.equal(chooseWeek(result.catalog, a.id).contentVariants.ko.tracks[0], track);
  assert.deepEqual(dev(catalog([a, b])).groups, result.groups);
});

test('generated identity suffixes cannot collide with existing unique labels', () => {
  const plainA = week('x', { title: '同名 · 正式播放版', sourceLabel: '', releaseLabel: '正式播放版' });
  const plainB = { ...plainA, id: 'y' };
  const reserved = { ...plainA, id: 'reserved', title: `${plainA.title} [ID: x]` };
  assert.equal(weekOptionLabel(reserved), `${weekOptionLabel(plainA)} [ID: x]`);
  const labels = dev(catalog([plainA, plainB, reserved])).groups.flatMap(group => group.items.map(item => item.label));
  assert.equal(new Set(labels).size, labels.length);
});

test('duplicate identities are rejected before filtering while hidden defaults and deep links fall back', () => {
  const hidden = diagnostic('hidden', { sourceRoute: 'same_video' });
  const visible = week('visible', { date: '2026-09-20' });
  const result = production(catalog([hidden, visible], hidden.id));
  assert.equal(result.catalog.defaultWeekId, visible.id);
  assert.equal(chooseWeek(result.catalog, hidden.id), visible);
  assert.equal(chooseWeek(result.catalog, hidden.date), visible);
  assert.equal(chooseWeek(result.catalog, 'unknown'), visible);
  assert.throws(() => production(catalog([hidden, { ...hidden }])));
  assert.throws(() => production(catalog([hidden])));
});

test('development markers inside a locale variant cannot bypass production filtering', () => {
  const hidden = week('nested', { contentVariants: { ko: { simulationOnly: true } } });
  const visible = week('visible');
  assert.deepEqual(production(catalog([hidden, visible])).catalog.weeks, [visible]);
  assert.equal(dev(catalog([hidden, visible])).groups[1].id, 'simulations');
});

test('diagnostic ready and blocked presentation remains bound to its actual candidate and tracks', () => {
  const track = { audioUrl: '/media/source.mp3', durationSeconds: 2, cues: [{ start: 0, end: 2, text: '参考' }] };
  const ready = diagnostic('ready', { tracks: [track], fullTranscript: [{ text: '参考' }] });
  const blocked = diagnostic('blocked');
  const result = dev(catalog([ready, blocked]));
  assert.match(result.groups[0].items.find(item => item.week === ready).label, /DEV 可试听/);
  assert.match(result.groups[0].items.find(item => item.week === blocked).label, /流程受阻/);
  assert.equal(diagnosticPresentation(chooseWeek(result.catalog, ready.id)).canPlay, true);
  assert.equal(diagnosticPresentation(chooseWeek(result.catalog, blocked.id)).canPlay, false);
});
