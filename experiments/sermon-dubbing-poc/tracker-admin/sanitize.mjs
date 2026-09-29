/** Explicit public projection: unknown fields cannot reach Firestore. */
const PAGE_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$/;
const LOCALE = /^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$/;
const STEP = /^L[1-4]-\d{2}(?:@[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*)?$/;
const STATUS = ['pending', 'running', 'waiting_review', 'blocked', 'complete'];
const TIMELINE_SCHEMA = 'sermon-tracker-relative-timeline-v1';
const MAX_TIMELINE_SECONDS = 366 * 24 * 60 * 60;
const SUBSTEP_CODES = {
  'L1-02': ['transcribe', 'align', 'freeze'],
  'L1-03': ['anchors', 'boundary_check'],
  'L2-02': ['group', 'translator', 'reviewer', 'repair'],
  'L2-03': ['coverage', 'language', 'admission'],
  'L3-02': ['inputs', 'validate', 'model_load', 'render_units', 'unit', 'assemble'],
  'L3-03': ['decode', 'hash', 'asr'],
  'L3-04': ['schedule', 'captions', 'mix'],
  'L4-02': ['build', 'upload'],
  'L4-03': ['get', 'range'],
};
const DELIVERY = ['unknown', 'not_generated', 'generated_local', 'http_verified',
  'declared_unchecked', 'index_missing', 'hash_mismatch', 'binding_invalid',
  'legacy_catalog_local', 'legacy_catalog_http_verified', 'legacy_track_listed',
  'legacy_track_http_verified', 'release_candidate', 'published_http_verified',
  'human_reviewed', 'candidate', 'withdrawn', 'unavailable', 'poc_catalog_local',
  'poc_catalog_http_verified', 'poc_track_listed', 'poc_track_http_verified',
  'machine_review_pass_human_review_pending'];
const enumValue = (value, allowed, fallback = 'unknown') => allowed.includes(value) ? value : fallback;
const number = (value) => Number.isFinite(value) && value >= 0 ? value : 0;
const elapsed = (value) => Number.isInteger(value) && value >= 0 && value <= 366 * 24 * 60 * 60 ? value : null;
const offset = (value, duration) => Number.isFinite(value) && value >= 0 && value <= duration
  ? Math.round(value * 10) / 10 : null;

function publicTimeline(value, stepIds) {
  if (value?.schemaVersion !== TIMELINE_SCHEMA || value.axis !== 'seconds_since_first_recorded_event'
      || !Number.isFinite(value.durationSeconds) || value.durationSeconds < 0
      || value.durationSeconds > MAX_TIMELINE_SECONDS || !Array.isArray(value.rows)) return null;
  const durationSeconds = Math.round(value.durationSeconds * 10) / 10;
  const spans = (items, max, allowed) => (Array.isArray(items) ? items : []).slice(0, max)
    .map((item) => ({ startSeconds: offset(item?.startSeconds, durationSeconds),
      endSeconds: offset(item?.endSeconds, durationSeconds),
      kind: allowed.includes(item?.kind) ? item.kind : null }))
    .filter((item) => item.startSeconds !== null && item.endSeconds !== null
      && item.startSeconds <= item.endSeconds && item.kind);
  const rows = value.rows.slice(0, 100).filter((item) => stepIds.has(item?.id)).map((item) => {
    const allowed = SUBSTEP_CODES[item.id.split('@')[0]] || [];
    return { id: item.id,
      intervals: spans(item.intervals, 12, ['running', 'waiting_review', 'blocked']),
      attempts: spans(item.attempts, 8, ['measured']),
      completedAtSeconds: offset(item.completedAtSeconds, durationSeconds),
      substeps: (Array.isArray(item.substeps) ? item.substeps : []).slice(0, allowed.length)
        .filter((child) => allowed.includes(child?.code)).map((child) => ({
          code: child.code,
          dependsOn: (Array.isArray(child.dependsOn) ? child.dependsOn : [])
            .filter((code) => allowed.includes(code)).slice(0, 3),
          observedCount: Number.isInteger(child.observedCount) && child.observedCount >= 0
            && child.observedCount <= 100000 ? child.observedCount : 0,
          longestSeconds: offset(child.longestSeconds, MAX_TIMELINE_SECONDS),
          attempts: spans(child.attempts, 5, ['measured']),
        })),
    };
  });
  return { schemaVersion: TIMELINE_SCHEMA, axis: 'seconds_since_first_recorded_event',
    durationSeconds, coverage: {
      measuredSteps: Math.min(rows.length, number(value.coverage?.measuredSteps)),
      plannedSubsteps: rows.reduce((total, row) => total + row.substeps.length, 0),
      measuredSubsteps: rows.reduce((total, row) => total
        + row.substeps.filter((child) => child.observedCount > 0).length, 0),
    }, rows };
}
const stamp = (value) => typeof value === 'string' && /^\d{4}-\d\d-\d\dT/.test(value)
  && !Number.isNaN(Date.parse(value)) ? value : null;
const row = (value) => ({ layer: [1, 2, 3, 4].includes(value?.layer) ? value.layer : null,
  locale: LOCALE.test(value?.locale || '') ? value.locale : null,
  complete: number(value?.complete), total: number(value?.total),
  percent: Math.min(100, number(value?.percent)) });
function publicUrl(value, source = false) {
  try {
    const url = new URL(value);
    if (url.protocol !== 'https:' || url.username || url.password || url.hash) return null;
    if (source) {
      if (url.hostname !== 'marinerschurch.org' && !url.hostname.endsWith('.marinerschurch.org')) return null;
      if (url.search) return null;
    } else if (url.pathname !== '/' || [...url.searchParams.keys()].some((key) => !['week', 'lang'].includes(key))) {
      return null;
    }
    return url.href.length <= 2048 ? url.href : null;
  } catch { return null; }
}

export function sanitizeSnapshot(input) {
  if (!input || !['sermon-public-tracker-snapshot-v1', 'sermon-public-tracker-snapshot-v2'].includes(input.schemaVersion)
      || !PAGE_ID.test(input.pageId || '') || !['dev', 'production'].includes(input.target)
      || !Array.isArray(input.locales) || !Array.isArray(input.steps)
      || !input.source || !input.progress || input.readOnly !== true) {
    throw new Error('invalid tracker snapshot');
  }
  if (Buffer.byteLength(JSON.stringify(input), 'utf8') > 512 * 1024) throw new Error('snapshot too large');
  const hasElapsed = input.schemaVersion === 'sermon-public-tracker-snapshot-v2';
  const source = input.source;
  const progress = input.progress;
  const missingTimingStepIds = input.steps.slice(0, 150)
    .filter((step) => STEP.test(step?.id || '') && step.status === 'complete'
      && step.timing?.measuredExecutionSeconds == null)
    .map((step) => step.id);
  const publicStepIds = new Set(input.steps.slice(0, 150)
    .filter((step) => STEP.test(step?.id || '')).map((step) => step.id));
  return {
    // Upgrade existing v1 records to v2; missing elapsed counters remain null.
    schemaVersion: 'sermon-public-tracker-snapshot-v2', pageId: input.pageId,
    target: input.target,
    serviceDate: /^\d{4}-\d\d-\d\d$/.test(input.serviceDate || '') ? input.serviceDate : null,
    generatedAt: stamp(input.generatedAt), ledgerUpdatedAt: stamp(input.ledgerUpdatedAt),
    readOnly: true,
    source: {
      inputPageUrl: publicUrl(source.inputPageUrl, true),
      inputPageConfigured: source.inputPageConfigured === true,
      monitorStatus: enumValue(source.monitorStatus, ['not_checked', 'source_detected', 'fallback', 'unknown']),
      checkedAt: stamp(source.checkedAt), videoPresent: source.videoPresent === true,
      videoState: enumValue(source.videoState, ['was_live', 'available', 'manual_available', 'live', 'upcoming', 'unknown', null]),
      videoChange: enumValue(source.videoChange, ['not_checked', 'not_detected', 'video_id_unknown', 'first_seen', 'updated', 'unchanged']),
      lastChangeAt: stamp(source.lastChangeAt),
    },
    progress: {
      complete: number(progress.complete), total: number(progress.total),
      blockerCount: number(progress.blockerCount),
      blockedStepIds: (Array.isArray(progress.blockedStepIds) ? progress.blockedStepIds : [])
        .filter((id) => typeof id === 'string' && STEP.test(id)).slice(0, 100),
      missingEstimateCount: number(progress.missingEstimateCount),
      activeUnits: (Array.isArray(progress.activeUnits) ? progress.activeUnits : []).slice(0, 100)
        .filter((item) => STEP.test(item?.step || ''))
        .map((item) => ({ step: item.step, done: number(item.done), total: number(item.total),
          percent: Math.min(100, number(item.percent)) })),
      earliestContinuousEta: stamp(progress.earliestContinuousEta),
      remainingSerialMinutes: progress.remainingSerialMinutes == null ? null : number(progress.remainingSerialMinutes),
    },
    timingCoverage: {
      measuredStepCount: number(input.timingCoverage?.measuredStepCount),
      damagedAccountingRows: number(input.timingCoverage?.damagedAccountingRows),
      completedWithoutMeasuredExecutionCount: missingTimingStepIds.length,
      completedWithoutMeasuredExecutionStepIds: missingTimingStepIds,
    },
    timeline: publicTimeline(input.timeline, publicStepIds),
    sharedLayer1: row(input.sharedLayer1),
    locales: input.locales.slice(0, 20).filter((item) => LOCALE.test(item?.locale || '')).map((item) => ({
      locale: item.locale,
      layers: Object.fromEntries([2, 3, 4].map((layer) => [String(layer), row(item.layers?.[String(layer)])])),
      delivery: {
        pageStatus: enumValue(item.delivery?.pageStatus, DELIVERY),
        pageUrl: publicUrl(item.delivery?.pageUrl),
        voiceStatus: enumValue(item.delivery?.voiceStatus, DELIVERY),
        voicePublished: item.delivery?.voicePublished === true,
        fingerprint: { status: enumValue(item.delivery?.fingerprint?.status, DELIVERY) },
        pocCandidateStatus: enumValue(item.delivery?.pocCandidateStatus, DELIVERY),
        pocScreeningStatus: enumValue(item.delivery?.pocScreeningStatus, ['pass', 'requires_review', 'fail']),
        pocVoiceReview: enumValue(item.delivery?.pocVoiceReview, ['pending', 'approved', 'rejected']),
        origin: enumValue(item.delivery?.origin, ['canonical_release_package', 'legacy_catalog_v1', 'dev_poc_catalog', 'no_release_evidence']),
      },
      acceptance: Object.fromEntries(['device', 'venue'].map((kind) => [kind, {
        status: enumValue(item.acceptance?.[kind]?.status, ['not_run', 'pending', 'passed', 'failed', 'blocked']),
      }])),
    })),
    steps: input.steps.slice(0, 150).filter((step) => STEP.test(step?.id || '')).map((step) => ({
      id: step.id, layer: [1, 2, 3, 4].includes(step.layer) ? step.layer : null,
      locale: LOCALE.test(step.locale || '') ? step.locale : null,
      status: enumValue(step.status, STATUS, 'pending'),
      doneUnits: step.doneUnits == null ? null : number(step.doneUnits),
      totalUnits: step.totalUnits == null ? null : number(step.totalUnits),
      timing: {
        executionAttempts: number(step.timing?.executionAttempts),
        failedExecutionAttempts: number(step.timing?.failedExecutionAttempts),
        measuredExecutionSeconds: step.timing?.measuredExecutionSeconds == null ? null : number(step.timing.measuredExecutionSeconds),
        lastExecutionStatus: enumValue(step.timing?.lastExecutionStatus, ['completed', 'failed'], null),
        lastExecutionAt: stamp(step.timing?.lastExecutionAt),
        openExecution: step.timing?.openExecution === true,
        openExecutionElapsedSeconds: hasElapsed && step.timing?.openExecution === true
          ? elapsed(step.timing?.openExecutionElapsedSeconds) : null,
        statusElapsedSeconds: hasElapsed && ['running', 'waiting_review'].includes(step.status)
          ? elapsed(step.timing?.statusElapsedSeconds) : null,
        closedReviewWaits: number(step.timing?.closedReviewWaits),
        operatorReviewWaitSeconds: step.timing?.operatorReviewWaitSeconds == null ? null : number(step.timing.operatorReviewWaitSeconds),
        openReviewWait: step.timing?.openReviewWait === true,
      },
    })),
  };
}
