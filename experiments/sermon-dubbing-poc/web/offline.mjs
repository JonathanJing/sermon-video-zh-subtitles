// Only previously visited, public reading resources are offered offline. Audio stays online.
export const OFFLINE_VERSION = '1.26.16';

export function publicReadingPath(value, origin) {
  try {
    const url = new URL(value, origin);
    if (url.origin !== origin || url.search || url.hash) return null;
    const path = url.pathname;
    return /^\/(?:weekly|multilingual-v3)\.json$/.test(path)
      || /^\/(?:releases-v2|content|captions)\/[A-Za-z0-9_-]{1,160}\/[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*\.json$/.test(path)
      || /^\/study\/[A-Za-z0-9_-]{1,160}\/[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*\/(?:outline|meditation|products)\.json$/.test(path)
      || /^\/(?:alignment|english-reference)\/[A-Za-z0-9_-]{1,160}\.json$/.test(path)
      ? path : null;
  } catch { return null; }
}

export async function registerOfflineReading({ onStatus = () => {}, env = globalThis } = {}) {
  const base = { version: OFFLINE_VERSION, scope: 'visited-content', audioAvailable: false };
  const publish = values => onStatus({ ...base, online: env.navigator?.onLine !== false, ...values });
  if (!env.isSecureContext || !env.navigator?.serviceWorker) {
    publish({ supported: false, available: false, cachedReadingCount: 0, reason: 'unsupported' });
    return { dispose() {}, refresh: async () => {} };
  }
  const serviceWorker = env.navigator.serviceWorker;
  let registration, observer, disposed = false;
  const ask = (type, paths = []) => new Promise((resolve, reject) => {
    const worker = serviceWorker.controller || registration?.active;
    if (!worker || !env.MessageChannel) return reject(new Error('Offline worker unavailable'));
    const channel = new env.MessageChannel();
    const timer = env.setTimeout(() => {
      channel.port1.close(); reject(new Error('Offline worker timed out'));
    }, 12000);
    channel.port1.onmessage = event => {
      env.clearTimeout(timer); channel.port1.close(); resolve(event.data);
    };
    worker.postMessage({ type, paths }, [channel.port2]);
  });
  const refresh = async () => {
    try {
      const status = await ask('OFFLINE_READING_STATUS');
      if (!disposed) publish({ supported: true, ...status });
    } catch {
      if (!disposed) publish({ supported: true, available: false, cachedReadingCount: 0, reason: 'cache-unavailable' });
    }
  };
  const prime = async entries => {
    const origin = env.location.origin;
    const paths = [...new Set(['/weekly.json', '/multilingual-v3.json', ...entries.map(entry => entry.name)]
      .map(path => publicReadingPath(path, origin)).filter(Boolean))];
    try {
      const status = await ask('CACHE_PUBLIC_READING', paths);
      if (!disposed) publish({ supported: true, ...status });
    } catch { await refresh(); }
  };
  const onNetworkChange = () => refresh();
  const onControllerChange = () => prime(env.performance?.getEntriesByType('resource') || []);
  try {
    publish({ supported: true, available: false, cachedReadingCount: 0, reason: 'preparing' });
    registration = await serviceWorker.register('/offline-worker.js', { scope: '/', updateViaCache: 'none' });
    // No skipWaiting: an updated shell activates after existing tabs release their old worker.
    let readyTimer;
    try {
      await Promise.race([serviceWorker.ready, new Promise((_, reject) => {
        readyTimer = env.setTimeout(() => reject(new Error('Offline worker activation timed out')), 15000);
      })]);
    } finally { env.clearTimeout(readyTimer); }
    serviceWorker.addEventListener('controllerchange', onControllerChange);
    env.addEventListener?.('online', onNetworkChange);
    env.addEventListener?.('offline', onNetworkChange);
    if (env.PerformanceObserver) {
      observer = new env.PerformanceObserver(list => {
        const entries = list.getEntries().filter(entry => publicReadingPath(entry.name, env.location.origin));
        if (entries.length) prime(entries);
      });
      observer.observe({ type: 'resource' });
    }
    await prime(env.performance?.getEntriesByType('resource') || []);
  } catch {
    publish({ supported: true, available: false, cachedReadingCount: 0, reason: 'registration-failed' });
  }
  return { registration, refresh, dispose() {
    disposed = true; observer?.disconnect();
    serviceWorker.removeEventListener('controllerchange', onControllerChange);
    env.removeEventListener?.('online', onNetworkChange);
    env.removeEventListener?.('offline', onNetworkChange);
  } };
}
