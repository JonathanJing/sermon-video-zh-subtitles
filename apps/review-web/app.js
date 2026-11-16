/* Review pack player.
 *
 * Reads pack.json, plays the reviewer's track (or the per-sentence clips), and
 * keeps per-sentence verdicts in localStorage. It never posts anything: when the
 * review is done the page hands back one short command line to paste into the
 * review channel. That is deliberate — the reviewer's network may not reach an
 * API, and a chat line can be replayed later by message id.
 *
 * No inline script, no inline style, no external origin: the pack runs under
 * `default-src 'none'` and everything it needs is a sibling file.
 */

const els = {
  eyebrow: document.querySelector('#eyebrow'),
  title: document.querySelector('#title'),
  counts: document.querySelector('#counts'),
  heard: document.querySelector('#heard'),
  meter: document.querySelector('#meter'),
  meterFill: document.querySelector('#meter-fill'),
  filters: document.querySelector('#filters'),
  list: document.querySelector('#list'),
  empty: document.querySelector('#empty'),
  player: document.querySelector('#player'),
  play: document.querySelector('#play'),
  now: document.querySelector('#now'),
  hint: document.querySelector('#hint'),
  copy: document.querySelector('#copy'),
  copyOut: document.querySelector('#copy-out'),
  theme: document.querySelector('#theme'),
};

const FLAG_LABELS = {
  revised: '译文改过',
  note: '有备注',
  speaker: '讲员存疑',
  spoken: '口播与字幕不同',
  digits: '含数字读法',
  lag: '落后偏大',
  doubt: '源句可疑',
};

const HOT_FLAGS = new Set(['speaker', 'digits', 'doubt', 'lag']);

const state = {
  pack: null,
  verdicts: new Map(),
  heard: new Set(),
  filter: 'hot',
  current: null,
  stopAt: Infinity,
  chain: true,
  visible: [],
};

const store = {
  key() {
    return `review:${state.pack?.productionId || 'unknown'}`;
  },
  load() {
    try {
      const raw = JSON.parse(localStorage.getItem(this.key()) || '{}');
      for (const [id, verdict] of Object.entries(raw.verdicts || {})) {
        state.verdicts.set(id, verdict);
      }
      for (const id of raw.heard || []) state.heard.add(id);
    } catch {
      /* a corrupt entry only loses a session; never blocks the review */
    }
  },
  save() {
    try {
      localStorage.setItem(this.key(), JSON.stringify({
        verdicts: Object.fromEntries(state.verdicts),
        heard: [...state.heard],
      }));
    } catch {
      /* private mode or quota: the copy-command path still works */
    }
  },
};

function esc(text) {
  return String(text ?? '');
}

function mmss(seconds) {
  const total = Math.max(0, Math.round(seconds || 0));
  const m = Math.floor(total / 60);
  return `${m}:${String(total % 60).padStart(2, '0')}`;
}

function rowNode(row) {
  const verdict = state.verdicts.get(row.id);
  const node = document.createElement('article');
  node.className = 'row';
  node.dataset.id = row.id;
  node.tabIndex = -1;
  if (verdict === 'fix') node.classList.add('is-fixed');
  if (verdict === 'pass') node.classList.add('is-passed');

  const head = document.createElement('div');
  head.className = 'row-head';

  const seq = document.createElement('span');
  seq.className = 'seq';
  seq.textContent = `#${row.index} · ${mmss(row.start)}`;

  const spokenFlag = document.createElement('span');
  spokenFlag.className = 'seq';
  spokenFlag.textContent = state.heard.has(row.id) ? '已听' : '';

  const skip = document.createElement('div');
  skip.className = 'skip';
  const prev = document.createElement('button');
  prev.type = 'button';
  prev.textContent = '上一句';
  prev.addEventListener('click', () => move(-1));
  const next = document.createElement('button');
  next.type = 'button';
  next.textContent = '下一句';
  next.addEventListener('click', () => move(1));
  skip.append(prev, next);

  head.append(seq, spokenFlag, skip);

  const english = document.createElement('p');
  english.className = 'english';
  english.textContent = esc(row.english);

  const target = document.createElement('p');
  target.className = 'target';
  target.textContent = esc(row.target || '（无译文）');

  node.append(head, english, target);

  if (row.spoken && row.spoken.trim() !== (row.target || '').trim()) {
    const spoken = document.createElement('p');
    spoken.className = 'spoken';
    spoken.append(document.createTextNode('口播：'));
    const strong = document.createElement('b');
    strong.textContent = esc(row.spoken);
    spoken.append(strong);
    node.append(spoken);
  }

  if (row.flags.length) {
    const flags = document.createElement('ul');
    flags.className = 'flags';
    for (const flag of row.flags) {
      const item = document.createElement('li');
      item.textContent = FLAG_LABELS[flag] || flag;
      if (HOT_FLAGS.has(flag)) item.classList.add('hot');
      flags.append(item);
    }
    node.append(flags);
  }

  if (row.note) {
    const note = document.createElement('p');
    note.className = 'note';
    note.textContent = esc(row.note);
    node.append(note);
  }

  const actions = document.createElement('div');
  actions.className = 'actions';
  const pass = document.createElement('button');
  pass.type = 'button';
  pass.textContent = verdict === 'pass' ? '已通过' : '通过';
  if (verdict === 'pass') pass.classList.add('on-pass');
  pass.addEventListener('click', () => setVerdict(row.id, 'pass'));
  const fix = document.createElement('button');
  fix.type = 'button';
  fix.textContent = verdict === 'fix' ? '已标问题' : '标问题';
  if (verdict === 'fix') fix.classList.add('on-fix');
  fix.addEventListener('click', () => setVerdict(row.id, 'fix'));
  actions.append(pass, fix);
  node.append(actions);

  node.addEventListener('click', (event) => {
    if (event.target.closest('button')) return;
    select(row.id, false);
  });

  return node;
}

