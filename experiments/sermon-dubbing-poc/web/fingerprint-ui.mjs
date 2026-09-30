import { t, onLocaleChange } from './i18n.mjs';
import { captureFingerprintAudio, microphoneSupported, abortError } from './fingerprint-capture.mjs';
import { diagnosticSummary, matchReason } from './fingerprint-diagnostics.mjs';
const HASH = /^[a-f0-9]{64}$/;
export function fingerprintBinding(context) {
  const { week, track, generation } = context || {}, m = week?.audioFingerprint;
  if (!m || !track || m.schemaVersion !== 'sermon-audio-fingerprint-binding-v1' || m.algorithmVersion !== 'spectral-landmarks-v1' || m.pageId !== week.id || !HASH.test(m.sourceSha256) || !HASH.test(m.trackSha256) || !HASH.test(m.indexSha256) || m.trackSha256 !== track.sha256 || m.sourceStartSeconds !== week.sourceStartSeconds || !Number.isFinite(m.sourceStartSeconds) || !Number.isFinite(m.sourceEndSeconds) || m.sourceEndSeconds <= m.sourceStartSeconds || Math.abs(track.durationSeconds - (m.sourceEndSeconds - m.sourceStartSeconds)) > .1 || m.captureSeconds !== 10 || !/^\/fingerprints\/[a-zA-Z0-9_.-]+\.json$/.test(m.indexUrl)) return null;
  if (week.sourceEndSeconds !== undefined && week.sourceEndSeconds !== m.sourceEndSeconds) return null;
  return { weekId: week.id, sourceSha256: m.sourceSha256, trackSha256: track.sha256, trackId: track.id, generation, metadata: { ...m } };
}
const key = value => value && JSON.stringify([value.weekId, value.sourceSha256, value.trackSha256, value.trackId, value.generation, value.metadata]);
export function matchInWorker(recording, metadata, signal, WorkerClass = globalThis.Worker) {
  return new Promise((resolve, reject) => {
    const worker = new WorkerClass(new URL('./fingerprint-worker.mjs', import.meta.url), { type: 'module' });
    const requestId = 1;
    const finish = (error, value) => { worker.terminate(); signal.removeEventListener('abort', abort); error ? reject(error) : resolve(value); };
    const abort = () => finish(abortError());
    signal.addEventListener('abort', abort, { once: true });
    if (signal.aborted) { abort(); return; }
    worker.onerror = () => finish(new Error('match_failed'));
    worker.onmessage = ({ data }) => {
      if (data.requestId !== requestId) return;
      finish(data.error ? new Error(data.error) : null, data);
    };
    try { worker.postMessage({ samples: recording.samples, sampleRate: recording.sampleRate, metadata, requestId }, [recording.samples.buffer]); } catch (error) { finish(error); }
  });
}
// Keep one verified index in one bounded operation's Worker. Closing the session
// discards session state. Persistent public bytes are revalidated by each Worker;
// cached indexes alone do not establish offline audio/catalog readiness.
export async function prepareInWorker(metadata, signal, WorkerClass = globalThis.Worker) {
  const worker = new WorkerClass(new URL('./fingerprint-worker.mjs', import.meta.url), { type: 'module' });
  let pending = null, serial = 0, closed = false;
  const close = (error = abortError()) => {
    if (closed) return;
    closed = true; worker.terminate(); signal.removeEventListener('abort', abort);
    const task = pending; pending = null; task?.reject(error);
  };
  const abort = () => close();
  signal.addEventListener('abort', abort, { once: true });
  worker.onerror = () => close(new Error('match_failed'));
  worker.onmessage = ({ data }) => {
    if (!pending || data.requestId !== pending.id || closed) return;
    const task = pending; pending = null;
    if (data.error) { const error = new Error(data.error); close(error); task.reject(error); }
    else task.resolve(data);
  };
  const request = (operation, payload = {}, transfer = []) => new Promise((resolve, reject) => {
    if (closed || signal.aborted) { close(); reject(abortError()); return; }
    if (pending) { reject(new Error('match_failed')); return; }
    const id = ++serial; pending = { id, resolve, reject };
    try { worker.postMessage({ operation, metadata, requestId: id, ...payload }, transfer); }
    catch (error) { close(error); }
  });
  if (signal.aborted) { close(); throw abortError(); }
  try {
    const result = await request('prepare');
    if (result.ready !== true) throw new Error('index_binding');
    return { timings: result.timings, close, match: recording => request('match',
      { samples: recording.samples, sampleRate: recording.sampleRate }, [recording.samples.buffer]) };
  } catch (error) { close(error); throw error; }
}

