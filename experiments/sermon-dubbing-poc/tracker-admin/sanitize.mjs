/** Explicit public projection: unknown fields cannot reach Firestore. */
const PAGE_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$/;
const LOCALE = /^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$/;
const STEP = /^L[1-4]-\d{2}(?:@[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*)?$/;
const STATUS = ['pending', 'running', 'waiting_review', 'blocked', 'complete'];
const DELIVERY = ['unknown', 'not_generated', 'generated_local', 'http_verified',
  'declared_unchecked', 'index_missing', 'hash_mismatch', 'binding_invalid',
  'legacy_catalog_local', 'legacy_catalog_http_verified', 'legacy_track_listed',
  'legacy_track_http_verified', 'release_candidate', 'published_http_verified',
  'human_reviewed', 'candidate', 'withdrawn', 'unavailable', 'poc_catalog_local',
  'poc_catalog_http_verified', 'poc_track_listed', 'poc_track_http_verified',
  'machine_review_pass_human_review_pending'];
const enumValue = (value, allowed, fallback = 'unknown') => allowed.includes(value) ? value : fallback;
const number = (value) => Number.isFinite(value) && value >= 0 ? value : 0;
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
  if (!input || input.schemaVersion !== 'sermon-public-tracker-snapshot-v1'
      || !PAGE_ID.test(input.pageId || '') || !['dev', 'production'].includes(input.target)
      || !Array.isArray(input.locales) || !Array.isArray(input.steps)
      || !input.source || !input.progress || input.readOnly !== true) {
    throw new Error('invalid tracker snapshot');
  }
  if (Buffer.byteLength(JSON.stringify(input), 'utf8') > 512 * 1024) throw new Error('snapshot too large');
  const source = input.source;
  const progress = input.progress;
  return {
    schemaVersion: 'sermon-public-tracker-snapshot-v1', pageId: input.pageId,
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
    })),
  };
}
