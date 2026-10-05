"""Real local L4 builders/validators with synthetic approved upstream evidence."""
import argparse
import copy
import hashlib
import json
import subprocess
from pathlib import Path
import pytest
from scripts import build_full_video_app_release as builder
from scripts import sermon_unified_delivery as delivery
from scripts import delivery_contract as d
from scripts import review_target_language_audio as audio_review
from scripts import study_artifacts


def save(root, name, value):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    return path


def binding(path):
    return {'path':str(path), 'sha256':builder.digest(path)}


@pytest.fixture
def prepared(tmp_path):
    from tests import test_produce_target_language_candidate as source_fixtures
    from tests import test_prepare_target_language_speech_job as speech_fixtures
    from tests import test_review_target_language_audio as audio_fixtures
    sf, tf = source_fixtures.ProduceTargetLanguageCandidateTests(), speech_fixtures.TargetLanguageSpeechJobTests()
    try:
        sf.setUp();tf.setUp()
        source = sf.source
        page, locale = 'synthetic-study-page', 'ko'
        candidate = copy.deepcopy(tf.candidate)
        candidate['englishSourcePackageJsonSha256']=d.sha(source)
        candidate['anchorManifestSha256']=d.sha(sf.anchor)
        for group, unit in zip(candidate['groups'], sf.anchor['sourceUnits']):
            group['sourceUnitIds']=[unit['sourceUnitId']]
            group['coverage']=[{'sourceUnitId':unit['sourceUnitId'],'targetText':group['targetText']}]
        human=copy.deepcopy(tf.human_review_receipt)
        human.update(englishSourcePackageJsonSha256=d.sha(source),anchorManifestJsonSha256=d.sha(sf.anchor),candidateJsonSha256=d.sha(candidate))
        track=tmp_path/'tone.mp3'
        subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','sine=frequency=440:duration=10','-y',str(track)],check=True)
        captions={'cues':[{'textGroupId':g['translationGroupId'],'start':i*5,'end':(i+1)*5,'text':g['targetText']} for i,g in enumerate(candidate['groups'])]}
        cap_path=save(tmp_path,'captions.json',captions)
        package, screening=audio_fixtures.fixture()
        package.update(targetLocale=locale,englishSourcePackageJsonSha256=d.sha(source),targetLanguageCandidateJsonSha256=d.sha(candidate),
            track=binding(track),captions=binding(cap_path),machineScreening={'status':'pass','model':'Qwen3-ASR','coverage':1.0})
        unit_path=tmp_path/'unit.wav';unit_path.write_bytes(b'synthetic-unit')
        package['units']=[{'textGroupId':g['translationGroupId'],'targetTextSha256':hashlib.sha256(g['targetText'].encode()).hexdigest(),
            'audio':binding(unit_path),'durationSeconds':5.0} for g in candidate['groups']]
        schedule=save(tmp_path,'schedule.json',{'synthetic':True});package['schedule']={**binding(schedule),'jsonSha256':d.sha({'synthetic':True})}
        screening.update(targetLocale=locale,trackSha256=builder.digest(track),status='pass',reviewedGroupIds=[u['textGroupId'] for u in package['units']],
            unitAudioSha256s=[u['audio']['sha256'] for u in package['units']],results=[{'textGroupId':u['textGroupId'],'targetTextSha256':u['targetTextSha256'],
                'audioSha256':u['audio']['sha256'],'recognized':'synthetic','similarity':1.0,'differences':[],'status':'pass'} for u in package['units']])
        worksheet=audio_review.prepare(package,screening)
        worksheet.update(decision='approved',reviewedBy='synthetic reviewer',reviewedAt='2026-10-04T20:00:00Z',fullPlayback='approved',videoSync1x='approved',checks={name:'approved' for name in audio_review.CHECKS})
        audio, audio_receipt=audio_review.approve(package,screening,worksheet)
        proposal=tmp_path/'proposal.md';proposal.write_text('Synthetic approved metadata')
        fields={'series':'Synthetic series','title':'Synthetic title','speaker':'Synthetic speaker','scripture':'John 3:16','summary':'Synthetic summary','outline':['Legacy metadata outline must not substitute approved outline']}
        proposal.write_text(' '.join(str(v) for v in fields.values()))
        metadata={'schemaVersion':'sermon-formal-dev-metadata-approval-v2','pageId':page,'date':'2026-09-20','proposalFileSha256':builder.digest(proposal),
            'approvedLocales':[locale],'decision':'approved_selected_locales','approvalText':'所列语言页面信息已批准','reviewer':'user','recordedAt':'2026-10-04T20:00:00Z','locales':{locale:fields}}
        content={'schemaVersion':'sermon-full-video-text-content-v1','pageId':page,'targetLocale':locale,'sourceLocale':'en','status':'human_reviewed',
            'englishSourcePackageJsonSha256':d.sha(source),'targetLanguageCandidateJsonSha256':d.sha(candidate),'sourceMediaSha256':source['source']['media']['sha256'],
            'durationSeconds':builder.stage.decode_audio(track,'fixture'),'sourceVideoUrl':f'/pages/{page}/full-video-browser.mp4',**fields,
            'cues':[{**cue,'sourceUnitIds':g['sourceUnitIds']} for cue,g in zip(captions['cues'],candidate['groups'])]}
        documents={'source':source,'metadata_approval':metadata,'full_candidate':candidate,'spoken_candidate':candidate,'full_review_receipt':human,'spoken_review_receipt':human,
            'audio_package':audio,'audio_review_receipt':audio_receipt,'audio_screening_receipt':screening,'full_content':content}
        for kind in ('outline','meditation'):
            artifact=study_artifacts.produce(kind,[{'title':kind+' <full>','body':"First complete sentence.\nSecond complete sentence & last words.\nJesus' 말씀 / esperanza.",'sourceUnitIds':candidate['groups'][0]['sourceUnitIds']}],page_id=page,locale=locale,source_sha=d.sha(source),text_sha=d.sha(candidate),producer_identity='synthetic-v1')
            review={'schemaVersion':'sermon-study-review-v1',**{k:artifact[k] for k in ('kind','pageId','locale','sourcePackageSha256','textCandidateSha256')},
                'artifactSha256':d.sha(artifact),'decision':'approved','humanApproval':True,'reviewedBy':'synthetic','reviewedAt':'2026-10-04T20:00:00Z',
                'checks':{k:'pass' for k in ('faithfulness','scriptureIntegrity','localeReadability')}}
            documents[kind]=artifact;documents[kind+'_review']=review
        paths={name:save(tmp_path,name+'.json',value) for name,value in documents.items()};paths['metadata_proposal']=proposal
        intent={'schemaVersion':'sermon-release-intent-v1','environment':'dev','channel':'dev','project':'test','site':'test-dev','origin':'https://test-dev.web.app'}
        config={'schemaVersion':'sermon-unified-delivery-v1','pageId':page,'date':'2026-09-20','locales':[locale], 'intent':intent,
            'routes':{'dev':{k:intent[k] for k in ('channel','project','site','origin')}},'workRoot':str(tmp_path/'work'),
            'requiredEndpoints':['dev','beta','production_ios','production_web'],
            'inputs':{name:binding(path) if name in ('source','metadata_approval','metadata_proposal') else {locale:binding(path)} for name,path in paths.items()}}
        config_path=save(tmp_path,'config.json',config)
        frozen=tmp_path/'frozen.json'; state=delivery.freeze(config_path,frozen)
        result=delivery.execute(frozen,state['planHash'])
        yield {'root':tmp_path,'config':config,'frozen':frozen,'state':state,'result':result,'locale':locale,'page':page,'documents':documents,'source':source}
    finally:
        tf.doCleanups();sf.doCleanups()


