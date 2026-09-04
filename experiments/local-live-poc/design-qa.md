# Design QA

Date: 2026-09-04

## Evidence

- Selected visual source: `/Users/jonathan_jing/.codex/generated_images/01a06885-13ce-7893-b285-83345a437d3b/exec-d066f367-b060-4dfd-b110-d1e6aee8ef38.png` (`1586 x 992`).
- Browser implementation capture: `/tmp/sermon-caption-implementation.jpg` (`1280 x 720`).
- Same-input comparison artifact: `/tmp/sermon-caption-ab-comparison.png` (`1920 x 600`), with the selected source on the left and browser implementation on the right.
- Implementation: `http://127.0.0.1:4174/?captionDemo=1`.
- State: deterministic previous-final and current-streaming bilingual captions. The page visibly labels this as interface demo data, not model output.
- Normalization: each side was fit without cropping into a `960 x 600` comparison panel. The implementation retains its wider browser viewport with letterboxing; raw coordinates were not compared across different aspect ratios.

## Full-view comparison

- The implementation preserves the selected hierarchy: muted previous Chinese and English, a thin divider, then dominant current Chinese with secondary English.
- The current Chinese remains the largest object on screen and keeps the existing high-contrast distance-reading treatment.
- The previous caption uses muted colors instead of lowering the opacity of the whole region, so it remains readable without competing with the current sentence.
- The existing microphone controls, timer, model/status footer, and restart control remain intact. This is an intentional POC constraint even where their exact proportions differ from the generated visual.
- At `1280 x 720`, the longer current Chinese wraps to two lines without clipping or colliding with the footer.

Focused-region comparison was not required because the complete caption stage, controls, and footer were all visible in the same full-page comparison.

## Responsive and interaction checks

- Operator CSS keeps the active Chinese at `54–80 px` on narrow screens and the previous Chinese at `25–38 px`, with independent fixed grid regions to avoid vertical jumping.
- The read-only phone viewer uses the same previous/current state model and includes a low-height landscape breakpoint.
- `prefers-reduced-motion` removes the one-time previous-caption entrance animation.
- Automated state tests verify that only a completed bilingual final moves to the previous region, unfinished text cannot replace it, and stale segment events are ignored.
- Viewer tests verify snapshot reconstruction and the transition from a completed segment to the next ASR final.
- Browser-rendered desktop inspection showed no clipping or horizontal overflow. A dedicated device-emulated screenshot was not available in the in-app browser, so phone geometry is covered by responsive CSS review and automated viewer behavior tests rather than claimed as pixel-verified.

## Findings

- P0: none.
- P1: none.
- P2: none after implementation review.
- P3: the implementation viewport is wider than the generated reference, so the exact Chinese line break differs; both remain a two-line composition and preserve the intended hierarchy.

## Comparison history

1. The A baseline displayed only one bilingual segment and could briefly pair new English with the previous Chinese.
2. The first B implementation introduced explicit `previousFinal` and `active` state, a stable two-tier grid, and matching phone-viewer snapshots.
3. Browser comparison against the selected mock confirmed the hierarchy and exposed no blocking visual mismatch.

## Verification

- Frontend unit tests: 11 passed.
- Viewer-server tests: 6 passed.
- Gateway/live-server integration tests: 15 passed using the existing POC virtual environment.
- Production frontend build: passed.
- `git diff --check`: passed.

final result: passed
