/** Closed public view contract shared by publisher and browser. No raw logs or URLs. */
export const DAG_SCHEMA = 'sermon-public-tracker-dag-v1';
export const EXECUTORS = ['deterministic_program', 'production_model', 'decision_agent', 'human', 'external_service', 'engineering_codex', 'unknown'];
export const MODELS = ['gpt-6-astra', 'gpt-6-sol', 'gpt-6-luna', 'qwen3-asr', 'qwen3-tts', 'whisper'];
export const CODES = ['initial_translation', 'independent_review', 'unit_synthesis', 'audio_validation', 'schedule_sync', 'translation', 'review', 'asr', 'tts', 'validation', 'publication', 'source', 'unknown'];
export const STATUSES = ['completed', 'failed', 'cancelled', 'outcome_unknown', 'unfinished_or_ambiguous', 'pending', 'running', 'retrying', 'waiting_review', 'blocked', 'complete', 'unknown_outcome', 'queued'];
const MODES = ['real', 'synthetic', 'mixed', 'unknown'];
const COUNTS = ['processed', 'executionSucceeded', 'contentReviewPassed', 'realHumanApproved', 'simulatedHumanApproved', 'admitted', 'done', 'total'];
const REASONS = ["accounting_invalid", "accounting_missing", "accounting_partial", "accounting_too_large", "active_duration_exceeds_empirical_envelope", "blocked", "conflicting_event_identity", "conflicting_unit_sequence", "damaged_events", "evidence_mode_not_established", "future_observation", "heartbeat_or_active_elapsed_unknown", "human_review_remaining", "incomplete_or_conflicting_profile_events", "invalid_conflicting_or_unbound_receipt", "invalid_or_conflicting_empirical_sample", "ledger_run_binding_mismatch", "no_comparable_history", "node_limit", "observed_blocker", "other", "progress_inputs_invalid", "progress_partial", "progress_plan_missing", "progress_run_mismatch", "resource_queue_or_configuration_unknown", "resource_state_missing", "retry_or_reconciliation_not_authorized", "run_not_found", "running_dependency_unresolved", "running_units_contradict_available_resource_slots", "stale_observations", "synthetic_evidence_not_production_approval", "unit_queue_unknown", "unknown_attempt_outcome", "unknown_outcome", "unresolved_post_execution_gate", "unsupported_schema", "upstream_evidence_issue", "waiting_review"];
const pick = (value, values, fallback = 'unknown') => values.includes(value) ? value : fallback;
const number = (value, max = 366 * 24 * 3600) => typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= max ? value : null;
const count = (value) => Number.isSafeInteger(value) && value >= 0 && value <= 1000000 ? value : null;
const stamp = (value) => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value)) ? new Date(value).toISOString() : null;
const reasons = (value) => [...new Set((Array.isArray(value) ? value.slice(0, 40) : []).map((v) => pick(v, REASONS, 'other')))];
const id = (value) => typeof value === 'string' && /^[np][1-9][0-9]{0,3}$/.test(value) ? value : null;

