export function boundedTime(time, duration) {
  if (!Number.isFinite(time) || !Number.isFinite(duration) || duration < 0) return 0;
  return Math.min(duration, Math.max(0, time));
}

export function nudge(time, delta, duration) {
  const before = boundedTime(time, duration);
  const after = boundedTime(before + delta, duration);
  return { time: after, applied: after - before };
}

export function formatTime(seconds) {
  const value = Math.max(0, Math.floor(Number.isFinite(seconds) ? seconds : 0));
  return `${Math.floor(value / 60).toString().padStart(2, "0")}:${(value % 60).toString().padStart(2, "0")}`;
}

export function cueIndex(cues, time) {
  return cues.findIndex(cue => time >= cue.start && time < cue.end);
}
