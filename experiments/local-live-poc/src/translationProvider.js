export const DEFAULT_TRANSLATION_PROVIDER = "ollama";
export const V41_TRANSLATION_PROVIDER = "milmmt-v41-mlx";
export const TRANSLATION_SELECTION_SCHEMA = "local-live-translation-selection-v1";

export function assertTranslationSession(session, provider) {
  if (provider !== V41_TRANSLATION_PROVIDER) return;
  const metadata = session?.metadata;
  const identity = metadata?.runtimeIdentity;
  const config = identity?.configuration;
  if (metadata?.translationProvider !== provider
    || metadata?.translationSelectionSchema !== TRANSLATION_SELECTION_SCHEMA
    || metadata?.experimental !== true || metadata?.releaseEligible !== false
    || metadata?.publicSharingAllowed !== false || metadata?.contextPolicy !== "none"
    || identity?.schemaVersion !== "local-live-runtime-identity-v2"
    || config?.translationProvider !== provider
    || config?.translationModel !== "milmmt-sermon-v41-experimental-mlx-q5"
    || config?.translationExpectedModelDigest !== "6057e793922b8aa0c30c5180b490d8e5cac14a3dcd1a000b1b906d0da8fa6987"
    || config?.publicSharingAllowed !== false) {
    throw new Error("Gateway 未确认 v4.1 实验会话及本机限制，请重启后台后恢复字幕");
  }
}

export function isTranslationStreamReady(event, provider) {
  return provider !== V41_TRANSLATION_PROVIDER || (
    event?.translationProvider === provider
    && event?.translationSelectionSchema === TRANSLATION_SELECTION_SCHEMA
    && event?.experimental === true
    && event?.viewer?.disabledReason === "experimental_local_only"
    && Array.isArray(event.viewer.urls) && event.viewer.urls.length === 0
    && event.viewer.publicUrl === null
  );
}

export function initialTranslationProvider(search = "") {
  return new URLSearchParams(search).get("translationProvider") === V41_TRANSLATION_PROVIDER
    ? V41_TRANSLATION_PROVIDER : DEFAULT_TRANSLATION_PROVIDER;
}

export function translationProviderStatus(health, provider = DEFAULT_TRANSLATION_PROVIDER) {
  if (health?.translationProviders?.[provider]) return health.translationProviders[provider];
  if (provider === DEFAULT_TRANSLATION_PROVIDER) {
    return { ...health?.ollama, id: provider, ready: Boolean(health?.ollama?.configuredModelInstalled), experimental: false };
  }
  return { id: provider, ready: false, available: false, experimental: true, startSupported: false };
}

export function providerContextPolicy(health, provider) {
  return provider === V41_TRANSLATION_PROVIDER ? "none" : health?.defaultContextPolicy || "none";
}

// Health and recording recovery must follow the chosen model, even when the
// other provider is healthy. Keep the original provider payloads for evidence.
export function healthForTranslationProvider(health, provider = DEFAULT_TRANSLATION_PROVIDER) {
  if (!health) return null;
  const selected = translationProviderStatus(health, provider);
  const coreReady = health.coreReady ?? Boolean(
    health.asr?.available && health.sessionStorage?.available && !health.liveProgress?.degraded,
  );
  return {
    ...health,
    status: health.status === "offline" ? "offline"
      : provider === DEFAULT_TRANSLATION_PROVIDER && health.coreReady === undefined ? health.status
      : coreReady && selected.ready ? "ready" : "degraded",
    selectedTranslationProvider: provider,
    translationAvailable: Boolean(selected.ready),
  };
}
