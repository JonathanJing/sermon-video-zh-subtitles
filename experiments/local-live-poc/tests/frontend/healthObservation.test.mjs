import test from "node:test";
import assert from "node:assert/strict";
import { healthObservation } from "../../src/healthObservation.js";

test("offline measurements remain unknown rather than claiming healthy zeros", () => {
  const sample = healthObservation(null);
  assert.equal(sample.status, "offline");
  assert.equal(sample.storageFreeBytes, null);
  assert.equal(sample.publisherFailureCount, null);
  assert.equal(sample.asrAvailable, null);
});

test("records degradation and counters without copying private health details", () => {
  const sample = healthObservation({
    status: "degraded", sessionStorage: { available: false, freeBytes: 42, reason: "secret-marker" },
    liveProgress: { degraded: true, streams: [{ asrQueueDepth: 3, translationQueueDepth: 2, reason: "secret-marker" }] },
    publicViewer: { publishFailureCount: 7, queueDepth: 2, lastError: "secret-marker", url: "secret-marker" },
  });
  assert.equal(sample.storageAvailable, false);
  assert.equal(sample.storageFreeBytes, 42);
  assert.equal(sample.liveDegraded, true);
  assert.equal(sample.streams[0].asrQueueDepth, 3);
  assert.equal(sample.publisherFailureCount, 7);
  assert.ok(!JSON.stringify(sample).includes("secret-marker"));
  assert.equal(healthObservation({ sessionStorage: { freeBytes: Infinity } }).storageFreeBytes, null);
});
