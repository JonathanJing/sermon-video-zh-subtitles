// Dev and Production share one renderer and one same-clip contract.
import { mountSpeakerClipDemos, demoCopy } from './speaker-clip-demos.mjs';
const more = document.getElementById('moreOptions');
if (more) {
  const panel = document.createElement('details'); panel.id = 'voiceDemoDetails'; panel.className = 'voice-demo-panel';
  const summary = document.createElement('summary'); summary.textContent = demoCopy(document).title;
  const body = document.createElement('div'); body.className = 'voice-demo-body'; panel.append(summary, body); more.append(panel);
  let mounted, pending = false;
  new MutationObserver(() => { summary.textContent = demoCopy(document).title; }).observe(document.documentElement, { attributes: true, attributeFilter: ['lang'] });
  panel.addEventListener('toggle', async () => {
    if (!panel.open) { mounted?.pause(); return; }
    if (mounted || pending) return;
    pending = true;
    try { mounted = await mountSpeakerClipDemos(body); if (!panel.open) mounted.pause(); }
    catch (error) { console.warn('Voice demo unavailable', error); body.textContent = '试听资料暂时不可用，请关闭后重试。'; }
    finally { pending = false; }
  });
  new MutationObserver(() => { if (more.hidden) mounted?.pause(); }).observe(more, { attributes: true, attributeFilter: ['hidden'] });
}
