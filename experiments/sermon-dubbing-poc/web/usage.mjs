import { UsageSession, lockedDailyBrowserId, usageDay, DAILY_BROWSER_KEY } from './usage-client.mjs';

const buttonActions = {
  back: 'back_5_click', forward: 'forward_5_click', 'theme-toggle': 'theme_toggle', download: 'download_click',
  'source-link': 'source_link', 'show-transcript': 'tab_transcript', 'outline-open': 'outline_open',
  'outline-secondary': 'outline_open', 'outline-close': 'outline_close',
  'feedback-up': 'feedback_up', 'feedback-down': 'feedback_down', 'feedback-point': 'feedback_point',
  'feedback-details': 'feedback_details', 'feedback-submit': 'feedback_submit', 'feedback-dialog-close': 'feedback_close',
  'feedback-retract-vote': 'feedback_retract_vote', 'feedback-retract-issue': 'feedback_retract_issue',
  'undo-seek': 'seek_undo', 'resume-position': 'position_restore', 'restart-position': 'position_restart',
  'transcript-current': 'transcript_current', 'precision-open': 'precision_open',
  'tab-listen': 'tab_listen', 'tab-transcript': 'tab_transcript', 'tab-production': 'tab_production', 'tab-voices': 'tab_voices',
};
const nudgeActions = { '-1': 'nudge_back_1_click', '-0.25': 'nudge_back_quarter_click', '0.25': 'nudge_forward_quarter_click', '1': 'nudge_forward_1_click' };

export function createUsage({ catalog, config, audio, context, onError = () => {} }) {
  const bootstrapWeek = catalog.weeks.find(week => week.tracks.length);
  if (!config?.enabled || !bootstrapWeek) return { setEnabled() {}, retract: async () => {}, record() {} };
  const bootstrapTrack = bootstrapWeek.tracks[0];
  const source = { week: bootstrapWeek.id, trackId: bootstrapTrack.id, audioSha256: bootstrapTrack.sha256, appVersion: config.appVersion };
  const sessions = []; let current = null, enabled = false, timer = null;
  let storage; try { storage = localStorage; } catch { storage = null; }
  function session() {
    const day = usageDay();
    if (!current || current.day !== day || current.stopped || (current.client.state.token && current.client.state.expiresAt <= Date.now() + 1000)) {
      current = new UsageSession(source, { day, browserId: lockedDailyBrowserId(storage, day, { permitted: () => enabled }) });
      sessions.push(current);
    }
    return current;
  }
  function flush() {
    if (!enabled) return;
    for (const item of sessions) item.flush().catch(onError);
  }
  function record(action, extra = {}) {
    if (!enabled) return;
    const selected = context();
    const panel = document.getElementById('feedback-dialog').open ? 'feedback'
      : document.getElementById('outline-dialog').open ? 'outline' : selected.panel;
    const position = selected.track && Number.isFinite(audio.currentTime) ? Math.min(selected.track.durationSeconds, Math.max(0, Math.round(audio.currentTime))) : null;
    session().add({ at: Math.floor(Date.now() / 1000) * 1000, action, panel,
      week: selected.week?.id || null, trackId: selected.track?.id || null,
      positionSeconds: position, speakerId: null, ...extra });
    if (!timer) timer = setTimeout(() => { timer = null; flush(); }, 5000);
  }
  document.addEventListener('click', event => {
    const target = event.target instanceof Element ? event.target.closest('button,a,summary') : null;
    if (!target || target.disabled) return;
    let action = buttonActions[target.id];
    if (target.id === 'play' || target.hasAttribute('data-play-toggle')) action = audio.paused ? 'play_click' : 'pause_click';
    if (target.hasAttribute('data-seek-undo')) action = 'seek_undo';
    if (target.id === 'more-toggle' && document.getElementById('more-options').hidden) action = 'more_open';
    if (target.tagName === 'SUMMARY' && target.parentElement?.id === 'feedback-options' && !target.parentElement.open) action = 'feedback_section_open';
    if (target.hasAttribute('data-nudge')) action = nudgeActions[target.dataset.nudge];
    if (target.classList.contains('cue-button')) action = 'transcript_seek';
    if (target.parentElement?.id === 'variants') {
      if (target.getAttribute('aria-pressed') !== 'true') record('track_select', { trackId: target.dataset.id, positionSeconds: 0 });
      return;
    }
    if (target.tagName === 'SUMMARY' && target.parentElement?.contains(document.getElementById('probe-text')) && !target.parentElement.open) action = 'probe_text_open';
    // Browser microtask checkpoints may run between capture and target
    // listeners. These known navigation controls carry an explicit destination.
    if (action?.startsWith('tab_')) { record(action, { panel: action.slice(4) }); return; }
    if (action === 'outline_open') { record(action, { panel: 'outline' }); return; }
    if (action === 'feedback_point' || action === 'feedback_details') { record(action, { panel: 'feedback' }); return; }
    if (action === 'outline_close' || action === 'feedback_close') { record(action, { panel: context().panel }); return; }
    if (action) record(action);
  }, true);
  document.getElementById('week-select').addEventListener('change', () => record('week_select'));
  document.getElementById('progress').addEventListener('change', () => record('progress_seek'));
  document.getElementById('jump-form').addEventListener('submit', () => record('time_jump'));
  document.addEventListener('visibilitychange', () => {
    if (!enabled) return;
    record(document.visibilityState === 'visible' ? 'page_visible' : 'page_hidden'); flush();
  });
  window.addEventListener('pagehide', () => { if (enabled) { record('page_hidden'); flush(); } });
  setInterval(() => {
    if (enabled && document.visibilityState === 'visible') record('page_heartbeat');
    flush();
  }, 60000);
  return {
    setEnabled(value) {
      if (value === enabled) return;
      enabled = value;
      if (enabled) { current = null; record('app_open'); flush(); }
    },
    async retract() {
      enabled = false;
      if (timer) clearTimeout(timer); timer = null;
      try { storage?.removeItem(DAILY_BROWSER_KEY); } catch {}
      const results = await Promise.allSettled(sessions.map(item => item.retract()));
      const failed = results.find(result => result.status === 'rejected');
      if (failed) throw failed.reason;
    },
    record,
  };
}