def seal_fixture(f):
    prepared=f['root']/'work/prepared';manifest,assets=builder.verified_assets(prepared)
    receipt=save(f['root'],'http.json',{'schemaVersion':'sermon-app-assets-http-verification-v1','status':'pass','origin':f['config']['intent']['origin'],
        'verifiedAt':'2026-10-04T20:00:00Z','assets':[{**row,'status':'pass'} for row in assets]})
    sealed=f['root']/'sealed';builder.seal(argparse.Namespace(prepared=prepared,http_verification=receipt,out=sealed))
    return sealed


def test_real_prepare_seal_publish_inventory_contains_complete_reviewed_study(prepared):
    f=prepared;root=f['root']/'work/prepared';state=delivery.inspect(f['frozen'])
    assert state['pageId']==f['page'] and state['sourceIdentity']==d.source_identity(f['source'])
    assert state['sourcePackageSha256']==d.sha(f['source'])
    release=builder.read(root/'public/releases-v2'/f['page']/(f['locale']+'.json'))
    assert release['schemaVersion']=='sermon-target-language-release-package-v3'
    assert len(release['assets'])==7
    checked=d.validate_public_study(release,reader=lambda url:(root/'public'/url.lstrip('/')).read_bytes())
    assert checked['meditation']==f['documents']['meditation']
    html=(root/'public/pages'/f['page']/f['locale']/'index.html').read_text()
    assert 'id="study-outline"' in html and 'id="study-meditation"' in html
    assert 'Second complete sentence &amp; last words.' in html and 'Legacy metadata outline' not in html
    sealed=seal_fixture(f);d.validate_catalog_snapshot(sealed)
    catalog=builder.read(sealed/'public/multilingual-v3.json')
    assert catalog['pages'][0]['sourceMediaSha256']==release['sourceIdentity']['mediaSha256']
    assert catalog['pages'][0]['sourceIdentitySha256']==release['englishSourcePackageJsonSha256']
    report=builder.read(sealed/'seal-report.json')
    assert sum('/study/' in row['path'] for row in report['files'])==3
    assert {'/' + name for name in builder.RUNTIME_WEB_FILES} <= {row['path'] for row in report['files']}
    for name in builder.RUNTIME_WEB_FILES:
        assert (sealed/'public'/name).read_bytes() == (builder.RUNTIME_WEB_ROOT/name).read_bytes()
    target=sealed/'public/study'/f['page']/f['locale']/'meditation.json';target.write_text('{}')
    with pytest.raises(ValueError):d.validate_catalog_snapshot(sealed)


