import { FeedbackClient, FeedbackError } from './feedback-client.mjs';

// A dedicated credential keeps this cumulative stream independent of legacy
// feedback statistics and usage-event sequence numbers.
export class LanguageListeningSession {
  constructor(source, { day, clientId = null, client = new FeedbackClient(source),
    endpoint = '/api/listening', interfaceLocale, contentLocale } = {}) {
    this.client = client; this.day = day; this.clientId = clientId;
    this.endpoint = endpoint; this.dimensions = { interfaceLocale, ...(contentLocale ? { contentLocale } : {}) };
    this.seq = 0; this.pending = null; this.latest = null; this.sent = null;
    this.flight = null; this.stopped = false; this.mayExist = false;
  }
  async prepare() {
    const token = await this.client.session();
    this.clientId = await this.clientId;
    return token;
  }
  flush(snapshot) {
    if (this.stopped) return Promise.resolve();
    if (snapshot && (this.endpoint === '/api/interface-usage' || snapshot.listenedSeconds > 0)) this.latest = structuredClone(snapshot);
    if (this.flight) return this.flight;
    this.flight = this.send().finally(() => { this.flight = null; });
    return this.flight;
  }
  async send() {
    if (!this.pending && (!this.latest || JSON.stringify(this.latest) === this.sent)) return;
    const token = await this.prepare();
    while (!this.stopped && (this.pending || (this.latest && JSON.stringify(this.latest) !== this.sent))) {
      if (!this.pending) {
        this.pendingSignature = JSON.stringify(this.latest);
        this.pending = { ...this.client.source, action: 'upsert', seq: this.seq + 1,
          day: this.day, clientId: this.clientId, platform: 'web', ...this.dimensions, ...this.latest };
      }
      const body = this.pending;
      this.mayExist = true;
      const result = await this.client.post(this.endpoint, body, token);
      if (result.lastSeq !== body.seq || ![true, false].includes(result.accepted)) throw new FeedbackError(409);
      this.seq = body.seq;
      this.sent = this.pendingSignature;
      this.pending = null;
    }
  }
  async retract() {
    this.stopped = true;
    if (this.flight) await this.flight.catch(() => {});
    if (!this.mayExist) return;
    const { token, expiresAt } = this.client.state;
    if (!token || expiresAt <= this.client.now()) throw new FeedbackError(410);
    // An uncertain upsert may have committed. Delete with a later sequence;
    // keep an uncertain delete byte-identical for the retry button.
    if (this.pending?.action !== 'delete') this.pending = { ...this.client.source,
      action: 'delete', seq: Math.max(this.seq, this.pending?.seq || 0) + 1 };
    const result = await this.client.post(this.endpoint, this.pending, token);
    if (result.lastSeq !== this.pending.seq || ![true, false].includes(result.accepted)) throw new FeedbackError(409);
    this.seq = this.pending.seq; this.pending = null; this.mayExist = false;
  }
}