// Show bounded diagnostic codes only; never expose native messages or device IDs.
export function captureDiagnostic(error = {}) {
  const known = {capture_start_timeout:'MIC_START_TIMEOUT',capture_interrupted:'INPUT_INTERRUPTED',audio_context_interrupted:'AUDIO_INTERRUPTED',microphone_ended:'MIC_ENDED',worklet_processor:'PROCESSOR_ERROR',capture_failed:'INVALID_CAPTURE',index_binding:'INDEX_MISMATCH',index_unavailable:'INDEX_UNAVAILABLE',match_failed:'MATCH_ERROR'};
  const native = {NotAllowedError:'MIC_PERMISSION',SecurityError:'MIC_PERMISSION',NotFoundError:'MIC_MISSING',NotReadableError:'MIC_BUSY',OverconstrainedError:'MIC_SETTINGS',NotSupportedError:'AUDIO_UNSUPPORTED'};
  const stages = new Set(['context','permission','startup','worklet_load','input','recording']);
  const stage = stages.has(error.captureStage) ? error.captureStage : 'matching';
  const code = (Object.hasOwn(known, error.message) ? known[error.message] : null) || (Object.hasOwn(native, error.name) ? native[error.name] : null) || (stage === 'worklet_load' ? 'WORKLET_LOAD' : stage === 'startup' || stage === 'context' ? 'AUDIO_START' : 'UNKNOWN');
  const details = {empty_input:'EMPTY',frame_gap:'CLOCK_GAP',channel_shape:'CHANNELS',track_muted:'MUTED',start_route:'ROUTE'};
  const detail = Object.hasOwn(details, error.captureDetail) ? details[error.captureDetail] : null;
  return {code,stage,...(detail ? {detail} : {}),version:'C3'};
}
export function diagnosticMessage(diagnostic) {
  const known = new Set('MIC_START_TIMEOUT INPUT_INTERRUPTED AUDIO_INTERRUPTED MIC_BUSY MIC_MISSING MIC_ENDED WORKLET_LOAD PROCESSOR_ERROR AUDIO_START INDEX_UNAVAILABLE'.split(' '));
  return t('fingerprint.diagnostic.detail', { message: t(`fingerprint.diagnostic.${known.has(diagnostic.code) ? diagnostic.code : 'UNKNOWN'}`), code: `${diagnostic.code}${diagnostic.detail ? ':' + diagnostic.detail : ''}`, stage: diagnostic.stage, version: diagnostic.version });
}
// The native play promise resolves only when playback can actually start.
// Cleanup never pauses a later attempt; only this pending operation may pause.
export function playAlignmentAudio(audio, { signal, timeoutMs = 8000, timers = globalThis } = {}) {
  return new Promise((resolve, reject) => {
    let settled = false, timeout;
    const clean = () => { timers.clearTimeout(timeout); signal?.removeEventListener('abort', abort); audio.removeEventListener('error', failed); };
    const finish = (error) => {
      if (settled) return;
      settled = true; clean();
      if (error) { audio.pause(); reject(error); } else resolve();
    };
    const abort = () => finish(abortError());
    const failed = () => finish(new Error('audio_play_failed'));
    signal?.addEventListener('abort', abort, { once: true });
    audio.addEventListener('error', failed);
    if (signal?.aborted) { abort(); return; }
    timeout = timers.setTimeout(() => finish(new Error('audio_play_timeout')), timeoutMs);
    try {
      Promise.resolve(audio.play()).then(() => {
        if (settled) return;
        if (signal?.aborted) { abort(); return; }
        finish(audio.paused ? new Error('audio_play_failed') : null);
      }, error => finish(error || new Error('audio_play_failed')));
    } catch (error) { finish(error || new Error('audio_play_failed')); }
  });
}
export function createFingerprintController({ context, pause, seek, play, position = () => NaN, onState = () => {}, capture = captureFingerprintAudio, prepare = prepareInWorker, match = null, supported = microphoneSupported, now = () => performance.now(), timers = globalThis, expirySeconds = 15, autoApply = true }) {
  let serial = 0, active = null, result = null, expiryTimer = null, pendingPlay = null;
  let state = { phase: 'idle' }, session = null, readyCapture = null;
  const elapsedMs = started => Math.max(0, now() - started);
  const emit = value => {
    state = value;
    if (session) {
      session.phase = value.phase;
      if (value.diagnostic) session.errorCode = value.diagnostic.code;
      if (!session.finished) session.timings.totalMs = elapsedMs(session.started);
      if (['no_match', 'error', 'permission_denied', 'unavailable', 'unsupported', 'expired', 'timeout', 'cancelled', 'applied'].includes(value.phase)) session.finished = true;
    }
    onState(value);
  };
  const diagnostics = () => session ? diagnosticSummary(session) : null;
  const clearExpiry = () => { timers.clearTimeout(expiryTimer); expiryTimer = null; };
  function cancel(reason = 'cancelled') {
    const pending = pendingPlay; pendingPlay = null;
    serial++; active?.abort(); active = null; readyCapture?.prepared.close(); readyCapture = null; result = null; clearExpiry();
    if (pending) { pending.controller.abort(); pause(); }
    if (reason === 'idle') session = null;
    emit({ phase: reason });
  }
  const valid = (token, binding) => serial === token && key(binding) === key(fingerprintBinding(context()));
  function targetFor(item) {
    const elapsed = (now() - item.endedAt) / 1000, target = item.end + elapsed;
    return valid(item.token, item.binding) && elapsed >= 0 && elapsed < expirySeconds && target < item.binding.metadata.sourceEndSeconds - item.binding.metadata.sourceStartSeconds ? target : null;
  }
  async function start() {
    // The ready branch reaches getUserMedia synchronously in this new click.
    if (readyCapture) return record();
    cancel('idle');
    const binding = fingerprintBinding(context());
    session = { started: now(), phase: 'idle', content: binding?.metadata, attempts: 0, timings: {} };
    const observation = session;
    if (!binding) { emit({ phase: 'unavailable' }); return; }
    if (!supported()) { emit({ phase: 'unsupported' }); return; }
    const token = serial, controller = new AbortController(); active = controller;
    emit({ phase: 'preparing_index' });
    let timedOut = false, prepared = null, retained = false;
    const timeout = timers.setTimeout(() => { timedOut = true; controller.abort(); }, 35000);
    try {
      prepared = await prepare(binding.metadata, controller.signal);
      if (!valid(token, binding) || controller.signal.aborted) return;
      observation.timings.indexMs = prepared.timings?.indexMs;
      readyCapture = {prepared, binding, token, controller, observation}; retained = true;
      expiryTimer = timers.setTimeout(() => {
        if (readyCapture?.controller === controller) cancel('expired');
      }, 30000);
      emit({phase: 'ready_to_record'});
    } catch (error) {
      if (valid(token, binding)) emit({phase: timedOut ? 'timeout' : error.name === 'AbortError' ? 'cancelled' : 'error', diagnostic: captureDiagnostic(error)});
    } finally {
      timers.clearTimeout(timeout);
      if (!retained) {
        prepared?.close();
        if (active === controller) {controller.abort(); active = null;}
      }
    }
  }
  async function record() {
    const {prepared, binding, token, controller, observation} = readyCapture;
    readyCapture = null; clearExpiry();
    if (!valid(token, binding) || controller.signal.aborted) {
      prepared.close(); cancel('expired'); return;
    }
    let timedOut = false;
    const timeout = timers.setTimeout(() => {timedOut = true; controller.abort();}, 35000);
    try {
      pause(); emit({ phase: 'permission' });
      const recording = await capture({ onTiming: value => {
        observation.attempts++;
        for (const name of ['permissionMs', 'startupMs', 'captureMs', 'microphoneObservedMs']) {
          if (typeof value[name] === 'number' && Number.isFinite(value[name]) && value[name] >= 0)
            observation.timings[name] = (observation.timings[name] || 0) + value[name];
        }
      }, seconds: 10, signal: controller.signal, onRecovering: () => { if (valid(token, binding)) emit({ phase: 'recovering' }); }, onPreparing: () => { if (valid(token, binding)) emit({ phase: 'starting' }); }, onRecording: () => { if (valid(token, binding)) emit({ phase: 'recording' }); } });
      if (!valid(token, binding) || controller.signal.aborted) return;
      if (!Number.isFinite(recording.endedAt) || !Number.isFinite(recording.durationSeconds) || recording.durationSeconds < 9 || recording.durationSeconds > 11 || recording.endedAt > now() + 50) throw new Error('capture_failed');
      emit({ phase: 'matching' });
      const workerStarted = now();
      const answer = await (match ? match(recording, binding.metadata, controller.signal) : prepared.match(recording));
      if (!valid(token, binding) || controller.signal.aborted) return;
      observation.timings.workerMs = elapsedMs(workerStarted);
      for (const name of ['indexMs', 'featureMs', 'matchMs']) {
        const value = answer.timings?.[name];
        if (typeof value === 'number' && Number.isFinite(value) && value >= 0) observation.timings[name] = value;
      }
      observation.match = answer.summary;
      const found = answer.result;
      if (!found?.matched) { emit({ phase: 'no_match', reason: matchReason(found?.diagnostics?.reason) }); return; }
      const end = found.queryStartSeconds + recording.durationSeconds;
      const elapsed = (now() - recording.endedAt) / 1000;
      if (!Number.isFinite(found.queryStartSeconds) || found.queryStartSeconds < 0 || !Number.isFinite(found.confidence) || found.confidence <= 0 || end >= binding.metadata.sourceEndSeconds - binding.metadata.sourceStartSeconds || elapsed < 0 || elapsed >= expirySeconds) { emit({ phase: 'expired' }); return; }
      const item = { binding, token, end, endedAt: recording.endedAt, confidence: found.confidence }; result = item;
      expiryTimer = timers.setTimeout(() => { if (result === item) cancel('expired'); }, (expirySeconds - elapsed) * 1000);
      emit({ phase: 'matched', sourceTimeSeconds: binding.metadata.sourceStartSeconds + end, confidence: found.confidence, expiresInSeconds: expirySeconds - elapsed });
      if (autoApply) apply();
    } catch (error) {
      if (valid(token, binding)) emit({ phase: timedOut ? 'timeout' : error.name === 'AbortError' ? 'cancelled' : error.name === 'NotAllowedError' || error.name === 'SecurityError' ? 'permission_denied' : error.message === 'unsupported' ? 'unsupported' : 'error', diagnostic: captureDiagnostic(error) });
    } finally {
      prepared?.close();
      timers.clearTimeout(timeout);
      if (active === controller) { controller.abort(); active = null; }
    }
  }
  function apply() {
    const item = result;
    if (!item || pendingPlay) return false;
    const target = targetFor(item);
    if (target === null) { cancel('expired'); return false; }
    if (!context().ready) { emit({ phase: 'play_failed' }); return false; }
    const observation = session;
    const pending = { controller: new AbortController() }; pendingPlay = pending;
    const current = () => pendingPlay === pending && result === item && valid(item.token, item.binding);
    const failed = error => {
      if (!current()) return;
      pendingPlay = null; pending.controller.abort(); pause();
      if (targetFor(item) === null) { cancel('expired'); return; }
      emit({ phase: error?.name === 'NotAllowedError' ? 'play_blocked' : 'play_failed' });
    };
    emit({ phase: 'play_starting', sourceTimeSeconds: target + item.binding.metadata.sourceStartSeconds });
    try {
      // Invoke seek and play synchronously; the fallback click retains its gesture.
      const seekStarted = now();
      const positioned = seek(target, { correction: Boolean(item.positioned) });
      observation.timings.seekCallMs = elapsedMs(seekStarted);
      if (!positioned) { failed(); return false; }
      item.positioned = true;
      const playStarted = now();
      Promise.resolve(play({ signal: pending.controller.signal })).then(() => {
        if (!current()) { if (pendingPlay === pending) cancel('cancelled'); return; }
        observation.timings.playStartMs = elapsedMs(playStarted);
        const latest = targetFor(item);
        if (latest === null) { cancel('expired'); return; }
        // One bounded correction for buffering delay, never a tracking loop.
        const actual = position();
        if (Number.isFinite(actual) && Math.abs(actual - latest) > .35 && !seek(latest, { correction: true })) { failed(); return; }
        pendingPlay = null; result = null; clearExpiry(); serial++;
        emit({ phase: 'applied', sourceTimeSeconds: latest + item.binding.metadata.sourceStartSeconds });
      }, failed).catch(failed);
    } catch (error) { failed(error); return false; }
    return true;
  }
  return { start, apply, cancel, playbackStarted() { if (!pendingPlay) this.invalidate(); }, invalidate() { if (active || result || pendingPlay) cancel('cancelled'); }, getState: () => state, getDiagnostics: diagnostics, available: () => Boolean(fingerprintBinding(context())) };
}

