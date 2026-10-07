"""Run the real unified CLI/owner with 100 persisted zero-provider transitions."""
from __future__ import annotations
import argparse
from datetime import datetime,timedelta,timezone
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import wave
from scripts.sermon_unified import contracts as c


def verify(root, *, with_resource_policy=False, media_path=None):
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=False)
    if media_path is None:
        media=root/'source.wav'
        with wave.open(str(media),'wb') as f:
            f.setparams((1,2,16000,0,'NONE','not compressed'));f.writeframes(b'\0\0'*1600)
        duration=.1
    else:
        media=Path(media_path).resolve(strict=True)
        probe=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration',
                              '-of','json',str(media)],capture_output=True,text=True,check=True)
        duration=float(json.loads(probe.stdout)['format']['duration'])
        if not math.isfinite(duration) or duration<=0:
            raise ValueError('Media duration must be positive')
    sha=c.file_sha(media);now=datetime.now(timezone.utc);modules=c.required_modules()
    bindings={'media':{'path':str(media),'sha256':sha}}
    if with_resource_policy:
        policy=root/'resource-policy.json'
        policy.write_text(json.dumps({'schemaVersion':'sermon-unified-resource-policy-v1',
            'brokerRoot':str(root/'broker'),'capacities':{'cpu':1,'online_api':0,
            'codex_cli':0,'spark_tts':0,'publisher':0}}))
        bindings['resourcePolicy']={'path':str(policy),'sha256':c.file_sha(policy)}
    steps=[{'id':'media','stageId':'media_verify','adapter':'media.verify','dependsOn':[],'scope':'media_verified'}]
    for n in range(1,100):
        p=root/f'fixed-{n}.json';p.write_text(json.dumps({'fixtureOnly':True,'fixtureSetId':'unified-cli-v2',
            'mediaSha256':sha,'stageId':'media_verify'}))
        bindings[f'f{n}']={'path':str(p),'sha256':c.file_sha(p)}
        steps.append({'id':f'f{n}','stageId':'media_verify','adapter':'fixture.replay','configuration':f'f{n}',
                      'dependsOn':[steps[-1]['id']],'scope':'media_verified'})
    manifest={'schemaVersion':'sermon-unified-run-manifest-v2','productionRunId':'cli-fixture','runRevision':1,
        'jobRoot':str(root/'jobroot'),'content':{'contentId':'fixture','pageId':'fixture','category':'podcast','sourceDate':None},
        'source':{'sourceId':'fixture','mediaSha256':sha,'durationSeconds':duration,'window':{'startSeconds':0,'endSeconds':duration,
            'timeBase':'source_media','approvalReceiptSha256':None}},'locales':['zh-Hans'],
        'canaryScope':'media_verified','activeScope':'media_verified','finalScope':'dual_production_verified',
        'policies':[{'locale':'zh-Hans','policySha256':'a'*64,'promptSha256':'b'*64,'pluginSha256':'c'*64}],
        'budget':{'currency':'USD','limitMicroUsd':0},'transport':'fixture','fixtureSetId':'unified-cli-v2',
        'executionAdmission':{'modules':modules,'closureSha256':c.closure(modules)},'bindings':bindings,
        'executionWindow':{'timezone':'America/Los_Angeles','startsAt':(now-timedelta(minutes=1)).isoformat(),
            'deadlineAt':(now+timedelta(minutes=10)).isoformat()},'steps':steps}
    path=root/'manifest.json';path.write_text(json.dumps(manifest));store=root/'store'
    env={k:v for k,v in os.environ.items() if not k.startswith(('OPENAI_', 'GEMINI_', 'GOOGLE_API_')) and k!='CODEX_API_KEY'}
    def cli(*args,accepted=(0,)):
        result=subprocess.run([sys.executable,str(c.ROOT/'scripts/sermon.py'),*args,'--state-root',str(store),'--json'],
                              capture_output=True,text=True,timeout=240,env=env)
        if result.returncode not in accepted:
            raise RuntimeError(f'CLI {args[:2]} failed: {result.returncode} {result.stdout} {result.stderr}')
        return json.loads(result.stdout)
    plan=cli('run','plan','--manifest',str(path));start=time.monotonic()
    submitted=cli('run','submit','--manifest',str(path),'--plan-hash',plan['plan']['planHash'])
    key=submitted['subject']['id']
    result=cli('job','wait','--run-id',key,'--timeout','180',accepted=(0,3,4))
    event=cli('run','events','--run-id',key);progress=event['progress']
    assert progress['completedSteps']==100, {'completedSteps':progress['completedSteps'],
        'outcome':progress['outcome'],'blockedSteps':[{k:row.get(k) for k in ('id','process','reason')}
            for row in progress['steps'] if row.get('reason') not in (None,'stage_complete')]}
    assert progress['handoff']['count']==99 and progress['handoff']['p95Seconds']<=2, progress['handoff']
    assert result['execution']['productionEligible'] is False
    assert result['cost']['reservedMicroUsd']==0
    report={'schemaVersion':'sermon-unified-cli-acceptance-v1','status':'passed','runKey':key,
            'sourceMediaSha256':sha,'sourceDurationSeconds':duration,
            'transitions':100,'wallSeconds':time.monotonic()-start,'handoff':progress['handoff'],
            'newPaidRequests':0,'runtimeCodexTurns':0,'productionEligible':False,
            'scope':'offline_real_cli_and_detached_owner','planHash':plan['plan']['planHash']}
    if with_resource_policy:
        from scripts.sermon_unified import resources
        # Run success is persisted before the owner's terminal resource cleanup.
        # Verify cleanup separately instead of racing job.wait's success receipt.
        deadline=time.monotonic()+15
        while True:
            ledger=c.read(root/'broker'/resources.BROKER_LOCK_ID/'resources.json')
            if all(row['status']=='released' for row in ledger['reservations'].values()):
                break
            if time.monotonic()>=deadline:
                raise AssertionError('resource cleanup did not complete')
            time.sleep(.05)
        assert len(ledger['reservations'])==100
        assert all(row['status']=='released' for row in ledger['reservations'].values())
        report['resourceReservations']=100
        report['heldAtCompletion']=0
    (root/'acceptance.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--with-resource-policy',action='store_true')
    parser.add_argument('--media',type=Path,help='Use existing frozen source media instead of synthetic silence')
    args=parser.parse_args()
    print(json.dumps(verify(args.out,with_resource_policy=args.with_resource_policy,media_path=args.media),indent=2))
