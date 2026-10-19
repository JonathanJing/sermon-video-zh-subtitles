"""Offline real-asset diagnostics under the production v3 accounting collector.

Explicit local inputs only. No model transport, publication or human approval.
Input manifests contain local paths and stay outside Git; reports contain hashes.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import sermon_accounting as accounting

ASR_CHECKPOINT_SHA256 = "862bbc832b05f3f4ec19dd632b701d61a6d3f5c7906360a10d72a79870642a80"


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''): digest.update(block)
    return digest.hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')


def files(root):
    return {str(p.relative_to(root)): sha(p) for p in root.rglob('*') if p.is_file()}


def cache_replay(inputs, source_media, out, forbidden):
    from scripts import run_target_language_models as models
    from scripts import produce_target_language_candidate as producer
    from scripts import target_language_policy as policies
    from scripts.sermon_workflow_evidence import collect_workflow_evidence
    report = {'scope': 'new_deterministic_replay_of_historical_paid_results_not_new_inference', 'locales': []}
    with accounting.accounting_session(out/'accounting', 'real_clip_trilingual_cached_replay', {'mode':'dry_run'}):
        with accounting.stage('diagnostic.real_source_decode', depends_on=[], executor_type='deterministic_program') as decode:
            report['sourceMediaSha256'] = sha(source_media)
            accounting.record_workload('diagnostic.source_media', {'sourceMediaSha256': report['sourceMediaSha256']})
            subprocess.run(['ffmpeg','-nostdin','-v','error','-xerror','-i',str(source_media),'-f','null','-'],check=True,timeout=90)
        for row in inputs:
            began=time.monotonic();locale=row['locale'];lane=out/locale;prior=Path(row['priorRun']);before=files(prior)
            source,anchor,policy=[producer._load(Path(row[k])) for k in ('source','anchor','policy')]
            old=producer._load(prior/'evidence.json')
            plan=[{k:g[k] for k in ('translationGroupId','sourceUnitIds')} for g in old['groups']]
            completion=[]
            evidence=models.run_accounted(source,anchor,policy,lane,'',forbidden,plan,Path(row['plugin']),None,prior,
                cache_only=True,predecessor_spans=[decode],completion_spans=completion)
            if evidence!=old: raise ValueError('historical_evidence_changed')
            with accounting.stage('diagnostic.candidate.'+locale, depends_on=completion, executor_type='deterministic_program'):
                request=producer._load(lane/'request.json');plugin_sha=policy['languageReview']['pluginImplementationSha256']
                receipt=producer.run_language_plugin(source,anchor,policy,request,evidence,Path(row['plugin']),plugin_sha)
                candidate=producer.admit_evidence(source,anchor,policy,request,evidence,receipt,Path(row['plugin']),plugin_sha)
                models.save_new(lane/'language-review.json',receipt);models.save_new(lane/'candidate.json',candidate)
                accounting.record_workload('diagnostic.candidate_identity', {'candidateSha256':policies.canonical_sha256(candidate),'languageReviewSha256':policies.canonical_sha256(receipt)})
                accounting._emit({'event':'workflow_evidence','phase':'after','workflow':'canonical_layer2','evidence':collect_workflow_evidence(lane,'canonical_layer2')})
            report['locales'].append({'locale':locale,'status':'cache_replayed_candidate_validated','groups':len(evidence['groups']),
                'historicalModels':{k:v['model'] for k,v in evidence['generation'].items()},'newModelCalls':0,
                'candidateJsonSha256':policies.canonical_sha256(candidate),'candidateStatus':candidate['status'],
                'releaseEligible':candidate['releaseEligible'],'evidenceEqualsPrior':evidence==old,
                'cacheFilesByteIdentical':all((lane/p.name).read_bytes()==p.read_bytes() for p in prior.glob('group-*.json')),
                'priorFilesUnchanged':files(prior)==before,'elapsedSeconds':time.monotonic()-began})
    report['sourceUnchanged']=sha(source_media)==report['sourceMediaSha256']
    return report


def local_asr(source, model, window, out):
    from scripts import sermon_local_model_observation as observation
    report={'scope':'new_local_decode_and_experimental_asr_not_formal_stage1','sourceMediaSha256':sha(source),
            'inputBytes':source.stat().st_size,'modelCacheSnapshot':model.name,'requestedModel':'mlx-community/whisper-large-v3-turbo-q4'}
    with accounting.accounting_session(out/'accounting','real_clip_local_asr_diagnostic',{'mode':'dry_run'}):
        with accounting.stage('diagnostic.source_decode',depends_on=[],executor_type='deterministic_program') as decoded:
            subprocess.run(['ffmpeg','-nostdin','-v','error','-xerror','-i',str(source),'-t',str(window),'-vn','-ac','1','-ar','16000','-c:a','pcm_s16le',str(out/'source.wav')],check=True,timeout=60)
            report['decodedWavSha256']=sha(out/'source.wav')
            accounting.record_workload('diagnostic.source_media',{'sourceMediaSha256':report['sourceMediaSha256'],'sourceDurationSeconds':window})
        with accounting.stage('diagnostic.local_asr_setup',depends_on=[decoded],executor_type='deterministic_program') as setup:
            checkpoint=sha(model/'weights.npz')
            if checkpoint != ASR_CHECKPOINT_SHA256:
                raise ValueError('unexpected_diagnostic_model_checkpoint')
            import mlx_whisper
            accounting.record_workload('diagnostic.model_identity',{'checkpointSha256':checkpoint})
        with accounting.stage('diagnostic.local_asr',depends_on=[setup],executor_type='production_model') as model_span:
            observation.record(report['requestedModel'],checkpoint,report['decodedWavSha256'],status='started')
            began=time.monotonic()
            result=mlx_whisper.transcribe(str(out/'source.wav'),path_or_hf_repo=str(model),language='en',temperature=0.0,verbose=None,word_timestamps=True)
            report['asrWallSeconds']=time.monotonic()-began
        with accounting.stage('diagnostic.local_asr_output',depends_on=[model_span],executor_type='deterministic_program'):
            write(out/'fresh-local-asr.json',result)
            report['transcriptSha256']=sha(out/'fresh-local-asr.json');report['segments']=len(result['segments']);report['wordCount']=len(result['text'].split())
            observation.record(report['requestedModel'],checkpoint,report['decodedWavSha256'],status='completed',
                output_sha256=report['transcriptSha256'],elapsed_seconds=report['asrWallSeconds'],span_id=model_span)
    report['sourceUnchanged']=sha(source)==report['sourceMediaSha256']
    return report


def audio_validation(inputs, out):
    from scripts import inspect_canonical_audio as audio
    from scripts import inspect_canonical_packages as packages
    from scripts import build_target_language_audio_package as builder
    from scripts.sermon_workflow_evidence import collect_workflow_evidence
    report={'scope':'new_read_only_validation_of_historical_audio_and_reviews_not_new_tts_or_human_signoff','locales':[]}
    previous=[]
    with accounting.accounting_session(out/'accounting','real_historical_audio_revalidation',{'mode':'dry_run'}):
        for row in inputs:
            began=time.monotonic();locale=row['locale'];artifact_root=Path(row['artifactRoot']);package=builder.read_object(Path(row['package']))
            tracked={Path(p) for p in row['trackedFiles']};tracked.update(p for p in artifact_root.rglob('*') if p.is_file())
            before={str(p):sha(p) for p in tracked}
            with accounting.stage('diagnostic.audio.'+locale,depends_on=previous,executor_type='deterministic_program') as span:
                accounting._emit({'event':'workflow_evidence','workflow':'layer3_formal_render','phase':'before','evidence':collect_workflow_evidence(artifact_root,'layer3_formal_render')})
                checked=audio.inspect(Path(row['root']),row['config'],{k:Path(v) for k,v in row['upstream'].items()},packages._read_package,{},locale)
            previous=[span]  # Actual sequential invocation order, not guessed parallel work.
            report['locales'].append({'locale':locale,'status':'historical_audio_and_bound_review_validated','units':len(package['units']),
                'outputSha256':checked['outputSha256'],'listeningReviewSha256':checked['listeningReviewSha256'],
                'originalFilesUnchanged':all(sha(Path(p))==h for p,h in before.items()),'newTtsCalls':0,
                'expectedAudioSha256s':[u['audio']['sha256'] for u in package['units']], 'elapsedSeconds':time.monotonic()-began})
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['cache','asr','audio'])
    parser.add_argument('--inputs',type=Path)
    parser.add_argument('--source-media',type=Path)
    parser.add_argument('--model-directory',type=Path)
    parser.add_argument('--window-seconds',type=float)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    if args.mode in {'cache','asr'} and (args.source_media is None or not args.source_media.is_file()): parser.error('local source media required')
    if args.mode=='asr' and (args.model_directory is None or not (args.model_directory/'weights.npz').is_file() or args.window_seconds is None or not 0<args.window_seconds<86400): parser.error('local cached model and finite window required')
    if args.mode in {'cache','audio'} and (args.inputs is None or not args.inputs.is_file()): parser.error('local input manifest required')
    attempts=[]
    def forbidden(*_args,**_kwargs):
        attempts.append(True)
        raise RuntimeError('offline_diagnostic_transport_forbidden')
    socket.socket.connect=forbidden;socket.create_connection=forbidden
    args.out.mkdir(parents=True,exist_ok=False)
    identity=accounting.execution_identity();began=time.monotonic()
    if args.mode=='cache': report=cache_replay(json.loads(args.inputs.read_text()),args.source_media,args.out,forbidden)
    elif args.mode=='audio': report=audio_validation(json.loads(args.inputs.read_text()),args.out)
    else: report=local_asr(args.source_media,args.model_directory,args.window_seconds,args.out)
    report.update(codeCommit=identity['gitCommit'],codeClean=identity['trackedWorkingTreeDirty'] is False,
        totalWallSeconds=time.monotonic()-began,actualTransportAttempts=len(attempts),newPaidCalls=0,
        networkGuard='socket_connect_denied',stage1PromotionAllowed=False,humanAcceptance='not_evaluated')
    write(args.out/'diagnostic-report.json',report)
    print(json.dumps(report))


if __name__=='__main__': main()
