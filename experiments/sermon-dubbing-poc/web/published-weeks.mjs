// Runtime bridge from published Layer 4 assets to the existing listening App.
// Only the small JSON assets are fetched here. Audio plays directly from Hosting.
const LOCALES = ['zh-Hans', 'ko', 'es'];
const LABELS = {
  'zh-Hans': {
    source: '完整视频', audio: '中文同步配音', voice: 'Eric Geiger · AI 配音',
    notice: 'AI 配音采用已批准的精简口播稿，字幕随配音播放；完整文稿另列供阅读。',
    review: '完整文稿及配音均已人工审核批准',
    stages: [['文稿审核', '完整文稿已审核批准。'], ['配音与字幕', '配音已审核批准，字幕采用对应口播稿。'], ['线上发布', '正式音轨及文稿已发布，线上文件核验通过。']],
    // A machine quality waiver is never a human approval; wording follows each product's own status.
    machine: {
      label: '机器质检', join: '；',
      text: { human_reviewed: '完整文稿已人工审核批准', machine_checked: '完整文稿经机器质检，未经人工审核' },
      audio: { human_reviewed: '配音已人工审核批准', machine_checked: '配音经机器质检，未经人工审核' },
      both: '完整文稿及配音均经机器质检，未经人工审核',
      notice: 'AI 配音经机器质检，未经人工审核；配音采用精简口播稿，字幕随配音播放，完整文稿另列供阅读。',
      textStage: ['文稿机器质检', '完整文稿经机器质检后自动发布，未经人工审核。'],
      audioStage: ['配音与字幕机器质检', '配音经机器质检后自动发布，未经人工审核；字幕采用对应口播稿。'],
      fullTextHint: '以下完整阅读文稿经机器质检后自动发布，未经人工审核；时间对应英文原视频。配音使用较短口播稿，跟读请查看配音字幕。',
      spokenHint: '当前字幕跟随较短口播配音；该配音经机器质检，未经人工审核。',
    },
  },
  ko: {
    source: '전체 영상', audio: '한국어 동기화 더빙', voice: 'Eric Geiger · AI 더빙',
    notice: 'AI 더빙은 승인된 간결한 구술 원고를 사용합니다. 자막은 더빙을 따르며 전체 읽기 원고는 별도로 제공됩니다.',
    review: '전체 원고와 더빙의 사람 검토 및 승인이 기록되었습니다',
    stages: [['원고 검토', '전체 원고가 검토 및 승인되었습니다.'], ['더빙과 자막', '더빙이 검토 및 승인되었으며 자막은 해당 구술 원고를 사용합니다.'], ['온라인 게시', '정식 음원과 원고가 게시되었고 온라인 파일 검증을 통과했습니다.']],
    machine: {
      label: '기계 품질 검사', join: '; ',
      text: { human_reviewed: '전체 원고의 사람 검토 및 승인이 기록되었습니다', machine_checked: '전체 원고는 기계 품질 검사를 거쳤으며 사람의 검토를 거치지 않았습니다' },
      audio: { human_reviewed: '더빙의 사람 검토 및 승인이 기록되었습니다', machine_checked: '더빙은 기계 품질 검사를 거쳤으며 사람의 검토를 거치지 않았습니다' },
      both: '전체 원고와 더빙은 기계 품질 검사를 거쳤으며 사람의 검토를 거치지 않았습니다',
      notice: 'AI 더빙은 기계 품질 검사를 거쳤으며 사람의 검토를 거치지 않았습니다. 간결한 구술 원고를 사용하며 자막은 더빙을 따르고 전체 읽기 원고는 별도로 제공됩니다.',
      textStage: ['원고 기계 품질 검사', '전체 원고는 기계 품질 검사 후 자동으로 게시되었으며 사람의 검토를 거치지 않았습니다.'],
      audioStage: ['더빙과 자막 기계 품질 검사', '더빙은 기계 품질 검사 후 자동으로 게시되었으며 사람의 검토를 거치지 않았습니다. 자막은 해당 구술 원고를 사용합니다.'],
      fullTextHint: '기계 품질 검사 후 자동으로 게시된 전체 읽기 원고이며 사람의 검토를 거치지 않았습니다. 시간은 영어 원본 영상을 기준으로 합니다. 음성에는 짧게 다듬은 원고를 사용하므로 들으면서 따라 읽을 때는 음성 자막을 보세요.',
      spokenHint: '현재 자막은 짧은 낭독 원고의 음성을 따릅니다. 이 더빙은 기계 품질 검사를 거쳤으며 사람의 검토를 거치지 않았습니다.',
    },
  },
  es: {
    source: 'Video completo', audio: 'Doblaje sincronizado en español', voice: 'Eric Geiger · doblaje con IA',
    notice: 'El doblaje con IA utiliza el guion oral abreviado aprobado. Los subtítulos siguen el audio; el texto íntegro se ofrece por separado.',
    review: 'El texto íntegro y el doblaje tienen revisión y aprobación humanas registradas',
    stages: [['Revisión del texto', 'El texto íntegro está revisado y aprobado.'], ['Doblaje y subtítulos', 'El doblaje está revisado y aprobado; los subtítulos utilizan su guion oral.'], ['Publicación', 'El audio oficial y el texto están publicados y sus archivos en línea están verificados.']],
    machine: {
      label: 'Control de calidad automático', join: '; ',
      text: { human_reviewed: 'El texto íntegro tiene revisión y aprobación humanas registradas', machine_checked: 'El texto íntegro pasó un control de calidad automático, sin revisión humana' },
      audio: { human_reviewed: 'el doblaje tiene revisión y aprobación humanas registradas', machine_checked: 'el doblaje pasó un control de calidad automático, sin revisión humana' },
      both: 'El texto íntegro y el doblaje pasaron un control de calidad automático, sin revisión humana',
      notice: 'El doblaje con IA pasó un control de calidad automático, sin revisión humana. Utiliza el guion oral abreviado; los subtítulos siguen el audio y el texto íntegro se ofrece por separado.',
      textStage: ['Control automático del texto', 'El texto íntegro se publicó automáticamente tras un control de calidad automático, sin revisión humana.'],
      audioStage: ['Control automático del doblaje y subtítulos', 'El doblaje se publicó automáticamente tras un control de calidad automático, sin revisión humana; los subtítulos utilizan su guion oral.'],
      fullTextHint: 'Este texto completo para leer se publicó automáticamente tras un control de calidad automático, sin revisión humana. Los tiempos corresponden al vídeo original en inglés. El audio usa un guion más breve; sigue los subtítulos de la narración mientras escuchas.',
      spokenHint: 'Estos subtítulos siguen la narración abreviada. El doblaje pasó un control de calidad automático, sin revisión humana.',
    },
  },
};
const CATALOG_V3 = 'sermon-multilingual-catalog-v3', CATALOG_V4 = 'sermon-multilingual-catalog-v4';
const RELEASE_V2 = 'sermon-target-language-release-package-v2', RELEASE_V3 = 'sermon-target-language-release-package-v3';
const RELEASE_V4 = 'sermon-target-language-release-package-v4';
const STUDY_RELEASES = [RELEASE_V3, RELEASE_V4];
const CONTENT_V1 = 'sermon-full-video-text-content-v1', CONTENT_V2 = 'sermon-full-video-text-content-v2';
const CONTENT_V3 = 'sermon-full-video-text-content-v3';
// machine_checked = a bound machine quality waiver passed. Never a human approval.
const PRODUCT_STATUSES = ['human_reviewed', 'machine_checked'];
const REVIEW_BASIS_KINDS = ['human_review', 'machine_quality_waiver'];
const HASH = /^[a-f0-9]{64}$/;
const ID = /^[A-Za-z0-9_-]{1,160}$/;
const LOCALE = /^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$/;
const required = (condition, message) => { if (!condition) throw new Error(message); };
const text = value => typeof value === 'string' && value.trim().length > 0;

