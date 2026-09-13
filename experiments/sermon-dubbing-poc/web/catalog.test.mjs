import test from 'node:test';
import assert from 'node:assert/strict';
import { parseTimecode, chooseWeek, validateCatalog, engagementWeek, downloadFilename, weekOptionLabel } from './catalog.mjs';
import { PlaybackMemory } from './playback-memory.mjs';

const fixture = () => ({schemaVersion: 'sermon-weekly-catalog-v1', defaultWeekId: '2026-08-23', weeks: [
  {id: '2026-08-30', title: 'Anger', speaker: 'Pending', tracks: []},
  {id: '2026-08-23', title: 'Betrayal', speaker: 'Eric', tracks: [{audioUrl: '/media/abc-sft.mp3', durationSeconds: 20, cues: [{start: 0, end: 20, text: '中文。'}]}]},
]});

test('select a pending week without carrying over another week audio', () => {
  const c = validateCatalog(fixture());
  assert.equal(chooseWeek(c, '2026-08-30').tracks.length, 0);
  assert.equal(chooseWeek(c, 'unknown').id, '2026-08-23');
});
test('time entry supports minute and hour timecodes with fine precision', () => {
  assert.equal(parseTimecode('01:05'), 65);
  assert.equal(parseTimecode('1:02:03.25'), 3723.25);
  assert.equal(parseTimecode('00:00'), 0);
  for (const input of ['12', '-1:00', '00:99', '1:90:00', 'no', '00:01.999']) assert.equal(parseTimecode(input), null);
});
test('reject missing default week, duplicate week and unsafe media', () => {
  for (const mutate of [c => c.defaultWeekId = 'missing', c => c.weeks.push(c.weeks[0]), c => c.weeks[1].tracks[0].audioUrl = 'https://other.test/private.mp3']) {
    const c = fixture(); mutate(c); assert.throws(() => validateCatalog(c));
  }
});
test('reject subtitle overlaps and out of bounds cue times', () => {
  for (const cue of [{start: 19, end: 20, text: '重叠'}, {start: 20, end: 21, text: '越界'}]) {
    const c = fixture(); c.weeks[1].tracks[0].cues.push(cue); assert.throws(() => validateCatalog(c));
  }
});

test('same-week source links stay distinct and date-only links prefer the Sunday video', () => {
  const pages = ['live_archive', 'same_video'].map(sourceRoute => ({
    id: `2026-09-06-${sourceRoute}-video`, date: '2026-09-06', sourceRoute,
    title: 'Sermon', speaker: 'Eric', tracks: [],
  }));
  const c = validateCatalog({ schemaVersion: 'sermon-weekly-catalog-v1', defaultWeekId: pages[1].id, weeks: pages });
  assert.equal(chooseWeek(c, pages[0].id), pages[0]);
  assert.equal(chooseWeek(c, pages[1].id), pages[1]);
  assert.equal(chooseWeek(c, '2026-09-06'), pages[1]);
  assert.equal(chooseWeek({ ...c, defaultWeekId: pages[0].id, weeks: [pages[0]] }, '2026-09-06'), pages[0]);
  const legacy = { ...pages[0], id: '2026-08-30', date: '2026-08-30' };
  assert.equal(chooseWeek({ ...c, weeks: [...pages, legacy] }, legacy.id), legacy);
});

test('page navigation does not change date-based feedback or mix saved listening positions', () => {
  const memory = new PlaybackMemory();
  const sources = ['live_archive', 'same_video'].map(sourceRoute => {
    const page = { id: `2026-09-06-${sourceRoute}-video`, date: '2026-09-06' };
    const copy = engagementWeek(page);
    assert.equal(copy.id, '2026-09-06');
    assert.equal(page.id, `2026-09-06-${sourceRoute}-video`);
    return { week: copy.id, trackId: `full_candidate__${sourceRoute}__video`, audioSha256: 'a'.repeat(64) };
  });
  assert.equal(memory.save(sources[0], { positionSeconds: 40, fineOffset: 1, durationSeconds: 100 }), true);
  assert.equal(memory.read(sources[1], 100), null);
  assert.equal(memory.read(sources[0], 100).positionSeconds, 40);
  assert.equal(engagementWeek(null), null);
});

