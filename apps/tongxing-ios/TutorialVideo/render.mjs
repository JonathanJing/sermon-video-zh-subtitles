#!/usr/bin/env node
// Renders alignment-tutorial.html to an MP4: headless Chrome draws each frame through the DevTools
// protocol and ffmpeg encodes them with a small synthesized cue track. No npm dependencies (Node >= 22).
//
//   node apps/tongxing-ios/TutorialVideo/render.mjs                  # full video
//   node apps/tongxing-ios/TutorialVideo/render.mjs --stills 2,17,30 # PNG frames only, for review
//
// Options: --out <dir>  --chrome <binary>  --stills <t,t,...>  --no-audio  --scene <html>
import { spawn, execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { once } from 'node:events';
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { homedir, tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, '../../..');

function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i++) {
    const key = argv[i];
    if (!key.startsWith('--')) throw new Error(`unexpected argument: ${key}`);
    if (key === '--no-audio') out.noAudio = true;
    else if (key === '--help') out.help = true;
    else { if (argv[i + 1] === undefined) throw new Error(`${key} needs a value`); out[key.slice(2)] = argv[++i]; }
  }
  return out;
}

function findChrome(explicit) {
  const cache = join(homedir(), 'Library/Caches/ms-playwright');
  const shells = existsSync(cache) ? readdirSync(cache).filter(d => d.startsWith('chromium_headless_shell-')).sort().reverse()
    .map(d => join(cache, d, 'chrome-headless-shell-mac-arm64/chrome-headless-shell')) : [];
  const candidates = [explicit, process.env.CHROME_PATH, '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium', ...shells].filter(Boolean);
  const found = candidates.find(p => existsSync(p));
  if (!found) throw new Error('No Chrome found. Pass --chrome <binary> or set CHROME_PATH.');
  return found;
}

class Cdp {
  constructor(ws) {
    this.ws = ws; this.next = 1; this.pending = new Map(); this.waiters = [];
    ws.addEventListener('message', ev => {
      const msg = JSON.parse(ev.data);
      if (msg.id) {
        const p = this.pending.get(msg.id); this.pending.delete(msg.id);
        if (p) msg.error ? p.reject(new Error(`${p.method}: ${msg.error.message}`)) : p.resolve(msg.result);
      } else {
        this.waiters = this.waiters.filter(w => { if (w.method !== msg.method) return true; w.resolve(msg.params); return false; });
      }
    });
  }
  send(method, params = {}, sessionId) {
    const id = this.next++;
    return new Promise((res, rej) => {
      this.pending.set(id, { resolve: res, reject: rej, method });
      this.ws.send(JSON.stringify({ id, method, params, sessionId }));
    });
  }
  waitFor(method) { return new Promise(res => this.waiters.push({ method, resolve: res })); }
}

async function launch(chrome, width, height) {
  const profile = mkdtempSync(join(tmpdir(), 'tongxing-tutorial-chrome-'));
  const proc = spawn(chrome, ['--headless=new', '--remote-debugging-port=0', `--user-data-dir=${profile}`, '--no-first-run',
    '--no-default-browser-check', '--hide-scrollbars', '--mute-audio', '--force-device-scale-factor=1', '--force-color-profile=srgb',
    '--allow-file-access-from-files', `--window-size=${width},${height}`, 'about:blank'], { stdio: ['ignore', 'ignore', 'pipe'] });
  const url = await new Promise((res, rej) => {
    let buf = '';
    const timer = setTimeout(() => rej(new Error(`Chrome did not report a DevTools endpoint:\n${buf}`)), 20000);
    proc.stderr.on('data', d => { buf += d; const m = buf.match(/DevTools listening on (ws:\/\/\S+)/); if (m) { clearTimeout(timer); res(m[1]); } });
    proc.on('exit', code => { clearTimeout(timer); rej(new Error(`Chrome exited early (${code}):\n${buf}`)); });
  });
  const ws = new WebSocket(url);
  await new Promise((res, rej) => { ws.addEventListener('open', res, { once: true }); ws.addEventListener('error', () => rej(new Error('DevTools socket failed')), { once: true }); });
  const close = () => { try { ws.close(); } catch {} proc.kill('SIGKILL'); try { rmSync(profile, { recursive: true, force: true }); } catch {} };
  return { cdp: new Cdp(ws), close };
}

