import { mkdir, writeFile } from 'node:fs/promises';
import { resolve, join } from 'node:path';
import { epoch, escapeHtml, validateRange, TIME_ZONE } from './usage-report.mjs';
import { usageClock } from './usage-core.mjs';
import { fetchListeningSessions } from './listening-report.mjs';
import { validListeningDay } from './listening-core.mjs';
import { ALIGNMENT_OUTCOMES, ALIGNMENT_REASONS, ALIGNMENT_FRACTION_BANDS, ALIGNMENT_ERROR_CODES } from './alignment-core.mjs';

const DAY = 86400000;
const RECORDED = new Set(['recording', 'matched_audio']);
export const fetchAlignmentSessions = (db, options) => fetchListeningSessions(db, { ...options, collection: 'alignmentUsageSessions30d' });

const newRow = () => ({ presses: 0, recorded: 0, matched: 0, applied: 0, clients: new Set() });
function publicRow(row) {
  return { presses: row.presses, recorded: row.recorded, matched: row.matched, applied: row.applied, devices: row.clients.size,
    jumpRateOfRecorded: row.recorded ? row.applied / row.recorded : null, jumpRateOfPresses: row.presses ? row.applied / row.presses : null };
}
const percentile = (values, p) => { const s = values.slice().sort((a, b) => a - b); return s.length ? s[Math.min(s.length - 1, Math.floor(s.length * p))] : null; };
const tally = (object, key) => { object[key] = (object[key] || 0) + 1; };

/** Aggregates only; no device keys, hashes, tokens or document IDs leave this function. */
export function summarizeAlignment(records, { from, to, now = Date.now(), query = null }) {
  validateRange(from, to);
  const total = newRow(), groups = { byPlatform: new Map(), byLocale: new Map(), byPage: new Map(), byDay: new Map(), byHour: new Map() };
  const outcomes = {}, reasons = {}, fractionBands = {}, errorCodes = {}, appliedMs = [], shadow = { evaluated: 0, rescued: 0 };
  let ignoredRecords = 0, ignoredAttempts = 0;
  for (const record of records) {
    if (!record || record.schemaVersion !== 1 || !validListeningDay(record.day) || record.day < from || record.day > to || !['web', 'ios'].includes(record.platform)
      || !Array.isArray(record.attempts) || !Number.isFinite(epoch(record.updatedAt)) || epoch(record.updatedAt) < now - 30 * DAY || epoch(record.updatedAt) > now
      || !Number.isFinite(epoch(record.expiresAt)) || epoch(record.expiresAt) <= now) { ignoredRecords++; continue; }
    const client = typeof record.dailyClientKey === 'string' && record.dailyClientKey ? `${record.day}:${record.platform}:${record.dailyClientKey}` : null;
    const locale = typeof record.contentLocale === 'string' ? record.contentLocale : 'unknown';
    const page = typeof record.pageId === 'string' && /^[A-Za-z0-9_-]{1,160}$/.test(record.pageId) ? record.pageId : 'unknown';
    for (const attempt of record.attempts) {
      if (!attempt || !ALIGNMENT_OUTCOMES.includes(attempt.outcome) || !Number.isSafeInteger(attempt.at)) { ignoredAttempts++; continue; }
      const hour = String(usageClock(attempt.at).hour);
      const rows = [total, ...[['byPlatform', record.platform], ['byLocale', locale], ['byPage', page], ['byDay', record.day], ['byHour', hour]].map(([name, key]) => {
        if (!groups[name].has(key)) groups[name].set(key, newRow()); return groups[name].get(key);
      })];
      for (const row of rows) {
        row.presses++;
        if (RECORDED.has(attempt.stage)) row.recorded++;
        if (attempt.stage === 'matched_audio' && attempt.reason === 'matched') row.matched++;
        if (attempt.outcome === 'applied') row.applied++;
        if (client) row.clients.add(client);
      }
      tally(outcomes, attempt.outcome);
      if (attempt.outcome === 'no_match') tally(reasons, ALIGNMENT_REASONS.includes(attempt.reason) ? attempt.reason : 'unknown');
      if (ALIGNMENT_FRACTION_BANDS.includes(attempt.fractionBand)) tally(fractionBands, attempt.fractionBand);
      if (ALIGNMENT_ERROR_CODES.includes(attempt.errorCode)) tally(errorCodes, attempt.errorCode);
      if (attempt.outcome === 'applied' && Number.isFinite(attempt.totalMs)) appliedMs.push(attempt.totalMs);
      if (attempt.shadow) { shadow.evaluated++; if (attempt.outcome === 'no_match' && attempt.shadow.matched) shadow.rescued++; }
    }
  }
  const flatten = (map) => Object.fromEntries([...map].sort(([a], [b]) => a.localeCompare(b, 'en', { numeric: true })).map(([key, row]) => [key, publicRow(row)]));
  return { schemaVersion: 'sermon-private-alignment-report-v1', generatedAt: new Date(now).toISOString(), timeZone: TIME_ZONE, range: { from, to }, retentionDays: 30,
    query: query ? { documentsRead: query.documentsRead, maxDocuments: query.maxDocuments, truncated: query.truncated === true } : null,
    totals: publicRow(total), ignoredRecords, ignoredAttempts, outcomes, reasons, fractionBands, errorCodes, shadow,
    appliedTotalMs: { p50: percentile(appliedMs, .5), p95: percentile(appliedMs, .95) },
    byPlatform: flatten(groups.byPlatform), byLocale: flatten(groups.byLocale), byPage: flatten(groups.byPage), byDay: flatten(groups.byDay), byHour: flatten(groups.byHour),
    definitions: {
      presses: '触发次数：每次点“开始定位”算一次，包括准备索引后没有录音就取消的。',
      recorded: '已录音：麦克风确实开始采集的次数。',
      jumpRateOfRecorded: '定位成功率 = 成功跳转并开始播放（applied）÷ 已录音次数。另列 ÷ 触发次数，用于观察权限拒绝和中途放弃。',
      matched: '匹配到位置的次数（含已跳转、播放被拦截或失败、过期前未应用）。',
      fractionBands: '被拒或命中的匹配比例（matchFraction）区间；接受门槛 0.055 不变，0.045–0.055 为接近门槛。',
      shadow: '影子对照：生产匹配失败后，在本机用候选去噪查询（cmn-v1）再算一次，只记录是否能命中，不改变播放位置；rescued 不是已验证的正确率。',
      devices: '同一洛杉矶日、同一平台按匿名标识去重的设备日，不是人数。',
      coverage: '只含开启匿名统计且成功送达的最近 30 天记录；iOS 默认关闭统计，旧客户端不上报。',
      privacy: '私有运营报告；不含录音、特征、设备名、标识哈希或令牌。请勿上传公开网站。',
    } };
}