test('downloaded same-week versions have explicit distinct filenames', () => {
  const page = { date: '2026-09-06', title: '证道', speaker: 'Eric' };
  const track = { scope: 'full_candidate' };
  assert.match(downloadFilename({ ...page, sourceRoute: 'live_archive' }, track), /主日聚会版/);
  assert.match(downloadFilename({ ...page, sourceRoute: 'same_video' }, track), /YouTube 版/);
});

test('archive downloads preserve series source without claiming Sunday playback', () => {
  const name = downloadFilename({ date: '2026-08-16', title: '当羞耻缠绕我 · 当生活令人费解', speaker: 'Eric', sourceRoute: 'archive_caption' }, { scope: 'full_candidate' });
  assert.match(name, /YouTube 版/);
  assert.match(name, /当生活令人费解/);
  assert.doesNotMatch(name, /周日/);
});

test('week selector includes the existing series title exactly once', () => {
  const label = weekOptionLabel({ date: '2026-08-23', title: '当我遭遇背叛 · 当生活令人费解', series: '当生活令人费解', sourceLabel: 'YouTube 版', audioStatus: 'full_candidate', tracks: [] });
  assert.equal(label, '2026.08.23 · 当我遭遇背叛 · 当生活令人费解 · YouTube 版 · 整篇待审');
  assert.equal(label.split('当生活令人费解').length - 1, 1);
});
test('week selector preserves missing-title fallback and avoids repeated route text', () => {
  assert.equal(weekOptionLabel({ date: '2026-08-09', tracks: [] }), '2026.08.09 · 待配音');
  assert.equal(weekOptionLabel({ date: '2026-08-09', title: ' ', sourceLabel: 'YouTube 版', tracks: [{}] }), '2026.08.09 · YouTube 版 · 可试听');
  assert.equal(weekOptionLabel({ date: '2026-08-09', title: '证道 · YouTube 版', sourceLabel: 'YouTube 版', tracks: [{}] }), '2026.08.09 · 证道 · YouTube 版 · 可试听');
});

// Contract mirrors TongxingCore/CatalogExtensionTests: source order is irrelevant.
import { bilingualCueRows } from './catalog.mjs';
function bilingualFixture() {
  const c = fixture(), w = c.weeks[1];
  w.tracks[0].cues = [0, 0, 1].map((blockId, i) => ({ blockId, start: i * 5, end: (i + 1) * 5, text: '中文' }));
  w.transcript = { schemaVersion: 'sermon-bilingual-transcript-v1', blocks: [
    { blockId: '1', english: 'Second source block.', sourceTextOrigin: 'job.blocks', reviewState: 'unspecified' },
    { blockId: '0', english: 'First source block.', sourceTextOrigin: 'job.blocks', reviewState: 'candidate' },
  ] };
  return c;
}
test('English appears once at the matching block end, for numeric and string cue IDs', () => {
  const c = bilingualFixture(), w = c.weeks[1];
  w.tracks[0].cues[0].blockId = '0';
  validateCatalog(c);
  const result = bilingualCueRows(w, w.tracks[0]);
  assert.deepEqual(result.rows.map(r => r.english), [null, 'First source block.', 'Second source block.']);
  assert.equal(result.missingEnglish, false);
});
test('missing English and unlinked legacy cues never borrow another source', () => {
  const w = bilingualFixture().weeks[1];
  delete w.transcript.blocks[1].english;
  assert.deepEqual(bilingualCueRows(w, w.tracks[0]).rows.map(r => r.english), [null, null, 'Second source block.']);
  assert.equal(bilingualCueRows(w, w.tracks[0]).missingEnglish, true);
  delete w.tracks[0].cues[2].blockId;
  assert.equal(bilingualCueRows(w, w.tracks[0]).hasEnglish, false);
  delete w.transcript;
  assert.equal(bilingualCueRows(w, w.tracks[0]).hasEnglish, false);
});
test('reject duplicate, missing and invalid bilingual identities and unknown schema', () => {
  for (const mutate of [
    w => w.transcript.schemaVersion = 'future',
    w => w.transcript.blocks[1].blockId = '1',
    w => w.transcript.blocks[1].blockId = 'missing',
    w => w.transcript.blocks[1].english = ' ',
    w => w.tracks[0].cues[0].blockId = -1,
    w => w.tracks[0].cues[0].blockId = true,
    w => delete w.transcript.blocks[1].sourceTextOrigin,
  ]) {
    const c = bilingualFixture(); mutate(c.weeks[1]);
    assert.throws(() => validateCatalog(c));
  }
});
