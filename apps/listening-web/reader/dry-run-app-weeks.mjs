// Dev-only adapter: expose a simulated Layer 4 package in the existing App.
// It never changes the formal v3 catalog or presents simulated assets as reviewed.
const LOCALES = ['zh-Hans', 'ko', 'es'];
const SHA = /^[a-f0-9]{64}$/;
const PAGE_ID = /^dryrun-[a-zA-Z0-9_-]+$/;
const requireValue = (value, message) => { if (!value) throw new Error(message); };

async function readJson(fetchImpl, path, expectedSha) {
  requireValue(/^\/[a-zA-Z0-9_./-]+$/.test(path) && !path.includes('..') && !path.includes('//'), 'Unsafe Dev simulation path');
  const response = await fetchImpl(path, { cache: 'no-store' });
  if (path === '/dry-run/latest.json' && response.status === 404) return null;
  requireValue(response.ok, `Dev simulation asset unavailable: ${path}`);
  const bytes = await response.arrayBuffer();
  if (expectedSha) {
    requireValue(SHA.test(expectedSha), 'Invalid Dev simulation hash');
    const digest = await globalThis.crypto.subtle.digest('SHA-256', bytes);
    const actual = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
    requireValue(actual === expectedSha, `Dev simulation hash mismatch: ${path}`);
  }
  return JSON.parse(new TextDecoder().decode(bytes));
}

function appVariant(pageId, locale, content, captions, english, release, video) {
  requireValue(content.schemaVersion === 'sermon-dev-simulated-content-v1'
    && content.status === 'simulation_only' && content.pageId === pageId
    && content.targetLocale === locale && content.inputLayer2Sha256 === release.inputLayer2Sha256
    && captions.schemaVersion === 'sermon-dev-simulated-captions-v1'
    && captions.status === 'simulation_only' && captions.pageId === pageId
    && captions.targetLocale === locale && captions.inputLayer3Sha256 === release.inputLayer3Sha256
    && Array.isArray(content.cues) && content.cues.length > 0
    && captions.cues.length === content.cues.length, 'Dev simulation content binding differs');
  const englishById = new Map(english.units.map(unit => [unit.sourceUnitId, unit.english]));
  const transcript = { schemaVersion: 'sermon-bilingual-transcript-v1', blocks: [] };
  const fullTranscript = content.cues.map((cue, index) => {
    const spoken = captions.cues[index];
    const sourceUnit = cue.sourceUnitIds?.[0];
    const original = englishById.get(sourceUnit);
    requireValue(spoken.textGroupId === cue.textGroupId && typeof original === 'string', 'Dev simulation cue identity differs');
    transcript.blocks.push({ blockId: cue.textGroupId, english: original,
      sourceTextOrigin: 'parent_approved_slice', reviewState: 'simulation_only' });
    return { ...cue, english: original };
  });
  const audioUrl = `/media/${pageId}/${locale}.mp3`;
  const track = { id: `${pageId}-${locale}-${release.assets.audio.slice(0, 12)}`,
    audioUrl, sha256: release.assets.audio, durationSeconds: content.durationSeconds,
    cues: captions.cues.map(cue => ({ ...cue, blockId: cue.textGroupId })),
    scope: 'machine_poc_not_production', subtitleTiming: 'source_video_aligned_simulation',
    label: `${locale} · DEV 演练音轨`, targetLocale: locale };
  return { id: pageId, date: '2026-09-27', number: 'DEV', targetLocale: locale,
    simulationOnly: true,
    defaultTargetLocale: locale, title: `[DEV 演练] ${content.title} · 30 秒片段`,
    series: content.series, speaker: content.speaker, scripture: '启示录 4–5 章',
    sourceUrl: video.canonicalUrl, sourceLabel: '9/27 DEV 演练片段', sourceRoute: 'full_video',
    sourceSha256: video.sha256, sourceStartSeconds: 0, sourceEndSeconds: content.durationSeconds,
    sourceDurationSeconds: content.durationSeconds, humanContentReview: 'pending', audioStatus: 'candidate',
    audioNotice: 'DEV 模拟：文字与音轨截取自已审整篇；截片未单独获得正式人审批准。',
    contentReview: 'simulation_only', centralMessage: '用于验证模拟链接到 App 内播放的发布链路。',
    summary: '用于验证模拟链接到 App 内播放的发布链路。',
    outline: [{ title: 'DEV 演练片段', points: [] }], questions: [],
    scriptureRefs: ['启示录 4–5 章'], tracks: [track], fullTranscript, transcript };
}

export async function loadDryRunWeeks(fetchImpl = globalThis.fetch) {
  const empty = { weeks: [], defaultWeekId: null, errors: [] };
  try {
    const index = await readJson(fetchImpl, '/dry-run/latest.json');
    if (index === null) return empty;
    requireValue(index.schemaVersion === 'sermon-dev-simulated-app-index-v1'
      && index.status === 'simulation_only' && PAGE_ID.test(index.pageId)
      && index.catalogUrl === `/dry-run/${index.pageId}/catalog.json`, 'Invalid Dev simulation App index');
    const catalog = await readJson(fetchImpl, index.catalogUrl, index.catalogSha256);
    requireValue(catalog.schemaVersion === 'sermon-dev-simulated-catalog-v1'
      && catalog.status === 'simulation_only' && catalog.pageId === index.pageId
      && catalog.videoDelivery?.canonicalUrl === `/pages/${index.pageId}/full-video-browser.mp4`,
    'Invalid Dev simulation catalog');
    const english = await readJson(fetchImpl, `/english-reference/${index.pageId}.json`);
    requireValue(english.schemaVersion === 'sermon-dev-simulated-english-reference-v1'
      && english.status === 'simulation_only' && english.pageId === index.pageId,
    'Invalid Dev simulation English reference');
    const variants = {};
    for (const locale of LOCALES) {
      const ref = catalog.releases?.[locale];
      requireValue(ref?.path === `/releases-v2/${index.pageId}/${locale}.json`, 'Invalid Dev simulation release path');
      const release = await readJson(fetchImpl, ref.path, ref.sha256);
      requireValue(release.schemaVersion === 'sermon-dev-simulated-release-v1'
        && release.status === 'simulation_only' && release.pageId === index.pageId
        && release.targetLocale === locale && release.inputLayer1Sha256 === catalog.inputLayer1Sha256
        && release.inputLayer2Sha256 === catalog.layer2Sha256[locale]
        && release.inputLayer3Sha256 === catalog.layer3Sha256[locale], 'Invalid Dev simulation release');
      const [content, captions] = await Promise.all([
        readJson(fetchImpl, `/content/${index.pageId}/${locale}.json`, release.assets.content),
        readJson(fetchImpl, `/captions/${index.pageId}/${locale}.json`, release.assets.captions),
      ]);
      variants[locale] = appVariant(index.pageId, locale, content, captions, english,
        release, catalog.videoDelivery);
    }
    return { weeks: [{ ...variants['zh-Hans'], contentVariants: variants }],
      defaultWeekId: index.pageId, errors: [] };
  } catch (error) {
    return { ...empty, errors: [String(error?.message || error)] };
  }
}
