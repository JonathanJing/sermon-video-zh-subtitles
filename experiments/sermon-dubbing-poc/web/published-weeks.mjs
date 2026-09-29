// Runtime bridge from published Layer 4 assets to the existing listening App.
// Only the small JSON assets are fetched here. Audio plays directly from Hosting.
const LOCALES = ['zh-Hans', 'ko', 'es'];
const LABELS = {
  'zh-Hans': {
    source: '完整视频', audio: '中文同步配音', voice: 'Eric Geiger · AI 配音',
    notice: 'AI 配音采用已批准的精简口播稿，字幕随配音播放；完整文稿另列供阅读。',
    review: '完整文稿及配音均已人工审核批准',
    stages: [['文稿审核', '完整文稿已审核批准。'], ['配音与字幕', '配音已审核批准，字幕采用对应口播稿。'], ['线上发布', '正式音轨及文稿已发布，线上文件核验通过。']],
  },
  ko: {
    source: '전체 영상', audio: '한국어 동기화 더빙', voice: 'Eric Geiger · AI 더빙',
    notice: 'AI 더빙은 승인된 간결한 구술 원고를 사용합니다. 자막은 더빙을 따르며 전체 읽기 원고는 별도로 제공됩니다.',
    review: '전체 원고와 더빙의 사람 검토 및 승인이 기록되었습니다',
    stages: [['원고 검토', '전체 원고가 검토 및 승인되었습니다.'], ['더빙과 자막', '더빙이 검토 및 승인되었으며 자막은 해당 구술 원고를 사용합니다.'], ['온라인 게시', '정식 음원과 원고가 게시되었고 온라인 파일 검증을 통과했습니다.']],
  },
  es: {
    source: 'Video completo', audio: 'Doblaje sincronizado en español', voice: 'Eric Geiger · doblaje con IA',
    notice: 'El doblaje con IA utiliza el guion oral abreviado aprobado. Los subtítulos siguen el audio; el texto íntegro se ofrece por separado.',
    review: 'El texto íntegro y el doblaje tienen revisión y aprobación humanas registradas',
    stages: [['Revisión del texto', 'El texto íntegro está revisado y aprobado.'], ['Doblaje y subtítulos', 'El doblaje está revisado y aprobado; los subtítulos utilizan su guion oral.'], ['Publicación', 'El audio oficial y el texto están publicados y sus archivos en línea están verificados.']],
  },
};
const HASH = /^[a-f0-9]{64}$/;
const ID = /^[A-Za-z0-9][A-Za-z0-9_-]*$/;
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

