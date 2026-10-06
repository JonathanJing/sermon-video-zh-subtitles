"""Closed adapter registry; no manifest-supplied executable, import or shell."""
from __future__ import annotations
import json
from pathlib import Path
import subprocess
import time
from scripts.sermon_unified import contracts as c

STAGE_ADAPTERS = {
    'media.verify': {'media_verify'},
    'canonical.inspect': {'english_source','layer2_admit','translation_review','layer3_screen','listen_review'},
    'canonical.layer2': {'layer2_group'},
    'canonical.audio': {'layer3_unit'},
    'source.prepare': {'asr'},
    'app.prepare': {'study_product'},
    'app.delivery': {'study_product','publish_endpoint'},
    'study.produce': {'study_product'},
    'fixture.replay': set(c.STAGES) - {'window_review','translation_review','listen_review','publish_endpoint'},
    'review.gate': {'window_review','english_source','translation_review','listen_review','study_product','publish_endpoint'},
}


def config_path(manifest, base, step):
    return c.binding(manifest, base, step.get('configuration', ''))


def inspect_step(m, base, step, *, ready=True):
    if step['stageId'] not in STAGE_ADAPTERS[step['adapter']]:
        raise c.ContractError('adapter_stage_mismatch')
    if step['adapter'] == 'source.prepare':
        from scripts import sermon_unified_source as source
        plan=source.inspect(config_path(m,base,step))
        if (not plan['snapshotBound'] or plan['sourceId']!=m['source']['sourceId']
            or plan['sourceMediaSha256']!=m['source']['mediaSha256']
            or any(plan['window'][k]!=m['source']['window'][k] for k in ('startSeconds','endSeconds'))):
            raise c.ContractError('source_preparation_identity_changed')
        identity={'sourceId':plan['sourceId'],'sourceUrlHash':plan['sourceUrlHash'],
                  'mediaSha256':plan['sourceMediaSha256'],'durationSeconds':plan['sourceDurationSeconds'],
                  'window':dict(plan['window'],timeBase='source_media',approvalReceiptSha256=plan['windowApprovalSha256'])}
        if identity != m['source'] or plan['sourceIdentity']['productionRunId']!=m['productionRunId']:
            raise c.ContractError('source_preparation_full_identity_changed')
        authority=c.binding(m,base,step.get('budgetAuthorization',''))
        if c.file_sha(authority)!=plan['inputsSha256']['budgetAuthorization']:
            raise c.ContractError('source_budget_authority_changed')
        cap=plan['globalBounds']['costMicrousd']
        if cap>m['budget']['limitMicroUsd'] or cap>step.get('maxCostMicroUsd',0):
            raise c.ContractError('source_budget_exceeds_manifest')
    elif step['adapter'] == 'canonical.layer2':
        from scripts.sermon_unified_layer2_binding import inspect_bound
        binding_plan=inspect_bound(m,base,step,config_path(m,base,step))
        from scripts import canonical_layer2_controller as ctl
        config = ctl.load_configuration(config_path(m, base, step))
        from scripts.sermon_unified_canonical_binding import validate_selected_source
        validate_selected_source(m,base,c.digest(c.read(config.inspection_root/config.inspection['source'])))
        if step.get('locale') not in config.lanes:
            raise c.ContractError('controller_locale_mismatch')
        from scripts import canonical_layer2_budget as budget
        auth_path=c.binding(m,base,step.get('budgetAuthorization',''))
        auth=budget.load_authorization(config,auth_path,ctl.code_identity())
        cap=auth['value']['authority']['globalBounds']['costMicrousd']
        if cap>m['budget']['limitMicroUsd'] or cap>step.get('maxCostMicroUsd',0):
            raise c.ContractError('budget_authority_exceeds_manifest')
        if not ready:
            return
        source, anchor, policy = ctl._inputs(config, step['locale'], ctl.package_view(config))
        if source['source']['media']['sha256'] != m['source']['mediaSha256']:
            raise c.ContractError('controller_source_mismatch')
        lane = next(x for x in m['policies'] if x['locale'] == step['locale'])
        if c.file_sha(config.lanes[step['locale']]['policy']) != lane['policySha256']:
            raise c.ContractError('controller_policy_mismatch')
    elif step['adapter'] == 'canonical.audio':
        from scripts import sermon_unified_audio as audio
        plan=audio.inspect(config_path(m,base,step))
        if not plan['snapshotBound']:
            raise c.ContractError('audio_input_snapshot_required')
        audio.validate_manifest_binding(plan,m,step.get('locale'))
        from scripts.sermon_unified_canonical_binding import validate_selected_source
        validate_selected_source(m,base,plan['sourcePackage']['jsonSha256'])
        if plan['sourceMediaSha256']!=m['source']['mediaSha256'] or plan['targetLocale']!=step.get('locale'):
            raise c.ContractError('audio_source_or_locale_changed')
        policy=next(x for x in m['policies'] if x['locale']==step['locale'])
        if policy['policySha256']!=plan['policySha256']:
            raise c.ContractError('audio_policy_changed')
    elif step['adapter'] == 'study.produce':
        from scripts import sermon_unified_study as study
        plan=study.inspect(m,base,config_path(m,base,step),step)
        config=c.read(config_path(m,base,step))
        from scripts.sermon_unified_canonical_binding import validate_selected_source
        validate_selected_source(m,base,c.digest(c.read(c.binding(m,base,config['inputs']['source']))))
        if plan.get('schemaVersion')=='sermon-study-generation-inspection-v1':
            config=c.read(config_path(m,base,step))
            name=config['inputs']['budgetAuthorization']
            if step.get('budgetAuthorization')!=name:
                raise c.ContractError('study_step_budget_binding_required')
            cap=plan['globalBounds']['costMicrousd']
            if cap>m['budget']['limitMicroUsd'] or cap>step.get('maxCostMicroUsd',0):
                raise c.ContractError('study_budget_exceeds_manifest')
    elif step['adapter'] == 'app.delivery':
        from scripts import sermon_unified_delivery as delivery
        plan=delivery.inspect(config_path(m,base,step))
        if not plan['snapshotBound']:
            raise c.ContractError('delivery_input_snapshot_required')
        from scripts.sermon_unified_canonical_binding import validate_selected_source
        validate_selected_source(m,base,plan['sourcePackageSha256'])
        identity=dict(plan['sourceIdentity']);identity['window']=dict(identity['window'],timeBase='source_media')
        if identity!=m['source'] or plan['pageId']!=m['content']['pageId']:
            raise c.ContractError('delivery_full_identity_changed')
        if plan['sourceId']!=m['source']['sourceId'] or plan['mediaSha256']!=m['source']['mediaSha256'] or not set(plan['locales'])<=set(m['locales']):
            raise c.ContractError('delivery_source_or_locale_changed')
    elif step['adapter'] == 'canonical.inspect':
        from scripts.sermon_unified_canonical_binding import inspect_bound
        inspect_bound(m, base, config_path(m, base, step), step)
    elif step['adapter'] == 'app.prepare':
        from scripts import sermon_app_delivery_workflow as app
        app.snapshot(config_path(m, base, step))
    elif step['adapter']=='review.gate' and step.get('reviewKind')!='window':
        config=c.read(config_path(m,base,step))
        if set(config)!={'schemaVersion','inputs'} or config['schemaVersion']!='sermon-unified-review-inputs-v1' or not isinstance(config['inputs'],dict):
            raise c.ContractError('review_configuration_invalid')
        for name in config['inputs'].values():
            c.binding(m,base,name)
        if step.get('reviewKind')!='english':
            from scripts.sermon_unified_canonical_binding import validate_selected_source
            validate_selected_source(m,base,c.digest(c.read(c.binding(m,base,config['inputs']['source']))))
    elif step['adapter'] == 'fixture.replay':
        obj = c.read(config_path(m, base, step))
        if (m['transport'] != 'fixture' or obj.get('fixtureSetId') != m.get('fixtureSetId')
                or obj.get('mediaSha256') != m['source']['mediaSha256']
                or obj.get('stageId') != step['stageId'] or obj.get('fixtureOnly') is not True):
            raise c.ContractError('fixture_response_missing')