function assetPath(value) {
  required(typeof value === 'string' && /^\/[A-Za-z0-9_./-]+$/.test(value)
    && !value.includes('//') && !value.split('/').some(part => part === '.' || part === '..'), 'Unsafe published asset path');
  return value;
}

async function readJson(fetchImpl, path, expectedHash, timeoutMs, optional = false, pageSignal) {
  const controller = new AbortController();
  let timer;
  let rejectCancelled;
  const onCancel = () => {
    controller.abort();
    rejectCancelled(new Error(`Published page loading timed out: ${path}`));
  };
  const cancelled = new Promise((_, reject) => { rejectCancelled = reject; });
  if (pageSignal) {
    if (pageSignal.aborted) onCancel();
    else pageSignal.addEventListener('abort', onCancel, { once: true });
  }
  const request = async () => {
    const response = await fetchImpl(assetPath(path), { cache: 'no-cache', signal: controller.signal });
    if (optional && response.status === 404) return null;
    required(response.ok, `Published asset unavailable: ${path}`);
    const bytes = await response.arrayBuffer();
    if (expectedHash !== undefined) {
      required(HASH.test(expectedHash), 'Missing published asset hash');
      const digest = await globalThis.crypto.subtle.digest('SHA-256', bytes);
      const actual = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
      required(actual === expectedHash, `Published asset hash mismatch: ${path}`);
    }
    return JSON.parse(new TextDecoder().decode(bytes));
  };
  try {
    return await Promise.race([request(), cancelled, new Promise((_, reject) => {
      timer = setTimeout(() => {
        controller.abort();
        reject(new Error(`Published asset request timed out: ${path}`));
      }, timeoutMs);
    })]);
  } finally {
    clearTimeout(timer);
    pageSignal?.removeEventListener('abort', onCancel);
  }
}

function validatedCues(cues, duration) {
  required(Array.isArray(cues) && cues.length > 0, 'Missing published transcript');
  let previous = 0;
  const ids = new Set();
  return cues.map(cue => {
    required(Number.isFinite(cue.start) && Number.isFinite(cue.end)
      && cue.start >= previous && cue.start < cue.end && cue.end <= duration + .001
      && text(cue.text) && text(cue.textGroupId) && !ids.has(cue.textGroupId), 'Invalid published transcript cue');
    previous = cue.end;
    ids.add(cue.textGroupId);
    return { start: cue.start, end: cue.end, text: cue.text, textGroupId: cue.textGroupId, ...(Array.isArray(cue.sourceUnitIds) ? { sourceUnitIds: [...cue.sourceUnitIds] } : {}) };
  });
}

// Shared contract fixtures exercise this same admission used by the loader.
// This validates bound evidence, never creates human/device/venue acceptance.
export function validatePublishedRelease(release, page, locale) {
  return admitPublishedRelease(release, page, locale, [RELEASE_V2, RELEASE_V3].includes(release?.schemaVersion)
    && release.contentStatus === 'human_reviewed' && release.audioStatus === 'human_reviewed');
}

// v4 is the only release that may carry machine_checked products. Each status is
// bound to its review basis, and the release's own-locale disclosure is mandatory.
export function validatePublishedV4Release(release, page, locale) {
  const basis = release?.reviewBasis, disclosure = release?.disclosure;
  required(release?.schemaVersion === RELEASE_V4
    && PRODUCT_STATUSES.includes(release.contentStatus) && PRODUCT_STATUSES.includes(release.audioStatus)
    && [release.contentStatus, release.audioStatus].includes('machine_checked')
    && basis && ['fullText', 'spokenText', 'audio'].every(key => REVIEW_BASIS_KINDS.includes(basis[key]?.kind) && HASH.test(basis[key].receiptSha256))
    && (release.contentStatus === 'machine_checked') === (basis.fullText.kind === 'machine_quality_waiver')
    && (release.audioStatus === 'human_reviewed') === (basis.spokenText.kind === 'human_review' && basis.audio.kind === 'human_review')
    && disclosure?.locale === locale && text(disclosure.text) && text(disclosure.english)
    && Array.isArray(release.assets) && release.assets.length === 7,
  'Invalid machine-checked release status, review basis or disclosure');
  return admitPublishedRelease(release, page, locale, true);
}

