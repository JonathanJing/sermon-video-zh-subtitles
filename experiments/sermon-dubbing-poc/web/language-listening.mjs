import { LanguageListeningSession } from './language-listening-client.mjs';
import { lockedDailyBrowserId, usageDay } from './usage-client.mjs';
import { mergeRanges } from './listening.mjs';

export function createLanguageListening({ audio, config, onError = () => {},
  document: doc = globalThis.document, window: win = globalThis.window,
  now = () => Date.now(), monotonicNow = () => performance.now(),
  schedule = (callback, delay) => setInterval(callback, delay),
  makeSession = (source, options) => new LanguageListeningSession(source, options),
  identity = (storage, day, permitted) => lockedDailyBrowserId(storage, day, { permitted }),
  getInterfaceLocale = () => 'zh', onInterfaceLocaleChange = () => {}, bootstrapSource,
  storage: providedStorage,
} = {}) {
  const sessions = new Map(), visits = new Map();
  let current = null, selected = null, enabled = false, playing = false, interfaceEpoch = 0;
  const interfaceLocale = () => getInterfaceLocale() === 'zh' ? 'zh-Hans' : getInterfaceLocale();
  let storage = providedStorage;
  if (storage === undefined) { try { storage = globalThis.localStorage; } catch { storage = null; } }
  function prepare(target) {
    if (!enabled || !target || target.ready || target.preparing || target.session.stopped) return;
    target.preparing = target.session.prepare().then(() => {
      target.ready = enabled && !target.session.stopped;
      target.previous = null; // Never backfill time spent waiting for a token.
    }).catch(onError).finally(() => { target.preparing = null; });
  }
  function chooseSession() {
    if (!enabled || !selected) return null;
    const day = usageDay(now()), { week, track } = selected;
    const key = `${day}:${week.id}:${track.id}:${track.sha256}:${interfaceLocale()}:${interfaceEpoch}`;
    if (!sessions.has(key) || sessions.get(key).session.stopped) {
      const session = makeSession({ week: week.id, trackId: track.id, audioSha256: track.sha256, appVersion: config.appVersion },
        { day, clientId: identity(storage, day, () => enabled), interfaceLocale: interfaceLocale(), contentLocale: week.targetLocale || track.targetLocale || 'zh-Hans' });
      const target = { session, duration: track.durationSeconds, previous: null, listenedSeconds: 0, ranges: [], ready: false };
      // Keep withdrawn epochs for retries; switching back may create a new one.
      if (sessions.has(key)) sessions.set(`${key}:withdrawn:${sessions.size}`, sessions.get(key));
      sessions.set(key, target);
    }
    return sessions.get(key);
  }
  function flush(target = current) {
    if (!enabled || !target?.ready) return;
    target.session.flush({ listenedSeconds: Math.floor(target.listenedSeconds * 100) / 100,
      ranges: target.ranges.map(([a, b]) => [Math.ceil(a * 100) / 100, Math.floor(b * 100) / 100]).filter(([a, b]) => b > a) }).catch(onError);
  }
  function rotate() {
    if (!enabled || !selected) return;
    visit();
    if (current?.session.day === usageDay(now()) && current.session.dimensions.interfaceLocale === interfaceLocale() && !current.session.stopped) return;
    flush(); if (current) current.previous = null;
    current = chooseSession(); prepare(current);
  }
  function observe() {
    if (!enabled || !selected) return;
    rotate(); prepare(current);
    if (!current?.ready) return;
    const position = audio.currentTime, time = monotonicNow(), rate = audio.playbackRate || 1;
    const prior = current.previous;
    const active = playing && !audio.paused && !audio.seeking && audio.readyState >= 3 && !audio.muted && audio.volume !== 0;
    current.previous = active && Number.isFinite(position) ? { position, time, rate } : null;
    if (!active || !prior || rate !== prior.rate) return;
    const elapsed = (time - prior.time) / 1000, advanced = position - prior.position;
    // Mobile browsers throttle background callbacks even while native audio
    // keeps playing. Require proportional media progress; no progress, seeks,
    // waiting, or interrupted samples never manufacture listening time.
    const maximumGap = doc.visibilityState === 'visible' ? 8 : 120;
    if (elapsed <= 0 || elapsed > maximumGap || advanced <= 0 || advanced > elapsed * rate * 1.25 + .1) return;
    const start = Math.max(0, prior.position), end = Math.min(current.duration, position);
    if (end <= start) return;
    current.listenedSeconds += Math.min(elapsed, (end - start) / rate);
    const ranges = mergeRanges([...current.ranges, [start, end]], current.duration);
    if (ranges.length <= 256) current.ranges = ranges;
  }
  function clearSample() { if (current) current.previous = null; }
  audio.addEventListener('playing', () => { playing = true; observe(); });
  audio.addEventListener('timeupdate', observe);
  for (const event of ['pause', 'ended', 'waiting', 'stalled', 'seeking', 'emptied', 'error']) {
    audio.addEventListener(event, () => {
      clearSample();
      if (event !== 'seeking') playing = false;
      if (['pause', 'ended', 'error'].includes(event)) flush();
    });
  }
  audio.addEventListener('seeked', () => { clearSample(); observe(); });
  audio.addEventListener('ratechange', clearSample);
  audio.addEventListener('volumechange', clearSample);
  doc.addEventListener('visibilitychange', () => {
    clearSample();
    if (doc.visibilityState !== 'visible') flushAll();
    else visit();
  });
  win.addEventListener('pagehide', () => { clearSample(); flushAll(); });
  win.addEventListener('online', () => { if (enabled) { prepare(current); flushAll(); } });
  function visit() {
    if (!enabled || !bootstrapSource || doc.visibilityState !== 'visible') return;
    const day = usageDay(now()), locale = interfaceLocale(), key = `${day}:${locale}:${interfaceEpoch}`;
    if (!visits.has(key) || visits.get(key).stopped) {
      if (visits.has(key)) visits.set(`${key}:withdrawn:${visits.size}`, visits.get(key));
      visits.set(key, makeSession(bootstrapSource, { day, clientId: identity(storage, day, () => enabled),
        endpoint: '/api/interface-usage', interfaceLocale: locale }));
    }
    visits.get(key).flush({}).catch(onError);
  }
  function flushAll() {
    if (!enabled) return;
    for (const target of sessions.values()) flush(target);
    for (const session of visits.values()) session.flush({}).catch(onError);
  }
  onInterfaceLocaleChange(() => { interfaceEpoch += 1; clearSample(); rotate(); visit(); });
  schedule(() => { visit(); observe(); flushAll(); }, 30000);
  return {
    select(week, track) {
      flush(); clearSample(); playing = false;
      selected = week && track ? { week, track } : null;
      current = chooseSession();
      // Source changes happen before audio.src is installed. No old media
      // sample can enter the new language's stream.
      prepare(current);
    },
    setEnabled(value) {
      if (enabled === value) return;
      enabled = value; clearSample();
      if (enabled) { visit(); current = chooseSession(); playing = !audio.paused && audio.readyState >= 3; prepare(current); }
    },
    async retract() {
      enabled = false; clearSample();
      const results = await Promise.allSettled([
        ...[...new Set(sessions.values())].map(target => target.session.retract()),
        ...[...new Set(visits.values())].map(session => session.retract()),
      ]);
      const failure = results.find(result => result.status === 'rejected');
      if (failure) throw failure.reason;
    },
  };
}
