"""Offline L1/L2 runtime reconstruction; writes only --out-dir."""
from pathlib import Path
import json,hashlib,subprocess,collections
import argparse
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--run-dir',type=Path,required=True)
p.add_argument('--out-dir',type=Path,required=True)
p.add_argument('--repo-dir',type=Path,required=True)
args=p.parse_args()
OUT=args.out_dir.resolve();OUT.mkdir(parents=True,exist_ok=True)
R=args.run_dir.resolve()
REPO=args.repo_dir.resolve()

sha=lambda b:hashlib.sha256(b).hexdigest()
canon=lambda d:sha(json.dumps(d,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())
def read(p):return json.loads(p.read_text())
def ref(p):return {'path':str(p.relative_to(R)),'sha256':sha(p.read_bytes())}
idx=read(R/'timing-token-audit-v1/accounting-audit.json');events={};inputs=[]
for f in idx['inputs']:
 p=R/f['path'];assert sha(p.read_bytes())==f['sha256'];inputs.append(ref(p))
 for l in p.open():
  e=json.loads(l);events.setdefault(e['eventId'],(str(p.parent.parent.relative_to(R)),e))
select=lambda p:p.startswith(('pipeline','english-source-judge','canonical-layer2','canonical-production','canonical-spoken','formal-layer2-timing'))
modules=['scripts/sermon_pipeline.py','scripts/judge_english_source_for_translation.py','scripts/run_sentence_interpretation_models.py','scripts/run_target_language_models.py','scripts/canonical_layer2_controller.py','scripts/layer2_api_concurrency.py','scripts/canonical_spoken_revision.py','scripts/sermon_sentence_interpretation.py']
blobs={}
def committed_hash(commit,module):
 k=(commit,module)
 if k not in blobs:
  x=subprocess.run(['git','-C',str(REPO),'show',commit+':'+module],capture_output=True);blobs[k]=sha(x.stdout) if x.returncode==0 else None
 return blobs[k]
workflows=[];runs={x['runId']:{**x,'configuration':[],'workflowIds':[]} for x in idx['attempts'] if select(x['path'])}
for path,e in events.values():
 if not select(path):continue
 if e['event']=='workflow_started':
  ei=e.get('executionIdentity',{});commit=ei.get('gitCommit');hs=ei.get('loadedProjectCodeSha256',{});mods={}
  for mod in modules:
   if mod in hs:mods[mod]={'loadedSha256':hs[mod],'commitBlobSha256':committed_hash(commit,mod),'matchesCommitBlob':hs[mod]==committed_hash(commit,mod)}
  workflows.append({'path':path,'at':e['recordedAt'],'runId':e['runId'],'workflow':e.get('workflow'),'gitCommit':commit,'trackedWorkingTreeDirty':ei.get('trackedWorkingTreeDirty'),'modules':mods})
  if e['runId'] in runs:runs[e['runId']]['workflowIds'].append(e.get('workflowId'))
 if e['event']=='workload' and 'concurrency' in (e.get('stage') or '') and e['runId'] in runs:runs[e['runId']]['configuration'].append(e.get('metrics'))
starts={e['attemptId']:(p,e) for p,e in events.values() if e['event']=='api_attempt_started'};ends={e['attemptId']:(p,e) for p,e in events.values() if e['event']=='api_attempt'}
for rid,row in runs.items():
 ticks=[];missing=0
 for aid,(p,e) in starts.items():
  if e['runId']!=rid:continue
  end=ends.get(aid)
  if end is None:missing+=1;continue
  ticks.extend([(e['recordedAt'],1),(end[1]['recordedAt'],-1)])
 n=mx=0
 for _,delta in sorted(ticks):n+=delta;mx=max(mx,n)
 row['observedMaxOverlappingApiAttempts']=mx;row['apiStartedWithoutTerminal']=missing
# Exact duplicate proof from both original caches and accounting, no source text retained.
rp=R/'english-source-judge-v3/parallel-cache-reconciliation.json';rec=read(rp)
byresponse={e.get('responseId'):e for _,e in events.values() if e['event']=='api_attempt' and e.get('responseId')};dup=[]
for x in rec['duplicateStages']:
 name=x['stage']+'-'+x['requestSha256']+'.json';p=R/'cache'/name;q=R/'english-source-judge-v3/cache'/name;a=read(p);b=read(q)
 assert a['request']==b['request'] and a['requestSha256']==b['requestSha256']==canon(a['request']);assert a['response']['id']!=b['response']['id']
 for d in [a,b]:
  assert canon(d['response'])==d['responseSha256'];e=byresponse[d['response']['id']];u=d['response']['usage'];assert u['prompt_tokens']==e['usage']['inputTokens'] and u['completion_tokens']==e['usage']['outputTokens']
 dup.append({'requestSha256':x['requestSha256'],'payloadSha256':canon(a['request']['payload']),'stage':x['stage'],'prewarm':ref(p),'canonical':ref(q),'distinctResponseIdsSha256':[sha(d['response']['id'].encode()) for d in [a,b]],'bothResponseIdsFoundInIndexedAccounting':True,'prewarmUsage':a['response']['usage']['total_tokens']})
commits={}
for w in workflows:
 c=w['gitCommit']
 if c not in commits:
  t=subprocess.check_output(['git','-C',str(REPO),'show','-s','--format=%H%n%P%n%cI%n%s',c],text=True).splitlines();commits[c]={'parents':t[1].split(),'committedAt':t[2],'subject':t[3]}
# Launch records expose controller options through hashes/counts, avoid raw argv/local private paths.
launch=[]
for root in ['canonical-layer2-v6-override','canonical-layer2-v7-user-confirmed','canonical-production-v8']+[f'canonical-spoken-v{i}' for i in range(1,7)]:
 for p in (R/root).rglob('request.json'):
  d=read(p)
  if d.get('schemaVersion')!='sermon-workflow-job-v1':continue
  command=d.get('command',[]);launch.append({'ref':ref(p),'identity':d.get('identity'),'commandSha256':d.get('commandSha256'),'flags':[s for s in command if isinstance(s,str) and s.startswith('--')],'timeoutSeconds':d.get('timeoutSeconds')})
extra=[rp,R/'prewarm_english_judge_v3.py',R/'prewarm_english_judge_v4.py',R/'migrate_plugin_revision_cached_layer2_v2.py',R/'source-preparation/cache-migration-v2-review/validation-summary.json',R/'formal-layer3-prep-v1/spoken-l2-execution-plan-v1/execution-plan.json']
result={'scope':'Historical L1/L2 run evolution, existing indexed events; git timestamps are not dispatch times. No model calls.','ledgerInputs':inputs,'runs':sorted(runs.values(),key=lambda x:x['startedAt']),'workflowExecutionIdentities':sorted(workflows,key=lambda x:x['at']),'commits':commits,'launchRecords':launch,'duplicateL1Proof':{'groups':dup,'extraSuccessfulResponses':len(dup),'knownExtraPrewarmTokens':sum(x['prewarmUsage'] for x in dup),'alreadyIncludedInProductionKnownTokens':24947374},'supportingInputs':[ref(p) for p in extra],'scriptSha256':sha(Path(__file__).read_bytes())}
(OUT/'text-metrics.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
for x in result['runs']:print(x['path'],x['stage'],x['apiAttempts'],x['observedMaxOverlappingApiAttempts'],x['configuration'])
print('dirty_modules')
for w in result['workflowExecutionIdentities']:
 changed=[k for k,v in w['modules'].items() if not v['matchesCommitBlob']]
 if changed:print(w['at'],w['path'],w['workflow'],w['gitCommit'][:7],changed)