function admitPublishedRelease(release, page, locale, statusAdmitted) {
  required(statusAdmitted
    && release.pageId === page.id && release.targetLocale === locale && release.contentLocale === locale
    && release.audioLocale === locale && release.sourceLocale === 'en'
    && typeof release.packageId === 'string' && release.packageId.length > 0 && release.interfaceLocale === locale
    && HASH.test(release.targetLanguageCandidateJsonSha256)
    && HASH.test(release.spokenTargetLanguageCandidateJsonSha256)
    && HASH.test(release.targetLanguageAudioPackageJsonSha256)
    && Array.isArray(release.issues) && release.issues.length === 0
    && release.status === 'published_http_verified' && release.httpVerification?.status === 'pass', 'Invalid published release identity or status');
  for (const name of ['httpVerification', 'deviceAcceptance', 'venueAcceptance']) {
    const gate = release[name];
    required(gate && ['not_run', 'pass', 'fail'].includes(gate.status)
      && (gate.status === 'not_run' ? gate.evidenceSha256 === null : HASH.test(gate.evidenceSha256)),
    'Invalid published acceptance evidence');
  }
  const assets = {};
  for (const role of ['page', 'content', 'captions', 'audio']) {
    const matches = release.assets?.filter(asset => asset.role === role) || [];
    required(matches.length === 1 && HASH.test(matches[0].sha256), `Invalid ${role} asset`);
    assets[role] = { ...matches[0], path: assetPath(matches[0].path) };
    const extension = role === 'audio' ? 'mp3' : 'json';
    const directory = role === 'audio' ? 'media' : role;
    const expected = role === 'page' ? `/pages/${page.id}/${locale}/index.html`
      : `/${directory}/${page.id}/${locale}.${extension}`;
    required(assets[role].path === expected, 'Published asset identity mismatch');
  }
  validateStudyReleaseAssets(release, page, locale, assets);
  return assets;
}

function validateStudyReleaseAssets(release, page, locale, assets) {
  if (!STUDY_RELEASES.includes(release.schemaVersion)) return;
  const identity = release.sourceIdentity, products = release.fourProducts;
  required(release.englishSourcePackageJsonSha256 === page.sourceIdentitySha256
    && identity && text(identity.sourceId) && HASH.test(identity.sourceUrlHash) && HASH.test(identity.mediaSha256)
    && Number.isFinite(identity.durationSeconds) && identity.durationSeconds > 0
    && Number.isFinite(identity.window?.startSeconds) && identity.window.startSeconds >= 0
    && Number.isFinite(identity.window?.endSeconds) && identity.window.endSeconds > identity.window.startSeconds
    && identity.window.endSeconds <= identity.durationSeconds && HASH.test(identity.window.approvalReceiptSha256)
    && products && ['sourcePackageSha256','textCandidateSha256','audioPackageSha256','outlineArtifactSha256',
      'meditationArtifactSha256','outlineReviewSha256','meditationReviewSha256','metadataApprovalSha256','contentSha256','candidateSha256']
      .every(key => HASH.test(products[key]))
    && products.sourcePackageSha256 === page.sourceIdentitySha256
    && products.textCandidateSha256 === release.targetLanguageCandidateJsonSha256
    && products.audioPackageSha256 === release.targetLanguageAudioPackageJsonSha256
    && products.contentSha256 === assets.content.sha256, 'Invalid four-product source identity');
  for (const [role, filename] of [['outline','outline'],['meditation','meditation'],['product_manifest','products']]) {
    const matches = release.assets.filter(asset => asset.role === role);
    required(matches.length === 1 && HASH.test(matches[0].sha256)
      && matches[0].path === `/study/${page.id}/${locale}/${filename}.json`, 'Invalid published study asset');
    assets[role] = { ...matches[0], path: assetPath(matches[0].path) };
  }
}

function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])]));
  return value;
}
async function jsonHash(value) {
  const digest = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify(canonical(value))));
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2,'0')).join('');
}

async function loadStudy(fetchImpl, release, assets, content, timeoutMs, pageSignal) {
  if (!STUDY_RELEASES.includes(release.schemaVersion)) return null;
  const [outline, meditation, manifest] = await Promise.all(['outline','meditation','product_manifest'].map(role =>
    readJson(fetchImpl, assets[role].path, assets[role].sha256, timeoutMs, false, pageSignal)));
  const products = release.fourProducts;
  required(JSON.stringify(canonical(manifest)) === JSON.stringify(canonical({schemaVersion:'sermon-public-app-products-v1',
    pageId:release.pageId, locale:release.targetLocale, sourceIdentity:release.sourceIdentity, fourProducts:products})), 'Public product manifest mismatch');
  const sourceUnits = new Set(content.cues.flatMap(cue => cue.sourceUnitIds || []));
  for (const [kind, artifact] of [['outline',outline],['meditation',meditation]]) {
    required(artifact.schemaVersion === 'sermon-study-artifact-v1' && artifact.kind === kind
      && artifact.pageId === release.pageId && artifact.locale === release.targetLocale
      && artifact.sourcePackageSha256 === products.sourcePackageSha256 && artifact.textCandidateSha256 === products.textCandidateSha256
      && text(artifact.producerIdentity) && Array.isArray(artifact.sections) && artifact.sections.length > 0
      && artifact.sections.every(section => text(section.title) && text(section.body)
        && Array.isArray(section.sourceUnitIds) && section.sourceUnitIds.length > 0
        && new Set(section.sourceUnitIds).size === section.sourceUnitIds.length
        && section.sourceUnitIds.every(id => sourceUnits.has(id)))
      && await jsonHash(artifact) === products[kind+'ArtifactSha256'], 'Study source/text/sections mismatch');
  }
  const joined = await jsonHash({source:products.sourcePackageSha256,products:{text:products.textCandidateSha256,audio:products.audioPackageSha256,
    outline:{status:'human_reviewed',artifactSha256:products.outlineArtifactSha256,reviewSha256:products.outlineReviewSha256},
    meditation:{status:'human_reviewed',artifactSha256:products.meditationArtifactSha256,reviewSha256:products.meditationReviewSha256}}});
  required(await jsonHash({products:joined,metadataApproval:products.metadataApprovalSha256,contentSha256:products.contentSha256}) === products.candidateSha256,
    'Four-product candidate hash mismatch');
  required(content.sourceMediaSha256 === release.sourceIdentity.mediaSha256, 'Study source media mismatch');
  return {outline, meditation, manifest};
}

