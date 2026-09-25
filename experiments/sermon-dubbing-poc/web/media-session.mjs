// Browser-owned lock-screen / media surfaces. This does not create ActivityKit
// Live Activities or claim control over the shape of the Dynamic Island.
export function createMediaSession({ audio, getSelection, play, pause, seek,
  session = globalThis.navigator?.mediaSession, Metadata = globalThis.MediaMetadata } = {}) {
  if (!session) return { update() {}, dispose() {} };
  let signature = null;
  let handlersBound = false;
  const actions = {
    play: () => play(), pause: () => pause(),
    seekbackward: details => seek(Math.max(0, audio.currentTime - (details?.seekOffset || 5))),
    seekforward: details => seek(Math.min(audio.duration, audio.currentTime + (details?.seekOffset || 5))),
    seekto: details => { if (Number.isFinite(details?.seekTime)) seek(details.seekTime); },
    stop: () => pause(),
  };
  function setHandlers(enabled) {
    if (handlersBound === enabled) return;
    for (const [action, handler] of Object.entries(actions)) {
      try { session.setActionHandler(action, enabled ? handler : null); } catch { /* Browser-specific supported actions. */ }
    }
    handlersBound = enabled;
  }
  function update() {
    const selected = getSelection();
    if (!selected?.track) {
      setHandlers(false);
      signature = null; session.metadata = null; session.playbackState = 'none';
      try { session.setPositionState?.(); } catch {}
      return;
    }
    setHandlers(true);
    const metadata = { title: selected.week.title, artist: selected.week.speaker,
      album: selected.album || '同行 · 证道中文听译',
      artwork: [{ src: selected.artwork || '/brand-icon.png', sizes: '1024x1024', type: 'image/png' }] };
    const key = JSON.stringify(metadata);
    if (key !== signature) { session.metadata = Metadata ? new Metadata(metadata) : metadata; signature = key; }
    session.playbackState = audio.paused ? 'paused' : 'playing';
    if (Number.isFinite(audio.duration) && audio.duration > 0 && Number.isFinite(audio.currentTime)
        && Number.isFinite(audio.playbackRate) && audio.playbackRate > 0) {
      try { session.setPositionState?.({ duration: audio.duration, position: Math.max(0, Math.min(audio.duration, audio.currentTime)), playbackRate: audio.playbackRate }); } catch {}
    } else {
      // A new track can have metadata before its media duration is available.
      // Clear the previous track's lock-screen position during that interval.
      try { session.setPositionState?.(); } catch {}
    }
  }
  return { update, dispose() {
    setHandlers(false);
    session.metadata = null; session.playbackState = 'none';
    try { session.setPositionState?.(); } catch {}
  } };
}