def execute(m, base, step, out):
    inspect_step(m, base, step)
    adapter = step['adapter']
    if adapter == 'media.verify':
        path = c.binding(m, base, 'media')
        result = subprocess.run(['ffprobe','-v','error','-show_entries','format=duration:stream=codec_type',
                                 '-of','json',str(path)],capture_output=True,text=True,timeout=60)
        if result.returncode:
            raise c.ContractError('media_probe_failed')
        data = json.loads(result.stdout)
        duration = float(data['format']['duration'])
        if not any(x.get('codec_type') == 'audio' for x in data.get('streams',[])) or duration <= 0:
            raise c.ContractError('media_audio_missing')
        if m['source']['window']['endSeconds'] > duration + 0.001:
            raise c.ContractError('source_window_exceeds_media')
        # Full audio decode, with no output and bounded execution.
        check = subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(path),'-map','0:a:0','-f','null','-'],
                               capture_output=True,timeout=max(60,duration*2))
        if check.returncode or c.file_sha(path) != m['source']['mediaSha256']:
            raise c.ContractError('media_decode_or_identity_failed')
        return {'status':'succeeded','artifact':'verified','kind':'media_identity',
                'mediaSha256':m['source']['mediaSha256'],'durationSeconds':duration,
                'freshApiAttempts':0,'productionEligible':False}
    if adapter == 'fixture.replay':
        data = c.read(config_path(m, base, step))
        return {'status':'succeeded','artifact':'present_unverified','fixtureOnly':True,
                'fixtureSetId':m['fixtureSetId'],'freshApiAttempts':0,'cacheHit':False,
                'productionEligible':False,'responseSha256':c.digest(data)}
    if adapter == 'review.gate' and step.get('reviewKind')=='window':
        from scripts.sermon_unified_reviews import validate_window
        evidence=validate_window(m,base=base)
        return {'status':'succeeded','artifact':'verified','review':'approved','kind':'window_review','receiptSha256':evidence['receiptSha256']}
    if adapter == 'review.gate':
        # Approval files are ingested via trusted validators; execution never
        # creates approval, interprets free text or manufactures a reviewer.
        return {'status':'blocked','reason':'human_review_required','review':'human_pending'}
    if adapter == 'source.prepare':
        from scripts import sermon_unified_source as source
        return source.execute(config_path(m,base,step))
    if adapter == 'canonical.layer2':
        from scripts import canonical_layer2_controller as ctl
        authority=c.binding(m,base,step['budgetAuthorization'])
        timeout=time.monotonic()+step.get('timeoutSeconds',21600)
        while True:
            result=ctl.drive(config_path(m,base,step),step['locale'],budget_authorization=authority)
            if result['status']!='waiting':
                if result['status']=='succeeded':result['kind']='target_language_candidate'
                return result
            if time.monotonic()>=timeout:
                raise c.ContractError('durable_job_requires_reconciliation',6)
            time.sleep(1)
    if adapter == 'canonical.audio':
        from scripts import sermon_unified_audio as audio
        plan=audio.inspect(config_path(m,base,step))
        result=audio.execute(config_path(m,base,step),out.parent/(step['id']+'-audio-result.json'),
                             expected_plan_hash=plan['planHash'],allow_synthesis=not plan['settings']['assemblyOnly'])
        result['kind']='speech_job'
        return result
    if adapter == 'study.produce':
        from scripts import sermon_unified_study as study
        return study.execute(m,base,config_path(m,base,step),step,out)
    if adapter == 'app.delivery':
        from scripts import sermon_unified_delivery as delivery
        plan=delivery.inspect(config_path(m,base,step))
        result=delivery.execute(config_path(m,base,step),plan['planHash'])
        names={'dev':'firebase_dev','beta':'ios_beta','production_ios':'ios_prod','production_web':'firebase_prod'}
        result['validatedEndpoints']=[names[x] for x in result.get('validatedEndpoints',[])]
        if result['status']=='partial':
            required={'dev_reader_verified':{'firebase_dev'},'dual_test_end_approved':{'firebase_dev','ios_beta'},
                      'dual_production_verified':set(names.values())}.get(step['scope'],set())
            result['status']='succeeded' if required and required<=set(result['validatedEndpoints']) else 'blocked'
            result['reason']='endpoint_evidence_incomplete' if result['status']=='blocked' else 'endpoint_evidence_verified'
        return result
    if adapter == 'canonical.inspect':
        from scripts.sermon_unified_canonical_binding import inspect_bound
        data = inspect_bound(m, base, config_path(m, base, step), step)
        unit = ('source' if step['stageId']=='english_source' else
                ('audio.' if step['stageId'] in ('layer3_screen','listen_review') else 'text.') + step.get('locale',''))
        node = data['nodes'].get(unit,{})
        if step['stageId'] in ('translation_review','listen_review'):
            return {'status':'blocked','reason':'bound_review_validator_required','review':'human_pending'}
        return {'status':'succeeded' if node.get('status')=='validated' else 'blocked',
                'artifact':'verified' if node.get('status')=='validated' else 'present_unverified',
                'reason':'canonical_gate','evidence':data,'productionEligible':False}
    if adapter == 'app.prepare':
        from scripts import sermon_app_delivery_workflow as app
        result = app.run(config_path(m, base, step),mode='execute')
        return {'status':'blocked','reason':'verify_app_candidate_and_study_reviews',
                'evidence':result,'productionEligible':False}
    raise c.ContractError('adapter_unavailable')


