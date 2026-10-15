import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

function harness(rate=48000) {
 let Processor;const messages=[];
 const scope={AudioWorkletProcessor:class{constructor(){this.port={postMessage:m=>messages.push(m)};}},Float32Array,sampleRate:rate,currentFrame:0,registerProcessor:(_,C)=>Processor=C};
 vm.createContext(scope);vm.runInContext(fs.readFileSync(new URL('./fingerprint-worklet.mjs',import.meta.url),'utf8'),scope);
 const p=new Processor({processorOptions:{seconds:10}});
 function feed(frame,{size=128,value=.75,empty=false,shape=false}={}){scope.currentFrame=frame;const channels=empty?[]:[new Float32Array(size).fill(value)];if(shape)channels.push(new Float32Array(size/2));return p.process([channels],[[new Float32Array(size)]]);}
 return {p,messages,feed,rate};
}
function prime(h,start=0) {let frame=start;while(h.p.used===0){assert.equal(h.feed(frame),true);frame+=128;}return frame;}

test('WebKit-like first frame zero then large real context offset primes and captures a fresh full 10 seconds',()=>{
 const h=harness();assert.equal(h.feed(0,{value:.1}),true);assert.equal(h.p.used,0);assert.equal(h.messages.length,0);
 let frame=100000;
 while(!h.p.finished){const priming=h.p.used===0&&h.p.primingFrames<h.p.primingLimit;h.feed(frame,{value:priming?.25:.75});frame+=128;}
 const started=h.messages.find(m=>m.started),result=h.messages.find(m=>m.samples);
 assert.equal(h.messages.filter(m=>m.started).length,1);assert.ok(!h.messages.some(m=>m.error));
 assert.equal(result.samples.length,480000);assert.ok(result.samples.every(v=>v===.75));
 assert.equal(started.startContextTime,107296/48000);assert.equal(result.endContextTime,(107296+480000)/48000);
});
test('priming is at least 150ms and emits no premature started or retained samples',()=>{
 const h=harness();for(let frame=0;frame<7296;frame+=128){assert.equal(h.feed(frame),true);assert.equal(h.p.used,0);assert.equal(h.messages.length,0);}h.feed(7296);assert.equal(h.messages[0].started,true);assert.equal(h.p.used,128);
});
test('initial empty input counts render work but does not occupy the 10-second query',()=>{
 const h=harness();for(let f=0;f<48000;f+=128){assert.equal(h.feed(f,{empty:true}),true);assert.equal(h.p.used,0);}let frame=48000;while(!h.p.finished){h.feed(frame);frame+=128;}assert.ok(!h.messages.some(m=>m.error));const start=h.messages.find(m=>m.started),end=h.messages.find(m=>m.samples);assert.equal(end.samples.length,480000);assert.ok(Math.abs(end.endContextTime-start.startContextTime-10)<1e-12);
});
test('repeated startup clock resets cannot evade the render-work timeout',()=>{
 const h=harness();for(let n=0;n<1200&&!h.p.finished;n++)h.feed(n*100000);assert.equal(h.messages.at(-1).error,'capture_start_timeout');assert.equal(h.messages.filter(m=>m.started).length,0);assert.equal(h.p.used,0);assert.ok(h.p.warmupFrames<=144128);
});
test('empty input forever fails once after the bounded render-work budget',()=>{
 const h=harness();for(let n=0;n<1200&&!h.p.finished;n++)h.feed(n*128,{empty:true});assert.equal(h.messages.at(-1).error,'capture_start_timeout');assert.equal(h.p.used,0);h.feed(999999);assert.equal(h.messages.length,1);
});
test('after started, frame gap and empty input fail with distinct detail and never return concatenated PCM',()=>{
 for(const kind of ['frame_gap','empty_input','channel_shape']){const h=harness();const next=prime(h,50000);const before=h.p.used;const active=h.feed(next+(kind==='frame_gap'?128:0),{empty:kind==='empty_input',shape:kind==='channel_shape'});assert.equal(active,false);assert.equal(h.messages.at(-1).error,'capture_interrupted');assert.equal(h.messages.at(-1).captureDetail,kind);assert.equal(h.p.used,before);assert.ok(!h.messages.some(m=>m.samples));}
});
test('44.1k and 48k variable render blocks retain exactly 10 seconds with exact partial final endpoint',()=>{
 for(const rate of [44100,48000]){const h=harness(rate);let frame=90000,n=0;while(!h.p.finished){const size=[64,192,128,256][n++%4];h.feed(frame,{size});frame+=size;}const start=h.messages.find(m=>m.started),result=h.messages.find(m=>m.samples);assert.equal(result.samples.length,rate*10);assert.equal(result.sampleRate,rate);assert.ok(Math.abs(result.endContextTime-start.startContextTime-10)<1e-12);}
});
test('zero-valued nonempty PCM participates in clock priming then remains actual silence for matcher rejection',()=>{
 const h=harness();for(let frame=0;!h.p.finished;frame+=128)h.feed(frame,{value:0});const result=h.messages.find(m=>m.samples);assert.ok(result);assert.ok(result.samples.every(v=>v===0));assert.equal(result.samples.length,480000);assert.equal(h.messages.filter(m=>m.started).length,1);
});
