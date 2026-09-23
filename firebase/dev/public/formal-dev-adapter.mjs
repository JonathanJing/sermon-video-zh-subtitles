import { sameOriginAsset } from "./dev-integrity.mjs";

const SHA256 = /^[a-f0-9]{64}$/;
const PAGE_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;
const LOCALES = new Set(["zh-Hans", "ko", "es"]);

function requireValue(condition, message) {
  if (!condition) throw new Error(message);
}

function exactKeys(value, names) {
  return value && typeof value === "object" && !Array.isArray(value)
    && Object.keys(value).length === names.length
    && names.every(name => Object.hasOwn(value, name));
}

// The formal catalog is optional while older Dev POC pages remain available.
// A failed or malformed formal feed must not make the existing reader unusable.
export async function loadOptionalFormalCatalog(fetcher, existingPageIds = []) {
  try {
    const response = await fetcher("/multilingual-v2.json", { cache: "no-store" });
    if (response.status === 404) return null;
    if (!response.ok) throw new Error(`Formal Dev catalog: HTTP ${response.status}`);
    const catalog = validateFormalCatalog(await response.json());
    const existing = new Set(existingPageIds);
    requireValue(!catalog.pages.some(page => existing.has(page.id)),
      "Dev page ID reused across formal and POC catalogs");
    return catalog;
  } catch (error) {
    console.warn("Optional formal Dev catalog unavailable", error);
    return null;
  }
}

export function validateFormalCatalog(catalog) {
  requireValue(exactKeys(catalog, ["schemaVersion", "generatedAt", "defaultPageId", "pages"])
    && catalog.schemaVersion === "sermon-multilingual-catalog-v2"
    && Array.isArray(catalog.pages) && catalog.pages.length > 0
    && PAGE_ID.test(catalog.defaultPageId), "Invalid formal Dev catalog");
  const ids = new Set();
  for (const page of catalog.pages) {
    requireValue(exactKeys(page, ["id", "date", "sourceLocale", "sourceIdentitySha256", "defaultTargetLocale", "targets"])
      && PAGE_ID.test(page.id) && !ids.has(page.id)
      && page.sourceLocale === "en" && SHA256.test(page.sourceIdentitySha256)
      && /^\d{4}-\d{2}-\d{2}$/.test(page.date)
      && LOCALES.has(page.defaultTargetLocale)
      && page.targets && typeof page.targets === "object" && !Array.isArray(page.targets)
      && Object.keys(page.targets).length === 3
      && [...LOCALES].every(locale => page.targets[locale]), "Invalid formal Dev page");
    ids.add(page.id);
    for (const [locale, target] of Object.entries(page.targets)) {
      requireValue(LOCALES.has(locale)
        && exactKeys(target, ["releasePackageUrl", "releasePackageJsonSha256", "contentStatus", "audioStatus", "capabilities"])
        && target.releasePackageUrl === `/releases/${page.id}/${locale}.json`
        && SHA256.test(target.releasePackageJsonSha256)
        && target.contentStatus === "human_reviewed" && target.audioStatus === "human_reviewed"
        && Array.isArray(target.capabilities) && target.capabilities.length === 3
        && ["text", "captions", "audio"].every(value => target.capabilities.includes(value)),
      "Invalid formal Dev release reference");
    }
  }
  requireValue(ids.has(catalog.defaultPageId), "Formal default page absent");
  return catalog;
}

export function validateFormalRelease(release, page, locale) {
  const target = page.targets[locale];
  requireValue(target && exactKeys(release, [
    "schemaVersion", "packageId", "pageId", "sourceLocale", "targetLocale",
    "targetLanguageCandidateJsonSha256", "targetLanguageAudioPackageJsonSha256",
    "status", "contentStatus", "audioStatus", "interfaceLocale", "contentLocale", "audioLocale",
    "assets", "httpVerification", "deviceAcceptance", "venueAcceptance", "issues"
  ]) && release.schemaVersion === "sermon-target-language-release-package-v1"
    && release.pageId === page.id && release.targetLocale === locale && release.sourceLocale === "en"
    && SHA256.test(release.targetLanguageCandidateJsonSha256)
    && SHA256.test(release.targetLanguageAudioPackageJsonSha256)
    && release.contentStatus === "human_reviewed" && release.audioStatus === "human_reviewed"
    && release.interfaceLocale === locale && release.contentLocale === locale && release.audioLocale === locale
    && Array.isArray(release.issues) && release.issues.length === 0
    && ["candidate", "published_http_verified"].includes(release.status),
  "Invalid formal Dev release identity or review state");
  const http = release.httpVerification;
  requireValue(http && (release.status === "candidate"
    ? http.status === "not_run" && http.evidenceSha256 === null
    : http.status === "pass" && SHA256.test(http.evidenceSha256)),
  "Invalid formal Dev HTTP state");
  for (const gate of ["deviceAcceptance", "venueAcceptance"]) {
    requireValue(["not_run", "pass", "fail"].includes(release[gate]?.status)
      && (release[gate].status === "not_run"
        ? release[gate].evidenceSha256 === null : SHA256.test(release[gate].evidenceSha256)),
    "Invalid formal Dev acceptance state");
  }
  if (release.status === "candidate") {
    requireValue(release.deviceAcceptance.status === "not_run"
      && release.venueAcceptance.status === "not_run", "Candidate cannot claim device or venue acceptance");
  }
  requireValue(Array.isArray(release.assets) && release.assets.length === 3,
    "Formal Dev release requires three explicit assets");
  const expected = {
    content: [`/content/${page.id}/${locale}.json`, ".json"],
    audio: [`/media/${page.id}/${locale}.mp3`, ".mp3"],
    captions: [`/captions/${page.id}/${locale}.json`, ".json"]
  };
  const assets = {};
  for (const asset of release.assets) {
    const rule = expected[asset?.role];
    requireValue(exactKeys(asset, ["role", "path", "sha256"])
      && rule && !assets[asset.role] && asset.path === rule[0]
      && SHA256.test(asset.sha256), "Invalid formal Dev asset");
    sameOriginAsset(asset.path, rule[0], rule[1]);
    assets[asset.role] = asset;
  }
  requireValue(Object.keys(assets).length === 3, "Missing formal Dev asset");
  return { release, assets };
}

