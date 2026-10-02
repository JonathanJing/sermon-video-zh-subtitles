"""Dev-only candidate snapshot and explicit publish/HTTP DAG nodes.

No formal catalog, Package, approval or release status is created. Build is
local/reversible; deploy requires frozen Dev target authorization and its own
append-only intent. An unknown deploy is never automatically repeated.
"""
from pathlib import Path
import html
import json
import re
import shutil
import subprocess
import tempfile
import time
import hashlib
from urllib.parse import quote
from urllib.request import Request,urlopen

from scripts import sermon_accounting as accounting
from scripts import sermon_historical_identity as historical_identity
from scripts import sermon_review_contracts as c
from scripts import sermon_strict_layer2 as immutable
from scripts import sermon_diagnostic_context as diagnostic
from scripts import sermon_diagnostic_preview_worker as worker
from scripts import run_bounded_diagnostic as bounded
from scripts.sermon_release_workflow import _safe_path

PROJECT='ai-for-god-sermon-audio-dev'
ORIGIN='https://ai-for-god-sermon-audio-dev.web.app'
REPO=Path(__file__).resolve().parents[1]
SCHEMA='sermon-dev-diagnostic-snapshot-v1'
UI=('app.mjs','catalog.mjs','locales-app.mjs','index.html','style.css','theme.js',
    'fingerprint-ui.mjs','locales-interface.mjs','locales-ko.mjs','locales-es.mjs',
    'icons.mjs','icons.svg','brand-icon.svg','brand-icon-light.svg','fingerprint-diagnostics.mjs',
    'voice-samples.mjs','speaker-clip-demos.mjs','voice-demo.css')
SAFE_REASONS=frozenset({'machine_candidate_missing','preview_audio_unavailable','strict_locale_group_not_passed',
    'strict_bridge_plugin_rejected','invalid_candidate_coverage','invalid_generated_candidate','invalid_review_response',
    'provider_input_bound_exceeded','provider_request_limit','provider_cost_limit','provider_run_deadline_reached',
    'provider_outcome_reconciliation_required','provider_configuration_stopped','native_runtime_unavailable',
    'preview_worker_failed_requires_reconciliation',
    'diagnostic_state_binding_invalid','invalid_snapshot_file',
    'diagnostic_flow_plan_changed','diagnostic_flow_frozen_inputs_changed','diagnostic_unbounded_subprocess_forbidden','unclassified_failure'}) | historical_identity.PRE_PROVIDER_CODES


def stage_presentation(observation, *, candidate, preview):
    """Typed observations only; no raw error body or inferred root cause."""
    if preview:return 'ready',None
    if observation is None:return 'pending','preview_audio_unavailable' if candidate else 'machine_candidate_missing'
    raw=observation.get('reason') or observation.get('reasonCode')
    reason=raw if type(raw) is str and raw in SAFE_REASONS else 'unclassified_failure'
    if observation.get('readyForDownstream') is True:
        return 'blocked','unclassified_failure'  # Required receipt absent.
    if raw=='upstream_not_completed':return 'blocked','strict_locale_group_not_passed'
    if observation.get('executionStatus')=='outcome_unknown':
        # The worker has a known failed exit, even if the DAG conservatively
        # requires reconciliation. Unknown provider outcomes remain blocked.
        if raw=='preview_worker_failed_requires_reconciliation':return 'failed',reason
        return 'blocked',reason
    if observation.get('executionStatus') in ('failed','completed') or observation.get('processed') is True:
        return 'failed',reason if raw else 'strict_locale_group_not_passed'
    return 'blocked',reason


def _sha(path):return c.bytes_sha256(_safe_path(Path(path)).read_bytes())
def _read(path):return c.read_snapshot(_safe_path(Path(path)))[0]
def _files(root):
    _safe_path(root,recursive=True)
    return {str(path.relative_to(root)):_sha(path) for path in sorted(root.rglob('*')) if path.is_file()}
def _write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
def _probe(path):
    output=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','json',str(path)],
                          check=True,capture_output=True,text=True,timeout=30)
    return float(json.loads(output.stdout)['format']['duration'])