// Content v3 is read only through a v4 release. Machine-checked text carries its
// own-locale disclosure; human-reviewed text never carries one.
export function validatePublishedContentV3(content, page, locale) {
  const disclosure = content?.disclosure;
  required(content?.schemaVersion === CONTENT_V3 && content.pageId === page.id && content.targetLocale === locale
    && content.sourceLocale === 'en' && PRODUCT_STATUSES.includes(content.status) && content.reviewMode === 'formal'
    && [content.durationSeconds, content.audioDurationSeconds].every(value => Number.isFinite(value) && value > 0 && value <= 86400)
    && Array.isArray(content.cues) && content.cues.length > 0
    && (content.status === 'machine_checked'
      ? disclosure?.locale === locale && text(disclosure.text) && text(disclosure.english)
      : !Object.hasOwn(content, 'disclosure')),
  'Invalid machine-checked content status or disclosure');
  return content;
}

// Candidate admission is explicit and keeps every review/acceptance state intact.
// A machine-reviewed manuscript is never accepted by the published-release path.
export function validateDevCandidateRelease(release, page, locale) {
  required(['sermon-target-language-release-package-v2', 'sermon-target-language-release-package-v3'].includes(release.schemaVersion)
    && text(release.packageId) && release.pageId === page.id && release.sourceLocale === 'en'
    && release.targetLocale === locale && release.contentLocale === locale && release.audioLocale === locale
    && (release.interfaceLocale === locale || (release.contentStatus === 'machine_reviewed' && release.interfaceLocale === 'zh-Hans'))
    && release.status === 'candidate' && ['human_reviewed', 'machine_reviewed'].includes(release.contentStatus)
    && release.audioStatus === 'human_reviewed'
    && HASH.test(release.targetLanguageCandidateJsonSha256) && HASH.test(release.spokenTargetLanguageCandidateJsonSha256)
    && HASH.test(release.targetLanguageAudioPackageJsonSha256)
    && (release.contentStatus !== 'machine_reviewed' || HASH.test(release.audioHumanReviewReceiptJsonSha256))
    && Array.isArray(release.issues) && release.issues.length === 0, 'Invalid Dev candidate identity or status');
  for (const name of ['httpVerification', 'deviceAcceptance', 'venueAcceptance']) {
    required(release[name]?.status === 'not_run' && release[name].evidenceSha256 === null,
      'Dev candidate cannot claim publication, device, or venue acceptance');
  }
  const assets = {};
  for (const role of ['page', 'content', 'captions', 'audio']) {
    const matches = release.assets?.filter(asset => asset.role === role) || [];
    required(matches.length === 1 && HASH.test(matches[0].sha256), `Invalid ${role} candidate asset`);
    assets[role] = { ...matches[0], path: assetPath(matches[0].path) };
    const accepted = role === 'audio' ? ['mp3', 'wav', 'm4a'].map(extension => `/media/${page.id}/${locale}.${extension}`)
      : [role === 'page' ? `/pages/${page.id}/${locale}/index.html` : `/${role}/${page.id}/${locale}.json`];
    required(accepted.includes(assets[role].path), 'Dev candidate asset identity mismatch');
  }
  validateStudyReleaseAssets(release, page, locale, assets);
  return assets;
}

// Catalog admission is distinct from this audio player's capabilities. A valid
// text-only target stays valid, but must never trigger an audio-release request.
// Only a v4 catalog may list machine_checked targets; each points at a v4 release.
export function validatePublishedTarget(target, page, locale, allowDevCandidates = false, catalogVersion = CATALOG_V3) {
  required([CATALOG_V3, CATALOG_V4].includes(catalogVersion), 'Unknown published catalog version');
  const capabilities = target?.capabilities;
  const machine = catalogVersion === CATALOG_V4 && [target?.contentStatus, target?.audioStatus].includes('machine_checked');
  const audible = PRODUCT_STATUSES.includes(target?.audioStatus);
  required(target && target.releasePackageUrl === `/releases-v${machine ? 4 : 2}/${page.id}/${locale}.json`
    && HASH.test(target.releasePackageJsonSha256)
    && (machine
      ? PRODUCT_STATUSES.includes(target.contentStatus) && PRODUCT_STATUSES.includes(target.audioStatus)
        && Array.isArray(capabilities) && ['text', 'captions', 'audio'].every(value => capabilities.includes(value))
      : (target.contentStatus === 'human_reviewed' || (allowDevCandidates && target.contentStatus === 'machine_reviewed'))
        && ['unavailable', 'human_reviewed'].includes(target.audioStatus))
    && Array.isArray(capabilities) && capabilities.includes('text')
    && capabilities.every(value => ['text', 'captions', 'audio', 'download', 'alignment'].includes(value))
    && new Set(capabilities).size === capabilities.length
    && audible === capabilities.includes('audio')
    && (target.audioFingerprint != null) === capabilities.includes('alignment')
    && ['diagnosticOnly', 'simulationOnly'].every(key => target[key] === undefined || typeof target[key] === 'boolean')
    && (allowDevCandidates || (target.diagnosticOnly !== true && target.simulationOnly !== true)),
  'Invalid published catalog target');
  const binding = target.audioFingerprint;
  if (binding != null) {
    const duration = binding.sourceEndSeconds - binding.sourceStartSeconds;
    required(binding.schemaVersion === 'sermon-audio-fingerprint-binding-v1'
      && binding.algorithmVersion === 'spectral-landmarks-v1'
      && binding.pageId === page.id && audible
      && HASH.test(binding.sourceSha256) && HASH.test(binding.trackSha256) && HASH.test(binding.indexSha256)
      && Number.isFinite(binding.sourceStartSeconds) && binding.sourceStartSeconds >= 0
      && Number.isFinite(binding.sourceEndSeconds) && duration > 0
      && binding.captureSeconds === 10
      && binding.indexUrl === `/fingerprints/${binding.indexSha256.slice(0, 16)}-landmarks.json`,
    'Invalid published catalog alignment binding');
  }
  return target;
}

