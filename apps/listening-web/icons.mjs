// Shared original SVG artwork for the weekly and multilingual Firebase readers.
const names = new Set(['play.fill', 'pause.fill', 'pause.circle', 'gobackward', 'goforward', 'magnifyingglass', 'mic', 'stop.circle', 'arrow.right.to.line', 'text.bubble', 'slider.horizontal.3', 'arrow.uturn.backward', 'calendar', 'ellipsis.circle', 'globe', 'play.rectangle', 'list.bullet.rectangle', 'chevron.left', 'chevron.right', 'chevron.down', 'xmark', 'arrow.down.circle', 'checkmark', 'checkmark.circle.fill', 'clock.arrow.circlepath', 'info.circle', 'hand.raised', 'circle', 'sun.max', 'moon', 'hand.thumbsup', 'hand.thumbsdown', 'flag', 'arrow.clockwise', 'chevron.up', 'exclamationmark.circle', 'globe.badge.chevron.backward', 'headphones', 'hourglass', 'play.circle', 'text.magnifyingglass', 'waveform', 'wifi.exclamationmark', 'wifi.slash']);
export function iconMarkup(name, className = '') {
  if (!names.has(name) || !/^[a-zA-Z0-9 _-]*$/.test(className)) throw new Error('Unknown icon');
  return `<svg class="app-icon ${className}" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="/icons.svg#${name}"></use></svg>`;
}
export function setIcon(container, name) {
  if (!container || container.dataset.icon === name) return;
  container.innerHTML = iconMarkup(name);
  container.dataset.icon = name;
}
export function setButtonLabel(button, text) {
  const label = button.querySelector?.('[data-icon-label]') || button;
  label.textContent = text;
}
