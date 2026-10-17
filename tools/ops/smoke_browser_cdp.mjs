#!/usr/bin/env node
// Observe one page in a real headless Chrome over the DevTools protocol and print
// what a visitor's browser actually did, as one JSON object on stdout:
//
//   node scripts/smoke_browser_cdp.mjs --browser <chrome> --url <page> [--settle-ms 4000] [--deadline-ms 60000]
//
// It records every console.error/console.assert call, uncaught exception and
// browser log entry at error level (resource and CSP failures), the page's own
// /api/session requests with their HTTP status, and, once the page has loaded and
// settled, the document title, the URL's week and contentLang, the selected
// content language, the <audio> source and the rendered caption and full text.
// It never sends a request of its own. A run that misses the deadline prints
// status "timeout" and exits 3; any other failure prints status "error".
import { spawn } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const args = Object.fromEntries(process.argv.slice(2).reduce((pairs, value, index, all) => {
  if (value.startsWith('--')) pairs.push([value.slice(2), all[index + 1]]);
  return pairs;
}, []));
const browser = args.browser;
const url = args.url;
const settleMs = Number(args['settle-ms'] ?? 4000);
const deadlineMs = Number(args['deadline-ms'] ?? 60000);
if (!browser || !url || !/^https?:\/\//.test(url) || !(settleMs >= 0) || !(deadlineMs > 0)) {
  console.error('usage: smoke_browser_cdp.mjs --browser <chrome> --url <http(s) url> [--settle-ms N] [--deadline-ms N]');
  process.exit(2);
}

const started = Date.now();
const profile = mkdtempSync(join(tmpdir(), 'sermon-cdp-smoke-'));
const chrome = spawn(browser, ['--headless=new', '--remote-debugging-port=0', `--user-data-dir=${profile}`, '--no-first-run',
  '--no-default-browser-check', '--disable-background-networking', '--disable-sync', '--disable-extensions',
  '--autoplay-policy=no-user-gesture-required', 'about:blank'], { stdio: 'ignore', detached: true });

const observation = { status: 'error', url, consoleErrors: [], sessionRequests: [], dom: null, elapsedMs: 0 };
let finished = false;
function finish(status, extra = {}) {
  if (finished) return;
  finished = true;
  Object.assign(observation, { status, ...extra, elapsedMs: Date.now() - started });
  try { process.kill(-chrome.pid, 'SIGKILL'); } catch {}
  try { rmSync(profile, { recursive: true, force: true }); } catch {}
  process.stdout.write(JSON.stringify(observation) + '\n');
  process.exit(status === 'ok' ? 0 : status === 'timeout' ? 3 : 1);
}
setTimeout(() => finish('timeout', { reason: `no result within ${deadlineMs} ms` }), deadlineMs).unref();

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function devtoolsPort() {
  const file = join(profile, 'DevToolsActivePort');
  while (!existsSync(file) || !readFileSync(file, 'utf8').includes('\n')) await sleep(50);
  return Number(readFileSync(file, 'utf8').split('\n')[0]);
}

function text(remoteObject) {
  if (!remoteObject) return '';
  if ('value' in remoteObject) return typeof remoteObject.value === 'string' ? remoteObject.value : JSON.stringify(remoteObject.value);
  return remoteObject.description ?? remoteObject.type ?? '';
}

async function main() {
  const port = await devtoolsPort();
  const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  const page = targets.find(target => target.type === 'page');
  if (!page) throw new Error('no page target');
  const socket = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = () => reject(new Error('devtools socket failed')); });
  let nextId = 0;
  const pending = new Map();
  const waiters = [];
  const sessions = new Map();
  socket.onmessage = event => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      const { resolve, reject } = pending.get(message.id);
      pending.delete(message.id);
      return message.error ? reject(new Error(message.error.message)) : resolve(message.result);
    }
    const { method, params } = message;
    if (method === 'Runtime.consoleAPICalled' && ['error', 'assert'].includes(params.type)) {
      const frame = params.stackTrace?.callFrames?.[0];
      observation.consoleErrors.push({ kind: `console.${params.type}`, message: params.args.map(text).join(' ').slice(0, 500),
        source: frame?.url ?? null, line: frame ? frame.lineNumber + 1 : null });
    } else if (method === 'Runtime.exceptionThrown') {
      const details = params.exceptionDetails;
      observation.consoleErrors.push({ kind: 'exception', message: (details.exception?.description ?? details.text).slice(0, 500),
        source: details.url ?? null, line: details.lineNumber + 1 });
    } else if (method === 'Log.entryAdded' && params.entry.level === 'error') {
      observation.consoleErrors.push({ kind: `log.${params.entry.source}`, message: params.entry.text.slice(0, 500),
        source: params.entry.url ?? null, line: params.entry.lineNumber ?? null });
    } else if (method === 'Network.requestWillBeSent' && new URL(params.request.url).pathname === '/api/session') {
      // The identity the page asks the API to bind: week, track and audio hash.
      const row = { method: params.request.method, status: null, source: null };
      const keep = body => { try { const value = JSON.parse(body);
        row.source = { week: value.week ?? null, trackId: value.trackId ?? null, audioSha256: value.audioSha256 ?? null }; } catch {} };
      if (params.request.postData) keep(params.request.postData);
      else if (params.request.hasPostData) send('Network.getRequestPostData', { requestId: params.requestId })
        .then(result => keep(result.postData)).catch(() => {});
      sessions.set(params.requestId, row);
    } else if (method === 'Network.responseReceived' && sessions.has(params.requestId)) {
      sessions.get(params.requestId).status = params.response.status;
    } else if (method === 'Network.loadingFailed' && sessions.has(params.requestId)) {
      sessions.get(params.requestId).status = 0;
      sessions.get(params.requestId).error = params.errorText;
    }
    for (const waiter of waiters.splice(0)) waiter(message);
  };
  function send(method, params = {}) { return new Promise((resolve, reject) => {
    const id = ++nextId;
    pending.set(id, { resolve, reject });
    socket.send(JSON.stringify({ id, method, params }));
  }); }
  const loaded = new Promise(resolve => {
    const watch = message => (message.method === 'Page.loadEventFired' ? resolve() : waiters.push(watch));
    waiters.push(watch);
  });
  for (const domain of ['Runtime', 'Log', 'Network', 'Page']) await send(`${domain}.enable`);
  await send('Page.navigate', { url });
  await loaded;
  await sleep(settleMs);
  // Read only after the page's own session requests have answered (or the deadline ends the run).
  while ([...sessions.values()].some(row => row.status === null)) await sleep(100);
  const { result } = await send('Runtime.evaluate', { returnByValue: true, expression: `(() => {
    const text = id => document.getElementById(id)?.textContent?.replace(/\\s+/g, ' ').trim() ?? null;
    const params = new URLSearchParams(location.search);
    return { title: document.title, week: params.get('week'), contentLang: params.get('contentLang'),
      contentLanguage: document.getElementById('content-language')?.value ?? null,
      audioSrc: document.getElementById('audio')?.getAttribute('src') ?? null,
      captionText: text('current-text'), fullReading: (text('full-reading-list') ?? '').slice(0, 20000) };
  })()` });
  observation.sessionRequests = [...sessions.values()];
  finish('ok', { dom: result.value });
}

main().catch(error => finish('error', { reason: String(error?.message ?? error) }));