// Header and page metadata are admitted before requesting any release asset.
// Locale asset failures remain isolated by loadVariant, as before.
export function validatePublishedCatalogHeader(catalog, catalogVersion = CATALOG_V3) {
  required([CATALOG_V3, CATALOG_V4].includes(catalogVersion) && catalog && catalog.schemaVersion === catalogVersion
    && typeof catalog.generatedAt === 'string' && typeof catalog.defaultPageId === 'string'
    && Array.isArray(catalog.pages) && catalog.pages.length > 0 && catalog.pages.length <= 104
    && new Set(catalog.pages.map(page => page?.id)).size === catalog.pages.length
    && catalog.pages.some(page => page?.id === catalog.defaultPageId), 'Invalid published catalog');
  return catalog;
}

export function validatePublishedPage(page) {
  const date = typeof page?.date === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(page.date)
    ? new Date(`${page.date}T00:00:00.000Z`) : null;
  required(page && typeof page.id === 'string' && ID.test(page.id)
    && date && Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === page.date
    && text(page.title) && Array.from(page.title).length <= 180
    && page.sourceLocale === 'en' && typeof page.sourceIdentitySha256 === 'string' && HASH.test(page.sourceIdentitySha256)
    && (page.sourceMediaSha256 == null || (typeof page.sourceMediaSha256 === 'string' && HASH.test(page.sourceMediaSha256)))
    && typeof page.defaultTargetLocale === 'string' && LOCALE.test(page.defaultTargetLocale)
    && page.targets && typeof page.targets === 'object' && !Array.isArray(page.targets)
    && Object.keys(page.targets).length > 0 && Object.keys(page.targets).length <= 16
    && Object.keys(page.targets).every(locale => LOCALE.test(locale))
    && Object.hasOwn(page.targets, page.defaultTargetLocale)
    && ['diagnosticOnly', 'simulationOnly'].every(key => page[key] === undefined || typeof page[key] === 'boolean')
    && (page.mediaType === undefined || ['video', 'podcast'].includes(page.mediaType)), 'Invalid published page');
  return page;
}

// A waiver is never a human approval: wording follows each product's status,
// and every machine-checked locale carries its release disclosure. Human-only
// views set the machine fields explicitly so a merged week never inherits them.
function reviewPresentation(labels, release) {
  if (release.schemaVersion !== RELEASE_V4) return {
    releaseLabel: '正式播放版', humanContentReview: 'approved', audioStatus: 'full_reviewed',
    machineChecked: false, disclosure: null, fullTextHint: null, spokenHint: null,
    audioNotice: labels.notice, contentReview: labels.review,
    productionStages: labels.stages.map(([label, detail]) => ({ label, detail, status: 'pass' })),
  };
  const machine = labels.machine, [textStage, audioStage, publishStage] = labels.stages;
  const textMachine = release.contentStatus === 'machine_checked', audioMachine = release.audioStatus === 'machine_checked';
  return {
    releaseLabel: machine.label, humanContentReview: textMachine ? 'machine_checked' : 'approved',
    audioStatus: audioMachine ? 'full_machine_checked' : 'full_reviewed',
    machineChecked: true, disclosure: release.disclosure.text,
    fullTextHint: textMachine ? machine.fullTextHint : null, spokenHint: audioMachine ? machine.spokenHint : null,
    audioNotice: audioMachine ? machine.notice : labels.notice,
    contentReview: textMachine && audioMachine ? machine.both
      : `${machine.text[release.contentStatus]}${machine.join}${machine.audio[release.audioStatus]}`,
    productionStages: [textMachine ? machine.textStage : textStage, audioMachine ? machine.audioStage : audioStage, publishStage]
      .map(([label, detail]) => ({ label, detail, status: 'pass' })),
  };
}

