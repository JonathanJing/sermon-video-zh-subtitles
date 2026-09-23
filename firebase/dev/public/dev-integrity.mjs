const SHA256 = /^[a-f0-9]{64}$/;
const PAGE_ID = /^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$/;
const LOCALE = /^(?:en|zh-Hans|ko|es|vi)$/;

function requireValue(ok, message) {
  if (!ok) throw new Error(message);
}

export function sameOriginAsset(path, prefix, suffix, origin = globalThis.location?.origin || "https://ai-for-god-sermon-audio-dev.web.app") {
  requireValue(typeof path === "string" && path.startsWith(prefix) && path.endsWith(suffix)
    && !path.includes("%") && !path.includes("?") && !path.includes("#")
    && !path.includes("\\") && !path.split("/").includes(".."), "Invalid Dev asset path");
  const url = new URL(path, origin);
  requireValue(url.origin === origin && url.pathname === path && !url.search && !url.hash, "Foreign Dev asset");
  return url;
}

export function validateDemoCatalog(catalog) {
  requireValue(catalog?.schemaVersion === "sermon-multilingual-demo-catalog-v1"
    && catalog.environment === "development" && catalog.poc === true
    && Array.isArray(catalog.pages) && catalog.pages.length > 0
    && PAGE_ID.test(catalog.defaultPageId), "Invalid Dev catalog");
  const ids = new Set();
  for (const page of catalog.pages) {
    requireValue(PAGE_ID.test(page.id) && !ids.has(page.id)
      && page.targets && typeof page.targets === "object" && !Array.isArray(page.targets)
      && LOCALE.test(page.defaultTargetLocale) && page.targets[page.defaultTargetLocale], "Invalid Dev page");
    ids.add(page.id);
    for (const [locale, target] of Object.entries(page.targets)) {
      requireValue(LOCALE.test(locale)
        && target.releasePackageUrl === `/releases/${page.id}/${locale}.json`
        && SHA256.test(target.releasePackageJsonSha256), "Invalid Dev release reference");
    }
  }
  requireValue(catalog.pages.some(page => page.id === catalog.defaultPageId), "Missing Dev default page");
  return catalog;
}

export function validateDemoRelease(release, page, locale) {
  const schema = locale === "en" ? "sermon-source-language-demo-package-v1" : "sermon-target-language-demo-package-v1";
  const target = page.targets[locale];
  requireValue(target && release?.schemaVersion === schema && release.environment === "development"
    && release.poc === true && release.productionEligible === false && release.humanApproval === false
    && release.pageId === page.id && release.targetLocale === locale && release.sourceLocale === "en"
    && release.pageUrl === `/pages/${page.id}/${locale}`
    && release.contentUrl === `/content/${page.id}/${locale}.json`
    && SHA256.test(release.contentSha256)
    && release.contentStatus === target.contentStatus && release.audioStatus === target.audioStatus,
    "Invalid Dev release identity or review state");
  const prefix = `/media/${page.id}/`;
  sameOriginAsset(release.audioUrl, prefix, ".mp3");
  if (release.audioSha256 !== undefined) requireValue(SHA256.test(release.audioSha256), "Invalid Dev audio hash");
  const variants = release.audioVariants || [];
  requireValue(Array.isArray(variants) && variants.length <= 20, "Invalid Dev audio variants");
  const ids = new Set();
  for (const variant of variants) {
    requireValue(PAGE_ID.test(variant.id) && !ids.has(variant.id)
      && SHA256.test(variant.audioSha256)
      && Number.isFinite(variant.durationSeconds) && variant.durationSeconds > 0,
      "Invalid Dev audio variant");
    sameOriginAsset(variant.audioUrl, prefix, ".mp3");
    if (variant.cues !== undefined) {
      requireValue(Array.isArray(variant.cues) && variant.cues.length > 0, "Invalid Dev variant cues");
      let end = 0;
      for (const cue of variant.cues) {
        requireValue(Number.isFinite(cue.start) && Number.isFinite(cue.end)
          // One retained acoustic-review variant has a 0.30s cue overlap.
          && cue.start >= end - 0.5 && cue.end > cue.start
          && cue.end <= variant.durationSeconds + 0.1 && typeof cue.text === "string",
          "Invalid Dev variant cue");
        end = cue.end;
      }
    }
    if (variant.audioUrl === release.audioUrl) {
      requireValue(variant.audioSha256 === release.audioSha256, "Dev base audio hash mismatch");
    }
    ids.add(variant.id);
  }
  requireValue(variants.length > 0 ? ids.has(release.defaultAudioVariantId)
    : SHA256.test(release.audioSha256), "Missing Dev audio hash");
  return release;
}

export function validateDemoContent(content, release, locale) {
  requireValue(content?.schemaVersion === "sermon-demo-content-v1"
    && content.poc === true && content.locale === locale
    && content.translationStatus === release.contentStatus
    && content.humanReview?.humanApproval === false
    && Number.isFinite(content.durationSeconds) && content.durationSeconds > 0
    && Array.isArray(content.cues) && content.cues.length > 0
    && Array.isArray(content.outline), "Invalid Dev content identity or review state");
  let end = 0;
  for (const cue of content.cues) {
    requireValue(Number.isFinite(cue.start) && Number.isFinite(cue.end)
      && cue.start >= end - 0.02 && cue.end > cue.start
      && cue.end <= content.durationSeconds + 0.1 && typeof cue.text === "string",
      "Invalid Dev content cue");
    end = cue.end;
  }
  return content;
}

export async function fetchVerified(path, expectedSha256, {
  fetchImpl = fetch, origin = location.origin, maxBytes = 24 * 1024 * 1024, signal
} = {}) {
  requireValue(SHA256.test(expectedSha256), "Missing Dev asset hash");
  const url = sameOriginAsset(path, "/", path.endsWith(".json") ? ".json" : ".mp3", origin);
  const response = await fetchImpl(url.href, { cache: "no-store", credentials: "omit", redirect: "error", signal });
  requireValue(response.ok && (!response.url || new URL(response.url).origin === origin), "Dev asset unavailable");
  const declared = Number(response.headers?.get("content-length"));
  requireValue(!Number.isFinite(declared) || declared <= maxBytes, "Dev asset too large");
  const bytes = new Uint8Array(await response.arrayBuffer());
  requireValue(bytes.byteLength > 0 && bytes.byteLength <= maxBytes, "Dev asset too large or empty");
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  const received = [...new Uint8Array(digest)].map(value => value.toString(16).padStart(2, "0")).join("");
  requireValue(received === expectedSha256, "Dev asset hash mismatch");
  return bytes;
}
