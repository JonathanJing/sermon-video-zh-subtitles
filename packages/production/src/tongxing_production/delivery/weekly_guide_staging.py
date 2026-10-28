"""Stage future weekly guides and bind only to verified sermon releases.

This preparation does not upload or publish anything. Source text stays in
ignored artifacts and is never included in test fixtures or Git.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import unicodedata

SOURCE_SHA256 = 'd6c6064e8fab11ab012edd9535372a9f99b83cd5240b6014f5451795a9198f86'
CUV_SHA256 = '363afb38148f150b30fee727f4818faa821a0d17b4888c16be3e05bd462503bb'
SERIES = '启示录：耶稣带来的安慰与盼望'
SERIES_ID = 'revelation-comfort-and-hope'
ORIGIN = 'https://www.flipsnack.com/57AF6AEEFB5/revelation-series-guide'
WEEKS = [
    dict(week=8,title='耶稣为属祂的人盖印',scripture='启示录 14 章',first=109,last=117,scripture_page=112,start='14:1',end='14:20',appendix=[171]),
    dict(week=9,title='耶稣是公义的，必使罪恶终结',scripture='启示录 15–16 章',first=119,last=129,scripture_page=120,start='15:1',end='16:21',appendix=[172]),
    dict(week=10,title='耶稣胜过这世界',scripture='启示录 17–19:10',first=131,last=143,scripture_page=132,start='17:1',end='19:10',appendix=[173]),
    dict(week=11,title='耶稣必再来',scripture='启示录 19:11–21:8',first=145,last=153,scripture_page=146,start='19:11',end='21:8',appendix=[174,175]),
    dict(week=12,title='耶稣将更新万有',scripture='启示录 21:9–22:21',first=155,last=161,scripture_page=156,start='21:9',end='22:21',appendix=[176]),
]
PAGE = re.compile(r'^## PAGE (\d+)（印刷页 (\d+)，id [^\n]+）\s*$', re.MULTILINE)
TABLE_SEP = re.compile(r'^:?-{3,}:?$')
HEX = re.compile(r'^[a-f0-9]{64}$')
PAGE_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$')
BUNDLE_EVIDENCE_SHA256 = '33300aab94e4c57ec66f39ba1efcd311478db0e1348b5690f68b36ba108f9e15'
ALIAS_EVIDENCE_SHA256 = 'ba582a43435ee7565a61210e041b7af7ab06d0d1024ad8aeba89d41b23a1a030'
BUNDLE_GUIDE_SHA256 = '99b494d5c52104df38e5a4be1a563b2905edd9cbe612209188ae2ea87ed860f2'
MANIFEST_LIMIT = 512 * 1024
GUIDE_LIMIT = 2 * 1024 * 1024


def digest(data): return hashlib.sha256(data).hexdigest()
def encoded(obj): return (json.dumps(obj,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
def verse_key(key):
    a,b=key.split(':'); return int(a),int(b)


def _cells(line):
    line=line.strip()
    if not (line.startswith('|') and line.endswith('|')): return None
    return [x.strip().replace(r'\|','|') for x in re.split(r'(?<!\\)\|',line[1:-1])]


def readable_tables(text):
    lines=text.split('\n'); out=[]; i=0
    while i<len(lines):
        headers=_cells(lines[i]); div=_cells(lines[i+1]) if i+1<len(lines) else None
        if not (headers and div and len(headers)>1 and len(headers)==len(div) and all(TABLE_SEP.fullmatch(x) for x in div)):
            out.append(lines[i]);i+=1;continue
        rows=[];j=i+2
        while j<len(lines):
            cells=_cells(lines[j])
            if cells is None or len(cells)!=len(headers): break
            rows.append(cells);j+=1
        if not rows: out.append('\n'.join(headers))
        else: out.append('\n\n'.join('\n'.join(f'{h}：{v}' if h else v for h,v in zip(headers,row)) for row in rows))
        i=j
    return '\n'.join(out)


def parse_pages(source):
    headings=list(PAGE.finditer(source));pages={}
    for i,m in enumerate(headings):
        n=int(m.group(1))
        if n in pages: raise ValueError(f'duplicate source page {n}')
        end=headings[i+1].start() if i+1<len(headings) else len(source)
        pages[n]=(int(m.group(2)),source[m.end():end].strip())
    return pages


def build_staged(source,cuv,weeks=WEEKS):
    pages=parse_pages(source);result=[]
    for w in weeks:
        sections=[]
        for n in [*range(w['first'],w['last']+1),*w['appendix']]:
            if n==w['scripture_page']:
                if w['start'] not in cuv or w['end'] not in cuv: raise ValueError('missing scripture boundary')
                keys=[k for k in sorted(cuv,key=verse_key) if verse_key(w['start'])<=verse_key(k)<=verse_key(w['end'])]
                sections.append({'id':'scripture-cuv1919','title':'完整经文 · 和合本（1919）',
                    'subtitle':'另附经文；并非手册原刊 CSB 译文','symbol':'book',
                    'body':'\n\n'.join(f'{k} {cuv[k]}' for k in keys)})
            if n not in pages or not pages[n][1]: raise ValueError(f'missing or empty source page {n}')
            printed,body=pages[n];is_appendix=n in w['appendix']
            sections.append({'id':f'page-{n}','title':f'{"附录 · " if is_appendix else ""}手册第 {printed} 页',
                'subtitle':f'原手册印刷页 {printed}','symbol':'doc.text','body':readable_tables(body)})
        result.append({'schemaVersion':'tongxing-weekly-guide-staging-v1','seriesID':SERIES_ID,
            'sermonPageId':None,'locale':'zh-Hans','week':w['week'],'title':w['title'],
            'scripture':w['scripture'],'sections':sections,'review':'machine_translation_not_human_reviewed',
            'humanApproval':False,'source':{'url':ORIGIN,'translationSHA256':SOURCE_SHA256,'cuvSHA256':CUV_SHA256,
                'pageRange':[w['first'],w['last']],'appendixPages':w['appendix']}})
    return result


def prepare_stage(source_bytes,cuv_bytes,out):
    if digest(source_bytes)!=SOURCE_SHA256 or digest(cuv_bytes)!=CUV_SHA256: raise ValueError('source hash mismatch')
    weeks=build_staged(source_bytes.decode('utf-8'),json.loads(cuv_bytes))
    return write_stage(weeks,out)


def write_stage(weeks,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=False);entries=[]
    for guide in weeks:
        if guide['sermonPageId'] is not None: raise ValueError('staged guide must be unbound')
        name=f"week-{guide['week']:02d}.json"; data=encoded(guide);(out/name).write_bytes(data)
        entries.append({'week':guide['week'],'file':name,'sha256':digest(data),'bytes':len(data),
            'sermonPageId':None,'locale':'zh-Hans','sourcePages':guide['source']['pageRange'],
            'appendixPages':guide['source']['appendixPages']})
    manifest={'schemaVersion':'tongxing-weekly-guide-staging-manifest-v1','seriesID':SERIES_ID,
      'translationSHA256':SOURCE_SHA256,'cuvSHA256':CUV_SHA256,
      'review':'machine_translation_not_human_reviewed','humanApproval':False,'entries':entries}
    (out/'staging-manifest.json').write_bytes(encoded(manifest));return manifest


def _norm(text):
    return ''.join(c for c in unicodedata.normalize('NFKC',str(text)).casefold() if c.isalnum())


def scripture_set(reference, cuv):
    """Parse explicit Revelation chapter/verse ranges using the verified verse IDs.

    Chapter ranges expand only to actual CUV IDs. Unknown or ambiguous forms
    fail closed; matching dates or titles alone never substitutes for scripture.
    """
    text=unicodedata.normalize('NFKC',str(reference)).strip()
    if not text.startswith('启示录'): raise ValueError('unsupported scripture book')
    text=re.sub(r'\s+','',text[len('启示录'):]).replace('第','')
    text=text.replace('—','-').replace('–','-').replace('~','-').replace('至','-')
    text=re.sub(r'(\d+)章(\d+)节?',r'\1:\2',text)
    text=text.replace('章','').replace('节','')
    if not re.fullmatch(r'\d+(?::\d+)?(?:-\d+(?::\d+)?)?',text): raise ValueError('unsupported scripture range')
    pieces=text.split('-'); first=pieces[0]; last=pieces[-1]
    def parts(value):
        a=value.split(':'); return int(a[0]),int(a[1]) if len(a)==2 else None
    start_ch,start_v=parts(first);end_ch,end_v=parts(last)
    # A trailing bare number after chapter:verse denotes another verse in
    # that chapter (14:1-20), not chapter 20.
    if len(pieces)==2 and ':' in first and ':' not in last:
        end_ch,end_v=start_ch,int(last)
    chapters={verse_key(k)[0] for k in cuv}
    if start_ch not in chapters or end_ch not in chapters: raise ValueError('unknown scripture chapter')
    start=(start_ch,1 if start_v is None else start_v)
    end=(end_ch,end_v if end_v is not None else max(verse_key(k)[1] for k in cuv if verse_key(k)[0]==end_ch))
    if start>end or f'{start[0]}:{start[1]}' not in cuv or f'{end[0]}:{end[1]}' not in cuv: raise ValueError('invalid scripture boundaries')
    return frozenset(k for k in cuv if start<=verse_key(k)<=end)


def _safe_asset(public,path):
    if not isinstance(path,str) or not path.startswith('/') or path.startswith('//') or '?' in path or '#' in path: raise ValueError('unsafe asset path')
    file=(public/path.lstrip('/')).resolve()
    if not file.is_relative_to(public.resolve()) or not file.is_file(): raise ValueError('asset missing or escapes snapshot')
    return file


def verified_live_snapshot(snapshot,environment):
    """Verify local snapshot against a Hosting live-file receipt, not SPA HTTP 200.

    This is a captured baseline only. Publisher must recheck live version before
    deployment. No source SHA can authenticate a malicious serving host.
    """
    from tongxing_production.delivery import baseline, contract
    from tongxing_production.delivery.single_source_dev_overlay import verify_live_baseline
    snapshot=Path(snapshot); public=(snapshot/'public').resolve()
    receipt=json.loads((snapshot/'baseline-receipt.json').read_bytes())
    target=baseline.hosting_target(environment)
    if (receipt.get('status')!='complete_verified_not_deployed'
        or any(receipt.get(k)!=target[k] for k in ('project','site','origin'))
        or receipt.get('environment')!=environment
        or not str(receipt.get('baselineVersion','')).startswith(f"sites/{target['site']}/versions/")):
        raise ValueError('verified live baseline for target environment required')
    rows=receipt.get('rows')
    if not isinstance(rows,list): raise ValueError('baseline live file list missing')
    paths=[r.get('path') for r in rows]
    if len(paths)!=len(set(paths)): raise ValueError('duplicate live receipt paths')
    indexed={r['path']:r for r in rows}
    def verify_file(path):
        r=indexed.get(path)
        if not r or r.get('managed') is True: raise ValueError('file absent from verified live baseline')
        raw=_safe_asset(public,path).read_bytes()
        if len(raw)!=r.get('rawBytes') or digest(raw)!=r.get('rawSha256'): raise ValueError('live receipt file mismatch')
        return raw
    verify_file('/multilingual-v5.json')
    verify_live_baseline(snapshot,receipt)
    contract.validate_catalog_snapshot(snapshot)
    return indexed,verify_file,receipt


def _target_identity(catalog,page_id):
    pages=[p for p in catalog['pages'] if p.get('id')==page_id]
    if len(pages)!=1: raise ValueError('page not unique in v5 catalog')
    page=pages[0];target=page.get('targets',{}).get('zh-Hans')
    if any(page.get(k) is True for k in ('simulationOnly','diagnosticOnly','revoked','withdrawn')) or page.get('status') in ('revoked','withdrawn'):
        raise ValueError('page is diagnostic, simulated, or withdrawn')
    if (not target or target.get('contentStatus') not in ('human_reviewed','machine_checked')
        or any(target.get(k) is True for k in ('simulationOnly','diagnosticOnly','revoked','withdrawn'))
        or target.get('status') in ('revoked','withdrawn')): raise ValueError('published Chinese target required')
    edition=target.get('editionId',page_id)
    identity=target.get('sourceIdentitySha256') if page.get('sourceMode')=='per_target' else page.get('sourceIdentitySha256')
    release_sha=target.get('releasePackageJsonSha256')
    if not isinstance(edition,str) or not PAGE_ID.fullmatch(edition) or not isinstance(identity,str) or not HEX.fullmatch(identity) or not isinstance(release_sha,str) or not HEX.fullmatch(release_sha):
        raise ValueError('verified source and release identity required')
    return page,target,edition,identity,release_sha



def validated_bundle_evidence(data,environment,expected_sha=BUNDLE_EVIDENCE_SHA256):
    from tongxing_production.delivery import baseline
    if digest(data)!=expected_sha: raise ValueError('frozen bundle evidence hash mismatch')
    evidence=json.loads(data)
    if evidence.get('schemaVersion')!='tongxing-weekly-guide-identity-evidence-v1': raise ValueError('invalid bundle evidence')
    env=evidence.get('environments',{}).get(environment)
    if not isinstance(env,dict) or env.get('origin')!=baseline.hosting_target(environment)['origin']:
        raise ValueError('bundle evidence environment mismatch')
    return env



def validated_alias_evidence(data,environment,expected_sha=ALIAS_EVIDENCE_SHA256):
    from tongxing_production.delivery import baseline
    if digest(data)!=expected_sha: raise ValueError('frozen alias evidence hash mismatch')
    evidence=json.loads(data)
    if evidence.get('schemaVersion')!='tongxing-weekly-guide-legacy-alias-evidence-v1' or evidence.get('bundleGuideSHA256')!=BUNDLE_GUIDE_SHA256:
        raise ValueError('invalid alias evidence')
    env=evidence.get('environments',{}).get(environment)
    if not isinstance(env,dict) or env.get('origin')!=baseline.hosting_target(environment)['origin']:
        raise ValueError('alias evidence environment mismatch')
    return {'bundlePageIDs':evidence.get('bundlePageIDs',{}),'catalogs':env.get('catalogs',{})}


def alias_tombstone(binding,evidence,verify_file):
    """Accept an exact frozen v3/v4 bundle alias only after live identity joins."""
    page_id=binding['pageID'];week=binding['week']
    if evidence.get('bundlePageIDs',{}).get(page_id)!=week: raise ValueError('alias absent from accepted bundle')
    identities=[]
    for version in ('v3','v4'):
        frozen_catalog=evidence.get('catalogs',{}).get(version,{})
        rows=[r for r in frozen_catalog.get('rows',[]) if r.get('pageID')==page_id and r.get('week')==week and r.get('locale')=='zh-Hans' and r.get('status')=='verified']
        if len(rows)!=1: raise ValueError('unique frozen alias evidence required')
        frozen=rows[0]
        catalog=json.loads(verify_file(f'/multilingual-{version}.json'))
        page,target,edition,identity,release_sha=_target_identity(catalog,page_id)
        media=page.get('sourceMediaSha256')
        if (frozen.get('editionId')!=edition or frozen.get('sourceIdentitySha256')!=identity
            or frozen.get('sourceMediaSha256')!=media or frozen.get('releasePackageJsonSha256')!=release_sha
            or frozen.get('releaseReadbackSHA256')!=release_sha or frozen.get('contentIdentityMatches') is not True):
            raise ValueError('alias identity differs from live catalog')
        release_raw=verify_file(target['releasePackageUrl'])
        if digest(release_raw)!=release_sha: raise ValueError('alias release hash mismatch')
        release=json.loads(release_raw)
        if release.get('pageId')!=edition or release.get('targetLocale')!='zh-Hans': raise ValueError('alias release identity mismatch')
        release_identity=release.get('englishSourcePackageJsonSha256')
        schema=release.get('schemaVersion')
        if schema=='sermon-target-language-release-package-v2':
            if release_identity is not None and release_identity!=identity: raise ValueError('alias release source mismatch')
        elif schema in ('sermon-target-language-release-package-v3','sermon-target-language-release-package-v4'):
            if release_identity!=identity: raise ValueError('alias release source mismatch')
        else: raise ValueError('unsupported alias release schema')
        assets=[a for a in release.get('assets',[]) if a.get('role')=='content']
        if len(assets)!=1: raise ValueError('unique alias content required')
        content_raw=verify_file(assets[0].get('path'))
        if digest(content_raw)!=assets[0].get('sha256') or digest(content_raw)!=frozen.get('contentReadbackSHA256'):
            raise ValueError('alias content hash mismatch')
        content=json.loads(content_raw)
        if (content.get('pageId')!=edition or content.get('targetLocale')!='zh-Hans'
            or content.get('englishSourcePackageJsonSha256')!=identity or content.get('sourceMediaSha256')!=media):
            raise ValueError('alias content source mismatch')
        identities.append((edition,identity,release_sha))
    if identities[0]!=identities[1]: raise ValueError('v3/v4 alias identities differ')
    edition,identity,release_sha=identities[0]
    return {'pageID':page_id,'locale':'zh-Hans','week':week,'status':'revoked',
        'editionId':edition,'sourceIdentitySha256':identity,'releasePackageJsonSha256':release_sha}

def bundled_tombstone(binding,catalog,evidence,verify_file,alias_evidence=None):
    page_id=binding['pageID'];week=binding['week']
    matches=[v for group in ('v5','legacy') for v in evidence.get(group,[])
             if v.get('pageID')==page_id and v.get('week')==week and v.get('locale')=='zh-Hans']
    if not matches and alias_evidence is not None:
        return alias_tombstone(binding,alias_evidence,verify_file)
    if len(matches)!=1: raise ValueError('unique frozen bundle identity required')
    frozen=matches[0]
    common={'pageID':page_id,'locale':'zh-Hans','week':week,'status':'revoked'}
    if 'editionId' in frozen:
        _,_,edition,identity,release_sha=_target_identity(catalog,page_id)
        if (frozen.get('editionId')!=edition or frozen.get('sourceIdentitySha256')!=identity
            or frozen.get('releasePackageJsonSha256')!=release_sha): raise ValueError('v5 bundle identity differs from live catalog')
        return {**common,'editionId':edition,'sourceIdentitySha256':identity,'releasePackageJsonSha256':release_sha}
    if frozen.get('sourceIdentityComplete') is not True: raise ValueError('incomplete frozen legacy identity')
    weekly=json.loads(verify_file('/weekly.json'))
    matches=[w for w in weekly.get('weeks',[]) if w.get('id')==page_id]
    if len(matches)!=1: raise ValueError('unique live legacy identity required')
    source=matches[0]
    if not isinstance(source.get('sourceId'),str) or not isinstance(source.get('sourceUrl'),str):
        raise ValueError('legacy source fields missing')
    top_sha=source.get('sourceSha256'); fingerprint=source.get('audioFingerprint')
    # Legacy records may omit top-level sourceSha256 while their fingerprint
    # supplies it. Accept only a complete fingerprint bound to this exact page
    # and source window; never silently prefer one conflicting identity.
    if fingerprint is not None:
        tracks=source.get('tracks')
        index_sha=fingerprint.get('indexSha256') if isinstance(fingerprint,dict) else None
        if (not isinstance(fingerprint,dict) or fingerprint.get('schemaVersion')!='sermon-audio-fingerprint-binding-v1'
            or fingerprint.get('algorithmVersion')!='spectral-landmarks-v1' or fingerprint.get('captureSeconds')!=10
            or not isinstance(index_sha,str) or not HEX.fullmatch(index_sha)
            or fingerprint.get('indexUrl')!=f'/fingerprints/{index_sha[:16]}-landmarks.json'
            or fingerprint.get('pageId')!=page_id or not isinstance(tracks,list)
            or not isinstance(fingerprint.get('trackSha256'),str) or not HEX.fullmatch(fingerprint['trackSha256'])
            or not any(isinstance(track,dict) and track.get('sha256')==fingerprint['trackSha256'] for track in tracks)
            or fingerprint.get('sourceStartSeconds')!=source.get('sourceStartSeconds')
            or fingerprint.get('sourceEndSeconds')!=source.get('sourceEndSeconds')
            or not isinstance(fingerprint.get('sourceSha256'),str) or not HEX.fullmatch(fingerprint['sourceSha256'])):
            raise ValueError('legacy fingerprint source binding mismatch')
        if top_sha is not None and top_sha!=fingerprint['sourceSha256']:
            raise ValueError('legacy source hashes conflict')
        media_sha=fingerprint['sourceSha256'] if top_sha is None else top_sha
    else: media_sha=top_sha
    legacy={'sourceIdSHA256':digest(source['sourceId'].encode()),'sourceUrlSHA256':digest(source['sourceUrl'].encode()),
        'sourceMediaSHA256':media_sha,'sourceStartSeconds':source.get('sourceStartSeconds'),
        'sourceEndSeconds':source.get('sourceEndSeconds')}
    if any(legacy[k]!=frozen.get(k) for k in legacy): raise ValueError('legacy bundle identity differs from live weekly catalog')
    if any(not isinstance(legacy[k],str) or not HEX.fullmatch(legacy[k]) for k in ('sourceIdSHA256','sourceUrlSHA256','sourceMediaSHA256')):
        raise ValueError('invalid legacy source hashes')
    a,b=legacy['sourceStartSeconds'],legacy['sourceEndSeconds']
    if any(not isinstance(x,(int,float)) or isinstance(x,bool) or not math.isfinite(x) for x in (a,b)) or a<0 or not 7<=b-a<=14400:
        raise ValueError('invalid legacy source window')
    return {**common,'legacy':legacy}

def verified_bindings(staging,snapshot,bindings,expected_staging,cuv,*,bundle_evidence=None,verify_file=None,alias_evidence=None):
    """Bind only to validated v5 Chinese releases. Date alone is insufficient."""
    staging=Path(staging);snapshot=Path(snapshot); public=(snapshot/'public').resolve()
    catalog=json.loads((public/'multilingual-v5.json').read_bytes())
    if catalog.get('schemaVersion')!='sermon-multilingual-catalog-v5': raise ValueError('v5 catalog required')
    manifest=json.loads((staging/'staging-manifest.json').read_bytes())
    if manifest.get('schemaVersion')!='tongxing-weekly-guide-staging-manifest-v1': raise ValueError('invalid staging manifest')
    entries=manifest.get('entries')
    if not isinstance(entries,list) or len({e.get('week') for e in entries})!=len(entries): raise ValueError('duplicate or invalid staged weeks')
    if (manifest.get('seriesID')!=SERIES_ID or manifest.get('translationSHA256')!=SOURCE_SHA256
        or manifest.get('cuvSHA256')!=CUV_SHA256 or manifest.get('humanApproval') is not False): raise ValueError('staging provenance mismatch')
    staged={e['week']:e for e in entries};result=[];seen=set()
    for binding in bindings:
        page_id=binding.get('pageID');week=binding.get('week');operation=binding.get('operation','add')
        if not isinstance(page_id,str) or not PAGE_ID.fullmatch(page_id) or not isinstance(week,int): raise ValueError('invalid explicit binding')
        if page_id in seen: raise ValueError('duplicate page and locale')
        if operation not in ('add','update','revoke','revokeBundled'): raise ValueError('unsupported binding operation')
        if operation in ('update','revoke') and (not HEX.fullmatch(str(binding.get('expectedEntrySha256',''))) or not str(binding.get('reason','')).strip()):
            raise ValueError('explicit previous entry hash and reason required')
        seen.add(page_id)
        if operation=='revokeBundled':
            if not str(binding.get('reason','')).strip() or bundle_evidence is None or verify_file is None:
                raise ValueError('verified bundle evidence, live receipt, and reason required')
            tombstone=bundled_tombstone(binding,catalog,bundle_evidence,verify_file,alias_evidence)
            result.append({'pageID':page_id,'week':week,'operation':operation,'reason':binding['reason'],'tombstone':tombstone});continue
        if operation=='revoke':
            result.append({'pageID':page_id,'week':week,'operation':operation,'expectedEntrySha256':binding['expectedEntrySha256'],'reason':binding['reason']});continue
        row=staged.get(week)
        if not row or row.get('sermonPageId') is not None: raise ValueError('week not staged or already bound')
        raw=_safe_asset(staging.resolve(),'/'+row['file']).read_bytes()
        if len(raw)!=row['bytes'] or digest(raw)!=row['sha256']: raise ValueError('staged file mismatch')
        if expected_staging.get(week)!=raw: raise ValueError('staged content differs from verified sources')
        guide=json.loads(raw)
        if guide.get('sermonPageId') is not None or guide.get('week')!=week or guide.get('locale')!='zh-Hans': raise ValueError('staged identity mismatch')
        page,target,edition,identity,release_sha=_target_identity(catalog,page_id)
        release_raw=_safe_asset(public,target.get('releasePackageUrl')).read_bytes()
        if digest(release_raw)!=release_sha: raise ValueError('release hash mismatch')
        release=json.loads(release_raw)
        release_schema=release.get('schemaVersion')
        if release.get('pageId')!=edition or release.get('targetLocale')!='zh-Hans': raise ValueError('release identity mismatch')
        # Legacy v2 does not require a top-level source hash. When present it
        # must still match; v3/v4 require it. Content always binds both hashes.
        release_identity=release.get('englishSourcePackageJsonSha256')
        if release_schema=='sermon-target-language-release-package-v2':
            if release_identity is not None and release_identity!=identity: raise ValueError('release identity mismatch')
        elif release_schema in ('sermon-target-language-release-package-v3','sermon-target-language-release-package-v4'):
            if release_identity!=identity: raise ValueError('release identity mismatch')
        else: raise ValueError('unsupported release schema')
        media=target.get('sourceMediaSha256') if page.get('sourceMode')=='per_target' else page.get('sourceMediaSha256')
        if not isinstance(media,str) or not HEX.fullmatch(media): raise ValueError('source media identity missing')
        release_source=release.get('sourceIdentity')
        if release_source is not None and (not isinstance(release_source,dict) or release_source.get('mediaSha256')!=media):
            raise ValueError('release source media mismatch')
        assets=[a for a in release.get('assets',[]) if a.get('role')=='content']
        if len(assets)!=1: raise ValueError('unique content asset required')
        content_raw=_safe_asset(public,assets[0].get('path')).read_bytes()
        if digest(content_raw)!=assets[0].get('sha256'): raise ValueError('content hash mismatch')
        content=json.loads(content_raw)
        if (content.get('pageId')!=edition or content.get('targetLocale')!='zh-Hans'
            or content.get('englishSourcePackageJsonSha256')!=identity or content.get('sourceMediaSha256')!=media):
            raise ValueError('content identity mismatch')
        if _norm(content.get('series',''))!=_norm(SERIES): raise ValueError('series mismatch')
        # Exact title, optionally followed by the same scripture; excludes
        # similarly named supplemental podcast episodes.
        actual_title=str(content.get('title',''));expected_title=_norm(guide['title'])
        title_parts=re.split(r'\s*[·•]\s*',actual_title)
        if len(title_parts)>2 or _norm(title_parts[0])!=expected_title: raise ValueError('title mismatch')
        guide_verses=scripture_set(guide['scripture'],cuv)
        if len(title_parts)==2 and scripture_set(title_parts[1],cuv)!=guide_verses: raise ValueError('title scripture mismatch')
        if guide_verses!=scripture_set(content.get('scripture',''),cuv): raise ValueError('scripture mismatch')
        item={'pageID':page_id,'week':week,'operation':operation,'editionId':edition,'sourceIdentitySha256':identity,
              'releasePackageJsonSha256':release_sha,'guide':{'id':page_id, **{k:guide[k] for k in ('week','title','scripture','sections')}}}
        if operation=='update': item.update(expectedEntrySha256=binding['expectedEntrySha256'],reason=binding['reason'])
        result.append(item)
    return result


def existing_manifest(snapshot,rows,verify_file,initialize_empty=False):
    path='/weekly-guides/manifest-v1.json'; public=Path(snapshot)/'public'; row=rows.get(path)
    if row is None:
        if not initialize_empty or (public/'weekly-guides/manifest-v1.json').exists(): raise ValueError('live manifest absent; explicit initialize-empty required')
        return [],{}
    if initialize_empty: raise ValueError('refusing to initialize over existing manifest')
    manifest_raw=verify_file(path)
    if len(manifest_raw)>MANIFEST_LIMIT: raise ValueError('existing manifest exceeds client limit')
    data=json.loads(manifest_raw)
    if (data.get('schemaVersion')!='tongxing-weekly-guide-manifest-v1' or data.get('seriesID')!=SERIES_ID or data.get('translationSHA256')!=SOURCE_SHA256
        or data.get('cuvSHA256')!=CUV_SHA256 or data.get('review')!='machine_translation_not_human_reviewed'
        or data.get('humanApproval') is not False or not isinstance(data.get('entries'),list)): raise ValueError('existing manifest provenance mismatch')
    entries=data['entries'];keys=set();assets={}
    for e in entries:
        page=e.get('pageID');sha=e.get('sha256');size=e.get('bytes')
        if (not isinstance(page,str) or not PAGE_ID.fullmatch(page) or e.get('locale')!='zh-Hans'
            or (page,e['locale']) in keys or not isinstance(e.get('week'),int) or isinstance(e.get('week'),bool) or e['week']<1
            or e.get('status') not in ('available','revoked')):
            raise ValueError('invalid or duplicate existing manifest entry')
        keys.add((page,e['locale']))
        legacy=e.get('legacy')
        if legacy is not None:
            if (e['status']!='revoked' or not isinstance(legacy,dict)
                or any(e.get(k) is not None for k in ('editionId','sourceIdentitySha256','releasePackageJsonSha256','path','sha256','bytes'))
                or any(not isinstance(legacy.get(k),str) or not HEX.fullmatch(legacy[k]) for k in ('sourceIdSHA256','sourceUrlSHA256','sourceMediaSHA256'))):
                raise ValueError('invalid legacy tombstone')
            a,b=legacy.get('sourceStartSeconds'),legacy.get('sourceEndSeconds')
            if any(not isinstance(x,(int,float)) or isinstance(x,bool) or not math.isfinite(x) for x in (a,b)) or a<0 or not 7<=b-a<=14400: raise ValueError('invalid legacy source window')
            continue
        if (not isinstance(e.get('editionId'),str) or not PAGE_ID.fullmatch(e['editionId'])
            or any(not isinstance(e.get(k),str) or not HEX.fullmatch(e[k]) for k in ('sourceIdentitySha256','releasePackageJsonSha256'))):
            raise ValueError('invalid v5 manifest identity')
        if e['status']=='revoked' and all(e.get(k) is None for k in ('path','sha256','bytes')): continue
        if (not isinstance(sha,str) or not HEX.fullmatch(sha) or not isinstance(size,int) or isinstance(size,bool) or size<=0 or size>GUIDE_LIMIT
            or e.get('path')!=f'/weekly-guides/published/{sha}.json'):
            raise ValueError('invalid existing guide resource')
        raw=verify_file(e['path'])
        if len(raw)!=size or digest(raw)!=sha: raise ValueError('existing guide asset mismatch')
        content=json.loads(raw)
        if content.get('id')!=page or content.get('week')!=e['week']: raise ValueError('existing guide identity mismatch')
        assets[e['path']]=raw
    return entries,assets


def write_published(operations,out,existing,assets,*,allow_initial_empty=False):
    # Verify everything before creating any output or preserving existing items.
    entries=[dict(e) for e in existing]; blobs=dict(assets)
    by_page={e['pageID']:e for e in entries}
    if len(by_page)!=len(entries): raise ValueError('duplicate existing page')
    seen=set()
    for operation in operations:
        page=operation['pageID'];kind=operation['operation'];week=operation['week']
        if not isinstance(page,str) or not PAGE_ID.fullmatch(page) or kind not in ('add','update','revoke','revokeBundled') or not isinstance(week,int) or isinstance(week,bool) or week<1:
            raise ValueError('invalid page operation')
        if page in seen: raise ValueError('duplicate page operation')
        seen.add(page); prior=by_page.get(page)
        if kind in ('add','revokeBundled') and prior: raise ValueError('duplicate existing page')
        if kind in ('update','revoke'):
            if not prior or digest(encoded(prior))!=operation.get('expectedEntrySha256') or prior['week']!=week:
                raise ValueError('previous entry identity changed')
            if not str(operation.get('reason','')).strip(): raise ValueError('update/revoke reason required')
        if kind=='revokeBundled':
            revised=operation['tombstone']
            if revised.get('pageID')!=page or revised.get('week')!=week or revised.get('locale')!='zh-Hans' or revised.get('status')!='revoked' or not str(operation.get('reason','')).strip():
                raise ValueError('invalid bundled tombstone')
        elif kind=='revoke':
            if prior['status']=='revoked': raise ValueError('entry already revoked')
            revised={**prior,'status':'revoked'}
        else:
            guide=operation['guide']
            if guide.get('id')!=page or guide.get('week')!=week or not isinstance(guide.get('sections'),list) or not guide['sections']:
                raise ValueError('new guide identity mismatch')
            if not isinstance(operation.get('editionId'),str) or not PAGE_ID.fullmatch(operation['editionId']) or any(not isinstance(operation.get(k),str) or not HEX.fullmatch(operation[k]) for k in ('sourceIdentitySha256','releasePackageJsonSha256')):
                raise ValueError('new guide source identity mismatch')
            raw=encoded(guide)
            if len(raw)>GUIDE_LIMIT: raise ValueError('guide exceeds client limit')
            sha=digest(raw);path=f'/weekly-guides/published/{sha}.json';blobs[path]=raw
            revised={'pageID':page,'locale':'zh-Hans','week':week,'editionId':operation['editionId'],
              'sourceIdentitySha256':operation['sourceIdentitySha256'],'releasePackageJsonSha256':operation['releasePackageJsonSha256'],
              'status':'available','path':path,'sha256':sha,'bytes':len(raw)}
        if prior: entries[entries.index(prior)]=revised
        else: entries.append(revised)
        by_page[page]=revised
    if not entries and not allow_initial_empty: raise ValueError('refusing to create an empty manifest')
    result={'schemaVersion':'tongxing-weekly-guide-manifest-v1','seriesID':SERIES_ID,'translationSHA256':SOURCE_SHA256,
        'cuvSHA256':CUV_SHA256,'review':'machine_translation_not_human_reviewed','humanApproval':False,'entries':entries}
    manifest_raw=encoded(result)
    if len(manifest_raw)>MANIFEST_LIMIT: raise ValueError('manifest exceeds client limit')
    out=Path(out);out.mkdir(parents=True,exist_ok=False);(out/'published').mkdir()
    # Retain old immutable bytes even when an entry is updated or revoked.
    for path,raw in blobs.items(): (out/'published'/Path(path).name).write_bytes(raw)
    (out/'manifest-v1.json').write_bytes(manifest_raw);return result



def prepare_guarded_candidate(staging,snapshot,bindings,expected_staging,cuv,out,environment,initialize_empty=False,bundle_evidence_bytes=None,alias_evidence_bytes=None):
    """Prepare a fresh guarded Hosting snapshot; never deploy or overwrite live data.

    Copy first, then bind from the frozen copy: the live receipt is the authority
    for all copied public bytes. Freeze the receipt/config themselves to prevent
    a local swap from altering the candidate's baseline identity.
    """
    from tongxing_production.delivery import baseline,contract
    snapshot=Path(snapshot).resolve();staging=Path(staging).resolve();out=Path(out).resolve()
    if out.exists() or out==snapshot or out==staging or out.is_relative_to(snapshot) or snapshot.is_relative_to(out) or out.is_relative_to(staging) or staging.is_relative_to(out):
        raise ValueError('unsafe candidate output location')
    receipt_bytes=(snapshot/'baseline-receipt.json').read_bytes()
    firebase_bytes=(snapshot/'firebase.json').read_bytes()
    frozen_receipt=json.loads(receipt_bytes)
    if digest(firebase_bytes)!=frozen_receipt.get('firebaseJsonSha256'): raise ValueError('baseline Firebase config differs from frozen receipt')
    out.mkdir(parents=True,exist_ok=False)
    shutil.copytree(snapshot/'public',out/'public')
    shutil.copyfile(snapshot/'firebase.json',out/'firebase.json')
    shutil.copyfile(snapshot/'baseline-receipt.json',out/'baseline-receipt.json')
    shutil.copyfile(snapshot/'seal-report.json',out/'seal-report.json')
    if (out/'baseline-receipt.json').read_bytes()!=receipt_bytes or (out/'firebase.json').read_bytes()!=firebase_bytes:
        raise ValueError('copied receipt or Firebase config differs from frozen bytes')
    # This verifies copied v5, complete sealed file list, environment, and
    # receipt; bind below never reads mutable snapshot files.
    rows,verify_file,receipt=verified_live_snapshot(out,environment)
    if receipt!=frozen_receipt: raise ValueError('copied receipt identity changed')
    for path,row in rows.items():
        if row.get('managed') is True: continue
        raw=_safe_asset(out/'public',path).read_bytes()
        if len(raw)!=row.get('rawBytes') or digest(raw)!=row.get('rawSha256'): raise ValueError('copied baseline differs from live receipt')
    old,assets=existing_manifest(out,rows,verify_file,initialize_empty)
    bundle_evidence=validated_bundle_evidence(bundle_evidence_bytes,environment) if bundle_evidence_bytes is not None else None
    alias_evidence=validated_alias_evidence(alias_evidence_bytes,environment) if alias_evidence_bytes is not None else None
    operations=verified_bindings(staging,out,bindings,expected_staging,cuv,bundle_evidence=bundle_evidence,verify_file=verify_file,alias_evidence=alias_evidence)
    fragment=out/'guide-fragment'
    manifest=write_published(operations,fragment,old,assets,allow_initial_empty=initialize_empty)
    public=out/'public';dest=public/'weekly-guides';dest.mkdir(parents=True,exist_ok=True)
    published=dest/'published';published.mkdir(parents=True,exist_ok=True)
    for source in sorted((fragment/'published').glob('*.json')):
        target=published/source.name
        if target.exists() and target.read_bytes()!=source.read_bytes(): raise ValueError('immutable guide collision')
        if not target.exists(): shutil.copyfile(source,target)
    shutil.copyfile(fragment/'manifest-v1.json',dest/'manifest-v1.json')
    new_seal=out/'seal-report.next.json'
    baseline.write(new_seal,{**baseline.catalog_report(public),'files':baseline.files_report(public)})
    new_seal.replace(out/'seal-report.json')
    contract.validate_catalog_snapshot(out)
    # Read the candidate's frozen receipt/config/catalog instead of the mutable
    # source snapshot while constructing the guarded deployment config.
    config=baseline.publication_config(out,out,environment=environment)
    if config.get('baseline_version')!=frozen_receipt.get('baselineVersion') or config.get('baseline_catalog_sha')!=frozen_receipt.get('catalogSha256'):
        raise ValueError('guarded config differs from frozen baseline')
    baseline.write(out/'publish-config.json',config)
    baseline.write(out/'weekly-guide-overlay-plan.json',{'schemaVersion':'tongxing-weekly-guide-overlay-plan-v1',
        'status':'prepared_not_uploaded','environment':environment,'baselineVersion':receipt['baselineVersion'],
        'manifestSHA256':digest((dest/'manifest-v1.json').read_bytes()),'entryCount':len(manifest['entries']),
        'liveRecheck':'required_before_deploy','clientAcceptance':'not_run'})
    return manifest


def safe_output(path):
    root=Path(__file__).resolve().parents[5];target=Path(path).resolve()
    if not target.is_relative_to((root/'artifacts').resolve()) or target==(root/'artifacts').resolve():
        raise ValueError('output must be a fresh path within ignored artifacts')
    return target


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    s=sub.add_parser('stage');s.add_argument('--source',required=True,type=Path);s.add_argument('--cuv',required=True,type=Path);s.add_argument('--output',required=True,type=Path)
    b=sub.add_parser('bind', aliases=['candidate']);b.add_argument('--staging',required=True,type=Path);b.add_argument('--snapshot',required=True,type=Path);b.add_argument('--environment',required=True,choices=['dev','production']);b.add_argument('--initialize-empty',action='store_true');b.add_argument('--bundle-evidence',type=Path);b.add_argument('--alias-evidence',type=Path);b.add_argument('--bindings',required=True,type=Path);b.add_argument('--source',required=True,type=Path);b.add_argument('--cuv',required=True,type=Path);b.add_argument('--output',required=True,type=Path)
    a=p.parse_args(argv)
    if a.action=='stage': result=prepare_stage(a.source.read_bytes(),a.cuv.read_bytes(),safe_output(a.output))
    else:
        binding=json.loads(a.bindings.read_text())
        if binding.get('schemaVersion')!='tongxing-weekly-guide-bindings-v1' or not isinstance(binding.get('bindings'),list): raise ValueError('invalid bindings schema')
        source=a.source.read_bytes();cuv=a.cuv.read_bytes()
        if digest(source)!=SOURCE_SHA256 or digest(cuv)!=CUV_SHA256: raise ValueError('source hash mismatch')
        verses=json.loads(cuv)
        expected={g['week']:encoded(g) for g in build_staged(source.decode('utf-8'),verses)}
        evidence_bytes=a.bundle_evidence.read_bytes() if a.bundle_evidence else None
        alias_bytes=a.alias_evidence.read_bytes() if a.alias_evidence else None
        if a.action=='candidate':
            result=prepare_guarded_candidate(a.staging,a.snapshot,binding['bindings'],expected,verses,safe_output(a.output),a.environment,a.initialize_empty,evidence_bytes,alias_bytes)
            receipt=json.loads((safe_output(a.output)/'baseline-receipt.json').read_bytes())
        else:
            rows,verify_file,receipt=verified_live_snapshot(a.snapshot,a.environment)
            old,assets=existing_manifest(a.snapshot,rows,verify_file,a.initialize_empty)
            bundle_evidence=validated_bundle_evidence(evidence_bytes,a.environment) if evidence_bytes is not None else None
            alias_evidence=validated_alias_evidence(alias_bytes,a.environment) if alias_bytes is not None else None
            operations=verified_bindings(a.staging,a.snapshot,binding['bindings'],expected,verses,bundle_evidence=bundle_evidence,verify_file=verify_file,alias_evidence=alias_evidence)
            result=write_published(operations,safe_output(a.output),old,assets,allow_initial_empty=a.initialize_empty)
        print(json.dumps({'baselineVersion':receipt['baselineVersion'],'environment':a.environment,'liveRecheck':'required_before_deploy'}))
    print(json.dumps({'status':'prepared_not_uploaded','action':a.action,'count':len(result['entries'])}))
    return 0
