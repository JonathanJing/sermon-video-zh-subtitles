/** Add source-bound listening alignment to an already reviewed v3 published week.
 * Run only against a new Hosting candidate. Reviewed content/audio/packages stay immutable.
 */
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import crypto from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
const args = {};
for (let i=2;i<process.argv.length;i+=2) {
  const key=process.argv[i]?.replace(/^--/,'');
  if (!['public','page-id','source'].includes(key)||args[key]||!process.argv[i+1]) throw Error('Expected --public --page-id --source');
  args[key]=process.argv[i+1];
}
if (!args.public||!args.source||!/^[A-Za-z0-9_-]+$/.test(args['page-id']||'')) throw Error('Missing arguments');
const root=path.resolve(args.public), pageId=args['page-id'];
const read=file=>JSON.parse(fs.readFileSync(file,'utf8'));
const hash=async file=>{const h=crypto.createHash('sha256');for await(const bytes of fs.createReadStream(file))h.update(bytes);return h.digest('hex');};
const require=(ok,message)=>{if(!ok)throw Error(message);};
const local=url=>{require(/^\/[A-Za-z0-9_./-]+$/.test(url)&&!url.split('/').some(x=>x==='..'||x==='.'),'Unsafe asset path');return path.join(root,url);};
const catalog=read(path.join(root,'multilingual-v3.json'));
require(catalog.schemaVersion==='sermon-multilingual-catalog-v3','Expected v3 catalog');
const page=catalog.pages.find(p=>p.id===pageId);
require(page,'Missing page');
const sidecarPath=path.join(root,'alignment',`${pageId}.json`);
require(!fs.existsSync(sidecarPath),'Alignment already exists; use a new candidate');
const sourceSha=await hash(args.source), variants=[];
for(const [locale,target] of Object.entries(page.targets)) {
  const releasePath=local(target.releasePackageUrl);
  require(await hash(releasePath)===target.releasePackageJsonSha256,'Release hash mismatch');
  const release=read(releasePath);
  require(release.pageId===pageId&&release.targetLocale===locale&&release.audioLocale===locale&&release.status==='published_http_verified'&&release.audioStatus==='human_reviewed','Unreviewed or mismatched release');
  const contentAsset=release.assets.find(a=>a.role==='content'), audioAsset=release.assets.find(a=>a.role==='audio');
  require(contentAsset&&audioAsset,'Missing assets');
  require(await hash(local(contentAsset.path))===contentAsset.sha256&&await hash(local(audioAsset.path))===audioAsset.sha256,'Asset hash mismatch');
  const content=read(local(contentAsset.path));
  require(content.sourceMediaSha256===sourceSha&&content.englishSourcePackageJsonSha256===page.sourceIdentitySha256&&content.pageId===pageId&&content.targetLocale===locale,'Source identity mismatch');
  const probe=spawnSync('ffprobe',['-v','error','-show_entries','format=duration','-of','json',local(audioAsset.path)],{encoding:'utf8'});
  require(probe.status===0&&Math.abs(Number(JSON.parse(probe.stdout).format.duration)-content.durationSeconds)<.1,'Track is not source-clock length');
  variants.push({locale,target,audioAsset,duration:content.durationSeconds});
}
require(variants.length>0&&variants.every(v=>v.duration===variants[0].duration),'Different source windows');
const duration=variants[0].duration, temp=fs.mkdtempSync(path.join(os.tmpdir(),'published-alignment-'));
const builder=fileURLToPath(new URL('./build_fingerprint_index.mjs',import.meta.url));
const run=flags=>{const r=spawnSync(process.execPath,[builder,...flags],{encoding:'utf8',timeout:1800000});require(r.status===0,r.stderr||'Fingerprint build failed');return JSON.parse(r.stdout);};
try {
  const precomputed=path.join(temp,'source.json');
  const shared=['--source-sha',sourceSha,'--start','0','--end',String(duration)];
  const pre=run(['--mode','precompute','--source',path.resolve(args.source),...shared,'--out',precomputed]);
  const targets={};
  for(const v of variants) {
    const out=path.join(temp,`${v.locale}.json`);
    const result=run(['--mode','bind',...shared,'--precomputed',precomputed,'--precomputed-sha',pre.sha256,'--track',local(v.audioAsset.path),'--page-id',pageId,'--out',out]);
    const indexUrl=`/fingerprints/${result.sha256.slice(0,16)}-landmarks.json`;
    fs.mkdirSync(path.dirname(local(indexUrl)),{recursive:true});
    fs.copyFileSync(out,local(indexUrl));
    targets[v.locale]={releasePackageJsonSha256:v.target.releasePackageJsonSha256,audioFingerprint:{
      schemaVersion:'sermon-audio-fingerprint-binding-v1',algorithmVersion:'spectral-landmarks-v1',pageId,
      sourceSha256:sourceSha,trackSha256:v.audioAsset.sha256,sourceStartSeconds:0,sourceEndSeconds:duration,
      captureSeconds:10,indexUrl,indexSha256:result.sha256,
    }};
  }
  require(await hash(args.source)===sourceSha,'Source changed during build');
  fs.mkdirSync(path.dirname(sidecarPath),{recursive:true});
  fs.writeFileSync(sidecarPath,JSON.stringify({schemaVersion:'sermon-published-alignment-v1',pageId,sourceIdentitySha256:page.sourceIdentitySha256,targets},null,2)+'\n',{flag:'wx'});
  console.log(JSON.stringify({sidecarPath,sourceSha256:sourceSha,durationSeconds:duration,locales:Object.keys(targets),landmarks:pre.landmarks}));
} finally {fs.rmSync(temp,{recursive:true,force:true});}