async function loadVariant(fetchImpl, page, locale, timeoutMs, pageSignal, allowDevCandidates, catalogVersion) {
  const target = validatePublishedTarget(page.targets[locale], page, locale, allowDevCandidates, catalogVersion);
  required(PRODUCT_STATUSES.includes(target.audioStatus)
    && ['text', 'captions', 'audio'].every(capability => target.capabilities?.includes(capability)), 'Target is not ready for playback');
  const machineTarget = target.releasePackageUrl.startsWith('/releases-v4/');
  const release = await readJson(fetchImpl, target.releasePackageUrl, target.releasePackageJsonSha256, timeoutMs, false, pageSignal);
  const candidate = release.status === 'candidate';
  required(!candidate || allowDevCandidates, 'Dev candidate requires explicit development context');
  const assets = machineTarget ? validatePublishedV4Release(release, page, locale)
    : candidate ? validateDevCandidateRelease(release, page, locale) : validatePublishedRelease(release, page, locale);
  required(release.contentStatus === target.contentStatus && release.audioStatus === target.audioStatus,
    'Release status does not match catalog target');
  const [content, captions] = await Promise.all([
    readJson(fetchImpl, assets.content.path, assets.content.sha256, timeoutMs, false, pageSignal),
    readJson(fetchImpl, assets.captions.path, assets.captions.sha256, timeoutMs, false, pageSignal),
  ]);
  const legacyCandidate = candidate && release.schemaVersion === RELEASE_V2;
  // Content v3 is admitted only through a v4 release, with the same text status.
  const contentVersions = legacyCandidate ? ['sermon-formal-dev-content-v1', 'sermon-dev-podcast-candidate-content-v2']
    : machineTarget ? (release.contentStatus === 'machine_checked' ? [CONTENT_V3] : [CONTENT_V1, CONTENT_V2, CONTENT_V3]) : [CONTENT_V1, CONTENT_V2];
  required(contentVersions.includes(content.schemaVersion)
    && content.pageId === page.id && (legacyCandidate ? content.locale === locale : content.targetLocale === locale) && content.sourceLocale === 'en'
    && (legacyCandidate ? content.contentStatus === release.contentStatus && content.audioStatus === release.audioStatus
      && content.targetLanguageAudioPackageJsonSha256 === release.targetLanguageAudioPackageJsonSha256 && content.date === page.date
      : content.status === (machineTarget ? release.contentStatus : 'human_reviewed'))
    && content.englishSourcePackageJsonSha256 === page.sourceIdentitySha256
    && content.targetLanguageCandidateJsonSha256 === release.targetLanguageCandidateJsonSha256
    && HASH.test(release.targetLanguageCandidateJsonSha256), 'Published content identity mismatch');
  if (content.schemaVersion === CONTENT_V3) validatePublishedContentV3(content, page, locale);
  // Machine-checked text repeats the release disclosure it was published under.
  required(content.status !== 'machine_checked' || ['locale', 'text', 'english'].every(key => content.disclosure[key] === release.disclosure[key]),
    'Content disclosure differs from its release');
  required(['title', 'speaker', 'series', 'scripture', 'summary'].every(key => text(content[key]))
    && Array.isArray(content.outline) && content.outline.every(item => legacyCandidate ? text(item?.title) && text(item?.body) : text(item))
    && Number.isFinite(content.durationSeconds) && content.durationSeconds > 0, 'Invalid published content metadata');
  const sourceWindow = content.sourceWindow;
  required(sourceWindow === undefined || (sourceWindow?.schemaVersion === 'sermon-original-recording-window-v1' && Number.isFinite(sourceWindow?.startSeconds)
    && sourceWindow.startSeconds >= 0 && Number.isFinite(sourceWindow.endSeconds)
    && sourceWindow.endSeconds > sourceWindow.startSeconds
    && sourceWindow.mediaSha256 === content.sourceMediaSha256 && HASH.test(sourceWindow.mediaSha256)
    && Math.abs(sourceWindow.endSeconds - sourceWindow.startSeconds - content.durationSeconds) < .001),
  'Invalid original-source fingerprint window');
  const separateAudioClock = [CONTENT_V2, CONTENT_V3].includes(content.schemaVersion) || Object.hasOwn(content, 'audioDurationSeconds');
  if ([CONTENT_V2, CONTENT_V3].includes(content.schemaVersion)) {
    required(['formal', 'simulation'].includes(content.reviewMode), 'Invalid published review mode');
    required(content.reviewMode !== 'simulation' || (page.simulationOnly === true && target.simulationOnly === true && page.diagnosticOnly === true && target.diagnosticOnly === true), 'Simulation content requires isolated catalog flags');
    required(content.reviewMode !== 'formal' || (page.simulationOnly !== true && target.simulationOnly !== true), 'Simulation catalog cannot declare formal content');
  }
  const audioDuration = separateAudioClock ? content.audioDurationSeconds : content.durationSeconds;
  required(Number.isFinite(audioDuration) && audioDuration > 0 && audioDuration <= 86400, 'Invalid published audio duration');
  const cues = validatedCues(captions.cues, audioDuration);
  const fullTranscript = validatedCues(content.cues, content.durationSeconds);
  // Full reading text and shorter spoken captions remain separate, explicitly linked by group ID.
  const fullIds = new Set(fullTranscript.map(cue => cue.textGroupId));
  required(cues.length === fullTranscript.length && cues.every(cue => fullIds.has(cue.textGroupId)), 'Spoken captions do not match full-text groups');
  const labels = LABELS[locale];
  if (legacyCandidate) {
    required(page.mediaType === 'podcast' && typeof page.sourceUrl === 'string'
      && /^https:\/\//.test(page.sourceUrl) && !new URL(page.sourceUrl).username && !new URL(page.sourceUrl).password,
      'Invalid candidate podcast source');
    required(captions.schemaVersion === 'sermon-target-language-captions-v1'
      && captions.pageId === page.id && captions.locale === locale
      && captions.audioPackageJsonSha256 === release.targetLanguageAudioPackageJsonSha256
      && captions.timingBasis === 'concatenated target audio; natural unit durations; no source-video synchronization',
      'Invalid candidate caption identity');
    const reviewed = release.contentStatus === 'human_reviewed';
    return {
      id: page.id, date: page.date, number: '', title: content.title, targetLocale: locale, defaultTargetLocale: locale,
      series: content.series, speaker: content.speaker, scripture: content.scripture,
      sourceUrl: page.sourceUrl, sourceLabel: '播客原片', sourceRoute: 'podcast',
      sourceSha256: page.sourceMediaSha256, diagnosticOnly: true, devCandidate: true,
      contentStatus: release.contentStatus, releaseStatus: release.status,
      releaseLabel: 'DEV 候选', humanContentReview: reviewed ? 'approved' : 'pending', audioStatus: 'full_reviewed',
      audioNotice: 'Dev 候选音轨；字幕采用目标音轨时间，不代表视频同步或设备验收。',
      contentReview: reviewed ? '文稿人工审核状态已记录；当前仍是 Dev 候选。' : '译文仅机器审核；人工全文审核未批准。当前仍是 Dev 候选。',
      productionStages: [
        { label: '文稿审核', detail: release.contentStatus, status: reviewed ? 'pass' : 'review' },
        { label: '音轨审核', detail: release.audioStatus, status: 'pass' },
        { label: '发布与验收', detail: 'candidate · HTTP / device / venue: not_run', status: 'review' },
      ],
      summary: content.summary, centralMessage: content.summary,
      outline: content.outline.map(item => ({ title: item.title, points: [item.body] })), questions: [], scriptureRefs: [content.scripture],
      tracks: [{ id: `${page.id}-${locale}-${assets.audio.sha256.slice(0, 12)}`,
        audioUrl: assets.audio.path, sha256: assets.audio.sha256, durationSeconds: audioDuration,
        cues, scope: 'full_candidate', label: labels.audio, voiceLabel: `${content.speaker} · AI`,
        targetLocale: locale, subtitleTiming: 'target_audio_clock' }], fullTranscript,
      contentSha256: assets.content.sha256, captionsSha256: assets.captions.sha256,
      releasePackageJsonSha256: target.releasePackageJsonSha256,
    };
  }
  const study = await loadStudy(fetchImpl, release, assets, content, timeoutMs, pageSignal);
  const track = {
    id: `${page.id}-${locale}-${assets.audio.sha256.slice(0, 12)}`,
    audioUrl: assets.audio.path, sha256: assets.audio.sha256,
    durationSeconds: audioDuration, cues, scope: release.audioStatus === 'machine_checked' ? 'full_machine_checked' : 'full_reviewed',
    label: labels.audio, voiceLabel: labels.voice, targetLocale: locale,
    subtitleTiming: separateAudioClock ? 'target_audio_clock' : 'source_video_aligned',
  };
  return {
    id: page.id, date: page.date, number: '', targetLocale: locale, defaultTargetLocale: locale, title: content.title,
    series: content.series, speaker: content.speaker, scripture: content.scripture,
    sourceUrl: assetPath(content.sourceVideoUrl), sourceLabel: labels.source,
    sourceRoute: 'full_video', sourceSha256: content.sourceMediaSha256, ...(sourceWindow ? { sourceFingerprintWindow: { ...sourceWindow } } : {}), sourceStartSeconds: 0, sourceEndSeconds: content.durationSeconds, sourceDurationSeconds: content.durationSeconds,
    ...reviewPresentation(labels, release),
    ...(page.diagnosticOnly === true || target.diagnosticOnly === true ? { diagnosticOnly: true } : {}),
    ...(page.simulationOnly === true || target.simulationOnly === true ? { simulationOnly: true } : {}),
    centralMessage: content.summary, summary: content.summary,
    outline: study ? study.outline.sections.map(section => ({ title: section.title, points: [section.body], sourceUnitIds: section.sourceUnitIds })) : content.outline.map(title => ({ title, points: [] })),
    meditation: study?.meditation.sections || [], studyArtifacts: study ? {outline:release.fourProducts.outlineArtifactSha256,meditation:release.fourProducts.meditationArtifactSha256} : null,
    fourProducts: study ? release.fourProducts : null, studyStatus: study ? 'human_reviewed' : 'unavailable',
    ...(candidate ? {devCandidate:true,releaseStatus:'candidate',contentReview:'人工审核候选；尚未发布验收。',productionStages:[{label:'发布与验收',detail:'candidate · not_run',status:'review'}]} : {}),
    ...(page.simulationOnly === true || target.simulationOnly === true ? {
      releaseLabel: '模拟审核测试', humanContentReview: 'simulated', studyStatus: study ? 'simulated' : 'unavailable',
      audioNotice: '测试音轨；模拟审核不构成真人听审或同步批准。',
      contentReview: '模拟审核测试；不构成正式内容批准。',
      productionStages: [{label:'测试交付', detail:'simulationOnly · 非正式内容批准', status:'review'}],
    } : {}),
    questions: [], scriptureRefs: [content.scripture], tracks: [track], fullTranscript,
    contentSha256: assets.content.sha256, captionsSha256: assets.captions.sha256,
    releasePackageJsonSha256: target.releasePackageJsonSha256,
  };
}

