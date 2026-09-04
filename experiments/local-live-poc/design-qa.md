# Design QA

Date: 2026-09-03

## Evidence

- Source visual truth: `/Users/jonathan_jing/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/tmp/product-design-audit-20260709-user-display/01-current-desktop.png`
- Source pixels: 1280 x 720.
- Implementation: `http://127.0.0.1:4173/`.
- Implementation screenshots: browser-rendered captures inspected in the Codex in-app browser during this QA run; the browser API did not persist local screenshot files.
- Desktop viewport and screenshot: 1440 x 900 CSS px, density 1.
- Mobile viewport and screenshot: 393 x 852 CSS px, density 1.
- State: active microphone recording with Chinese and English demo captions visible.
- Normalization: content viewport only; no browser chrome or device frame. The desktop source and implementation were emitted together in the same comparison view. Their aspect ratios differ, so composition was compared by occupied viewport proportions rather than raw pixel coordinates.

The source visual supplies the navy/white caption-stage direction. The implementation intentionally removes navigation, publishing actions, scripture controls, timeline, and secondary workflows according to the KISS audit. The mobile layout has no separate source image; its target is the user's responsive requirement that Chinese remain the largest readable element without changing the English size.

## Full-view comparison evidence

- Desktop Chinese increased from the earlier 78 px ceiling to a viewport-aware 72–118 px range. At 1440 x 900 the active Chinese caption occupied two high-contrast lines in the center stage without clipping.
- Mobile Chinese uses a 46–64 px range. At 393 x 852 the longer active sentence occupied three lines, while the English source remained fully visible beneath it.
- Controls and the evidence footer remained visible at both viewports. No horizontal overflow, clipped persistent action, or caption/footer collision was observed.
- The final active-state desktop capture was visually compared with the source in one comparison input.

Focused-region comparison was not required: the only changed fidelity surface was the central text block, and its Chinese wrapping, English hierarchy, margins, and line height were clearly readable in the full-view captures.

## Required fidelity surfaces

- Fonts and typography: system CJK stack retained; Chinese is 800 weight with 1.18 desktop and 1.2 mobile line height; English size and hierarchy are unchanged; both language blocks wrap without truncation.
- Spacing and layout rhythm: desktop control and footer heights are unchanged. Mobile controls use a compact two-column arrangement so the caption stage retains most of the remaining height.
- Colors and tokens: existing navy, white, muted English, warning, and state colors are unchanged and maintain strong contrast.
- Image quality and assets: no image or icon assets are present or required.
- Copy and content: demo-data warning remains visible; Chinese and English content are unchanged.

## Interaction verification

- iPhone viewport: microphone start, running state, active caption, stop, and generated download links verified.
- MacBook viewport: live level reached 63%, timer advanced, active captions rotated, and stop generated a 227 KB recording plus an 11-event log.
- Browser console: no warning or error entries after the responsive tests.

## Findings

- P0: none.
- P1: none.
- P2: none.
- P3: none observed in the two target viewports.

## Comparison history

1. Earlier desktop implementation capped Chinese at 78 px; it was readable but did not use the available viewing distance and stage area.
2. First responsive pass increased desktop Chinese to 72–118 px and mobile Chinese to 44–60 px, and compacted mobile controls.
3. Mobile active-state inspection showed unused stage space, so the mobile range was increased to 46–64 px.
4. Post-fix captures at 393 x 852 and 1440 x 900 showed no clipping, overflow, action loss, or English-size regression.

## Open questions

- Real ASR can emit longer clauses than the demo data. The later gateway should cap stable subtitle segments by time/character count rather than shrinking the display font dynamically.

## Implementation checklist

- [x] Maximize Chinese size on MacBook Pro.
- [x] Maximize Chinese size on iPhone while preserving controls and English.
- [x] Verify active recording at both target viewports.
- [x] Check browser warnings/errors.

final result: passed