def verify_result(m,base,step,result):
    """Read retained output evidence without dispatching another producer."""
    inspect_step(m,base,step)
    adapter=step['adapter']
    if adapter=='canonical.audio':
        from scripts import sermon_unified_audio as audio
        audio.verify_result(config_path(m,base,step),result)
    elif adapter=='canonical.layer2':
        from scripts import canonical_layer2_controller as ctl
        config=ctl.load_configuration(config_path(m,base,step))
        if ctl.package_view(config)['nodes']['text.'+step['locale']]['status']!='validated':
            raise c.ContractError('retained_candidate_not_validated')
    elif adapter=='source.prepare':
        package=c.read(result['candidatePath'])
        if c.digest(package)!=result['candidateSha256'] or package['source']['media']['sha256']!=m['source']['mediaSha256']:
            raise c.ContractError('retained_source_candidate_changed')
    elif adapter=='study.produce':
        from scripts import sermon_unified_study as study
        study.verify_result(m,base,config_path(m,base,step),step,result)
    elif adapter=='app.delivery':
        from scripts import sermon_unified_delivery as delivery
        plan=delivery.inspect(config_path(m,base,step))
        if plan['planHash']!=result['planHash'] or plan['candidateSha256']!=result['candidateSha256']:
            raise c.ContractError('retained_delivery_changed')
