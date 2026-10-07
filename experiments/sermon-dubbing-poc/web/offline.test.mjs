import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import { publicReadingPath, registerOfflineReading, offlineReadingState } from './offline.mjs';

const origin = 'https://example.web.app';
const workerSource = await readFile(new URL('./offline-worker.js', import.meta.url), 'utf8');
const shell = path => new Response('shell', { headers: { 'content-type':
  /\.m?js$/.test(path) ? 'text/javascript' : path.endsWith('.css') ? 'text/css'
    : path.endsWith('.html') ? 'text/html' : 'image/svg+xml' } });
const json = body => new Response(JSON.stringify(body), { headers: { 'content-type': 'application/json' } });

function worker(fetchImpl = async () => json({ text: 'reading' })) {
  const buckets = new Map(), handlers = new Map();
  const normalize = value => new URL(typeof value === 'string' ? value : value.url, origin).href;
  const caches = {
    async open(name) {
      if (!buckets.has(name)) buckets.set(name, new Map());
      const bucket = buckets.get(name);
      return {
        async put(key, value) { bucket.set(normalize(key), value.clone()); },
        async match(key) { return bucket.get(normalize(key))?.clone(); },
        async keys() { return [...bucket.keys()].map(key => new Request(key)); },
      };
    },
    async keys() { return [...buckets.keys()]; },
    async delete(name) { return buckets.delete(name); },
  };
  const context = vm.createContext({
    self: { location: { origin }, clients: { claim: async () => {} }, addEventListener: (type, fn) => handlers.set(type, fn) },
    caches, fetch: fetchImpl, URL, Request, Response, AbortController, setTimeout, clearTimeout,
  });
  vm.runInContext(workerSource, context);
  const methods = vm.runInContext('({eligibleRequest, networkFirst, status, SHELL, CACHE_NAME})', context);
  return { ...methods, caches, buckets, context, handlers };
}

test('public content allowlist excludes cross-origin, query, private endpoints, and media', () => {
  for (const path of ['/weekly.json', '/multilingual-v3.json', '/content/2026-10-04/zh-Hans.json',
    '/study/week-1/es/outline.json', '/study/week-1/ko/meditation.json', '/releases-v2/week-1/es.json']) {
    assert.equal(publicReadingPath(path, origin), path);
    assert.equal(worker().eligibleRequest(new Request(origin + path)), path);
  }
  for (const path of ['/api/weekly.json', '/engagement.json', '/private.json', '/media/week.mp3',
    '/media/week.mp4', '/weekly.json?token=secret', 'https://elsewhere.test/weekly.json',
    '/study/week-1/es/private.json', '/content/week-1/../../private.json']) {
    assert.equal(publicReadingPath(path, origin), null);
    assert.equal(worker().eligibleRequest(new Request(new URL(path, origin))), null);
  }
});

test('POST, authorized requests, ranges and unknown navigations bypass worker', () => {
  const w = worker();
  for (const request of [new Request(origin + '/weekly.json', { method: 'POST' }),
    new Request(origin + '/weekly.json', { headers: { Authorization: 'Bearer ignored-test' } }),
    new Request(origin + '/weekly.json', { headers: { Range: 'bytes=0-100' } }),
    { url: origin + '/account', method: 'GET', mode: 'navigate', headers: new Headers() },
    { url: origin + '/?token=private', method: 'GET', mode: 'navigate', headers: new Headers() }]) {
    assert.equal(w.eligibleRequest(request), null);
  }
  assert.equal(w.eligibleRequest({ url: origin + '/?week=week-1&tab=transcript&contentLang=ko',
    method: 'GET', mode: 'navigate', headers: new Headers() }), '/index.html');
});

test('network first refreshes public JSON and reads stored bytes when offline', async () => {
  let online = true, revision = 1;
  const w = worker(async () => { if (!online) throw new Error('offline'); return json({ revision }); });
  const request = new Request(origin + '/content/week-1/es.json');
  assert.deepEqual(await (await w.networkFirst(request, '/content/week-1/es.json')).json(), { revision: 1 });
  revision = 2;
  assert.deepEqual(await (await w.networkFirst(request, '/content/week-1/es.json')).json(), { revision: 2 });
  online = false;
  assert.deepEqual(await (await w.networkFirst(request, '/content/week-1/es.json')).json(), { revision: 2 });
  await assert.rejects(w.networkFirst(new Request(origin + '/weekly.json'), '/weekly.json'), /offline/);
});