async function loadPage(fetchImpl, page, timeoutMs, pageSignal, allowDevCandidates, catalogVersion) {
  const errors = [];
  const variants = await Promise.all(LOCALES.filter(locale => page.targets[locale]).map(async locale => {
    try { return [locale, await loadVariant(fetchImpl, page, locale, timeoutMs, pageSignal, allowDevCandidates, catalogVersion)]; }
    catch (error) { errors.push(`${page.id}/${locale}: ${error.message}`); return null; }
  }));
  const contentVariants = Object.fromEntries(variants.filter(Boolean));
  // Optional delivery sidecar: never change a reviewed release or hide its audio
  // because listening alignment is unavailable. Each locale binds its own track.
  try {
    const alignment = await readJson(fetchImpl, `/alignment/${page.id}.json`, undefined, timeoutMs, true, pageSignal);
    if (alignment !== null) {
      required(alignment.schemaVersion === 'sermon-published-alignment-v1'
        && alignment.pageId === page.id && alignment.sourceIdentitySha256 === page.sourceIdentitySha256,
      'Invalid alignment catalog identity');
      for (const [locale, variant] of Object.entries(contentVariants)) {
        try {
          const target = alignment.targets?.[locale], m = target?.audioFingerprint;
          required(target?.releasePackageJsonSha256 === variant.releasePackageJsonSha256
            && m?.schemaVersion === 'sermon-audio-fingerprint-binding-v1'
            && m.algorithmVersion === 'spectral-landmarks-v1' && m.pageId === page.id
            && HASH.test(m.sourceSha256) && m.sourceSha256 === variant.sourceSha256
            && m.trackSha256 === variant.tracks[0].sha256 && HASH.test(m.indexSha256)
            && m.sourceStartSeconds === (variant.sourceFingerprintWindow?.startSeconds ?? 0)
              && m.sourceEndSeconds === (variant.sourceFingerprintWindow?.endSeconds ?? variant.sourceDurationSeconds)
            && m.captureSeconds === 10
            && m.indexUrl === `/fingerprints/${m.indexSha256.slice(0, 16)}-landmarks.json`,
          'Invalid alignment track/source binding');
          variant.audioFingerprint = { ...m };
          variant.automaticAudioAlignment = { schemaVersion: 'sermon-automatic-audio-alignment-v1', status: 'ready', required: true };
        } catch (error) { errors.push(`${page.id}/${locale}: ${error.message}`); }
      }
    }
  } catch (error) { errors.push(`${page.id}: ${error.message}`); }
  try {
    const reference = await readJson(fetchImpl, `/english-reference/${page.id}.json`, undefined, timeoutMs, true, pageSignal);
    if (reference !== null) {
      required(reference.schemaVersion === 'sermon-published-english-reference-v1'
        && reference.pageId === page.id && reference.sourceIdentitySha256 === page.sourceIdentitySha256
        && reference.reviewState === 'human_approved', 'Invalid English reference identity');
      for (const [locale, variant] of Object.entries(contentVariants)) {
        try {
          const target = reference.targets?.[locale];
          required(reference.sourceMediaSha256 === variant.sourceSha256
            && target?.releasePackageJsonSha256 === variant.releasePackageJsonSha256
            && target.contentSha256 === variant.contentSha256 && target.captionsSha256 === variant.captionsSha256
            && Array.isArray(target.blocks) && target.blocks.length === variant.fullTranscript.length,
          'English reference is not bound to this release');
          const blocks = new Map();
          for (const [i, block] of target.blocks.entries()) {
            const cue = variant.fullTranscript[i];
            required(block.textGroupId === cue.textGroupId && !blocks.has(block.textGroupId)
              && text(block.english) && Array.isArray(block.sourceUnitIds) && block.sourceUnitIds.length > 0
              && JSON.stringify(block.sourceUnitIds) === JSON.stringify(cue.sourceUnitIds),
            'English reference group mismatch');
            blocks.set(block.textGroupId, block);
          }
          // Associate by approved group IDs, never by translated wording or timing.
          variant.transcript = { schemaVersion: 'sermon-bilingual-transcript-v1', blocks: target.blocks.map(block => ({
            blockId: block.textGroupId, english: block.english, sourceTextOrigin: 'approved_english_source', reviewState: 'human_approved',
          })) };
          variant.tracks[0].cues = variant.tracks[0].cues.map(cue => ({...cue, blockId: cue.textGroupId}));
          variant.fullTranscript = variant.fullTranscript.map(cue => ({...cue, english: blocks.get(cue.textGroupId).english}));
        } catch (error) { errors.push(`${page.id}/${locale}: ${error.message}`); }
      }
    }
  } catch (error) { errors.push(`${page.id}: ${error.message}`); }
  const defaultLocale = contentVariants[page.defaultTargetLocale] ? page.defaultTargetLocale : Object.keys(contentVariants)[0];
  return { week: defaultLocale ? { ...contentVariants[defaultLocale], defaultTargetLocale: defaultLocale, contentVariants } : null, errors };
}

