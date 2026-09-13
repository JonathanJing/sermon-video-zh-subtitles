import test from 'node:test';
import assert from 'node:assert/strict';
import { parseTimecode, chooseWeek, validateCatalog } from './catalog.mjs';

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
