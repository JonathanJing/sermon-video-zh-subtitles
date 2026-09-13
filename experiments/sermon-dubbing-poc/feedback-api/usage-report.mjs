import { mkdir, writeFile } from 'node:fs/promises';
import { resolve, join } from 'node:path';

const DAY = 86_400_000;
export const TIME_ZONE = 'America/Los_Angeles';
export const ACTIONS = Object.freeze({
  app_open: '打开应用', page_heartbeat: '页面可见心跳', page_visible: '页面变为可见', page_hidden: '页面隐藏',
  play_click: '点击播放', pause_click: '点击暂停', back_5_click: '后退 5 秒', forward_5_click: '前进 5 秒',
  download_click: '点击下载', week_select: '切换周次', track_select: '切换音轨', theme_toggle: '切换主题', source_link: '打开原视频',
  tab_listen: '切换到收听', tab_transcript: '切换到全文', tab_production: '切换到制作进度', tab_voices: '切换到音色库',
  outline_open: '打开大纲', outline_close: '关闭大纲', transcript_seek: '从全文跳转', progress_seek: '拖动进度', time_jump: '跳转指定时间',
  nudge_back_1_click: '同步后调 1 秒', nudge_back_quarter_click: '同步后调 0.25 秒', nudge_forward_quarter_click: '同步前调 0.25 秒', nudge_forward_1_click: '同步前调 1 秒',
  voice_reference_play: '试听英文原声', voice_reference_pause: '暂停英文原声', voice_chinese_play: '试听中文音色', voice_chinese_pause: '暂停中文音色', probe_text_open: '展开音色试听文稿',
  feedback_up: '点赞', feedback_down: '点踩', feedback_point: '标记问题位置', feedback_details: '展开反馈', feedback_submit: '提交反馈', feedback_close: '关闭反馈',
  feedback_retract_vote: '撤回评价', feedback_retract_issue: '撤回问题', unknown: '未知动作',
  seek_undo: '撤销跳转', position_restore: '继续上次收听', position_restart: '从头开始', transcript_current: '定位当前字幕',
  more_open: '展开更多功能', precision_open: '展开精细调整', feedback_section_open: '展开反馈区域',
});
const PANELS = Object.freeze({ listen: '收听', transcript: '全文', production: '制作进度', voices: '音色库', outline: '大纲', feedback: '反馈', unknown: '未知页面' });
const SPEAKERS = Object.freeze({ eric_pilot: 'Eric Geiger', eric_geiger: 'Eric Geiger', jared_kirkwood: 'Jared Kirkwood', christine_caine: 'Christine Caine', doug_fields: 'Doug Fields', kenton_beshore: 'Kenton Beshore', steve_bang_lee: 'Steve Bang Lee' });
const localParts = new Intl.DateTimeFormat('en-CA', { timeZone: TIME_ZONE, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', hourCycle: 'h23' });
const displayTime = new Intl.DateTimeFormat('zh-CN', { timeZone: TIME_ZONE, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23', timeZoneName: 'short' });

export function epoch(value) {
  if (typeof value?.toMillis === 'function') return value.toMillis();
  if (typeof value?.toDate === 'function') return value.toDate().getTime();
  return value instanceof Date ? value.getTime() : typeof value === 'number' ? value : NaN;
}
function localDateHour(at) {
  const parts = Object.fromEntries(localParts.formatToParts(at).map((part) => [part.type, part.value]));
  return { day: `${parts.year}-${parts.month}-${parts.day}`, hour: Number(parts.hour) };
}
function validDay(day) {
  return typeof day === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(day) && Number.isFinite(Date.parse(day)) && new Date(day).toISOString().slice(0, 10) === day;
}
export function validateRange(from, to) {
  if (!validDay(from) || !validDay(to) || from > to || Date.parse(to) - Date.parse(from) > 30 * DAY) throw new Error('日期必须有效且 --from ≤ --to，最多连续 31 天（含首尾）。');
  return { from, to };
}
export function parseUsageArgs(args) {
  const options = {};
  for (let i = 0; i < args.length; i += 2) {
    const flag = args[i];
    if (!['--from', '--to', '--out'].includes(flag) || !args[i + 1] || args[i + 1].startsWith('--') || options[flag.slice(2)] !== undefined) throw new Error('Usage: node admin.mjs usage --from YYYY-MM-DD --to YYYY-MM-DD --out NEW_DIRECTORY');
    options[flag.slice(2)] = args[i + 1];
  }
  validateRange(options.from, options.to);
  if (!options.out) throw new Error('--out 必须是尚不存在的私有本地目录。');
  return options;
}

/** ADC caller supplies Firestore. The server validates each event's LA day.
 * Paginate one indexed collection, with a hard cap; never return document IDs.
 */
export async function fetchUsageSessions(db, { from, to, now = Date.now(), pageSize = 500, maxDocuments = 20000 }) {
  validateRange(from, to);
  if (!Number.isInteger(pageSize) || pageSize < 1 || pageSize > 1000 || !Number.isInteger(maxDocuments) || maxDocuments < 1 || maxDocuments > 100000) throw new Error('Invalid usage query limits');
  const base = db.collection('usageSessions').where('day', '>=', from).where('day', '<=', to).orderBy('day');
  const records = [];
  let cursor, documentsRead = 0, truncated = false;
  while (true) {
    const limit = Math.min(pageSize, maxDocuments - documentsRead + 1);
    let query = base.limit(limit);
    if (cursor) query = query.startAfter(cursor);
    const snapshot = await query.get();
    for (const doc of snapshot.docs) {
      documentsRead += 1;
      if (documentsRead > maxDocuments) { truncated = true; break; }
      records.push(doc.data());
    }
    if (truncated || snapshot.docs.length < limit || !snapshot.docs.length) break;
    cursor = snapshot.docs.at(-1);
  }
  return { records, query: { documentsRead, maxDocuments, truncated, retentionCutoff: new Date(now - 30 * DAY).toISOString() } };
}

function integer(value) { return Number.isSafeInteger(value) && value >= 0 ? value : 0; }
function known(map, key, fallback = 'unknown') { return typeof key === 'string' && Object.hasOwn(map, key) ? key : fallback; }
function add(map, key, session) {
  if (!map.has(key)) map.set(key, { events: 0, sessions: new Set() });
  const row = map.get(key); row.events += 1; row.sessions.add(session);
}
function counted(map, labels) {
  return [...map].map(([key, row]) => ({ key, label: labels[key] || key, events: row.events, sessions: row.sessions.size })).sort((a, b) => b.sessions - a.sessions || b.events - a.events || a.key.localeCompare(b.key));
}

/** Whitelist-derived output only: no session IDs, browser hashes or free text. */
export function summarizeUsage(records, { from, to, now = Date.now(), query = null }) {
  validateRange(from, to);
  if (!Number.isFinite(now)) throw new Error('Invalid report clock');
  const cutoff = now - 30 * DAY;
  const daily = new Map();
  for (let day = Date.parse(from); day <= Date.parse(to); day += DAY) daily.set(new Date(day).toISOString().slice(0, 10), { browsers: new Set(), sessions: 0, events: 0, appOpens: 0 });
  const actions = new Map(), panels = new Map(), voices = new Map(), hours = Array.from({ length: 24 }, () => new Set());
  const totals = { sessions: 0, events: 0, appOpens: 0, browserDays: 0, sessionsWithoutBrowserId: 0, droppedEvents: 0, sessionsWithDroppedEvents: 0, cappedSessions: 0, ignoredRecords: 0, ignoredEvents: 0 };
  const prepared = [];
  for (const record of records) {
    const received = epoch(record?.firstReceivedAt);
    if (!daily.has(record?.day) || !Number.isFinite(received) || received < cutoff || received > now || !Array.isArray(record.events)) { totals.ignoredRecords += 1; continue; }
    const events = [];
    for (const event of record.events) {
      const at = epoch(event?.at);
      if (!Number.isFinite(at) || at < cutoff || at > now || localDateHour(at).day !== record.day) { totals.ignoredEvents += 1; continue; }
      events.push({ at: new Date(at).toISOString(), sequence: integer(event.sequence), localTime: displayTime.format(at), action: known(ACTIONS, event.action), panel: known(PANELS, event.panel),
        week: validDay(event.week) ? event.week : null,
        positionSeconds: typeof event.positionSeconds === 'number' && Number.isFinite(event.positionSeconds) && event.positionSeconds >= 0 && event.positionSeconds <= 21600 ? Math.round(event.positionSeconds) : null,
        speaker: SPEAKERS[known(SPEAKERS, event.speakerId, '')] || null });
    }
    events.sort((a, b) => a.at.localeCompare(b.at) || a.sequence - b.sequence);
    prepared.push({ day: record.day, browserHash: typeof record.dailyBrowserKey === 'string' && /^[a-f0-9]{64}$/.test(record.dailyBrowserKey) ? record.dailyBrowserKey : null,
      sortAt: events[0]?.at || new Date(received).toISOString(), droppedEvents: integer(record.droppedEvents), capped: integer(record.totalEvents) >= 500 || record.events.length >= 500, events });
  }
  prepared.sort((a, b) => a.sortAt.localeCompare(b.sortAt) || a.day.localeCompare(b.day));
  const funnel = { appOpenSessions: 0, appOpenAndPlaySessions: 0, appOpenAndPlayAndDownloadSessions: 0 };
  const sessions = prepared.map((session, index) => {
    const number = index + 1, day = daily.get(session.day), used = new Set();
    day.sessions += 1; totals.sessions += 1;
    if (session.browserHash) day.browsers.add(session.browserHash); else totals.sessionsWithoutBrowserId += 1;
    totals.droppedEvents += session.droppedEvents;
    if (session.droppedEvents) totals.sessionsWithDroppedEvents += 1;
    if (session.capped) totals.cappedSessions += 1;
    for (const event of session.events) {
      totals.events += 1; day.events += 1;
      if (event.action === 'app_open') { totals.appOpens += 1; day.appOpens += 1; }
      used.add(event.action);
      add(actions, event.action, number); add(panels, event.panel, number);
      if (event.speaker) add(voices, event.speaker, number);
      const local = localDateHour(Date.parse(event.at));
      hours[local.hour].add(`${local.day}:${number}`);
    }
    if (used.has('app_open')) {
      funnel.appOpenSessions += 1;
      if (used.has('play_click')) {
        funnel.appOpenAndPlaySessions += 1;
        if (used.has('download_click')) funnel.appOpenAndPlayAndDownloadSessions += 1;
      }
    }
    return { number, day: session.day, firstEventAt: session.events[0]?.at || null, lastEventAt: session.events.at(-1)?.at || null, droppedEvents: session.droppedEvents, capped: session.capped, events: session.events };
  });
  const days = [...daily].map(([day, row]) => ({ day, anonymousBrowsers: row.browsers.size, sessions: row.sessions, events: row.events, appOpens: row.appOpens }));
  totals.browserDays = days.reduce((sum, day) => sum + day.anonymousBrowsers, 0);
  return { schemaVersion: 'sermon-private-usage-report-v1', generatedAt: new Date(now).toISOString(), timeZone: TIME_ZONE, range: { from, to }, retentionDays: 30,
    retentionCutoff: new Date(cutoff).toISOString(), query: query ? { documentsRead: integer(query.documentsRead), maxDocuments: integer(query.maxDocuments), truncated: query.truncated === true } : null,
    definitions: { anonymousBrowsers: '同一天匿名浏览器标识去重；不是人数。标识每日轮换，跨日无法去重。', browserDays: '每日匿名浏览器数相加，单位为浏览器日；不是月度 UV。',
      daily: '按事件所属洛杉矶日期统计，由服务端校验；匿名浏览器按每日随机标识去重。小时按事件发生时刻归属。30 天保留范围以服务端首次收到记录的时间筛选。', hourly: '每个日期、小时内，同一会话多次事件只计一次；再按当地小时跨日相加。心跳仅表示页面可见，不代表人在操作。夏令时回拨重复小时合并。',
      funnel: '同一会话包含打开、播放点击、下载点击的逐层交集；不要求先后顺序。点击不等于播放成功或下载完成。',
      coverage: '仅展示最近 30 天仍保留且已收到的记录。关闭统计、浏览器禁用或关闭前未送达的使用不会出现，不能代表全部流量。',
      limits: '每会话最多保留 500 个事件，达到上限后客户端停止上报；停止后的事件数量未知，不能用 droppedEvents 推算。已记录的丢弃事件无法重建。查询有文档上限，截断时所有指标仅为读取部分。',
      privacy: '私有本地报告；不含原始浏览器哈希、令牌、数据库文档 ID 或反馈正文。请勿上传公开站点。' },
    totals, daily: days, hourly: hours.map((set, hour) => ({ hour, activeSessionHours: set.size })), actions: counted(actions, ACTIONS), panels: counted(panels, PANELS), voices: counted(voices, {}), funnel, sessions };
}

export function escapeHtml(value) { return String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]); }
function table(headers, rows) { return `<div class="scroll"><table><thead><tr>${headers.map((h) => `<th>${escapeHtml(h)}</th>`).join('')}</tr></thead><tbody>${rows.map((row) => `<tr>${row.map((cell) => `<td>${escapeHtml(cell)}</td>`).join('')}</tr>`).join('') || `<tr><td colspan="${headers.length}">无记录</td></tr>`}</tbody></table></div>`; }
function bars(rows) {
  const max = Math.max(1, ...rows.map((row) => row.activeSessionHours));
  return `<div class="hours">${rows.map((row) => `<div><span>${row.activeSessionHours}</span><i style="height:${Math.round(row.activeSessionHours / max * 120)}px"></i><small>${String(row.hour).padStart(2, '0')}</small></div>`).join('')}</div>`;
}
export function renderUsageHtml(report) {
  const esc = escapeHtml;
  const counts = (rows) => table(['类别', '事件数', '使用该类别的会话数'], rows.map((row) => [row.label, row.events, row.sessions]));
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; base-uri 'none'; form-action 'none'"><title>私有应用使用报告</title><style>
  *{box-sizing:border-box}body{margin:0;background:#f4f6fa;color:#172033;font:16px/1.6 system-ui,sans-serif}main{max-width:1160px;margin:auto;padding:36px 22px}h1{font-size:30px;line-height:1.25}h2{margin-top:36px;font-size:21px}p{color:#4a566b}.private{font-weight:700;color:#784516}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px}.card{padding:20px;background:white;border:1px solid #dce2ec;border-radius:10px}.card b{display:block;font-size:30px}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;background:white}th,td{text-align:left;padding:10px 12px;border-bottom:1px solid #e1e5ed;vertical-align:top}th{background:#e8edf6;white-space:nowrap}details{margin:12px 0;padding:12px;background:white;border:1px solid #dce2ec;border-radius:8px}summary{cursor:pointer;font-weight:600}.notice{padding:14px;border-left:4px solid #b6791a;background:#fff4db}.hours{height:190px;display:flex;align-items:end;gap:5px;overflow:auto}.hours>div{flex:1;min-width:24px;text-align:center;font-size:12px}.hours i{display:block;background:#3566a7;min-height:1px}.hours small{display:block}.muted{font-size:14px}footer{margin-top:40px;border-top:1px solid #cbd3df;padding-top:18px}@media print{details{break-inside:avoid}.scroll{overflow:visible}body{background:white}}
  </style></head><body><main><div class="private">私有 · 仅供本地运营查看</div><h1>应用使用报告</h1><p>${esc(report.range.from)} 至 ${esc(report.range.to)} · 洛杉矶时间<br>生成于 ${esc(displayTime.format(Date.parse(report.generatedAt)))}</p>
  ${report.query?.truncated ? '<p class="notice">查询达到文档上限，结果已截断；以下全部指标只代表读取到的部分。</p>' : ''}
  ${report.totals.sessions === 0 ? '<p class="notice">所选日期没有可用的已接收记录。这不表示没有人使用应用；统计尚未启用、未送达或已过保留期也会导致空白。</p>' : ''}
  <div class="cards">${[['匿名浏览器日', report.totals.browserDays], ['会话', report.totals.sessions], ['打开应用次数', report.totals.appOpens], ['保留事件', report.totals.events]].map(([label, value]) => `<div class="card">${esc(label)}<b>${esc(value)}</b></div>`).join('')}</div>
  <p class="muted">${esc(report.definitions.anonymousBrowsers)} ${esc(report.definitions.browserDays)}</p>
  <h2>每日访问</h2>${table(['日期', '匿名浏览器', '会话', '打开应用', '保留事件'], report.daily.map((day) => [day.day, day.anonymousBrowsers, day.sessions, day.appOpens, day.events]))}<p class="muted">${esc(report.definitions.daily)} 有 ${esc(report.totals.sessionsWithoutBrowserId)} 个会话缺少浏览器标识，仍计入会话与事件。</p>
  <h2>什么时间在用</h2>${bars(report.hourly)}<p class="muted">${esc(report.definitions.hourly)}</p>
  <h2>使用了哪些功能</h2>${counts(report.actions)}<h2>查看了哪些页面</h2>${counts(report.panels)}<h2>讲员音色使用</h2>${counts(report.voices)}
  <h2>打开 → 播放点击 → 下载点击</h2>${table(['同一会话内的动作组合', '会话数'], [['包含打开应用', report.funnel.appOpenSessions], ['同时包含打开和播放点击', report.funnel.appOpenAndPlaySessions], ['同时包含打开、播放点击和下载点击', report.funnel.appOpenAndPlayAndDownloadSessions]])}<p class="muted">${esc(report.definitions.funnel)}</p>
  <h2>匿名会话时间线</h2><p>编号仅在本报告内有意义；按首个保留事件排序。展开可查看事件先后顺序。</p>${report.sessions.map((session) => `<details><summary>会话 ${session.number} · ${esc(session.day)} · ${session.events.length} 个保留事件${session.droppedEvents ? ` · 丢弃 ${session.droppedEvents}` : ''}</summary>${table(['洛杉矶时间', '动作', '页面', '周次', '播放位置（秒）', '讲员'], session.events.map((event) => [event.localTime, ACTIONS[event.action], PANELS[event.panel], event.week || '—', event.positionSeconds ?? '—', event.speaker || '—']))}</details>`).join('') || '<p>无可展示的会话。</p>'}
  <footer><h2>数据边界</h2><p>${esc(report.definitions.coverage)}</p><p>${esc(report.definitions.limits)}</p><p>达到事件上限的会话：${esc(report.totals.cappedSessions)}。已记录的丢弃事件：${esc(report.totals.droppedEvents)}；涉及会话：${esc(report.totals.sessionsWithDroppedEvents)}。过滤过期或无效记录：${esc(report.totals.ignoredRecords)}；过滤时间无效、日期不符或不在区间的事件：${esc(report.totals.ignoredEvents)}。</p><p>${esc(report.definitions.privacy)}</p></footer></main></body></html>`;
}

export async function writeUsageReport(out, report) {
  const directory = resolve(out);
  // Exclusive directory creation prevents accidental replacement of a prior report.
  await mkdir(directory, { mode: 0o700 });
  await writeFile(join(directory, 'summary.json'), JSON.stringify(report, null, 2) + '\n', { flag: 'wx', mode: 0o600 });
  await writeFile(join(directory, 'index.html'), renderUsageHtml(report), { flag: 'wx', mode: 0o600 });
  return { directory, sessions: report.totals.sessions, events: report.totals.events, truncated: report.query?.truncated === true };
}
