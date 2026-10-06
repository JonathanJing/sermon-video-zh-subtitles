#!/usr/bin/env python3
"""Offline, bounded audit. Writes only to --out-dir. No mtime used as event time."""
import json,hashlib,datetime,collections
from pathlib import Path
import argparse
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--run-dir',type=Path,required=True)
parser.add_argument('--out-dir',type=Path,required=True)
args=parser.parse_args()
OUT=args.out_dir.resolve(); OUT.mkdir(parents=True,exist_ok=True)
RUN=args.run_dir.resolve()
HERE=OUT; E={}; H={}
def sha(p):
 p=Path(p)
 if p not in H:H[p]=hashlib.sha256(p.read_bytes()).hexdigest()
 return H[p]
def path(p):return p if isinstance(p,Path) and p.is_absolute() else RUN/p
def evidence(p):
 p=path(p);key=str(p.relative_to(RUN));E[key]=sha(p);return key
def read(p):
 p=path(p);evidence(p);return json.loads(p.read_text())
def canonical(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def dt(s):return datetime.datetime.fromisoformat(s.replace('Z','+00:00'))
def delta(a,b):return round((dt(b)-dt(a)).total_seconds(),6)
def ready(candidate,expected):
 p=path(candidate).parent/'accounting/events.jsonl'
 if not p.exists():return None
 evidence(p);events=[json.loads(l) for l in p.read_text().splitlines() if l.strip()]
 matches=[e for e in events if e.get('metrics',{}).get('candidateSha256')==expected]
 for e in reversed(matches):
  finishes=[f for f in events if f.get('spanId')==e.get('spanId') and f.get('event')=='stage_finished' and f.get('status')=='completed']
  if finishes:return {'at':finishes[-1]['completedAt'],'identityEventId':e['eventId'],'completedEventId':finishes[-1]['eventId'],'ledger':str(p.relative_to(RUN)),'candidateCanonicalSha256':expected}
 return None
m=read('RUN/formal-layer3-approved-v1/approval-manifest.json');job=read('formal-layer3-execution-v1/native-job-preparation.json');queue=read('formal-layer3-execution-driver-v1/queue.json');snap=read('formal-layer3-execution-driver-v1/snapshot-122126.json');launch=read('formal-layer3-execution-driver-v1/launch-receipt.json');stagebase=RUN/'formal-layer3-prep-v1/stage-preparation-v1/approved-runtime-stage-v2/build-5b2c1ac'
assert sha(RUN/'RUN/formal-layer3-approved-v1/approval-manifest.json')==job['approvalManifestFileSha256'];assert sha(RUN/'formal-layer3-execution-driver-v1/queue.json')==snap['queueState']['queueSha256']
handoffs=[]
for a in m['artifacts']:
 c=read(a['sourceCandidatePath']);approved=read(a['approvedCandidatePath']);receipt=read(a['humanReviewReceiptPath']);assert sha(RUN/a['sourceCandidatePath'])==a['sourceCandidateRawSha256'];assert canonical(c)==a['sourceCandidateJsonSha256'];assert canonical(approved)==receipt['candidateJsonSha256']==a['approvedCandidateJsonSha256'];assert sha(RUN/a['humanReviewReceiptPath'])==a['humanReviewReceiptRawSha256'];event=ready(a['sourceCandidatePath'],a['sourceCandidateJsonSha256']);row={'locale':a['targetLocale'],'variant':a['variant'],'ready':event,'approvedAt':receipt['reviewedAt'],'approvalReceipt':a['humanReviewReceiptPath'],'approvedCandidateSha256':canonical(approved),'readyToApprovalSeconds':delta(event['at'],receipt['reviewedAt']) if event else None}
 if a['variant']=='spoken':
  loc=a['targetLocale'];n=job['locales'][loc];selected=read(stagebase/f'selected-{loc}.json');assert n['candidateJsonSha256']==canonical(approved);assert selected['selected']['candidate']['sha256']==a['approvedCandidateRawSha256'];assert sha(stagebase/f'selected-{loc}.json')==queue['jobs'][loc]['manifestSha256'];assert snap['locales'][loc]['nativeCheck']['jobSha256']==n['inputFileHashes']['job'];at=snap['queueState']['locales'][loc]['startedAtUtc'];row.update(launchAt=at,approvalToLocaleLaunchSeconds=delta(receipt['reviewedAt'],at),approvalToQueueStartSeconds=delta(receipt['reviewedAt'],launch['result']['startedAtUtc']),queueWaitBeforeLocaleSeconds=delta(snap['queueState']['startedAtUtc'],at),launchMeaning='renderer invocation, includes native checks/loading; not GPU first token')
 handoffs.append(row)
# Metadata/publication sample: all control receipts under three task roots, excluding public snapshots and unit files.
roots=['zh-publication-v1','metadata-title-fix-v1','multilingual-publication-v2'];receipts=[];deployment=[];http=[]
for root in roots:
 for p in sorted((RUN/root).rglob('*.json')):
  parts=p.relative_to(RUN/root).parts
  if 'public' in parts or any(t.startswith(('collected','audio-render','audio-human-approved')) for t in parts):continue
  if not ('receipt' in p.name or p.name=='publication-http-final-v4.json' or p.parent.name=='http-assets-ko-es-v1'):continue
  if len(parts)>4 or p.stat().st_size>500000:continue
  try:x=read(p)
  except Exception:continue
  if not isinstance(x,dict):continue
  stamp={k:v for k,v in x.items() if isinstance(v,str) and ('At' in k or k.endswith('Utc')) and v.startswith('2026-')}
  row={'path':str(p.relative_to(RUN)),'sha256':sha(p),'schemaVersion':x.get('schemaVersion'),'timestamps':stamp,'origin':x.get('origin'),'status':x.get('status'),'deploymentVersionPresent':any('version' in k.lower() and k!='schemaVersion' for k in x),'filesCount':len(x.get('files',x.get('assets',[]))) if isinstance(x.get('files',x.get('assets',[])),list) else None};receipts.append(row)
  if p.name in ('deployment-command-receipt.json','catalog-deploy-receipt.json'):
   row=dict(row,candidate=x.get('candidate'),candidateDirectoryMatches=p.parent==Path(x['candidate']) if x.get('candidate') else None,exitCode=x.get('exitCode'));deployment.append(row)
  if 'http' in p.name or p.parent.name=='http-assets-ko-es-v1':http.append(row)
byhash=collections.defaultdict(list)
for r in deployment:byhash[r['sha256']].append(r['path'])
duplicates=[{'sha256':h,'paths':p} for h,p in byhash.items() if len(p)>1]
# Final raw HTTP readback must bind to this exact local release and its assets, not an inherited filename.
final=[];releases=[]
for env,folder in [('prod','prod-es'),('dev','dev-es-v3')]:
 base=RUN/'multilingual-publication-v2/catalog-ko-es-v1'/folder;r=read(base/'final-http-ko-es-receipt-v1.json');files={x['path'].lstrip('/'):x for x in r['files']};filechecks=[]
 for name,record in files.items():
  f=base/'public'/name;ok=f.is_file() and sha(f)==record['sha256'];filechecks.append({'path':name,'matchesSnapshot':ok,'status':record['status']});assert ok
 cat=read(base/'public/multilingual-v3.json');page=next(p for p in cat['pages'] if p['id']=='resi-20261004-69ba7a66')
 final.append({'environment':env,'receipt':str((base/'final-http-ko-es-receipt-v1.json').relative_to(RUN)),'files':len(files),'matchedSnapshotFiles':sum(c['matchesSnapshot'] for c in filechecks),'ranges':len(r['ranges']),'range206':sum(x['status']==206 for x in r['ranges']),'hasTimestamp':any(k in r for k in ('verifiedAt','startedAt','finishedAt','observedAt')),'hasDeploymentVersion':any('version' in k.lower() and k!='schemaVersion' for k in r),'catalogSha256':files['multilingual-v3.json']['sha256'],'deviceAcceptance':r['deviceAcceptance'],'venueAcceptance':r['venueAcceptance'],'fileChecks':filechecks})
 for loc in ('ko','es'):
  p=base/f'public/releases-v2/resi-20261004-69ba7a66/{loc}.json';release=read(p);raw=read(f'multilingual-publication-v2/http-assets-ko-es-v1/{env}-{loc}.json');assetpath=RUN/f'multilingual-publication-v2/http-assets-ko-es-v1/{env}-{loc}.json';assert release['httpVerification']['evidenceSha256']==sha(assetpath);assets={x['path'].lstrip('/'):x['sha256'] for x in raw['assets']};matches=sum(assets.get(x['path'].lstrip('/'))==x['sha256']==files[x['path'].lstrip('/')]['sha256'] for x in release['assets']);target=page['targets'][loc];assert target['releasePackageJsonSha256']==sha(p);releases.append({'environment':env,'locale':loc,'releasePath':str(p.relative_to(RUN)),'releaseSha256':sha(p),'catalogTarget':target,'httpEvidenceHashMatchesRawReceipt':True,'assetHashesMatchBothHttpReceipts':matches,'assetCount':len(release['assets']),'rawAssetsVerifiedAt':raw['verifiedAt'],'deviceAcceptance':release['deviceAcceptance']['status'],'venueAcceptance':release['venueAcceptance']['status']})
# Final human audio receipts retain machine status and can be joined to published track SHA.
audio=[]
for loc,name in [('zh-Hans','zh-publication-v1/audio-human-approved-v1/audio-human-review-receipt.json'),('ko','ko-publication-v1/human-approved-leading60-v1/human-reviewed-output-v1/audio-human-review-receipt.json'),('es','formal-layer3-execution-v2/es-publication-v1/human-approved-leading60-v1/audio-review-approved-v1/audio-human-review-receipt.json')]:
 r=read(name);audio.append({'locale':loc,'path':name,'reviewedAt':r.get('reviewedAt'),'trackSha256':r.get('trackSha256'),'machineScreeningStatus':r.get('machineScreeningStatus'),'adjudicatedGroups':len(r.get('asrAdjudications',[])),'fullPlayback':r.get('fullPlayback'),'videoSync1x':r.get('videoSync1x'),'decision':r.get('decision'),'reviewedUnitCount':len(r.get('reviewedUnitIds',[]))})
# Identify inherited HTTP receipts by comparing their recorded catalog against the adjacent snapshot.
stale_http=[]
for item in http:
 p=RUN/item['path'];x=read(p);catfile=p.parent/'public/multilingual-v3.json'
 entries=x.get('files',x.get('assets',[]))
 if catfile.exists() and isinstance(entries,list):
  catalogs=[z for z in entries if z.get('path','').lstrip('/')=='multilingual-v3.json']
  for z in catalogs:
   if z['sha256']!=sha(catfile):stale_http.append({'path':item['path'],'recordedCatalogSha256':z['sha256'],'adjacentSnapshotCatalogSha256':sha(catfile),'meaning':'Inherited receipt does not verify this candidate snapshot.'})
revision_request=read('formal-layer2-timing-revision-v1/human-translation-approval-request-v2.json');revised=[]
for row in revision_request['locales']:
 loc=row['targetLocale'];c=read(Path(row['candidatePath']));assert sha(Path(row['candidatePath']))==row['candidateRawSha256'];receipt=read(f'formal-layer2-timing-revision-v1/runs/{loc}-human-approved-v1/human-review-receipt.json');approved_path=RUN/f'formal-layer2-timing-revision-v1/runs/{loc}-human-approved-v1/candidate.approved.json';approved=read(approved_path);assert canonical(approved)==receipt['candidateJsonSha256'];launchmanifest=read(f'formal-layer3-execution-v2/launch-manifests-v1/{loc}.json');assert launchmanifest['selected']['candidate']['sha256']==sha(approved_path);assert launchmanifest['selected']['human_receipt']['sha256']==sha(RUN/f'formal-layer2-timing-revision-v1/runs/{loc}-human-approved-v1/human-review-receipt.json');event=ready(Path(row['candidatePath']),row['candidateCanonicalSha256']);revised.append({'locale':loc,'approvedAt':receipt['reviewedAt'],'ready':event,'readyToApprovalSeconds':delta(event['at'],receipt['reviewedAt']) if event else None,'launchManifestHashBound':True,'launchAt':None,'limitation':'Selected launch manifest has no dispatch timestamp; initial launch cannot be timed from a later reused-render accounting run.'})
browser=read('multilingual-publication-v2/browser-readback-three-locales-v1.json')
metrics={'schemaVersion':'retrospective-handoffs-release-audit-v1','scope':'offline specified RUN; control-receipt sample rules encoded in script; no mtime timing inference','initialApprovalHandoffs':handoffs,'initialCoverage':{'candidates':len(handoffs),'hashBoundApproved':len(handoffs),'readyEvents':sum(x['ready'] is not None for x in handoffs),'spokenLaunchBound':sum('launchAt' in x for x in handoffs)},'receiptSample':receipts,'receiptCoverage':{'controlReceipts':len(receipts),'withTimestamp':sum(bool(x['timestamps']) for x in receipts),'httpReceipts':len(http),'httpWithTimestamp':sum(bool(x['timestamps']) for x in http),'deploymentReceipts':len(deployment),'deploymentWithTimestamp':sum(bool(x['timestamps']) for x in deployment),'deploymentCandidateDirectoryMismatch':sum(x['candidateDirectoryMatches'] is False for x in deployment),'deploymentVersionPresent':sum(x['deploymentVersionPresent'] for x in deployment)},'deploymentReceiptDuplicates':duplicates,'deployments':deployment,'finalHttp':final,'finalReleaseBindings':releases,'humanAudioApprovals':audio,'browserReadback':{'observedAt':browser['observedAt'],'playbackTests':{x['targetLocale']:x['playbackTest'] for x in browser['locales']},'deviceAcceptance':browser['deviceAcceptance'],'venueAcceptance':browser['venueAcceptance']},'timingRevisionHandoffs':revised,'inheritedHttpCatalogMismatch':stale_http,'evidence':E}
(HERE/'metrics.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'coverage':metrics['receiptCoverage'],'handoffs':handoffs,'initialCoverage':metrics['initialCoverage'],'duplicates':duplicates,'audio':audio},ensure_ascii=False,indent=2))
