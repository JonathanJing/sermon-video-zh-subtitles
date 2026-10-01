import test from 'node:test';
import assert from 'node:assert/strict';
import { diagnosticPresentation, weekOptionLabel } from './catalog.mjs';

function variant(locale, status, hasCandidate) {
  return { diagnosticOnly:true, targetLocale:locale, date:'2026-10-01', title:'DEV',
    diagnosticInputSha256:'a'.repeat(64),
    fullTranscript:hasCandidate?[{text:'machine text'}]:[], tracks:[{id:locale}],
    diagnosticState:{schemaVersion:'sermon-dev-diagnostic-presentation-v1',targetLocale:locale,
      status,machineCandidateAvailable:hasCandidate, candidateSha256:hasCandidate?'b'.repeat(64):null,
      inputBindingSha256:'a'.repeat(64),reasonCode:hasCandidate?null:'machine_candidate_missing'} };
}
test('failed, blocked and pending variants never inherit audio availability or outline readiness',()=>{
  for (const locale of ['zh-Hans','ko','es']) for (const state of ['failed','blocked','pending']) {
    const week=variant(locale,state,false),view=diagnosticPresentation(week);
    assert.equal(view.status,state);assert.equal(view.canPlay,false);assert.equal(view.hasCandidate,false);
    assert.notEqual(view.stages[0].status,'pass');assert.doesNotMatch(weekOptionLabel(week),/可试听|大纲已就绪/);
  }
});
test('ready requires actual audio and a bound candidate; it remains human pending',()=>{
  const week=variant('ko','ready',true);
  assert.equal(diagnosticPresentation(week).canPlay,true);
  assert.equal(diagnosticPresentation(week).stages[2].status,'pending');
  const missing=variant('ko','ready',true);missing.fullTranscript=[];
  assert.equal(diagnosticPresentation(missing).reasonCode,'diagnostic_state_binding_invalid');
  const empty=variant('ko','ready',true);empty.fullTranscript=[{text:'  '}];
  assert.equal(diagnosticPresentation(empty).canPlay,false);
  week.tracks=[];assert.equal(diagnosticPresentation(week).status,'blocked');
  week.tracks=[{id:'old'}];week.diagnosticState.machineCandidateAvailable=false;
  assert.equal(diagnosticPresentation(week).canPlay,false);
});
test('locale/input changes block stale state and exception text is never displayed',()=>{
  const week=variant('es','failed',false);week.diagnosticState.reasonCode='/Users/private API_KEY=secret';
  assert.equal(diagnosticPresentation(week).reasonCode,'unclassified_failure');
  assert.doesNotMatch(JSON.stringify(diagnosticPresentation(week)),/API_KEY|\/Users/);
  week.diagnosticState.targetLocale='ko';assert.equal(diagnosticPresentation(week).status,'blocked');
  week.diagnosticState.targetLocale='es';week.diagnosticInputSha256='c'.repeat(64);
  assert.equal(diagnosticPresentation(week).reasonCode,'diagnostic_state_binding_invalid');
});
test('historical diagnostic without a state is conservative and legacy weeks are unchanged',()=>{
  const old={diagnosticOnly:true,tracks:[],fullTranscript:[],outline:[{title:'status placeholder'}]};
  assert.equal(diagnosticPresentation(old).reasonCode,'machine_candidate_missing');
  assert.equal(diagnosticPresentation(old).canPlay,false);
  assert.equal(diagnosticPresentation({simulationOnly:true,tracks:[]}),null);
  assert.equal(diagnosticPresentation({tracks:[]}),null);
});
