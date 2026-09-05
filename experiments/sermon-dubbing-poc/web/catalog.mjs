export function validateCatalog(catalog) {
  if (catalog?.schemaVersion !== "sermon-weekly-catalog-v1" || !catalog.weeks?.length) throw new Error("Invalid catalog");
  const ids = new Set();
  for (const week of catalog.weeks) {
    if (ids.has(week.id) || !week.title || !week.speaker || !Array.isArray(week.tracks)) throw new Error("Invalid week");
    ids.add(week.id);
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
