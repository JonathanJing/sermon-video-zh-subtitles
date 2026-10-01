// Replaces the legacy English/Chinese bank plus Korean/Spanish sidecar with one UI.
import { mountSpeakerClipDemos, demoCopy } from './speaker-clip-demos.mjs';
const grid = globalThis.document?.getElementById('voice-grid');
if (grid) {
  const css = document.createElement('link'); css.rel = 'stylesheet'; css.href = '/voice-demo.css'; document.head.append(css);
  let mounted, pending = false;
  const mount = async () => {
    if (mounted || pending || grid.querySelectorAll('.voice-card').length !== 6) return;
    pending = true;
    for (const media of grid.querySelectorAll('audio,video')) media.pause();
    const loading = document.createElement('p'); loading.textContent = demoCopy(document).loading; grid.replaceChildren(loading);
    // Hide the obsolete shared probe script: each selected sample has its own actual text.
    for (const obsolete of document.querySelectorAll('.probe-script, .voice-method-intro, .voice-method, .voice-ai-disclosure, .voices-heading .eyebrow, .voices-heading p[data-i18n]')) obsolete.hidden = true;
    const heading = document.querySelector('.voices-heading h2');
    if (heading) { heading.removeAttribute('data-i18n'); heading.textContent = demoCopy(document).title;
      new MutationObserver(() => { heading.textContent = demoCopy(document).title; }).observe(document.documentElement, { attributes: true, attributeFilter: ['lang'] }); }
    try { mounted = await mountSpeakerClipDemos(grid, { production: true });
      document.getElementById('voice-bank-notice').hidden = true;
      observer.disconnect(); }
    catch (error) { console.warn('Voice demo unavailable', error); grid.replaceChildren();
      const message = document.createElement('p'); message.textContent = '试听资料暂时不可用，请刷新后重试。'; grid.append(message); observer.disconnect(); }
    finally { pending = false; }
  };
  const observer = new MutationObserver(() => { void mount(); }); observer.observe(grid, { childList: true });
  const panel = document.getElementById('panel-voices');
  if (panel) new MutationObserver(() => { if (panel.hidden) mounted?.pause(); }).observe(panel, { attributes: true, attributeFilter: ['hidden'] });
  void mount();
}
