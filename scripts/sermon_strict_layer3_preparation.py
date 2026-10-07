"""Consume a current D4 intent into the EXISTING immutable speech-job schema.

Only deterministic preparation runs here. No TTS, alignment, listening approval,
audio package, release, publication or worker is dispatched. Existing adapter,
voice authorization and human validators decide synthesis eligibility unchanged.
"""
from pathlib import Path
import json
from scripts import sermon_review_contracts as c
from scripts import sermon_workflow_jobs as jobs
from scripts import sermon_review_budget as budget
from scripts import sermon_public_snapshot as public
from scripts import prepare_target_language_speech_job as speech
from scripts.sermon_release_workflow import _safe_path

VOICE_INPUTS={'clip_voice_authorization_path','source_voice_authorization_path',
              'clip_voice_capability_path','clip_timeline_map_path'}


def prepare(boundary, intent_id, *, adapter_path, registry_path, out, **voice_paths):
    """Revalidate the whole locale under existing locks before preparing once.

    A durable preparation marker pins every path/input BEFORE writing job.json.
    After an uncertain write, the same call may validate the exact existing job;
    it never overwrites an output or starts synthesis. A different output path
    cannot consume the same permission as fresh work.
    """
    c.require(set(voice_paths)<=VOICE_INPUTS,'unknown_speech_preparation_input')
    out=_safe_path(out)
    paths={k:_safe_path(v) for k,v in dict(adapter_path=adapter_path,registry_path=registry_path,**voice_paths).items()}
    with boundary._locked() as (record_path,record,record_bytes,ledger):
        intent=record['intents'].get(intent_id)
        c.require(intent is not None,'layer3_admission_intent_missing')
        snapshot=boundary._load(record_bytes,ledger)
        validated,decisions,reasons=boundary._validate(snapshot,intent['createdAt'])
        c.require(not reasons and validated is not None and
            validated['publicCandidateSha256']==intent['publicCandidateSha256'] and
            validated['humanReceiptSha256']==intent['humanReceiptSha256'], 'layer3_admission_evidence_changed')
        config=boundary.config
        protected=[boundary.store.root,boundary._path(config.job_root),*map(boundary._path,config.revision_roots)]
        c.require(not any(out==p or out in p.parents or p in out.parents for p in protected) and
            not any(out==p or out in p.parents for p in paths.values()),'speech_preparation_paths_overlap')
        captured={k:c.read_snapshot(path)[1] for k,path in paths.items()}
        expected=speech.prepare_job(config.source,config.anchor,config.public_candidate,config.policy,
            config.human_receipt,paths['adapter_path'],paths['registry_path'],out,
            strict_rubric=c.decode_json(snapshot.files['rubric']),build_only=True,
            **{k:v for k,v in paths.items() if k in VOICE_INPUTS})
        # Speech jobs aggregate reviewed units; private per-revision limits do
        # not apply. Check the exact durable writer encoding before any marker
        # or output is created, using the same public bound as both replay paths.
        public.decode_json((json.dumps(expected,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8'))
        c.require(all(c.read_snapshot(paths[k])[1]==v for k,v in captured.items()),'speech_preparation_input_changed')
        fresh=boundary._load(c.read_snapshot(record_path)[1],c.read_snapshot(
            boundary.store.root / budget.STORE_ID / 'state.json')[0])
        c.require(fresh.snapshot_sha256==snapshot.snapshot_sha256,'speech_preparation_snapshot_changed')
        binding={'intentId':intent_id,'out':str(out),'inputs':{k:{'path':str(paths[k]),
            'fileBytesSha256':c.bytes_sha256(v)} for k,v in captured.items()},
            'publicCandidateSha256':intent['publicCandidateSha256'],
            'humanReceiptSha256':intent['humanReceiptSha256']}
        marker=record_path.parent/('prepare-'+intent_id+'.json')
        if marker.exists():
            saved,_=c.read_snapshot(marker)
            c.require(type(saved) is dict and set(saved)=={'schemaVersion','binding','status','jobSha256'} and
                saved['schemaVersion']=='sermon-strict-layer3-preparation-v1' and saved['status'] in {'reserved','prepared'} and
                saved['binding']==binding,'speech_preparation_identity_changed')
            if saved['status']=='prepared':
                c.require((out/'job.json').exists() and c.canonical_sha256(public.read_snapshot(out/'job.json')[0])==saved['jobSha256'],
                    'speech_preparation_completed_output_missing_or_changed')
        else:
            c.require(not out.exists(),'speech_preparation_requires_new_output')
            jobs._persist(marker,{'schemaVersion':'sermon-strict-layer3-preparation-v1',
                'binding':binding,'status':'reserved','jobSha256':None})
        target=out/'job.json'
        if target.exists():
            job,_=public.read_snapshot(target)
            speech.validate_speech_job_schema(job)
            c.require({k:v for k,v in job.items() if k!='createdAt'}==
                {k:v for k,v in expected.items() if k!='createdAt'},'speech_preparation_output_changed')
        else:
            c.require(not out.exists() or not any(out.iterdir()),'speech_preparation_partial_output')
            out.mkdir(parents=True,exist_ok=True,mode=0o700);jobs._sync_directory_ancestry(out)
            jobs._persist(target,expected);job=public.read_snapshot(target)[0]
            c.require(job==expected,'speech_preparation_output_changed')
        jobs._persist(marker,{'schemaVersion':'sermon-strict-layer3-preparation-v1',
            'binding':binding,'status':'prepared','jobSha256':c.canonical_sha256(job)})
        return {'status':'prepared','scope':'speech_job_preparation_only','intentId':intent_id,
            'jobSha256':c.canonical_sha256(job),'synthesisEligible':job['synthesisEligible'],
            'modelCalls':0,'dispatched':False}
