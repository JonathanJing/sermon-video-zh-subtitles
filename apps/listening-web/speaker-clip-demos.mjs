// Shared iOS/Firebase audition contract. Demo evidence never approves a sermon release.
import { setIcon } from './icons.mjs';
export const CLIP_CATALOG_URL = '/voice-demos/speaker-clips-v2/catalog.json';
export const DEMO_LOCALES = ['zh-Hans', 'ko', 'es'];
const PREFIX = '/voice-demos/speaker-clips-v2/';
const LEGACY = '/voice-demos/2026-09-21-v2/';
const languageNames = { 'zh-Hans': '中文', ko: '한국어', es: 'Español' };
const require = (condition, message) => { if (!condition) throw new Error(message); };
const sha = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const text = value => typeof value === 'string' && Boolean(value.trim());
const duration = value => Number.isFinite(value) && value > 0;
const safePath = (value, prefix) => typeof value === 'string' && value.startsWith(prefix)
  && /^[a-zA-Z0-9_./-]+$/.test(value) && !value.includes('..') && !value.includes('//');
const sourceURL = value => {
  try { const url = new URL(value); return url.protocol === 'https:' && !url.username && !url.password; }
  catch { return false; }
};
export async function sha256(bytes) {
  return [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))]
    .map(value => value.toString(16).padStart(2, '0')).join('');
}
export async function validateSpeakerClips(catalog) {
  require(catalog?.schemaVersion === 'sermon-speaker-clip-demo-catalog-v2'
    && catalog.status === 'audition_demo'
    && catalog.sourceScope === 'source_clip_translation_audition_not_sermon_release'
    && catalog.humanListeningStatus === 'pending' && catalog.speakerCount === 6
    && catalog.sampleCount === 18 && Array.isArray(catalog.speakers)
    && catalog.speakers.length === 6, 'Invalid speaker clip catalog');
  const speakers = new Set(), clips = new Set(), paths = new Set();
  for (const speaker of catalog.speakers) {
    require(/^[a-z0-9_]+$/.test(speaker.speakerId) && text(speaker.displayName)
      && !speakers.has(speaker.speakerId) && text(speaker.clipId) && !clips.has(speaker.clipId), 'Invalid speaker identity');
    speakers.add(speaker.speakerId); clips.add(speaker.clipId);
    const source = speaker.source;
    require(source && sourceURL(source.url) && Number.isFinite(source.startSeconds)
      && source.startSeconds > 0 && source.endSeconds > source.startSeconds
      && source.endSeconds - source.startSeconds <= 60
      && sha(source.englishTextSha256), 'Invalid source interval');
    require(speaker.original?.locale === 'en' && text(speaker.original.text)
      && speaker.original.transcriptStatus === 'machine_screening_only', 'Missing English provenance');
    require(await sha256(new TextEncoder().encode(speaker.original.text)) === source.englishTextSha256,
      'English transcript hash mismatch');
    require(Array.isArray(speaker.samples) && speaker.samples.length === 3
      && DEMO_LOCALES.every(locale => speaker.samples.filter(sample => sample.locale === locale).length === 1),
      'Three unique translation locales required');
    for (const asset of [speaker.original, speaker.video, ...speaker.samples]) {
      require(asset && safePath(asset.path, PREFIX) && !paths.has(asset.path) && sha(asset.sha256)
        && Number.isSafeInteger(asset.bytes) && asset.bytes > 0 && duration(asset.durationSeconds)
        && asset.sourceClipId === speaker.clipId
        && (asset === speaker.video ? asset.path.endsWith('.mp4') && asset.bytes <= 20_000_000
          : asset.path.endsWith('.mp3') && asset.bytes <= 5_000_000 && asset.durationSeconds <= 180),
        'Invalid or cross-bound clip asset');
      paths.add(asset.path);
      if (asset !== speaker.video) require(asset.englishTextSha256 === source.englishTextSha256,
        'Cross-bound English source hash');
      if (speaker.samples.includes(asset)) require(text(asset.text) && asset.humanListeningStatus === 'pending',
        'Translation review provenance missing');
    }
    require(Math.abs(speaker.video.durationSeconds - (source.endSeconds - source.startSeconds)) <= 0.5
      && Math.abs(speaker.original.durationSeconds - (source.endSeconds - source.startSeconds)) <= 0.5,
      'Original/video duration mismatch');
  }
  return { ...catalog, matchedClip: true };
}
export function legacyDevClips(catalog) {
  require(catalog?.schemaVersion === 'sermon-multilingual-voice-demo-public-v1'
    && catalog.status === 'audition_demo' && catalog.humanListeningStatus === 'pending'
    && catalog.sourceScope === 'voice_capability_audition_not_sermon_translation'
    && catalog.speakerCount === 6 && catalog.sampleCount === 24
    && catalog.speakers?.length === 6, 'Invalid legacy Dev demo');
  const seen = new Set();
  const speakers = catalog.speakers.map(speaker => {
    require(/^[a-z0-9_]+$/.test(speaker.speakerId) && !seen.has(speaker.speakerId), 'Duplicate legacy speaker');
    seen.add(speaker.speakerId);
    require(Array.isArray(speaker.samples) && DEMO_LOCALES.every(locale =>
      speaker.samples.filter(sample => sample.locale === locale).length === 1), 'Duplicate or missing legacy locale');
    const samples = DEMO_LOCALES.map(locale => speaker.samples.find(sample => sample.locale === locale));
    require(text(speaker.displayName) && text(speaker.original?.text)
      && speaker.original.transcriptStatus === 'machine_screening_only' && sourceURL(speaker.original.sourceUrl),
      'Invalid legacy original');
    for (const asset of [speaker.original, ...samples]) require(asset && safePath(asset.path, LEGACY)
      && sha(asset.sha256) && Number.isSafeInteger(asset.bytes) && asset.bytes > 0 && asset.bytes <= 5_000_000 && text(asset.text),
      'Invalid legacy audition asset');
    require(samples.every(sample => sample.humanListeningStatus === 'pending'), 'Invalid legacy sample review status');
    return { ...speaker, samples, source: { url: speaker.original.sourceUrl }, video: null };
  });
  return { ...catalog, speakers, matchedClip: false };
}
export function legacyProductionClips(weekly, additions) {
  const bank = weekly?.voiceBank?.speakers;
  require(weekly?.schemaVersion === 'sermon-weekly-catalog-v1' && bank?.length === 6 && additions?.schemaVersion === 'sermon-production-voice-auditions-v1'
    && additions.status === 'audition_demo' && additions.humanListeningStatus === 'pending'
    && additions.sourceScope === 'voice_capability_audition_not_sermon_translation'
    && additions.speakerCount === 6 && additions.sampleCount === 12
    && additions.speakers?.length === 6, 'Invalid production audition fallback');
  const speakers = bank.map(speaker => {
    const extra = additions.speakers.find(item => item.speakerId === speaker.id && item.displayName === speaker.name);
    require(speaker.humanListeningStatus === 'accepted' && extra && extra.samples?.length === 2, 'Missing legacy speaker samples');
    const convert = (track, locale) => {
      require(safePath(track?.audioUrl, '/media/') && sha(track.sha256)
        && duration(track.durationSeconds) && track.cues?.length, 'Invalid published audition track');
      return { path: track.audioUrl, sha256: track.sha256, locale, durationSeconds: track.durationSeconds,
        text: track.cues.map(cue => cue.text).join('\n'), transcriptStatus: 'machine_screening_only' };
    };
    const samples = [convert(speaker.chinese, 'zh-Hans'), ...['ko', 'es'].map(locale => {
      const sample = extra.samples.find(item => item.locale === locale);
      require(sample && safePath(sample.path, LEGACY) && sha(sample.sha256)
        && Number.isSafeInteger(sample.bytes) && sample.bytes > 0 && text(sample.text)
        && sample.humanListeningStatus === 'pending', 'Invalid extra audition sample');
      return sample;
    })];
    require(sourceURL(speaker.referenceSourceUrl), 'Missing original source URL');
    return { speakerId: speaker.id, displayName: speaker.name, original: convert(speaker.reference, 'en'),
      source: { url: speaker.referenceSourceUrl }, samples, video: null };
  });
  require(new Set(speakers.map(speaker => speaker.speakerId)).size === 6, 'Duplicate fallback speaker');
  return { speakers, matchedClip: false };
}
export function validateDemoResponse(response, path, origin = globalThis.location?.origin) {
  if (!response.url) return; // Injected test transports may not expose a final URL.
  const url = new URL(response.url);
  require(origin && url.origin === origin && url.pathname === path && !url.search && !url.hash
    && !url.username && !url.password, 'Unsafe demo response redirect');
}
async function fetchJSON(url, fetcher, origin) {
  const response = await fetcher(url, { cache: 'no-store' });
  validateDemoResponse(response, url, origin);
  require(response.ok, `Demo HTTP ${response.status}`);
  return response.json();
}
export async function loadSpeakerClips({ production = false, fetcher = fetch, origin = globalThis.location?.origin } = {}) {
  const response = await fetcher(CLIP_CATALOG_URL, { cache: 'no-store' });
  validateDemoResponse(response, CLIP_CATALOG_URL, origin);
  if (response.ok) return validateSpeakerClips(await response.json());
  require(response.status === 404, `Demo HTTP ${response.status}`);
  if (!production) return legacyDevClips(await fetchJSON(`${LEGACY}catalog.json`, fetcher, origin));
  const [weekly, additions] = await Promise.all([fetchJSON('/weekly.json', fetcher, origin),
    fetchJSON(`${LEGACY}production-ko-es.json`, fetcher, origin)]);
  return legacyProductionClips(weekly, additions);
}
export async function verifiedAssetURL(asset, { fetcher = fetch, createURL = URL.createObjectURL, origin = globalThis.location?.origin } = {}) {
  const response = await fetcher(asset.path, { cache: 'force-cache' });
  validateDemoResponse(response, asset.path, origin);
  require(response.ok, `Media HTTP ${response.status}`);
  if (asset.path.endsWith('.mp4')) {
    const type = response.headers?.get('content-type')?.split(';')[0].trim().toLowerCase();
    require(!type || ['video/mp4', 'application/octet-stream'].includes(type), 'Unexpected video content type');
  }
  const maxBytes = asset.path.endsWith('.mp4') ? 20_000_000 : 5_000_000;
  const limit = Math.min(asset.bytes ?? maxBytes, maxBytes);
  const length = Number(response.headers?.get('content-length'));
  require(!Number.isFinite(length) || length <= limit, 'Demo media exceeds byte limit');
  let bytes;
  if (response.body?.getReader) {
    const reader = response.body.getReader(), chunks = []; let total = 0;
    try {
      for (;;) { const { done, value } = await reader.read(); if (done) break;
        total += value.byteLength; require(total <= limit, 'Demo media exceeds byte limit'); chunks.push(value); }
    } catch (error) { await reader.cancel(); throw error; }
    const joined = new Uint8Array(total); let offset = 0;
    for (const chunk of chunks) { joined.set(chunk, offset); offset += chunk.byteLength; }
    bytes = joined.buffer;
  } else bytes = await response.arrayBuffer();
  require(bytes.byteLength > 0 && bytes.byteLength <= limit, 'Demo media exceeds byte limit');
  require((asset.bytes === undefined || bytes.byteLength === asset.bytes)
    && await sha256(bytes) === asset.sha256, 'Demo media hash mismatch');
  return createURL(new Blob([bytes], { type: asset.path.endsWith('.mp4') ? 'video/mp4' : asset.path.endsWith('.wav') ? 'audio/wav' : 'audio/mpeg' }));
}
// Pause/resume is explicit, and switching a language never auto-plays.
export function createDemoPlayer(media, { pauseOthers, resolveURL = verifiedAssetURL, onChange = () => {}, onError = () => {} }) {
  let asset, generation = 0, pending = false, disposed = false, wantsPlayback = false;
  const urls = new Map();
  const refresh = () => onChange({ playing: !media.paused && !media.ended, pending,
    currentTime: media.currentTime || 0, duration: Number.isFinite(media.duration) ? media.duration : asset?.durationSeconds || 0 });
  for (const event of ['play', 'pause', 'ended', 'timeupdate', 'loadedmetadata']) media.addEventListener(event, refresh);
  media.addEventListener('play', () => pauseOthers(media));
  media.addEventListener('error', () => onError(new Error('Demo playback failed')));
  const pause = () => { generation++; wantsPlayback = false; pending = false; media.pause(); refresh(); };
  return {
    select(next) { pause(); asset = next; media.removeAttribute('src'); media.load(); refresh(); },
    pause,
    async toggle() {
      if (!asset || disposed) return;
      if (!media.paused || pending) { pause(); return; }
      const requestedAsset = { ...asset }, key = `${asset.path}:${asset.sha256}`;
      const token = ++generation; wantsPlayback = true; pending = true; pauseOthers(media); refresh();
      try {
        let url = urls.get(key);
        if (!url) { url = await resolveURL(requestedAsset); if (disposed) { URL.revokeObjectURL(url); return; } urls.set(key, url); }
        if (token !== generation) return;
        if (media.src !== url) media.src = url;
        await media.play();
        if (token !== generation && !wantsPlayback) media.pause();
      } catch (error) { if (token === generation) onError(error); }
      finally { if (token === generation) { pending = false; refresh(); } }
    },
    dispose() { disposed = true; pause(); for (const url of urls.values()) URL.revokeObjectURL(url); urls.clear(); },
  };
}
const COPY = {
 zh: { title: '多语种音色试听 · Demo', intro: '每位讲员同一个英文片段，可听原声、看视频，再比较三种语言的合成音频。', legacy: '旧版独立样音：合成文稿与原声并非同一片段，不能作为翻译对照。', original: '英文原声', generated: 'AI 合成试听', video: '同片段视频', source: '原声来源', transcript: '英文机器转写参考', compare: '英文与译文', script: '独立样音文稿', pending: '待人工听审 · 不属于正式证道音频', play: '播放', pause: '暂停', loading: '加载中，点按取消', error: '试听暂时不可用，请重试。', english: '英文机器转写参考', disclosure: '独立个人项目；AI 合成音频不代表讲员或教会背书。' },
 en: { title: 'Multilingual voice demos', intro: 'One English clip per speaker: listen, watch, then compare three translated AI voices.', legacy: 'Legacy independent samples: scripts differ from the original clip and are not translation comparisons.', original: 'Original English', generated: 'AI voice audition', video: 'Same-clip video', source: 'Original source', transcript: 'Machine English transcript reference', compare: 'English and translation', script: 'Independent sample script', pending: 'Human listening review pending · not released sermon audio', play: 'Play', pause: 'Pause', loading: 'Loading, tap to cancel', error: 'Demo unavailable. Please try again.', english: 'Machine English transcript reference', disclosure: 'Independent personal project; AI audio is not endorsed by the speakers or church.' },
 ko: { title: '다국어 음색 데모', intro: '설교자별 같은 영어 구간의 원음과 영상을 보고 세 언어의 AI 음성을 비교하세요.', legacy: '이전 독립 샘플: 원음과 원고가 다른 구간이므로 번역 대조가 아닙니다.', original: '영어 원음', generated: 'AI 합성 샘플', video: '같은 구간 영상', source: '원음 출처', transcript: '영어 기계 전사 참고', compare: '영어와 번역문', script: '독립 샘플 원고', pending: '청취 검토 대기 중 · 정식 설교 음성 아님', play: '재생', pause: '일시 정지', loading: '로딩 중, 눌러 취소', error: '샘플을 불러올 수 없습니다. 다시 시도하세요.', english: '영어 기계 전사 참고', disclosure: '독립 개인 프로젝트이며 AI 음성은 설교자나 교회의 보증이 아닙니다.' },
 es: { title: 'Demos de voces multilingües', intro: 'Un mismo fragmento por orador: escucha, mira y compara voces de IA en tres idiomas.', legacy: 'Muestras independientes anteriores: el texto difiere del fragmento original y no permite comparar traducciones.', original: 'Original en inglés', generated: 'Muestra de voz de IA', video: 'Vídeo del mismo fragmento', source: 'Fuente original', transcript: 'Transcripción automática de referencia', compare: 'Inglés y traducción', script: 'Texto independiente de muestra', pending: 'Revisión auditiva pendiente · no es audio publicado del sermón', play: 'Reproducir', pause: 'Pausar', loading: 'Cargando, pulsa para cancelar', error: 'Demo no disponible. Inténtalo de nuevo.', english: 'Transcripción automática de referencia', disclosure: 'Proyecto personal independiente; el audio de IA no cuenta con el respaldo de los oradores ni de la iglesia.' },
 vi: { title: 'Bản nghe thử giọng đa ngôn ngữ', intro: 'Mỗi diễn giả dùng cùng một đoạn tiếng Anh: nghe giọng gốc, xem video và so sánh ba bản giọng AI.', legacy: 'Mẫu cũ độc lập: văn bản mẫu khác đoạn gốc, không phải bản dịch đối chiếu.', original: 'Giọng tiếng Anh gốc', generated: 'Mẫu giọng AI', video: 'Video cùng đoạn', source: 'Nguồn bản gốc', transcript: 'Tham khảo bản chép máy tiếng Anh', compare: 'Tiếng Anh và bản dịch', script: 'Văn bản mẫu độc lập', pending: 'Chờ người nghe kiểm duyệt · không phải âm thanh bài giảng đã phát hành', play: 'Phát', pause: 'Tạm dừng', loading: 'Đang tải, chạm để hủy', error: 'Không thể tải bản nghe thử. Vui lòng thử lại.', english: 'Tham khảo bản chép máy tiếng Anh', disclosure: 'Dự án cá nhân độc lập; âm thanh AI không được diễn giả hoặc nhà thờ bảo trợ.' },
};
export const demoCopy = doc => COPY[doc.documentElement.lang.toLowerCase().split('-')[0]] || COPY.zh;
const time = seconds => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;
export async function mountSpeakerClipDemos(root, { production = false, doc = document, fetcher = fetch, onPlay = () => {} } = {}) {
  const catalog = await loadSpeakerClips({ production, fetcher });
  const localized = [], controllers = [];
  const c = () => demoCopy(doc);
  const node = (tag, className = '', value) => { const n = doc.createElement(tag); n.className = className; if (value !== undefined) n.textContent = value; return n; };
  const label = (key, tag = 'p', className = '') => { const n = node(tag, className); localized.push(() => { n.textContent = c()[key]; }); return n; };
  const pauseOthers = active => { onPlay(); for (const item of doc.querySelectorAll('audio, video')) if (item !== active) item.pause();
    for (const player of controllers) if (player.media !== active) player.controller.pause(); };
  const body = node('div', 'voice-demo-list');
  body.append(label(catalog.matchedClip ? 'intro' : 'legacy', 'p', 'voice-demo-intro'));
  const player = (asset, speaker, heading, video = false) => {
    let currentAsset = asset;
    const section = node('section', 'voice-demo-track'), headingNode = label(heading, 'h4');
    const audio = node(video ? 'video' : 'audio'); audio.preload = 'none'; audio.playsInline = true;
    if (video) { audio.controls = true; audio.hidden = true; }
    const controls = node('div', 'voice-demo-controls'), button = node('button', 'voice-demo-play'), icon = node('span');
    button.type = 'button'; button.append(icon);
    const timestamp = node('span', 'voice-demo-time');
    const error = label('error', 'p', 'voice-demo-error'); error.hidden = true; error.setAttribute('role', 'status');
    let state = { playing: false, pending: false, currentTime: 0, duration: asset.durationSeconds || 0 };
    const render = () => { const trackLabel = heading === 'generated' ? `${languageNames[currentAsset.locale]} · ${c()[heading]}` : c()[heading];
      headingNode.textContent = trackLabel;
      setIcon(icon, state.playing || state.pending ? 'pause.fill' : 'play.fill');
      button.setAttribute('aria-label', `${speaker.displayName} · ${trackLabel} · ${c()[state.pending ? 'loading' : state.playing ? 'pause' : 'play']}`);
      button.setAttribute('aria-pressed', String(state.playing)); timestamp.textContent = `${time(state.currentTime)} / ${time(state.duration)}`; };
    localized.push(render);
    const controller = createDemoPlayer(audio, { pauseOthers,
      resolveURL: selected => verifiedAssetURL(selected, { fetcher }),
      onChange: next => { state = next; render(); }, onError: () => { error.hidden = false; } });
    button.addEventListener('click', () => { error.hidden = true; if (video) audio.hidden = false; void controller.toggle(); });
    controller.select(asset); controls.append(button, timestamp); section.append(headingNode, audio, controls, error);
    controllers.push({ controller, media: audio });
    return { section, controller, headingNode, select(next) { currentAsset = next; error.hidden = true; controller.select(next); } };
  };
  for (const speaker of catalog.speakers) {
    const card = node('details', 'voice-demo-speaker voice-card');
    card.dataset.speakerId = speaker.speakerId;
    card.append(node('summary', '', speaker.displayName));
    const original = player(speaker.original, speaker, 'original'); card.append(original.section);
    if (speaker.video) card.append(player(speaker.video, speaker, 'video', true).section);
    const reference = node('details', 'voice-demo-text'); reference.append(label('transcript', 'summary'));
    const english = node('p', '', speaker.original.text); english.lang = 'en'; reference.append(english); if (!catalog.matchedClip) card.append(reference);
    const source = node('a', 'voice-demo-source'); source.href = speaker.source.url; source.target = '_blank'; source.rel = 'noopener noreferrer';
    source.append(label('source', 'span'));
    source.addEventListener('click', () => controllers.forEach(player => player.controller.pause()));
    if (Number.isFinite(speaker.source.startSeconds)) source.append(node('span', '', ` · ${time(speaker.source.startSeconds)}–${time(speaker.source.endSeconds)}`));
    const choices = node('div', 'voice-demo-languages'); choices.setAttribute('role', 'group');
    let selected = speaker.samples.find(sample => sample.locale === 'zh-Hans');
    const synthetic = player(selected, speaker, 'generated');
    const transcript = node('details', 'voice-demo-text'); transcript.append(label(catalog.matchedClip ? 'compare' : 'script', 'summary'));
    if (catalog.matchedClip) { transcript.append(label('english', 'h4')); const en = node('p', '', speaker.original.text); en.lang = 'en'; transcript.append(en); }
    const translation = node('p', '', selected.text); translation.lang = selected.locale; transcript.append(translation);
    const buttons = [];
    for (const locale of DEMO_LOCALES) {
      const button = node('button', 'voice-demo-language', languageNames[locale]); button.type = 'button'; button.lang = locale;
      const refresh = () => button.setAttribute('aria-pressed', String(selected.locale === locale)); buttons.push(refresh);
      button.addEventListener('click', () => { if (selected.locale === locale) return;
        controllers.forEach(player => player.controller.pause());
        selected = speaker.samples.find(sample => sample.locale === locale); synthetic.select(selected);
        translation.textContent = selected.text; translation.lang = locale; buttons.forEach(update => update()); });
      choices.append(button);
    }
    buttons.forEach(update => update()); synthetic.section.prepend(choices); synthetic.section.append(transcript); card.append(synthetic.section);
    card.append(source, label('pending', 'p', 'voice-demo-pending'));
    card.addEventListener('toggle', () => { if (!card.open) for (const item of card.querySelectorAll('audio, video')) { item.pause(); controllers.find(player => player.media === item)?.controller.pause(); } });
    body.append(card);
  }
  body.append(label('disclosure', 'p', 'voice-demo-disclosure'));
  root.replaceChildren(body);
  const refresh = () => localized.forEach(update => update()); refresh();
  const observer = new MutationObserver(refresh); observer.observe(doc.documentElement, { attributes: true, attributeFilter: ['lang'] });
  const main = doc.getElementById('audio'); const mainPlay = () => controllers.forEach(player => player.controller.pause()); main?.addEventListener('play', mainPlay);
  const pause = () => controllers.forEach(player => player.controller.pause());
  return { pause, dispose() { pause(); observer.disconnect(); main?.removeEventListener('play', mainPlay); controllers.forEach(player => player.controller.dispose()); } };
}