def endpoint_fixture(f, sealed):
    release_path=f"/releases-v2/{f['page']}/{f['locale']}.json"
    release=builder.read(sealed/'public'/release_path.lstrip('/'))
    candidate=f['state']['candidateSha256'];locale=f['locale'];origin=f['config']['intent']['origin']
    studies={kind:release['fourProducts'][kind+'ArtifactSha256'] for kind in ('outline','meditation')}
    telemetry={'schemaVersion':'sermon-playback-observation-v1','candidateSha256':candidate,'locale':locale,'origin':origin,
        'audioUrl':origin+next(row['path'] for row in release['assets'] if row['role']=='audio'),'runner':'browser',
        'paused':False,'ended':False,'currentTimeStart':0,'currentTimeEnd':3,'playbackRate':1,'sourceVideoMuted':True,
        'captionText':'current caption','captionLocale':locale,'syncErrorSeconds':0,'studyArtifacts':studies,'studyDisplayed':True}
    evidence=save(f['root'],'playback.json',telemetry)
    rows=[{'role':'catalog','path':'/multilingual-v3.json'},{'role':'release','path':release_path}]+release['assets']
    rows += [{'role':'reader_runtime','path':'/' + name} for name in builder.RUNTIME_WEB_FILES]
    receipt={'locales':[locale],'readback':{'schemaVersion':'sermon-client-readback-v2','intent':f['config']['intent'],
        'candidateSha256':candidate,'observedAt':'2026-10-04T20:00:00Z','resources':[{'role':r['role'],'url':origin+r['path'],
            'sha256':builder.digest(sealed/'public'/r['path'].lstrip('/'))} for r in rows]},
        'playback':[{'channel':'dev','locale':locale,'candidateSha256':candidate,'humanApproval':True,'reviewedBy':'synthetic',
            'reviewedAt':'2026-10-04T20:00:00Z','evidencePath':evidence.name,'evidenceSha256':builder.digest(evidence),
            'checks':{k:'pass' for k in ('actualPlayback','captions','sourceVideoMuted','synchronizationAt1x','outline','meditation')}}]}
    rp=save(f['root'],'endpoint.json',receipt)
    config=copy.deepcopy(f['config']);config['acceptance']=[{'name':'dev','intent':config['intent'],'receipt':binding(rp),'evidenceRoot':str(f['root'])}]
    def reader(url):
        path=sealed/'public'/url.removeprefix(origin+'/')
        return (200,path.read_bytes()) if path.is_file() else (404,b'')
    return config,receipt,evidence,rp,reader


