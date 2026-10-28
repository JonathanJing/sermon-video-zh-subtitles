"""Synthetic tests only: no copyrighted guide text or private materials."""
import json
from pathlib import Path
import pytest
from tongxing_production.delivery import weekly_guide_staging as m


def text(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True); raw=m.encoded(obj);path.write_bytes(raw);return raw


def example_guide():
    w={'week':8,'title':'Synthetic title','scripture':'启示录 14 章','first':1,'last':2,
       'scripture_page':2,'start':'14:1','end':'14:2','appendix':[4,5]}
    source=('## PAGE 1（印刷页 1，id a）\n\nSample opening\n\n'
        '## PAGE 2（印刷页 2，id b）\n\n| Head A | Head B |\n| --- | --- |\n| X | Y |\n\n'
        '## PAGE 4（印刷页 4，id c）\n\nAppendix one\n\n'
        '## PAGE 5（印刷页 5，id d）\n\nAppendix two\n')
    return m.build_staged(source,{'14:1':'Synthetic verse one','14:2':'Synthetic verse two'},[w])[0]


@pytest.fixture
def context(tmp_path):
    guide=example_guide();staging=tmp_path/'stage';m.write_stage([guide],staging)
    public=tmp_path/'snapshot/public';public.mkdir(parents=True)
    content={'pageId':'sermon-8','targetLocale':'zh-Hans','series':m.SERIES,
             'title':'Synthetic title · 启示录 14 章','scripture':'启示录 14 章', 'englishSourcePackageJsonSha256':'a'*64,'sourceMediaSha256':'d'*64}
    contentraw=text(public/'content/8.json',content)
    release={'schemaVersion':'sermon-target-language-release-package-v2','pageId':'sermon-8','targetLocale':'zh-Hans','englishSourcePackageJsonSha256':'a'*64,'assets':[{'role':'content','path':'/content/8.json','sha256':m.digest(contentraw)}]}
    releaseraw=text(public/'releases/8.json',release)
    target={'contentStatus':'human_reviewed','releasePackageUrl':'/releases/8.json','releasePackageJsonSha256':m.digest(releaseraw)}
    catalog={'schemaVersion':'sermon-multilingual-catalog-v5','pages':[{'id':'sermon-8','sourceMode':'single_source','sourceIdentitySha256':'a'*64,'sourceMediaSha256':'d'*64,'targets':{'zh-Hans':target}}]}
    text(public/'multilingual-v5.json',catalog)
    expected={8:(staging/'week-08.json').read_bytes()}
    return staging,tmp_path/'snapshot',expected,content,release,catalog


def bind(ctx,bindings=None,validator=lambda _:None):
    staging,snapshot,expected,*_=ctx
    validator(snapshot)
    return m.verified_bindings(staging,snapshot,bindings or [{'week':8,'pageID':'sermon-8'}],expected,{'14:1':'Synthetic verse one','14:2':'Synthetic verse two'})


def test_staging_preserves_pages_scripture_and_unbound():
    g=example_guide();assert g['sermonPageId'] is None and g['humanApproval'] is False
    assert g['review']=='machine_translation_not_human_reviewed'
    assert [x['id'] for x in g['sections']]==['page-1','scripture-cuv1919','page-2','page-4','page-5']
    assert g['sections'][1]['body']=='14:1 Synthetic verse one\n\n14:2 Synthetic verse two'
    assert g['sections'][2]['body']=='Head A：X\nHead B：Y'
    assert g['source']['appendixPages']==[4,5]


def test_verified_explicit_binding_produces_content_hashed_manifest(context,tmp_path):
    calls=[];guides=bind(context,validator=lambda p:calls.append(p));assert len(calls)==1
    manifest=m.write_published(guides,tmp_path/'out',[],{});entry=manifest['entries'][0]
    raw=(tmp_path/'out/published'/f"{entry['sha256']}.json").read_bytes()
    assert m.digest(raw)==entry['sha256'] and len(raw)==entry['bytes']
    assert entry['path']==f"/weekly-guides/published/{entry['sha256']}.json"
    assert json.loads(raw)['id']=='sermon-8' and entry['locale']=='zh-Hans'


def test_rich_binding_verifies_v1_input_and_hashes_new_compatible_payload(context,tmp_path):
    staging,snapshot,expected,*_=context
    raw=expected[8];original=json.loads(raw)
    section=next(s for s in original['sections'] if s['id']=='page-1')
    revision={'correctionsSHA256':'f'*64,'entries':{1:{'week':8,
        'expectedOriginalBodySHA256':m.digest(section['body'].encode()),
        'correctedFallbackBody':'Corrected synthetic content',
        'blocks':[{'type':'paragraph','text':'Corrected synthetic content'}]}}}
    operations=m.verified_bindings(staging,snapshot,[{'week':8,'pageID':'sermon-8'}],expected,
        {'14:1':'Synthetic verse one','14:2':'Synthetic verse two'},rich_revision=revision)
    manifest=m.write_published(operations,tmp_path/'rich',[],{})
    entry=manifest['entries'][0];payload=(tmp_path/'rich/published'/f"{entry['sha256']}.json").read_bytes()
    guide=json.loads(payload);section=next(s for s in guide['sections'] if s['id']=='page-1')
    assert section['body']=='Corrected synthetic content' and section['blocks'][0]['text']==section['body']
    assert entry['richRevisionSHA256']==guide['richRevisionSHA256']=='f'*64
    assert m.digest(payload)==entry['sha256'] and (staging/'week-08.json').read_bytes()==raw
    bad=dict(revision,entries={1:{**revision['entries'][1], 'expectedOriginalBodySHA256':'0'*64}})
    with pytest.raises(ValueError,match='original guide body'):
        m.verified_bindings(staging,snapshot,[{'week':8,'pageID':'sermon-8'}],expected,
            {'14:1':'Synthetic verse one','14:2':'Synthetic verse two'},rich_revision=bad)