test('failed HTTP, malformed JSON, HTML rewrites and private responses never replace public cache', async () => {
  let next = json({ safe: true });
  const w = worker(async () => next.clone());
  const request = new Request(origin + '/weekly.json');
  await w.networkFirst(request, '/weekly.json');
  for (const response of [new Response('failure', { status: 500 }),
    new Response('not json', { headers: { 'content-type': 'application/json' } }),
    new Response('<html/>', { headers: { 'content-type': 'text/html' } }),
    new Response('{}', { headers: { 'content-type': 'application/json', 'cache-control': 'private' } })]) {
    next = response;
    assert.deepEqual(await (await w.networkFirst(request, '/weekly.json')).json(), { safe: true });
  }
  const empty = worker(async () => new Response('error', { status: 404 }));
  assert.equal((await empty.networkFirst(request, '/weekly.json')).status, 404);
  assert.equal((await empty.status()).cachedReadingCount, 0);
});

test('cache quota failure preserves online response', async () => {
  const w = worker();
  const cache = await w.caches.open(w.CACHE_NAME);
  w.context.caches.open = async () => ({ ...cache, put: async () => { throw new Error('quota'); } });
  const response = await w.networkFirst(new Request(origin + '/weekly.json'), '/weekly.json');
  assert.deepEqual(await response.json(), { text: 'reading' });
});

test('disabled CacheStorage preserves online public requests', async () => {
  const w = worker();
  w.context.caches.open = async () => { throw new Error('storage disabled'); };
  assert.deepEqual(await (await w.networkFirst(new Request(origin + '/weekly.json'), '/weekly.json')).json(), { text: 'reading' });
});

test('offline availability requires every observed public reading request and survives worker restart', async () => {
  let offline = true;
  const w = worker(async () => { if (offline) throw new Error('offline'); return json({ text: 'restored' }); });
  const cache = await w.caches.open(w.CACHE_NAME);
  for (const path of w.SHELL) await cache.put(path, shell(path));
  await cache.put('/weekly.json', json({ weeks: [] }));
  const path = '/study/week-1/es/meditation.json';
  await assert.rejects(w.networkFirst(new Request(origin + path), path), /offline/);
  assert.equal((await w.status()).available, false);
  assert.equal((await w.status()).missingReadingCount, 1);
  const restarted = worker();
  restarted.context.caches = w.caches;
  assert.equal((await restarted.status()).available, false);
  assert.equal((await restarted.status()).missingReadingCount, 1);
  offline = false;
  await w.networkFirst(new Request(origin + path), path);
  assert.equal((await w.status()).available, true);
  assert.equal((await w.status()).missingReadingCount, 0);
});

test('failed required shell installation and activation preserve the previous working cache', async () => {
  const w = worker(async request => {
    const path = new URL(request.url).pathname;
    return path === '/reading-mode.mjs' ? new Response('missing', { status: 404 }) : shell(path);
  });
  const oldName = 'tongxing-reading-1.26.15-v1';
  const oldCache = await w.caches.open(oldName);
  await oldCache.put('/index.html', shell('/index.html'));
  let pending;
  w.handlers.get('install')({ waitUntil(value) { pending = value; } });
  await assert.rejects(pending, /Required offline shell incomplete/);
  assert.ok(await oldCache.match('/index.html'));
  assert.ok((await w.caches.keys()).includes(oldName));
  w.handlers.get('activate')({ waitUntil(value) { pending = value; } });
  await assert.rejects(pending, /Required offline shell incomplete/);
  assert.ok((await w.caches.keys()).includes(oldName));
});

test('missing optional shell assets allow a fully verified required shell to install', async () => {
  const w = worker(async request => {
    const path = new URL(request.url).pathname;
    return path === '/brand-icon-light.png' ? new Response('missing', { status: 404 }) : shell(path);
  });
  let pending;
  w.handlers.get('install')({ waitUntil(value) { pending = value; } });
  await pending;
  const cache = await w.caches.open(w.CACHE_NAME);
  await cache.put('/weekly.json', json({ weeks: [] }));
  const status = await w.status();
  assert.equal(status.available, true);
  assert.equal(status.audioAvailable, false);
  assert.equal(status.scope, 'visited-content');
});

