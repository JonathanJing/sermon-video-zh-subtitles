"""Run the real unified CLI/owner with 100 persisted zero-provider transitions."""
from __future__ import annotations
import argparse
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import subprocess
import sys
import time
import wave
from scripts.sermon_unified import contracts as c


def verify(root):
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=False)
    media=root/'source.wav'
    with wave.open(str(media),'wb') as f:
        f.setparams((1,2,16000,0,'NONE','not compressed'));f.writeframes(b'\0\0'*1600)
    sha=c.file_sha(media);now=datetime.now(timezone.utc);modules=c.required_modules()
    bindings={'media':{'path':str(media),'sha256':sha}}
    steps=[{'id':'media','stageId':'media_verify','adapter':'media.verify','dependsOn':[],'scope':'media_verified'}]
    for n in range(1,100):
        p=root/f'fixed-{n}.json';p.write_text(json.dumps({'fixtureOnly':True,'fixtureSetId':'unified-cli-v2',
            'mediaSha256':sha,'stageId':'media_verify'}))
        bindings[f'f{n}']={'path':str(p),'sha256':c.file_sha(p)}
        steps.append({'id':f'f{n}','stageId':'media_verify','adapter':'fixture.replay','configuration':f'f{n}',
                      'dependsOn':[steps[-1]['id']],'scope':'media_verified'})
    manifest={'schemaVersion':'sermon-unified-run-manifest-v2','productionRunId':'cli-fixture','runRevision':1,
        'jobRoot':str(root/'jobroot'),'content':{'contentId':'fixture','pageId':'fixture','category':'podcast','sourceDate':None},
        'source':{'sourceId':'fixture','mediaSha256':sha,'durationSeconds':.1,'window':{'startSeconds':0,'endSeconds':.1,
            'timeBase':'source_media','approvalReceiptSha256':None}},'locales':['zh-Hans'],
        'canaryScope':'media_verified','activeScope':'media_verified','finalScope':'dual_production_verified',
        'policies':[{'locale':'zh-Hans','policySha256':'a'*64,'promptSha256':'b'*64,'pluginSha256':'c'*64}],
        'budget':{'currency':'USD','limitMicroUsd':0},'transport':'fixture','fixtureSetId':'unified-cli-v2',
        'executionAdmission':{'modules':modules,'closureSha256':c.closure(modules)},'bindings':bindings,
        'executionWindow':{'timezone':'America/Los_Angeles','startsAt':(now-timedelta(minutes=1)).isoformat(),
            'deadlineAt':(now+timedelta(minutes=10)).isoformat()},'steps':steps}
    path=root/'manifest.json';path.write_text(json.dumps(manifest));store=root/'store'
    def cli(*args,accepted=(0,)):
        result=subprocess.run([sys.executable,str(c.ROOT/'scripts/sermon.py'),*args,'--state-root',str(store),'--json'],
                              capture_output=True,text=True,timeout=240)
        if result.returncode not in accepted:
            raise RuntimeError(f'CLI {args[:2]} failed: {result.returncode} {result.stdout} {result.stderr}')
        return json.loads(result.stdout)
    plan=cli('run','plan','--manifest',str(path));start=time.monotonic()
    submitted=cli('run','submit','--manifest',str(path),'--plan-hash',plan['plan']['planHash'])
    key=submitted['subject']['id']
    result=cli('job','wait','--run-id',key,'--timeout','180',accepted=(0,3,4))
    event=cli('run','events','--run-id',key);progress=event['progress']
    assert progress['completedSteps']==100, progress
    assert progress['handoff']['count']==99 and progress['handoff']['p95Seconds']<=2, progress['handoff']
    assert result['execution']['productionEligible'] is False
    assert result['cost']['reservedMicroUsd']==0
    report={'schemaVersion':'sermon-unified-cli-acceptance-v1','status':'passed','runKey':key,
            'transitions':100,'wallSeconds':time.monotonic()-start,'handoff':progress['handoff'],
            'newPaidRequests':0,'runtimeCodexTurns':0,'productionEligible':False,
            'scope':'offline_real_cli_and_detached_owner','planHash':plan['plan']['planHash']}
    (root/'acceptance.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True)
    print(json.dumps(verify(parser.parse_args().out),indent=2))
