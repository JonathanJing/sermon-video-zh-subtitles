import json,shutil,sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
from scripts import prepare_dev_simulated_publication as p,delivery_contract as c
root=Path('artifacts/weekend-live/layer4-54475d42'); base=root/'beta-baseline-v1'; prod=root/'prod-default-week-v1'; out=root/'beta-content-v1'; proof=root/'beta-sync-v1'; pid='resi-20261011-54475d42'
c.validate_catalog_snapshot(base);c.validate_catalog_snapshot(prod)
shutil.copytree(base/'public',out/'public');shutil.copy2(base/'firebase.json',out/'firebase.json')
cat=json.loads((base/'public/multilingual-v3.json').read_text());cat['schemaVersion']=c.CATALOG_V4
new=next(x for x in p.read(prod/'public/multilingual-v4.json')['pages'] if x['id']==pid)
assert pid not in {x['id'] for x in cat['pages']}
cat['pages'].insert(0,new);cat['defaultPageId']=pid
paths=set()
for target in new['targets'].values():
 paths.add(target['releasePackageUrl']);paths.add(target['audioFingerprint']['indexUrl'])
 release=p.read(prod/'public'/target['releasePackageUrl'].lstrip('/'));paths.update(x['path'] for x in release['assets'])
side=p.read(base/'public/weekly-announcements-v1.json');ann=[a for a in p.read(prod/'public/weekly-announcements-v1.json')['announcements'] if a['pageID']==pid]
side['announcements']=ann+[a for a in side['announcements'] if a['pageID']!=pid]
for a in ann:paths.add(a['poster']['url'])
for f in (prod/'public').rglob('*'):
 if f.is_file() and pid in str(f.relative_to(prod/'public')):paths.add('/'+str(f.relative_to(prod/'public')))
for name in paths:
 src=prod/'public'/name.lstrip('/');dst=out/'public'/name.lstrip('/');dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
for name,value in [('multilingual-v4.json',cat),('multilingual-v3.json',c.project_human_catalog(cat)),('weekly-announcements-v1.json',side)]:
 (out/'public'/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
cfg=p.read(out/'firebase.json');redirect=next(r for r in p.read(prod/'firebase.json')['hosting']['redirects'] if pid in r['source']);cfg['hosting'].setdefault('redirects',[]).append(redirect);(out/'firebase.json').write_text(json.dumps(cfg,indent=2)+'\n')
p.write(out/'seal-report.json',{**p.catalog_report(out/'public'),'files':p.files_report(out/'public')});c.validate_catalog_snapshot(out)
p.write(proof/'config.json',p.publication_config(base.resolve(),out.resolve()))
p.write(proof/'preparation-receipt.json',{'status':'validated_not_deployed','pageId':pid,'locales':list(new['targets']),'preservedPageCount':len(cat['pages'])-1,'copiedFiles':sorted(paths),'contentReviewUnchanged':True})
print('validated',len(paths),'copied files;',len(cat['pages'])-1,'existing pages preserved')
