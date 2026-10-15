export function statisticsPreference(storage) {
  try {
    const current = storage?.getItem('sermon-anonymous-statistics-v2');
    if (current === 'yes' || current === 'no') return current === 'yes';
    return storage?.getItem('sermon-anonymous-statistics-v1') !== 'no';
  } catch { return true; }
}

export class FeedbackError extends Error {
  constructor(status) { super('Feedback request failed'); this.status = status; }
}

// The App keeps credentials in page memory, never in URLs or a visitor profile.
export class FeedbackClient {
  constructor(source, { fetchImpl = (...args) => fetch(...args), storage = null, now = () => Date.now() } = {}) {
    this.source = { schemaVersion: 1, ...source };
    this.fetchImpl = fetchImpl;
    this.storage = storage;
    this.now = now;
    this.key = `sermon-feedback-v1:${source.week}:${source.trackId}:${source.audioSha256}:${source.appVersion}`;
    this.state = {};
    try {
      const saved = JSON.parse(storage?.getItem(this.key) || 'null');
      if (saved && saved.expiresAt > now()) this.state = saved;
    } catch { /* A blocked or full storage never prevents listening. */ }
    this.pending = Promise.resolve();
  }
  save() { try { this.storage?.setItem(this.key, JSON.stringify(this.state)); } catch {} }
  enqueue(action) {
    const task = this.pending.then(action);
    this.pending = task.catch(() => {});
    return task;
  }
  async post(path, body, token) {
    const response = await this.fetchImpl(path, {
      method: 'POST', credentials: 'same-origin', cache: 'no-store', keepalive: true,
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify(body), signal: AbortSignal.timeout(15000),
    });
    if (!response.ok) throw new FeedbackError(response.status);
    return response.json();
  }
  async session() {
    if (this.state.token && this.state.expiresAt > this.now() + 1000) return this.state.token;
    // Never silently replace an expired credential: it cannot retract records
    // owned by the old session, or accept that session's cumulative statistics.
    if (this.state.token) throw new FeedbackError(410);
    if (!this.minting) this.minting = (async () => {
      const result = await this.post('/api/session', this.source);
      const expiresAt = typeof result.expiresAt === 'number' ? result.expiresAt : Date.parse(result.expiresAt);
      if (!result.token || !Number.isFinite(expiresAt) || expiresAt <= this.now()) throw new FeedbackError(503);
      this.state = { token: result.token, expiresAt, vote: null, voteSeq: 0, eventsSeq: 0, issues: {} };
      this.save();
      return this.state.token;
    })().finally(() => { this.minting = null; });
    return this.minting;
  }
  vote(value) {
    return this.enqueue(async () => {
      const token = await this.session();
      const seq = (this.state.voteSeq || 0) + 1;
      this.state.voteSeq = seq; this.save();
      const result = await this.post('/api/feedback', { ...this.source, kind: 'vote', seq, vote: value }, token);
      if (result.accepted === false) { this.state.voteSeq = Math.max(seq, result.lastSeq || seq); this.save(); throw new FeedbackError(409); }
      this.state.vote = value; this.save();
    });
  }
  issue(feedbackId, details, action = 'upsert') {
    return this.enqueue(async () => {
      const token = await this.session();
      this.state.issues ||= {};
      const seq = (this.state.issues[feedbackId] || 0) + 1;
      this.state.issues[feedbackId] = seq; this.save();
      const result = await this.post('/api/feedback', { ...this.source, kind: 'issue', feedbackId, seq, action,
        ...(action === 'upsert' ? details : {}) }, token);
      if (result.accepted === false) { this.state.issues[feedbackId] = Math.max(seq, result.lastSeq || seq); this.save(); throw new FeedbackError(409); }
      if (action === 'upsert') this.state.lastIssueId = feedbackId;
      else if (this.state.lastIssueId === feedbackId) delete this.state.lastIssueId;
      this.save();
    });
  }
  events(snapshot, permitted = () => true) {
    return this.enqueue(async () => {
      if (!permitted()) return;
      const token = await this.session();
      if (!permitted()) return;
      const seq = (this.state.eventsSeq || 0) + 1;
      this.state.eventsSeq = seq;
      this.state.summary = snapshot;
      // A timeout may follow a successful write, so remember to retract it too.
      this.state.statsMayExist = true; this.save();
      const result = await this.post('/api/events', { ...this.source, action: 'upsert', seq, ...snapshot }, token);
      if (result.accepted === false) { this.state.eventsSeq = Math.max(seq, result.lastSeq || seq); this.save(); throw new FeedbackError(409); }
    });
  }
  deleteEvents() {
    return this.enqueue(async () => {
      if (!this.state.statsMayExist) return;
      if (!this.state.token || this.state.expiresAt <= this.now()) throw new FeedbackError(410);
      const seq = (this.state.eventsSeq || 0) + 1;
      this.state.eventsSeq = seq; this.save();
      const result = await this.post('/api/events', { ...this.source, action: 'delete', seq }, this.state.token);
      if (result.accepted === false) { this.state.eventsSeq = Math.max(seq, result.lastSeq || seq); this.save(); throw new FeedbackError(409); }
      delete this.state.summary; delete this.state.statsMayExist; this.save();
    });
  }
}
