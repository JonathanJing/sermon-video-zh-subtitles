export const GATEWAY_URL = import.meta.env?.VITE_GATEWAY_URL || "http://127.0.0.1:8766";

async function requestJson(path, options = {}, fetchImpl = globalThis.fetch) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetchImpl(`${GATEWAY_URL}${path}`, { ...options, signal: controller.signal });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.message || `Gateway HTTP ${response.status}`);
    return payload;
  } finally {
    clearTimeout(timeout);
  }
}

function jsonOptions(method, payload) {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  };
}

export function getGatewayHealth(fetchImpl) {
  return requestJson("/api/health", {}, fetchImpl);
}

export function restartGateway(fetchImpl) {
  return requestJson("/api/runtime/restart", jsonOptions("POST", {}), fetchImpl);
}

export function startLocalSession(metadata, fetchImpl) {
  return requestJson("/api/sessions/start", jsonOptions("POST", metadata), fetchImpl);
}

export function resumeLocalSession(sessionId, availableAudioChunks, pcmFrameSequence, fetchImpl) {
  return requestJson(`/api/sessions/${sessionId}/resume`,
    jsonOptions("POST", { availableAudioChunks, ...(pcmFrameSequence == null ? {} : { pcmFrameSequence }) }), fetchImpl);
}

export function appendSessionEvent(sessionId, event, fetchImpl) {
  return requestJson(
    `/api/sessions/${sessionId}/events`,
    jsonOptions("POST", event),
    fetchImpl,
  );
}

export function appendAudioChunk(sessionId, sequence, chunk, mimeType, fetchImpl) {
  return requestJson(
    `/api/sessions/${sessionId}/audio?sequence=${sequence}`,
    {
      method: "POST",
      headers: { "Content-Type": mimeType },
      body: chunk,
    },
    fetchImpl,
  );
}

export function finalizeLocalSession(sessionId, details, fetchImpl) {
  return requestJson(
    `/api/sessions/${sessionId}/finalize`,
    jsonOptions("POST", details),
    fetchImpl,
  );
}

export function translateCaption(request, fetchImpl) {
  return requestJson("/api/translate", jsonOptions("POST", request), fetchImpl);
}
