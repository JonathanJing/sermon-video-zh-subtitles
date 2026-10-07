#!/usr/bin/env python3
"""Read-only production audit. Writes only to --out-dir; no model/API calls."""
from pathlib import Path
import json, hashlib, collections
import argparse
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--run-dir',type=Path,required=True)
parser.add_argument('--out-dir',type=Path,required=True)
args=parser.parse_args()
OUT=args.out_dir.resolve(); OUT.mkdir(parents=True,exist_ok=True)
R=args.run_dir.resolve()
sha=lambda b:hashlib.sha256(b).hexdigest()
canon=lambda d:sha(json.dumps(d,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())
def load(p):return json.loads(p.read_text())
def ref(p):return {'path':str(p.relative_to(R)),'sha256':sha(p.read_bytes())}
index=load(R/'timing-token-audit-v1/accounting-audit.json')
ledger_inputs=[]; events={}
for item in index['inputs']:
 p=R/item['path']; actual_ref=ref(p)
 if actual_ref['sha256'] != item['sha256']:
  raise ValueError('Ledger changed since frozen accounting index: '+item['path'])
 ledger_inputs.append(actual_ref)
 for line in p.open():
  e=json.loads(line);events.setdefault(e['eventId'],(str(p.parent.parent.relative_to(R)),e))
starts={e['attemptId']:(path,e) for path,e in events.values() if e['event']=='api_attempt_started'}
ends={e['attemptId']:(path,e) for path,e in events.values() if e['event']=='api_attempt'}
selected=lambda p:p.startswith(('canonical-layer2-v6-override/','canonical-layer2-v7-user-confirmed/','canonical-production-v8/','canonical-spoken-','formal-layer2-timing-revision-v1/'))
rows={}
for a in index['attempts']:
 if selected(a['path']):
  rows[a['runId']]={**a,'cacheObservations':{},'cacheStageHits':0,'modelStageMissFlags':0,'failures':[],'identity':{}}
for path,e in events.values():
 if e['runId'] not in rows:continue
 row=rows[e['runId']]
 if e['event']=='run_started':row['jobMetadata']=e.get('metadata',{})
 if e['event']=='workflow_started' and 'executionIdentity' in e:
  ei=e['executionIdentity'];row.setdefault('executionIdentities',[]).append({'gitCommit':ei.get('gitCommit'),'loadedProjectCodeSha256':{k:v for k,v in ei.get('loadedProjectCodeSha256',{}).items() if k.endswith(('run_target_language_models.py','review_prompts.py','canonical_spoken_revision.py'))}})
 if e['event']=='log' and e.get('code')=='model_cache_observation':
  mode=e['fields'].get('reuseMode','unknown');row['cacheObservations'][mode]=row['cacheObservations'].get(mode,0)+1
 if e['event']=='stage_started' and e.get('stage','').startswith(('layer2.translator.','layer2.reviewer.')):
  row['cacheStageHits' if e.get('cacheHit') else 'modelStageMissFlags']+=1
 if e['event']=='stage_finished' and e.get('status')=='failed':
  row['failures'].append({'stage':e.get('stage'),'errorType':e.get('errorType'),'lastFrame':e.get('error',{}).get('frames',[])[-1:]})
for row in rows.values():
 p=R/row['path']/'request.json'
 if p.exists():
  d=load(p);row['identity']={k:d.get(k) for k in ['englishSourcePackageJsonSha256','anchorManifestSha256','translationPolicySha256','targetLocale']};row['identity']['sourceUnitsSha256']=canon(d.get('sourceUnits'));row['identity']['requestFile']=ref(p)
# policies: use bounded structural scan, omit translation/source text.
policies={}; evidence=[]
roots=['policy-prep-v6-override','canonical-layer2-v6-override','canonical-layer2-v7-user-confirmed','canonical-production-v8','formal-layer3-prep-v1','source-preparation','formal-layer2-timing-revision-v1']
for root in roots:
 for p in (R/root).rglob('*.json'):
  if p.name.startswith('group-') or any(x in p.parts for x in ['accounting','review-worksheets-v1']):continue
  if p.stat().st_size>2000000:continue
  try:d=load(p)
  except (ValueError,OSError):continue
  if not isinstance(d,dict):continue
  if isinstance(d.get('translator'),dict) and isinstance(d.get('reviewer'),dict) and 'languageReview' in d:
   policies[canon(d)]={'ref':ref(p),'translator':d['translator'],'reviewer':d['reviewer'],'pluginSha256':d['languageReview'].get('pluginImplementationSha256'),'componentSha256':d.get('componentSha256')}
  if any(x in p.name for x in ['brief','audit','receipt','diagnostic','preparation-plan','validation-summary']):
   # Retain identity/count/reason metadata; never export full translations or prompts.
   q={k:v for k,v in d.items() if k in ['schemaVersion','status','reason','changedFields','sourceContentChanged','sourceAndAnchorsUnchanged','allModelFacingPolicyFieldsUnchanged','newApiCalls','newModelCalls','changedGroups','sourceAndPolicyUnchanged','newModelEvidenceRequired','englishWordsAndAnchorsUnchanged','failedGroups','cacheFileCount','actualReplay']}
   if 'actualReplay' in q:q['actualReplay']={k:v for k,v in q['actualReplay'].items() if k in ['groups','originalPluginFailedGroupCount','fixedPluginFailedGroupCount']}
   if isinstance(d.get('groups'),list):q['groupCount']=len(d['groups']);q['groupIds']=[x.get('translationGroupId') for x in d['groups'] if isinstance(x,dict)]
   if len(q.get('groupIds',[]))>25:q['groupIdsSha256']=canon(q.pop('groupIds'))
   if q:evidence.append({'ref':ref(p),'metadata':q})
for row in rows.values():
 jobid=row.get('jobMetadata',{}).get('jobSha256')
 if jobid:
  candidates=list((R/row['path'].split('/')[0]).glob('**/'+jobid+'/request.json'))
  if candidates:row['jobInputIdentity']={'ref':ref(candidates[0]),'identity':load(candidates[0]).get('identity')}
 identity=row['identity'];h=identity.get('translationPolicySha256');identity['policy']=policies.get(h)
# Global exact-request duplicates. Repeated terminal records dedup by attemptId above.
byhash=collections.defaultdict(list)
for aid,(path,s) in starts.items():
 h=s.get('settings',{}).get('requestPayloadSha256')
 if not h:continue
 end=ends.get(aid,(None,{}))[1];u=end.get('usage') or {}
 byhash[h].append({'path':path,'attemptId':aid,'at':s['recordedAt'],'model':s.get('model'),'status':end.get('status','unknown'),'responseIdSha256':sha(str(end.get('responseId')).encode()) if end.get('responseId') else None,'inputTokens':u.get('inputTokens'),'outputTokens':u.get('outputTokens'),'stage':s.get('stage')})
dup=[{'requestPayloadSha256':h,'attempts':sorted(v,key=lambda x:x['at'])} for h,v in byhash.items() if len(v)>1 and any(selected(x['path']) for x in v)]
# Exact payload repetition is not invoice evidence. Count every successful usage-bearing request after first successful one.
repeated=[]
for d in dup:
 completed=[x for x in d['attempts'] if x['status']=='completed' and isinstance(x['inputTokens'],int) and isinstance(x['outputTokens'],int)]
 repeated+=completed[1:]
# Attribute by explicit revision brief / documented policy event. This is a trigger,
# not a counterfactual estimate of unavoidable spending.
continuations={
 'canonical-layer2-v6-override/text/es-repair-v1':('canonical-layer2-v6-override/text/es','canonical-layer2-v6-override/partial-repair-es-v1.json'),
 'canonical-layer2-v6-override/text/zh-Hans-repair-v1':('canonical-layer2-v6-override/text/zh-Hans','canonical-layer2-v6-override/partial-repair-zh-Hans-v1.json'),
 'canonical-production-v8/revision-3/text/es':('canonical-production-v8/revision-2/text/es','canonical-production-v8/revision-3/es-partial-repair-brief.json')}
def cause(path,e):
 import re
 group=int(re.search(r'group-(\d+)',e.get('stage','')).group(1)) if re.search(r'group-(\d+)',e.get('stage','')) else None
 if path in continuations:
  prior,brief=continuations[path];gs={int(x['sourceUnitIds'][0].split('u')[-1]) for x in load(R/brief)['groups']}
  if group in gs:return 'source_context_targeted_repair'
  suffix='astra' if '.translator.' in e.get('stage','') else 'sol'
  return 'prior_result_missing_continuation' if not (R/prior/f'group-{group:04d}-{suffix}.json').exists() else 'unknown_continuation'
 if path.startswith('canonical-layer2-v6-override/'):return 'initial_selected_scope_prior_trigger_unknown'
 if path.endswith('ko-v7-repair-v1') or path=='canonical-production-v8/revision-3/text/ko' or path=='canonical-production-v8/revision-4/text/es':return 'source_bound_content_targeted_repair'
 if path.startswith('canonical-layer2-v7-'):return 'human_confirmed_policy_revision'
 if path.startswith('canonical-production-v8/revision-2/text/zh-Hans'):return 'model_policy_quote_map_was_missing'
 if path.startswith('canonical-production-v8/revision-2/text/ko'):return 'model_policy_remove_unspoken_citations'
 if path.startswith('canonical-production-v8/'):return 'source_receipt_and_context_policy_rebinding'
 if path.startswith('formal-layer2-timing-revision-v1/'):
  if path.endswith(('zh-Hans-attempt3','ko-attempt2','es-attempt2')):return 'timing_followup_plugin_repair'
  return 'measured_audio_timing_revision'
 if path=='canonical-spoken-v5/es':return 'plugin_numeric_spelling_repair' if group in [14,398] else 'spoken_timing_forecast_repair'
 if path=='canonical-spoken-v6/ko':return 'source_bound_content_targeted_repair' if group in [157,158] else 'spoken_timing_forecast_repair'
 if path in ['canonical-spoken-v2/zh-Hans','canonical-spoken-v3/zh-Hans']:return 'spoken_followup_targeted_revision'
 if path.startswith('canonical-spoken-'):return 'spoken_candidate_revision'
 return 'unknown'
causes={};call_causes=[]
for aid,(path,e) in ends.items():
 if not selected(path):continue
 c=cause(path,e);u=e.get('usage') or {};a=causes.setdefault(c,{'attempts':0,'knownInputTokens':0,'knownOutputTokens':0,'usageMissing':0})
 a['attempts']+=1
 if u.get('inputTokens') is None or u.get('outputTokens') is None:a['usageMissing']+=1
 a['knownInputTokens']+=u.get('inputTokens') or 0;a['knownOutputTokens']+=u.get('outputTokens') or 0
 call_causes.append({'attemptId':aid,'reason':c})
checks=[('attempts','apiAttempts'),('knownInputTokens','inputTokens'),('knownOutputTokens','outputTokens'),('usageMissing','usageMissing')]
for cause_key,run_key in checks:
 if sum(x[cause_key] for x in causes.values()) != sum(x[run_key] for x in rows.values()):
  raise ValueError('Cause and run totals differ: '+cause_key)
result={'scope':'Frozen accounting index (46 ledgers), unique eventId and attemptId; selected L2 paths. No invoice evidence. Cache misses are stage flags, not proof of rejection.','sourceInputs':ledger_inputs,'runs':sorted(rows.values(),key=lambda x:x['startedAt']),'exactPayloadDuplicateSummary':{'hashesWithMultipleAttempts':len(dup),'extraSuccessfulUsageBearingCalls':len(repeated),'extraKnownTokens':sum(x['inputTokens']+x['outputTokens'] for x in repeated)},'exactPayloadDuplicates':dup,'metadataEvidence':evidence,'reasonTotals':causes,'attributionRules':'Script cause(): explicit briefs for repair group IDs, prior file absence for incomplete continuations; policy audit trigger labels are not claims of minimum necessary cost.','scriptSha256':sha(Path(__file__).read_bytes())}
(OUT/'metrics.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'runs':len(rows),'duplicateSummary':result['exactPayloadDuplicateSummary'],'metadataEvidence':len(evidence)},ensure_ascii=False))
for row in result['runs']:print(row['path'],row['apiAttempts'],row['inputTokens']+row['outputTokens'],row['cacheObservations'],row['cacheStageHits'],row['modelStageMissFlags'])