const pct = (value) => value === null ? '—' : `${(value * 100).toFixed(1)}%`;
export function renderAlignmentHtml(report) {
  const esc = escapeHtml;
  const table = (title, rows) => `<h2>${esc(title)}</h2><div class="scroll"><table><tr><th>分组</th><th>触发</th><th>已录音</th><th>匹配到</th><th>成功跳转</th><th>成功率（÷已录音）</th><th>成功率（÷触发）</th><th>设备日</th></tr>${Object.entries(rows).map(([key, r]) => `<tr>${[key, r.presses, r.recorded, r.matched, r.applied, pct(r.jumpRateOfRecorded), pct(r.jumpRateOfPresses), r.devices].map((v) => `<td>${esc(v)}</td>`).join('')}</tr>`).join('') || '<tr><td>暂无记录</td></tr>'}</table></div>`;
  const counts = (title, object) => `<h2>${esc(title)}</h2><div class="scroll"><table>${Object.entries(object).sort(([, a], [, b]) => b - a).map(([key, value]) => `<tr><td>${esc(key)}</td><td>${esc(value)}</td></tr>`).join('') || '<tr><td>暂无</td></tr>'}</table></div>`;
  const t = report.totals;
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"><title>听声定位统计 · 私有后台</title><style>body{font:16px/1.6 system-ui;background:#f5f7fa;color:#172033;margin:0}main{max-width:1100px;margin:auto;padding:32px 24px}table{border-collapse:collapse;background:white;width:100%}th,td{text-align:left;padding:10px;border-bottom:1px solid #dce2ec}th{background:#e7edf4;white-space:nowrap}.scroll{overflow:auto}.note{padding:16px;background:#fff3d6}.cards{display:flex;flex-wrap:wrap;gap:16px}.card{padding:20px;background:white;border:1px solid #dce2ec;min-width:150px}.card b{display:block;font-size:28px}</style></head><body><main><p>私有后台 · 同行</p><h1>听声定位统计</h1><p>${esc(report.range.from)} 至 ${esc(report.range.to)} · 洛杉矶时间</p>${report.query?.truncated ? '<p class="note">查询已达上限，指标只代表读到的部分。</p>' : ''}${t.presses ? '' : '<p class="note">尚无记录。新客户端上线并有人使用后才开始累计。</p>'}<div class="cards">${[['触发次数', t.presses], ['已录音', t.recorded], ['成功跳转', t.applied], ['成功率（÷已录音）', pct(t.jumpRateOfRecorded)], ['成功率（÷触发）', pct(t.jumpRateOfPresses)], ['成功耗时 P50/P95', `${report.appliedTotalMs.p50 === null ? '—' : (report.appliedTotalMs.p50 / 1000).toFixed(1)} / ${report.appliedTotalMs.p95 === null ? '—' : (report.appliedTotalMs.p95 / 1000).toFixed(1)} 秒`]].map(([label, value]) => `<div class="card">${esc(label)}<b>${esc(value)}</b></div>`).join('')}</div>${table('按平台', report.byPlatform)}${table('按内容语言', report.byLocale)}${table('按讲道页面', report.byPage)}${table('按日期', report.byDay)}${table('按小时（洛杉矶）', report.byHour)}${counts('结束状态', report.outcomes)}${counts('未匹配原因', report.reasons)}${counts('匹配比例区间', report.fractionBands)}${counts('错误代码', report.errorCodes)}<h2>影子对照（cmn-v1）</h2><p>已评估 ${esc(report.shadow.evaluated)} 次，生产失败而候选命中 ${esc(report.shadow.rescued)} 次。</p><footer><h2>统计口径</h2>${Object.values(report.definitions).map((v) => `<p>${esc(v)}</p>`).join('')}<p>过滤无效或过期记录：${esc(report.ignoredRecords)}；无效尝试：${esc(report.ignoredAttempts)}</p></footer></main></body></html>`;
}
export async function writeAlignmentReport(out, report) {
  const directory = resolve(out);
  await mkdir(directory, { mode: 0o700 });
  await writeFile(join(directory, 'summary.json'), JSON.stringify(report, null, 2) + '\n', { flag: 'wx', mode: 0o600 });
  await writeFile(join(directory, 'index.html'), renderAlignmentHtml(report), { flag: 'wx', mode: 0o600 });
  return { directory, presses: report.totals.presses, applied: report.totals.applied, jumpRateOfRecorded: report.totals.jumpRateOfRecorded, truncated: report.query?.truncated === true };
}
