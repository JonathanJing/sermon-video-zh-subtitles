import assert from "node:assert/strict";
import test from "node:test";

import {
  appendAudioChunk,
  startLocalSession,
  translateCaption,
} from "../../src/gatewayClient.js";

function response(payload, { ok = true, status = 200 } = {}) {
  return {
    ok,
    status,
    json: async () => payload,
  };
}

test("startLocalSession sends one JSON request", async () => {
  let observed;
  const result = await startLocalSession(
    { audioMimeType: "audio/webm" },
    async (url, options) => {
      observed = { url, options };
      return response({ sessionId: "session-1" }, { status: 201 });
    },
  );

  assert.equal(result.sessionId, "session-1");
  assert.match(observed.url, /\/api\/sessions\/start$/);
  assert.equal(observed.options.method, "POST");
  assert.deepEqual(JSON.parse(observed.options.body), { audioMimeType: "audio/webm" });
});

test("appendAudioChunk preserves sequence, content type, and body", async () => {
  const chunk = new Blob(["audio"]);
  let observed;
  await appendAudioChunk("session-1", 3, chunk, "audio/webm;codecs=opus", async (url, options) => {
    observed = { url, options };
    return response({ audioChunkCount: 3 });
  });

  assert.match(observed.url, /\/api\/sessions\/session-1\/audio\?sequence=3$/);
  assert.equal(observed.options.headers["Content-Type"], "audio/webm;codecs=opus");
  assert.equal(observed.options.body, chunk);
});

test("translation errors expose the gateway message", async () => {
  await assert.rejects(
    translateCaption(
      { sourceTextEn: "Grace leads us." },
      async () => response({ message: "model unavailable" }, { ok: false, status: 503 }),
    ),
    /model unavailable/,
  );
});
