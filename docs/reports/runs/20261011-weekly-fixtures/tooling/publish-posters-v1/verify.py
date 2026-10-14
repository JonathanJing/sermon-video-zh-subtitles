import json,urllib.request,hashlib,concurrent.futures
from pathlib import Path
p=Path('artifacts/weekend-live/layer4-54475d42');s=p/'prod-posters-v1';proof=p/'publish-posters-v1';origin='https://ai-for-god-sermon-audio.web.app';prep=json.loads((proof/'preparation-receipt.json').read_text());paths=prep['added']+prep['changed']+['/multilingual-v4.json','/multilingual-v3.json']
def fetch(path):
 with urllib.request.urlopen(urllib.request.Request(origin+path,headers={'Cache-Control':'no-cache'}),timeout=60) as x:data=x.read();assert x.status==200
 expected=(s/'public'/path.lstrip('/')).read_bytes();assert data==expected,path
 return {'path':path,'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),'passed':True},data
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:res=list(ex.map(fetch,paths))
data={path:value[1] for path,value in zip(paths,res)};cat=json.loads(data['/multilingual-v4.json']);side=json.loads(data['/weekly-announcements-v1.json']);page=next(x for x in cat['pages'] if x['id']=='resi-20261011-54475d42');bound=[]
for locale in ['zh-Hans','ko','es']:
 a=next(x for x in side['announcements'] if x['pageID']==page['id'] and x['locale']==locale);assert a['releaseSHA256']==page['targets'][locale]['releasePackageJsonSha256'] and a['sourceIdentitySHA256']==page['sourceIdentitySha256'];assert hashlib.sha256(data[a['poster']['url']]).hexdigest()==a['poster']['sha256'];bound.append({'locale':locale,'title':a['title'],'url':origin+a['poster']['url'],'releaseSHA256':a['releaseSHA256']})
attempt=json.loads((s/'deployment-attempt-v2.json').read_text());out={'status':'published_http_verified','version':attempt['newVersion'],'origin':origin,'files':[x[0] for x in res],'announcements':bound,'nativeDeviceDisplay':'not_run','externalNotification':'not_sent'};(proof/'http-receipt.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n');(proof/'deployment-receipt.json').write_text(json.dumps(attempt,indent=2)+'\n');print(json.dumps(out,ensure_ascii=False))