/**
 * Returns { weeks, defaultWeekId, errors }. Each week has a contentVariants map
 * keyed by the exact published target locale. Variants contain their own track,
 * spoken cues and fullTranscript. An unavailable optional catalog leaves legacy
 * weeks usable; a rejected locale is reported in errors and is never selectable.
 */
export async function loadPublishedWeeks(fetchImpl = globalThis.fetch, { requestTimeoutMs = 10000, pageLoadTimeoutMs = 30000, allowDevCandidates = false } = {}) {
  const timeoutMs = Number.isFinite(requestTimeoutMs) && requestTimeoutMs > 0 ? Math.min(requestTimeoutMs, 30000) : 10000;
  const loadTimeoutMs = Number.isFinite(pageLoadTimeoutMs) && pageLoadTimeoutMs > 0 ? Math.min(pageLoadTimeoutMs, 30000) : 30000;
  const empty = { weeks: [], defaultWeekId: null, errors: [] };
  // v4 adds machine-checked locales; v3 stays the human-only projection. A missing
  // v4 is the normal pre-v4 state. An unreadable or invalid v4 never hides v3 weeks.
  const errors = [];
  let catalog = null, catalogVersion = CATALOG_V4;
  try {
    catalog = await readJson(fetchImpl, '/multilingual-v4.json', undefined, timeoutMs, true);
    if (catalog !== null) validatePublishedCatalogHeader(catalog, CATALOG_V4);
  } catch (error) { catalog = null; errors.push(`Catalog v4 unavailable, using v3: ${error.message}`); }
  if (catalog === null) {
    catalogVersion = CATALOG_V3;
    try {
      catalog = await readJson(fetchImpl, '/multilingual-v3.json', undefined, timeoutMs, true);
      if (catalog === null) return { ...empty, errors };
      validatePublishedCatalogHeader(catalog);
    } catch (error) { return { ...empty, errors: [...errors, error.message] }; }
  }
  const pages = [];
  for (const page of catalog.pages) {
    try {
      validatePublishedPage(page);
      if (!allowDevCandidates && (page.diagnosticOnly === true || page.simulationOnly === true)) continue;
      // Remove only Dev-only machine_reviewed locales; independently reviewed and
      // machine_checked (published with a disclosure) locales remain usable.
      const targets = Object.fromEntries(Object.entries(page.targets).filter(([, target]) => allowDevCandidates || (target.contentStatus !== 'machine_reviewed' && target.diagnosticOnly !== true && target.simulationOnly !== true)));
      if (!Object.keys(targets).length) continue;
      pages.push({ ...page, targets, defaultTargetLocale: targets[page.defaultTargetLocale] ? page.defaultTargetLocale : Object.keys(targets).sort()[0] });
    }
    catch (error) { errors.push(error.message); }
  }
  pages.sort((a, b) => (b.id === catalog.defaultPageId) - (a.id === catalog.defaultPageId) || b.date.localeCompare(a.date));
  const pageController = new AbortController();
  const timer = setTimeout(() => pageController.abort(), loadTimeoutMs);
  const results = new Array(pages.length);
  let next = 0;
  try {
    // Issue current-page requests first, then let the archive make progress even
    // if a current-page asset or optional sidecar stalls.
    const currentPage = pages.length
      ? loadPage(fetchImpl, pages[0], timeoutMs, pageController.signal, allowDevCandidates, catalogVersion).then(result => { results[0] = result; })
      : Promise.resolve();
    // Historical pages are independent; cap simultaneous pages and the total wait.
    const worker = async () => {
      while (!pageController.signal.aborted && next < pages.length - 1) {
        const index = ++next;
        results[index] = await loadPage(fetchImpl, pages[index], timeoutMs, pageController.signal, allowDevCandidates, catalogVersion);
      }
    };
    await Promise.all([currentPage, ...Array.from({ length: Math.min(12, pages.length - 1) }, worker)]);
  } finally { clearTimeout(timer); }
  if (pageController.signal.aborted) errors.push('Published page loading timed out');
  const weeks = results.flatMap(result => result?.week ? [result.week] : []);
  for (const result of results) if (result) errors.push(...result.errors);
  weeks.sort((a, b) => b.date.localeCompare(a.date));
  return { weeks, defaultWeekId: weeks.find(week => week.id === catalog.defaultPageId)?.id || weeks[0]?.id || null, errors };
}

// Render only validated study artifacts. textContent preserves complete text safely.
export function renderMeditation(container, sections, locale = 'zh-Hans') {
  container.replaceChildren();
  container.hidden = !Array.isArray(sections) || sections.length === 0;
  if (container.hidden) return;
  const document = container.ownerDocument;
  const heading = document.createElement('h2');
  heading.textContent = { 'zh-Hans': '默想', ko: '묵상', es: 'Meditación' }[locale] || 'Meditation';
  container.append(heading);
  for (const item of sections) {
    const section = document.createElement('section');
    section.className = 'outline-section';
    const title = document.createElement('h3');
    title.textContent = item.title;
    const body = document.createElement('p');
    body.style.whiteSpace = 'pre-wrap';
    body.textContent = item.body;
    section.append(title, body);
    container.append(section);
  }
}
