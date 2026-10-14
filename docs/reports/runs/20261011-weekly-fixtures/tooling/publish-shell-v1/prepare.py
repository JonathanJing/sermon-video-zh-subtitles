import json,hashlib,sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
from scripts.guarded_hosting_publish import authenticated_transport,live_version
from scripts.delivery_contract import validate_catalog_snapshot
p=Path('artifacts/weekend-live/layer4-54475d42'); s=p/'prod-shell-v1'; b=p/'live-baseline-7089e037'
sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest()
r=json.loads((p/'sealed-prod-v2/seal-report.json').read_text())
r['files']=[{'path':'/'+str(f.relative_to(s/'public')),'sha256':sha(f),'bytes':f.stat().st_size} for f in sorted((s/'public').rglob('*')) if f.is_file()]
for k,n in [('catalogSha256','multilingual-v3.json'),('catalogV4Sha256','multilingual-v4.json')]:r[k]=sha(s/'public'/n)
(s/'seal-report.json').write_text(json.dumps(r,indent=2)+'\n')
validate_catalog_snapshot(s)
site='ai-for-god-sermon-audio';version=live_version(authenticated_transport(),site)
assert version.endswith('/7089e0378ae6b7e7'),version
route={'project':'ai-for-god','site':site,'origin':'https://'+site+'.web.app','channel':'production_web'}
c={'snapshot':str(s.resolve()),'intent':{'schemaVersion':'sermon-release-intent-v1','environment':'production',**route},'routes':{'production':route},'baseline_version':version,'baseline_catalog_sha':sha(b/'public/multilingual-v3.json'),'baseline_catalog_v4_sha':sha(b/'public/multilingual-v4.json') if (b/'public/multilingual-v4.json').exists() else None,'lease_bucket':'ai-for-god-sermon-media-prod'}
(p/'publish-shell-v1/config.json').write_text(json.dumps(c,indent=2)+'\n')
print('snapshot validated',len(r['files']),'files; live',version)
