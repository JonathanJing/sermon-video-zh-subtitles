"""Offline evidence hashes, workflow code identities and receipt-stage hotspot checks."""
import argparse
import collections
import hashlib
import json
import subprocess
from pathlib import Path

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--run-dir',type=Path,required=True)
p.add_argument('--repo-dir',type=Path,required=True)
p.add_argument('--out-dir',type=Path,required=True)
a=p.parse_args()
r=a.run_dir.resolve(); repo=a.repo_dir.resolve(); out=a.out_dir.resolve()
expected=json.loads(Path(__file__).with_name('inputs.json').read_text())
sha=lambda b:hashlib.sha256(b).hexdigest()
for rel,h in expected['evidenceSha256'].items():
    if sha((r/rel).read_bytes()) != h:
        raise ValueError('Evidence differs from reviewed snapshot: '+rel)
index=json.loads((r/'timing-token-audit-v1/accounting-audit.json').read_text())
events={}
for x in index['inputs']:
    b=(r/x['path']).read_bytes()
    if sha(b)!=x['sha256']:raise ValueError('Frozen index mismatch: '+x['path'])
    for line in b.splitlines():
        e=json.loads(line)
        if e['eventId'] in events and events[e['eventId']]!=e:raise ValueError('Conflicting event identity')
        events[e['eventId']]=e
blobs={}; observations=[]
for e in events.values():
    if e.get('event')!='workflow_started' or not e.get('executionIdentity'):continue
    i=e['executionIdentity']; commit=i.get('gitCommit'); differs=[]
    for path,h in i.get('loadedProjectCodeSha256',{}).items():
        if not commit:continue
        key=(commit,path)
        if key not in blobs:
            result=subprocess.run(['git','-C',str(repo),'show',commit+':'+path],capture_output=True)
            blobs[key]=sha(result.stdout) if result.returncode==0 else None
        if blobs[key]!=h:differs.append(path)
    observations.append({'runId':e['runId'],'commit':commit,'dirty':i.get('trackedWorkingTreeDirty'),'differingLoadedPaths':differs})
counts={'count':len(observations),'dirty':sum(x['dirty'] is True for x in observations),'clean':sum(x['dirty'] is False for x in observations),'unknown':sum(x['dirty'] is None for x in observations),'loadedFilesDifferFromCommit':sum(bool(x['differingLoadedPaths']) for x in observations)}
assert counts==expected['workflowIdentityObservations'],counts
hotspots={}
for loc,rel in [('zh-Hans','zh-publication-v1/audio-render/accounting/events.jsonl'),('ko','ko-publication-v1/audio-render/accounting/events.jsonl')]:
    unique={}
    for line in (r/rel).read_text().splitlines():
        e=json.loads(line);unique[e['eventId']]=e
    roots=[x for x in unique.values() if x.get('event')=='stage_finished' and x.get('stage')=='layer3_formal_render']
    assert len(roots)==1
    run=roots[0]; totals=collections.defaultdict(float)
    for e in unique.values():
        if e.get('runId')!=run['runId'] or e.get('event')!='stage_finished':continue
        for name in ['receipt','reuse','validation','commit','cache_admission','unit']:
            if e.get('stage','').startswith('layer3.'+name+'.'):totals[name]+=e['elapsedSeconds']
    exp=expected['audio']['cacheAssemblyHotspot'][loc]
    assert abs(totals['receipt']-exp['leafSeconds']['receipt'])<1e-6
    assert abs(run['elapsedSeconds']-exp['runSeconds'])<1e-6
    hotspots[loc]={'runSeconds':run['elapsedSeconds'],'stageSeconds':dict(totals),'receiptShare':totals['receipt']/run['elapsedSeconds']}
for x in expected['audio']['codeHashes']:
    b=(r/x['path']).read_bytes();assert sha(b)==x['sha256']
    rel=x['path'].split('/repo/',1)[1]
    blob=subprocess.check_output(['git','-C',str(repo),'show',expected['audio']['baseCommit']+':'+rel]);assert b==blob
out.mkdir(parents=True,exist_ok=True)
(out/'identity-audio.json').write_text(json.dumps({'workflowCounts':counts,'observations':observations,'hotspots':hotspots},ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'workflowCounts':counts,'hotspots':hotspots},ensure_ascii=False))
