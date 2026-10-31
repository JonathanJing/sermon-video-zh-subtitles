#!/usr/bin/env node
/** Operator-only weekly APNs fanout. A prior private plan is mandatory for sends. */
import { readFileSync, writeFileSync, openSync, closeSync, statSync } from 'node:fs';
import { dirname, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createPrivateKey, randomUUID, sign } from 'node:crypto';
import http2 from 'node:http2';
import { Firestore } from '@google-cloud/firestore';
import { ORIGIN, TOPIC, dispatchOne, eligibleSubscriptions, sha256, verifiedPublication } from './send-core.mjs';
import { firestoreStore } from './firestore-store.mjs';

function privateJSON(path) {
  const file = resolve(path);
  if ((statSync(file).mode & 0o077) !== 0) throw new Error('private_file_permissions_required');
  return JSON.parse(readFileSync(file, 'utf8'));
}
function parseArgs(args) {
  if (!['plan', 'send'].includes(args[0])) throw new Error('usage: node send.mjs plan --page-id PAGE_ID --out PRIVATE_FILE | send --plan PRIVATE_FILE --key-config PRIVATE_FILE');
  const options = { action: args[0] };
  for (let i = 1; i < args.length; i += 2) {
    if (!['--out', '--plan', '--key-config', '--page-id'].includes(args[i]) || !args[i + 1]) throw new Error('invalid_arguments');
    options[args[i].slice(2).replace('-', '_')] = args[i + 1];
  }
  if (options.action === 'plan' && (!options.out || !options.page_id || options.plan || options.key_config)) throw new Error('invalid_arguments');
  if (options.action === 'send' && (!options.plan || !options.key_config || options.out || options.page_id)) throw new Error('invalid_arguments');
  return options;
}
function jwt(key, keyID, teamID) {
  const encode = (value) => Buffer.from(JSON.stringify(value)).toString('base64url');
  const message = encode({ alg: 'ES256', kid: keyID }) + '.' +
    encode({ iss: teamID, iat: Math.floor(Date.now() / 1000) });
  const signature = sign('sha256', Buffer.from(message), { key, dsaEncoding: 'ieee-p1363' }).toString('base64url');
  return message + '.' + signature;
}
function sendAPNsFactory(config, publication) {
  if (config.topic !== TOPIC || config.environment !== 'production' ||
      !/^[A-Z0-9]{10}$/.test(config.keyId ?? '') || !/^[A-Z0-9]{10}$/.test(config.teamId ?? '')) {
    throw new Error('production_apns_config_required');
  }
  const keyFile = resolve(config.keyFile);
  if ((statSync(keyFile).mode & 0o077) !== 0) throw new Error('private_key_permissions_required');
  const key = createPrivateKey(readFileSync(keyFile));
  if (key.asymmetricKeyType !== 'ec' || key.asymmetricKeyDetails?.namedCurve !== 'prime256v1') {
    throw new Error('p256_key_required');
  }
  return async ({ deviceToken, notice, apnsID }) => {
    const payload = JSON.stringify({
      aps: { alert: publication.copy[notice.locale], sound: 'default' },
      tongxing: notice,
    });
    if (Buffer.byteLength(payload) > 4000) throw new Error('apns_payload_too_large');
    const session = http2.connect('https://api.push.apple.com');
    return new Promise((resolveRequest, rejectRequest) => {
      let settled = false;
      function finish(error, result) {
        if (settled) return;
        settled = true;
        session.close();
        if (error) rejectRequest(new Error('apns_outcome_unknown'));
        else resolveRequest(result);
      }
      session.on('error', () => finish(true));
      const request = session.request({
        ':method': 'POST', ':path': `/3/device/${deviceToken}`,
        authorization: `bearer ${jwt(key, config.keyId, config.teamId)}`,
        'apns-topic': TOPIC, 'apns-push-type': 'alert', 'apns-priority': '10',
        'apns-expiration': '0', 'apns-id': apnsID,
      });
      request.setTimeout(30000, () => finish(true));
      let status = 0;
      let body = '';
      request.on('response', (headers) => { status = Number(headers[':status'] ?? 0); });
      request.on('data', (chunk) => { if (body.length < 4096) body += chunk.toString('utf8'); });
      request.on('end', () => {
        let reason = null;
        try { reason = JSON.parse(body).reason ?? null; } catch { /* APNs 200 has no body. */ }
        finish(false, { httpStatus: status, reason });
      });
      request.on('error', () => finish(true));
      request.end(payload);
    });
  };
}

