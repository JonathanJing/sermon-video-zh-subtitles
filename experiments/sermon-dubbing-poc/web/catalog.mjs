const blockKey = value => typeof value === 'string' ? value : Number.isSafeInteger(value) && value >= 0 ? String(value) : null;
const validBlockKey = value => typeof value === 'string' && value.length > 0 && value.length <= 128 && value.trim() === value && !/[\u0000-\u001f\u007f]/.test(value);

function validateTranscript(week) {
  const transcript = week.transcript;
  if (transcript == null) return;
  if (transcript.schemaVersion !== 'sermon-bilingual-transcript-v1' || !Array.isArray(transcript.blocks)) throw new Error('Invalid bilingual transcript');
  const ids = new Set();
  for (const block of transcript.blocks) {
    if (!validBlockKey(block.blockId) || ids.has(block.blockId)
        || [block.sourceTextOrigin, block.reviewState, ...[block.english, block.chinese].filter(v => v != null)]
          .some(v => typeof v !== 'string' || !v.trim())) throw new Error('Invalid bilingual source block');
    ids.add(block.blockId);
  }
  for (const cue of week.tracks.flatMap(t => t.cues)) {
    if (cue.blockId != null && (!validBlockKey(blockKey(cue.blockId)) || (ids.size && !ids.has(blockKey(cue.blockId))))) throw new Error('Unlinked bilingual cue');
  }
}

// Same association rule as iOS: show the complete English source once, after
// the last Chinese cue bearing its ID. Never infer links from text or timing.
export function bilingualCueRows(week, track) {
  const originals = new Map(), ambiguous = new Set(), lastCue = new Map();
  if (week?.transcript?.schemaVersion === 'sermon-bilingual-transcript-v1') {
    for (const block of week.transcript.blocks) {
      if (originals.has(block.blockId)) ambiguous.add(block.blockId);
      originals.set(block.blockId, block);
    }
  }
  track.cues.forEach((cue, index) => {
    const id = blockKey(cue.blockId);
    if (id != null) lastCue.set(id, index);
  });
  let missingEnglish = false;
  const rows = track.cues.map((cue, index) => {
    const id = blockKey(cue.blockId), block = ambiguous.has(id) ? null : originals.get(id);
    const hasEnglish = typeof block?.english === 'string' && !!block.english.trim();
    if (!hasEnglish) missingEnglish = true;
    return { cue, index, english: hasEnglish && lastCue.get(id) === index ? block.english : null };
  });
  return { rows, hasEnglish: rows.some(row => row.english != null), missingEnglish };
}

export function validateCatalog(catalog) {
  if (catalog?.schemaVersion !== "sermon-weekly-catalog-v1" || !catalog.weeks?.length) throw new Error("Invalid catalog");
  const ids = new Set();
  for (const week of catalog.weeks) {
    if (ids.has(week.id) || !week.title || !week.speaker || !Array.isArray(week.tracks)) throw new Error("Invalid week");
    ids.add(week.id);
    validateTranscript(week);
    for (const track of week.tracks) {
      if (!/^\/media\/[a-zA-Z0-9_.-]+\.mp3$/.test(track.audioUrl) || !(track.durationSeconds > 0) || !track.cues?.length) throw new Error("Invalid track");
      let previous = 0;
      for (const cue of track.cues) {
        if (!(previous <= cue.start && cue.start < cue.end && cue.end <= track.durationSeconds + 0.001) || !cue.text?.trim()) throw new Error("Invalid cues");
        previous = cue.end;
      }
    }
  }
  if (!ids.has(catalog.defaultWeekId)) throw new Error("Missing default week");
  for (const speaker of catalog.voiceBank?.speakers || []) {
    if (!speaker.name || !speaker.id) throw new Error("Invalid speaker");
    for (const key of ["reference", "chinese"]) {
      const track = speaker[key];
      if (!/^\/media\/[a-zA-Z0-9_.-]+\.mp3$/.test(track?.audioUrl) || !(track.durationSeconds > 0)) throw new Error("Invalid speaker audition");
    }
  }
  return catalog;
}

export function chooseWeek(catalog, id) {
  return catalog.weeks.find(w => w.id === id) || catalog.weeks.find(w => w.id === catalog.defaultWeekId);
}

export function parseTimecode(value) {
  const match = /^(?:(\d{1,2}):)?(\d{1,3}):(\d{2})(?:\.(\d{1,2}))?$/.exec(value.trim());
  if (!match || Number(match[3]) >= 60 || (match[1] && Number(match[2]) >= 60)) return null;
  return Number(match[1] || 0) * 3600 + Number(match[2]) * 60 + Number(match[3]) + Number(`0.${match[4] || 0}`);
}
