import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, writeFileSync, mkdtempSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';
import {compareGolden, checkGolden} from '../../../apps/tongxing-ios/scripts/generate-published-fingerprint-golden.mjs';
const generator = fileURLToPath(new URL('../../../apps/tongxing-ios/scripts/generate-published-fingerprint-golden.mjs', import.meta.url));
const fixture = fileURLToPath(new URL('../../../apps/tongxing-ios/Core/Tests/TongxingCoreTests/Fixtures/published-fingerprint.golden.json', import.meta.url));
const run = args => spawnSync(process.execPath,[generator,...args],{encoding:'utf8',timeout:20000});

test('frozen production DSP baseline passes without rewriting the fixture', () => {
  const before = readFileSync(fixture);
  const report = checkGolden();
  assert.equal(report.status,'synthetic_contract_passed');assert.equal(report.mismatchCount,0);
  assert.equal(report.cases.length,12);assert.deepEqual(report.sampleRates,[8000,44100,48000]);
  assert.equal(report.cases.filter(c=>c.matched).length,3);
  assert.equal(report.swiftParity,'not_run');assert.equal(report.deviceAcceptance,'not_run');
  assert.equal(report.venueAcceptance,'not_run');assert.equal(report.promotionAllowed,false);
  assert.deepEqual(readFileSync(fixture),before);
});

test('comparison keeps integer landmarks and acceptance exact, permits only tiny numerical drift', () => {
  assert.equal(compareGolden({x:1.2},{x:1.2+1e-12}).mismatchCount,0);
  for (const [a,b] of [[{x:1},{x:2}],[{x:1},{x:1.00000000001}],[{matched:true},{matched:false}],[{reason:'ambiguous'},{reason:'matched'}],[{x:1.2},{x:1.2001}],[{x:[1,2]},{x:[1]}],[{x:NaN},{x:NaN}],[{x:1},{x:1,extra:2}]]) assert.ok(compareGolden(a,b).mismatchCount>0);
  const result=compareGolden(Array(100).fill(0),Array(100).fill(1));
  assert.equal(result.mismatchCount,100);assert.equal(result.differences.length,32);
});

test('CLI detects stale fixture, emits failed report and preserves source bytes', () => {
  const dir=mkdtempSync(join(tmpdir(),'fingerprint-baseline-'));
  try {
    const stale=JSON.parse(readFileSync(fixture));stale.cases[0].expectedMatch.matched=false;
    const path=join(dir,'fixture.json'),report=join(dir,'report.json');writeFileSync(path,JSON.stringify(stale));const before=readFileSync(path);
    const result=run(['--check','--fixture',path,'--report',report]);assert.equal(result.status,1);
    const evidence=JSON.parse(readFileSync(report));assert.equal(evidence.status,'failed');assert.equal(evidence.promotionAllowed,false);
    assert.ok(evidence.differences.includes('fixture.cases[0].expectedMatch.matched'));
    assert.deepEqual(readFileSync(path),before);
  } finally {rmSync(dir,{recursive:true,force:true});}
});

test('CLI cannot overwrite evidence and malformed fixtures cannot echo private input', () => {
  const dir=mkdtempSync(join(tmpdir(),'fingerprint-baseline-'));
  try {
    const report=join(dir,'report.json');writeFileSync(report,'preserve-me');
    assert.equal(run(['--check','--report',report]).status,1);assert.equal(readFileSync(report,'utf8'),'preserve-me');
    const path=join(dir,'bad.json');writeFileSync(path,'private-device-label');
    const result=run(['--check','--fixture',path]);assert.equal(result.status,1);assert.ok(!(result.stdout+result.stderr).includes('private-device-label'));
    assert.equal(run(['--check','--report']).status,1);assert.equal(run(['--help']).status,0);
  } finally {rmSync(dir,{recursive:true,force:true});}
});
