# Design QA — congregation paragraph captions

## Comparison target

- Source visual truth: `/Users/jonyopenclaw/.codex/generated_images/019f4909-9896-7c11-9013-81cbd9f17327/exec-f108814d-fb62-4201-b3c5-f67cec57063f.png`
- Final implementation screenshot: `/Users/jonyopenclaw/sermon-video-zh-subtitles/tmp/product-design-qa-20260709-paragraph/11-final-matched-state-390x844.png`
- Final combined evidence: `/Users/jonyopenclaw/sermon-video-zh-subtitles/tmp/product-design-qa-20260709-paragraph/12-final-matched-source-left-implementation-right.png`
- Viewport: `390 × 844`
- State: congregation page, paragraph mode, complete reviewed subtitle track loaded, historical cue at `28:18` selected so current/previous/next context and `回到现场` are visible.

## Full-view comparison evidence

The final side-by-side comparison uses the selected generated concept on the left and the browser-rendered implementation on the right. Both are normalized to the same `390 × 844` viewport. The implementation preserves the source hierarchy: compact Mariners header, three primary controls, compact sermon title, dominant navy reading surface, progress/live row, four-sentence context window, and one high-contrast current-sentence block.

Focused-region comparison was not required because the full-view composite preserves the native mobile viewport and keeps the typography, controls, progress row, sentence spacing, and current marker readable at inspection size.

## Findings

- No remaining P0, P1, or P2 findings.
- [P3] The generated source uses small decorative icons and a circular Mariners mark; the implementation keeps the existing product's text-only controls and avoids introducing a new remote icon dependency. Labels, focus states, and tap targets remain clear.
- [P3] Dynamic sermon sentences differ from the illustrative mock copy. The implementation intentionally renders the real published subtitle track while matching the same four-sentence hierarchy.

## Required fidelity surfaces

- Fonts and typography: passed. Existing system CJK stack is preserved; mobile context text is `18.9px` with a `1.48` line height, and the current sentence is `23.7px`, bold, and readable without clipping.
- Spacing and layout rhythm: passed. The navy reading surface dominates the phone viewport, the sermon title is compact, and the full transcript stays below the primary live-reading surface.
- Colors and visual tokens: passed. Existing white/blue product tokens are retained; current sentence uses solid `#174c83` with white text and a blue current marker against the navy stage.
- Image quality and asset fidelity: passed. The target contains no photographic or illustrative assets. No placeholder imagery, custom SVG art, CSS illustrations, or low-resolution replacements were introduced.
- Copy and content: passed. Live UI labels are Chinese-first, the sermon title is shortened only for the congregation display while retaining the full value in the title attribute, and English transcript text remains out of the paragraph view.
- Icons: acceptable P3 deviation noted above; no fake glyph or handmade icon substitutes were introduced.
- Accessibility: passed for visible implementation checks. Current state uses text, weight, background, and marker rather than color alone; focus indicators remain; the current sentence has `aria-current`; only the current sentence is announced in the polite live region; reduced-motion rules remain active.
- Responsiveness: passed at `390×844`, `1024×768`, `1366×900`, and `1440×900`; no horizontal overflow was detected.

## Comparison history

### Iteration 1

- Evidence: `04-source-left-implementation-right.png`
- [P1] Caption surface was too short, so the complete-transcript panel entered the first viewport and weakened the selected concept's primary hierarchy.
- [P2] The sermon metadata and disclaimer consumed too much space above the live reading surface.
- [P2] Programmatic transcript scrolling could briefly expose `回到现场` on initial load.

Fixes made:

- Expanded the mobile paragraph surface and moved the full transcript below the first reading viewport.
- Removed the outer mobile stage card, compacted the sermon row, shortened the public display title, and moved the collapsible disclaimer below the transcript while preserving its full content.
- Extended the programmatic-scroll guard and recomputed follow state after layout settled.

### Iteration 2

- Evidence: `06-source-left-implementation-pass2-right.png`
- The main hierarchy matched, but the navy stage still ended earlier than the source and the sermon title retained a redundant publisher suffix.

Fixes made:

- Increased the mobile stage to `clamp(580px, 75svh, 640px)`.
- Removed the trailing `| Mariners Church` only from the congregation display string while preserving the complete title as metadata.

### Final pass

- Evidence: `12-final-matched-source-left-implementation-right.png`
- Browser-rendered viewport: `390 × 844`.
- Primary interactions tested: paragraph-to-focus toggle and focus-to-paragraph toggle.
- Responsive regression: phone, iPad, desktop, wide desktop, autoplay parameter, admin desktop, and admin iPad passed.
- Browser console warnings/errors: none.
- Remaining differences are P3 only.

## Implementation checklist

- [x] Paragraph mode is the congregation default.
- [x] Focus mode remains available from the header.
- [x] Complete reviewed tracks show up to four contextual sentence groups.
- [x] Realtime-only tracks stay lightweight and do not expose future text.
- [x] Current sentence, timestamp, progress, history selection, and return-to-live state update together.
- [x] Full disclaimer remains accessible.
- [x] Mobile, tablet, desktop, realtime-runtime, and public/admin boundary checks pass.

final result: passed
