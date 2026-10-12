import json,hashlib,urllib.request,concurrent.futures
from pathlib import Path
root=Path('artifacts/weekend-live/layer4-54475d42');out=root/'beta-content-v1';proof=root/'beta-sync-v1';origin='https://ai-for-god-sermon-audio-dev.web.app';pid='resi-20261011-54475d42'
paths=json.loads((proof/'preparation-receipt.json').read_text())['copiedFiles']+['/multilingual-v4.json','/multilingual-v3.json','/weekly-announcements-v1.json']
def verify(name):
 expected=hashlib.sha256((out/'public'/name.lstrip('/')).read_bytes()).hexdigest()
 with urllib.request.urlopen(urllib.request.Request(origin+name,headers={'Cache-Control':'no-cache'}),timeout=120) as r:
  assert r.status==200 and r.url==origin+name
  h=hashlib.sha256()
  while b:=r.read(1024*1024):h.update(b)
 assert h.hexdigest()==expected,name
 return {'path':name,'sha256':expected,'passed':True}
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:files=list(pool.map(verify,paths))
cat=json.loads((out/'public/multilingual-v4.json').read_text());assert cat['defaultPageId']==pid
page=next(p for p in cat['pages'] if p['id']==pid);side=json.loads((out/'public/weekly-announcements-v1.json').read_text());selections=[]
for locale,target in page['targets'].items():
 a=next(a for a in side['announcements'] if a['pageID']==pid and a['locale']==locale)
 assert a['releaseSHA256']==target['releasePackageJsonSha256'] and a['sourceIdentitySHA256']==page['sourceIdentitySha256']
 assert hashlib.sha256((out/'public'/a['poster']['url'].lstrip('/')).read_bytes()).hexdigest()==a['poster']['sha256']
 selections.append({'locale':locale,'title':a['title'],'posterBinding':'pass'})
r={'status':'published_http_verified','origin':origin,'pageId':pid,'files':files,'posterSelections':selections,'deviceDisplayed':'not_run','contentOpened':'not_run','posterVerified':'not_run'}
(proof/'http-receipt.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');print('HTTP hashes passed',len(files),'poster bindings',len(selections))
