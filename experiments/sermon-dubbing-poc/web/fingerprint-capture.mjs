export function abortError() { return new DOMException('Cancelled', 'AbortError'); }
export const MAX_MICROPHONE_MS = 15000;
const budgetError = () => Object.assign(new Error('capture_budget_exhausted'), { captureStage: 'input' });
function abortable(promise, signal, onLate = () => {}) {
  return new Promise((resolve, reject) => {
    let settled = false;
    const abort = () => { if (!settled) { settled = true; reject(abortError()); } };
    signal.addEventListener('abort', abort, { once: true });
    if (signal.aborted) abort();
    promise.then(value => {
      signal.removeEventListener('abort', abort);
      if (settled) { onLate(value); return; }
      settled = true; resolve(value);
    }, error => { signal.removeEventListener('abort', abort); if (!settled) { settled = true; reject(error); } });
  });
}
export function microphoneSupported(env = globalThis) {
  return Boolean(env.isSecureContext && env.navigator?.mediaDevices?.getUserMedia && env.AudioContext && env.AudioWorkletNode && env.Worker && env.crypto?.subtle);
}
async function waitForInputReady(stream, context, signal) {
  const tracks = stream.getAudioTracks();
  if (!tracks.length) throw new Error('microphone_ended');
  let cleanup = () => {}, resuming = false;
  try {
    const ready = new Promise((resolve, reject) => {
      const check = () => {
        if (tracks.some(t => t.readyState === 'ended') || context.state === 'closed') { reject(new Error('microphone_ended')); return; }
        if (context.state === 'running' && tracks.every(t => t.muted !== true)) { resolve(); return; }
        if (context.state !== 'running' && !resuming) {
          resuming = true;
          Promise.resolve().then(() => context.resume()).catch(() => {}).finally(() => { resuming = false; });
        }
      };
      for (const track of tracks) for (const event of ['unmute', 'mute', 'ended']) track.addEventListener(event, check);
      context.addEventListener('statechange', check);
      cleanup = () => {
        for (const track of tracks) for (const event of ['unmute', 'mute', 'ended']) track.removeEventListener(event, check);
        context.removeEventListener('statechange', check);
      };
      check();
    });
    return await abortable(ready, signal);
  } finally { cleanup(); }
}
export async function captureFingerprintAttempt({ seconds = 10, signal, microphoneBudgetMs = MAX_MICROPHONE_MS, onPreparing = () => {}, onRecording = () => {}, onTiming = () => {}, env = globalThis }) {
  if (!microphoneSupported(env)) throw new Error('unsupported');
  if (signal.aborted) throw abortError();
  if (!Number.isFinite(seconds) || seconds <= 0 || !Number.isFinite(microphoneBudgetMs) || microphoneBudgetMs > MAX_MICROPHONE_MS || seconds * 1000 > microphoneBudgetMs) throw budgetError();
  const operation = new AbortController(), localSignal = operation.signal;
  const cancel = () => operation.abort(); signal.addEventListener('abort', cancel, { once: true });
  const timers = env.setTimeout ? env : globalThis;
  let stream, context, source, node, mute, detach = () => {}, started = false, startupTimer, microphoneTimer, startupTimedOut = false, budgetTimedOut = false, stage = 'context';
  const clock = () => (env.performance || globalThis.performance).now();
  const attemptStarted = clock();
  let permissionStarted, grantedAt, recordingAt, stoppedAt;
  const stopStream = value => value?.getTracks().forEach(track => track.stop());
  try {
    context = new env.AudioContext();
    // Unlock in the click, but resume again after iOS changes the microphone route.
    Promise.resolve(context.resume()).catch(() => {});
    stage = 'permission'; permissionStarted = clock();
    stream = await abortable(env.navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: false, noiseSuppression: false, autoGainControl: false }, video: false }), localSignal, stopStream);
    grantedAt = clock();
    if (localSignal.aborted) throw abortError();
    // One granted stream consumes the same operation budget during startup,
    // worklet loading and PCM capture. Recovery cannot reset that budget.
    microphoneTimer = timers.setTimeout(() => { budgetTimedOut = true; operation.abort(); }, microphoneBudgetMs);
    onPreparing(); stage = 'startup';
    startupTimer = timers.setTimeout(() => { startupTimedOut = true; operation.abort(); }, 5000);
    await abortable(context.resume(), localSignal);
    stage = 'worklet_load';
    await abortable(context.audioWorklet.addModule(new URL('./fingerprint-worklet.mjs', import.meta.url)), localSignal);
    if (localSignal.aborted) throw abortError();
    stage = 'input';
    await waitForInputReady(stream, context, localSignal);
    if (localSignal.aborted) throw abortError();
    source = context.createMediaStreamSource(stream);
    node = new env.AudioWorkletNode(context, 'fingerprint-capture', { processorOptions: { seconds, startupSeconds: 3 } });
    mute = context.createGain(); mute.gain.value = 0;
    const complete = new Promise((resolve, reject) => {
      let resuming = false;
      const ended = () => reject(new Error('microphone_ended'));
      const interrupted = detail => Object.assign(new Error('capture_interrupted'), {captureDetail: detail});
      const muted = () => { if (started) reject(interrupted('track_muted')); };
      const stateChanged = () => {
        if (context.state === 'running') return;
        if (started || context.state === 'closed') { reject(new Error('audio_context_interrupted')); return; }
        // A route switch during startup is not a discontinuity in retained PCM.
        if (!resuming) {
          resuming = true;
          Promise.resolve().then(() => context.resume()).catch(() => {}).finally(() => { resuming = false; });
        }
      };
      for (const track of stream.getAudioTracks()) { track.addEventListener('ended', ended); track.addEventListener('mute', muted); }
      context.addEventListener('statechange', stateChanged);
      detach = () => {
        context.removeEventListener('statechange', stateChanged);
        for (const track of stream.getAudioTracks()) { track.removeEventListener('ended', ended); track.removeEventListener('mute', muted); }
      };
      node.onprocessorerror = () => reject(new Error('worklet_processor'));
      node.port.onmessage = ({ data }) => {
        // A delayed main-thread timer must not admit a late completed buffer.
        if (clock() - grantedAt >= microphoneBudgetMs) { budgetTimedOut = true; operation.abort(); return; }
        if (data.error) {
          const error = new Error(data.error);
          if (['empty_input','channel_shape','frame_gap'].includes(data.captureDetail)) error.captureDetail = data.captureDetail;
          reject(error); return;
        }
        if (data.started === true) {
          if (!Number.isFinite(data.startContextTime)) { reject(new Error('capture_failed')); return; }
          if (context.state !== 'running' || stream.getAudioTracks().some(t => t.muted === true || t.readyState === 'ended')) { reject(interrupted('start_route')); return; }
          if (!started) { started = true; recordingAt = clock(); stage = 'recording'; timers.clearTimeout(startupTimer); onRecording(); }
          return;
        }
        if (!(data.samples instanceof Float32Array) || !Number.isFinite(data.endContextTime) || !(data.sampleRate >= 4000 && data.sampleRate <= 192000)) { reject(new Error('capture_failed')); return; }
        const receivedAt = env.performance.now();
        const lag = Math.max(0, context.currentTime - data.endContextTime);
        resolve({ samples: data.samples, sampleRate: data.sampleRate, endedAt: receivedAt - lag * 1000, durationSeconds: data.samples.length / data.sampleRate });
      };
    });
    source.connect(node); node.connect(mute); mute.connect(context.destination);
    stateChangedIfNeeded();
    function stateChangedIfNeeded() {
      if (context.state !== 'running') Promise.resolve(context.resume()).catch(() => {});
    }
    return await abortable(complete, localSignal);
  } catch (error) {
    if (budgetTimedOut) throw budgetError();
    if (startupTimedOut) { const failure = new Error('capture_start_timeout'); failure.captureStage = stage; throw failure; }
    error.captureStage = stage; throw error;
  } finally {
    timers.clearTimeout(startupTimer); timers.clearTimeout(microphoneTimer); signal.removeEventListener('abort', cancel); operation.abort();
    detach(); stopStream(stream); stoppedAt = clock();
    for (const item of [source, node, mute]) { try { item?.disconnect(); } catch { /* Release remaining resources. */ } }
    if (node) { node.port.onmessage = null; node.onprocessorerror = null; node.port.close(); }
    if (context && context.state !== 'closed') await context.close().catch(() => {});
    // Observational callbacks cannot prevent microphone cleanup or alter retries.
    try { onTiming({
      permissionMs: permissionStarted === undefined ? null : (grantedAt ?? stoppedAt) - permissionStarted,
      startupMs: grantedAt === undefined ? null : (recordingAt ?? stoppedAt) - grantedAt,
      captureMs: recordingAt === undefined ? null : stoppedAt - recordingAt,
      microphoneObservedMs: grantedAt === undefined ? null : stoppedAt - grantedAt,
      attemptMs: stoppedAt - attemptStarted,
    }); } catch { /* Diagnostics are best effort. */ }
  }
}

