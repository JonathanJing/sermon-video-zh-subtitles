import { mkdir, writeFile } from 'node:fs/promises';
import { resolve, join } from 'node:path';
import { epoch, escapeHtml, parseUsageArgs, validateRange, TIME_ZONE } from './usage-report.mjs';
import { validListeningDay, INTERFACE_LOCALES } from './listening-core.mjs';

const DAY = 86400000;
export const parseListeningArgs = parseUsageArgs;
export async function fetchListeningSessions(db, { from, to, now = Date.now(), pageSize = 500, maxDocuments = 20000, collection = 'languageListeningSessions30d' }) {
  validateRange(from, to);
  if (!Number.isInteger(pageSize) || pageSize < 1 || pageSize > 1000 || !Number.isInteger(maxDocuments) || maxDocuments < 1 || maxDocuments > 100000) throw new Error('Invalid listening query limits');
  const base = db.collection(collection).where('day', '>=', from).where('day', '<=', to).orderBy('day');
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
export const fetchInterfaceUsageSessions = (db, options) => fetchListeningSessions(db, { ...options, collection: 'interfaceUsageSessions30d' });
const localeNames = { vi: '越南语', 'zh-Hans': '中文', ko: '韩语', es: '西班牙语', en: '英语', unknown: '语言未标注' };
const newRow = () => ({ sessions: 0, qualifiedSessions: 0, listenedSeconds: 0, completedSessions: 0, qualifiedSessionsWithoutClientId: 0, clients: new Set() });
function count(row, record, qualifiedDevices) {
  row.sessions += 1; row.listenedSeconds += record.listenedSeconds;
  if (record.listenedSeconds >= 30) {
    row.qualifiedSessions += 1;
    if (record.coveredSeconds / record.durationSeconds >= .9) row.completedSessions += 1;
    if (!clientKey(record)) row.qualifiedSessionsWithoutClientId += 1;
  }
  if (qualifiedDevices.has(audienceKey(record))) row.clients.add(clientKey(record));
}
const clientKey = (r) => typeof r.dailyClientKey === 'string' && /^[a-f0-9]{64}$/.test(r.dailyClientKey) ? `${r.day}:${r.platform}:${r.dailyClientKey}` : null;
const audienceKey = (r) => clientKey(r) ? `${clientKey(r)}:${r.pageId}:${r.audioSha256}` : null;
function publicRow(row) {
  return { sessions: row.sessions, qualifiedSessions: row.qualifiedSessions, deviceDays: row.clients.size,
    listenedSeconds: Math.round(row.listenedSeconds * 1000) / 1000,
    completedSessions: row.completedSessions, completionRate: row.qualifiedSessions ? row.completedSessions / row.qualifiedSessions : null,
    qualifiedSessionsWithoutClientId: row.qualifiedSessionsWithoutClientId };
}
/** Only aggregate whitelist fields leave this function; no identifiers or hashes. */
export function summarizeListening(records, { from, to, now = Date.now(), query = null, interfaceRecords = [], interfaceQuery = null }) {
  validateRange(from, to);
  if (!Number.isFinite(now)) throw new Error('Invalid report clock');
  const groups = new Map(), daily = new Map(), weeks = new Map(), crossTab = new Map(), total = newRow();
  const accepted = [];
  let ignoredRecords = 0;
  for (const record of records) {
    if (!record || record.schemaVersion !== 1 || record.day < from || record.day > to || !validListeningDay(record.day) || !['web', 'ios'].includes(record.platform) || !Number.isFinite(record.listenedSeconds) || record.listenedSeconds < 0 || !Number.isFinite(record.coveredSeconds) || record.coveredSeconds < 0 || !Number.isFinite(record.durationSeconds) || record.durationSeconds <= 0 || record.coveredSeconds > record.durationSeconds + .01 || !Number.isFinite(epoch(record.updatedAt)) || epoch(record.updatedAt) < now - 30 * DAY || epoch(record.updatedAt) > now || !Number.isFinite(epoch(record.expiresAt)) || epoch(record.expiresAt) <= now) {
      ignoredRecords += 1; continue;
    }
    accepted.push(record);
  }
  const durations = new Map();
  for (const r of accepted) if (audienceKey(r)) durations.set(audienceKey(r), (durations.get(audienceKey(r)) || 0) + r.listenedSeconds);
  const qualifiedDevices = new Set([...durations].filter(([, duration]) => duration >= 30).map(([key]) => key));
  for (const record of accepted) {
    const interfaceLocale = INTERFACE_LOCALES.includes(record.interfaceLocale) ? record.interfaceLocale : 'unknown';
    const contentLocale = INTERFACE_LOCALES.includes(record.contentLocale) ? record.contentLocale : 'unknown';
    const audioLocale = Object.hasOwn(localeNames, record.audioLocale) ? record.audioLocale : 'unknown';
    const groupKey = `${contentLocale}:${audioLocale}:${record.platform}`;
    const crossKey = `${interfaceLocale}:${groupKey}`;
    const dayKey = `${record.day}:${groupKey}`;
    const safeWeek = typeof record.week === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(record.week) ? record.week : 'unknown';
    const safePage = typeof record.pageId === 'string' && /^[A-Za-z0-9_-]{1,160}$/.test(record.pageId) ? record.pageId : null;
    const weekKey = `${safeWeek}:${safePage}:${groupKey}`;
    if (!groups.has(groupKey)) groups.set(groupKey, { contentLocale, audioLocale, platform: record.platform, row: newRow() });
    if (!daily.has(dayKey)) daily.set(dayKey, { day: record.day, contentLocale, audioLocale, platform: record.platform, row: newRow() });
    if (!weeks.has(weekKey)) weeks.set(weekKey, { week: safeWeek, pageId: safePage, contentLocale, audioLocale, platform: record.platform, row: newRow() });
    if (!crossTab.has(crossKey)) crossTab.set(crossKey, { interfaceLocale, contentLocale, audioLocale, platform: record.platform, row: newRow() });
    for (const row of [crossTab.get(crossKey).row, total, groups.get(groupKey).row, daily.get(dayKey).row, weeks.get(weekKey).row]) count(row, record, qualifiedDevices);
  }
  const flatten = (map) => [...map].sort(([a], [b]) => a.localeCompare(b)).map(([, { row, ...rest }]) => ({ ...rest, ...publicRow(row) }));
  const interfaceUsage = summarizeInterfaceUsage(interfaceRecords, { from, to, now, query: interfaceQuery });
  return { schemaVersion: 'sermon-private-listening-report-v1', generatedAt: new Date(now).toISOString(), timeZone: TIME_ZONE, range: { from, to }, retentionDays: 30,
    query: query ? { documentsRead: query.documentsRead, maxDocuments: query.maxDocuments, truncated: query.truncated === true } : null,
    definitions: {
      qualifiedSessions: '累计实际播放满 30 秒的收听片段会话；切换界面或内容语言会开始新片段，点击播放不计作收听。',
      deviceDays: '先按同日、平台、匿名设备、页面及音轨累计满 30 秒（可合并界面切换片段），再去重设备。同一洛杉矶日内、同一平台的匿名浏览器或设备去重，跨日相加为设备日；不是人数或跨日独立设备。不同语言的设备数可能重叠，分组不可直接相加。',
      listenedSeconds: '实际播放的累计时长，包括重复收听；暂停、缓冲和跳转不应累加。全部已接收会话均计时。',
      completionRate: '满 30 秒的会话中，音频不重复覆盖达到 90% 的比例；按会话计算。',
      missingClient: '没有可用每日匿名标识的会话仍计入次数和时长，单列未识别会话，不推算人数。',
      source: '音轨语言由服务端发布目录的音轨身份决定；界面语言及页面语言由客户端分别上报，页面语言须在该页面的已发布语言目录内。没有历史回填。',
      crossTab: '交叉表统计达到当日同页面同音轨 30 秒门槛的匿名设备使用过的界面；不要求在每个界面分别满 30 秒，因此不同界面行可能包含同一设备。',
      coverage: '只包含启用统计且成功送达的最近 30 天数据；丢失上报、关闭统计、旧客户端不在统计内。后台过期删除可能延迟，报告仍排除已过期记录。',
      privacy: '私有运营报告；不输出设备标识、哈希、令牌或会话文档 ID。请勿上传公开网站。',
    }, totals: { ...publicRow(total), ignoredRecords }, groups: flatten(groups), daily: flatten(daily), weeks: flatten(weeks), crossTab: flatten(crossTab), interfaceUsage };
}
export function renderListeningHtml(report) {
  const esc = escapeHtml;
  const table = (rows, includeDay = false, includeWeek = false) => `<div class="scroll"><table><thead><tr>${[...(includeDay ? ['日期'] : []), ...(includeWeek ? ['主日', '页面'] : []), '页面语言', '音频语言', '平台', '收听设备日', '收听次数（≥30秒）', '收听小时', '完播率', '缺少标识的收听会话'].map((h) => `<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.map((r) => `<tr>${[...(includeDay ? [r.day] : []), ...(includeWeek ? [r.week, r.pageId || '—'] : []), localeNames[r.contentLocale], localeNames[r.audioLocale], r.platform === 'ios' ? 'iOS' : '网页', r.deviceDays, r.qualifiedSessions, (r.listenedSeconds / 3600).toFixed(2), r.completionRate === null ? '—' : `${(r.completionRate * 100).toFixed(1)}%`, r.qualifiedSessionsWithoutClientId].map((v) => `<td>${esc(v)}</td>`).join('')}</tr>`).join('') || '<tr><td>尚无已收到的收听记录</td></tr>'}</tbody></table></div>`;
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"><title>语言收听统计 · 私有后台</title><style>body{font:16px/1.6 system-ui;background:#f5f7fa;color:#172033;margin:0}main{max-width:1200px;margin:auto;padding:32px 24px}h1{font-size:30px}h2{margin-top:32px}table{border-collapse:collapse;background:white;width:100%}th,td{text-align:left;padding:12px;border-bottom:1px solid #dce2ec}th{white-space:nowrap;background:#e7edf4}.scroll{overflow:auto}.note{padding:16px;background:#fff3d6}.cards{display:flex;flex-wrap:wrap;gap:16px}.card{padding:20px;background:white;border:1px solid #dce2ec;min-width:160px}.card b{display:block;font-size:28px}footer{margin-top:36px;border-top:1px solid #ccd4de}</style></head><body><main><p>私有后台 · 同行</p><h1>各语言收听统计</h1><p>${esc(report.range.from)} 至 ${esc(report.range.to)} · 洛杉矶时间</p>${(report.query?.truncated || report.interfaceUsage.query?.truncated) ? '<p class="note">查询已达到上限，所有指标仅代表读到的部分。</p>' : ''}${report.totals.sessions ? '' : '<p class="note">尚无可用记录。这不表示无人收听；新客户端上报后才开始累计。</p>'}<div class="cards">${[['收听设备日', report.totals.deviceDays], ['收听次数（≥30秒）', report.totals.qualifiedSessions], ['收听小时', (report.totals.listenedSeconds / 3600).toFixed(2)]].map(([label, value]) => `<div class="card">${esc(label)}<b>${esc(value)}</b></div>`).join('')}</div><h2>界面语言访问（无需播放）</h2>${renderInterfaceTable(report.interfaceUsage.groups)}<p>访问会话数不是人数；界面切换可产生多个会话。同日同平台按匿名设备去重，跨日为设备日。</p><h2>每日界面访问</h2>${renderInterfaceTable(report.interfaceUsage.daily, true)}<h2>页面及音频语言与平台</h2>${table(report.groups)}<h2>界面语言与收听内容</h2>${renderCrossTable(report.crossTab)}<h2>每日收听</h2>${table(report.daily, true)}<h2>各周内容</h2>${table(report.weeks, false, true)}<footer><h2>统计口径</h2>${Object.values(report.definitions).map((v) => `<p>${esc(v)}</p>`).join('')}<p>过滤无效或过期记录：${esc(report.totals.ignoredRecords)}</p></footer></main></body></html>`;
}
export async function writeListeningReport(out, report) {
  const directory = resolve(out);
  await mkdir(directory, { mode: 0o700 });
  await writeFile(join(directory, 'summary.json'), JSON.stringify(report, null, 2) + '\n', { flag: 'wx', mode: 0o600 });
  await writeFile(join(directory, 'index.html'), renderListeningHtml(report), { flag: 'wx', mode: 0o600 });
  return { directory, qualifiedSessions: report.totals.qualifiedSessions, deviceDays: report.totals.deviceDays, truncated: report.query?.truncated === true || report.interfaceUsage.query?.truncated === true };
}

