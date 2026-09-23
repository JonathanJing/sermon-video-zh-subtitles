import './style.css';

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
const LOCALE_NAMES = { 'zh-Hans': '简体中文', ko: '한국어', es: 'Español', vi: 'Tiếng Việt' };
const STEP_NAMES = {
  'L1-01':'来源媒体、身份与人工范围','L1-02':'冻结英文文本与词级对齐','L1-03':'句界、停顿和锚点核验','L1-04':'英文人工审核与 Source Package',
  'L2-01':'目标语言策略与经文版本','L2-02':'逐单元翻译与覆盖','L2-03':'独立机器复核与语言检查','L2-04':'人工文字审核与 Candidate',
  'L3-01':'授权音色、能力与 Speech Job','L3-02':'逐单元合成','L3-03':'解码、哈希与回转写筛查','L3-04':'排程、字幕与完整音轨','L3-05':'人工全文听审','L3-06':'同视频同步审核与 Audio Package',
  'L4-01':'同语言 Release Package 与文件清单','L4-02':'构建与上传','L4-03':'线上 HTTP、哈希与 Range 核验','L4-04':'客户端文字、语言与播放核验',
};
const stepName = (step) => STEP_NAMES[step.id.split('@')[0]] || step.id;
const STATUS_CLASS = {
  complete: 'ok', passed: 'ok', pass: 'ok', http_verified: 'ok', published_http_verified: 'ok',
  updated: 'ok', running: 'active', first_seen: 'active', waiting_review: 'warn',
  blocked: 'bad', withdrawn: 'bad', failed: 'bad', fail: 'bad', hash_mismatch: 'bad',
  binding_invalid: 'bad', index_missing: 'bad',
};

const byId = (id) => document.getElementById(id);
const text = (id, value) => { byId(id).textContent = value ?? '—'; };
const name = (locale) => LOCALE_NAMES[locale] || locale;
const label = (value) => LABELS[value] || value || '未知';
const make = (tag, className, value) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (value !== undefined) node.textContent = value;
  return node;
};
const statusClass = (value) => STATUS_CLASS[value] || 'neutral';

