"""Isolated native Temporal -> project Python -> same durable pump acceptance."""
from __future__ import annotations
import argparse
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import subprocess
import sys
import wave


def project_state(directory, operation):
    from scripts.sermon_unified import contracts as c,runtime as r
    from scripts.sermon_temporal.unified import transfer
    directory=Path(directory).resolve();store=directory/'store'
    reference=directory/'request.json'
    if operation=='prepare':
        directory.mkdir(parents=True,exist_ok=False)
        media=directory/'source.wav'
        with wave.open(str(media),'wb') as f:
            f.setparams((1,2,16000,0,'NONE','not compressed'));f.writeframes(b'\0\0'*1600)
        now=datetime.now(timezone.utc);modules=c.required_modules();sha=c.file_sha(media)
        manifest={'schemaVersion':'sermon-unified-run-manifest-v2','productionRunId':'temporal-unified-integration',
            'runRevision':1,'jobRoot':str(directory/'jobs'),'content':{'contentId':'test','pageId':'test','category':'podcast','sourceDate':None},
            'source':{'sourceId':'test','mediaSha256':sha,'durationSeconds':.1,
                'window':{'startSeconds':0,'endSeconds':.1,'timeBase':'source_media','approvalReceiptSha256':None}},
            'locales':[],'policies':[],'canaryScope':'media_verified','activeScope':'media_verified','finalScope':'dual_production_verified',
            'transport':'provider','budget':{'currency':'USD','limitMicroUsd':0},
            'executionAdmission':{'modules':modules,'closureSha256':c.closure(modules)},
            'bindings':{'media':{'path':str(media),'sha256':sha}},
            'executionWindow':{'timezone':'America/Los_Angeles','startsAt':(now-timedelta(minutes=1)).isoformat(),
                'deadlineAt':(now+timedelta(minutes=20)).isoformat()},
            'steps':[{'id':'media','stageId':'media_verify','adapter':'media.verify','dependsOn':[],'scope':'media_verified'}]}
        state=r.submit(manifest,directory,store,c.plan_hash(manifest));key=state['runKey']
        state=r.mutate(store,key,'drain',state['stateRevision'])
        state=transfer(store,key,state['stateRevision'],scheduler='temporal')
        state=r.mutate(store,key,'drain',state['stateRevision'])
        value={'state_root':str(store),'run_key':key,'plan_hash':state['planHash']}
        reference.write_text(json.dumps(value));return value
    request=json.loads(reference.read_text());key=request['run_key'];state=r.load(store,key)
    if operation=='resume':
        state=r.mutate(store,key,'resume',state['stateRevision'])
    elif operation=='fallback':
        before=len(state['events']);state=r.mutate(store,key,'drain',state['stateRevision'])
        state=transfer(store,key,state['stateRevision'],scheduler='canonical')
        state=r.pump(store,key)
        assert len(state['events'])==before, 'fallback repeated dispatch'
    return {'outcome':r._project(state)[0],'events':len(state['events']),
            'scheduler':state['scheduler'],'stateRevision':state['stateRevision']}


async def check(directory):
    import asyncio
    import socket
    import uuid
    from temporalio.client import Client
    from temporalio.worker import Worker
    from scripts.sermon_temporal import server
    from scripts.sermon_temporal.local_io import PROJECT_PYTHON,ROOT
    from scripts.sermon_temporal.unified import UnifiedRequest
    from scripts.sermon_temporal.unified_sdk import UnifiedWorkflow,execute_activity
    directory=Path(directory).resolve()
    def project(operation):
        result=subprocess.run([str(PROJECT_PYTHON),'-m',__spec__.name,'--out',str(directory),
                               '--project-operation',operation],cwd=ROOT,capture_output=True,text=True,check=True,timeout=60)
        return json.loads(result.stdout)
    request=UnifiedRequest(**project('prepare'))
    sockets=[]
    try:
        for _ in range(2):
            sock=socket.socket();sock.bind(('127.0.0.1',0));sockets.append(sock)
        ports=[sock.getsockname()[1] for sock in sockets]
    finally:
        for sock in sockets:sock.close()
    server_root=directory/'server'
    started=False
    try:
        health=server.start(server_root,port=ports[0],ui_port=ports[1]);started=True
        client=await Client.connect(f'127.0.0.1:{ports[0]}')
        queue='unified-integration-'+uuid.uuid4().hex
        async with Worker(client,task_queue=queue,workflows=[UnifiedWorkflow],activities=[execute_activity],
                          graceful_shutdown_timeout=timedelta(seconds=5)):
            handle=await client.start_workflow(UnifiedWorkflow.run,request,id=queue,task_queue=queue)
            async def wait_paused():
                for _ in range(100):
                    value=await handle.query(UnifiedWorkflow.status)
                    if 'stateRevision' in value:
                        assert value['outcome']=='pending',value
                        return value
                    await asyncio.sleep(.1)
                raise AssertionError('workflow did not reach durable pause')
            paused=await asyncio.wait_for(wait_paused(),30)
            project('resume');await handle.signal(UnifiedWorkflow.evidence_changed)
            result=await asyncio.wait_for(handle.result(),30)
            assert result['outcome']=='succeeded',result
            fallback=project('fallback')
            assert fallback['outcome']=='succeeded' and fallback['scheduler']=='canonical',fallback
        report={'schemaVersion':'sermon-unified-temporal-acceptance-v1','status':'passed',
                'nativeServerVersion':health['version'],'durablePauseObserved':True,
                'signalResume':'passed','sameLedgerCanonicalFallback':'passed',
                'dispatchEvents':fallback['events'],'newPaidRequests':0,'productionAcceptance':False,
                'runKey':request.run_key,'planHash':request.plan_hash}
        (directory/'acceptance.json').write_text(json.dumps(report,indent=2)+'\n')
        return report
    finally:
        if started:server.stop(server_root)


def main():
    import asyncio
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--project-operation',choices=['prepare','resume','fallback','inspect'])
    args=parser.parse_args()
    result=project_state(args.out,args.project_operation) if args.project_operation else asyncio.run(check(args.out))
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