test('activation deletes only older reading caches, leaving unrelated storage intact', async () => {
  const w = worker();
  await w.caches.open('tongxing-reading-1.26.15-v1');
  const cache = await w.caches.open(w.CACHE_NAME);
  for (const path of w.SHELL) await cache.put(path, shell(path));
  await w.caches.open('unrelated-cache');
  let pending;
  w.handlers.get('activate')({ waitUntil(value) { pending = value; } });
  await pending;
  assert.deepEqual(await w.caches.keys(), [w.CACHE_NAME, 'unrelated-cache']);
  assert.doesNotMatch(workerSource, /self\.skipWaiting\(/);
});

test('worker leaves unrelated traffic unintercepted', () => {
  const w = worker();
  let intercepted = false;
  w.handlers.get('fetch')({ request: new Request(origin + '/api/feedback'), respondWith() { intercepted = true; } });
  assert.equal(intercepted, false);
});

test('late registration primes already-loaded public reading URLs and reports offline scope', async () => {
  const sent = [], statuses = [];
  class Channel {
    constructor() {
      this.port1 = { onmessage: null, close() {} };
      this.port2 = { postMessage: data => this.port1.onmessage({ data }) };
    }
  }
  const active = { postMessage(message, ports) {
    sent.push(message);
    ports[0].postMessage({ available: true, cachedReadingCount: 4, reason: 'available', audioAvailable: false });
  } };
  const sw = { controller: null, register: async () => ({ active }), ready: Promise.resolve({ active }),
    addEventListener() {}, removeEventListener() {} };
  const env = { isSecureContext: true, navigator: { onLine: true, serviceWorker: sw },
    location: { origin }, MessageChannel: Channel, setTimeout, clearTimeout,
    performance: { getEntriesByType: () => [{ name: origin + '/study/week-1/es/outline.json' },
      { name: origin + '/engagement.json' }, { name: 'https://thirdparty.test/content/week-1/es.json' }] } };
  const handle = await registerOfflineReading({ env, onStatus: value => statuses.push(value) });
  assert.deepEqual(sent[0].paths, ['/weekly.json', '/multilingual-v3.json', '/study/week-1/es/outline.json']);
  assert.equal(statuses.at(-1).available, true);
  assert.equal(statuses.at(-1).audioAvailable, false);
  env.navigator.onLine = false;
  await handle.refresh();
  assert.equal(statuses.at(-1).online, false);
  handle.dispose();
});

test('unsupported clients report unavailable without registering', async () => {
  const statuses = [];
  await registerOfflineReading({ env: {}, onStatus: value => statuses.push(value) });
  assert.equal(statuses[0].supported, false);
  assert.equal(statuses[0].available, false);
  assert.equal(statuses[0].reason, 'unsupported');
});

async function messageWorker(w, paths) {
  let pending, result;
  w.handlers.get('message')({ data: { type: 'CACHE_PUBLIC_READING', paths },
    ports: [{ postMessage(value) { result = value; } }], waitUntil(value) { pending = value; } });
  await pending;
  return result;
}

test('canonical sermon and locale navigations retain independent HTML and never replace the root reader', async () => {
  let online = true;
  const w = worker(async request => {
    if (!online) throw new Error('offline');
    return new Response(new URL(request.url).pathname, { headers: { 'content-type': 'text/html' } });
  });
  const paths = ['/', '/pages/first/zh-Hans/index.html', '/pages/first/es/index.html',
    '/pages/second/es/index.html', '/pages/second/ko/', '/pages/second/zh-Hans'];
  const request = path => ({ url: origin + path, method: 'GET', mode: 'navigate', headers: new Headers() });
  for (const path of paths) {
    const key = w.eligibleRequest(request(path));
    assert.equal(key, path === '/' ? '/index.html' : path);
    await w.networkFirst(request(path), key);
  }
  online = false;
  for (const path of paths)
    assert.equal(await (await w.networkFirst(request(path), w.eligibleRequest(request(path)))).text(), path);
  await assert.rejects(w.networkFirst(request('/pages/unvisited/es/index.html'),
    '/pages/unvisited/es/index.html'), /offline/);
});

test('priming reuses verified resources already cached by controlled fetches without another network request', async () => {
  const requested = [];
  const w = worker(async request => { requested.push(new URL(request.url).pathname); return json({ safe: true }); });
  const paths = ['/weekly.json', '/content/week-1/es.json', '/captions/week-1/es.json'];
  for (const path of paths) await w.networkFirst(new Request(origin + path), path);
  await messageWorker(w, paths);
  assert.deepEqual(requested, paths);
  const cache = await w.caches.open(w.CACHE_NAME);
  await cache.put('/content/week-1/es.json', new Response('<html/>', { headers: { 'content-type': 'text/html' } }));
  await messageWorker(w, ['/content/week-1/es.json']);
  assert.equal(requested.length, 4);
  assert.deepEqual(await (await cache.match('/content/week-1/es.json')).json(), { safe: true });
});

test('worker primes every path beyond 400 with at most eight simultaneous requests', async () => {
  let active = 0, peak = 0;
  const requested = [];
  const w = worker(async request => {
    active++; peak = Math.max(peak, active);
    requested.push(new URL(request.url).pathname);
    await new Promise(resolve => setTimeout(resolve, 1));
    active--;
    return json({ safe: true });
  });
  const paths = Array.from({ length: 413 }, (_, index) => `/content/week-${index}/es.json`);
  const result = await messageWorker(w, [...paths, paths[0], '/media/no.mp3', 'https://elsewhere.test/weekly.json']);
  assert.deepEqual([...requested].sort(), [...paths].sort());
  assert.ok(peak <= 8);
  assert.equal(result.cachedReadingCount, 413);
  const cache = await w.caches.open(w.CACHE_NAME);
  assert.ok(await cache.match(paths.at(-1)));
});

function clientEnv({ active, register, ready = Promise.resolve(), entries = [] } = {}) {
  class Channel {
    constructor() {
      this.port1 = { onmessage: null, close() {} };
      this.port2 = { postMessage: data => this.port1.onmessage({ data }) };
    }
  }
  return { isSecureContext: true, navigator: { onLine: true, serviceWorker: {
    controller: active, register: register || (async () => ({ active })), ready,
    addEventListener() {}, removeEventListener() {} } }, location: { origin },
  MessageChannel: Channel, setTimeout, clearTimeout, performance: { getEntriesByType: () => entries } };
}

test('client sends the entire resource set in bounded messages, including paths after 400', async () => {
  const sent = [], statuses = [];
  const active = { postMessage(message, ports) {
    sent.push(message);
    ports[0].postMessage({ available: true, reason: 'available' });
  } };
  const paths = Array.from({ length: 413 }, (_, index) => `/content/week-${index}/es.json`);
  const env = clientEnv({ active, entries: paths.map(path => ({ name: origin + path })) });
  const handle = await registerOfflineReading({ env, onStatus: status => statuses.push(status) });
  assert.deepEqual(sent.flatMap(message => message.paths), ['/weekly.json', '/multilingual-v3.json', ...paths]);
  assert.ok(sent.every(message => message.paths.length <= 32));
  assert.equal(statuses[0].state, 'pending');
  assert.equal(statuses.at(-1).state, 'available');
  handle.dispose();
});

test('registration, activation and initial worker exchange failures finish as unavailable', async () => {
  const failingEnvs = [clientEnv({ register: async () => { throw new Error('registration failed'); } }),
    clientEnv({ ready: new Promise(() => {}) }),
    clientEnv({ active: { postMessage() { throw new Error('worker failed'); } } }),
    clientEnv({ active: { postMessage(message, ports) {
      ports[0].postMessage({ available: false, reason: 'cache-unavailable' });
    } } })];
  failingEnvs[1].setTimeout = callback => { queueMicrotask(callback); return 0; };
  failingEnvs[1].clearTimeout = () => {};
  for (const env of failingEnvs) {
    const statuses = [];
    const handle = await registerOfflineReading({ env, onStatus: status => statuses.push(status) });
    assert.equal(statuses[0].state, 'pending');
    assert.equal(statuses.at(-1).state, 'unavailable');
    assert.equal(statuses.at(-1).available, false);
    assert.ok(['registration-failed', 'cache-unavailable'].includes(statuses.at(-1).reason));
    handle.dispose();
  }
  assert.equal(offlineReadingState({ supported: true, reason: 'not-cached' }), 'unavailable');
});