def test_rich_comparison_binding_preserves_source_body(context,tmp_path):
    staging,snapshot,expected,*_=context
    original=json.loads(expected[8]); section=next(s for s in original['sections'] if s['id']=='page-1')
    blocks=[{'type':'table','title':'','columns':['Left','Right'],'rows':[['left quotation','right quotation']]}]
    revision={'correctionsSHA256':'e'*64,'entries':{1:{'week':8,
        'expectedOriginalBodySHA256':m.digest(section['body'].encode()),'blocks':blocks}}}
    operations=m.verified_bindings(staging,snapshot,[{'week':8,'pageID':'sermon-8'}],expected,
        {'14:1':'Synthetic verse one','14:2':'Synthetic verse two'},rich_revision=revision)
    manifest=m.write_published(operations,tmp_path/'comparison',[],{})
    entry=manifest['entries'][0]; guide=json.loads((tmp_path/'comparison/published'/f"{entry['sha256']}.json").read_bytes())
    actual=next(s for s in guide['sections'] if s['id']=='page-1')
    assert actual['body']==section['body'] and actual['blocks']==blocks


def test_affected_week_rejects_default_add_and_update_but_allows_revoke(context, tmp_path):
    _,snapshot,_,*_=context
    guide=example_guide();guide['week']=9
    stage=tmp_path/'week9-stage';m.write_stage([guide],stage)
    expected={9:(stage/'week-09.json').read_bytes()}
    verses={'14:1':'Synthetic verse one','14:2':'Synthetic verse two'}
    for binding in ({'week':9,'pageID':'sermon-8'},
                    {'week':9,'pageID':'sermon-8','operation':'update','expectedEntrySha256':'a'*64,'reason':'fix'}):
        with pytest.raises(ValueError,match='requires verified --rich'):
            m.verified_bindings(stage,snapshot,[binding],expected,verses)
    revoke={'week':9,'pageID':'sermon-8','operation':'revoke','expectedEntrySha256':'a'*64,'reason':'unsafe'}
    assert m.verified_bindings(stage,snapshot,[revoke],expected,verses)[0]['operation']=='revoke'


