import json,hashlib,shutil,sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
from scripts.build_weekly_announcement_sidecar import build
from scripts.delivery_contract import validate_catalog_snapshot
from scripts.guarded_hosting_publish import authenticated_transport,live_version
p=Path('artifacts/weekend-live/layer4-54475d42');base=p/'prod-video-v1';out=p/'prod-posters-v1';proof=p/'publish-posters-v1';posters=Path('artifacts/sermon-poster/2026-10-11/multilingual-published-video-v1');page='resi-20261011-54475d42';sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest()
version=live_version(authenticated_transport(),'ai-for-god-sermon-audio');assert version.endswith('/bb01b5d98ae9fb4d'),version
out.mkdir();shutil.copytree(base/'public',out/'public');shutil.copy2(base/'firebase.json',out/'firebase.json');cat=json.loads((out/'public/multilingual-v4.json').read_text());side=json.loads((out/'public/weekly-announcements-v1.json').read_text());bindings=[];added=[]
for locale in ['zh-Hans','ko','es']:
 r=json.loads((posters/locale/'poster-receipt.json').read_text());data=(posters/locale/'poster.png').read_bytes();a,e=build(cat,(out/f'public/releases-v4/{page}/{locale}.json').read_bytes(),r,data,locale,page)
 dest=out/'public'/a['poster']['url'].lstrip('/');dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data);added.append(a['poster']['url']);side['announcements']=[x for x in side['announcements'] if (x['pageID'],x['locale'])!=(page,locale)]+[a]
 prev=posters/locale/'poster-preview.png';ph=sha(prev);pp=f'/posters/{page}/{locale}-preview-{ph}.png';(out/'public'/pp.lstrip('/')).write_bytes(prev.read_bytes());added.append(pp);bindings.append(e)
(out/'public/weekly-announcements-v1.json').write_text(json.dumps(side,ensure_ascii=False,indent=2)+'\n')
report=json.loads((base/'seal-report.json').read_text());report['files']=[{'path':'/'+str(f.relative_to(out/'public')),'sha256':sha(f),'bytes':f.stat().st_size} for f in sorted((out/'public').rglob('*')) if f.is_file()];(out/'seal-report.json').write_text(json.dumps(report,indent=2)+'\n');validate_catalog_snapshot(out)
old=json.loads((base/'seal-report.json').read_text());changes=[x['path'] for x in old['files'] if sha(out/'public'/x['path'].lstrip('/'))!=x['sha256']];assert changes==['/weekly-announcements-v1.json'],changes
assert (base/'firebase.json').read_bytes()==(out/'firebase.json').read_bytes()
(proof/'preparation-receipt.json').write_text(json.dumps({'status':'prepared','baselineVersion':version,'pageId':page,'locales':['zh-Hans','ko','es'],'added':added,'changed':changes,'unchangedFiles':len(old['files'])-1,'catalogsAndConfigUnchanged':True,'bindings':bindings},ensure_ascii=False,indent=2)+'\n')
c=json.loads((p/'publish-video-v1/config.json').read_text());c.update(snapshot=str(out.resolve()),baseline_version=version,baseline_catalog_sha=sha(base/'public/multilingual-v3.json'),baseline_catalog_v4_sha=sha(base/'public/multilingual-v4.json'));(proof/'config.json').write_text(json.dumps(c,indent=2)+'\n');print('Prepared six PNGs and three App announcements; 200 old files and config unchanged.')