function dateTime(value) {
  if (!value || Number.isNaN(Date.parse(value))) return '未知';
  return new Intl.DateTimeFormat('zh-CN', {
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
    return make('span', 'muted', '暂无有效链接');
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
  text('metric-video-note', source?.videoPresent ? '本周有候选视频' : '等待 source monitor');
  byId('source-page').replaceChildren(safeLink(source?.inputPageUrl, '打开输入源页面'));
  text('source-video', change === 'not_checked' ? '未检查' :
    source?.videoPresent ? '已检测到' : '未检测到');
  text('source-video-state', label(source?.videoState || source?.monitorStatus));
  const checked = source?.checkedAt ? dateTime(source.checkedAt) : '未检查';
  const age = source?.checkedAt ? Date.now() - Date.parse(source.checkedAt) : 0;
  text('source-checked', `${checked}${age > 2 * 60 * 60 * 1000 ? ' · 可能过期' : ''}`);
}

function renderShared(row, steps) {
  text('shared-detail', `${row.complete}/${row.total} 检查点 · ${row.percent}%`);
  const sharedSteps = steps.filter((step) => step.layer === 1);
  setBadge('shared-status', row.complete === row.total ? 'complete' :
    sharedSteps.some((step) => step.status === 'blocked') ? 'blocked' :
    sharedSteps.some((step) => step.status === 'waiting_review') ? 'waiting_review' : 'running');
  byId('shared-fill').style.width = `${Math.max(0, Math.min(100, row.percent || 0))}%`;
  const list = byId('shared-steps');
  list.replaceChildren(...steps.filter((step) => step.layer === 1).map((step) => {
    const item = make('li');
    item.append(make('span', `dot ${statusClass(step.status)}`), make('span', '', stepName(step)), pill(step.status));
    return item;
  }));
}

function renderLocales(locales) {
  const grid = byId('locale-grid');
  grid.replaceChildren(...locales.map((item) => {
    const card = make('article', 'locale-card panel');
    const top = make('div', 'locale-head');
    const title = make('div');
    title.append(make('span', 'eyebrow', item.locale), make('h4', '', name(item.locale)));
    top.append(title, pill(item.delivery?.pageStatus));
    card.append(top);
    for (const layer of [2, 3, 4]) {
      const row = item.layers?.[String(layer)] || { complete: 0, total: 1, percent: 0 };
      const block = make('div', 'layer-row');
      const meta = make('div', 'layer-meta');
      const layerName = { 2: '目标语言文字', 3: '音频与同步', 4: '发布与播放' }[layer];
      meta.append(make('span', '', `Layer ${layer} · ${layerName}`),
                  make('strong', '', `${row.complete}/${row.total}`));
      const track = make('div', 'progress-track small-track');
      const fill = make('div', 'progress-fill');
      fill.style.width = `${Math.max(0, Math.min(100, row.percent || 0))}%`;
      track.append(fill);
      block.append(meta, track);
      card.append(block);
    }
    if (item.delivery?.origin === 'dev_poc_catalog') {
      const checks = [
        ['文字候选', item.delivery.pocCandidateStatus === 'machine_review_pass_human_review_pending'],
        ['音轨在线', item.delivery.voiceStatus === 'poc_track_http_verified'],
        ['页面目录', item.delivery.pageStatus === 'poc_catalog_http_verified'],
        ['声纹', item.delivery.fingerprint?.status === 'http_verified'],
      ];
      const complete = checks.filter(([, yes]) => yes).length;
      const poc = make('div', 'poc-progress');
      poc.append(make('strong', '', `Dev POC 资产 ${complete}/${checks.length}`),
        make('small', '', checks.map(([title, yes]) => `${title}${yes ? ' ✓' : ' —'}`).join(' · ')));
      card.append(poc);
    }
    const footer = make('div', 'locale-foot');
    footer.append(make('span', '', `语音 ${label(item.delivery?.voiceStatus)}`),
                  make('span', '', `声纹 ${label(item.delivery?.fingerprint?.status)}`));
    if (item.delivery?.pocCandidateStatus && item.delivery.pocCandidateStatus !== 'unknown') {
      footer.append(make('span', '', `文字 ${label(item.delivery.pocCandidateStatus)}`));
    }
    if (item.delivery?.origin === 'dev_poc_catalog') {
      footer.append(make('span', '', `音频筛查 ${label(item.delivery.pocScreeningStatus)}`),
        make('span', '', `音色听审 ${item.delivery.pocVoiceReview === 'pending' ? '待审核' : label(item.delivery.pocVoiceReview)}`));
    }
    card.append(footer);
    return card;
  }));
}

function renderDelivery(locales) {
  const body = byId('delivery-body');
  body.replaceChildren(...locales.map((item) => {
    const row = make('tr');
    row.append(make('th', '', name(item.locale)));
    const page = make('td');
    page.append(pill(item.delivery?.pageStatus));
    if (item.delivery?.pageUrl) page.append(safeLink(item.delivery.pageUrl, '打开页面'));
    row.append(page);
    const voice = make('td');
    voice.append(pill(item.delivery?.voiceStatus));
    if (item.delivery?.voicePublished) voice.append(make('small', 'table-note', '正式音轨已绑定'));
    row.append(voice);
    for (const value of [item.delivery?.fingerprint?.status,
                         item.acceptance?.device?.status, item.acceptance?.venue?.status]) {
      const cell = make('td');
      cell.append(pill(value));
      row.append(cell);
    }
    return row;
  }));
}

function renderSteps(steps, filter) {
  const list = byId('step-list');
  const visible = (steps || []).filter((step) => filter === 'all' || step.status === filter);
  list.replaceChildren(...visible.map((step) => {
    const row = make('div', 'step-row');
    const title = make('div', 'step-title');
    title.append(make('span', 'step-id', step.id), make('strong', '', stepName(step)));
    const right = make('div', 'step-right');
    if (step.totalUnits != null) right.append(make('small', 'muted', `${step.doneUnits || 0}/${step.totalUnits} 单元`));
    const timing = step.timing;
    if (timing?.executionAttempts) {
      const seconds = Math.round(timing.measuredExecutionSeconds || 0);
      right.append(make('small', 'muted', `实测 ${Math.floor(seconds / 60)}分${seconds % 60}秒 · ${timing.executionAttempts} 次${timing.failedExecutionAttempts ? ` · 失败 ${timing.failedExecutionAttempts}` : ''}`));
    }
    if (timing?.openExecution) right.append(make('small', 'muted', '存在未结束执行记录'));
    if (timing?.operatorReviewWaitSeconds != null) {
      right.append(make('small', 'muted', `审核等待 ${Math.round(timing.operatorReviewWaitSeconds / 60)} 分钟`));
    }
    if (timing?.openReviewWait) right.append(make('small', 'muted', '审核等待中'));
    right.append(pill(step.status));
    row.append(title, right);
    return row;
  }));
  if (!visible.length) list.append(make('p', 'no-steps', '当前筛选没有检查点。'));
}

export function renderSnapshot(snapshot) {
  if (!snapshot || snapshot.schemaVersion !== 'sermon-public-tracker-snapshot-v1') {
    throw new Error('Unsupported tracker snapshot');
  }
  byId('empty').hidden = true;
  byId('dashboard').hidden = false;
  text('page-title', snapshot.pageId);
  text('page-subtitle', `${snapshot.serviceDate || '日期未登记'} · ${snapshot.target || '目标环境未知'} · 来源与多语言制作`);
  text('updated-at', `状态更新 ${dateTime(snapshot.ledgerUpdatedAt)} · 快照 ${dateTime(snapshot.generatedAt)}`);
  const report = snapshot.progress || {};
  text('metric-progress', `${report.complete || 0} / ${report.total || 0}`);
  text('metric-progress-note', '完成数只表示检查点');
  const timingCoverage = snapshot.timingCoverage || {};
  if (timingCoverage.measuredStepCount) {
    text('metric-progress-note', `完成数只表示检查点 · ${timingCoverage.measuredStepCount} 个步骤有实测耗时`);
  }
  text('metric-eta', report.earliestContinuousEta ? dateTime(report.earliestContinuousEta) : '未知');
  text('metric-blockers', report.blockerCount || 0);
  renderSource(snapshot.source);
  renderShared(snapshot.sharedLayer1, snapshot.steps || []);
  renderLocales(snapshot.locales || []);
  renderDelivery(snapshot.locales || []);
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
