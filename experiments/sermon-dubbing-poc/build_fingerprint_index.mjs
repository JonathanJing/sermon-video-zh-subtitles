/** Build a same-recording landmark index locally; never publish original PCM. */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { fingerprint, CONFIG } from './web/fingerprint-core.mjs';
const flags=new Set(['source','source-sha','track-sha','page-id','start','end','out']),args={};
for(let i=2;i<process.argv.length;i+=2){const key=process.argv[i]?.replace(/^--/,'');if(!flags.has(key)||args[key]!==undefined||!process.argv[i+1])throw Error('Required: --source --source-sha --track-sha --page-id --start --end --out');args[key]=process.argv[i+1];}
if(Object.keys(args).length!==flags.size)throw Error('Required: --source --source-sha --track-sha --page-id --start --end --out');
const start=Number(args.start),end=Number(args.end),source=path.resolve(args.source),out=path.resolve(args.out);
if(!/^[a-f0-9]{64}$/.test(args['source-sha'])||!/^[a-f0-9]{64}$/.test(args['track-sha'])||!/^[A-Za-z0-9_-]{1,200}$/.test(args['page-id'])||!Number.isFinite(start)||!Number.isFinite(end)||start<0||end<=start||end-start>7200||source===out||fs.existsSync(out))throw Error('Invalid identity/window or output already exists');
const sha=crypto.createHash('sha256');for await(const chunk of fs.createReadStream(source))sha.update(chunk);
if(sha.digest('hex')!==args['source-sha'])throw Error('Source SHA mismatch');
const decoded=spawnSync('ffmpeg',['-v','error','-ss',String(start),'-i',source,'-t',String(end-start),'-vn','-ac','1','-ar','8000','-f','f32le','pipe:1'],{maxBuffer:Math.ceil((end-start)*8000*4)+1024*1024});
if(decoded.status!==0)throw Error('Local ffmpeg audio extraction failed');
if(Math.abs(decoded.stdout.byteLength/4/8000-(end-start))>.05)throw Error('Decoded source window is incomplete');
const samples=new Float32Array(decoded.stdout.buffer,decoded.stdout.byteOffset,decoded.stdout.byteLength/4);
const result=fingerprint(samples,8000),postings={};for(const [hash,t] of result.landmarks)(postings[hash]??=[]).push(t);
for(const h in postings)postings[h]=[...new Set(postings[h])];
const index={schemaVersion:'sermon-landmark-index-v1',algorithmVersion:CONFIG.algorithmVersion,sampleRate:8000,hopSize:256,fftSize:1024,sourceSha256:args['source-sha'],trackSha256:args['track-sha'],pageId:args['page-id'],sourceStartSeconds:start,sourceEndSeconds:end,window:{startSeconds:start,endSeconds:end},durationSeconds:end-start,landmarkCount:result.landmarks.length,postings};
const data=JSON.stringify(index);fs.writeFileSync(out,data,{flag:'wx'});samples.fill(0);
console.log(JSON.stringify({path:out,sha256:crypto.createHash('sha256').update(data).digest('hex'),bytes:Buffer.byteLength(data),landmarks:result.landmarks.length}));