function planDigest(publication) {
  return sha256(JSON.stringify([publication.pageID, publication.date, publication.notices, publication.copy]));
}
async function subscriptions(db) {
  const snapshot = await db.collection('pushSubscriptions').where('active', '==', true).limit(5000).get();
  if (snapshot.size === 5000) throw new Error('subscription_page_limit_reached');
  return snapshot.docs.map((doc) => doc.data());
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const plan = options.action === 'send' ? privateJSON(options.plan) : null;
  const runtime = privateJSON(new URL('./server-config.json', import.meta.url).pathname);
  if (runtime.projectId !== 'ai-for-god-caption-dev' || runtime.databaseId !== 'sermon-push') {
    throw new Error('production_push_database_required');
  }
  const db = new Firestore({ projectId: runtime.projectId, databaseId: runtime.databaseId });
  const publication = await verifiedPublication(options.action === 'plan' ? options.page_id : plan.pageID);
  const { eligible, suppressedDuplicates } = eligibleSubscriptions(await subscriptions(db), publication);
  const recipients = eligible.map((row) => ({ installationId: row.installationId, seq: row.seq,
    tokenHash: row.tokenHash, locale: row.locale }));
  if (options.action === 'plan') {
    const file = resolve(options.out);
    const repository = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
    if (file.startsWith(repository + sep) && !file.startsWith(resolve(repository, 'artifacts') + sep)) {
      throw new Error('private_plan_location_required');
    }
    const plan = { schemaVersion: 1, origin: ORIGIN, topic: TOPIC, environment: 'production',
      pageID: publication.pageID, publicationDigest: planDigest(publication), copy: publication.copy,
      createdAt: new Date().toISOString(), suppressedDuplicates, recipients };
    const fd = openSync(file, 'wx', 0o600);
    try { writeFileSync(fd, JSON.stringify(plan, null, 2) + '\n'); } finally { closeSync(fd); }
    console.log(JSON.stringify({ dryRun: true, pageID: plan.pageID, copy: plan.copy,
      recipients: recipients.length, suppressedDuplicates, plan: file }));
    return;
  }
  if (plan.schemaVersion !== 1 || plan.origin !== ORIGIN || plan.topic !== TOPIC ||
      plan.environment !== 'production' || plan.pageID !== publication.pageID ||
      plan.publicationDigest !== planDigest(publication) ||
      JSON.stringify(plan.copy) !== JSON.stringify(publication.copy) ||
      Date.now() - Date.parse(plan.createdAt) > 15 * 60 * 1000 ||
      Date.now() < Date.parse(plan.createdAt)) throw new Error('stale_or_changed_plan');
  const current = new Map(eligible.map((row) => [row.installationId, row]));
  const keyConfig = privateJSON(options.key_config);
  const sendAPNs = sendAPNsFactory(keyConfig, publication);
  const store = firestoreStore(db);
  let accepted = 0, skipped = 0, rejected = 0, unknown = 0;
  for (const recipient of plan.recipients) {
    const row = current.get(recipient.installationId);
    if (!row || row.seq !== recipient.seq || row.tokenHash !== recipient.tokenHash ||
        row.locale !== recipient.locale) { skipped++; continue; }
    const result = await dispatchOne({ store, subscription: row,
      notice: publication.notices[row.locale], sendAPNs, attemptID: randomUUID() });
    if (!result.claimed) {
      if (result.reason === 'outcome_unknown') { unknown++; break; }
      skipped++; continue;
    }
    if (result.status === 'accepted') accepted++;
    else if (result.status === 'rejected') { rejected++; break; }
    else { unknown++; break; }
  }
  // Never print device tokens, secrets or request errors. The ledger is the
  // durable per-recipient receipt; unknown outcomes require manual reconciliation.
  console.log(JSON.stringify({ pageID: publication.pageID, planned: plan.recipients.length,
    accepted, skipped, rejected, unknown }));
  if (rejected || unknown) process.exitCode = 1;
}

main().catch((error) => {
  console.error(['stale_or_changed_plan', 'subscription_page_limit_reached', 'production_push_database_required',
    'production_apns_config_required', 'private_file_permissions_required', 'private_key_permissions_required',
    'p256_key_required', 'private_plan_location_required'].includes(error.message) ? error.message : 'push_operator_failed');
  process.exitCode = 1;
});