def _decode(path):
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-i',str(path),'-f','null','-'],
                   check=True,capture_output=True,timeout=120)


def _track(candidate,preview,target,page):
    manifest=_read(preview/'manifest.json');digest=c.canonical_sha256(candidate)
    c.require(manifest['status']=='preview_only' and manifest['candidateJsonSha256']==digest
        and _read(preview/'candidate.json')==candidate,'dev_preview_candidate_changed')
    inputs=[];cues=[];offset=0.
    for i,group in enumerate(candidate['groups']):
        wav=preview/f'units/unit-{i:04d}.wav';receipt=_read(preview/f'receipts/unit-{i:04d}.json')
        c.require(receipt['status']=='preview_only' and receipt['fullDecode']=='pass' and
            receipt['candidateJsonSha256']==digest and receipt['audioSha256']==_sha(wav),'dev_preview_unit_changed')
        seconds=_probe(wav);_decode(wav)
        c.require(abs(seconds-receipt['durationSeconds'])<=.02,'dev_preview_duration_changed')
        cues.append({'start':round(offset,6),'end':round(offset+seconds,6),'text':group['targetText'],
                     'textGroupId':group['translationGroupId'],'blockId':group['translationGroupId']})
        offset+=seconds;inputs.append(wav)
    c.require(inputs and all("'" not in str(p) and '\n' not in str(p) for p in inputs),'dev_preview_audio_path_invalid')
    target.parent.mkdir(parents=True,exist_ok=True);concat=target.with_suffix('.concat.txt')
    concat.write_text(''.join("file '"+str(p)+"'\n" for p in inputs))
    try:
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','concat','-safe','0','-i',str(concat),
            '-vn','-ac','1','-ar','24000','-c:a','libmp3lame','-b:a','64k',str(target)],check=True,capture_output=True,timeout=120)
    finally:concat.unlink(missing_ok=True)
    _decode(target);seconds=_probe(target)
    c.require(cues[-1]['end']<=seconds+.001,'dev_preview_track_short')
    sha=_sha(target);addressed=target.with_name(target.stem+'-'+sha[:16]+'.mp3');target.rename(addressed)
    return {'id':page+'-'+candidate['targetLocale'],'audioUrl':'/media/'+page+'/'+addressed.name,'sha256':sha,
            'durationSeconds':seconds,'cues':cues,'scope':'machine_poc_not_production','subtitleTiming':'preview_unsynchronized',
            'label':candidate['targetLocale']+' · DEV 真实生成试听','targetLocale':candidate['targetLocale']}