// Retry only a transient input interruption, with a completely new PCM window.
// Each failed attempt has stopped its tracks and closed its context before retry.
export async function captureFingerprintAudio(options) {
  const {signal, env = globalThis, onRecovering = () => {}} = options;
  const timers = env.setTimeout ? env : globalThis;
  const limit = options.microphoneBudgetMs ?? MAX_MICROPHONE_MS;
  let occupiedMs = 0;
  for (let attempt = 0; attempt < 3; attempt++) {
    try { return await captureFingerprintAttempt({...options, microphoneBudgetMs: limit - occupiedMs, onTiming: value => {
      const occupied = value.microphoneObservedMs;
      if (Number.isFinite(occupied) && occupied >= 0) occupiedMs += occupied;
      options.onTiming?.(value);
    }}); }
    catch (error) {
      if (signal.aborted) throw abortError();
      const transient = error.message === 'capture_interrupted' && error.captureDetail !== 'channel_shape' || error.message === 'audio_context_interrupted';
      if (!transient || attempt === 2) throw error;
      if (limit - occupiedMs < (options.seconds ?? 10) * 1000) throw budgetError();
      onRecovering({attempt: attempt + 1});
      let timer;
      try { await abortable(new Promise(resolve => { timer = timers.setTimeout(resolve, 600); }), signal); }
      finally { timers.clearTimeout(timer); }
    }
  }
}