// ---- cue track: a few soft synthesized tones, so the video needs no licensed audio ----
function synthCues(cues, duration, rate = 48000) {
  const mix = new Float32Array(Math.ceil(duration * rate));
  const tone = (at, freq, len, amp, { decay = 5, harm = .25, glide = 0, attack = .006 } = {}) => {
    const start = Math.floor(at * rate), n = Math.floor(len * rate);
    let phase = 0;
    for (let i = 0; i < n && start + i < mix.length; i++) {
      const x = i / rate, f = freq * (1 + glide * (x / len));
      phase += 2 * Math.PI * f / rate;
      const env = Math.min(1, x / attack) * Math.exp(-decay * x) * Math.min(1, (len - x) / .02);
      mix[start + i] += amp * env * (Math.sin(phase) + harm * Math.sin(2 * phase));
    }
  };
  for (const [at, kind] of cues) {
    if (kind === 'tap') { tone(at, 1250, .07, .22, { decay: 60, glide: -.4, attack: .001 }); tone(at, 420, .06, .1, { decay: 70, attack: .001 }); }
    else if (kind === 'listen') { tone(at, 659.25, .28, .11, { decay: 9 }); tone(at + .16, 880, .4, .11, { decay: 7 }); }
    else if (kind === 'success') [523.25, 659.25, 783.99, 1046.5].forEach((f, i) => tone(at + i * .085, f, 1.3, .15, { decay: 3.6 }));
    else if (kind === 'ok') tone(at, 987.77, .7, .11, { decay: 6 });
    else if (kind === 'soft') { tone(at, 440, .5, .1, { decay: 7 }); tone(at + .18, 369.99, .6, .1, { decay: 6 }); }
    else if (kind === 'intro') [261.63, 392, 659.25].forEach((f, i) => tone(at + i * .12, f, 3.2, .075, { decay: 1.3, attack: .35, harm: .12 }));
    else if (kind === 'outro') [261.63, 392, 523.25, 659.25, 783.99].forEach((f, i) => tone(at + i * .1, f, 4.2, .08, { decay: 1.0, attack: .05, harm: .15 }));
  }
  const pcm = Buffer.alloc(44 + mix.length * 2);
  pcm.write('RIFF', 0); pcm.writeUInt32LE(36 + mix.length * 2, 4); pcm.write('WAVEfmt ', 8); pcm.writeUInt32LE(16, 16);
  pcm.writeUInt16LE(1, 20); pcm.writeUInt16LE(1, 22); pcm.writeUInt32LE(rate, 24); pcm.writeUInt32LE(rate * 2, 28);
  pcm.writeUInt16LE(2, 32); pcm.writeUInt16LE(16, 34); pcm.write('data', 36); pcm.writeUInt32LE(mix.length * 2, 40);
  for (let i = 0; i < mix.length; i++) pcm.writeInt16LE(Math.round(Math.tanh(mix[i]) * 32767), 44 + i * 2);
  return pcm;
}

