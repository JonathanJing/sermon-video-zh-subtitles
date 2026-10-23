#!/usr/bin/env node
/** Close an unknown dispatch with an operator's private evidence; never resends. */
import { readFileSync, statSync } from 'node:fs';
import { Firestore } from '@google-cloud/firestore';
import { sha256 } from './send-core.mjs';

function option(flag) {
  const index = process.argv.indexOf(flag);
  return index >= 0 && process.argv[index + 1] ? process.argv[index + 1] : null;
}
async function main() {
  const key = option('--dispatch-key');
  const apnsID = option('--apns-id');
  const resolution = option('--resolution');
  const evidence = option('--evidence');
  if (!/^[0-9a-f]{64}$/.test(key ?? '') ||
      !/^[0-9a-f-]{36}$/i.test(apnsID ?? '') ||
      !['device_observed', 'closed_without_resend'].includes(resolution) || !evidence) {
    throw new Error('usage_error');
  }
  if ((statSync(evidence).mode & 0o077) !== 0) throw new Error('private_evidence_required');
  const evidenceHash = sha256(readFileSync(evidence));
  const config = JSON.parse(readFileSync(new URL('./server-config.json', import.meta.url), 'utf8'));
  if (config.projectId !== 'ai-for-god-caption-dev' || config.databaseId !== 'sermon-push') {
    throw new Error('production_push_database_required');
  }
  const db = new Firestore({ projectId: config.projectId, databaseId: config.databaseId });
  await db.runTransaction(async (tx) => {
    const ref = db.doc(`pushDispatches/${key}`);
    const snapshot = await tx.get(ref);
    const current = snapshot.data();
    if (!current || current.status !== 'outcome_unknown' || current.apnsID !== apnsID) {
      throw new Error('dispatch_not_unknown');
    }
    tx.set(ref, { ...current, status: 'resolved_no_resend', resolution,
      evidenceSHA256: evidenceHash, reconciledAt: new Date() });
  });
  console.log(JSON.stringify({ dispatchKey: key, status: 'resolved_no_resend', resolution,
    evidenceSHA256: evidenceHash, resent: false }));
}
main().catch((error) => {
  console.error(['usage_error', 'private_evidence_required', 'production_push_database_required',
    'dispatch_not_unknown'].includes(error.message) ? error.message : 'reconcile_failed');
  process.exitCode = 1;
});
