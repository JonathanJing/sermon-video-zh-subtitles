import './style.css';
import { stepTimingSummary, timingCoverageNote } from './timing.js';
import { tr, uiLanguage } from './i18n.js';

const LABELS = {
  pending: '待开始', running: '进行中', waiting_review: '待审核', blocked: '阻塞', complete: '已记录',
  not_generated: '未制作', generated_local: '本地已生成', http_verified: '线上已核验',
  declared_unchecked: '已声明·待核验', index_missing: '索引缺失', hash_mismatch: '哈希不符',
  binding_invalid: '绑定无效', legacy_catalog_local: '旧目录·本地',
  legacy_catalog_http_verified: '旧目录·线上已核验', legacy_track_listed: '旧音轨·已列出',
  legacy_track_http_verified: '旧音轨·线上已核验', release_candidate: '发布候选',
  published_http_verified: '线上已核验', human_reviewed: '人工已审核',
  candidate: '候选', withdrawn: '已撤回', unavailable: '无音频', unknown: '未知',
  not_run: '未执行', passed: '通过', failed: '失败', pass: '通过', fail: '失败',
  first_seen: '首次发现', updated: '视频已更新', unchanged: '未变化',
  not_detected: '未检测到视频', not_checked: '未检查', video_id_unknown: '视频 ID 未知',
  was_live: '直播回放', available: '可用', manual_available: '人工提供',
  live: '直播中', upcoming: '即将直播', source_detected: '已找到来源', fallback: '回退来源',
  poc_catalog_local: 'Dev POC · 本地目录', poc_catalog_http_verified: 'Dev POC · 线上页面',
  poc_track_listed: 'POC 音轨已列出', poc_track_http_verified: 'POC 音轨线上已核验',
  machine_review_pass_human_review_pending: '机器文字通过 · 待人审',
  requires_review: '需要复核', approved: '已审核', rejected: '未通过',
};
const LABELS_EN = {
  pending: 'Not started', running: 'In progress', waiting_review: 'Awaiting review', blocked: 'Blocked', complete: 'Recorded',
  not_generated: 'Not produced', generated_local: 'Generated locally', http_verified: 'Verified online',
  declared_unchecked: 'Declared · Unverified', index_missing: 'Index missing', hash_mismatch: 'Hash mismatch',
  binding_invalid: 'Invalid binding', legacy_catalog_local: 'Legacy catalog · Local',
  legacy_catalog_http_verified: 'Legacy catalog · Verified online', legacy_track_listed: 'Legacy track · Listed',
  legacy_track_http_verified: 'Legacy track · Verified online', release_candidate: 'Release candidate',
  published_http_verified: 'Verified online', human_reviewed: 'Human reviewed',
  candidate: 'Candidate', withdrawn: 'Withdrawn', unavailable: 'Audio unavailable', unknown: 'Unknown',
  not_run: 'Not run', passed: 'Passed', failed: 'Failed', pass: 'Passed', fail: 'Failed',
  first_seen: 'First seen', updated: 'Video updated', unchanged: 'Unchanged',
  not_detected: 'No video detected', not_checked: 'Not checked', video_id_unknown: 'Video ID unknown',
  was_live: 'Live replay', available: 'Available', manual_available: 'Provided manually',
  live: 'Live', upcoming: 'Upcoming', source_detected: 'Source found', fallback: 'Fallback source',
  poc_catalog_local: 'Dev POC · Local catalog', poc_catalog_http_verified: 'Dev POC · Online page',
  poc_track_listed: 'POC track listed', poc_track_http_verified: 'POC track verified online',
  machine_review_pass_human_review_pending: 'Machine text passed · Awaiting human review',
  requires_review: 'Needs review', approved: 'Reviewed', rejected: 'Rejected',
};
const LOCALE_NAMES = { 'zh-Hans': '简体中文', ko: '한국어', es: 'Español', vi: 'Tiếng Việt' };
const LOCALE_NAMES_EN = { 'zh-Hans': 'Simplified Chinese', ko: 'Korean', es: 'Spanish', vi: 'Vietnamese' };
const STEP_NAMES = {
  'L1-01':'来源媒体、身份与人工范围','L1-02':'冻结英文文本与词级对齐','L1-03':'句界、停顿和锚点核验','L1-04':'英文人工审核与 Source Package',
  'L2-01':'目标语言策略与经文版本','L2-02':'逐单元翻译与覆盖','L2-03':'独立机器复核与语言检查','L2-04':'人工文字审核与 Candidate',
  'L3-01':'授权音色、能力与 Speech Job','L3-02':'逐单元合成','L3-03':'解码、哈希与回转写筛查','L3-04':'排程、字幕与完整音轨','L3-05':'人工全文听审','L3-06':'同视频同步审核与 Audio Package',
  'L4-01':'同语言 Release Package 与文件清单','L4-02':'构建与上传','L4-03':'线上 HTTP、哈希与 Range 核验','L4-04':'客户端文字、语言与播放核验',
};
const STEP_NAMES_EN = {
  'L1-01':'Source media, identity, and approved window','L1-02':'Frozen English text and word alignment','L1-03':'Sentence boundaries, pauses, and anchors','L1-04':'Human English review and Source Package',
  'L2-01':'Target-language policy and scripture version','L2-02':'Unit translation and coverage','L2-03':'Independent machine review and language checks','L2-04':'Human text review and Candidate',
  'L3-01':'Authorized voice, capability, and Speech Job','L3-02':'Unit-by-unit synthesis','L3-03':'Decode, hash, and back-transcription screen','L3-04':'Scheduling, subtitles, and full audio track','L3-05':'Human full-audio review','L3-06':'Video sync review and Audio Package',
  'L4-01':'Same-language Release Package and manifest','L4-02':'Build and upload','L4-03':'Online HTTP, hash, and Range checks','L4-04':'Client text, language, and playback checks',
};
const stepName = (step) => (uiLanguage() === 'en' ? STEP_NAMES_EN : STEP_NAMES)[step.id.split('@')[0]] || step.id;
const STATUS_CLASS = {
  complete: 'ok', passed: 'ok', pass: 'ok', http_verified: 'ok', published_http_verified: 'ok',
  updated: 'ok', running: 'active', first_seen: 'active', waiting_review: 'warn',
  blocked: 'bad', withdrawn: 'bad', failed: 'bad', fail: 'bad', hash_mismatch: 'bad',
  binding_invalid: 'bad', index_missing: 'bad',
};

