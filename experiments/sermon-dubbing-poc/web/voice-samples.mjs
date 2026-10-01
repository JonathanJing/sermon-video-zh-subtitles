// Replaces the legacy English/Chinese bank plus Korean/Spanish sidecar with one UI.
import { mountSpeakerClipDemos, demoCopy } from './speaker-clip-demos.mjs';
const grid = globalThis.document?.getElementById('voice-grid');
if (grid) {
  let mounted, attempted = false;
  const mount = async () => {
    if (attempted || grid.querySelectorAll('.voice-card').length !== 6) return;
    attempted = true;
    observer.disconnect();
    // Validate and render without changing the currently working legacy bank.
    // Moving these children preserves the renderer's player/localization closures.
    const staged = document.createElement('div');
    try { mounted = await mountSpeakerClipDemos(staged, { production: true }); }
    catch (error) { console.warn('Voice demo unavailable; keeping existing samples', error); return; }
    for (const media of grid.querySelectorAll('audio,video')) media.pause();
    const css = document.createElement('link'); css.rel = 'stylesheet'; css.href = '/voice-demo.css'; document.head.append(css);
    grid.replaceChildren(...staged.childNodes);
    // Hide the obsolete shared probe script only after replacement succeeds.
    for (const obsolete of document.querySelectorAll('.probe-script, .voice-method-intro, .voice-method, .voice-ai-disclosure, .voices-heading .eyebrow, .voices-heading p[data-i18n]')) obsolete.hidden = true;
    const heading = document.querySelector('.voices-heading h2');
    if (heading) { heading.removeAttribute('data-i18n'); heading.textContent = demoCopy(document).title;
      new MutationObserver(() => { heading.textContent = demoCopy(document).title; }).observe(document.documentElement, { attributes: true, attributeFilter: ['lang'] }); }
    const notice = document.getElementById('voice-bank-notice');
    if (notice) notice.hidden = true;
    if (document.getElementById('panel-voices')?.hidden) mounted.pause();
  };
  const observer = new MutationObserver(() => { void mount(); }); observer.observe(grid, { childList: true });
  const panel = document.getElementById('panel-voices');
  if (panel) new MutationObserver(() => { if (panel.hidden) mounted?.pause(); }).observe(panel, { attributes: true, attributeFilter: ['hidden'] });
  void mount();
}
