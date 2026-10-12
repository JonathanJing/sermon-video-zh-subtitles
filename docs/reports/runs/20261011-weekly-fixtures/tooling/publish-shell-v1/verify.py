import json,hashlib,concurrent.futures,urllib.request,time
from pathlib import Path
from datetime import datetime,timezone
p=Path('artifacts/weekend-live/layer4-54475d42/prod-shell-v1');origin='https://ai-for-god-sermon-audio.web.app'
r=json.loads((p/'seal-report.json').read_text());started=datetime.now(timezone.utc).isoformat()
def check(row):
 url=origin+row['path'];h=hashlib.sha256();size=0
 try:
  with urllib.request.urlopen(urllib.request.Request(url,headers={'Cache-Control':'no-cache'}),timeout=120) as x:
   status=x.status
   while data:=x.read(1024*1024):h.update(data);size+=len(data)
  out={'path':row['path'],'passed':status==200 and size==row['bytes'] and h.hexdigest()==row['sha256'],'sha256':h.hexdigest(),'bytes':size}
  if row['path'].endswith('.mp3'):
   with urllib.request.urlopen(urllib.request.Request(url,headers={'Range':'bytes=0-1023'}),timeout=60) as x:
    data=x.read();out['rangePassed']=x.status==206 and x.headers.get('Content-Range')==f'bytes 0-1023/{size}' and data==(p/'public'/row['path'].lstrip('/')).open('rb').read(1024)
   out['passed'] &= out['rangePassed']
  return out
 except Exception as e:return {'path':row['path'],'passed':False,'error':type(e).__name__}
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:rows=list(ex.map(check,r['files']))
a=json.loads((p/'deployment-attempt-v2.json').read_text())
out={'status':'published_http_verified' if all(x['passed'] for x in rows) else 'failed','passed':all(x['passed'] for x in rows),'origin':origin,'newVersion':a['newVersion'],'startedAt':started,'completedAt':datetime.now(timezone.utc).isoformat(),'checkedFiles':rows,'failures':[x for x in rows if not x['passed']],'deviceAcceptance':'not_run','venueAcceptance':'not_run'}
(p.parent/'publish-shell-v1/http-receipt.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps({k:v for k,v in out.items() if k!='checkedFiles'}));assert out['passed']