def build_snapshot(session, *, baseline, out, page_id, preview_receipts, stage_results, depends_on=None):
    """Fixed actual candidate+preview binding; missing lanes get typed UI state."""
    c.require(re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,79}',page_id) is not None,'dev_diagnostic_page_invalid')
    session._check();root=session.root;baseline=_safe_path(Path(baseline),recursive=True);out=_safe_path(Path(out),recursive=True)
    c.require(out.is_absolute() and not out.exists() and not out.is_relative_to(baseline) and not baseline.is_relative_to(out)
        and out.is_relative_to(root),'dev_snapshot_output_scope_changed')
    c.require(_read(baseline/'firebase.json').get('hosting',{}).get('site')==PROJECT,'dev_snapshot_target_invalid')
    before=_files(baseline);source=_read(root/'source.json');anchor=_read(root/'anchor-manifest.json')
    diagnostic.validate_source(source,anchor,session.context)
    c.require(type(stage_results) is dict and set(stage_results)=={'schemaVersion','runId','diagnosticContextSha256','nodes'}
        and stage_results['schemaVersion']=='sermon-dev-diagnostic-stage-results-v1'
        and stage_results['runId']==session.subject.config['runId']
        and stage_results['diagnosticContextSha256']==c.canonical_sha256(session.context)
        and type(stage_results['nodes']) is dict,'dev_stage_results_binding_changed')
    nodes=stage_results['nodes']
    c.require(all(type(row) is dict and row.get('nodeId')==key and row.get('executionStatus') in
        ('completed','blocked','failed','outcome_unknown') and type(row.get('readyForDownstream')) is bool
        for key,row in nodes.items()),'dev_stage_results_invalid')
    input_hash=c.canonical_sha256({'context':session.context,'locales':session._locale_results,'stageResults':stage_results})
    out.parent.mkdir(parents=True,exist_ok=True);temp=Path(tempfile.mkdtemp(prefix='.dev-diagnostic-',dir=out.parent))
    with accounting.stage('diagnostic.dev_snapshot',depends_on=depends_on,executor_type='deterministic_program') as span:
        try:
            hosting=temp/'hosting';shutil.copytree(baseline,hosting);public=hosting/'public'
            for name in UI:shutil.copyfile(REPO/'experiments/sermon-dubbing-poc/web'/name,public/name)
            clip=_safe_path(Path(session.plan['sourceClipPath']));video=public/'media'/page_id/'source.mp4'
            video.parent.mkdir(parents=True);shutil.copyfile(clip,video);_decode(video);duration=_probe(video)
            variants={};bindings={};source_by={u['sourceUnitId']:u['english'] for u in anchor['sourceUnits']}
            for locale in ('zh-Hans','ko','es'):
                result=session._locale_results.get(locale);candidate=None;track=None
                if result is not None and result.get('status')=='waiting_human' and result.get('output'):
                    candidate=_read(Path(result['output'])/'candidate.json')
                    c.require(c.canonical_sha256(candidate)==result['candidateSha256'] and candidate['targetLocale']==locale
                        and candidate['releaseEligible'] is False and candidate['humanReview']['translation']=='pending'
                        and candidate['modelReview']['status']=='pass' and all(g['semanticReview']['status']=='pass'
                        and g['languageReview']['status']=='pass' for g in candidate['groups']),'dev_machine_candidate_changed')
                receipt=preview_receipts.get(locale)
                if receipt is not None:
                    c.require(candidate is not None,'dev_preview_without_candidate')
                    worker.validate_preview_receipt(root,session.subject,session.context,receipt)
                    c.require(receipt['offlineFixture'] is session.offline_fixture,'dev_preview_mode_changed')
                    track=_track(candidate,_safe_path(Path(receipt['spec']['out'])),public/'media'/page_id/(locale+'.mp3'),page_id)
                observation=nodes.get(('preview.' if candidate else 'text.')+locale)
                status,reason=stage_presentation(observation,candidate=candidate is not None,preview=track is not None)
                groups=candidate['groups'] if candidate else []
                text_rows=[];blocks=[]
                for i,g in enumerate(groups):
                    text_rows.append({'start':track['cues'][i]['start'] if track else 0.,'text':g['targetText'],
                        'textGroupId':g['translationGroupId'],'english':' '.join(source_by[x] for x in g['sourceUnitIds'])})
                    blocks.append({'blockId':g['translationGroupId'],'english':text_rows[-1]['english'],
                                   'sourceTextOrigin':'machine_asr_not_human_verified','reviewState':'diagnostic_preview_only'})
                notice='DEV 机器候选与试听；真实人审 pending；音轨与原视频同步未验证。'
                state={'schemaVersion':'sermon-dev-diagnostic-presentation-v1','targetLocale':locale,'status':status,
                    'machineCandidateAvailable':candidate is not None,'candidateSha256':None if candidate is None else c.canonical_sha256(candidate),
                    'inputBindingSha256':input_hash,'reasonCode':reason}
                variants[locale]={'id':page_id,'date':source['source']['serviceDate'],'number':'DEV','title':'[DEV 诊断] 真实片段',
                    'series':'DAG / Log / Agent API 测试','speaker':'来源讲员','scripture':'诊断未建立正式经文元数据',
                    'targetLocale':locale,'defaultTargetLocale':'zh-Hans','diagnosticOnly':True,'simulationOnly':True,
                    'diagnosticState':state,'diagnosticInputSha256':input_hash,'humanContentReview':'pending','contentReview':'preview_only',
                    'centralMessage':notice,'summary':notice,'outline':[],'questions':[],'scriptureRefs':[],
                    'sourceRoute':'full_video','sourceUrl':'/media/'+page_id+'/source.mp4','sourceLabel':'原片段 / 机器 ASR',
                    'sourceSha256':_sha(clip),'sourceDurationSeconds':duration,'audioStatus':'candidate' if track else 'unavailable',
                    'audioNotice':notice,'tracks':[track] if track else [],'fullTranscript':text_rows,
                    'transcript':{'schemaVersion':'sermon-bilingual-transcript-v1','blocks':blocks},'productionReadiness':[]}
                bindings[locale]={'state':state,'previewReceiptSha256':None if receipt is None else c.canonical_sha256(receipt)}
            week={**variants['zh-Hans'],'contentVariants':variants}
            payload={'schemaVersion':'sermon-dev-real-diagnostic-app-v1','productionEligible':False,'week':week}
            relative='diagnostic/'+page_id+'/latest.json';_write(public/relative,payload)
            parent_name='published-weeks-parent-'+input_hash[:16]+'.mjs'
            shutil.copyfile(baseline/'public/published-weeks.mjs',public/parent_name)
            (public/'published-weeks.mjs').write_text("import {loadPublishedWeeks as existing} from './"+parent_name+"';\n"
                "export async function loadPublishedWeeks(fetchImpl=globalThis.fetch,options={}) {const prior=await existing(fetchImpl,options);"
                "const r=await fetchImpl("+json.dumps('/'+relative)+",{cache:'no-store'});if(!r.ok)return prior;const d=await r.json();"
                "if(d.schemaVersion!=='sermon-dev-real-diagnostic-app-v1'||d.productionEligible!==false||!d.week?.diagnosticOnly)return prior;"
                "return {...prior,weeks:[d.week,...prior.weeks.filter(w=>w.id!==d.week.id)]};}\n")
            manifest={'schemaVersion':SCHEMA,'runId':session.subject.config['runId'],'inputBindingSha256':input_hash,
                'contextSha256':c.canonical_sha256(session.context),'target':{'project':PROJECT,'site':PROJECT,'origin':ORIGIN},
                'stageResultsSha256':c.canonical_sha256(stage_results),
                'pageId':page_id,'appUrl':ORIGIN+'/?week='+page_id,'evidenceMode':session.evidence_mode,'locales':bindings,
                'baselineSha256':c.canonical_sha256(before),'baselineFilesRemoved':[], 'publicFiles':_files(public),
                'humanAcceptance':'pending','productionEligible':False,'formalAudioPackageCreated':False,'formalReleasePackageCreated':False,
                'formalCatalogUpdated':False,'sourceVideoSynchronization':'not_validated','deviceAcceptance':'not_run','venueAcceptance':'not_run'}
            c.require(_files(baseline)==before and _sha(public/'multilingual-v3.json')==_sha(baseline/'public/multilingual-v3.json'),
                      'dev_snapshot_formal_catalog_changed')
            immutable.save_once(temp/'snapshot-manifest.json',manifest);temp.rename(out)
            accounting.record_workload('diagnostic.dev_snapshot_binding',{'manifestSha256':c.canonical_sha256(manifest),
                'inputBindingSha256':input_hash,'productionEligible':False})
        except BaseException:
            shutil.rmtree(temp);raise
    return {'manifest':manifest,'out':str(out),'completionSpans':[span],'publicationAuthorized':False}