def test_affected_week_requires_corrected_body_and_keeps_legacy_fallback(context,tmp_path,monkeypatch):
    from tongxing_production.delivery import weekly_guide_rich as rich
    _,snapshot,_,*_=context
    guide=example_guide();guide['week']=9; section=guide['sections'][0];section['id']='page-123'
    stage=tmp_path/'week9-stage';m.write_stage([guide],stage); expected={9:(stage/'week-09.json').read_bytes()}
    verses={'14:1':'Synthetic verse one','14:2':'Synthetic verse two'}
    corrected='Separate merged explanation'; sha=m.digest(corrected.encode())
    blocks=[{'type':'paragraph','text':corrected}]
    blocks_sha=m.digest(json.dumps(blocks,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode())
    monkeypatch.setitem(m.REQUIRED_CORRECTED_BODIES,9,(123,sha,blocks_sha))
    monkeypatch.setattr(rich,'CORRECTIONS_SHA256','f'*64)
    entry={'week':9,'expectedOriginalBodySHA256':m.digest(section['body'].encode()),
           'correctedFallbackBody':corrected,'correctedFallbackBodySHA256':sha,
           'blocks':blocks}
    revision={'correctionsSHA256':'f'*64,'entries':{123:entry}}
    bindings=[{'week':9,'pageID':'sermon-8'}]
    operations=m.verified_bindings(stage,snapshot,bindings,expected,verses,rich_revision=revision)
    manifest=m.write_published(operations,tmp_path/'safe',[],{}); record=manifest['entries'][0]
    payload=json.loads((tmp_path/'safe/published'/f"{record['sha256']}.json").read_bytes())
    corrected_section=next(s for s in payload['sections'] if s['id']=='page-123')
    # Old decoders read body and ignore unknown block/revision fields.
    assert corrected_section['body']==corrected
    tampered=json.loads(json.dumps(operations)); tampered[0]['guide']['sections'][0]['blocks']=[{'type':'paragraph','text':'wrong'}]
    with pytest.raises(ValueError,match='corrected blocks'):
        m.write_published(tampered,tmp_path/'tampered',[],{})
    for bad in ({'correctionsSHA256':'0'*64,'entries':{123:entry}},
                {'correctionsSHA256':'f'*64,'entries':{}},
                {'correctionsSHA256':'f'*64,'entries':{123:{**entry,'correctedFallbackBody':'wrong'}}},
                {'correctionsSHA256':'f'*64,'entries':{123:{**entry,'blocks':[{'type':'paragraph','text':'wrong'}]}}}):
        with pytest.raises(ValueError,match='requires'):
            m.verified_bindings(stage,snapshot,bindings,expected,verses,rich_revision=bad)


def test_unbound_weeks_never_enter_empty_manifest(tmp_path):
    assert m.write_published([],tmp_path/'empty',[],{},allow_initial_empty=True)['entries']==[]


@pytest.mark.parametrize('field,value,expected',[('series','Other','series mismatch'),('title','Other','title mismatch'),('scripture','启示录 14:2','scripture mismatch'),('targetLocale','ko','content identity mismatch')])
def test_missing_or_mismatched_identity_is_rejected(context,field,value,expected):
    staging,snapshot,_,content,release,catalog=context;public=snapshot/'public'
    content[field]=value;raw=text(public/'content/8.json',content);release['assets'][0]['sha256']=m.digest(raw)
    rr=text(public/'releases/8.json',release);catalog['pages'][0]['targets']['zh-Hans']['releasePackageJsonSha256']=m.digest(rr)
    text(public/'multilingual-v5.json',catalog)
    with pytest.raises(ValueError,match=expected):bind(context)


def test_wrong_hash_unknown_page_and_duplicates_are_rejected(context):
    staging,snapshot,*_=context; (snapshot/'public/releases/8.json').write_text('{}')
    with pytest.raises(ValueError,match='release hash mismatch'):bind(context)
    with pytest.raises(ValueError,match='page not unique'):bind(context,[{'week':8,'pageID':'unknown'}])
    with pytest.raises(ValueError,match='previous entry identity changed'):
        # Reset and use duplicate validation in manifest writer, independent of release bytes.
        m.write_published([{'pageID':'same','week':8,'operation':'revoke','expectedEntrySha256':'a'*64,'reason':'test'}, {'pageID':'same','week':9,'operation':'revoke'}],snapshot/'dup',[],{})


def test_modified_staging_even_if_rehashed_is_rejected(context):
    staging,*_=context;p=staging/'week-08.json';d=json.loads(p.read_bytes());d['sections'][0]['body']='tampered';raw=text(p,d)
    mf=staging/'staging-manifest.json';v=json.loads(mf.read_bytes());v['entries'][0]['sha256']=m.digest(raw);v['entries'][0]['bytes']=len(raw);text(mf,v)
    with pytest.raises(ValueError,match='differs from verified sources'):bind(context)


def test_snapshot_validation_failure_is_not_ignored(context):
    def fail(_): raise ValueError('snapshot not verified')
    with pytest.raises(ValueError,match='snapshot not verified'):bind(context,validator=fail)


def test_output_cannot_escape_ignored_artifacts(tmp_path):
    with pytest.raises(ValueError,match='ignored artifacts'):m.safe_output(tmp_path/'other')


def test_unverified_source_is_rejected_before_creating_output(tmp_path):
    out=tmp_path/'candidate'
    with pytest.raises(ValueError,match='source hash mismatch'):
        m.prepare_stage(b'unverified translation',b'unverified scripture',out)
    assert not out.exists()


def test_unknown_chinese_target_cannot_bind(context):
    staging,snapshot,_,_,_,catalog=context
    catalog['pages'][0]['targets']={}
    text(snapshot/'public/multilingual-v5.json',catalog)
    with pytest.raises(ValueError,match='published Chinese target required'):bind(context)


def test_scripture_ranges_compare_verified_verse_ids_without_date_guessing():
    cuv={f'14:{i}':'sample' for i in range(1,21)}
    expected=m.scripture_set('启示录 14 章',cuv)
    assert expected==m.scripture_set('启示录14:1–20',cuv)
    assert expected==m.scripture_set('启示录 第14章1节–14章20节',cuv)
    assert expected!=m.scripture_set('启示录14:1–19',cuv)
    cuv.update({f'{c}:{v}':'sample' for c in (6,7,8) for v in (1,2)})
    assert m.scripture_set('启示录6章–8章1节',cuv)==m.scripture_set('启示录6:1–8:1',cuv)
    with pytest.raises(ValueError):m.scripture_set('2026-11-01',cuv)
    with pytest.raises(ValueError):m.scripture_set('启示录14:0–20',cuv)
    with pytest.raises(ValueError):m.scripture_set('启示录14:1–0',cuv)
    with pytest.raises(ValueError):m.scripture_set('启示录0章',cuv)


def test_scripture_equivalence_still_rejects_supplemental_podcast(context):
    staging,snapshot,_,content,release,catalog=context;public=snapshot/'public'
    content['scripture']='启示录14:1–2';content['title']='Synthetic title · 启示录14:1–2'
    raw=text(public/'content/8.json',content);release['assets'][0]['sha256']=m.digest(raw)
    rr=text(public/'releases/8.json',release);catalog['pages'][0]['targets']['zh-Hans']['releasePackageJsonSha256']=m.digest(rr);text(public/'multilingual-v5.json',catalog)
    assert bind(context)[0]['pageID']=='sermon-8'
    content['title']='如果我有更多时间 · Synthetic title'
    raw=text(public/'content/8.json',content);release['assets'][0]['sha256']=m.digest(raw)
    rr=text(public/'releases/8.json',release);catalog['pages'][0]['targets']['zh-Hans']['releasePackageJsonSha256']=m.digest(rr);text(public/'multilingual-v5.json',catalog)
    with pytest.raises(ValueError,match='title mismatch'):bind(context)


def operation(page,week,body):
    return {'pageID':page,'week':week,'operation':'add','editionId':page,'sourceIdentitySha256':'a'*64,
        'releasePackageJsonSha256':'b'*64,'guide':{'id':page,'week':week,'title':'sample','scripture':'sample',
         'sections':[{'id':'x','title':'x','subtitle':'x','symbol':'book','body':body}]}}


def test_increment_preserves_previous_entries_assets_and_rejects_duplicates(tmp_path):
    first=m.write_published([operation('old',8,'old')],tmp_path/'first',[],{})
    entry=first['entries'][0];raw=(tmp_path/'first/published'/f"{entry['sha256']}.json").read_bytes()
    second=m.write_published([operation('new',10,'new')],tmp_path/'second',[entry],{entry['path']:raw})
    assert second['entries'][0]==entry and len(second['entries'])==2
    assert (tmp_path/'second/published'/f"{entry['sha256']}.json").read_bytes()==raw
    with pytest.raises(ValueError,match='duplicate existing page'):
        m.write_published([operation('old',8,'replacement')],tmp_path/'duplicate',[entry],{entry['path']:raw})
    with pytest.raises(ValueError,match='empty manifest'):
        m.write_published([],tmp_path/'no-implicit-empty',[],{})


def test_update_and_revocation_require_exact_previous_entry_and_retain_old_asset(tmp_path):
    first=m.write_published([operation('page',8,'old')],tmp_path/'first',[],{})
    entry=first['entries'][0];old=(tmp_path/'first/published'/f"{entry['sha256']}.json").read_bytes()
    updated=operation('page',8,'new');updated.update(operation='update',reason='verified source update',expectedEntrySha256='0'*64)
    with pytest.raises(ValueError,match='previous entry identity changed'):
        m.write_published([updated],tmp_path/'bad',[entry],{entry['path']:old})
    updated['expectedEntrySha256']=m.digest(m.encoded(entry))
    second=m.write_published([updated],tmp_path/'second',[entry],{entry['path']:old})
    new=second['entries'][0];assert new['status']=='available' and new['sha256']!=entry['sha256']
    assert (tmp_path/'second/published'/f"{entry['sha256']}.json").read_bytes()==old
    revoke={'pageID':'page','week':8,'operation':'revoke','reason':'withdrawn','expectedEntrySha256':m.digest(m.encoded(new))}
    newraw=(tmp_path/'second/published'/f"{new['sha256']}.json").read_bytes()
    third=m.write_published([revoke],tmp_path/'third',[new],{entry['path']:old,new['path']:newraw})
    assert third['entries'][0]=={**new,'status':'revoked'}
    assert (tmp_path/'third/published'/f"{new['sha256']}.json").read_bytes()==newraw


def test_existing_manifest_and_files_must_match_verified_receipt(tmp_path):
    first=m.write_published([operation('old',8,'old')],tmp_path/'first',[],{})
    root=tmp_path/'snapshot';dest=root/'public/weekly-guides';dest.mkdir(parents=True)
    import shutil
    shutil.copyfile(tmp_path/'first/manifest-v1.json',dest/'manifest-v1.json')
    shutil.copytree(tmp_path/'first/published',dest/'published')
    rows={}
    for f in dest.rglob('*.json'):
        p='/'+str(f.relative_to(root/'public'));raw=f.read_bytes();rows[p]={'path':p,'rawBytes':len(raw),'rawSha256':m.digest(raw),'managed':False}
    def verify(path):
        row=rows.get(path)
        if not row:raise ValueError('missing from receipt')
        raw=(root/'public'/path.lstrip('/')).read_bytes()
        if len(raw)!=row['rawBytes'] or m.digest(raw)!=row['rawSha256']:raise ValueError('receipt mismatch')
        return raw
    entries,assets=m.existing_manifest(root,rows,verify);assert entries==first['entries'] and len(assets)==1
    f=dest/'published'/f"{entries[0]['sha256']}.json";f.write_bytes(b'tampered')
    with pytest.raises(ValueError,match='receipt mismatch'):m.existing_manifest(root,rows,verify)
    with pytest.raises(ValueError,match='initialize over existing'):m.existing_manifest(root,rows,verify,True)


def test_target_source_identity_and_diagnostic_flags(context):
    staging,snapshot,_,_,release,catalog=context
    p=catalog['pages'][0];p['sourceMode']='per_target';p.pop('sourceIdentitySha256');t=p['targets']['zh-Hans'];t['editionId']='edition-8';t['sourceIdentitySha256']='c'*64;t['sourceMediaSha256']='d'*64
    content_path=snapshot/'public/content/8.json';content=json.loads(content_path.read_bytes());content['pageId']='edition-8';content['englishSourcePackageJsonSha256']='c'*64;raw=text(content_path,content)
    release['pageId']='edition-8';release['englishSourcePackageJsonSha256']='c'*64;release['assets'][0]['sha256']=m.digest(raw);rr=text(snapshot/'public/releases/8.json',release);t['releasePackageJsonSha256']=m.digest(rr);text(snapshot/'public/multilingual-v5.json',catalog)
    item=bind(context)[0];assert item['editionId']=='edition-8' and item['sourceIdentitySha256']=='c'*64 and item['releasePackageJsonSha256']==m.digest(rr)
    p['diagnosticOnly']=True;text(snapshot/'public/multilingual-v5.json',catalog)
    with pytest.raises(ValueError,match='diagnostic, simulated, or withdrawn'):bind(context)


def test_live_receipt_binds_environment_v5_and_absence_not_spa_fallback(tmp_path,monkeypatch):
    from tongxing_production.delivery import baseline,contract,single_source_dev_overlay
    root=tmp_path/'snapshot';public=root/'public';public.mkdir(parents=True)
    catalog=m.encoded({'schemaVersion':'sermon-multilingual-catalog-v5','pages':[]})
    (public/'multilingual-v5.json').write_bytes(catalog)
    target=baseline.hosting_target('dev')
    receipt={'status':'complete_verified_not_deployed','environment':'dev','project':target['project'],
        'site':target['site'],'origin':target['origin'],'baselineVersion':f"sites/{target['site']}/versions/abc",
        'rows':[{'path':'/multilingual-v5.json','rawBytes':len(catalog),'rawSha256':m.digest(catalog),'managed':False}]}
    text(root/'baseline-receipt.json',receipt)
    monkeypatch.setattr(contract,'validate_catalog_snapshot',lambda _:None)
    monkeypatch.setattr(single_source_dev_overlay,'verify_live_baseline',lambda *_:None)
    rows,verify,observed=m.verified_live_snapshot(root,'dev')
    assert observed['baselineVersion']==receipt['baselineVersion']
    assert m.existing_manifest(root,rows,verify,True)==([], {})
    with pytest.raises(ValueError,match='initialize-empty'):m.existing_manifest(root,rows,verify,False)
    # HTTP SPA fallback is irrelevant: only the authoritative file listing matters.
    (public/'weekly-guides').mkdir();(public/'weekly-guides/manifest-v1.json').write_text('fallback')
    with pytest.raises(ValueError,match='initialize-empty'):m.existing_manifest(root,rows,verify,True)
    with pytest.raises(ValueError,match='target environment'):m.verified_live_snapshot(root,'production')
    (public/'multilingual-v5.json').write_bytes(b'tampered')
    with pytest.raises(ValueError,match='live receipt file mismatch'):m.verified_live_snapshot(root,'dev')


def test_no_silent_update_or_revocation(context,tmp_path):
    with pytest.raises(ValueError,match='previous entry hash and reason'):
        bind(context,[{'pageID':'sermon-8','week':8,'operation':'update'}])
    with pytest.raises(ValueError,match='previous entry hash and reason'):
        bind(context,[{'pageID':'sermon-8','week':8,'operation':'revoke','expectedEntrySha256':'a'*64}])
    with pytest.raises(ValueError,match='duplicate page and locale'):
        bind(context,[{'pageID':'sermon-8','week':8},{'pageID':'sermon-8','week':8}])


@pytest.mark.parametrize('field,value', [('englishSourcePackageJsonSha256','e'*64),('sourceMediaSha256','f'*64),('englishSourcePackageJsonSha256',None),('sourceMediaSha256',None)])
def test_self_consistent_v2_hashes_cannot_hide_source_join_mismatch(context,field,value):
    staging,snapshot,_,content,release,catalog=context;public=snapshot/'public'
    content[field]=value
    raw=text(public/'content/8.json',content);release['assets'][0]['sha256']=m.digest(raw)
    rr=text(public/'releases/8.json',release);catalog['pages'][0]['targets']['zh-Hans']['releasePackageJsonSha256']=m.digest(rr);text(public/'multilingual-v5.json',catalog)
    with pytest.raises(ValueError,match='content identity mismatch'):bind(context)


def test_legacy_v2_may_omit_top_level_source_hash_but_content_must_bind(context):
    staging,snapshot,_,content,release,catalog=context;public=snapshot/'public'
    release.pop('englishSourcePackageJsonSha256');rr=text(public/'releases/8.json',release)
    catalog['pages'][0]['targets']['zh-Hans']['releasePackageJsonSha256']=m.digest(rr);text(public/'multilingual-v5.json',catalog)
    assert bind(context)[0]['sourceIdentitySha256']=='a'*64
    release['englishSourcePackageJsonSha256']='e'*64;rr=text(public/'releases/8.json',release)
    catalog['pages'][0]['targets']['zh-Hans']['releasePackageJsonSha256']=m.digest(rr);text(public/'multilingual-v5.json',catalog)
    with pytest.raises(ValueError,match='release identity mismatch'):bind(context)
    release['schemaVersion']='sermon-target-language-release-package-v3';release.pop('englishSourcePackageJsonSha256');rr=text(public/'releases/8.json',release)
    catalog['pages'][0]['targets']['zh-Hans']['releasePackageJsonSha256']=m.digest(rr);text(public/'multilingual-v5.json',catalog)
    with pytest.raises(ValueError,match='release identity mismatch'):bind(context)


def test_guarded_hosting_candidate_preserves_snapshot_and_exposes_exact_client_schema(context,tmp_path,monkeypatch):
    from tongxing_production.delivery import baseline,contract
    staging,snapshot,expected,*_=context;public=snapshot/'public'
    text(public/'multilingual-v3.json',{'fixture':'old catalog'})
    text(snapshot/'firebase.json',{'hosting':{'site':baseline.hosting_target('dev')['site'],'public':'public'}})
    seal={**baseline.catalog_report(public),'files':baseline.files_report(public)};text(snapshot/'seal-report.json',seal)
    target=baseline.hosting_target('dev')
    rows=[{'path':r['path'],'rawBytes':r['bytes'],'rawSha256':r['sha256'],'managed':False} for r in seal['files']]
    receipt={'status':'complete_verified_not_deployed','environment':'dev','project':target['project'],
        'site':target['site'],'origin':target['origin'],'baselineVersion':f"sites/{target['site']}/versions/abc",
        'catalogSha256':seal['catalogSha256'],'firebaseJsonSha256':baseline.digest(snapshot/'firebase.json'),'rows':rows}
    text(snapshot/'baseline-receipt.json',receipt)
    checked=[];monkeypatch.setattr(contract,'validate_catalog_snapshot',lambda p:checked.append(Path(p)))
    out=tmp_path/'candidate'
    result=m.prepare_guarded_candidate(staging,snapshot,[{'week':8,'pageID':'sermon-8'}],expected,
        {'14:1':'Synthetic verse one','14:2':'Synthetic verse two'},out,'dev',True)
    assert len(checked)==2 and checked[0]==out and checked[1]==out
    for r in rows:
        assert (out/'public'/r['path'].lstrip('/')).read_bytes()==(public/r['path'].lstrip('/')).read_bytes()
    entry=result['entries'][0];assert entry['editionId']=='sermon-8' and entry['sourceIdentitySha256']=='a'*64
    assert entry['releasePackageJsonSha256']==json.loads((public/'multilingual-v5.json').read_bytes())['pages'][0]['targets']['zh-Hans']['releasePackageJsonSha256']
    raw=(out/'public'/entry['path'].lstrip('/')).read_bytes();assert len(raw)==entry['bytes'] and m.digest(raw)==entry['sha256']
    assert json.loads((out/'public/weekly-guides/manifest-v1.json').read_bytes())==result
    config=json.loads((out/'publish-config.json').read_bytes());assert config['baseline_version']==receipt['baselineVersion'] and config['intent']['origin']==target['origin']
    plan=json.loads((out/'weekly-guide-overlay-plan.json').read_bytes());assert plan['status']=='prepared_not_uploaded' and plan['liveRecheck']=='required_before_deploy'
    with pytest.raises(ValueError,match='unsafe candidate'):m.prepare_guarded_candidate(staging,snapshot,[],expected,{},out,'dev',True)


def prepare_snapshot_for_candidate(context,monkeypatch):
    from tongxing_production.delivery import baseline,contract
    staging,snapshot,expected,*_=context;public=snapshot/'public'
    text(public/'multilingual-v3.json',{'fixture':'old catalog'})
    text(snapshot/'firebase.json',{'hosting':{'site':baseline.hosting_target('dev')['site'],'public':'public'}})
    seal={**baseline.catalog_report(public),'files':baseline.files_report(public)};text(snapshot/'seal-report.json',seal)
    target=baseline.hosting_target('dev')
    rows=[{'path':r['path'],'rawBytes':r['bytes'],'rawSha256':r['sha256'],'managed':False} for r in seal['files']]
    receipt={'status':'complete_verified_not_deployed','environment':'dev','project':target['project'],
        'site':target['site'],'origin':target['origin'],'baselineVersion':f"sites/{target['site']}/versions/abc",
        'catalogSha256':seal['catalogSha256'],'firebaseJsonSha256':baseline.digest(snapshot/'firebase.json'),'rows':rows}
    text(snapshot/'baseline-receipt.json',receipt)
    monkeypatch.setattr(contract,'validate_catalog_snapshot',lambda _:None)
    return staging,snapshot,expected


@pytest.mark.parametrize('name',['firebase.json','baseline-receipt.json'])
def test_guarded_candidate_rejects_changed_copied_receipt_or_firebase(context,tmp_path,monkeypatch,name):
    staging,snapshot,expected=prepare_snapshot_for_candidate(context,monkeypatch)
    original=m.shutil.copyfile
    def mutate(src,dst,*args,**kwargs):
        result=original(src,dst,*args,**kwargs)
        if Path(src).name==name: Path(dst).write_bytes(b'tampered')
        return result
    monkeypatch.setattr(m.shutil,'copyfile',mutate)
    with pytest.raises(ValueError,match='copied receipt or Firebase config differs'):
        m.prepare_guarded_candidate(staging,snapshot,[],expected,{},tmp_path/'out','dev',True)


def test_candidate_binding_uses_frozen_copy_not_mutable_original(context,tmp_path,monkeypatch):
    staging,snapshot,expected=prepare_snapshot_for_candidate(context,monkeypatch)
    original=m.verified_bindings;original_catalog=(snapshot/'public/multilingual-v5.json').read_bytes()
    def race(staging_arg,snapshot_arg,*args,**kwargs):
        assert Path(snapshot_arg)==tmp_path/'out'
        (snapshot/'public/multilingual-v5.json').write_bytes(b'changed after copy')
        return original(staging_arg,snapshot_arg,*args,**kwargs)
    monkeypatch.setattr(m,'verified_bindings',race)
    result=m.prepare_guarded_candidate(staging,snapshot,[{'week':8,'pageID':'sermon-8'}],expected,
        {'14:1':'Synthetic verse one','14:2':'Synthetic verse two'},tmp_path/'out','dev',True)
    assert result['entries'][0]['pageID']=='sermon-8'
    assert (tmp_path/'out/public/multilingual-v5.json').read_bytes()==original_catalog


def test_v5_bundle_only_tombstone_requires_frozen_matching_identity(context,tmp_path):
    staging,snapshot,expected,_,_,catalog=context
    target=catalog['pages'][0]['targets']['zh-Hans']
    evidence={'v5':[{'pageID':'sermon-8','week':8,'locale':'zh-Hans','editionId':'sermon-8',
        'sourceIdentitySha256':'a'*64,'releasePackageJsonSha256':target['releasePackageJsonSha256']}],'legacy':[]}
    request=[{'pageID':'sermon-8','week':8,'operation':'revokeBundled','reason':'withdrawn'}]
    operations=m.verified_bindings(staging,snapshot,request,expected,{},bundle_evidence=evidence,verify_file=lambda _:b'')
    result=m.write_published(operations,tmp_path/'output',[],{})
    row=result['entries'][0]
    assert row['status']=='revoked' and row['editionId']=='sermon-8' and row['sourceIdentitySha256']=='a'*64
    assert 'path' not in row and 'sha256' not in row and 'bytes' not in row
    evidence['v5'][0]['sourceIdentitySha256']='b'*64
    with pytest.raises(ValueError,match='bundle identity differs'):m.verified_bindings(staging,snapshot,request,expected,{},bundle_evidence=evidence,verify_file=lambda _:b'')
    with pytest.raises(ValueError,match='evidence, live receipt, and reason'):m.verified_bindings(staging,snapshot,request,expected,{})


def test_legacy_bundle_only_tombstone_matches_complete_live_legacy_identity(context,tmp_path):
    staging,snapshot,expected,*_=context
    source={'id':'legacy-1','sourceId':'synthetic-source','sourceUrl':'https://example.invalid/source',
        'sourceSha256':'e'*64,'sourceStartSeconds':100,'sourceEndSeconds':200}
    frozen={'pageID':'legacy-1','week':1,'locale':'zh-Hans','sourceIdentityComplete':True,
        'sourceIdSHA256':m.digest(source['sourceId'].encode()),'sourceUrlSHA256':m.digest(source['sourceUrl'].encode()),
        'sourceMediaSHA256':source['sourceSha256'],'sourceStartSeconds':100,'sourceEndSeconds':200}
    evidence={'v5':[],'legacy':[frozen]};request=[{'pageID':'legacy-1','week':1,'operation':'revokeBundled','reason':'withdrawn'}]
    weekly=m.encoded({'weeks':[source]})
    operations=m.verified_bindings(staging,snapshot,request,expected,{},bundle_evidence=evidence,verify_file=lambda path: weekly if path=='/weekly.json' else b'')
    result=m.write_published(operations,tmp_path/'output',[],{});row=result['entries'][0]
    assert row['status']=='revoked' and row['legacy']['sourceMediaSHA256']=='e'*64
    assert 'editionId' not in row and 'path' not in row
    source['sourceEndSeconds']=201;weekly=m.encoded({'weeks':[source]})
    with pytest.raises(ValueError,match='legacy bundle identity differs'):m.verified_bindings(staging,snapshot,request,expected,{},bundle_evidence=evidence,verify_file=lambda _:weekly)
    frozen['sourceIdentityComplete']=False
    with pytest.raises(ValueError,match='incomplete frozen legacy identity'):m.verified_bindings(staging,snapshot,request,expected,{},bundle_evidence=evidence,verify_file=lambda _:weekly)


def test_existing_manifest_preserves_bundle_only_tombstones(tmp_path):
    legacy={'sourceIdSHA256':'a'*64,'sourceUrlSHA256':'b'*64,'sourceMediaSHA256':'c'*64,'sourceStartSeconds':1,'sourceEndSeconds':10}
    a={'pageID':'legacy','locale':'zh-Hans','week':1,'status':'revoked','legacy':legacy}
    b={'pageID':'v5','locale':'zh-Hans','week':3,'status':'revoked','editionId':'v5','sourceIdentitySha256':'d'*64,'releasePackageJsonSha256':'e'*64}
    manifest={'schemaVersion':'tongxing-weekly-guide-manifest-v1','seriesID':m.SERIES_ID,'translationSHA256':m.SOURCE_SHA256,
        'cuvSHA256':m.CUV_SHA256,'review':'machine_translation_not_human_reviewed','humanApproval':False,'entries':[a,b]}
    root=tmp_path/'snapshot';(root/'public/weekly-guides').mkdir(parents=True);(root/'public/weekly-guides/manifest-v1.json').write_bytes(m.encoded(manifest))
    entries,assets=m.existing_manifest(root,{'/weekly-guides/manifest-v1.json':{}},lambda _:m.encoded(manifest))
    assert entries==[a,b] and assets=={}
    result=m.write_published([],tmp_path/'out',entries,assets)
    assert result['entries']==[a,b]


def test_bundle_evidence_is_pinned_and_environment_scoped():
    from tongxing_production.delivery import baseline
    value={'schemaVersion':'tongxing-weekly-guide-identity-evidence-v1','environments':{
        'dev':{'origin':baseline.hosting_target('dev')['origin'],'v5':[],'legacy':[]}}}
    raw=m.encoded(value)
    assert m.validated_bundle_evidence(raw,'dev',m.digest(raw))['origin']==baseline.hosting_target('dev')['origin']
    with pytest.raises(ValueError,match='hash mismatch'):m.validated_bundle_evidence(raw,'dev','0'*64)
    with pytest.raises(ValueError,match='environment mismatch'):m.validated_bundle_evidence(raw,'production',m.digest(raw))


def test_legacy_missing_top_source_uses_only_matching_bound_fingerprint(context):
    staging,snapshot,expected,*_=context
    media='e'*64
    source={'id':'legacy-1','sourceId':'synthetic-source','sourceUrl':'https://example.invalid/source',
        'sourceStartSeconds':100,'sourceEndSeconds':200,
        'tracks':[{'sha256':'9'*64}],
        'audioFingerprint':{'schemaVersion':'sermon-audio-fingerprint-binding-v1','algorithmVersion':'spectral-landmarks-v1',
            'captureSeconds':10,'indexSha256':'7'*64,'indexUrl':'/fingerprints/'+('7'*16)+'-landmarks.json',
            'pageId':'legacy-1','sourceSha256':media,'trackSha256':'9'*64,'sourceStartSeconds':100,'sourceEndSeconds':200}}
    frozen={'pageID':'legacy-1','week':1,'locale':'zh-Hans','sourceIdentityComplete':True,
        'sourceIdSHA256':m.digest(source['sourceId'].encode()),'sourceUrlSHA256':m.digest(source['sourceUrl'].encode()),
        'sourceMediaSHA256':media,'sourceStartSeconds':100,'sourceEndSeconds':200}
    evidence={'v5':[],'legacy':[frozen]};request=[{'pageID':'legacy-1','week':1,'operation':'revokeBundled','reason':'withdrawn'}]
    def run():return m.verified_bindings(staging,snapshot,request,expected,{},bundle_evidence=evidence,verify_file=lambda _:m.encoded({'weeks':[source]}))
    assert run()[0]['tombstone']['legacy']['sourceMediaSHA256']==media
    source['audioFingerprint']['schemaVersion']='wrong'
    with pytest.raises(ValueError,match='fingerprint source binding mismatch'):run()
    source['audioFingerprint']['schemaVersion']='sermon-audio-fingerprint-binding-v1';source['audioFingerprint']['algorithmVersion']='wrong'
    with pytest.raises(ValueError,match='fingerprint source binding mismatch'):run()
    source['audioFingerprint']['algorithmVersion']='spectral-landmarks-v1';source['audioFingerprint']['indexUrl']='/wrong'
    with pytest.raises(ValueError,match='fingerprint source binding mismatch'):run()
    source['audioFingerprint']['indexUrl']='/fingerprints/'+('7'*16)+'-landmarks.json';source['audioFingerprint']['trackSha256']='8'*64
    with pytest.raises(ValueError,match='fingerprint source binding mismatch'):run()
    source['audioFingerprint']['trackSha256']='9'*64
    source['audioFingerprint']['pageId']='other'
    with pytest.raises(ValueError,match='fingerprint source binding mismatch'):run()
    source['audioFingerprint']['pageId']='legacy-1';source['audioFingerprint']['sourceStartSeconds']=101
    with pytest.raises(ValueError,match='fingerprint source binding mismatch'):run()
    source['audioFingerprint']['sourceStartSeconds']=100;source['audioFingerprint']['sourceEndSeconds']=201
    with pytest.raises(ValueError,match='fingerprint source binding mismatch'):run()
    source['audioFingerprint']['sourceEndSeconds']=200;source['sourceSha256']='f'*64
    with pytest.raises(ValueError,match='source hashes conflict'):run()
    source['sourceSha256']=media;assert run()[0]['tombstone']['legacy']['sourceMediaSHA256']==media


def test_v3_v4_bundle_alias_revocation_requires_both_verified_live_joins(context,tmp_path):
    staging,snapshot,expected,*_=context;identity='a'*64;media='d'*64;page='legacy-edition'
    content=m.encoded({'pageId':page,'targetLocale':'zh-Hans','englishSourcePackageJsonSha256':identity,'sourceMediaSha256':media})
    release=m.encoded({'schemaVersion':'sermon-target-language-release-package-v2','pageId':page,'targetLocale':'zh-Hans',
        'assets':[{'role':'content','path':'/content/legacy.json','sha256':m.digest(content)}]})
    target={'contentStatus':'human_reviewed','releasePackageUrl':'/releases/legacy.json','releasePackageJsonSha256':m.digest(release)}
    catalog=m.encoded({'pages':[{'id':page,'sourceIdentitySha256':identity,'sourceMediaSha256':media,'targets':{'zh-Hans':target}}]})
    row={'pageID':page,'week':6,'locale':'zh-Hans','status':'verified','editionId':page,
        'sourceIdentitySha256':identity,'sourceMediaSha256':media,'releasePackageJsonSha256':m.digest(release),
        'releaseReadbackSHA256':m.digest(release),'contentReadbackSHA256':m.digest(content),'contentIdentityMatches':True}
    aliases={'bundlePageIDs':{page:6},'catalogs':{v:{'rows':[dict(row)]} for v in ('v3','v4')}}
    files={'/multilingual-v3.json':catalog,'/multilingual-v4.json':catalog,'/releases/legacy.json':release,'/content/legacy.json':content}
    request=[{'pageID':page,'week':6,'operation':'revokeBundled','reason':'withdrawn'}]
    evidence={'v5':[],'legacy':[]}
    def verify(path):
        if path not in files:raise ValueError('not in verified receipt')
        return files[path]
    operations=m.verified_bindings(staging,snapshot,request,expected,{},bundle_evidence=evidence,verify_file=verify,alias_evidence=aliases)
    out=m.write_published(operations,tmp_path/'out',[],{})['entries'][0]
    assert out['status']=='revoked' and out['pageID']==page and out['editionId']==page and out['sourceIdentitySha256']==identity
    aliases['catalogs']['v4']['rows'][0]['sourceMediaSha256']='f'*64
    with pytest.raises(ValueError,match='alias identity differs'):m.verified_bindings(staging,snapshot,request,expected,{},bundle_evidence=evidence,verify_file=verify,alias_evidence=aliases)
    aliases['catalogs']['v4']['rows'][0]['sourceMediaSha256']=media;files['/content/legacy.json']=b'tampered'
    with pytest.raises(ValueError,match='alias content hash mismatch'):m.verified_bindings(staging,snapshot,request,expected,{},bundle_evidence=evidence,verify_file=verify,alias_evidence=aliases)


def test_alias_evidence_is_pinned_and_environment_scoped():
    from tongxing_production.delivery import baseline
    value={'schemaVersion':'tongxing-weekly-guide-legacy-alias-evidence-v1','bundleGuideSHA256':m.BUNDLE_GUIDE_SHA256,
      'bundlePageIDs':{'synthetic':6},'environments':{'dev':{'origin':baseline.hosting_target('dev')['origin'],'catalogs':{}}}}
    raw=m.encoded(value);assert m.validated_alias_evidence(raw,'dev',m.digest(raw))['bundlePageIDs']=={'synthetic':6}
    with pytest.raises(ValueError,match='hash mismatch'):m.validated_alias_evidence(raw,'dev','0'*64)
    with pytest.raises(ValueError,match='environment mismatch'):m.validated_alias_evidence(raw,'production',m.digest(raw))
