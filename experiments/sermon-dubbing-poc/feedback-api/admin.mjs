#!/usr/bin/env node
import { Firestore } from '@google-cloud/firestore';
import { fetchUsageSessions, parseUsageArgs, summarizeUsage, writeUsageReport } from './usage-report.mjs';

// IAM/ADC-only local operator tool; never imported into the HTTP runtime.
const [command, ...args] = process.argv.slice(2);
const projectId = process.env.GOOGLE_CLOUD_PROJECT;
const databaseId = process.env.FEEDBACK_DATABASE_ID || 'sermon-dubbing-feedback';
if (!projectId || databaseId === '(default)') throw new Error('Set GOOGLE_CLOUD_PROJECT and use the named feedback database');
const db = new Firestore({ projectId, databaseId });
if (command === 'usage') {
  const options = parseUsageArgs(args);
  const now = Date.now();
  const { records, query } = await fetchUsageSessions(db, { ...options, now });
  const report = summarizeUsage(records, { ...options, now, query });
  console.log(JSON.stringify(await writeUsageReport(options.out, report)));
} else if (command === 'list') {
  const week = args[0];
  if (!/^\d{4}-\d{2}-\d{2}$/.test(week || '')) throw new Error('Usage: node admin.mjs list YYYY-MM-DD');
  const result = await db.collection('feedback').where('week', '==', week).limit(100).get();
  for (const doc of result.docs) {
    const record = doc.data();
    // Exclude any unexpected fields; output is private operational feedback.
    console.log(JSON.stringify({ id: doc.id, kind: record.kind, trackId: record.trackId, audioSha256: record.audioSha256, vote: record.vote, categories: record.categories, comment: record.comment, positionSeconds: record.positionSeconds, cueId: record.cueId, blockId: record.blockId, context: record.context, status: record.status, fixedVersion: record.fixedVersion, updatedAt: record.updatedAt?.toDate?.().toISOString() }));
  }
} else if (command === 'status') {
  const [id, status, fixedVersion] = args;
  if (!/^[a-f0-9]{64}-(?:vote|[a-f0-9-]{36})$/.test(id || '') || !['pending', 'confirmed', 'fixed'].includes(status) || (status === 'fixed' && !/^[a-zA-Z0-9._-]{1,100}$/.test(fixedVersion || '')) || (fixedVersion && !/^[a-zA-Z0-9._-]{1,100}$/.test(fixedVersion))) throw new Error('Usage: node admin.mjs status ID pending|confirmed|fixed [FIXED_VERSION]');
  await db.doc(`feedback/${id}`).update({ status, fixedVersion: status === 'fixed' ? fixedVersion : null, reviewedAt: new Date() });
  console.log(JSON.stringify({ ok: true, id, status }));
} else if (command === 'metrics') {
  const week = args[0];
  if (!/^\d{4}-\d{2}-\d{2}$/.test(week || '')) throw new Error('Usage: node admin.mjs metrics YYYY-MM-DD');
  const result = await db.collection('weeklyMetrics').where('week', '==', week).get();
  for (const doc of result.docs) console.log(JSON.stringify(doc.data()));
} else throw new Error('Commands: usage --from YYYY-MM-DD --to YYYY-MM-DD --out NEW_DIRECTORY; list YYYY-MM-DD; metrics YYYY-MM-DD; status ID pending|confirmed|fixed [FIXED_VERSION]');
