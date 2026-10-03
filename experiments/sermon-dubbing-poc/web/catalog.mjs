// Publication presentation is independent of human listening/content review.
export function isFormalPlayback(week) {
  return week?.releaseLabel === "正式播放版";
}

const blockKey = value => typeof value === 'string' ? value : Number.isSafeInteger(value) && value >= 0 ? String(value) : null;
const validBlockKey = value => typeof value === 'string' && value.length > 0 && value.length <= 128 && value.trim() === value && !/[\u0000-\u001f\u007f]/.test(value);

function validateTranscript(week) {
  const transcript = week.transcript;
  if (transcript == null) return;
  if (transcript.schemaVersion !== 'sermon-bilingual-transcript-v1' || !Array.isArray(transcript.blocks)) throw new Error('Invalid bilingual transcript');
  const ids = new Set();
  for (const block of transcript.blocks) {
    if (!validBlockKey(block.blockId) || ids.has(block.blockId)
        || [block.sourceTextOrigin, block.reviewState, ...[block.english, block.chinese].filter(v => v != null)]
          .some(v => typeof v !== 'string' || !v.trim())) throw new Error('Invalid bilingual source block');
    ids.add(block.blockId);
  }
  for (const cue of week.tracks.flatMap(t => t.cues)) {
    if (cue.blockId != null && (!validBlockKey(blockKey(cue.blockId)) || (ids.size && !ids.has(blockKey(cue.blockId))))) throw new Error('Unlinked bilingual cue');
  }
}

// Same association rule as iOS: show the complete English source once, after
// the last Chinese cue bearing its ID. Never infer links from text or timing.
export function bilingualCueRows(week, track) {
  const originals = new Map(), ambiguous = new Set(), lastCue = new Map();
  if (week?.transcript?.schemaVersion === 'sermon-bilingual-transcript-v1') {
    for (const block of week.transcript.blocks) {
      if (originals.has(block.blockId)) ambiguous.add(block.blockId);
      originals.set(block.blockId, block);
    }
  }
  track.cues.forEach((cue, index) => {
    const id = blockKey(cue.blockId);
    if (id != null) lastCue.set(id, index);
  });
  let missingEnglish = false;
  const rows = track.cues.map((cue, index) => {
    const id = blockKey(cue.blockId), block = ambiguous.has(id) ? null : originals.get(id);
    const hasEnglish = typeof block?.english === 'string' && !!block.english.trim();
    if (!hasEnglish) missingEnglish = true;
    return { cue, index, english: hasEnglish && lastCue.get(id) === index ? block.english : null };
  });
  return { rows, hasEnglish: rows.some(row => row.english != null), missingEnglish };
}

export function validateCatalog(catalog) {
  if (catalog?.schemaVersion !== "sermon-weekly-catalog-v1" || !catalog.weeks?.length) throw new Error("Invalid catalog");
  const ids = new Set();
  for (const week of catalog.weeks) {
    if (ids.has(week.id) || !week.title || !week.speaker || !Array.isArray(week.tracks)) throw new Error("Invalid week");
    ids.add(week.id);
    validateTranscript(week);
    for (const track of week.tracks) {
      if (!/^\/media\/(?:[a-zA-Z0-9_-]+\/)*[a-zA-Z0-9_.-]+\.(?:mp3|wav)$/.test(track.audioUrl) || !(track.durationSeconds > 0) || !track.cues?.length) throw new Error("Invalid track");
      let previous = 0;
      for (const cue of track.cues) {
        if (!(previous <= cue.start && cue.start < cue.end && cue.end <= track.durationSeconds + 0.001) || !cue.text?.trim()) throw new Error("Invalid cues");
        previous = cue.end;
      }
    }
  }
  if (!ids.has(catalog.defaultWeekId)) throw new Error("Missing default week");
  for (const speaker of catalog.voiceBank?.speakers || []) {
    if (!speaker.name || !speaker.id) throw new Error("Invalid speaker");
    for (const key of ["reference", "chinese"]) {
      const track = speaker[key];
      if (!/^\/media\/[a-zA-Z0-9_.-]+\.mp3$/.test(track?.audioUrl) || !(track.durationSeconds > 0)) throw new Error("Invalid speaker audition");
    }
  }
  return catalog;
}