function summarizeInterfaceUsage(records, { from, to, now, query }) {
  const groups = new Map(), daily = new Map(), clients = new Set();
  let sessions = 0, sessionsWithoutClientId = 0, ignoredRecords = 0;
  for (const record of records) {
    if (!record || record.schemaVersion !== 1 || !validListeningDay(record.day) || record.day < from || record.day > to || !INTERFACE_LOCALES.includes(record.interfaceLocale) || !['web', 'ios'].includes(record.platform) || !Number.isFinite(epoch(record.updatedAt)) || epoch(record.updatedAt) < now - 30 * DAY || epoch(record.updatedAt) > now || !Number.isFinite(epoch(record.expiresAt)) || epoch(record.expiresAt) <= now) { ignoredRecords++; continue; }
    sessions++;
    const key = `${record.interfaceLocale}:${record.platform}`;
    const dayKey = `${record.day}:${key}`;
    if (!groups.has(key)) groups.set(key, { interfaceLocale: record.interfaceLocale, platform: record.platform, sessions: 0, sessionsWithoutClientId: 0, clients: new Set() });
    if (!daily.has(dayKey)) daily.set(dayKey, { day: record.day, interfaceLocale: record.interfaceLocale, platform: record.platform, sessions: 0, sessionsWithoutClientId: 0, clients: new Set() });
    const client = clientKey(record);
    if (client) clients.add(client); else sessionsWithoutClientId++;
    for (const row of [groups.get(key), daily.get(dayKey)]) { row.sessions++; if (client) row.clients.add(client); else row.sessionsWithoutClientId++; }
  }
  const flatten = (map) => [...map].sort(([a], [b]) => a.localeCompare(b)).map(([, { clients, ...rest }]) => ({ ...rest, deviceDays: clients.size }));
  return { totals: { sessions, deviceDays: clients.size, sessionsWithoutClientId, ignoredRecords }, groups: flatten(groups), daily: flatten(daily), query: query ? { documentsRead: query.documentsRead, maxDocuments: query.maxDocuments, truncated: query.truncated === true } : null };
}
function renderInterfaceTable(rows, daily = false) {
  return `<div class="scroll"><table><tr>${daily ? '<th>日期</th>' : ''}<th>界面语言</th><th>平台</th><th>访问会话</th><th>设备日</th><th>缺少匿名标识</th></tr>${rows.map((r) => `<tr>${[...(daily ? [r.day] : []), localeNames[r.interfaceLocale], r.platform, r.sessions, r.deviceDays, r.sessionsWithoutClientId].map((v) => `<td>${escapeHtml(v)}</td>`).join('')}</tr>`).join('') || '<tr><td>暂无界面访问记录</td></tr>'}</table></div>`;
}
function renderCrossTable(rows) {
  return `<div class="scroll"><table><tr><th>界面语言</th><th>页面语言</th><th>音频语言</th><th>平台</th><th>收听设备日</th><th>收听小时</th></tr>${rows.map((r) => `<tr>${[localeNames[r.interfaceLocale], localeNames[r.contentLocale], localeNames[r.audioLocale], r.platform, r.deviceDays, (r.listenedSeconds / 3600).toFixed(2)].map((v) => `<td>${escapeHtml(v)}</td>`).join('')}</tr>`).join('') || '<tr><td>暂无交叉统计记录</td></tr>'}</table></div>`;
}