def publish_and_verify(snapshot, *, plan, authorization, execute=False, depends_on=None, timeout_seconds=300):
    """Explicit fixed Firebase Dev operation. Failed/unknown intent needs review."""
    out=_safe_path(Path(snapshot['out']),recursive=True);manifest=_read(out/'snapshot-manifest.json')
    root,subject=bounded.prepare_plan(plan)
    c.require(not (root/'offline-business-scope.json').exists(),'dev_publish_fixture_scope_forbidden')
    c.require(out.is_relative_to(root) and manifest['runId']==subject.config['runId'],'dev_publish_run_changed')
    context=_read(root/'diagnostic-context.json')
    diagnostic.validate_source(_read(root/'source.json'),_read(root/'anchor-manifest.json'),context)
    c.require(c.canonical_sha256(context)==manifest['contextSha256'] and context['runId']==subject.config['runId']
        and context['runConfigSha256']==c.canonical_sha256(subject.config) and context['storeSha256']==subject.store.store_sha256,
        'dev_publish_context_changed')
    with subject._locked() as (_,state):
        subject._remaining(state)
        c.require(all(row['state'] in ('returned','rejected') for row in state['requests'].values()),
                  'dev_publish_provider_outcome_unknown')
        deadline=state['startedMonotonic']+subject.config['totalWallSeconds']
    def remaining(cap):
        seconds=min(cap,deadline-subject.monotonic())
        c.require(seconds>0,'dev_publish_original_deadline_reached')
        return seconds
    c.require(snapshot['manifest']==manifest and manifest['schemaVersion']==SCHEMA and
        manifest['target']=={'project':PROJECT,'site':PROJECT,'origin':ORIGIN} and manifest['evidenceMode']=='current_execution'
        and manifest['productionEligible'] is False and _files(out/'hosting/public')==manifest['publicFiles'],
        'dev_publish_snapshot_changed')
    expected={'schemaVersion':'sermon-dev-diagnostic-publication-authorization-v1','manifestSha256':c.canonical_sha256(manifest),
        'project':PROJECT,'site':PROJECT,'origin':ORIGIN,'publicationScope':'diagnostic_preview_only','productionEligible':False}
    c.require(execute is True and type(authorization) is dict and set(authorization)==set(expected)|{'approvalSha256'} and
        all(authorization[k]==v for k,v in expected.items()),'dev_publish_explicit_authorization_required')
    budget_hash=authorization['approvalSha256'];c.require(type(budget_hash) is str and re.fullmatch('[a-f0-9]{64}',budget_hash),
                                                        'dev_publish_explicit_authorization_required')
    c.require(type(timeout_seconds) is int and 1<=timeout_seconds<=300,'dev_publish_timeout_invalid')
    c.require(_read(out/'hosting/firebase.json').get('hosting',{}).get('site')==PROJECT,'dev_publish_target_changed')
    intent=out/'publish-intent.json';returned=out/'publish-returned.json'
    expected_intent={'schemaVersion':'sermon-dev-diagnostic-publication-intent-v1',
        'authorizationSha256':c.canonical_sha256(authorization),
        'manifestSha256':c.canonical_sha256(manifest),'status':'outcome_unknown'}
    if intent.exists():
        c.require(returned.exists(),'dev_publication_requires_reconciliation')
        replay=True
    else:
        c.require(not returned.exists(),'dev_publication_replay_changed')
        immutable.save_once(intent,expected_intent)
        replay=False
    if replay:
        with accounting.stage('diagnostic.dev_publish_replay',depends_on=depends_on,cache_hit=True,
                              executor_type='deterministic_program') as published_span:
            intent_value,intent_raw=c.read_snapshot(intent)
            returned_value,returned_raw=c.read_snapshot(returned)
            c.require(intent_value==expected_intent and type(returned_value) is dict and
                set(returned_value)=={'status','manifestSha256','stdoutSha256','stderrSha256','exitCode'} and
                returned_value['status']=='deploy_command_returned_success' and
                returned_value['manifestSha256']==c.canonical_sha256(manifest) and
                type(returned_value['exitCode']) is int and returned_value['exitCode']==0 and
                all(type(returned_value[key]) is str and re.fullmatch('[a-f0-9]{64}',returned_value[key])
                    for key in ('stdoutSha256','stderrSha256')),'dev_publication_replay_changed')
            remaining(30)
            accounting.record_workload('diagnostic.dev_publish_replay_binding',{
                'manifestSha256':c.canonical_sha256(manifest),'intentSha256':c.bytes_sha256(intent_raw),
                'returnedSha256':c.bytes_sha256(returned_raw)})
    else:
        with accounting.stage('diagnostic.dev_publish',depends_on=depends_on,
                              executor_type='external_service') as published_span:
            try:
                c.require(not returned.exists(),'dev_publication_replay_changed')
                result=subprocess.run(['firebase','deploy','--project',PROJECT,'--only','hosting','--non-interactive'],cwd=out/'hosting',
                    env=accounting.subprocess_environment(),capture_output=True,timeout=remaining(timeout_seconds))
                c.require(result.returncode==0,'dev_publication_outcome_requires_reconciliation')
                immutable.save_once(returned,{'status':'deploy_command_returned_success',
                    'manifestSha256':c.canonical_sha256(manifest),'stdoutSha256':c.bytes_sha256(result.stdout),
                    'stderrSha256':c.bytes_sha256(result.stderr),'exitCode':0})
            except BaseException:
                immutable.save_once(out/'publish-unconfirmed.json',{'status':'outcome_unknown','manifestSha256':c.canonical_sha256(manifest)})
                raise
    with accounting.stage('diagnostic.dev_http',depends_on=[published_span],executor_type='external_service') as http_span:
        verified_assets=0;verified_bytes=0;manifest_sha=c.canonical_sha256(manifest)
        def progress(complete):
            accounting.record_workload('diagnostic.dev_http_progress',{'manifestSha256':manifest_sha,
                'verifiedAssets':verified_assets,'totalAssets':len(manifest['publicFiles']),
                'verifiedBytes':verified_bytes,'verificationComplete':int(complete)})
        for asset_index,(relative,sha) in enumerate(manifest['publicFiles'].items(),1):
            last_download_progress=-1;next_download_progress=16*1024*1024
            def download_progress():
                # Streamed byte observations are explicitly unverified until SHA passes.
                accounting.record_workload('diagnostic.dev_http_download_progress',{'manifestSha256':manifest_sha,
                    'assetIndex':asset_index,'currentDownloadedBytes':total,'verificationComplete':0})
            local=out/'hosting/public'/relative;size=local.stat().st_size;total=0;digest=hashlib.sha256()
            with urlopen(Request(ORIGIN+'/'+quote(relative,safe='/'),headers={'Cache-Control':'no-cache'}),timeout=remaining(30)) as response:
                c.require(response.status==200,'dev_http_asset_changed')
                while True:
                    block=response.read(min(1024*1024,size+1-total));remaining(30)
                    if not block:
                        if last_download_progress!=total:download_progress()
                        break
                    total+=len(block);c.require(total<=size,'dev_http_asset_changed');digest.update(block)
                    if total>=next_download_progress:
                        download_progress();last_download_progress=total
                        next_download_progress=(total//(16*1024*1024)+1)*(16*1024*1024)
                c.require(total==size and digest.hexdigest()==sha,'dev_http_asset_changed')
            verified_assets+=1;verified_bytes+=total
            if verified_assets%10==0:progress(False)
        relative='media/'+manifest['pageId']+'/source.mp4';local=out/'hosting/public'/relative
        with urlopen(Request(ORIGIN+'/'+quote(relative,safe='/'),headers={'Range':'bytes=0-1023','Cache-Control':'no-cache'}),timeout=remaining(30)) as response:
            c.require(response.status==206 and response.headers.get('Content-Range')==f'bytes 0-1023/{local.stat().st_size}'
                and response.read(1025)==local.read_bytes()[:1024],'dev_http_range_changed')
        remaining(30)
        receipt={'schemaVersion':'sermon-dev-diagnostic-publication-receipt-v1','status':'published_http_verified',
            'manifestSha256':c.canonical_sha256(manifest),'publicFilesVerified':len(manifest['publicFiles']),
            'rangeVerified':True,'productionEligible':False,'humanAcceptance':'pending','deviceAcceptance':'not_run','venueAcceptance':'not_run'}
        immutable.save_once(out/'http-receipt.json',receipt)
        accounting.record_workload('diagnostic.dev_http_binding',{'manifestSha256':c.canonical_sha256(manifest),
            'receiptSha256':c.canonical_sha256(receipt),'productionEligible':False})
        progress(True)  # Final only after every asset, Range and persisted receipt pass.
    return {**receipt,'completionSpans':[http_span]}
