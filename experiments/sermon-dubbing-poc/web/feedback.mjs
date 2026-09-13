import { FeedbackClient, FeedbackError, statisticsPreference } from '/feedback-client.mjs';
import { ListeningSummary } from '/listening.mjs';
import { formatTime } from '/timing.mjs';

// Default on; an explicit current or legacy opt-out remains authoritative.
const preferenceKey = 'sermon-anonymous-statistics-v2';
const $ = id => document.getElementById(id);
const categories = [['translation', '翻译不准确'], ['pronunciation', '发音有误'], ['fluency', '听起来不流畅'],
  ['voice', '音色不自然'], ['sync', '与视频不同步'], ['volume', '音量问题'], ['playback', '播放或下载问题']];
function storedPreference() { try { return statisticsPreference(localStorage); } catch { return true; } }
function errorMessage(error) {
  if (error instanceof FeedbackError && error.status === 410) return '本次会话已过期，请刷新页面再提交。旧记录未撤回，将按保留期限清理。';
  return error instanceof FeedbackError && error.status === 429 ? '提交较频繁，请稍后再试。' : '暂时未能确认保存，请检查网络后重试。';
}

export function createFeedback(audio, config, { usage } = {}) {
  if (!config?.enabled) return { select() {}, count() {}, error() {}, statisticsEnabled: () => false };
  const clients = new Map();
  let current = null, feedbackTarget = null, point = null, issueId = null, busy = false, optIn = storedPreference();
  const setStatus = text => { $('feedback-status').textContent = text; };
  $('privacy-controls').hidden = false;
  $('statistics-notice').hidden = false;
  $('statistics-opt-in').checked = optIn;
  $('statistics-status').textContent = optIn ? '已开启匿名统计，可随时关闭；每日更换随机标识，不连接跨日个人轨迹。' : '已保留你关闭匿名统计的选择。';
  for (const [value, label] of categories) {
    const item = document.createElement('label'), checkbox = document.createElement('input');
    checkbox.type = 'checkbox'; checkbox.value = value; checkbox.name = 'feedback-category';
    item.append(checkbox, document.createTextNode(label)); $('feedback-categories').append(item);
  }
  function buttons() {
    for (const [id, value] of [['feedback-up', 'up'], ['feedback-down', 'down']]) {
      $(id).setAttribute('aria-pressed', String(current?.client.state.vote === value));
      $(id).disabled = busy || !current;
    }
    $('feedback-retract-vote').hidden = !current?.client.state.vote;
    $('feedback-retract-vote').disabled = busy;
    $('feedback-point').disabled = !current;
    $('feedback-details').disabled = !current;
    $('feedback-retract-issue').hidden = !current?.client.state.lastIssueId;
    $('feedback-retract-issue').disabled = busy;
  }
  function observe() {
    if (optIn && current?.readyForStats) current.summary.observe(audio.currentTime, performance.now(), !audio.paused && !audio.seeking && audio.readyState >= 3);
  }
  function prepareStatistics(target = current) {
    if (!optIn || !target || target.readyForStats || target.preparing || target.expired) return;
    target.preparing = true;
    target.client.session().then(() => {
      target.readyForStats = optIn;
      target.summary.resetSample();
    }).catch(error => {
      target.expired = error instanceof FeedbackError && error.status === 410;
      if (optIn) $('statistics-status').textContent = target.expired ? '本页会话已结束，匿名统计已暂停；刷新页面可重新开启。' : '暂时无法开启匿名统计，稍后会重试；播放不受影响。';
    }).finally(() => { target.preparing = false; });
  }
  function flush(target = current) {
    if (!optIn || !target?.readyForStats) return;
    const snapshot = target.summary.snapshot(), signature = JSON.stringify(snapshot);
    if (signature === target.sent || !(snapshot.listenedSeconds || Object.values(snapshot.errors).some(Boolean) || Object.values(target.summary.counts).some(Boolean))) return;
    target.sent = signature;
    target.client.events(snapshot, () => optIn).catch(error => {
      target.sent = null;
      target.expired = error instanceof FeedbackError && error.status === 410;
      if (target.expired) target.readyForStats = false;
      if (optIn) $('statistics-status').textContent = target.expired ? '本页会话已结束，匿名统计已暂停；刷新页面可重新开启。' : '匿名摘要暂未送达，稍后会重试；播放不受影响。';
    });
  }
  function flushPendingStatistics() {
    // Switching tracks must not strand a failed final summary. flush() skips
    // disabled, withdrawn, empty and unchanged targets without minting sessions.
    for (const target of clients.values()) flush(target);
  }
  function count(name) { if (optIn && current?.readyForStats) current.summary.count(name); }
  function openDetails(atPoint) {
    if (!current) return;
    feedbackTarget = current;
    point = null;
    if (atPoint) {
      const seconds = Math.max(0, Math.min(audio.currentTime, current.track.durationSeconds));
      const index = current.track.cues.findIndex(cue => cue.start <= seconds && seconds < cue.end);
      point = { positionSeconds: Math.round(seconds * 100) / 100, cueId: index < 0 ? null : String(index),
        blockId: index < 0 || current.track.cues[index].blockId == null ? null : String(current.track.cues[index].blockId) };
      $('feedback-excerpt').textContent = index < 0 ? '当前位置没有字幕。' : current.track.cues[index].text;
    }
    issueId = crypto.randomUUID();
    $('feedback-form').reset();
    $('feedback-dialog-context').textContent = `${current.week.title} · ${point ? formatTime(point.positionSeconds) : '整份音频'}`;
    $('feedback-excerpt').hidden = !point;
    $('feedback-form-status').textContent = '';
    $('feedback-dialog').showModal();
  }
  async function vote(value) {
    if (!current || busy) return;
    const target = current;
    busy = true; buttons(); setStatus('正在保存…');
    try {
      await target.client.vote(value);
      if (target === current) {
        setStatus(value ? '谢谢，评价已保存。' : '评价已撤回。');
        if (value === 'down') openDetails(false);
      }
    } catch (error) { if (target === current) setStatus(errorMessage(error)); }
    finally { busy = false; buttons(); }
  }
  $('feedback-up').addEventListener('click', () => vote('up'));
  $('feedback-down').addEventListener('click', () => vote('down'));
  $('feedback-retract-vote').addEventListener('click', () => vote(null));
  $('feedback-point').addEventListener('click', () => openDetails(true));
  $('feedback-details').addEventListener('click', () => openDetails(false));
  $('feedback-dialog-close').addEventListener('click', () => $('feedback-dialog').close());
  $('feedback-form').addEventListener('submit', async event => {
    event.preventDefault();
    if (!feedbackTarget || !issueId || $('feedback-submit').disabled) return;
    const selected = [...document.querySelectorAll('[name="feedback-category"]:checked')].map(input => input.value);
    const comment = $('feedback-comment').value.trim();
    if (!selected.length && !comment) { $('feedback-form-status').textContent = '请选择一个问题，或写下补充说明。'; return; }
    const target = feedbackTarget, id = issueId;
    $('feedback-submit').disabled = true; $('feedback-form-status').textContent = '正在保存…';
    try {
      await target.client.issue(id, { categories: selected, comment, context: $('feedback-use-context').value,
        ...(point || { positionSeconds: null, cueId: null, blockId: null }) });
      if (issueId === id) $('feedback-dialog').close();
      if (target === current) setStatus('问题已保存，谢谢你帮助改进中文听译。');
      buttons();
    } catch (error) { $('feedback-form-status').textContent = errorMessage(error); }
    finally { $('feedback-submit').disabled = false; }
  });
  $('feedback-retract-issue').addEventListener('click', async () => {
    if (!current?.client.state.lastIssueId || busy) return;
    const target = current, id = target.client.state.lastIssueId;
    busy = true; buttons(); setStatus('正在撤回…');
    try { await target.client.issue(id, null, 'delete'); if (target === current) setStatus('最近一次问题反馈已撤回。'); }
    catch (error) { if (target === current) setStatus(errorMessage(error)); }
    finally { busy = false; buttons(); }
  });
  async function changePreference(enabled) {
    optIn = enabled;
    $('statistics-opt-in').checked = enabled;
    try { localStorage.setItem(preferenceKey, enabled ? 'yes' : 'no'); } catch {}
    if (enabled) {
      usage?.setEnabled(true);
      current?.summary.resetSample();
      prepareStatistics();
      $('statistics-status').textContent = '已开启：统计使用时间、操作和收听摘要，不连接跨日个人轨迹。';
    } else {
      usage?.setEnabled(false);
      try { localStorage.setItem('sermon-anonymous-statistics-v1', 'no'); } catch {}
      $('statistics-opt-in').disabled = true;
      $('statistics-status').textContent = '已关闭匿名统计，正在撤回本页已上传的使用记录…';
      const results = await Promise.allSettled([usage?.retract(), ...[...clients.values()].map(async target => {
        target.readyForStats = false;
        await target.client.deleteEvents();
        // A failed delete leaves the accepted baseline intact for a later retry
        // or re-enable. Reset only after the server confirms removal.
        target.summary = new ListeningSummary(target.track.durationSeconds); target.sent = null;
      })]);
      $('statistics-opt-in').disabled = false;
      const failures = results.filter(result => result.status === 'rejected');
      const expired = failures.some(result => result.reason instanceof FeedbackError && result.reason.status === 410);
      $('statistics-status').textContent = expired ? '已停止统计；会话已过期，部分摘要无法在本页撤回，将按 30 天期限清理。'
        : failures.length ? '已停止统计；部分历史摘要暂未撤回，请联网后点击“重试撤回”。'
        : '已关闭匿名统计；本页已上传的使用记录已撤回。';
      $('statistics-retry-delete').hidden = !failures.some(result => !(result.reason instanceof FeedbackError && result.reason.status === 410));
    }
  }
  $('statistics-opt-in').addEventListener('change', event => changePreference(event.target.checked));
  $('statistics-retry-delete').addEventListener('click', () => changePreference(false));
  window.addEventListener('storage', event => { if (event.key === preferenceKey && optIn !== storedPreference()) changePreference(storedPreference()); });
  for (const name of ['play', 'pause', 'seeking', 'waiting', 'ended']) audio.addEventListener(name, () => {
    observe();
    current?.summary.resetSample();
    if (name === 'play' && current && !current.playing) { count('plays'); current.playing = true; }
    if (name === 'pause' && current?.playing) { count('pauses'); current.playing = false; flush(); }
    if (name === 'seeking') count('seeks');
    if (name === 'ended') flush();
  });
  audio.addEventListener('timeupdate', observe);
  setInterval(() => { prepareStatistics(); observe(); flushPendingStatistics(); }, 60000);
  window.addEventListener('online', flushPendingStatistics);
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') { observe(); flushPendingStatistics(); current?.summary.resetSample(); } });
  window.addEventListener('pagehide', () => { observe(); flushPendingStatistics(); });
  return {
    statisticsEnabled: () => optIn,
    select(week, track) {
      if (current?.playing) { count('pauses'); current.playing = false; }
      flush();
      current = null;
      $('feedback-card').hidden = !track;
      if (track) {
        const key = `${week.id}:${track.id}:${track.sha256}`;
        if (!clients.has(key)) {
          // Each document gets its own credential: duplicating a browser tab
          // must not share a cumulative statistics stream with the original.
          const client = new FeedbackClient({ week: week.id, trackId: track.id, audioSha256: track.sha256, appVersion: config.appVersion });
          const summary = new ListeningSummary(track.durationSeconds), saved = client.state.summary;
          if (saved && optIn) {
            summary.listenedSeconds = saved.listenedSeconds || 0; summary.ranges = saved.ranges || [];
            for (const name of Object.keys(summary.counts)) summary.counts[name] = saved[name] || 0;
            for (const name of Object.keys(summary.errors)) summary.errors[name] = saved.errors?.[name] || 0;
          }
          clients.set(key, { client, summary, week, track, sent: null });
        }
        current = clients.get(key); current.playing = false; current.summary.resetSample();
        prepareStatistics();
      }
      buttons(); setStatus('');
    },
    count,
    error(name) { if (optIn && current?.readyForStats) { current.summary.error(name); flush(); } },
  };
}
