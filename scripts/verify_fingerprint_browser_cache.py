"""Optional local Chrome smoke: verified index cache, not whole-app offline acceptance.

Uses synthetic public data, a loopback server and a disposable browser profile.
Does not request a microphone, use existing browser data or deploy content.
Run explicitly with --browser /path/to/chrome --out /tmp/index-cache-report.json.
"""
import argparse
import hashlib,json,pathlib,subprocess,tempfile,threading,http.server,os,signal


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser',required=True,type=pathlib.Path)
    parser.add_argument('--out',required=True,type=pathlib.Path)
    args=parser.parse_args()
    root=pathlib.Path(__file__).resolve().parents[1]/'experiments/sermon-dubbing-poc/web'
    args.out.parent.mkdir(parents=True,exist_ok=True)
    index={'schemaVersion':'sermon-landmark-index-v1','algorithmVersion':'spectral-landmarks-v1','pageId':'synthetic-browser-cache','sourceSha256':'a'*64,'trackSha256':'b'*64,'sourceStartSeconds':20,'sourceEndSeconds':220,'durationSeconds':200,'sampleRate':8000,'hopSize':256,'postings':{'123':[1,20]}}
    body=json.dumps(index).encode();sha=hashlib.sha256(body).hexdigest()
    metadata={k:v for k,v in index.items() if k not in {'postings','durationSeconds','sampleRate','hopSize'}}
    metadata.update(schemaVersion='sermon-audio-fingerprint-binding-v1',captureSeconds=10,indexUrl='/fingerprints/synthetic.json',indexSha256=sha)
    js='''const metadata=METADATA;
    async function prepare(){const w=new Worker('/fingerprint-worker.mjs',{type:'module'});try{return await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('deadline')),10000);w.onerror=()=>{clearTimeout(timer);reject(Error('worker_error'));};w.onmessage=e=>{clearTimeout(timer);resolve(e.data);};w.postMessage({operation:'prepare',requestId:1,metadata});});}finally{w.terminate();}}
    try{
     await caches.delete('tongxing-verified-current-index-v1');
     const cold=await prepare();if(cold.ready!==true)throw Error('cold_not_ready');
     const cache=await caches.open('tongxing-verified-current-index-v1');
     const keys=await cache.keys();if(keys.length!==1)throw Error('entry_count');
     const stored=await cache.match(keys[0]);const cachedBytes=await stored.clone().arrayBuffer();
     const cachedHash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',cachedBytes))].map(x=>x.toString(16).padStart(2,'0')).join('');
     if(cachedHash!==metadata.indexSha256)throw Error('stored_hash');
     await fetch('/make-index-unavailable');
     const warm=await prepare();if(warm.ready!==true)throw Error('offline_index_not_ready');
     await cache.put(keys[0],new Response('corrupt',{headers:{'X-Tongxing-Index-Sha256':metadata.indexSha256}}));
     const corrupt=await prepare();if(!corrupt.error||corrupt.ready)throw Error('corrupt_not_rejected');
     if((await cache.keys()).length!==0)throw Error('corrupt_not_removed');
     await fetch('/result',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({status:'pass',coldReady:cold.ready,warmNewWorkerReady:warm.ready,corruptOfflineRejected:true,cachedShaVerified:true,cacheEntriesAfterCorruption:0,microphoneRequested:false,scope:'real_chrome_cache_storage_index_route_unavailable_not_whole_app_offline'})});
    }catch(e){await fetch('/result',{method:'POST',body:JSON.stringify({status:'fail',reason:e.message})});}
    '''.replace('METADATA',json.dumps(metadata))
    class Handler(http.server.BaseHTTPRequestHandler):
     def log_message(self,*args):pass
     def do_GET(self):
      if self.path=='/':data=('<!doctype html><html><body><script type="module">'+js+'</script></body></html>').encode();kind='text/html'
      elif self.path=='/make-index-unavailable':self.server.offline=True;data=b'ok';kind='text/plain'
      elif self.path=='/fingerprints/synthetic.json':
       self.server.index_requests+=1
       if self.server.offline:self.send_error(503);return
       data=body;kind='application/json'
      elif self.path in {'/fingerprint-worker.mjs','/fingerprint-core.mjs','/fingerprint-diagnostics.mjs'}:data=(root/self.path[1:]).read_bytes();kind='text/javascript'
      else:self.send_error(404);return
      self.send_response(200);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data)
     def do_POST(self):
      if self.path!='/result':self.send_error(404);return
      length=int(self.headers.get('Content-Length','0'))
      if length>4096:self.send_error(413);return
      self.server.result=json.loads(self.rfile.read(length));self.send_response(200);self.end_headers();self.server.done.set()
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);server.offline=False;server.index_requests=0;server.done=threading.Event();server.result=None
    threading.Thread(target=server.serve_forever,daemon=True).start()
    chrome=str(args.browser.resolve())
    with tempfile.TemporaryDirectory(prefix='sermon-browser-cache-') as profile:
     with args.out.with_suffix('.browser.log').open('w') as log:
      process=subprocess.Popen([chrome,'--headless=new','--no-first-run','--no-default-browser-check','--disable-background-networking','--disable-sync','--disable-extensions','--user-data-dir='+profile,f'http://127.0.0.1:{server.server_port}/'],stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
      try:
       complete=server.done.wait(40)
       report=server.result or {'status':'fail','reason':'browser_deadline'}
       report['indexRouteRequests']=server.index_requests
       # Exactly one cold network read plus the deliberately corrupt/offline retry.
       if report['status']=='pass' and server.index_requests!=2:report={'status':'fail','reason':'unexpected_index_network_requests','indexRouteRequests':server.index_requests}
       report['browserVersion']=subprocess.check_output([chrome,'--version'],text=True).strip()
       report['workerSha256']=hashlib.sha256((root/'fingerprint-worker.mjs').read_bytes()).hexdigest()
       args.out.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
      finally:
       try:os.killpg(process.pid,signal.SIGTERM)
       except ProcessLookupError:pass
       try:process.wait(timeout=5)
       except subprocess.TimeoutExpired:
        try:os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        process.wait(timeout=5)
    server.shutdown();server.server_close()
    return int(report['status']!='pass')


if __name__ == '__main__':
    raise SystemExit(main())
