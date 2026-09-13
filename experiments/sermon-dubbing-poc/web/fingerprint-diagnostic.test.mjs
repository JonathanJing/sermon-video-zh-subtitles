import test from 'node:test';
import assert from 'node:assert/strict';
import {captureDiagnostic,diagnosticMessage,createFingerprintController} from './fingerprint-ui.mjs';
const allowed=new Set(['MIC_START_TIMEOUT','INPUT_INTERRUPTED','AUDIO_INTERRUPTED','MIC_ENDED','PROCESSOR_ERROR','INVALID_CAPTURE','INDEX_MISMATCH','INDEX_UNAVAILABLE','MATCH_ERROR','MIC_PERMISSION','MIC_MISSING','MIC_BUSY','MIC_SETTINGS','AUDIO_UNSUPPORTED','WORKLET_LOAD','AUDIO_START','UNKNOWN']);
test('private native messages, labels and device IDs never enter diagnostic or visible text',()=>{const privateValue='private_device_id_12345 personal microphone label';for(const name of ['NotReadableError','Error','NotAllowedError']){const d=captureDiagnostic({name,message:privateValue,captureStage:privateValue,deviceId:privateValue});const all=JSON.stringify(d)+diagnosticMessage(d);assert.ok(!all.includes(privateValue));assert.ok(allowed.has(d.code));assert.equal(d.stage,'matching');assert.equal(d.version,'C3');}});
test('all diagnostic branches including inherited object names remain bounded strings',()=>{for(const message of ['capture_start_timeout','capture_interrupted','constructor','__proto__','toString','hasOwnProperty','unknown message'])for(const name of ['Error','NotReadableError','constructor','__proto__','toString']){const d=captureDiagnostic({message,name,captureStage:'input'});assert.equal(typeof d.code,'string',`${message}/${name} must not resolve an inherited map property`);assert.ok(allowed.has(d.code));}});
test('controller error state keeps sanitized diagnostic only and performs no seek/play',async()=>{
 const sha='a'.repeat(64),raw='private_device_id_12345';const events=[];let seeks=0,plays=0;
 const metadata={schemaVersion:'sermon-audio-fingerprint-binding-v1',algorithmVersion:'spectral-landmarks-v1',pageId:'week',sourceSha256:sha,trackSha256:sha,indexSha256:sha,indexUrl:'/fingerprints/one.json',captureSeconds:10,sourceStartSeconds:1793,sourceEndSeconds:4033};
 const controller=createFingerprintController({context:()=>({week:{id:'week',sourceStartSeconds:1793,audioFingerprint:metadata},track:{id:'track',sha256:sha,durationSeconds:2240},generation:1,ready:true}),pause(){},seek(){seeks++;},play(){plays++;},supported:()=>true,onState:e=>events.push(e),capture:async({onPreparing})=>{onPreparing();const e=new Error(raw);e.name='NotReadableError';e.captureStage='startup';throw e;},timers:{setTimeout(){return 1;},clearTimeout(){}}});
 await controller.start();assert.ok(events.some(e=>e.phase==='starting'));assert.ok(!events.some(e=>e.phase==='recording'));assert.equal(controller.getState().diagnostic.code,'MIC_BUSY');assert.ok(!JSON.stringify(events).includes(raw));assert.equal(seeks,0);assert.equal(plays,0);
});

test('detail diagnostics are whitelisted and distinguish the interrupted source',()=>{
 for(const [detail,expected] of [['frame_gap','CLOCK_GAP'],['track_muted','MUTED'],['empty_input','EMPTY']]){const d=captureDiagnostic({message:'capture_interrupted',captureDetail:detail,captureStage:'recording'});assert.equal(d.detail,expected);assert.ok(diagnosticMessage(d).includes(expected));}
 for(const detail of ['constructor','__proto__','private_device_id']){const d=captureDiagnostic({captureDetail:detail});assert.equal(d.detail,undefined);assert.ok(!diagnosticMessage(d).includes(detail));}
});
