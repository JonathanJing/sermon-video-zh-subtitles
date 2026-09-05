import assert from "node:assert/strict";
import test from "node:test";
import {
  V41_TRANSLATION_PROVIDER as V41, initialTranslationProvider,
  assertTranslationSession, healthForTranslationProvider, providerContextPolicy,
} from "../../src/translationProvider.js";
import { startV41TranslationRuntime, startLocalSession } from "../../src/gatewayClient.js";
import { healthObservation } from "../../src/healthObservation.js";

function v41Session() {
  return {
    sessionId: "v41-session",
    metadata: {
      translationProvider: V41,
      translationSelectionSchema: "local-live-translation-selection-v1",
      experimental: true,
      releaseEligible: false,
      publicSharingAllowed: false,
      contextPolicy: "none",
      runtimeIdentity: {
        schemaVersion: "local-live-runtime-identity-v2",
        configuration: {
          translationProvider: V41,
          translationModel: "milmmt-sermon-v41-experimental-mlx-q5",
          translationExpectedModelDigest: "6057e793922b8aa0c30c5180b490d8e5cac14a3dcd1a000b1b906d0da8fa6987",
          publicSharingAllowed: false,
        },
      },
    },
  };
}

test("v4.1 sessions require the versioned runtime binding and local experimental restrictions", () => {
  const session = v41Session();
  assert.doesNotThrow(() => assertTranslationSession(session, V41));
  for (const legacy of [null, {}, { sessionId: "old-gateway-session" }, { metadata: {} }]) {
    assert.throws(() => assertTranslationSession(legacy, V41), /Gateway 未确认 v4\.1 实验会话/);
  }
});

test("v4.1 sessions reject forged or incomplete provider, model, policy and runtime bindings", () => {
  const mutations = [
    ["missing selected provider", (metadata) => { delete metadata.translationProvider; }],
    ["baseline selected provider", (metadata) => { metadata.translationProvider = "ollama"; }],
    ["missing selection schema", (metadata) => { delete metadata.translationSelectionSchema; }],
    ["unknown selection schema", (metadata) => { metadata.translationSelectionSchema = "local-live-translation-selection-v999"; }],
    ["missing experimental status", (metadata) => { delete metadata.experimental; }],
    ["release eligible", (metadata) => { metadata.releaseEligible = true; }],
    ["sharing allowed", (metadata) => { metadata.publicSharingAllowed = true; }],
    ["candidate context enabled", (metadata) => { metadata.contextPolicy = "weekly_terms_v1"; }],
    ["missing runtime identity", (metadata) => { delete metadata.runtimeIdentity; }],
    ["legacy runtime schema", (metadata) => { metadata.runtimeIdentity.schemaVersion = "local-live-runtime-identity-v1"; }],
    ["baseline runtime provider", (metadata) => { metadata.runtimeIdentity.configuration.translationProvider = "ollama"; }],
    ["different runtime model", (metadata) => { metadata.runtimeIdentity.configuration.translationModel = "milmmt-base"; }],
    ["different model digest", (metadata) => { metadata.runtimeIdentity.configuration.translationExpectedModelDigest = "0".repeat(64); }],
    ["missing model digest", (metadata) => { delete metadata.runtimeIdentity.configuration.translationExpectedModelDigest; }],
    ["runtime sharing allowed", (metadata) => { metadata.runtimeIdentity.configuration.publicSharingAllowed = true; }],
  ];
  for (const [label, mutate] of mutations) {
    const session = v41Session();
    mutate(session.metadata);
    assert.throws(() => assertTranslationSession(session, V41), /Gateway 未确认 v4\.1 实验会话/, label);
  }
});

test("baseline sessions remain compatible with legacy gateway metadata", () => {
  assert.doesNotThrow(() => assertTranslationSession({ sessionId: "old-gateway-session" }, "ollama"));
});

test("default launch keeps baseline while explicit v4.1 link selects the experiment", () => {
  assert.equal(initialTranslationProvider(), "ollama");
  assert.equal(initialTranslationProvider("?translationProvider=unknown"), "ollama");
  assert.equal(initialTranslationProvider(`?translationProvider=${V41}`), V41);
});

test("a ready baseline cannot hide an unavailable selected candidate", () => {
  const original = {
    status: "ready", coreReady: true,
    ollama: { configuredModelInstalled: true },
    translationProviders: { ollama: { ready: true }, [V41]: { ready: false } },
  };
  const selected = healthForTranslationProvider(original, V41);
  assert.equal(selected.status, "degraded");
  assert.equal(healthObservation(selected).translationAvailable, false);
  assert.equal(healthObservation(selected).translationProvider, V41);
  assert.equal(original.status, "ready");
});

test("a ready candidate works independently of baseline availability but needs ASR and storage", () => {
  const health = { status: "degraded", coreReady: true, translationProviders: { [V41]: { ready: true } } };
  assert.equal(healthForTranslationProvider(health, V41).status, "ready");
  assert.equal(healthForTranslationProvider({ ...health, coreReady: false }, V41).status, "degraded");
  assert.equal(healthForTranslationProvider({ ...health, status: "offline" }, V41).status, "offline");
  assert.equal(healthForTranslationProvider(null, V41), null);
});

test("an old gateway does not accidentally offer v4.1 or drop the baseline context", () => {
  const health = { status: "ready", defaultContextPolicy: "weekly_terms_v1", ollama: { configuredModelInstalled: true } };
  assert.equal(healthForTranslationProvider(health, "ollama").status, "ready");
  assert.equal(healthForTranslationProvider(health, V41).status, "degraded");
  assert.equal(providerContextPolicy(health, V41), "none");
  assert.equal(providerContextPolicy(health, "ollama"), "weekly_terms_v1");
});

test("the model launcher sends no arbitrary command arguments", async () => {
  let observed;
  const result = await startV41TranslationRuntime(async (url, options) => {
    observed = { url, options };
    return { ok: true, json: async () => ({ ready: true }) };
  });
  assert.equal(result.ready, true);
  assert.match(observed.url, /\/api\/translation\/providers\/milmmt-v41-mlx\/start$/);
  assert.equal(observed.options.method, "POST");
  assert.deepEqual(JSON.parse(observed.options.body), {});
  await assert.rejects(startV41TranslationRuntime(async () => ({
    ok: false, status: 503, json: async () => ({ message: "candidate unavailable" }),
  })), /candidate unavailable/);
});

test("recording creation carries the chosen provider alongside context", async () => {
  let payload;
  await startLocalSession({ audioMimeType: "audio/webm", translationProvider: V41, contextPolicy: "none" }, async (_, options) => {
    payload = JSON.parse(options.body);
    return { ok: true, json: async () => ({ sessionId: "test" }) };
  });
  assert.equal(payload.translationProvider, V41);
  assert.equal(payload.contextPolicy, "none");
});
