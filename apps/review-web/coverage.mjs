// Listening coverage for the track review page: which seconds of the whole track were
// actually played, and at what speed. Pure logic, no DOM, so it is unit-tested with node.

export function createCoverage(trackSeconds) {
  const total = Math.max(0, Math.ceil(trackSeconds || 0));
  const normal = new Uint8Array(total);   // seconds heard at 1x
  const other = new Uint8Array(total);    // seconds heard at another speed
  let last = null;                         // previous playhead position, seconds
  const rates = new Set();

  return {
    // Call on every timeupdate while the whole track is playing.
    tick(position, rate = 1) {
      if (!Number.isFinite(position) || position < 0) return;
      // A jump of more than 2 s is a seek, not listening: do not credit the gap.
      const from = last !== null && position >= last && position - last <= 2 ? last : position;
      const bucket = Math.abs(rate - 1) < 0.01 ? normal : other;
      for (let s = Math.floor(from); s <= Math.floor(position) && s < total; s += 1) bucket[s] = 1;
      rates.add(Math.round(rate * 100) / 100);
      last = position;
    },
    // Call on pause, seeking and ended so the next tick starts a new stretch.
    stop() { last = null; },
    // Was every second of [from, to) played, at any speed?
    covers(from, to) {
      const first = Math.max(0, Math.floor(from)), end = Math.min(total, Math.max(first + 1, Math.ceil(to)));
      if (first >= total) return false;
      for (let s = first; s < end; s += 1) if (!normal[s] && !other[s]) return false;
      return true;
    },
    restore(saved) {
      if (!saved || saved.total !== total) return;
      for (const s of saved.normal || []) if (s < total) normal[s] = 1;
      for (const s of saved.other || []) if (s < total) other[s] = 1;
      for (const r of saved.rates || []) rates.add(r);
    },
    snapshot() {
      const list = array => Array.from(array.keys()).filter(s => array[s]);
      return { total, normal: list(normal), other: list(other), rates: [...rates].sort() };
    },
    summary() {
      let atNormal = 0, any = 0;
      for (let s = 0; s < total; s += 1) {
        if (normal[s]) atNormal += 1;
        if (normal[s] || other[s]) any += 1;
      }
      return {
        trackSeconds: total,
        heardSecondsAt1x: atNormal,
        heardSecondsAnySpeed: any,
        shareAt1x: total ? atNormal / total : 0,
        shareAnySpeed: total ? any / total : 0,
        playbackRates: [...rates].sort(),
      };
    },
  };
}

// The receipt's reviewMode is derived from what was measured, never chosen by hand.
// whole_track needs the whole track at 1x; flagged_only needs every flagged sentence heard.
export function reviewMode({ shareAt1x, flaggedIds, heardIds, declaredWholeTrackElsewhere = false }) {
  const heard = new Set(heardIds);
  const missing = flaggedIds.filter(id => !heard.has(id));
  if (shareAt1x >= 0.98) return { mode: "whole_track", basis: "measured", missingFlagged: missing };
  if (declaredWholeTrackElsewhere) return { mode: "whole_track", basis: "declared", missingFlagged: missing };
  if (!missing.length) return { mode: "flagged_only", basis: "measured", missingFlagged: [] };
  return { mode: "partial", basis: "measured", missingFlagged: missing };
}