export function validateFormalContent(content, release, page, locale) {
  requireValue(exactKeys(content, [
    "schemaVersion", "pageId", "sourceLocale", "locale", "englishSourcePackageJsonSha256",
    "targetLanguageCandidateJsonSha256", "targetLanguageAudioPackageJsonSha256",
    "contentStatus", "audioStatus", "series", "title", "speaker", "scripture", "date",
    "summary", "durationSeconds", "cues", "outline"
  ]) && content.schemaVersion === "sermon-formal-dev-content-v1"
    && content.pageId === page.id && content.locale === locale && content.sourceLocale === "en"
    && content.englishSourcePackageJsonSha256 === page.sourceIdentitySha256
    && content.targetLanguageCandidateJsonSha256 === release.targetLanguageCandidateJsonSha256
    && content.targetLanguageAudioPackageJsonSha256 === release.targetLanguageAudioPackageJsonSha256
    && content.contentStatus === "human_reviewed" && content.audioStatus === "human_reviewed"
    && ["series", "title", "speaker", "scripture", "date", "summary"].every(key =>
      typeof content[key] === "string" && content[key].trim().length > 0)
    && Number.isFinite(content.durationSeconds) && content.durationSeconds > 0
    && Array.isArray(content.outline) && Array.isArray(content.cues) && content.cues.length > 0,
  "Invalid formal Dev content identity or review state");
  let previousEnd = 0;
  const groups = new Set();
  for (const cue of content.cues) {
    requireValue(exactKeys(cue, ["textGroupId", "sourceUnitIds", "start", "end", "text"])
      && typeof cue.textGroupId === "string" && cue.textGroupId.length > 0
      && !groups.has(cue.textGroupId)
      && Array.isArray(cue.sourceUnitIds) && cue.sourceUnitIds.length > 0
      && cue.sourceUnitIds.every(id => typeof id === "string" && id.length > 0)
      && Number.isFinite(cue.start) && Number.isFinite(cue.end)
      && cue.start >= previousEnd - 0.02 && cue.end > cue.start
      && cue.end <= content.durationSeconds + 0.1
      && typeof cue.text === "string" && cue.text.trim().length > 0,
    "Invalid formal Dev cue");
    groups.add(cue.textGroupId);
    previousEnd = cue.end;
  }
  return content;
}

export function validateFormalCaptions(captions, content) {
  requireValue(exactKeys(captions, ["cues"])
    && Array.isArray(captions.cues) && captions.cues.length === content.cues.length,
    "Invalid formal Dev captions");
  for (let index = 0; index < captions.cues.length; index++) {
    const cue = captions.cues[index];
    const expected = content.cues[index];
    requireValue(exactKeys(cue, ["textGroupId", "text", "start", "end"])
      && cue.textGroupId === expected.textGroupId && cue.text === expected.text
      && cue.start === expected.start && cue.end === expected.end,
    "Formal Dev captions differ from reviewed content");
  }
  return captions;
}

export function formalReleaseView(checked, page, locale) {
  const { release, assets } = checked;
  return {
    ...release,
    formal: true,
    pageUrl: `/pages/${page.id}/${locale}`,
    contentUrl: assets.content.path,
    contentSha256: assets.content.sha256,
    audioUrl: assets.audio.path,
    audioSha256: assets.audio.sha256,
    captionsUrl: assets.captions.path,
    captionsSha256: assets.captions.sha256
  };
}
