#!/usr/bin/env node
/** Publish one bounded snapshot, or watch local evidence and refresh it on change. */
import { createHash } from 'node:crypto';
import { existsSync, readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { setTimeout as delay } from 'node:timers/promises';
import { sanitizeSnapshot } from './sanitize.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, '../../..');
const BUILDER = resolve(REPO, 'scripts/build_four_layer_tracker_snapshot.py');
const ARG_MAP = {
  ledger: '--ledger', out: '--out', sourceMonitor: '--source-monitor',
  sourcePageUrl: '--source-page-url', serviceDate: '--service-date',
  catalog: '--catalog', publicRoot: '--public-root', httpReceipt: '--http-receipt',
  siteUrl: '--site-url', sourceState: '--source-state',
};

export function parseArgs(argv) {
  const result = { execute: false, watch: false, intervalSeconds: 15 };
  for (let index = 0; index < argv.length; index += 1) {
    const key = argv[index];
    if (key === '--execute' || key === '--watch') {
      result[key.slice(2)] = true;
      continue;
    }
    if (!['--project', '--database', '--snapshot', '--watch-config', '--interval-seconds'].includes(key)) {
      throw new Error(`unsupported argument: ${key}`);
    }
    if (!argv[index + 1]) throw new Error(`missing value for ${key}`);
    const name = key.replace(/^--/, '').replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
    result[name] = argv[++index];
  }
  if (!result.project || !/^[a-z][a-z0-9-]{4,28}[a-z0-9]$/.test(result.project)) {
    throw new Error('valid Firebase project ID required');
  }
  if (!result.database || !/^[a-z][a-z0-9-]{2,62}$/.test(result.database)) {
    throw new Error('valid dedicated Firestore database ID required');
  }
  if (result.watch && (!result.execute || !result.watchConfig)) {
    throw new Error('--watch requires --execute and --watch-config');
  }
  if (!result.snapshot && !result.watchConfig) throw new Error('--snapshot or --watch-config required');
  result.intervalSeconds = Number(result.intervalSeconds);
  if (!Number.isFinite(result.intervalSeconds) || result.intervalSeconds < 5) {
    throw new Error('interval must be at least 5 seconds');
  }
  return result;
}

export function validateSnapshot(snapshot) {
  return sanitizeSnapshot(snapshot);
}

function buildFromConfig(path) {
  const config = JSON.parse(readFileSync(path, 'utf8'));
  if (!config.ledger || !config.out) throw new Error('watch config requires ledger and out');
  const args = [];
  for (const [field, flag] of Object.entries(ARG_MAP)) {
    if (config[field]) args.push(flag, String(config[field]));
  }
  for (const path of config.releasePackages || []) args.push('--release-package', String(path));
  for (const path of config.fingerprintEvidence || []) args.push('--fingerprint-evidence', String(path));
  execFileSync(process.env.PYTHON || 'python3', [BUILDER, ...args], {
    cwd: REPO, stdio: 'pipe', timeout: 30000,
  });
  return resolve(REPO, config.out);
}

function readSnapshot(path) {
  if (!existsSync(path)) throw new Error(`snapshot missing: ${path}`);
  return validateSnapshot(JSON.parse(readFileSync(path, 'utf8')));
}

function semanticHash(snapshot) {
  const copy = { ...snapshot };
  delete copy.generatedAt;
  return createHash('sha256').update(JSON.stringify(copy)).digest('hex');
}

async function run(options) {
  let db = null;
  let previous = null;
  while (true) {
    try {
      const path = options.watchConfig ? buildFromConfig(resolve(options.watchConfig))
        : resolve(options.snapshot);
      const snapshot = readSnapshot(path);
      const hash = semanticHash(snapshot);
      if (hash !== previous) {
        if (options.execute) {
          if (!db) {
            const [{ applicationDefault, initializeApp }, { getFirestore }] = await Promise.all([
              import('firebase-admin/app'), import('firebase-admin/firestore'),
            ]);
            const app = initializeApp({ credential: applicationDefault(), projectId: options.project });
            db = getFirestore(app, options.database);
          }
          await db.collection('sermonTrackerRuns').doc(snapshot.pageId).set({
            schemaVersion: snapshot.schemaVersion,
            pageId: snapshot.pageId,
            serviceDate: snapshot.serviceDate || null,
            updatedAt: snapshot.generatedAt,
            snapshot,
          });
        }
        previous = hash;
        console.log(JSON.stringify({ pageId: snapshot.pageId, target: snapshot.target,
          complete: snapshot.progress.complete, total: snapshot.progress.total,
          status: options.execute ? 'published' : 'validated_not_published' }));
      }
    } catch (error) {
      console.error(JSON.stringify({ status: 'error', reason: error.message }));
      if (!options.watch) process.exitCode = 1;
    }
    if (!options.watch) return;
    await delay(options.intervalSeconds * 1000);
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { await run(parseArgs(process.argv.slice(2))); }
  catch (error) { console.error(error.message); process.exitCode = 1; }
}
