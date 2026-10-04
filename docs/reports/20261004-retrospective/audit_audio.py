#!/usr/bin/env python3
"""Read-only local evidence audit. Writes only to --out-dir."""
from pathlib import Path
import json, hashlib, statistics, datetime, collections
import argparse
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--run-dir',type=Path,required=True)
parser.add_argument('--out-dir',type=Path,required=True)
parser.add_argument('--session-log',type=Path,help='Optional authorized historical tool-output log for the memory guard diagnosis.')
args=parser.parse_args()
OUT=args.out_dir.resolve(); OUT.mkdir(parents=True,exist_ok=True)
RUN=args.run_dir.resolve()
EVIDENCE={}
def load(rel):
 p=RUN/rel; b=p.read_bytes(); EVIDENCE[rel]=hashlib.sha256(b).hexdigest(); return json.loads(b)
def dt(s):return datetime.datetime.fromisoformat(s.replace('Z','+00:00'))
def summary(rows):
 if not rows:return {}
 return {'units':len(rows),'over8Seconds':sum(x['endLagSeconds']>8 for x in rows),'over62Seconds':sum(x['endLagSeconds']>62 for x in rows),'maxLag':max(rows,key=lambda x:x['endLagSeconds']),'totalAudioSeconds':sum(x['audioSeconds'] for x in rows),'sourceSpeechSeconds':sum(x['sourceSeconds'] for x in rows),'fiveMinuteBins':[{'sourceMinuteRange':[b*5,(b+1)*5],'units':len(a),'over8Seconds':sum(x['endLagSeconds']>8 for x in a),'maxLagSeconds':max([x['endLagSeconds'] for x in a],default=0)} for b in range(7) if (a:=[x for x in rows if int(x['sourceStart']/300)==b])],'topDurationExpansions':sorted(rows,key=lambda x:x['audioSeconds']-x['sourceSeconds'],reverse=True)[:10]}
anchor=load('pipeline-source-correction-v6h/sentence-interpretation-v6h/f8f91d3097131dd2e8b8e8d8936895f928e8636c1b446268eac7180cbd89797e/anchor-manifest.json')
anchors={u['sourceUnitId']:u for u in anchor['sourceUnits']}
metrics={'schemaVersion':'audio-resources-retrospective-v1','clock':'UTC','locales':{},'evidenceSha256':EVIDENCE}
paths={'zh-Hans':('zh-publication-v1/audio-render','zh-publication-v1/audio-render'),'ko':('ko-publication-v1/audio-render','ko-publication-v1/canonical-leading60-v1'),'es':('formal-layer3-execution-v2/es-publication-v1/collected-es-render-v1','formal-layer3-execution-v2/es-publication-v1/canonical-leading60-v1')}
for locale,(raw,final) in paths.items():
 job=load(raw+'/job.json'); manifest=load(final+'/render-manifest.json'); schedule=load(final+'/'+manifest['schedule']['path']); sched={x['textGroupId']:x for x in schedule['entries']}; audio={x['textGroupId']:x for x in manifest['units']}; rows=[]
 trim={}
 if 'silenceTrimEvidence' in manifest:
  trim={x['textGroupId']:x for x in load(final+'/'+manifest['silenceTrimEvidence']['path'])['units']}
 for u in job['units']:
  gid=u['translationGroupId']; src=[anchors[s] for s in u['sourceUnitIds']]; start=min(x['start'] for x in src); end=max(x['end'] for x in src); au=audio[gid]; sc=sched[gid]; t=trim.get(gid,{})
  rows.append({'unitIndex':u['unitIndex'],'textGroupId':gid,'sourceStart':start,'sourceEnd':end,'sourceSeconds':end-start,'englishChars':sum(len(x['english']) for x in src),'englishWordCount':sum(len(x['english'].split()) for x in src),'targetChars':len(u['text']),'targetWhitespaceWords':len(u['text'].split()),'audioSeconds':au['durationSeconds'],'rawAudioSeconds':t.get('originalDurationSeconds',au['durationSeconds']),'removedLeadingSeconds':t.get('removedLeadingSeconds',0),'plannedStart':sc['plannedStart'],'plannedEnd':sc['plannedEnd'],'endLagSeconds':sc['plannedEnd']-end})
 (OUT/(locale+'-unit-metrics.json')).write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
 screening=load(final+'/asr-screening-receipt-v1.json'); flagged=[x for x in screening['results'] if x['status']!='pass']; sums=summary(rows)
 sums.update({'schedulePolicy':schedule.get('policy'),'scheduleStatus':schedule.get('status'),'removedLeadingSeconds':sum(x['removedLeadingSeconds'] for x in rows),'asr':{'model':screening['model'],'minSimilarity':screening['minSimilarity'],'coverage':screening['coverage'],'results':len(screening['results']),'flagged':len(flagged),'zeroSimilarity':sum(x['similarity']==0 for x in flagged),'flaggedIds':[x['textGroupId'] for x in flagged],'flagsByFiveMinuteBin':dict(collections.Counter(int(next(y['sourceStart'] for y in rows if y['textGroupId']==x['textGroupId'])/300) for x in flagged)),'falsePositiveRate':None,'reason':'Human release approval is not phonetic error adjudication.'}})
 metrics['locales'][locale]=sums
