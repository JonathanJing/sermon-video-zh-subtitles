export const PLAYBACK_MEMORY_KEY = 'sermon-playback-memory-v1';
const SCHEMA_VERSION = 1;
const MAX_ENTRIES = 12;
const MAX_AGE_MS = 30 * 86_400_000;
const finite = value => typeof value === 'number' && Number.isFinite(value);

function sourceCopy(source) {
  if (!source || typeof source.week !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(source.week)
      || !Number.isFinite(Date.parse(source.week)) || new Date(source.week).toISOString().slice(0, 10) !== source.week
      || typeof source.trackId !== 'string' || !source.trackId.trim() || source.trackId.length > 160 || /[\x00-\x1f\x7f]/.test(source.trackId)
      || typeof source.audioSha256 !== 'string' || !/^[a-f0-9]{64}$/.test(source.audioSha256)) return null;
  return { week: source.week, trackId: source.trackId, audioSha256: source.audioSha256 };
}
const keyOf = source => JSON.stringify([source.week, source.trackId, source.audioSha256]);
const validDuration = duration => finite(duration) && duration > 0;
const validPosition = (position, duration) => finite(position) && position >= 0 && position <= duration;
const usefulPosition = (position, duration) => position >= 2 && position < duration - 2;
const validOffset = (offset, duration) => finite(offset) && Math.abs(offset) <= duration;

/** A saved position is a bookmark, never a live-clock estimate or autoplay request.
 * Storage failures leave this instance's in-memory bookmarks usable.
 */
export class PlaybackMemory {
  constructor({ storage = null, now = Date.now } = {}) {
    this.storage = storage;
    this.now = now;
    this.entries = new Map();
    this.load();
  }

  clock() {
    try { const value = this.now(); return finite(value) && value >= 0 ? value : null; }
    catch { return null; }
  }

  load() {
    let raw;
    try { raw = this.storage?.getItem(PLAYBACK_MEMORY_KEY); }
    catch { return; }
    if (!raw) return;
    const now = this.clock();
    if (now === null) return;
    try {
      const saved = JSON.parse(raw);
      if (saved?.schemaVersion !== SCHEMA_VERSION || !Array.isArray(saved.entries)) throw new Error('Invalid playback memory');
      for (const row of saved.entries) {
        const source = sourceCopy(row?.source);
        if (!source || !validDuration(row.durationSeconds) || !validPosition(row.positionSeconds, row.durationSeconds)
            || !usefulPosition(row.positionSeconds, row.durationSeconds) || !validOffset(row.fineOffset, row.durationSeconds)
            || !finite(row.savedAt) || row.savedAt > now || now - row.savedAt >= MAX_AGE_MS || row.savedAt < 0) continue;
        const key = keyOf(source), prior = this.entries.get(key);
        if (!prior || row.savedAt > prior.savedAt) this.entries.set(key, { source, positionSeconds: row.positionSeconds, fineOffset: row.fineOffset, durationSeconds: row.durationSeconds, savedAt: row.savedAt });
      }
    } catch { this.entries.clear(); }
    this.prune(now);
    // Also removes expired/corrupt/excess entries from persistent storage.
    this.persist();
  }

  prune(now) {
    let changed = false;
    for (const [key, row] of this.entries) {
      if (row.savedAt > now || now - row.savedAt >= MAX_AGE_MS) { this.entries.delete(key); changed = true; }
    }
    if (this.entries.size > MAX_ENTRIES) {
      const recent = [...this.entries].reverse().sort((a, b) => b[1].savedAt - a[1].savedAt);
      this.entries = new Map(recent.slice(0, MAX_ENTRIES).reverse());
      changed = true;
    }
    return changed;
  }

  persist() {
    try {
      this.storage?.setItem(PLAYBACK_MEMORY_KEY, JSON.stringify({ schemaVersion: SCHEMA_VERSION, entries: [...this.entries.values()] }));
    } catch { /* A storage/quota/private-mode failure never interrupts playback. */ }
  }

  save(source, { positionSeconds, fineOffset, durationSeconds } = {}) {
    const identity = sourceCopy(source), now = this.clock();
    if (!identity || now === null || !validDuration(durationSeconds) || !validPosition(positionSeconds, durationSeconds) || !validOffset(fineOffset, durationSeconds)) return false;
    if (!usefulPosition(positionSeconds, durationSeconds)) { this.clear(identity); return false; }
    const key = keyOf(identity);
    // Reinsert so equally timed saves retain the most recently touched source.
    this.entries.delete(key);
    this.entries.set(key, { source: identity, positionSeconds, fineOffset, durationSeconds, savedAt: now });
    this.prune(now);
    this.persist();
    return true;
  }

  read(source, durationSeconds) {
    const identity = sourceCopy(source), now = this.clock();
    if (!identity || now === null || !validDuration(durationSeconds)) return null;
    if (this.prune(now)) this.persist();
    const row = this.entries.get(keyOf(identity));
    if (!row) return null;
    if (!validPosition(row.positionSeconds, durationSeconds) || !usefulPosition(row.positionSeconds, durationSeconds) || !validOffset(row.fineOffset, durationSeconds)) {
      this.clear(identity);
      return null;
    }
    return { positionSeconds: row.positionSeconds, fineOffset: row.fineOffset, savedAt: row.savedAt };
  }

  clear(source) {
    const identity = sourceCopy(source);
    if (!identity) return false;
    const removed = this.entries.delete(keyOf(identity));
    const now = this.clock();
    if (now !== null) this.prune(now);
    this.persist();
    return removed;
  }
}
