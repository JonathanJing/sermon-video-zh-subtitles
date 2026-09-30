import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {validatePublishedRelease} from './published-weeks.mjs';

const matrix=JSON.parse(readFileSync(new URL('../../../apps/tongxing-ios/Core/Tests/TongxingCoreTests/Fixtures/shared-text-only-releases.json',import.meta.url)));
assert.equal(matrix.schemaVersion,'sermon-shared-text-only-release-fixtures-v1');
assert.equal(matrix.scope,'synthetic_decoder_tests_not_production_approval');
assert.equal(matrix.cases.length,27);
for(const row of matrix.cases) {
 test(`shared text-only release: ${row.id}`,()=>{
  const release=row.release;
  const admit=()=>validatePublishedRelease(release,{id:release.pageId},release.targetLocale);
  if(row.webPlaybackAdmission==='accept') {
   assert.equal(admit().audio.path,`/media/${release.pageId}/${release.targetLocale}.mp3`);
  } else {
   assert.equal(row.webPlaybackAdmission,'reject');
   assert.throws(admit);
  }
  if(row.nativeAdmission==='accept'&&release.audioStatus==='unavailable') {
   assert.equal(release.audioLocale,null);
   assert.ok(!release.assets.some(a=>a.role==='audio'));
   assert.equal(row.webPlaybackAdmission,'reject','native readable never implies Web audio playable');
  }
 });
}