export function chooseWeek(catalog, id) {
  return catalog.weeks.find(w => w.id === id)
    || catalog.weeks.find(w => w.date === id && w.sourceRoute === 'same_video')
    || catalog.weeks.find(w => w.date === id)
    || catalog.weeks.find(w => w.id === catalog.defaultWeekId);
}

// Navigation uses the source page ID. Feedback, usage and playback bookmarks
// retain their date contract and distinguish versions by the exported track ID.
export function engagementWeek(week) {
  return week ? { ...week, id: week.date || week.id } : null;
}

export function downloadFilename(week, track) {
  // Use the sermon week, not the download date; keep names portable across OSes.
  const clean = value => String(value).normalize("NFC")
    .replace(/[<>:"/\\|?*\u0000-\u001f\u007f]/g, " ")
    .replace(/\s+/g, " ").trim().replace(/[. ]+$/g, "");
  const speaker = week.speaker.split(" · ")[0];
  const parts = [week.date, week.targetLocale ? `证道配音_${week.targetLocale}` : "证道中文转译", week.title, speaker];
  const sourceLabels = { live_archive: '主日聚会版', same_video: 'YouTube 版', archive_caption: 'YouTube 版' };
  const sourceLabel = week.sourceLabel?.trim() || sourceLabels[week.sourceRoute];
  if (sourceLabel && !week.title.includes(sourceLabel)) parts.push(sourceLabel);
  if (isFormalPlayback(week)) {
    if (!parts.some(part => String(part).includes("正式播放版"))) parts.push("正式播放版");
  } else if (week.humanContentReview === "approved") {
    // Content review is independent of video synchronization.
  } else if (track.scope === "full_candidate") {
    parts.push(track.subtitleTiming === "source_video_aligned_candidate" ? "同步试播" : "试听稿");
  } else if (track.scope !== "full_reviewed") {
    parts.push("样片", track.label);
  }
  const extension = track.audioUrl?.toLowerCase().endsWith('.wav') ? 'wav' : 'mp3';
  return `${parts.map(clean).filter(Boolean).join("_")}.${extension}`;
}


export function weekOptionLabel(week) {
  const date = String(week.date || week.id || '').replaceAll('-', '.');
  const title = typeof week.title === 'string' ? week.title.trim() : '';
  const route = typeof week.sourceLabel === 'string' ? week.sourceLabel.trim() : '';
  const diagnostic = diagnosticPresentation(week);
  const status = diagnostic ? ({failed:'处理失败',blocked:'流程受阻',pending:'待生成',ready:'DEV 可试听'})[diagnostic.status] : week.devCandidate === true ? 'DEV 可试听' : isFormalPlayback(week) ? '正式播放版' : week.humanContentReview === 'approved' ? '整篇中文' : week.audioStatus === 'full_candidate' ? '整篇待审' : week.tracks?.length ? '可试听' : '待配音';
  const displayStatus = isFormalPlayback(week) && [title, route].some(text => text.includes(status)) ? '' : status;
  return [date, title, route && !title.includes(route) ? route : '', displayStatus].filter(Boolean).join(' · ');
}

// Only diagnostic variants consume this state. Formal and legacy weeks retain
// their existing contracts. Public messages never display raw exception text.
const DIAGNOSTIC_REASONS = new Set(['machine_candidate_missing', 'preview_audio_unavailable',
  'strict_locale_group_not_passed', 'strict_bridge_plugin_rejected', 'invalid_candidate_coverage',
  'invalid_generated_candidate', 'invalid_review_response', 'provider_input_bound_exceeded',
  'provider_request_limit', 'provider_cost_limit', 'provider_run_deadline_reached',
  'provider_outcome_reconciliation_required', 'provider_configuration_stopped',
  'preview_worker_failed_requires_reconciliation',
  'native_runtime_unavailable', 'diagnostic_state_binding_invalid', 'unclassified_failure',
  'diagnostic_flow_plan_changed', 'diagnostic_flow_frozen_inputs_changed', 'diagnostic_unbounded_subprocess_forbidden', 'historical_current_code_changed', 'historical_identity_file_changed_during_read', 'historical_identity_file_missing', 'historical_identity_file_not_regular_or_too_large', 'historical_identity_fixed_repository_required', 'historical_identity_git_inspection_failed', 'historical_identity_git_or_tree_changed', 'historical_identity_git_path_invalid', 'historical_identity_head_invalid', 'historical_identity_tracked_inventory_invalid', 'historical_identity_tracked_inventory_too_large', 'historical_identity_witness_changed', 'invalid_snapshot_file']);
export function diagnosticPresentation(week) {
  if (week?.diagnosticOnly !== true) return null;
  const typed = week.diagnosticState;
  const hasActualText = Array.isArray(week.fullTranscript) && week.fullTranscript.length > 0
    && week.fullTranscript.every(row => typeof row?.text === 'string' && row.text.trim().length > 0);
  let hasCandidate = hasActualText;
  let status = hasCandidate ? (week.tracks?.length ? 'ready' : 'pending') : 'blocked';
  let reasonCode = hasCandidate ? (week.tracks?.length ? null : 'preview_audio_unavailable') : 'machine_candidate_missing';
  if (typed) {
    const valid = typed.schemaVersion === 'sermon-dev-diagnostic-presentation-v1'
      && ['failed','blocked','pending','ready'].includes(typed.status)
      && typeof typed.machineCandidateAvailable === 'boolean'
      && typed.targetLocale === week.targetLocale
      && /^[a-f0-9]{64}$/.test(typed.inputBindingSha256 || '')
      && typed.inputBindingSha256 === week.diagnosticInputSha256
      && (!typed.machineCandidateAvailable || (hasActualText && /^[a-f0-9]{64}$/.test(typed.candidateSha256 || '')));
    if (valid) {
      hasCandidate = typed.machineCandidateAvailable;
      status = typed.status;
      reasonCode = typeof typed.reasonCode === 'string' && DIAGNOSTIC_REASONS.has(typed.reasonCode)
        ? typed.reasonCode : typed.reasonCode == null ? null : 'unclassified_failure';
    } else { hasCandidate = false; status = 'blocked'; reasonCode = 'diagnostic_state_binding_invalid'; }
  }
  if (status === 'ready' && (!hasCandidate || !week.tracks?.length)) {
    status = 'blocked'; reasonCode = hasCandidate ? 'preview_audio_unavailable' : 'machine_candidate_missing';
  }
  return { status, statusKey:`app.diagnostic.${status}`, reasonCode, hasCandidate,
    canPlay: status === 'ready' && hasCandidate && Boolean(week.tracks?.length),
    stages: [
      { labelKey:'app.diagnostic.text', status:hasCandidate?'pass':status, detailKey:hasCandidate?'app.diagnostic.textReady':'app.diagnostic.textMissing' },
      { labelKey:'app.diagnostic.audio', status:status==='ready'?'review':status, detailKey:`app.diagnostic.${status}` },
      { labelKey:'app.diagnostic.review', status:'pending', detailKey:'app.diagnostic.reviewPending' },
      { labelKey:'app.diagnostic.delivery', status:'pending', detailKey:'app.diagnostic.previewOnly' },
    ] };
}

export function parseTimecode(value) {
  const match = /^(?:(\d{1,2}):)?(\d{1,3}):(\d{2})(?:\.(\d{1,2}))?$/.exec(value.trim());
  if (!match || Number(match[3]) >= 60 || (match[1] && Number(match[2]) >= 60)) return null;
  return Number(match[1] || 0) * 3600 + Number(match[2]) * 60 + Number(match[3]) + Number(`0.${match[4] || 0}`);
}