function clock(seconds) {
  const n = Math.floor(seconds), mm = String(Math.floor(n / 60) % 60).padStart(2, '0'), ss = String(n % 60).padStart(2, '0');
  return n >= 3600 ? `${Math.floor(n / 3600)}:${mm}:${ss}` : `${mm}:${ss}`;
}
export function mountFingerprintUI(options) {
  const $ = id => document.getElementById(id);
  const dialog = $('fingerprint-dialog');
  const phases = new Set(["idle", "preparing_index", "ready_to_record", "permission", "recovering", "starting", "recording", "matching", "cancelled", "unavailable", "unsupported", "permission_denied", "timeout", "error", "no_match", "expired", "play_starting", "play_blocked", "play_failed"]);
  function renderState(value) {
    const busy = ['preparing_index', 'permission', 'starting', 'recovering', 'recording', 'matching', 'play_starting'].includes(value.phase);
    $('fingerprint-start').disabled = busy;
    $('fingerprint-start').textContent = t(value.phase === 'ready_to_record' ? 'fingerprint.record' : value.phase === 'idle' ? 'fingerprint.start' : 'fingerprint.restart');
    $('fingerprint-apply').hidden = !['matched', 'play_blocked', 'play_failed'].includes(value.phase);
    $('fingerprint-apply').textContent = t('fingerprint.apply');
    $('fingerprint-message').textContent = value.phase === 'matched' ? t('fingerprint.matched', { time: clock(value.sourceTimeSeconds) }) : value.phase === 'applied' ? t('fingerprint.applied', { time: clock(value.sourceTimeSeconds) }) : value.phase === 'no_match' ? t(`fingerprint.reason.${matchReason(value.reason)}`) : value.phase === 'error' && value.diagnostic ? diagnosticMessage(value.diagnostic) : t(`fingerprint.phase.${phases.has(value.phase) ? value.phase : 'error'}`);
  }
  const controller = createFingerprintController({ ...options, onState(value) {
    renderState(value);
    renderDiagnostics();
    if (value.phase === 'applied' && dialog.open) dialog.close();
  } });
  function renderDiagnostics() {
    const node = $('fingerprint-diagnostics');
    if (!node) return;
    const d = controller.getDiagnostics();
    node.textContent = d ? t('fingerprint.sessionSummary', {
      level: t(`fingerprint.level.${d.match.level}`), clipping: t(`fingerprint.clipping.${d.match.clipping}`),
      landmarks: d.match.landmarks ?? '—', anchors: d.match.supportingAnchors ?? '—',
      total: d.timings.totalMs === null ? '—' : d.timings.totalMs / 1000,
      microphone: d.timings.microphoneObservedMs === null ? '—' : d.timings.microphoneObservedMs / 1000,
    }) : t('fingerprint.sessionEmpty');
  }
  onLocaleChange(() => { renderState(controller.getState()); renderDiagnostics(); });
  renderState(controller.getState()); renderDiagnostics();
  $('fingerprint-open').addEventListener('click', () => { controller.cancel('idle'); dialog.showModal(); });
  $('fingerprint-start').addEventListener('click', () => controller.start());
  $('fingerprint-apply').addEventListener('click', () => controller.apply());
  for (const id of ['fingerprint-cancel', 'fingerprint-stop']) $(id).addEventListener('click', () => { controller.cancel(); dialog.close(); });
  dialog.addEventListener('cancel', () => controller.cancel());
  dialog.addEventListener('close', () => controller.invalidate());
  document.addEventListener('visibilitychange', () => { if (document.hidden) { controller.cancel(); dialog.close(); } });
  window.addEventListener('pagehide', () => controller.cancel());
  return { ...controller, refresh() { controller.invalidate(); $('fingerprint-open').hidden = !controller.available(); if (dialog.open) dialog.close(); } };
}