const sha256 = file => createHash('sha256').update(readFileSync(file)).digest('hex');
const tryRun = (cmd, args) => { try { return execFileSync(cmd, args, { cwd: repo, encoding: 'utf8' }).trim(); } catch { return null; } };

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) { console.log(readFileSync(fileURLToPath(import.meta.url), 'utf8').split('\n').slice(1, 9).map(l => l.replace(/^\/\/ ?/, '')).join('\n')); return; }
  const scene = resolve(args.scene ?? join(here, 'alignment-tutorial.html'));
  const now = new Date();
  const day = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
  const outDir = resolve(args.out ?? join(repo, 'artifacts/tongxing-ios', day, 'tutorial-video'));
  mkdirSync(outDir, { recursive: true });
  const chrome = findChrome(args.chrome);

  const { cdp, close } = await launch(chrome, 1920, 1080);
  try {
    const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank' });
    const { sessionId } = await cdp.send('Target.attachToTarget', { targetId, flatten: true });
    const send = (method, params) => cdp.send(method, params, sessionId);
    const evaluate = async expression => {
      const r = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
      if (r.exceptionDetails) throw new Error(`page error: ${r.exceptionDetails.exception?.description ?? r.exceptionDetails.text}`);
      return r.result.value;
    };
    await send('Page.enable');
    await send('Emulation.setDeviceMetricsOverride', { width: 1920, height: 1080, deviceScaleFactor: 1, mobile: false });
    const loaded = cdp.waitFor('Page.loadEventFired');
    await send('Page.navigate', { url: `${pathToFileURL(scene).href}?render=1` });
    await loaded;
    const broken = await evaluate(`document.fonts.ready.then(() => Promise.all([...document.images].map(i => i.decode().then(() => null, () => i.src)))).then(r => r.filter(Boolean))`);
    if (broken.length) throw new Error(`images failed to load: ${broken.join(', ')}`);
    const meta = JSON.parse(await evaluate('JSON.stringify(window.TUTORIAL)'));
    await send('Emulation.setDeviceMetricsOverride', { width: meta.width, height: meta.height, deviceScaleFactor: 1, mobile: false });
    const frame = async t => {
      await evaluate(`renderAt(${t}); new Promise(r => { const done = () => r(true); requestAnimationFrame(() => requestAnimationFrame(done)); setTimeout(done, 250); })`);
      const { data } = await send('Page.captureScreenshot', { format: 'png', optimizeForSpeed: true });
      return Buffer.from(data, 'base64');
    };

    if (args.stills) {
      for (const t of args.stills.split(',').map(Number)) {
        const file = join(outDir, `still-${t.toFixed(2).padStart(6, '0')}.png`);
        writeFileSync(file, await frame(t)); console.log(file);
      }
      return;
    }

    const name = 'tongxing-alignment-tutorial';
    const video = join(outDir, `${name}.mp4`), wav = join(outDir, `${name}-cues.wav`);
    const input = ['-f', 'image2pipe', '-framerate', String(meta.fps), '-c:v', 'png', '-i', 'pipe:0'];
    if (!args.noAudio) { writeFileSync(wav, synthCues(meta.cues, meta.duration)); input.push('-i', wav); }
    const ff = spawn('ffmpeg', ['-y', '-loglevel', 'error', ...input,
      '-vf', 'scale=out_color_matrix=bt709:out_range=tv,format=yuv420p', '-c:v', 'libx264', '-preset', 'slow', '-crf', '17',
      '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-r', String(meta.fps),
      ...(args.noAudio ? [] : ['-c:a', 'aac', '-b:a', '160k', '-ac', '2']), '-movflags', '+faststart', video],
      { stdio: ['pipe', 'inherit', 'inherit'] });
    const ffDone = once(ff, 'exit');
    const total = Math.round(meta.duration * meta.fps);
    for (let i = 0; i < total; i++) {
      if (!ff.stdin.write(await frame(i / meta.fps))) await once(ff.stdin, 'drain');
      if (i % 150 === 0) process.stderr.write(`frame ${i}/${total}\n`);
    }
    ff.stdin.end();
    const [code] = await ffDone;
    if (code !== 0) throw new Error(`ffmpeg exited with ${code}`);
    writeFileSync(join(outDir, `${name}-poster.png`), await frame(2.6));
    const manifest = {
      kind: 'illustrative_tutorial_animation', note: '示意动画：界面为按源码文案重绘的示意，不是真机录屏，也不是真机、麦克风或现场验收证据。',
      scene: { path: scene.replace(repo + '/', ''), sha256: sha256(scene) }, gitRevision: tryRun('git', ['rev-parse', 'HEAD']),
      gitDirty: (tryRun('git', ['status', '--porcelain', '--', here]) ?? '') !== '', chrome: tryRun(chrome, ['--version']),
      ffmpeg: (tryRun('ffmpeg', ['-version']) ?? '').split('\n')[0], frames: total, fps: meta.fps, width: meta.width, height: meta.height,
      durationSeconds: meta.duration, audio: args.noAudio ? 'none' : 'synthesized cue tones (render.mjs)', video: { path: video, sha256: sha256(video) },
      renderedAt: now.toISOString(),
    };
    writeFileSync(join(outDir, `${name}-manifest.json`), JSON.stringify(manifest, null, 2) + '\n');
    console.log(video);
  } finally { close(); }
}

main().catch(err => { console.error(err.message); process.exit(1); });
