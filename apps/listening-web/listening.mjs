// Only observed playback intervals count. Seeking never fabricates coverage.
export function mergeRanges(ranges, duration) {
  const sorted = ranges.filter(([a, b]) => Number.isFinite(a) && Number.isFinite(b) && b > a)
    .map(([a, b]) => [Math.max(0, a), Math.min(duration, b)])
    .filter(([a, b]) => b > a).sort((a, b) => a[0] - b[0]);
  const merged = [];
  for (const range of sorted) {
    const previous = merged.at(-1);
    if (previous && range[0] <= previous[1]) previous[1] = Math.max(previous[1], range[1]);
    else merged.push([...range]);
  }
  return merged;
}

export class ListeningSummary {
  constructor(duration) {
    this.duration = duration;
    this.ranges = [];
    this.listenedSeconds = 0;
    this.previous = null;
    this.counts = { plays: 0, pauses: 0, seeks: 0, nudges: 0, outlineViews: 0, downloadClicks: 0 };
    this.errors = { audio_load: 0, audio_play: 0 };
  }
  resetSample() { this.previous = null; }
  observe(position, now, playing) {
    const previous = this.previous;
    this.previous = playing && Number.isFinite(position) ? { position, now } : null;
    if (!playing || !previous) return;
    const elapsed = (now - previous.now) / 1000;
    const advanced = position - previous.position;
    // Gaps from suspended/background tabs are omitted rather than guessed.
    if (elapsed <= 0 || elapsed > 8 || advanced <= 0 || advanced > elapsed * 1.25 + .1) return;
    const end = Math.min(this.duration, position), start = Math.max(0, previous.position);
    if (end <= start) return;
    this.listenedSeconds += end - start;
    const next = mergeRanges([...this.ranges, [start, end]], this.duration);
    // Preserve every previously reported interval. On very fragmented listens,
    // omit new disjoint ranges rather than bridge unplayed gaps or shrink history.
    if (next.length <= 128) this.ranges = next;
  }
  count(name) { if (Object.hasOwn(this.counts, name)) this.counts[name] += 1; }
  error(name) { if (Object.hasOwn(this.errors, name)) this.errors[name] += 1; }
  snapshot() {
    return { listenedSeconds: Math.round(this.listenedSeconds * 100) / 100,
      ranges: this.ranges.map(([a, b]) => [Math.ceil(a * 100) / 100, Math.floor(b * 100) / 100]).filter(([a, b]) => b > a),
      ...this.counts, errors: { ...this.errors } };
  }
}