def test_endpoint_requires_all_study_resources_and_human_display_evidence(prepared):
    f=prepared;sealed=seal_fixture(f);config,receipt,evidence,rp,reader=endpoint_fixture(f,sealed)
    assert delivery._endpoints(config,f['root'],sealed,f['state'],reader)==['dev']
    receipt['readback']['resources']=[r for r in receipt['readback']['resources'] if r['role']!='meditation']
    save(f['root'],rp.name,receipt);config['acceptance'][0]['receipt']=binding(rp)
    with pytest.raises(ValueError,match='misses current locale resources'):
        delivery._endpoints(config,f['root'],sealed,f['state'],reader)
    config,receipt,evidence,rp,reader=endpoint_fixture(f,sealed)
    data=builder.read(evidence);data['studyDisplayed']=False;save(f['root'],evidence.name,data)
    receipt['playback'][0]['evidenceSha256']=builder.digest(evidence);save(f['root'],rp.name,receipt);config['acceptance'][0]['receipt']=binding(rp)
    with pytest.raises(ValueError,match='did not display'):
        delivery._endpoints(config,f['root'],sealed,f['state'],reader)


def test_actual_builder_output_loads_complete_study_in_web(prepared):
    f=prepared;sealed=seal_fixture(f)
    module=(builder.ROOT/'experiments/sermon-dubbing-poc/web/published-weeks.mjs').as_uri()
    script="""
import {readFile} from 'node:fs/promises';
const {loadPublishedWeeks}=await import(process.argv[1]);
const fetchImpl=async path=>{try{return new Response(await readFile(process.argv[2]+path));}catch{return new Response('',{status:404});}};
const result=await loadPublishedWeeks(fetchImpl);
if(result.weeks.length!==1)throw new Error(JSON.stringify(result));
const week=result.weeks[0];
if(week.studyStatus!=='human_reviewed'||week.meditation[0].body!==JSON.parse(process.argv[3])||week.outline[0].title!=='outline <full>')throw new Error('Study text not exposed');
console.log(JSON.stringify({status:'passed',studyArtifacts:week.studyArtifacts}));
"""
    result=subprocess.run(['node','--input-type=module','-e',script,module,str(sealed/'public'),json.dumps(f['documents']['meditation']['sections'][0]['body'])],capture_output=True,text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['status']=='passed'


def test_web_rejects_changed_study_bytes_and_cross_page_study(prepared):
    f=prepared;sealed=seal_fixture(f)
    module=(builder.ROOT/'experiments/sermon-dubbing-poc/web/published-weeks.mjs').as_uri()
    script="""
import {readFile} from 'node:fs/promises';
const {loadPublishedWeeks}=await import(process.argv[1]);
let reads=0;
const fetchImpl=async path=>{try{let bytes=await readFile(process.argv[2]+path);if(path.endsWith('/meditation.json')){reads++;bytes=Buffer.from('{}');}return new Response(bytes);}catch{return new Response('',{status:404});}};
const result=await loadPublishedWeeks(fetchImpl);
if(result.weeks.length||!reads||!result.errors.some(e=>e.includes('hash mismatch')))throw new Error(JSON.stringify(result));
"""
    result=subprocess.run(['node','--input-type=module','-e',script,module,str(sealed/'public'),json.dumps(f['documents']['meditation']['sections'][0]['body'])],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    release=builder.read(sealed/'public/releases-v2'/f['page']/(f['locale']+'.json'))
    study_path=sealed/'public/study'/f['page']/f['locale']/'meditation.json'
    artifact=builder.read(study_path);artifact['pageId']='another-page';save(study_path.parent,study_path.name,artifact)
    next(row for row in release['assets'] if row['role']=='meditation')['sha256']=builder.digest(study_path)
    with pytest.raises(ValueError,match='artifact identity differs'):
        d.validate_public_study(release,reader=lambda path:(sealed/'public'/path.lstrip('/')).read_bytes())


def test_inspect_refuses_full_content_from_another_page_before_prepare(prepared):
    f=prepared;config=copy.deepcopy(f['config']);path=f['root']/'full_content.json';content=builder.read(path);content['pageId']='another-page';save(f['root'],path.name,content)
    config['inputs']['full_content'][f['locale']]=binding(path)
    raw=save(f['root'],'wrong-page-config.json',config)
    with pytest.raises(ValueError,match='source/page identity differs'):delivery.inspect(raw)