function matches(row) {
  const verdict = state.verdicts.get(row.id);
  switch (state.filter) {
    case 'hot': return row.flags.some((flag) => HOT_FLAGS.has(flag));
    case 'flagged': return row.flags.length > 0;
    case 'pending': return !verdict;
    case 'fixed': return verdict === 'fix';
    default: return true;
  }
}

function render() {
  const rows = state.pack.sentences;
  state.visible = rows.filter(matches);
  els.list.replaceChildren(...state.visible.map(rowNode));
  els.empty.hidden = state.visible.length > 0;
  updateMeter();
  if (state.current) {
    const node = els.list.querySelector(`[data-id="${state.current}"]`);
    if (node) node.classList.add('is-playing');
  }
}

function updateMeter() {
  const rows = state.pack.sentences;
  const decided = rows.filter((row) => state.verdicts.has(row.id)).length;
  const percent = rows.length ? Math.round((decided / rows.length) * 100) : 0;
  els.counts.textContent = `${decided} / ${rows.length} 已审`;
  els.heard.textContent = `听过 ${state.heard.size}`;
  els.meterFill.style.width = `${percent}%`;
  els.meter.setAttribute('aria-valuenow', String(percent));
  const fixes = rows.filter((row) => state.verdicts.get(row.id) === 'fix').length;
  els.copy.textContent = fixes ? `复制口令 · ${fixes} 处` : '复制口令';
}

function setVerdict(id, verdict) {
  if (state.verdicts.get(id) === verdict) state.verdicts.delete(id);
  else state.verdicts.set(id, verdict);
  store.save();
  render();
  const node = els.list.querySelector(`[data-id="${id}"]`);
  if (node) node.focus({ preventScroll: true });
}

function audioSource(row) {
  if (row.clip) return row.clip;
  return state.pack.track ? state.pack.track.url : null;
}

function select(id, play) {
  const row = state.pack.sentences.find((item) => item.id === id);
  if (!row) return;
  state.current = id;
  for (const node of els.list.querySelectorAll('.row')) {
    node.classList.toggle('is-playing', node.dataset.id === id);
  }
  els.now.textContent = `#${row.index} ${row.target || row.english || ''}`.slice(0, 90);
  if (play) playRow(row);
  const node = els.list.querySelector(`[data-id="${id}"]`);
  if (node) node.scrollIntoView({ block: 'center', behavior: 'smooth' });
}

function playRow(row) {
  const source = audioSource(row);
  if (!source) {
    els.now.textContent = '这是纯文字包，没有音频';
    return;
  }
  const audio = els.player;
  if (audio.dataset.src !== source) {
    audio.dataset.src = source;
    audio.src = source;
  }
  const start = row.clip ? 0 : row.dubStart;
  const length = row.clip
    ? Infinity
    : Math.max(row.dubSeconds || 0, (row.end || 0) - (row.start || 0)) + 0.2;
  state.stopAt = row.clip ? Infinity : start + length;
  try {
    audio.currentTime = start;
  } catch {
    /* the browser resets currentTime once metadata is ready below */
  }
  audio.play().then(() => {
    state.chain = true;
    els.play.textContent = '❚❚';
  }).catch(() => {
    els.now.textContent = '浏览器挡住了自动播放，点一下播放键';
  });
}

function move(step) {
  const list = state.visible.length ? state.visible : state.pack.sentences;
  const index = list.findIndex((row) => row.id === state.current);
  const next = list[Math.min(Math.max(index + step, 0), list.length - 1)] || list[0];
  if (next) select(next.id, true);
}

function markHeard() {
  if (state.current) {
    state.heard.add(state.current);
    store.save();
    updateMeter();
  }
}