const byId = (id) => document.getElementById(id);
const text = (id, value) => { byId(id).textContent = value ?? '—'; };
const name = (locale) => (uiLanguage() === 'en' ? LOCALE_NAMES_EN : LOCALE_NAMES)[locale] || locale || tr('共享', 'Shared');
const label = (value) => (uiLanguage() === 'en' ? LABELS_EN : LABELS)[value] || value || tr('未知', 'Unknown');
const make = (tag, className, value) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (value !== undefined) node.textContent = value;
  return node;
};
const statusClass = (value) => STATUS_CLASS[value] || 'neutral';
const localeKey = (locale) => String(locale).replace(/[^a-zA-Z0-9-]/g, '-');
const layerId = (locale, layer) => `layer-${localeKey(locale)}-${layer}`;
const deliveryId = (locale) => `delivery-${localeKey(locale)}`;
const stepId = (id) => `checkpoint-${String(id).replace(/[^a-zA-Z0-9-]/g, '-')}`;

function jumpTo(id) {
  const target = byId(id);
  if (!target) return;
  if (target.tagName === 'DETAILS') target.open = true;
  target.scrollIntoView({ behavior: 'smooth', block: 'center' });
  target.tabIndex = -1;
  target.focus({ preventScroll: true });
}

function dateTime(value) {
  if (!value || Number.isNaN(Date.parse(value))) return tr('未知', 'Unknown');
  return new Intl.DateTimeFormat(uiLanguage() === 'en' ? 'en-US' : 'zh-CN', {
    timeZone: 'America/Los_Angeles', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(new Date(value)) + ' PT';
}

function safeLink(url, title) {
  const value = typeof url === 'string' ? url : '';
  try {
    const parsed = new URL(value);
    if (parsed.protocol !== 'https:') throw new Error('not HTTPS');
    const link = make('a', 'inline-link', title);
    link.href = parsed.href;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    return link;
  } catch {
    return make('span', 'muted', tr('暂无有效链接', 'No valid link'));
  }
}

function pill(value) {
  return make('span', `badge ${statusClass(value)}`, label(value));
}

function setBadge(id, value) {
  const node = byId(id);
  node.textContent = label(value);
  node.className = `badge ${statusClass(value)}`;
}

function renderSource(source) {
  const change = source?.videoChange || 'not_checked';
  setBadge('source-state', change);
  text('metric-video', label(change));
  text('metric-video-note', source?.videoPresent ? tr('本周有候选视频', 'Candidate video found this week') : tr('等待 source monitor', 'Awaiting source monitor'));
  byId('source-page').replaceChildren(safeLink(source?.inputPageUrl, tr('打开输入源页面', 'Open source page')));
  text('source-video', change === 'not_checked' ? label('not_checked') :
    source?.videoPresent ? tr('已检测到', 'Detected') : tr('未检测到', 'Not detected'));
  text('source-video-state', label(source?.videoState || source?.monitorStatus));
  const checked = source?.checkedAt ? dateTime(source.checkedAt) : label('not_checked');
  const age = source?.checkedAt ? Date.now() - Date.parse(source.checkedAt) : 0;
  text('source-checked', `${checked}${age > 2 * 60 * 60 * 1000 ? tr(' · 可能过期', ' · May be stale') : ''}`);
}

function renderShared(row, steps) {
  text('shared-detail', tr(`${row.complete}/${row.total} 检查点 · ${row.percent}%`, `${row.complete}/${row.total} checkpoints · ${row.percent}%`));
  const sharedSteps = steps.filter((step) => step.layer === 1);
  setBadge('shared-status', row.complete === row.total ? 'complete' :
    sharedSteps.some((step) => step.status === 'blocked') ? 'blocked' :
    sharedSteps.some((step) => step.status === 'waiting_review') ? 'waiting_review' : 'running');
  byId('shared-fill').style.width = `${Math.max(0, Math.min(100, row.percent || 0))}%`;
  const list = byId('shared-steps');
  list.replaceChildren(...steps.filter((step) => step.layer === 1).map((step) => {
    const item = make('li');
    item.id = stepId(step.id);
    const detail = make('span', 'shared-step-body');
    detail.append(make('span', '', stepName(step)));
    const timing = stepTimingSummary(step);
    if (timing.length) detail.append(make('small', 'step-timing', timing.join(' · ')));
    item.append(make('span', `dot ${statusClass(step.status)}`), detail, pill(step.status));
    return item;
  }));
}

function layerState(steps, locale, layer, progress) {
  const related = steps.filter((step) => step.locale === locale && step.layer === layer);
  if (related.some((step) => step.status === 'blocked')) return 'blocked';
  if (related.some((step) => step.status === 'waiting_review')) return 'waiting_review';
  if (related.some((step) => step.status === 'running')) return 'running';
  if (progress?.total > 0) {
    if (progress.complete >= progress.total) return 'complete';
    if (progress.complete > 0) return 'running';
  }
  if (related.length && related.every((step) => step.status === 'complete')) return 'complete';
  if (related.some((step) => step.status === 'complete')) return 'running';
  return 'pending';
}

function flowButton(title, detail, state, target, stateLabel = '') {
  const button = make('button', `flow-node ${statusClass(state)}`);
  button.type = 'button';
  button.append(make('span', 'flow-node-title', title), make('strong', '', detail));
  if (stateLabel) button.append(make('small', 'flow-state', stateLabel));
  button.addEventListener('click', () => jumpTo(target));
  return button;
}

function renderFlow(snapshot) {
  const steps = snapshot.steps || [];
  const sharedState = layerState(steps, null, 1, snapshot.sharedLayer1);
  const shared = make('div', 'flow-shared');
  const sourceMonitor = flowButton(tr('视频更新监控 · 独立观察', 'Video update monitor · Separate observation'), label(snapshot.source?.videoChange),
    snapshot.source?.videoChange === 'not_checked' ? 'pending' : 'running', 'source-panel');
  sourceMonitor.classList.add('evidence');
  shared.append(flowButton(tr('Layer 1 · 英文事实与锚点', 'Layer 1 · English source and anchors'),
      `${snapshot.sharedLayer1?.complete || 0}/${snapshot.sharedLayer1?.total || 0}`,
      sharedState, 'shared-panel', label(sharedState)),
    sourceMonitor);
  const branches = make('div', 'flow-branches');
  for (const item of snapshot.locales || []) {
    const row = make('div', 'flow-branch');
    row.append(make('strong', 'flow-locale', name(item.locale)));
    for (const layer of [2, 3]) {
      if (layer > 2) row.append(make('span', 'flow-arrow', '→'));
      const progress = item.layers?.[String(layer)] || { complete: 0, total: 0 };
      const state = layerState(steps, item.locale, layer, progress);
      row.append(flowButton(`Layer ${layer}`, `${progress.complete}/${progress.total}`,
        state, layerId(item.locale, layer), label(state)));
    }
    branches.append(row);
  }
  const locales = snapshot.locales || [];
  const layer3Ready = locales.filter((item) => {
    const progress = item.layers?.['3'];
    return progress?.total > 0 && progress.complete === progress.total &&
      layerState(steps, item.locale, 3, progress) === 'complete';
  }).length;
  const releaseComplete = locales.reduce((sum, item) => sum + (item.layers?.['4']?.complete || 0), 0);
  const releaseTotal = locales.reduce((sum, item) => sum + (item.layers?.['4']?.total || 0), 0);
  const releaseSteps = steps.filter((step) => step.layer === 4);
  const releaseState = releaseSteps.some((step) => step.status === 'blocked') ? 'blocked' :
    releaseSteps.some((step) => step.status === 'waiting_review') ? 'waiting_review' :
    releaseSteps.some((step) => step.status === 'running') ? 'running' :
    releaseTotal > 0 && releaseComplete === releaseTotal ? 'complete' :
    releaseComplete > 0 ? 'running' : 'pending';
  const join = make('div', 'flow-join');
  join.append(make('span', 'flow-join-arrow', '↓'), flowButton(
    tr('Layer 4 · 多语言发布与播放', 'Layer 4 · Multilingual delivery and playback'),
    `${releaseComplete}/${releaseTotal}`,
    releaseState, 'release-panel', tr(`Layer 3 分支 ${layer3Ready}/${locales.length} 已记录`, `Layer 3 branches ${layer3Ready}/${locales.length} recorded`)));
  byId('flow-map').replaceChildren(shared, branches, join);
}

function renderEta(report) {
  const missing = report.missingEstimateCount || 0;
  const blockers = report.blockerCount || 0;
  text('metric-eta', report.earliestContinuousEta ? dateTime(report.earliestContinuousEta) : tr('未知', 'Unknown'));
  text('metric-eta-note', report.earliestContinuousEta ? tr('连续串行参考值 · 不含等待和返工', 'Serial-work reference · Excludes waits and rework') :
    tr(`${missing} 项缺剩余工时 · ${blockers} 项待审核或阻塞`, `${missing} missing estimates · ${blockers} awaiting review or blocked`));
  const method = tr(
    '逐项计算未完成检查点的剩余分钟：有实测单元速度时，用已耗分钟 ÷ 已完成单元 × 剩余单元；否则用登记估时减已耗分钟。将各项剩余分钟串行相加，再加到快照生成时间。',
    'For each unfinished checkpoint, estimate remaining minutes from measured minutes per completed unit times remaining units. Otherwise, subtract elapsed minutes from the recorded estimate. Add all remaining minutes serially to the snapshot time.');
  const limit = tr(
    '待审核、阻塞或任何一项缺估时则显示未知；参考值不含审核等待、排队、并行调度、返工和发布窗口。',
    'Any pending review, blockage, or missing estimate makes the result unknown. The reference excludes review waits, queues, parallel scheduling, rework, and release windows.');
  text('eta-explanation', `${method}${limit}${report.earliestContinuousEta && report.remainingSerialMinutes != null ? tr(` 当前合计剩余 ${report.remainingSerialMinutes} 分钟。`, ` Current serial remainder: ${report.remainingSerialMinutes} minutes.`) : ''}`);
}

function renderBlockers(report, steps) {
  const ids = report.blockedStepIds || steps.filter((step) =>
    ['blocked', 'waiting_review'].includes(step.status)).map((step) => step.id);
  const related = ids.map((id) => steps.find((step) => step.id === id)).filter(Boolean);
  text('metric-blockers', report.blockerCount ?? related.length);
  const details = byId('blocker-details');
  details.hidden = related.length === 0;
  const list = byId('blocker-list');
  list.replaceChildren(...related.map((step) => {
    const item = make('li');
    const button = make('button', 'blocker-link', `${name(step.locale)} · ${stepName(step)}`);
    button.type = 'button';
    button.addEventListener('click', () => jumpTo(stepId(step.id)));
    item.append(button, pill(step.status));
    return item;
  }));
}

function renderLocales(locales, steps) {
  const grid = byId('locale-grid');
  const releaseGrid = byId('release-grid');
  const openDeliveries = new Set([...releaseGrid.querySelectorAll('.delivery-details[open]')].map((item) => item.id));
  const releases = [];
  grid.replaceChildren(...locales.map((item) => {
    const card = make('article', 'locale-card panel');
    const releaseCard = make('article', 'release-card panel');
    releaseCard.append(make('h4', '', name(item.locale)));
    const top = make('div', 'locale-head');
    const title = make('div');
    title.append(make('span', 'eyebrow', item.locale), make('h4', '', name(item.locale)));
    const completed = [2, 3].reduce((sum, layer) => sum + (item.layers?.[String(layer)]?.complete || 0), 0);
    const total = [2, 3].reduce((sum, layer) => sum + (item.layers?.[String(layer)]?.total || 0), 0);
    const localeProgress = make('div', 'locale-overall');
    localeProgress.append(make('strong', '', `${total ? Math.round(100 * completed / total) : 0}%`),
      make('span', '', tr(`Layer 2–3 · ${completed}/${total} 检查点`, `Layer 2–3 · ${completed}/${total} checkpoints`)));
    top.append(title, localeProgress);
    card.append(top);
    const layers = make('div', 'locale-layers');
    for (const layer of [2, 3, 4]) {
      const row = item.layers?.[String(layer)] || { complete: 0, total: 0, percent: 0 };
      const block = make('section', 'layer-row');
      block.id = layerId(item.locale, layer);
      const meta = make('div', 'layer-meta');
      const layerName = (uiLanguage() === 'en'
        ? { 2: 'Target-language text', 3: 'Audio and sync', 4: 'Release and playback' }
        : { 2: '目标语言文字', 3: '音频与同步', 4: '发布与播放' })[layer];
      meta.append(make('span', '', `Layer ${layer} · ${layerName}`),
                  make('strong', '', `${row.complete}/${row.total} · ${row.percent || 0}%`));
      const track = make('div', 'progress-track small-track');
      const fill = make('div', 'progress-fill');
      fill.style.width = `${Math.max(0, Math.min(100, row.percent || 0))}%`;
      track.append(fill);
      const list = make('ol', 'layer-steps');
      const layerSteps = (steps || []).filter((step) => step.locale === item.locale && step.layer === layer);
      list.replaceChildren(...layerSteps.map((step) => {
        const line = make('li', `layer-step ${statusClass(step.status)}`);
        line.id = stepId(step.id);
        const description = make('div', 'layer-step-description');
        description.append(make('span', 'layer-step-number', step.id.split('@')[0]),
          make('span', 'layer-step-name', stepName(step)));
        if (step.totalUnits != null) description.append(make('small', 'unit-count', tr(`${step.doneUnits || 0}/${step.totalUnits} 单元`, `${step.doneUnits || 0}/${step.totalUnits} units`)));
        const timing = stepTimingSummary(step);
        if (timing.length) description.append(make('small', 'step-timing', timing.join(' · ')));
        line.append(description, pill(step.status));
        return line;
      }));
      if (!layerSteps.length) list.append(make('li', 'muted', tr('暂无检查点明细', 'No checkpoint details')));
      block.append(meta, track, list);
      if (layer === 4) releaseCard.append(block);
      else layers.append(block);
    }
    card.append(layers);
    if (item.delivery?.origin === 'dev_poc_catalog') {
      const checks = [
        [tr('文字候选', 'Text candidate'), item.delivery.pocCandidateStatus === 'machine_review_pass_human_review_pending'],
        [tr('音轨在线', 'Audio online'), item.delivery.voiceStatus === 'poc_track_http_verified'],
        [tr('页面目录', 'Page catalog'), item.delivery.pageStatus === 'poc_catalog_http_verified'],
        [tr('声纹', 'Fingerprint'), item.delivery.fingerprint?.status === 'http_verified'],
      ];
      const complete = checks.filter(([, yes]) => yes).length;
      const poc = make('div', 'poc-progress');
      poc.append(make('strong', '', tr(`Dev POC 资产 ${complete}/${checks.length}`, `Dev POC assets ${complete}/${checks.length}`)),
        make('small', '', checks.map(([title, yes]) => `${title}${yes ? ' ✓' : ' —'}`).join(' · ')));
      releaseCard.append(poc);
    }
    const delivery = make('details', 'delivery-details');
    delivery.id = deliveryId(item.locale);
    delivery.open = openDeliveries.has(delivery.id);
    delivery.append(make('summary', '', tr('交付与验收 · 独立证据', 'Delivery and acceptance · Separate evidence')));
    const fields = make('dl', 'delivery-fields');
    const values = [
      [tr('页面', 'Page'), item.delivery?.pageStatus],
      [tr('语音', 'Voice'), item.delivery?.voiceStatus],
      [tr('声纹索引', 'Fingerprint index'), item.delivery?.fingerprint?.status],
      [tr('设备', 'Device'), item.acceptance?.device?.status],
      [tr('现场', 'Venue'), item.acceptance?.venue?.status],
    ];
    for (const [title, value] of values) {
      const field = make('div');
      field.append(make('dt', '', title), make('dd', '', label(value)));
      if (title === tr('页面', 'Page') && item.delivery?.pageUrl) {
        field.lastChild.append(safeLink(item.delivery.pageUrl, tr('打开页面', 'Open page')));
      }
      if (title === tr('语音', 'Voice') && item.delivery?.voicePublished) {
        field.lastChild.append(make('small', 'table-note', tr('正式音轨已绑定', 'Formal audio track bound')));
      }
      fields.append(field);
    }
    if (item.delivery?.pocCandidateStatus && item.delivery.pocCandidateStatus !== 'unknown') {
      const field = make('div');
      field.append(make('dt', '', tr('POC 文字', 'POC text')), make('dd', '', label(item.delivery.pocCandidateStatus)));
      fields.append(field);
    }
    if (item.delivery?.origin === 'dev_poc_catalog') {
      for (const [title, value] of [
        [tr('POC 音频筛查', 'POC audio screening'), item.delivery.pocScreeningStatus],
        [tr('POC 音色听审', 'POC voice review'), item.delivery.pocVoiceReview === 'pending' ? 'waiting_review' : item.delivery.pocVoiceReview],
      ]) {
        const field = make('div');
        field.append(make('dt', '', title), make('dd', '', label(value)));
        fields.append(field);
      }
    }
    delivery.append(fields);
    releaseCard.append(delivery);
    releases.push(releaseCard);
    return card;
  }));
  releaseGrid.replaceChildren(...releases);
  const ready = locales.filter((item) => {
    const progress = item.layers?.['3'];
    return progress?.total > 0 && progress.complete === progress.total &&
      layerState(steps, item.locale, 3, progress) === 'complete';
  }).length;
  const complete = locales.reduce((sum, item) => sum + (item.layers?.['4']?.complete || 0), 0);
  const total = locales.reduce((sum, item) => sum + (item.layers?.['4']?.total || 0), 0);
  text('release-readiness', `${ready}/${locales.length}`);
  text('release-progress', `${complete}/${total}`);
}

function renderSteps(steps, filter) {
  const list = byId('step-list');
  const visible = (steps || []).filter((step) => filter === 'all' || step.status === filter);
  list.replaceChildren(...visible.map((step) => {
    const row = make('div', 'step-row');
    const title = make('div', 'step-title');
    title.append(make('span', 'step-id', step.id), make('strong', '', stepName(step)));
    const right = make('div', 'step-right');
    if (step.totalUnits != null) right.append(make('small', 'muted', tr(`${step.doneUnits || 0}/${step.totalUnits} 单元`, `${step.doneUnits || 0}/${step.totalUnits} units`)));
    const timing = stepTimingSummary(step);
    if (timing.length) right.append(make('small', 'step-timing', timing.join(' · ')));
    right.append(pill(step.status));
    row.append(title, right);
    return row;
  }));
  if (!visible.length) list.append(make('p', 'no-steps', tr('当前筛选没有检查点。', 'No checkpoints match this filter.')));
}

export function renderSnapshot(snapshot) {
  if (!snapshot || snapshot.schemaVersion !== 'sermon-public-tracker-snapshot-v1') {
    throw new Error('Unsupported tracker snapshot');
  }
  byId('empty').hidden = true;
  byId('dashboard').hidden = false;
  text('page-title', snapshot.pageId);
  text('page-subtitle', tr(
    `${snapshot.serviceDate || '日期未登记'} · ${snapshot.target || '目标环境未知'} · 来源与多语言制作`,
    `${snapshot.serviceDate || 'Date not recorded'} · ${snapshot.target || 'Unknown target'} · Source and multilingual production`));
  text('updated-at', tr(
    `状态更新 ${dateTime(snapshot.ledgerUpdatedAt)} · 快照 ${dateTime(snapshot.generatedAt)}`,
    `Status updated ${dateTime(snapshot.ledgerUpdatedAt)} · Snapshot ${dateTime(snapshot.generatedAt)}`));
  const report = snapshot.progress || {};
  const complete = report.complete || 0;
  const total = report.total || 0;
  const percent = total ? Math.round(100 * complete / total) : 0;
  text('metric-progress', `${percent}%`);
  text('metric-progress-count', tr(`${complete} / ${total} 检查点已记录`, `${complete} / ${total} checkpoints recorded`));
  byId('overall-fill').style.width = `${Math.max(0, Math.min(100, percent))}%`;
  text('metric-progress-note', timingCoverageNote(snapshot.timingCoverage, snapshot.steps));
  renderEta(report);
  renderBlockers(report, snapshot.steps || []);
  renderFlow(snapshot);
  renderSource(snapshot.source);
  renderShared(snapshot.sharedLayer1, snapshot.steps || []);
  renderLocales(snapshot.locales || [], snapshot.steps || []);
  renderSteps(snapshot.steps, byId('step-filter').value);
  byId('step-filter').onchange = () => renderSteps(snapshot.steps, byId('step-filter').value);
}

export function showEmpty(title, detail) {
  byId('dashboard').hidden = true;
  byId('empty').hidden = false;
  text('empty-title', title);
  text('empty-detail', detail);
}

export function showConnection(message, status = 'neutral') {
  const node = byId('connection');
  node.textContent = message;
  node.className = `connection ${status}`;
}

export { dateTime, label };
