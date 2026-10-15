import { readFileSync } from 'node:fs';
import { Firestore } from '@google-cloud/firestore';
import { onRequest } from 'firebase-functions/v2/https';
import { error as logError } from 'firebase-functions/logger';
import { ApiError, createService } from './core.mjs';
import { firestoreStore } from './firestore-store.mjs';

// Deployment generates these two compact, non-secret files from the same catalog
// as the static App. A missing configuration fails closed during discovery.
const config = JSON.parse(readFileSync(new URL('./server-config.json', import.meta.url), 'utf8'));
const catalog = JSON.parse(readFileSync(new URL('./catalog.json', import.meta.url), 'utf8'));
if (!config.databaseId || config.databaseId === '(default)' || !/^[a-z][a-z0-9-]{2,62}$/.test(config.databaseId)) throw new Error('Named feedback database required');
if (!Array.isArray(config.origins) || config.origins.length === 0 || config.origins.some((origin) => !/^https:\/\/[^/]+$/.test(origin))) throw new Error('HTTPS origins required');
if (!/^[a-zA-Z0-9-]+@[a-zA-Z0-9-]+\.iam\.gserviceaccount\.com$/.test(config.serviceAccount || '')) throw new Error('Dedicated runtime identity required');
const db = new Firestore({ databaseId: config.databaseId, ...(config.projectId ? { projectId: config.projectId } : {}) });
const service = createService({ store: firestoreStore(db), catalog, origins: config.origins, limits: config.limits });

export const sermonFeedback = onRequest({
  region: 'us-west1', memory: '256MiB', timeoutSeconds: 15,
  minInstances: 0, maxInstances: 2, concurrency: 20,
  serviceAccount: config.serviceAccount, invoker: 'public', cors: false,
}, async (request, response) => {
  response.set('Cache-Control', 'private, no-store');
  response.set('X-Content-Type-Options', 'nosniff');
  try {
    const result = await service({
      method: request.method, path: request.path,
      origin: request.get('origin'), contentType: request.get('content-type'),
      body: request.body, rawBytes: request.rawBody?.length ?? 0,
      authorization: request.get('authorization'), address: request.ip,
    });
    response.status(200).json(result);
  } catch (error) {
    if (error instanceof ApiError) {
      if (error.status === 429) response.set('Retry-After', '60');
      response.status(error.status).json({ ok: false, error: error.code });
    } else {
      // Never serialize errors: vendor errors may contain headers, tokens, or
      // user-supplied text. Platform request logs have a separate retention policy.
      logError('feedback_api_failure', { code: 'storage_unavailable' });
      response.status(503).json({ ok: false, error: 'temporarily_unavailable' });
    }
  }
});
