#!/usr/bin/env node
// Voices narration.zh.srt with DeepSeek cloud TTS: one request per cue, each clip placed at its cue start.
// Clips are cached by voice and spoken text, so a rerun pays only for cues whose text changed.
//
//   node apps/tongxing-ios/TutorialVideo/narrate.mjs             # synthesize, assemble, write the timed SRT
//   node apps/tongxing-ios/TutorialVideo/narrate.mjs --dry-run   # show the plan and the billed characters only
//
// Options: --srt <file>  --out <dir>  --voice tide|stella  --duration <seconds>  --dry-run
// The key comes from DEEPSEEK_API_KEY, or from ~/.config/tongxing/deepseek.env (mode 600), and is never printed.
import { createHash } from 'node:crypto';
import { existsSync, lstatSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, '../../..');
const URL_TTS = 'https://api.deepseek.com/v1/tools/tts';
const RATE = 24000;                       // the service returns 24 kHz mono PCM16
const PRICE_PER_10K = 0.45;               // list price in USD; a Chinese character bills as two
// The app's name is read tóngxíng. 同行 alone can be read tóngháng, so the request spells it with an unambiguous homophone.
const SPOKEN = [['同行', '同形'], ['7 到 15 秒', '七到十五秒']];   // and digits are spelled out so they are read in Chinese

function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i++) {
    const key = argv[i];
    if (key === '--dry-run') out.dryRun = true;
    else if (key === '--help') out.help = true;
    else if (key.startsWith('--') && argv[i + 1] !== undefined) out[key.slice(2)] = argv[++i];
    else throw new Error(`unexpected argument: ${key}`);
  }
  return out;
}

const toSeconds = s => { const m = s.trim().match(/^(\d+):(\d\d):(\d\d)[,.](\d{3})$/); if (!m) throw new Error(`bad SRT time: ${s}`); return +m[1] * 3600 + +m[2] * 60 + +m[3] + +m[4] / 1000; };
const toStamp = x => { const ms = Math.round(x * 1000); const p = (n, w = 2) => String(n).padStart(w, '0');
  return `${p(Math.floor(ms / 3600000))}:${p(Math.floor(ms / 60000) % 60)}:${p(Math.floor(ms / 1000) % 60)},${p(ms % 1000, 3)}`; };

function parseSrt(text) {
  return text.replace(/\r/g, '').trim().split(/\n\s*\n/).map(block => {
    const lines = block.split('\n');
    const [from, to] = lines[1].split('-->');
    return { index: +lines[0], start: toSeconds(from), end: toSeconds(to), text: lines.slice(2).join('\n').trim() };
  });
}

const spokenText = text => SPOKEN.reduce((s, [a, b]) => s.replaceAll(a, b), text.replace(/\n/g, ''));
const billedChars = text => [...text].reduce((n, ch) => n + (/[㐀-鿿豈-﫿]/.test(ch) ? 2 : 1), 0);

