import { readFileSync } from 'node:fs';
import { Firestore } from '@google-cloud/firestore';
import { onRequest } from 'firebase-functions/v2/https';
import { error as logError } from 'firebase-functions/logger';
import { PushApiError, createSourceLimiter, createSubscriptionService } from './core.mjs';
import { firestoreStore } from './firestore-store.mjs';

// Deployment places this non-secret file alongside the function. Missing or
// placeholder configuration fails closed at cold start.
const config = JSON.parse(readFileSync(new URL('./server-config.json', import.meta.url), 'utf8'));
if (config.projectId !== 'ai-for-god-caption-dev' ||
    !/^[a-z][a-z0-9-]{2,62}$/.test(config.databaseId) || config.databaseId === '(default)' ||
    config.serviceAccount !== 'sermon-push-runtime@ai-for-god-caption-dev.iam.gserviceaccount.com') {
  throw new Error('Dedicated production push identity and named database required');
}
const db = new Firestore({ projectId: config.projectId, databaseId: config.databaseId });
const subscribe = createSubscriptionService({ store: firestoreStore(db),
  maxPerMinute: config.maxPerMinute ?? 600, maxPerDay: config.maxPerDay ?? 10000 });
const checkSource = createSourceLimiter();

export const sermonPushSubscription = onRequest({
  region: 'us-west1', memory: '256MiB', timeoutSeconds: 15,
  minInstances: 0, maxInstances: 2, concurrency: 20,
  serviceAccount: config.serviceAccount, invoker: 'public', cors: false,
}, async (request, response) => {
  response.set('Cache-Control', 'private, no-store');
  response.set('X-Content-Type-Options', 'nosniff');
  response.set('Referrer-Policy', 'no-referrer');
  try {
    if (request.method !== 'POST' || !['/api/push/subscription', '/subscription', '/'].includes(request.path)) {
      throw new PushApiError(404, 'not_found');
    }
    const origin = request.get('origin');
    // Native iOS sends no Origin. Browser callers are restricted to the same
    // production site; Origin is not treated as an authentication factor.
    if (origin && origin !== 'https://ai-for-god-sermon-audio.web.app') {
      throw new PushApiError(403, 'origin_unavailable');
    }
    const bodyBytes = request.rawBody?.length ?? Buffer.byteLength(JSON.stringify(request.body ?? null));
    if (!/^application\/json(?:\s*;\s*charset=utf-8)?$/i.test(request.get('content-type') || '') ||
        bodyBytes > 4096) throw new PushApiError(415, 'invalid_content_type_or_size');
    checkSource(request.ip || 'unknown');
    const result = await subscribe(request.body);
    response.status(200).json(result);
  } catch (error) {
    if (error instanceof PushApiError) {
      if (error.status === 429) response.set('Retry-After', '60');
      response.status(error.status).json({ ok: false, error: error.code });
    } else {
      // Never log request bodies, APNs tokens, subscription secrets or vendor
      // errors. Platform request metadata has its own retention policy.
      logError('push_subscription_failure', { code: 'storage_unavailable' });
      response.status(503).json({ ok: false, error: 'temporarily_unavailable' });
    }
  }
});
