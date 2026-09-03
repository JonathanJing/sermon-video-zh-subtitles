# Design QA

Date: 2026-09-03

## Evidence

- Source visual: `/Users/jonathan_jing/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/tmp/product-design-audit-20260709-user-display/01-current-desktop.png`
- Implementation: `http://127.0.0.1:4173/`
- Verified viewport: 1440 x 900 in the Codex in-app browser.

The source visual supplied the navy/white caption-stage direction. The implementation intentionally removes its navigation, scripture/sidebar controls, publishing actions, timeline, and secondary workflows to match the KISS audit.

## Visual comparison

| Check | Result |
|---|---|
| Large Chinese caption is the dominant element | Pass |
| English source remains visible but clearly secondary | Pass |
| Microphone, timer, and one primary action fit in one compact row | Pass |
| Status and evidence links stay outside the caption reading area | Pass |
| No layout overflow or clipping at 1440 x 900 | Pass |
| Simulated captions cannot be mistaken for model output | Pass |

## Interaction verification

- MacBook Pro built-in microphone was discovered and selected.
- Start changed the page to the recording state.
- The live level meter reached 23% and the timer advanced past 13 seconds.
- Stop released the recording state and exposed a 219 KB audio download.
- The session exposed a JSON log download with 11 recorded events.
- A stalled permission request is bounded by an eight-second timeout and returns to a retryable error state.

## Severity review

- P0: none.
- P1: none.
- P2: none.
- P3: none observed in the tested desktop path.

Known scope boundary: ASR, translation, context retrieval, incremental gateway recording, and offline replay are not implemented. The UI labels those dependencies as pending.
