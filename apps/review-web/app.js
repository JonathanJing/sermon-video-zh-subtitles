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
  notes: new Map(),
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
      for (const [id, text] of Object.entries(raw.notes || {})) state.notes.set(id, text);
      for (const id of raw.heard || []) state.heard.add(id);
    } catch {
      /* a corrupt entry only loses a session; never blocks the review */
    }
  },
  save() {
    try {
      localStorage.setItem(this.key(), JSON.stringify({
        verdicts: Object.fromEntries(state.verdicts),
        notes: Object.fromEntries(state.notes),
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

function paintRow(node) {
  const row = state.pack.sentences.find((item) => item.id === node.dataset.id);
  if (!row) return;
  const verdict = state.verdicts.get(row.id);
  node.classList.toggle('is-fixed', verdict === 'fix');
  node.classList.toggle('is-passed', verdict === 'pass');
  const [pass, fix] = node.querySelectorAll('.actions button');
  if (!pass || !fix) return;
  pass.textContent = verdict === 'pass' ? '已通过' : '通过';
  pass.classList.toggle('on-pass', verdict === 'pass');
  fix.textContent = verdict === 'fix' ? '已标问题' : '标问题';
  fix.classList.toggle('on-fix', verdict === 'fix');
}

function rowNode(row) {
  const node = document.createElement('article');
  node.className = 'row';
  node.dataset.id = row.id;
  node.tabIndex = -1;

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

  const issue = document.createElement('label');
  issue.className = 'issue';
  const issueLabel = document.createElement('span');
  issueLabel.className = 'issue-label';
  issueLabel.textContent = '问题或改法';
  const issueInput = document.createElement('input');
  issueInput.type = 'text';
  issueInput.className = 'issue-input';
  issueInput.placeholder = '写出具体问题或改成什么；留空表示这句没问题';
  issueInput.value = state.notes.get(row.id) || '';
  issueInput.addEventListener('input', () => setNote(row.id, issueInput.value));
  issueInput.addEventListener('keydown', (event) => event.stopPropagation());
  issue.append(issueLabel, issueInput);

  const actions = document.createElement('div');
  actions.className = 'actions';
  const pass = document.createElement('button');
  pass.type = 'button';
  pass.textContent = '通过';
  pass.addEventListener('click', () => setVerdict(row.id, 'pass'));
  const fix = document.createElement('button');
  fix.type = 'button';
  fix.textContent = '标问题';
  fix.addEventListener('click', () => setVerdict(row.id, 'fix'));
  actions.append(pass, fix);
  node.append(issue, actions);

  node.addEventListener('click', (event) => {
    if (event.target.closest('button') || event.target.closest('input')) return;
    select(row.id, false);
  });

  paintRow(node);
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
  if (verdict === 'pass' && state.verdicts.get(id) === 'pass') {
    state.notes.delete(id);
    const node = els.list.querySelector(`[data-id="${id}"]`);
    const input = node && node.querySelector('.issue-input');
    if (input) input.value = '';
  }
  store.save();
  const node = els.list.querySelector(`[data-id="${id}"]`);
  if (node) paintRow(node);
  updateMeter();
}

function setNote(id, text) {
  const clean = String(text || '').slice(0, 240);
  if (clean.trim()) {
    state.notes.set(id, clean);
    if (state.verdicts.get(id) !== 'fix') state.verdicts.set(id, 'fix');
  } else {
    state.notes.delete(id);
  }
  store.save();
  const node = els.list.querySelector(`[data-id="${id}"]`);
  if (node) paintRow(node);
  updateMeter();
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
  const fixes = sentences.filter((row) => state.verdicts.get(row.id) === 'fix');
  if (!fixes.length) return `${code} ${checkpoint} PASS played=${state.heard.size}`;
  const lines = [`${code} ${checkpoint} FIX ${fixes.map((row) => row.id).join(' ')}`];
  for (const row of fixes) {
    const note = (state.notes.get(row.id) || '').trim();
    if (note) lines.push(`${row.id}: ${note}`);
  }
  return lines.join('\n');
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
