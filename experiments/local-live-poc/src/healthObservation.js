const number = (value) => typeof value === "number" && Number.isFinite(value) ? value : null;
const boolean = (value) => typeof value === "boolean" ? value : null;

// Persist measurements only; health responses can also contain URLs and errors.
export function healthObservation(health) {
  return {
    status: health ? (["ready", "degraded", "offline"].includes(health.status) ? health.status : "unknown") : "offline",
    storageAvailable: boolean(health?.sessionStorage?.available),
    storageFreeBytes: number(health?.sessionStorage?.freeBytes),
    asrAvailable: boolean(health?.asr?.available),
    translationAvailable: boolean(health?.ollama?.configuredModelInstalled),
    liveDegraded: boolean(health?.liveProgress?.degraded),
    streams: (Array.isArray(health?.liveProgress?.streams) ? health.liveProgress.streams : []).map((stream) => ({
      degraded: boolean(stream.degraded),
      consecutiveNoFinal: number(stream.consecutiveNoFinal),
      asrQueueDepth: number(stream.asrQueueDepth),
      translationQueueDepth: number(stream.translationQueueDepth),
    })),
    publisherQueueDepth: number(health?.publicViewer?.queueDepth),
    publisherFailureCount: number(health?.publicViewer?.publishFailureCount),
    publisherDroppedFinalCount: number(health?.publicViewer?.droppedFinalCount),
    publisherWriteLatencyMs: number(health?.publicViewer?.lastWriteLatencyMs),
  };
}
