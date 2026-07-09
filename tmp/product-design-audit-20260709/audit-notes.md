# UI / HCI Audit - 2026-07-09

## Audit scope

- Surfaces: congregation page and admin page.
- Primary admin device: iPhone, 390 x 844 viewport.
- Primary operator goal: scheduled live-link capture -> transcription -> translation -> PDF/SRT/page output -> open admin -> start captions.
- Evidence source: current deployed UI captured before changes, then local implementation captured after changes.

## Flow steps

1. Congregation opens the subtitle page - Healthy.
   - Evidence: `01-public-iphone-current.png`, `07-public-desktop-current.png`, `12-public-iphone-final.png`.
   - The current caption and sermon title dominate the reading surface and the page has no horizontal overflow.
   - The disclaimer remains visible but is capped to a 150px internal scroll area on iPhone.

2. Operator opens admin and checks Sunday readiness - Improved from high friction to healthy.
   - Before: `02-admin-iphone-current.png`.
   - The four KPI cards consumed most of the first screen and showed a raw ISO timestamp.
   - After: `11-admin-iphone-final.png`.
   - KPI cards use a 2 x 2 mobile grid and compact PT timestamps.

3. Operator confirms capture and generation progress - Improved.
   - Before: `03-admin-iphone-prepare-current.png`, `04-admin-iphone-generation-current.png`, `05-admin-iphone-pipeline-current.png`.
   - Manual inputs, GCS fields, Cloud Run test data, source candidates, and latency tools appeared before the final action.
   - After: the four-step main flow is visible near the top; detailed pipeline and tests are in the collapsed Advanced tools disclosure.

4. Operator starts captions - Improved from critical friction to healthy.
   - Before: `06-admin-iphone-playback-current.png`.
   - The start action was around 6385px down a roughly 7115px mobile page and competed with pause/resume/end, timing offsets, jump, freeze, and exports.
   - After: `11-admin-iphone-final.png`.
   - Start captions is fully visible in the first 844px viewport, is 44px tall, and pause/resume/end appear only when relevant.

5. Operator optionally reviews captions or uses diagnostics - Healthy.
   - Caption review starts collapsed at about 70px and expands to a scrollable area around 354px.
   - Manual capture, Cloud Run tests, latency tests, logs, timing calibration, and exports remain available in collapsed advanced sections.

6. Operator uses the desktop fallback - Healthy.
   - Evidence: `14-admin-desktop-final.png`.
   - The same primary flow remains visible, with advanced tools collapsed and no horizontal overflow.

## Highest-impact findings

1. The old admin hierarchy optimized for diagnostics rather than the Sunday operator task.
2. The final action was effectively undiscoverable on iPhone because it lived at the bottom of a very long page.
3. Controls were always visible even when they were not valid for the current playback state.
4. The public page was already structurally sound; the main risk was admin complexity, not congregation readability.

## Accessibility and HCI notes

- Primary iPhone actions are at least 44px tall.
- There is no horizontal overflow at 390px.
- Native `details` / `summary` controls preserve keyboard and assistive-technology disclosure semantics.
- Status changes use existing live regions and explicit text rather than color alone.
- Screenshot review cannot prove full screen-reader behavior, VoiceOver announcements, contrast ratios, or real network/error recovery. Those still require device and assistive-technology testing.