function advance() {
  const list = state.visible.length ? state.visible : state.pack.sentences;
  const index = list.findIndex((row) => row.id === state.current);
  const next = list[index + 1];
  if (next) {
    select(next.id, true);
  } else {
    els.play.textContent = '▶';
    els.now.textContent = '这一组听完了';
  }
}

function finishSentence() {
  markHeard();
  if (state.chain) advance();
}

els.player.addEventListener('timeupdate', () => {
  if (!state.current || state.stopAt === Infinity) return;
  if (els.player.currentTime < state.stopAt) return;
  els.player.pause();
  finishSentence();
});

els.player.addEventListener('ended', () => {
  if (!state.current) return;
  finishSentence();
});

els.player.addEventListener('play', () => { els.play.textContent = '❚❚'; });
els.player.addEventListener('pause', () => { els.play.textContent = '▶'; });

els.play.addEventListener('click', () => {
  const audio = els.player;
  if (!audio.src) {
    const first = state.visible[0] || state.pack.sentences[0];
    if (first) select(first.id, true);
    return;
  }
  if (audio.paused) {
    state.chain = true;
    audio.play();
  } else {
    state.chain = false;
    audio.pause();
  }
});

els.filters.addEventListener('click', (event) => {
  const button = event.target.closest('button[data-filter]');
  if (!button) return;
  state.filter = button.dataset.filter;
  for (const item of els.filters.querySelectorAll('button')) {
    item.classList.toggle('on', item === button);
  }
  render();
});

function commandLine() {
  const { code, checkpoint, sentences } = state.pack;
  const fixes = sentences.filter((row) => state.verdicts.get(row.id) === 'fix').map((row) => row.id);
  if (fixes.length) return `${code} ${checkpoint} FIX ${fixes.join(' ')}`;
  return `${code} ${checkpoint} PASS played=${state.heard.size}`;
}

els.copy.addEventListener('click', async () => {
  const line = commandLine();
  els.copyOut.hidden = false;
  els.copyOut.textContent = line;
  try {
    await navigator.clipboard.writeText(line);
    els.copy.textContent = '已复制';
    window.setTimeout(() => {
      els.copy.textContent = '复制口令';
      updateMeter();
    }, 1800);
  } catch {
    const range = document.createRange();
    range.selectNodeContents(els.copyOut);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
  }
});

document.addEventListener('keydown', (event) => {
  if (event.metaKey || event.ctrlKey || event.altKey) return;
  const tag = (event.target.tagName || '').toLowerCase();
  if (tag === 'input' || tag === 'textarea') return;
  switch (event.key) {
    case ' ':
      event.preventDefault();
      els.play.click();
      break;
    case 'j':
    case 'ArrowDown':
      event.preventDefault();
      move(1);
      break;
    case 'k':
    case 'ArrowUp':
      event.preventDefault();
      move(-1);
      break;
    case 'Enter':
      event.preventDefault();
      if (state.current) setVerdict(state.current, 'pass');
      break;
    case 'x':
      event.preventDefault();
      if (state.current) setVerdict(state.current, 'fix');
      break;
    case 'f': {
      event.preventDefault();
      const list = state.visible.filter((row) => row.flags.length);
      const index = list.findIndex((row) => row.id === state.current);
      const next = list[index + 1] || list[0];
      if (next) select(next.id, true);
      break;
    }
    default:
      break;
  }
});

function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem('review-theme', theme);
  } catch {
    /* the page still works without persistence */
  }
}

els.theme.addEventListener('click', () => {
  setTheme(document.documentElement.dataset.theme === 'light' ? 'dark' : 'light');
});

async function boot() {
  try {
    const saved = localStorage.getItem('review-theme');
    if (saved === 'light' || saved === 'dark') document.documentElement.dataset.theme = saved;
  } catch {
    /* ignore */
  }

  const response = await fetch('pack.json', { cache: 'no-cache' });
  if (!response.ok) throw new Error(`pack.json ${response.status}`);
  const pack = await response.json();
  if (pack.schemaVersion !== 'sentence-first-review-pack-v1') {
    throw new Error(`unsupported pack schema ${pack.schemaVersion}`);
  }
  state.pack = pack;

  els.eyebrow.textContent = `${pack.locale} · ${pack.checkpoint === 'audio' ? '音频审核' : '文字审核'} · ${pack.code}`;
  els.title.textContent = pack.title;
  document.title = `${pack.code} · ${pack.title}`;

  store.load();
  render();

  if (pack.checkpoint !== 'audio' || !pack.track) {
    els.play.disabled = true;
    els.hint.textContent = '纯文字包：直接标问题或通过，然后复制口令';
  }
}

boot().catch((error) => {
  els.title.textContent = '审核包载入失败';
  els.now.textContent = String(error.message || error);
});
