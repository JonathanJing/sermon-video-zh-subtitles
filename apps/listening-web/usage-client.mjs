import { FeedbackClient, FeedbackError } from './feedback-client.mjs';

export const DAILY_BROWSER_KEY = 'sermon-usage-daily-browser-v1';
export function usageDay(timestamp = Date.now()) {
  const parts = new Intl.DateTimeFormat('en-US', { timeZone: 'America/Los_Angeles', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date(timestamp));
  const value = type => parts.find(part => part.type === type).value;
  return `${value('year')}-${value('month')}-${value('day')}`;
}
export function dailyBrowserId(storage, day, uuid = () => crypto.randomUUID()) {
  try {
    const saved = JSON.parse(storage?.getItem(DAILY_BROWSER_KEY) || 'null');
    if (saved?.day === day && /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i.test(saved.id)) return saved.id;
    const id = uuid();
    storage?.setItem(DAILY_BROWSER_KEY, JSON.stringify({ day, id }));
    // A blocked store cannot provide browser-level deduplication.
    return storage?.getItem(DAILY_BROWSER_KEY) ? id : null;
  } catch { return null; }
}

export async function lockedDailyBrowserId(storage, day, { locks = globalThis.navigator?.locks, permitted = () => true, uuid } = {}) {
  // A localStorage read/write pair is not atomic across tabs. Use one origin
  // lock; without it, keep session statistics but do not invent a daily count.
  if (!locks?.request || !storage) return null;
  try {
    return await locks.request(DAILY_BROWSER_KEY, () => permitted() ? dailyBrowserId(storage, day, uuid) : null);
  } catch { return null; }
}

/** Each page/day/consent epoch owns a separate in-memory credential. */
export class UsageSession {
  constructor(source, { day, browserId = null, client = new FeedbackClient(source) } = {}) {
    this.day = day; this.browserId = browserId; this.client = client;
    this.queue = []; this.seq = 0; this.dropped = 0;
    this.batch = null; this.flight = null; this.stopped = false; this.closed = false;
    this.mayExist = false;
  }
  add(event) {
    if (this.stopped || this.closed) return;
    if (this.queue.length >= 90) { this.dropped += 1; return; }
    this.queue.push({ ...event });
  }
  flush() {
    if (this.flight) return this.flight;
    if (this.stopped || this.closed || (!this.batch && !this.queue.length && !this.dropped)) return Promise.resolve();
    this.flight = this.send().finally(() => { this.flight = null; });
    return this.flight;
  }
  async send() {
    this.browserId = await this.browserId;
    if (this.stopped) return;
    const token = await this.client.session();
    if (this.stopped) return;
    while (!this.stopped && !this.closed && (this.batch || this.queue.length || this.dropped)) {
      if (!this.batch) {
        // A visitor may opt in while offline and obtain the first credential
        // much later. Remove only unsent events outside the server's admission
        // window; an already-sent uncertain batch must remain byte-identical.
        const earliest = Math.max(this.client.state.expiresAt - 86400000 - 300000, this.client.now() - 86400000);
        const retained = this.queue.filter(event => event.at >= earliest);
        this.dropped += this.queue.length - retained.length;
        this.queue = retained;
        if (!this.queue.length && this.day !== usageDay(this.client.now())) {
          this.closed = true; return;
        }
        this.batch = { ...this.client.source, action: 'append', seq: this.seq + 1,
          day: this.day, browserId: this.browserId, events: this.queue.splice(0, 30), droppedEvents: this.dropped };
        this.dropped = 0;
      }
      // Retain this exact batch and sequence after a timeout. A retry must not
      // replace it with newer events or count an accepted batch twice.
      const batch = this.batch;
      this.mayExist = true;
      const result = await this.client.post('/api/usage', batch, token);
      if (result.accepted !== true || result.lastSeq !== batch.seq) throw new FeedbackError(409);
      this.seq = batch.seq; this.batch = null;
      this.closed = result.closed === true;
      if (this.closed) this.queue = [];
    }
  }
  async retract() {
    this.stopped = true; this.queue = []; this.dropped = 0;
    // A started append may have committed even when its response was lost.
    if (this.flight) await this.flight.catch(() => {});
    this.batch = null;
    if (!this.mayExist) return;
    const { token, expiresAt } = this.client.state;
    if (!token || expiresAt <= this.client.now()) throw new FeedbackError(410);
    await this.client.post('/api/usage', { ...this.client.source, action: 'delete' }, token);
    this.mayExist = false;
  }
}
