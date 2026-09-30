"""Optional Chrome fake-device smoke; never records the physical microphone.

Runs production capture/AudioWorklet modules using a disposable browser profile
and Chrome's synthetic media device. Does not establish Safari, hardware, field
acoustics or permission-gesture acceptance. No PCM leaves the browser.
"""
import argparse
import hashlib
import http.server
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import threading


PAGE = '''<!doctype html><html><body><script type="module">
import {captureFingerprintAudio} from '/fingerprint-capture.mjs';
const streams=[], contexts=[];
const mediaDevices={getUserMedia:async constraints=>{
 const stream=await navigator.mediaDevices.getUserMedia(constraints);
 streams.push(stream); return stream;
}};
class ObservedContext extends AudioContext {
 constructor(...args){super(...args);contexts.push(this);}
}
const env={isSecureContext,navigator:{mediaDevices},AudioContext:ObservedContext,
 AudioWorkletNode,Worker,crypto,performance,
 setTimeout:setTimeout.bind(window),clearTimeout:clearTimeout.bind(window)};
function cleaned(){return streams.every(s=>s.getTracks().every(t=>t.readyState==='ended'))
 && contexts.every(c=>c.state==='closed');}
try {
 const timings=[];
 const result=await captureFingerprintAudio({seconds:10,signal:new AbortController().signal,
  env,onTiming:value=>timings.push(value)});
 if(result.durationSeconds!==10||result.samples.length!==10*result.sampleRate)
  throw Error('incorrect_continuous_window');
 if(!cleaned())throw Error('successful_capture_leaked_resources');
 // The worklet primes real input before retaining PCM, so ten seconds of total
 // microphone allowance cannot admit ten seconds of PCM plus startup time.
 let rejected=false;
 try {await captureFingerprintAudio({seconds:10,microphoneBudgetMs:10000,
  signal:new AbortController().signal,env,onTiming:value=>timings.push(value)});}
 catch(error){if(error.message!=='capture_budget_exhausted')throw error;rejected=true;}
 if(!rejected)throw Error('deadline_did_not_reject');
 if(!cleaned())throw Error('deadline_leaked_resources');
 if(streams.length!==2||contexts.length!==2)throw Error('unexpected_retry');
 await fetch('/result',{method:'POST',body:JSON.stringify({status:'pass',
  scope:'chrome_synthetic_device_audio_worklet_not_hardware_or_safari',
  continuousPcmSeconds:result.durationSeconds,sampleRate:result.sampleRate,
  budgetExhaustedRejected:rejected,streamsEnded:streams.length,contextsClosed:contexts.length,
  physicalMicrophoneRequested:false,pcmExported:false,timings})});
} catch(error) {
 await fetch('/result',{method:'POST',body:JSON.stringify({status:'fail',reason:error.message})});
}
</script></body></html>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1] / 'experiments/sermon-dubbing-poc/web'
    allowed = {'/fingerprint-capture.mjs', '/fingerprint-worklet.mjs'}
    args.out.parent.mkdir(parents=True, exist_ok=True)

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == '/':
                data, kind = PAGE.encode(), 'text/html'
            elif self.path in allowed:
                data, kind = (root / self.path[1:]).read_bytes(), 'text/javascript'
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            if self.path != '/result':
                self.send_error(404)
                return
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 4096:
                self.send_error(413)
                return
            self.server.result = json.loads(self.rfile.read(length))
            self.send_response(200)
            self.end_headers()
            self.server.done.set()

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.done = threading.Event()
    server.result = None
    threading.Thread(target=server.serve_forever, daemon=True).start()
    chrome = str(args.browser.resolve())
    try:
        with tempfile.TemporaryDirectory(prefix='sermon-synthetic-capture-') as profile:
            with args.out.with_suffix('.browser.log').open('w') as log:
                process = subprocess.Popen([
                    chrome, '--headless=new', '--no-first-run', '--no-default-browser-check',
                    '--disable-background-networking', '--disable-sync', '--disable-extensions',
                    '--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream',
                    '--autoplay-policy=no-user-gesture-required', '--user-data-dir=' + profile,
                    f'http://127.0.0.1:{server.server_port}/',
                ], stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    server.done.wait(50)
                    report = server.result or {'status': 'fail', 'reason': 'browser_deadline'}
                    report['browserVersion'] = subprocess.check_output([chrome, '--version'], text=True).strip()
                    report['moduleSha256'] = {
                        name[1:]: hashlib.sha256((root / name[1:]).read_bytes()).hexdigest()
                        for name in sorted(allowed)
                    }
                    args.out.write_text(json.dumps(report, indent=2) + '\n')
                    print(json.dumps(report, indent=2))
                finally:
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        process.wait(timeout=5)
    finally:
        server.shutdown()
        server.server_close()
    return int(report['status'] != 'pass')


if __name__ == '__main__':
    raise SystemExit(main())
