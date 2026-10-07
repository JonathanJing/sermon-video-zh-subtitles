// Display metadata never changes review or playback eligibility.
export function categoryLabel(category, locale) {
  if (!category || category.schemaVersion !== 'sermon-page-display-category-v1') return null;
  const labels = category.labels;
  if (!labels || typeof labels !== 'object' || !Object.hasOwn(labels, 'en')) return null;
  const entries = Object.entries(labels);
  if (!entries.length || entries.length > 16 || entries.some(([key, value]) =>
    !/^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$/.test(key) || typeof value !== 'string'
    || !value.trim() || [...value].length > 48 || /[\u0000-\u001f\u007f-\u009f\u2028\u2029]/u.test(value))) return null;
  const normalized = String(locale || 'en').replace('_', '-');
  if (Object.hasOwn(labels, normalized)) return labels[normalized];
  if (/^zh(?:-(?:CN|Hans|SG))?$/i.test(normalized)) {
    for (const key of ['zh-Hans', 'zh-CN', 'zh-SG', 'zh']) if (labels[key]) return labels[key];
  }
  return labels[normalized.split('-')[0]] || labels.en;
}

// Full text uses its explicit group identity to locate the audio, never the
// source-video clock. Missing/ambiguous associations stay reading-only.
export function fullReadingRows(fullText, cues) {
  const mapped = new Map();
  for (const cue of cues || []) {
    const id = cue.textGroupId;
    if (id != null) mapped.set(id, mapped.has(id) ? null : cue);
  }
  return (fullText || []).map(cue => ({ cue, audioCue: mapped.get(cue.textGroupId) || null }));
}

export function findEnglishPositions(rows, query) {
  const terms = String(query || '').toLocaleLowerCase('en').trim().split(/\s+/).filter(Boolean);
  if (!terms.length) return [];
  return rows.filter(row => typeof row.english === 'string' && terms.every(term =>
    row.english.toLocaleLowerCase('en').includes(term))).slice(0, 40);
}

export class ReadingFollow {
  following = true;
  reset() { this.following = true; }
  userScroll() { this.following = false; }
  returnToCurrent(scroll) { this.following = true; scroll(); }
  update({ active, playing, changed }, scroll) {
    if (active && playing && changed && this.following) scroll();
  }
}
