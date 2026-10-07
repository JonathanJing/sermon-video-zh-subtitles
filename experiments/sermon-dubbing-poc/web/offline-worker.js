/* Public reading cache only. Never store audio, video, API traffic, or engagement. */
'use strict';
const CACHE_PREFIX = 'tongxing-reading-';
const CACHE_NAME = `${CACHE_PREFIX}1.26.16-v1`;
const STATE_PATH = '/_tongxing_offline_reading_state.json'; // Internal CacheStorage key; never intercepted.
const observedReading = new Set();
let stateLoaded, stateWrite = Promise.resolve();
const MODULES = [
  'app', 'offline', 'reading-mode', 'locales-reader', 'icons', 'i18n', 'content-locales',
  'locales-app', 'locales-interface', 'locales-feedback', 'locales-ko', 'locales-es',
  'timing', 'catalog', 'feedback', 'feedback-client', 'listening', 'usage', 'usage-client',
  'language-listening', 'language-listening-client', 'fingerprint-ui', 'fingerprint-capture',
  'fingerprint-diagnostics', 'fingerprint-core', 'playback-memory', 'published-weeks', 'media-session',
];
const REQUIRED_SHELL = ['/index.html', '/style.css', '/theme.js', ...MODULES.map(name => `/${name}.mjs`)];
const SHELL = new Set([...REQUIRED_SHELL, '/icons.svg', '/brand-icon.svg', '/brand-icon-light.svg',
  '/brand-icon.png', '/brand-icon-light.png', '/fingerprint-worker.mjs', '/fingerprint-worklet.mjs']);