function apiKey() {
  const env = (process.env.DEEPSEEK_API_KEY ?? '').trim();
  if (env) return env;
  const file = join(homedir(), '.config/tongxing/deepseek.env');
  if (!existsSync(file) || lstatSync(file).isSymbolicLink()) throw new Error('DEEPSEEK_API_KEY is not set and ~/.config/tongxing/deepseek.env is missing');
  if ((lstatSync(file).mode & 0o777) !== 0o600) throw new Error('~/.config/tongxing/deepseek.env must have mode 600');
  const line = readFileSync(file, 'utf8').split('\n').find(l => l.startsWith('DEEPSEEK_API_KEY='));
  const value = line?.slice('DEEPSEEK_API_KEY='.length).trim().replace(/^['"]|['"]$/g, '');
  if (!value) throw new Error('~/.config/tongxing/deepseek.env has no DEEPSEEK_API_KEY');
  return value;
}

// The streamed WAV leaves its sizes unset (0xFFFFFFFF), so locate the data chunk and take everything after it.
function pcmFromWav(buf) {
  if (buf.length < 44 || buf.toString('latin1', 0, 4) !== 'RIFF' || buf.toString('latin1', 8, 12) !== 'WAVE') throw new Error('response is not a WAV file');
  let at = 12, fmt = null;
  while (at + 8 <= buf.length) {
    const id = buf.toString('latin1', at, at + 4), size = buf.readUInt32LE(at + 4);
    if (id === 'fmt ') fmt = { format: buf.readUInt16LE(at + 8), channels: buf.readUInt16LE(at + 10), rate: buf.readUInt32LE(at + 12), bits: buf.readUInt16LE(at + 22) };
    if (id === 'data') {
      if (!fmt || fmt.format !== 1 || fmt.channels !== 1 || fmt.rate !== RATE || fmt.bits !== 16) throw new Error(`unexpected audio format: ${JSON.stringify(fmt)}`);
      const end = size === 0xFFFFFFFF || size === 0 || at + 8 + size > buf.length ? buf.length : at + 8 + size;
      const bytes = buf.subarray(at + 8, end - ((end - at - 8) % 2));
      return new Int16Array(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.length));
    }
    at += 8 + size + (size % 2);
  }
  throw new Error('WAV has no data chunk');
}

function wavFromPcm(pcm) {
  const out = Buffer.alloc(44 + pcm.length * 2);
  out.write('RIFF', 0); out.writeUInt32LE(36 + pcm.length * 2, 4); out.write('WAVEfmt ', 8); out.writeUInt32LE(16, 16);
  out.writeUInt16LE(1, 20); out.writeUInt16LE(1, 22); out.writeUInt32LE(RATE, 24); out.writeUInt32LE(RATE * 2, 28);
  out.writeUInt16LE(2, 32); out.writeUInt16LE(16, 34); out.write('data', 36); out.writeUInt32LE(pcm.length * 2, 40);
  Buffer.from(pcm.buffer, pcm.byteOffset, pcm.length * 2).copy(out, 44);
  return out;
}

// Keep the speech and drop the service's leading and trailing silence (about 0.28 s each), without touching the speech itself.
function trimSilence(pcm) {
  let peak = 0; for (const v of pcm) peak = Math.max(peak, Math.abs(v));
  const gate = Math.max(260, peak * 0.03), win = Math.round(RATE * 0.01);
  const loud = i => { let m = 0; for (let k = i; k < Math.min(pcm.length, i + win); k++) m = Math.max(m, Math.abs(pcm[k])); return m > gate; };
  let first = 0, last = pcm.length;
  while (first < pcm.length && !loud(first)) first += win;
  while (last > first && !loud(Math.max(0, last - win))) last -= win;
  const lead = first / RATE, tail = (pcm.length - last) / RATE;
  const a = Math.max(0, first - Math.round(RATE * 0.03)), b = Math.min(pcm.length, last + Math.round(RATE * 0.09));
  const out = Int16Array.from(pcm.subarray(a, b)), fade = Math.round(RATE * 0.006);
  for (let i = 0; i < fade && i < out.length; i++) { out[i] *= i / fade; out[out.length - 1 - i] *= i / fade; }
  return { pcm: out, lead, tail, peak };
}

async function synthesize(text, voice, key) {
  for (let attempt = 1; ; attempt++) {
    const res = await fetch(URL_TTS, { method: 'POST', headers: { Authorization: `Bearer ${key}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, voice_id: voice, format: 'wav' }), signal: AbortSignal.timeout(120000) });
    if (res.ok) return Buffer.from(await res.arrayBuffer());
    const body = (await res.text()).slice(0, 300);
    // 429 and 503 mean the request was not accepted; anything else stops here instead of being retried blindly.
    if ((res.status === 429 || res.status === 503) && attempt < 4) { await new Promise(r => setTimeout(r, 800 * 2 ** attempt)); continue; }
    throw new Error(`DeepSeek TTS HTTP ${res.status}: ${body}`);
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) { console.log(readFileSync(fileURLToPath(import.meta.url), 'utf8').split('\n').slice(1, 9).map(l => l.replace(/^\/\/ ?/, '')).join('\n')); return; }
  const srtPath = resolve(args.srt ?? join(here, 'narration.zh.srt'));
  const sceneDuration = readFileSync(join(here, 'alignment-tutorial.html'), 'utf8').match(/const DURATION = ([\d.]+)/)?.[1];
  const voice = args.voice ?? 'tide', duration = +(args.duration ?? sceneDuration);
  if (!(duration > 0)) throw new Error('no video duration: pass --duration');
  const now = new Date();
  const day = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
  const outDir = resolve(args.out ?? join(repo, 'artifacts/tongxing-ios', day, 'tutorial-video'));
  const clipDir = join(outDir, 'narration-clips');
  const cues = parseSrt(readFileSync(srtPath, 'utf8')).map(c => ({ ...c, spoken: spokenText(c.text) }));
  const billed = cues.reduce((n, c) => n + billedChars(c.spoken), 0);
  console.log(`${cues.length} cues, voice ${voice}, ${billed} billed characters, about $${(billed / 10000 * PRICE_PER_10K).toFixed(4)} at list price`);
  if (args.dryRun) { for (const c of cues) console.log(`${String(c.index).padStart(2)}  ${toStamp(c.start)}  ${c.spoken}`); return; }

  mkdirSync(clipDir, { recursive: true });
  let key = null, requested = 0;
  for (const c of cues) {
    const id = createHash('sha256').update(`${voice}\n${c.spoken}`).digest('hex').slice(0, 12);
    c.clip = join(clipDir, `${String(c.index).padStart(2, '0')}-${id}.wav`);
    if (!existsSync(c.clip)) {
      key ??= apiKey();
      const raw = pcmFromWav(await synthesize(c.spoken, voice, key));   // throws on a body that is not PCM16 mono 24 kHz
      writeFileSync(c.clip, wavFromPcm(raw)); requested++;
    }
    const raw = pcmFromWav(readFileSync(c.clip));
    Object.assign(c, trimSilence(raw), { rawSeconds: raw.length / RATE });
    c.seconds = c.pcm.length / RATE;
  }

  // Checks: a clip cut off by the service ends without silence; every clip must finish before the next cue starts.
  const problems = [];
  const track = new Float32Array(Math.round(duration * RATE));
  cues.forEach((c, i) => {
    const next = cues[i + 1]?.start ?? duration, speech = [...c.spoken].filter(ch => /[㐀-鿿\w]/.test(ch)).length;
    c.slack = next - (c.start + c.seconds); c.perChar = c.seconds / speech;
    if (c.tail < 0.06) problems.push(`cue ${c.index}: no trailing silence (${c.tail.toFixed(2)} s), the audio may be cut off`);
    if (c.perChar < 0.12 || c.perChar > 0.5) problems.push(`cue ${c.index}: ${c.perChar.toFixed(2)} s per character is outside the expected range`);
    if (c.slack < 0.12) problems.push(`cue ${c.index}: runs ${(-c.slack).toFixed(2)} s into the next cue`);
    const at = Math.round(c.start * RATE);
    for (let k = 0; k < c.pcm.length && at + k < track.length; k++) track[at + k] += c.pcm[k] / 32768;
  });
  let peak = 0; for (const v of track) peak = Math.max(peak, Math.abs(v));
  const gain = peak > 0 ? 0.8 / peak : 1;
  const mixed = Int16Array.from(track, v => Math.round(Math.max(-1, Math.min(1, v * gain)) * 32767));

  // The delivered SRT keeps each cue's start and ends when its speech ends.
  const timed = cues.map((c, i) => `${i + 1}\n${toStamp(c.start)} --> ${toStamp(Math.min(c.start + c.seconds + 0.1, (cues[i + 1]?.start ?? duration) - 0.05))}\n${c.text}\n`).join('\n');
  const name = 'tongxing-alignment-tutorial';
  const wav = join(outDir, `${name}-narration.zh.wav`), srtOut = join(outDir, `${name}.zh.srt`);
  writeFileSync(wav, wavFromPcm(mixed)); writeFileSync(srtOut, timed);
  const sha = f => createHash('sha256').update(readFileSync(f)).digest('hex');
  writeFileSync(join(outDir, `${name}-narration-report.json`), JSON.stringify({
    kind: 'ai_synthesized_narration', humanListening: 'not_run', provider: 'DeepSeek cloud TTS', endpoint: URL_TTS, voice,
    spokenSubstitutions: SPOKEN, billedCharacters: billed, listPriceUsd: +(billed / 10000 * PRICE_PER_10K).toFixed(4), requestsThisRun: requested,
    script: { path: srtPath.replace(repo + '/', ''), sha256: sha(srtPath) }, narration: { file: `${name}-narration.zh.wav`, sha256: sha(wav), gain: +gain.toFixed(3) },
    timedSrt: { file: `${name}.zh.srt`, sha256: sha(srtOut) }, problems,
    cues: cues.map(c => ({ index: c.index, start: c.start, speechSeconds: +c.seconds.toFixed(3), slackToNextSeconds: +c.slack.toFixed(3), secondsPerCharacter: +c.perChar.toFixed(3),
      trimmedLeadSeconds: +c.lead.toFixed(3), trimmedTailSeconds: +c.tail.toFixed(3), text: c.text, spoken: c.spoken, clipSha256: sha(c.clip) })),
    generatedAt: now.toISOString(),
  }, null, 2) + '\n');

  for (const c of cues) console.log(`${String(c.index).padStart(2)}  ${toStamp(c.start)}  speech ${c.seconds.toFixed(2)} s  slack ${c.slack.toFixed(2)} s  ${c.perChar.toFixed(2)} s/char  ${c.text}`);
  console.log(`requests this run: ${requested}; narration: ${wav}; srt: ${srtOut}`);
  if (problems.length) { console.error(problems.join('\n')); process.exit(2); }
}

main().catch(err => { console.error(err.message); process.exit(1); });