function nodes(value, kind) {
  if (!Array.isArray(value) || value.length > 256 || value.some((n) => !id(n?.id))) return null;
  const ids = new Set(value.map((n) => n.id));
  if (ids.size !== value.length) return null;
  const result = value.map((n) => {
    const rawDeps = Array.isArray(n.dependsOn) ? n.dependsOn : [];
    const validDeps = [...new Set(rawDeps.filter((dep) => ids.has(dep)))];
    const timing = n.timing || {};
    const start = number(timing.startSeconds), end = number(timing.endSeconds);
    return { id:n.id, kind, code:pick(n.code,CODES), layer:[1,2,3,4].includes(n.layer) ? n.layer : null,
      locale:pick(n.locale,['en','zh-Hans','ko','es','vi']), executorType:pick(n.executorType,EXECUTORS),
      modelCodes:[...new Set((Array.isArray(n.modelCodes) ? n.modelCodes : []).filter((m) => MODELS.includes(m)))].slice(0,6),
      modelStatus:pick(n.modelStatus,['allowlisted','observed','not_observed','unknown','partial']),
      dependencyStatus:pick(n.dependencyStatus,['recorded','partial','unknown']),
      dependsOn:validDeps, unresolvedDependencyCount:(count(n.unresolvedDependencyCount) || 0) + rawDeps.filter((dep) => !ids.has(dep)).length,
      complete:n.complete === true, unknownOutcome:n.unknownOutcome === true,
      requiredEvidence:(Array.isArray(n.requiredEvidence) ? n.requiredEvidence : []).filter((v) => COUNTS.includes(v)).slice(0,6),
      heartbeatStatus:pick(n.heartbeatStatus,['fresh','stale','unknown','not_applicable']),
      status:pick(n.status, STATUSES), evidenceMode:pick(n.evidenceMode,MODES), attemptNumber:count(n.attemptNumber), retryCount:count(n.retryCount),
      timing:{status:pick(timing.status,['measured','unknown','not_observed','unfinished','partial']),
        startSeconds: start !== null && end !== null && end >= start ? start : null,
        endSeconds: start !== null && end !== null && end >= start ? end : null,
        elapsedSeconds:number(timing.elapsedSeconds), activeElapsedSeconds:number(timing.activeElapsedSeconds)},
      io:{status:pick(n.io?.status,['observed','not_observed','partial']), inputArtifactCount:count(n.io?.inputArtifactCount), outputArtifactCount:count(n.io?.outputArtifactCount)},
      evidence:Object.fromEntries(COUNTS.filter((k) => !['done','total'].includes(k)).map((k) => [k, typeof n.evidence?.[k] === 'boolean' ? n.evidence[k] : null])),
    };
  });
  // Reject cycles; a malformed DAG must not be rendered as a scheduling truth.
  const remaining = new Set(ids);
  while (remaining.size) {
    const ready = result.filter((n) => remaining.has(n.id) && !n.dependsOn.some((dep) => remaining.has(dep)));
    if (!ready.length) return null;
    ready.forEach((n) => remaining.delete(n.id));
  }
  return result;
}