async function loadVariant(fetchImpl, page, locale, timeoutMs, pageSignal) {
  const target = page.targets[locale];
  required(target?.contentStatus === 'human_reviewed' && target.audioStatus === 'human_reviewed'
    && ['text', 'captions', 'audio'].every(capability => target.capabilities?.includes(capability)), 'Target is not ready for playback');
  const release = await readJson(fetchImpl, target.releasePackageUrl, target.releasePackageJsonSha256, timeoutMs, false, pageSignal);
  required(release.schemaVersion === 'sermon-target-language-release-package-v2'
    && release.pageId === page.id && release.targetLocale === locale && release.contentLocale === locale
    && release.audioLocale === locale && release.sourceLocale === 'en'
    && release.status === 'published_http_verified' && release.httpVerification?.status === 'pass'
    && release.contentStatus === 'human_reviewed' && release.audioStatus === 'human_reviewed', 'Invalid published release identity or status');
  const assets = {};
  for (const role of ['content', 'captions', 'audio']) {
    const matches = release.assets?.filter(asset => asset.role === role) || [];
    required(matches.length === 1 && HASH.test(matches[0].sha256), `Invalid ${role} asset`);
    assets[role] = { ...matches[0], path: assetPath(matches[0].path) };
    const extension = role === 'audio' ? 'mp3' : 'json';
    const directory = role === 'audio' ? 'media' : role;
    required(assets[role].path === `/${directory}/${page.id}/${locale}.${extension}`, 'Published asset identity mismatch');
  }
  const [content, captions] = await Promise.all([
    readJson(fetchImpl, assets.content.path, assets.content.sha256, timeoutMs, false, pageSignal),
    readJson(fetchImpl, assets.captions.path, assets.captions.sha256, timeoutMs, false, pageSignal),
  ]);
  required(content.schemaVersion === 'sermon-full-video-text-content-v1'
    && content.pageId === page.id && content.targetLocale === locale && content.sourceLocale === 'en'
    && content.status === 'human_reviewed' && content.englishSourcePackageJsonSha256 === page.sourceIdentitySha256
    && content.targetLanguageCandidateJsonSha256 === release.targetLanguageCandidateJsonSha256
    && HASH.test(release.targetLanguageCandidateJsonSha256), 'Published content identity mismatch');
  required(['title', 'speaker', 'series', 'scripture', 'summary'].every(key => text(content[key]))
    && Array.isArray(content.outline) && content.outline.every(text)
    && Number.isFinite(content.durationSeconds) && content.durationSeconds > 0, 'Invalid published content metadata');
  const cues = validatedCues(captions.cues, content.durationSeconds);
  const fullTranscript = validatedCues(content.cues, content.durationSeconds);
  // Full reading text and shorter spoken captions remain separate, explicitly linked by group ID.
  const fullIds = new Set(fullTranscript.map(cue => cue.textGroupId));
  required(cues.length === fullTranscript.length && cues.every(cue => fullIds.has(cue.textGroupId)), 'Spoken captions do not match full-text groups');
  const labels = LABELS[locale];
  const track = {
    id: `${page.id}-${locale}-${assets.audio.sha256.slice(0, 12)}`,
    audioUrl: assets.audio.path, sha256: assets.audio.sha256,
    durationSeconds: content.durationSeconds, cues, scope: 'full_reviewed',
    label: labels.audio, voiceLabel: labels.voice, targetLocale: locale,
    subtitleTiming: 'source_video_aligned',
  };
  return {
    id: page.id, date: page.date, number: '', targetLocale: locale, defaultTargetLocale: locale, title: content.title,
    series: content.series, speaker: content.speaker, scripture: content.scripture,
    sourceUrl: assetPath(content.sourceVideoUrl), sourceLabel: labels.source,
    sourceRoute: 'full_video', sourceSha256: content.sourceMediaSha256, sourceStartSeconds: 0, sourceEndSeconds: content.durationSeconds, sourceDurationSeconds: content.durationSeconds,
    releaseLabel: '正式播放版', humanContentReview: 'approved', audioStatus: 'full_reviewed',
    audioNotice: labels.notice, contentReview: labels.review,
    productionStages: labels.stages.map(([label, detail]) => ({ label, detail, status: 'pass' })),
    centralMessage: content.summary, summary: content.summary,
    outline: content.outline.map(title => ({ title, points: [] })),
    questions: [], scriptureRefs: [content.scripture], tracks: [track], fullTranscript,
    contentSha256: assets.content.sha256, captionsSha256: assets.captions.sha256,
    releasePackageJsonSha256: target.releasePackageJsonSha256,
  };
}

async function loadPage(fetchImpl, page, timeoutMs, pageSignal) {
  const errors = [];
  const variants = await Promise.all(LOCALES.filter(locale => page.targets[locale]).map(async locale => {
    try { return [locale, await loadVariant(fetchImpl, page, locale, timeoutMs, pageSignal)]; }
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
            && m.sourceStartSeconds === 0 && m.sourceEndSeconds === variant.sourceDurationSeconds
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
export async function loadPublishedWeeks(fetchImpl = globalThis.fetch, { requestTimeoutMs = 10000, pageLoadTimeoutMs = 30000 } = {}) {
  const timeoutMs = Number.isFinite(requestTimeoutMs) && requestTimeoutMs > 0 ? Math.min(requestTimeoutMs, 30000) : 10000;
  const loadTimeoutMs = Number.isFinite(pageLoadTimeoutMs) && pageLoadTimeoutMs > 0 ? Math.min(pageLoadTimeoutMs, 30000) : 30000;
  const empty = { weeks: [], defaultWeekId: null, errors: [] };
  let catalog;
  try {
    catalog = await readJson(fetchImpl, '/multilingual-v3.json', undefined, timeoutMs, true);
    if (catalog === null) return empty;
    required(catalog.schemaVersion === 'sermon-multilingual-catalog-v3' && Array.isArray(catalog.pages), 'Invalid published catalog');
  } catch (error) { return { ...empty, errors: [error.message] }; }
  const errors = [];
  const seen = new Set();
  const pages = [];
  for (const page of catalog.pages) {
    if (!page || typeof page !== 'object' || !ID.test(page.id) || !/^\d{4}-\d{2}-\d{2}$/.test(page.date) || seen.has(page.id)
      || page.sourceLocale !== 'en' || !HASH.test(page.sourceIdentitySha256) || !page.targets) {
      errors.push('Invalid published page');
      continue;
    }
    seen.add(page.id);
    pages.push(page);
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
      ? loadPage(fetchImpl, pages[0], timeoutMs, pageController.signal).then(result => { results[0] = result; })
      : Promise.resolve();
    // Historical pages are independent; cap simultaneous pages and the total wait.
    const worker = async () => {
      while (!pageController.signal.aborted && next < pages.length - 1) {
        const index = ++next;
        results[index] = await loadPage(fetchImpl, pages[index], timeoutMs, pageController.signal);
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
