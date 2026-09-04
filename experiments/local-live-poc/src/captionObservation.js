// Rendering telemetry must never prevent recovery recording finalization.
export function observeCaptionFrame({
  requestFrame = (callback) => window.requestAnimationFrame(callback),
  cancelFrame = (id) => window.cancelAnimationFrame(id),
  setTimer = (callback, delay) => window.setTimeout(callback, delay),
  clearTimer = (id) => window.clearTimeout(id),
  isVisible = () => document.visibilityState === "visible",
  now = () => Date.now(),
  timeoutMs = 2000,
} = {}) {
  return new Promise((resolve) => {
    let settled = false;
    let frameId = null;
    let timerId = null;
    const finish = (observed, reason) => {
      if (settled) return;
      settled = true;
      if (frameId !== null) cancelFrame(frameId);
      if (timerId !== null) clearTimer(timerId);
      resolve({ observed, reason, atMs: now() });
    };
    if (!isVisible()) {
      finish(false, "document_hidden");
      return;
    }
    frameId = requestFrame(() => finish(isVisible(), isVisible() ? null : "document_hidden"));
    timerId = setTimer(() => finish(false, "animation_frame_timeout"), timeoutMs);
  });
}