export function sanitizeDag(value) {
  if (!value || value.schemaVersion !== DAG_SCHEMA || value.scope !== 'accounting_run'
      || value.executionAuthority !== 'none' || value.acceptance !== 'not_evaluated') return null;
  const observed = nodes(value.nodes, 'observed');
  if (!observed) return null;
  const planned = value.progress == null ? null : nodes(value.progress.nodes, 'planned');
  if (value.progress && !planned) return null;
  const summary = value.summary || {};
  const source = value.progress;
  const production = value.evidenceMode === 'real' && (!planned || planned.every((node) => node.evidenceMode === 'real'));
  if (planned) for (const node of planned) {
    if (!production || node.evidenceMode !== 'real') {
      node.complete = false;
      node.evidence.realHumanApproved = false;
      node.evidence.admitted = false;
    }
  }
  const progress = source ? {status:pick(source.status,['consistent','partial','known','unknown']), planVersion:count(source.planVersion),
    denominator:typeof source.denominator === 'string' && /^\d{1,12}(\.\d{1,6})?$/.test(source.denominator) ? source.denominator : null,
    plannedProcessedPercent:number(source.plannedProcessedPercent,100), knownProcessedPercentLowerBound:number(source.knownProcessedPercentLowerBound,100),
    gateCompletionPercent:production ? number(source.gateCompletionPercent,100) : null, complete:production && source.complete === true,
    counts:Object.fromEntries(COUNTS.map((k) => [k,!production && ['realHumanApproved','admitted','done'].includes(k) ? 0 : count(source.counts?.[k])])),
    extraWork:{retryAttempts:count(source.extraWork?.retryAttempts),reworkAttempts:count(source.extraWork?.reworkAttempts)}, nodes:planned} : null;
  if (progress) {
    for (const node of planned) {
      node.complete = node.complete && !node.unknownOutcome && node.status === 'complete'
        && node.requiredEvidence.includes('executionSucceeded')
        && node.requiredEvidence.every((key) => node.evidence[key] === true);
    }
    if (!planned.length || !planned.every((node) => node.complete) || progress.counts.done !== planned.length) {
      progress.complete = false;
      if (progress.gateCompletionPercent === 100) progress.gateCompletionPercent = null;
    }
  }
  const eta = value.eta || {};
  const lower = number(eta.lowerSeconds), upper = number(eta.upperSeconds);
  const planReady = production && progress?.status === 'consistent' && planned?.length > 0
    && progress.counts.total === planned.length && Number(progress.denominator) > 0;
  const etaReady = planReady && !planned.some((node) => node.unknownOutcome
    || ['blocked','waiting_review','unknown_outcome','outcome_unknown'].includes(node.status)
    || (node.status === 'running' && node.heartbeatStatus !== 'fresh'));
  const coherentComplete = planReady && progress.complete && progress.counts.done === planned.length && planned.every((node) => node.complete);
  const etaStatus = eta.status === 'complete' ? (coherentComplete && lower === 0 && upper === 0 ? 'complete' : 'unknown')
    : etaReady && eta.status === 'estimated' && lower !== null && upper !== null && upper >= lower ? 'estimated' : 'unknown';
  return {schemaVersion:DAG_SCHEMA,scope:'accounting_run',generatedAt:stamp(value.generatedAt),executionAuthority:'none',acceptance:'not_evaluated',
    evidenceMode:pick(value.evidenceMode,MODES),freshness:{status:pick(value.freshness?.status,['recent','fresh','stale','unknown','clock_skew']),sourceObservedAt:stamp(value.freshness?.sourceObservedAt),ageSeconds:number(value.freshness?.ageSeconds)},
    quality:{status:pick(value.quality?.status,['projected','partial','unavailable']),reasonCodes:reasons(value.quality?.reasonCodes),damagedRowCount:count(value.quality?.damagedRowCount),duplicateEventsIgnored:count(value.quality?.duplicateEventsIgnored),omittedNodeCount:count(value.quality?.omittedNodeCount)},
    summary:{observedNodeCount:Math.max(observed.length, count(summary.observedNodeCount) || 0),...Object.fromEntries(['completedSpanCount','unfinishedSpanCount','failedSpanCount','retryCount'].map((k) => [k,count(summary[k])])),measuredSpanSeconds:number(summary.measuredSpanSeconds),endToEndWallSeconds:number(summary.endToEndWallSeconds)},
    nodes:observed,criticalPath:{status:pick(value.criticalPath?.status,['measured','projected','partial','unknown','unavailable']),activeSeconds:number(value.criticalPath?.activeSeconds),nodeIds:(Array.isArray(value.criticalPath?.nodeIds) ? value.criticalPath.nodeIds : []).filter((v) => observed.some((n) => n.id === v)).slice(0,256),durationBasis:pick(value.criticalPath?.durationBasis,['verified_monotonic_dag','recorded_utc_intervals'], 'unknown')},
    io:{status:pick(value.io?.status,['observed','not_observed','partial']),beforeArtifactCount:count(value.io?.beforeArtifactCount),afterArtifactCount:count(value.io?.afterArtifactCount),scope:'observed_file_snapshots_not_execution_proof'},
    logs:{schemaVersions:(Array.isArray(value.logs?.schemaVersions) ? value.logs.schemaVersions : []).filter((v) => ['sermon-workflow-accounting-v1','sermon-workflow-accounting-v2','sermon-workflow-accounting-v3'].includes(v)).slice(0,3),contractVersions:Array.isArray(value.logs?.contractVersions) && value.logs.contractVersions.includes('sermon-accounting-log-contract-v1') ? ['sermon-accounting-log-contract-v1'] : [],...Object.fromEntries(['eventCount','profileEventCount','legacyEventCount','damagedRowCount'].map((k) => [k,count(value.logs?.[k])]))},
    progress,eta:{status:etaStatus,
      lowerSeconds:etaStatus === 'unknown' ? null : lower,upperSeconds:etaStatus === 'unknown' ? null : upper,remainingSerialSeconds:etaStatus === 'unknown' ? null : number(eta.remainingSerialSeconds),criticalPathSeconds:etaStatus === 'unknown' ? null : number(eta.criticalPathSeconds),sampleCount:count(eta.sampleCount),confidence:pick(eta.confidence,['low','medium','unknown']),reasonCodes:reasons(eta.reasonCodes),estimatorVersion:eta.estimatorVersion === 'remaining-dag-resource-slots-v1' ? eta.estimatorVersion : null},
  };
}
