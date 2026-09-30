// Session-only, coarse diagnostics. No storage, transport, PCM or landmark output.
const REASONS = new Set(['matched', 'silence', 'insufficient_audio', 'no_consensus', 'ambiguous', 'low_confidence', 'incompatible_index', 'incompatible_query']);
const CODES = new Set('MIC_START_TIMEOUT INPUT_INTERRUPTED AUDIO_INTERRUPTED MIC_ENDED PROCESSOR_ERROR INVALID_CAPTURE INDEX_MISMATCH INDEX_UNAVAILABLE MATCH_ERROR MIC_PERMISSION MIC_MISSING MIC_BUSY MIC_SETTINGS AUDIO_UNSUPPORTED WORKLET_LOAD AUDIO_START UNKNOWN'.split(' '));
const LEVELS = new Set(['silent', 'very_low', 'low', 'moderate', 'high', 'unknown']);
const CLIPPING = new Set(['none', 'under_1_percent', '1_to_5_percent', 'over_5_percent', 'unknown']);
const finite = value => typeof value === 'number' && Number.isFinite(value) && value >= 0;
const count = value => finite(value) ? Math.min(1000000, Math.floor(value)) : null;
const ms = value => finite(value) ? Math.min(3600000, Math.round(value / 100) * 100) : null;
export function matchReason(value) { return REASONS.has(value) ? value : 'unknown'; }
export function captureQuality(samples, rms) {
  let clipped = 0;
  for (const value of samples) {
    if (!Number.isFinite(value)) return { level: 'unknown', clipping: 'unknown' };
    if (Math.abs(value) >= .99) clipped++;
  }
  const fraction = samples.length ? clipped / samples.length : NaN;
  return {
    level: !finite(rms) ? 'unknown' : rms < .0001 ? 'silent' : rms < .001 ? 'very_low' : rms < .01 ? 'low' : rms < .1 ? 'moderate' : 'high',
    clipping: !Number.isFinite(fraction) ? 'unknown' : fraction === 0 ? 'none' : fraction < .01 ? 'under_1_percent' : fraction <= .05 ? '1_to_5_percent' : 'over_5_percent',
  };
}
export function summarizeMatch(query = {}, result = {}, quality = {}) {
  const d = result.diagnostics || {};
  return {
    reason: matchReason(d.reason),
    level: LEVELS.has(quality.level) ? quality.level : 'unknown',
    clipping: CLIPPING.has(quality.clipping) ? quality.clipping : 'unknown',
    landmarks: count(query.landmarks?.length), peaks: count(query.peakCount),
    supportingAnchors: count(d.distinctAnchors), votes: count(d.votes), runnerUpVotes: count(d.runnerUpVotes),
    coverageMs: ms(finite(d.coveredSeconds) ? d.coveredSeconds * 1000 : NaN),
  };
}
// Reconstruct every field at the final boundary; never spread an event/error object.
export function diagnosticSummary(value = {}) {
  const raw = value.match || {}, timing = value.timings || {}, content = value.content || {};
  const hashes = {};
  for (const key of ['sourceSha256', 'trackSha256', 'indexSha256']) if (typeof content[key] === 'string' && /^[a-f0-9]{64}$/.test(content[key])) hashes[key] = content[key];
  const phases = new Set(['idle', 'permission', 'starting', 'recording', 'recovering', 'matching', 'matched', 'no_match', 'error', 'permission_denied', 'unavailable', 'unsupported', 'expired', 'timeout', 'cancelled', 'play_starting', 'play_failed', 'play_blocked', 'applied']);
  const timings = {};
  for (const key of ['totalMs', 'permissionMs', 'startupMs', 'captureMs', 'microphoneObservedMs', 'indexMs', 'featureMs', 'matchMs', 'workerMs', 'seekCallMs', 'playStartMs']) timings[key] = ms(timing[key]);
  return {
    schemaVersion: 'sermon-fingerprint-diagnostics-v1',
    phase: phases.has(value.phase) ? value.phase : 'error',
    errorCode: CODES.has(value.errorCode) ? value.errorCode : null,
    profile: 'raw-v1', route: 'unknown', content: hashes,
    attempts: count(value.attempts), timings,
    match: {
      reason: matchReason(raw.reason), level: LEVELS.has(raw.level) ? raw.level : 'unknown',
      clipping: CLIPPING.has(raw.clipping) ? raw.clipping : 'unknown',
      landmarks: count(raw.landmarks), peaks: count(raw.peaks), supportingAnchors: count(raw.supportingAnchors),
      votes: count(raw.votes), runnerUpVotes: count(raw.runnerUpVotes), coverageMs: ms(raw.coverageMs),
    },
    // Native play promise is observable; acoustic output/caption alignment is not.
    audibleOutputMs: null, captionAlignmentMs: null,
  };
}
