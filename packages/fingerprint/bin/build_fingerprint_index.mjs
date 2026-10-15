/** Compute source landmarks early; bind the actual Chinese track only at delivery. */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { fingerprint, CONFIG } from './web/fingerprint-core.mjs';
const flags=new Set(['source','source-sha','track-sha','track','page-id','start','end','out','mode','precomputed','precomputed-sha']),args={};
for(let i=2;i<process.argv.length;i+=2){const key=process.argv[i]?.replace(/^--/,'');if(!flags.has(key)||args[key]!==undefined||!process.argv[i+1])throw Error('Invalid or repeated fingerprint flag');args[key]=process.argv[i+1];}
const mode=args.mode??'build';
if(!['build','precompute','bind'].includes(mode))throw Error('Invalid fingerprint mode');
for(const key of ['source-sha','start','end','out'])if(!args[key])throw Error(`Required: --${key}`);
const start=Number(args.start),end=Number(args.end),out=path.resolve(args.out);
const hex=value=>/^[a-f0-9]{64}$/.test(value??'');
if(!hex(args['source-sha'])||!Number.isFinite(start)||!Number.isFinite(end)||start<0||end<=start||end-start>7200||fs.existsSync(out))throw Error('Invalid identity/window or output already exists');
async function hashFile(file){const hash=crypto.createHash('sha256');for await(const chunk of fs.createReadStream(file))hash.update(chunk);return hash.digest('hex');}
let index;
if(mode==='bind'){
  if(!args.precomputed||!hex(args['precomputed-sha'])||!args.track)throw Error('Bind requires --precomputed --precomputed-sha and actual --track');
  if(await hashFile(args.precomputed)!==args['precomputed-sha'])throw Error('Precomputed landmarks changed');
  index=JSON.parse(fs.readFileSync(args.precomputed,'utf8'));
  if(index.schemaVersion!=='sermon-source-landmarks-v1'||index.algorithmVersion!==CONFIG.algorithmVersion||index.sourceSha256!==args['source-sha']||index.sourceStartSeconds!==start||index.sourceEndSeconds!==end||index.trackSha256!==undefined||index.pageId!==undefined)throw Error('Precomputed source/window identity mismatch');
}else{
  if(!args.source||path.resolve(args.source)===out)throw Error('Source is required and must differ from output');
  if(await hashFile(args.source)!==args['source-sha'])throw Error('Source SHA mismatch');
  const decoded=spawnSync('ffmpeg',['-v','error','-ss',String(start),'-i',path.resolve(args.source),'-t',String(end-start),'-vn','-ac','1','-ar','8000','-f','f32le','pipe:1'],{maxBuffer:Math.ceil((end-start)*8000*4)+1024*1024});
  if(decoded.status!==0)throw Error('Local ffmpeg audio extraction failed');
  if(Math.abs(decoded.stdout.byteLength/4/8000-(end-start))>.05)throw Error('Decoded source window is incomplete');
  const samples=new Float32Array(decoded.stdout.buffer,decoded.stdout.byteOffset,decoded.stdout.byteLength/4);
  const result=fingerprint(samples,8000),postings={};for(const [hash,t] of result.landmarks)(postings[hash]??=[]).push(t);
  for(const h in postings)postings[h]=[...new Set(postings[h])];
  index={schemaVersion:'sermon-source-landmarks-v1',algorithmVersion:CONFIG.algorithmVersion,sampleRate:8000,hopSize:256,fftSize:1024,sourceSha256:args['source-sha'],sourceStartSeconds:start,sourceEndSeconds:end,window:{startSeconds:start,endSeconds:end},durationSeconds:end-start,landmarkCount:result.landmarks.length,postings};
  samples.fill(0);
}
if(mode!=='precompute'){
  let trackSha=args['track-sha'];
  if(args.track){const actual=await hashFile(args.track);if(trackSha&&actual!==trackSha)throw Error('Chinese track SHA mismatch');trackSha=actual;}
  if(!hex(trackSha)||!/^[A-Za-z0-9_-]{1,200}$/.test(args['page-id']??''))throw Error('Required valid track identity and page id');
  index={...index,schemaVersion:'sermon-landmark-index-v1',trackSha256:trackSha,pageId:args['page-id']};
}else if(args.track||args['track-sha']||args['page-id'])throw Error('Source precompute must not claim a finished track/page binding');
const data=JSON.stringify(index);fs.writeFileSync(out,data,{flag:'wx'});
console.log(JSON.stringify({path:out,sha256:crypto.createHash('sha256').update(data).digest('hex'),bytes:Buffer.byteLength(data),landmarks:index.landmarkCount,mode}));