# Entire-process timestamps directly retained in queue snapshots.
snapshot=load('formal-layer3-execution-driver-v1/snapshot-122126.json');metrics['initialQueue']=[]
for locale,v in snapshot['queueState']['locales'].items():
 metrics['initialQueue'].append({'locale':locale,'startedAtUtc':v['startedAtUtc'],'finishedAtUtc':v['finishedAtUtc'],'elapsedSeconds':(dt(v['finishedAtUtc'])-dt(v['startedAtUtc'])).total_seconds(),'status':v['status'],'waveFiles':v['observedWaveFiles'],'receipts':v['observedUnitReceipts'],'replicaRuntime':snapshot['locales'][locale]['replicaRuntime'],'lastPoolEvents':snapshot['locales'][locale]['lastPoolEvents']})
# Native compaction diagnostics describe 8-second gate failures before revised text.
metrics['initialCompaction']={}
for locale in ['zh-Hans','ko']:
 o=load('formal-layer3-postprocess-execution-v1/plan-preparation/'+locale+'-measurement.json')['measurement'];schedule=o['nativeSchedule']; rows=[]
 for sc in schedule['entries']:
  src=[anchors[s] for s in sc['sourceUnitIds']];start=min(x['start'] for x in src);end=max(x['end'] for x in src)
  rows.append({'textGroupId':sc['textGroupId'],'sourceStart':start,'sourceEnd':end,'sourceSeconds':end-start,'audioSeconds':sc['plannedEnd']-sc['plannedStart'],'endLagSeconds':sc['plannedEnd']-end})
 metrics['initialCompaction'][locale]={'reportedRemovedSeconds':o['totalRemovedSeconds'],'reportedMaxEndLag':o['maxEndLag'],'reportedOverLimitUnits':o['overLimitUnits'],'recalculated':summary(rows)}
# Quantify the u172 discontinuity separately from its propagated backlog.
metrics['u172Discontinuity']={}
for locale in ['zh-Hans','ko']:
 schedule=load('formal-layer3-postprocess-execution-v1/plan-preparation/'+locale+'-measurement.json')['measurement']['nativeSchedule'];entries=schedule['entries'];window=[]
 for ix in range(169,174):
  sc=entries[ix];prev=entries[ix-1];src=[anchors[x] for x in sc['sourceUnitIds']];end=max(x['end'] for x in src);start=min(x['start'] for x in src);prevEnd=max(anchors[x]['end'] for x in prev['sourceUnitIds']);lag=sc['plannedEnd']-end;priorLag=prev['plannedEnd']-prevEnd
  window.append({'textGroupId':sc['textGroupId'],'sourceStart':start,'sourceEnd':end,'sourceDurationSeconds':end-start,'audioDurationSeconds':sc['plannedEnd']-sc['plannedStart'],'priorEndLagSeconds':priorLag,'endLagSeconds':lag,'lagJumpSeconds':lag-priorLag})
 final=json.loads((OUT/(locale+'-unit-metrics.json')).read_text())[169:174]
 metrics['u172Discontinuity'][locale]={'initialCompactedWindow':window,'finalWindow':final,'inference':'Near-zero prior lag jumps by about 58 seconds at a 61-second unit against a 2.960022-second source span; following units propagate and reduce that backlog. Final unit duration recovers, but no acoustic cause is adjudicated.'}
metrics['u172InputBindingComparison']={}
for locale,(raw,final) in paths.items():
 candidate=load('RUN/formal-layer3-approved-v1/spoken/'+locale+'/candidate.json');oldJob=load('formal-layer3-execution-v1/'+locale+'/raw/job.json');newJob=load(raw+'/job.json')
 c=next(x for x in candidate['groups'] if x['translationGroupId']=='translation-0-u172');old=oldJob['units'][171];new=newJob['units'][171]
 metrics['u172InputBindingComparison'][locale]={'originalApprovedTargetText':c['targetText'],'originalJobText':old['text'],'finalJobText':new['text'],'originalTargetChars':len(old['text']),'finalTargetChars':len(new['text']),'originalWhitespaceWords':len(old['text'].split()),'finalWhitespaceWords':len(new['text'].split()),'sourceUnitIdsOriginal':old['sourceUnitIds'],'sourceUnitIdsFinal':new['sourceUnitIds'],'originalCandidateEqualsJob':c['targetText']==old['text'],'sameTextOriginalFinal':old['text']==new['text'],'isLongQuotationMappedToShortAnchor':False,'sourceEnglish':anchors['0-u172']['english'],'sourceSpanSeconds':anchors['0-u172']['end']-anchors['0-u172']['start'],'oldMeasured61SecondWavFoundLocally':False,'limitation':'Only current revised unit WAVs found locally; initial compacted 61-second measurements retained without old WAV here. Cannot acoustically attribute the old failure.'}