function readingPath(path) {
  return /^\/(?:weekly|multilingual-v3)\.json$/.test(path)
    || /^\/(?:releases-v2|content|captions)\/[A-Za-z0-9_-]{1,160}\/[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*\.json$/.test(path)
    || /^\/study\/[A-Za-z0-9_-]{1,160}\/[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*\/(?:outline|meditation|products)\.json$/.test(path)
    || /^\/(?:alignment|english-reference)\/[A-Za-z0-9_-]{1,160}\.json$/.test(path);
}

function eligibleRequest(request) {
  if (request.method !== 'GET' || request.headers.has('authorization') || request.headers.has('range')) return null;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin || url.hash) return null;
  const path = url.pathname;
  if (request.mode === 'navigate' && (path === '/' || path === '/index.html'
    || /^\/pages\/[A-Za-z0-9_-]{1,160}\/[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*(?:\/index\.html)?$/.test(path))
    && [...url.searchParams.keys()].every(key => ['week', 'tab', 'contentLang', 'lang'].includes(key))) return '/index.html';
  if (url.search) return null;
  return SHELL.has(path) || readingPath(path) ? path : null;
}

async function validResponse(response, path) {
  if (!response.ok || response.status !== 200 || response.type === 'opaque'
    || response.redirected || /(?:^|,)\s*private\b/i.test(response.headers.get('cache-control') || '')) return false;
  if (response.url && new URL(response.url).origin !== self.location.origin) return false;
  const type = response.headers.get('content-type') || '';
  if (readingPath(path)) {
    if (!/^application\/(?:json|[a-z0-9.-]+\+json)(?:;|$)/i.test(type)) return false;
    try { return (await response.clone().json()) !== null; } catch { return false; }
  }
  if (path.endsWith('.mjs') || path.endsWith('.js')) return /(?:javascript|ecmascript)/i.test(type);
  if (path.endsWith('.css')) return /^text\/css\b/i.test(type);
  if (path.endsWith('.html')) return /^text\/html\b/i.test(type);
  return /^image\//i.test(type);
}

async function loadObserved(cache) {
  if (!stateLoaded) stateLoaded = (async () => {
    try {
      const previous = await (await cache.match(STATE_PATH))?.json();
      if (Array.isArray(previous?.paths)) previous.paths.filter(path => typeof path === 'string' && readingPath(path))
        .forEach(path => observedReading.add(path));
    } catch { /* Missing or damaged metadata does not prevent online reads. */ }
  })();
  await stateLoaded;
}

async function saveObserved(cache) {
  stateWrite = stateWrite.catch(() => {}).then(() => cache.put(STATE_PATH,
    new Response(JSON.stringify({ paths: [...observedReading] }), { headers: { 'content-type': 'application/json' } })));
  try { await stateWrite; } catch { /* Keep in-memory completeness when metadata cannot be persisted. */ }
}

async function networkFirst(request, path) {
  let cache;
  try { cache = await caches.open(CACHE_NAME); }
  catch { return fetch(request); }
  if (readingPath(path)) {
    await loadObserved(cache);
    observedReading.add(path);
  }
  try {
    const response = await fetch(request);
    if (await validResponse(response, path)) {
      // An explicit allowlist overrides Hosting's blanket no-store for these public artifacts.
      // Cache storage failure must not turn a successful online request into a failed request.
      try { await cache.put(path, response.clone()); } catch { /* quota or storage disabled */ }
      if (readingPath(path)) await saveObserved(cache);
      return response;
    }
    // Never replace a valid offline copy with a failed HTTP response or an HTML rewrite.
    const cached = await cache.match(path);
    // Optional study/catalog extensions that are absent online do not claim offline support.
    if (response.status === 404 && !cached) observedReading.delete(path);
    if (readingPath(path)) await saveObserved(cache);
    return cached || response;
  } catch (error) {
    const cached = await cache.match(path);
    if (readingPath(path)) await saveObserved(cache);
    if (cached) return cached;
    throw error;
  }
}

async function status() {
  const cache = await caches.open(CACHE_NAME);
  await loadObserved(cache);
  const paths = new Set((await cache.keys()).map(request => new URL(request.url).pathname));
  const shellAvailable = REQUIRED_SHELL.every(path => paths.has(path));
  const catalogAvailable = paths.has('/weekly.json');
  const cachedReadingCount = [...paths].filter(readingPath).length;
  const missingReadingCount = [...observedReading].filter(path => !paths.has(path)).length;
  const available = shellAvailable && catalogAvailable && missingReadingCount === 0;
  return { available, shellAvailable, catalogAvailable, cachedReadingCount, scope: 'visited-content',
    missingReadingCount, audioAvailable: false, reason: available ? 'available' : 'not-cached' };
}

self.addEventListener('install', event => {
  // New optional shell modules may be absent in an older Hosting bundle. Keep installation usable.
  event.waitUntil(Promise.allSettled([...SHELL].map(async path => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 8000);
    try {
      await networkFirst(new Request(new URL(path, self.location.origin), { cache: 'reload', signal: controller.signal }), path);
    } finally { clearTimeout(timer); }
  })));
});
self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names.filter(name => name.startsWith(CACHE_PREFIX) && name !== CACHE_NAME).map(name => caches.delete(name)));
    await self.clients.claim();
  })());
});
self.addEventListener('fetch', event => {
  const path = eligibleRequest(event.request);
  if (path) event.respondWith(networkFirst(event.request, path));
});
self.addEventListener('message', event => {
  if (!['OFFLINE_READING_STATUS', 'CACHE_PUBLIC_READING'].includes(event.data?.type) || !event.ports?.[0]) return;
  event.waitUntil((async () => {
    if (event.data.type === 'CACHE_PUBLIC_READING' && Array.isArray(event.data.paths)) {
      await Promise.allSettled([...new Set(event.data.paths)].slice(0, 400).map(async value => {
        if (typeof value !== 'string') return;
        const request = new Request(new URL(value, self.location.origin), { cache: 'no-cache' });
        const path = eligibleRequest(request);
        if (!path || !readingPath(path)) return;
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 8000);
        try { await networkFirst(new Request(request, { signal: controller.signal }), path); }
        finally { clearTimeout(timer); }
      }));
    }
    try { event.ports[0].postMessage(await status()); }
    catch { event.ports[0].postMessage({ available: false, cachedReadingCount: 0, audioAvailable: false, reason: 'cache-unavailable' }); }
  })());
});
