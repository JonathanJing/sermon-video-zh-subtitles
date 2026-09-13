import { captureFingerprintAudio, microphoneSupported, abortError } from './fingerprint-capture.mjs';
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
  const messages={MIC_START_TIMEOUT:'麦克风已获许可，但音频数据没有及时开始。请保持页面在前台后重试。',INPUT_INTERRUPTED:'录音过程中声音输入中断，请重新听取。',AUDIO_INTERRUPTED:'系统中断了音频会话，请保持页面在前台后重试。',MIC_BUSY:'系统未能打开麦克风，请结束正在占用麦克风的通话或录音后重试。',MIC_MISSING:'系统未找到可用麦克风。',MIC_ENDED:'麦克风连接已结束，请重新听取。',WORKLET_LOAD:'录音组件加载失败，请刷新页面后重试。',PROCESSOR_ERROR:'录音组件运行失败，请刷新页面后重试。',AUDIO_START:'系统音频会话未能启动，请保持页面在前台后重试。',INDEX_UNAVAILABLE:'声音已采集，但定位索引下载失败，请检查网络后重试。'};
  return `${messages[diagnostic.code] || '定位未完成，请重试或手动定位。'}（诊断 ${diagnostic.code}${diagnostic.detail ? ':' + diagnostic.detail : ''} / ${diagnostic.stage} · ${diagnostic.version}）`;
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
export function createFingerprintController({ context, pause, seek, play, position = () => NaN, onState = () => {}, capture = captureFingerprintAudio, match = matchInWorker, supported = microphoneSupported, now = () => performance.now(), timers = globalThis, expirySeconds = 15, autoApply = true }) {
  let serial = 0, active = null, result = null, expiryTimer = null, pendingPlay = null;
  let state = { phase: 'idle' };
  const emit = value => { state = value; onState(value); };
  const clearExpiry = () => { timers.clearTimeout(expiryTimer); expiryTimer = null; };
  function cancel(reason = 'cancelled') {
    const pending = pendingPlay; pendingPlay = null;
    serial++; active?.abort(); active = null; result = null; clearExpiry();
    if (pending) { pending.controller.abort(); pause(); }
    emit({ phase: reason });
  }
  const valid = (token, binding) => serial === token && key(binding) === key(fingerprintBinding(context()));
  function targetFor(item) {
    const elapsed = (now() - item.endedAt) / 1000, target = item.end + elapsed;
    return valid(item.token, item.binding) && elapsed >= 0 && elapsed < expirySeconds && target < item.binding.metadata.sourceEndSeconds - item.binding.metadata.sourceStartSeconds ? target : null;
  }
  async function start() {
    cancel('idle');
    const binding = fingerprintBinding(context());
    if (!binding) { emit({ phase: 'unavailable' }); return; }
    if (!supported()) { emit({ phase: 'unsupported' }); return; }
    const token = serial, controller = new AbortController(); active = controller;
    pause(); emit({ phase: 'permission' });
    let timedOut = false;
    const timeout = timers.setTimeout(() => { timedOut = true; controller.abort(); }, 35000);
    try {
      const recording = await capture({ seconds: 10, signal: controller.signal, onRecovering: () => { if (valid(token, binding)) emit({ phase: 'recovering' }); }, onPreparing: () => { if (valid(token, binding)) emit({ phase: 'starting' }); }, onRecording: () => { if (valid(token, binding)) emit({ phase: 'recording' }); } });
      if (!valid(token, binding) || controller.signal.aborted) return;
      if (!Number.isFinite(recording.endedAt) || !Number.isFinite(recording.durationSeconds) || recording.durationSeconds < 9 || recording.durationSeconds > 11 || recording.endedAt > now() + 50) throw new Error('capture_failed');
      emit({ phase: 'matching' });
      const answer = await match(recording, binding.metadata, controller.signal);
      if (!valid(token, binding) || controller.signal.aborted) return;
      const found = answer.result;
      if (!found?.matched) { emit({ phase: 'no_match', reason: found?.diagnostics?.reason || 'low_confidence' }); return; }
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
      if (!seek(target, { correction: Boolean(item.positioned) })) { failed(); return false; }
      item.positioned = true;
      Promise.resolve(play({ signal: pending.controller.signal })).then(() => {
        if (!current()) { if (pendingPlay === pending) cancel('cancelled'); return; }
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
  return { start, apply, cancel, playbackStarted() { if (!pendingPlay) this.invalidate(); }, invalidate() { if (active || result || pendingPlay) cancel('cancelled'); }, getState: () => state, available: () => Boolean(fingerprintBinding(context())) };
}

function clock(seconds) {
  const n = Math.floor(seconds), mm = String(Math.floor(n / 60) % 60).padStart(2, '0'), ss = String(n % 60).padStart(2, '0');
  return n >= 3600 ? `${Math.floor(n / 3600)}:${mm}:${ss}` : `${mm}:${ss}`;
}
export function mountFingerprintUI(options) {
  const $ = id => document.getElementById(id);
  const dialog = $('fingerprint-dialog');
  const messages = {
    idle: '听取后会自动对齐并播放中文，请保持英文原视频连续播放。', permission: '等待麦克风许可… 中文已暂停。',
    recovering: '声音输入短暂中断，正在重新连接；将重新听取完整 10 秒…',
    starting: '麦克风已获许可，正在等待声音输入…', recording: '正在听取约 10 秒英文原声…', matching: '采集已停止，正在设备内匹配…',
    cancelled: '已取消。中文保持暂停，可自行播放。', unavailable: '本期尚未提供现场声音定位。',
    unsupported: '当前浏览器不支持安全麦克风采集，请使用 HTTPS 页面上的新版 Safari 或 Chrome，或手动定位。',
    permission_denied: '未获得麦克风权限。可在浏览器设置中允许，或继续手动定位。',
    timeout: '等待超时，已停止采集。请重试或手动定位。', error: '定位未完成，已停止采集。请重试或手动定位。',
    no_match: '未找到可靠位置：可能有噪声、静音或当前视频不一致。请重试或手动定位。',
    expired: '结果已过期或播放内容已切换，请重新定位。', play_starting: '已找到位置，正在跟上并开始播放…', play_blocked: '浏览器需要你再点一次。点击下方按钮，会按此刻的位置跟上播放。', play_failed: '中文尚未开始播放。可点击下方按钮重试，会重新补偿等待时间。',
  };
  const controller = createFingerprintController({ ...options, onState(value) {
    const busy = ['permission', 'starting', 'recovering', 'recording', 'matching', 'play_starting'].includes(value.phase);
    $('fingerprint-start').disabled = busy;
    $('fingerprint-start').textContent = value.phase === 'idle' ? '听取后自动对齐播放' : '重新听取并跟上';
    $('fingerprint-apply').hidden = !['matched', 'play_blocked', 'play_failed'].includes(value.phase);
    $('fingerprint-apply').textContent = '一键跟上播放';
    $('fingerprint-message').textContent = value.phase === 'matched' ? `已找到原视频 ${clock(value.sourceTimeSeconds)} 的位置，正在自动跟上。` : value.phase === 'applied' ? `已跟上原视频 ${clock(value.sourceTimeSeconds)} 并开始播放。` : value.phase === 'error' && value.diagnostic ? diagnosticMessage(value.diagnostic) : messages[value.phase] || messages.error;
    if (value.phase === 'applied' && dialog.open) dialog.close();
  } });
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