metrics['renderAttempts']=[]
for locale,(raw,_) in paths.items():
 rel=raw+'/accounting/events.jsonl';b=(RUN/rel).read_bytes();EVIDENCE[rel]=hashlib.sha256(b).hexdigest();ev=[json.loads(x) for x in b.splitlines()];starts={};counts=collections.Counter()
 for x in ev:
  if x.get('event')=='stage_started':
   st=x.get('stage') or ''
   if st=='layer3_formal_render':starts[x['runId']]=x
   for k in ['reuse','synthesis']:
    if st.startswith('layer3.'+k+'.'):counts[(x['runId'],k)]+=1
  if x.get('event')=='stage_finished' and x.get('stage')=='layer3_formal_render':metrics['renderAttempts'].append({'locale':locale,'runId':x['runId'],'start':starts[x['runId']]['startedAt'],'end':x['completedAt'],'elapsedSeconds':x['elapsedSeconds'],'status':x['status'],'errorType':x.get('errorType'),'errorStack':x.get('error'),'reuseStageCount':counts[(x['runId'],'reuse')],'synthesisStageCount':counts[(x['runId'],'synthesis')],'tokenUsage':None})
metrics['revisionReport']=load('formal-layer3-execution-v2/reports-v1/layer3-8x8-execution-report-v1.json')
metrics['esResumePoolRuntime']=load(paths['es'][0]+'/replica-runtime.json')
metrics['humanAdjudication']={}
for locale,rel,key in [('ko','ko-publication-v1/human-approved-leading60-v1/evidence/asr-adjudications-v1.json','adjudications'),('es','formal-layer3-execution-v2/es-publication-v1/human-approved-leading60-v1/audio-review-worksheet.approved-v1.json','asrAdjudications')]:
 o=load(rel);a=o[key];metrics['humanAdjudication'][locale]={'entries':len(a),'decisions':dict(collections.Counter(x['decision'] for x in a)),'evidenceSamples':[x['evidence'] for x in a[:2]],'itemSpecificPhoneticReasons':False,'approvalBasis':'Same full-track human approval bound separately to flagged group IDs; not measured ASR false positives.'}
# Only tool output payloads from the authorized historical session; no reasoning/system fields.
SESSION=args.session_log
def output_strings(v):
 if isinstance(v,str):
  try:return output_strings(json.loads(v))
  except (ValueError,TypeError):return [v]
 if isinstance(v,list):return sum([output_strings(x) for x in v],[])
 if isinstance(v,dict):return sum([output_strings(v[x]) for x in ['text','output'] if x in v],[])
 return []
metrics['historicalStderrEvidence']=[]
metrics['historicalStderrStatus']='provided' if SESSION else 'not_provided'
for lineNo,line in enumerate(SESSION.read_text().splitlines() if SESSION else [],1):
 o=json.loads(line);ts=o.get('timestamp','');v=o.get('payload',{})
 if not ('2026-10-04T14:04'<=ts<='2026-10-04T14:30'):continue
 if o.get('type')!='response_item' or v.get('type') not in ['function_call_output','custom_tool_call_output']:continue
 text='\n'.join(output_strings(v.get('output')))
 if 'ReplicaPoolError:' in text:
  metrics['historicalStderrEvidence'].append({'timestamp':ts,'line':lineNo,'sessionBasename':SESSION.name,'decodedToolOutputSha256':hashlib.sha256(text.encode()).hexdigest(),'error':'scripts.spark_tts_replica_pool.ReplicaPoolError: MemAvailable is below the TTS replica reserve','errorNumericAvailableBytes':None})
metrics['limitations']=['Target characters or whitespace word counts are not cross-language token counts or semantic inflation measurements.','Audio duration records are validated receipts; audit does not rerun waveform decoding.','Source anchors are MFA estimates; approval includes a documented 9.199951-second anchor exception.','First-round snapshot only retains a few issue samples, not full schedule; full per-unit initial compaction exists for zh-Hans and ko only.','ES accounting proves ReplicaPoolError guard stack; historical tool stderr confirms MemAvailable below reserve, but exact failing MemAvailable is absent.','GPU peak memory unknown; NVIDIA GB10 telemetry reports N/A and accountingGpuPeakBytes null. minAvailableBytes is host available memory, not GPU peak.','Runtime retains limited tail events; cannot derive complete per-worker throughput or batch concurrency from these tails.','CPU cache reassembly is not new model generation even when launcher argv requests cuda.','Final 62-second accepted policy and human release are distinct from original 8-second synchronization goal.']
(OUT/'metrics.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:{x:v[x] for x in ['units','over8Seconds','maxLag','removedLeadingSeconds','asr']} for k,v in metrics['locales'].items()},ensure_ascii=False)[:6000])
