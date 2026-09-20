"""Local text boundary baseline, frozen against the Gemini experiment inputs."""
import hashlib
import importlib.util
import json
import re
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('gemini_poc', ROOT/'experiments/gemini-prosody-poc/run.py')
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)
OUT = ROOT/'artifacts/local-prosody-poc/20260919'
BASE = 'http://192.168.1.152:8000/v1'

def local_api(path, payload=None):
    # Existing server listens on Spark loopback; use SSH without changing its binding.
    code = "import json,sys,urllib.request; x=json.load(sys.stdin); p=x['payload']; r=urllib.request.Request('http://127.0.0.1:8000/v1'+x['path'],data=json.dumps(p).encode() if p is not None else None,headers={'Content-Type':'application/json'}); print(urllib.request.urlopen(r,timeout=240).read().decode())"
    import shlex
    proc=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=5','achillesjing@192.168.1.152','python3 -c '+shlex.quote(code)],input=json.dumps({'path':path,'payload':payload}),capture_output=True,text=True,timeout=260)
    if proc.returncode:
        raise RuntimeError(proc.stderr[-2000:])
    return json.loads(proc.stdout)

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    inventory=local_api('/models')
    model=inventory['data'][0]['id']
    (OUT/'model-inventory.json').write_text(json.dumps(inventory,indent=2))
    results=[]
    for name in ['A-text','B-text','A-text-repeat']:
        source=ROOT/'artifacts/gemini-prosody-poc/20260917'/((name.replace('-repeat',''))+'.json')
        original=json.loads(source.read_text())
        request={'model':model,'messages':[{'role':'user','content':original['prompt']}], 'temperature':0.2,'max_tokens':8192,'response_format':{'type':'json_object'},'chat_template_kwargs':{'enable_thinking':False}}
        identity=hashlib.sha256(json.dumps(request,sort_keys=True).encode()).hexdigest()
        target=OUT/(name+'.json'); raw_path=OUT/(name+'.response.json'); attempt=OUT/(name+'.attempt.json')
        if target.exists():
            result=json.loads(target.read_text())
            if result['request_sha256']!=identity:
                raise ValueError('Changed request; use fresh output directory')
            results.append(result);continue
        latency=None
        if raw_path.exists():
            if json.loads(attempt.read_text())['request_sha256']!=identity:
                raise ValueError('Raw response identity mismatch')
            raw=json.loads(raw_path.read_text())
        else:
            if attempt.exists():
                raise RuntimeError('Inspect previous incomplete attempt before retrying '+name)
            attempt.write_text(json.dumps({'request_sha256':identity,'request':request,'started_unix':time.time()}))
            start=time.monotonic()
            raw=local_api('/chat/completions',request)
            latency=round(time.monotonic()-start,2)
            raw_path.write_text(json.dumps(raw,ensure_ascii=False,indent=2))
        content=raw['choices'][0]['message']['content'].strip()
        # Preserve raw provider output; remove only a whole-response Markdown fence.
        content=re.sub(r'^```(?:json)?\s*\n(.*?)\n```$',r'\1',content,flags=re.S)
        analysis=json.loads(content)
        result={**original,'id':name,'model_requested':model,'model_returned':raw.get('model'),'request_sha256':identity,'analysis':analysis,'usage':raw.get('usage'),'latency_seconds':latency,'finish_reason':raw['choices'][0]['finish_reason'],'validation_errors':shared.validate(analysis,len(original['words']),original['duration'],'text')}
        target.write_text(json.dumps(result,ensure_ascii=False,indent=2));results.append(result)
        print(name,model,len(analysis.get('sentences',[])),result['validation_errors'],flush=True)
    shared.render(OUT,results)
    # The shared renderer has a Gemini-specific heading; correct it for this local baseline.
    page=OUT/'review.html';page.write_text(page.read_text().replace('Gemini 3.8 Flash 断句实验',model+' 本地文字断句实验').replace('Gemini 断句 POC','本地断句 POC'))

if __name__=='__main__': main()
