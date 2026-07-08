# Product Design UI Audit - 2026-07-07

## Scope

- Public congregation page: `web/index.html`
- Admin operator page: `web/admin.html`
- Viewports checked: iPhone 390x844, desktop 1366x900
- Evidence folder: `tmp/product-design-audit-20260707/`

## Screenshots

1. `01-public-iphone-before.png` - public page, iPhone baseline, healthy
2. `02-public-desktop-before.png` - public page, desktop baseline
3. `03-admin-iphone-before.png` - admin page, iPhone baseline, review list over-expands
4. `04-admin-desktop-before.png` - admin page, desktop baseline
5. `09-admin-iphone-after-final.png` - admin page, iPhone after resize fix
6. `10-admin-iphone-review-controls-after.png` - admin page, iPhone review controls in view
7. `08-admin-desktop-after-versioned.png` - admin page, desktop after resize fix
8. `11-public-iphone-final.png` - public page, iPhone after clear sidebar labels and compact disclaimer
9. `12-admin-iphone-review-final.png` - admin page, iPhone final review controls check

## Public Page Audit

User goal: open the congregation page quickly and read current Chinese captions with scripture context.

Strengths:

- The first mobile viewport prioritizes the caption experience and disclaimer before secondary details.
- Public page has no visible operator-only controls.
- No horizontal overflow was detected at 390px.

Risks:

- The scripture toggle uses single-character labels on mobile. This is compact, but it relies on `aria-label` and title text for clarity.
- Long disclaimer copy is necessary for trust, but it takes meaningful vertical space before captions.

Recommendation:

- Keep the current public layout for this change. It is stable and should not inherit admin-only controls.

## Admin Page Audit

User goal: operate live/review subtitles from an iPhone without losing access to key controls.

Strengths:

- Admin status, caption preview, source controls, and footer sync actions are separated by task.
- Primary tap targets are mostly 36-44px high and usable on touch.
- No horizontal overflow was detected at 390px after the fix.

Baseline risks:

- Before the fix, the iPhone admin review list expanded to about 8807px, making later admin controls hard to reach.
- The subtitle review area had no direct way to compact, expand, or temporarily hide the list.
- The old CSS/JS query versions could let browsers keep stale assets after a UI change.

Changes made:

- Added admin-only subtitle review controls: small, collapse/expand, large.
- Added `data-review-size` and `data-review-collapsed` state on the admin shell.
- Constrained the mobile admin review list to controlled heights with internal scrolling.
- Bumped shared CSS/JS cache-buster query strings in both public and admin HTML.
- Replaced public single-character scripture sidebar controls with clear labels.
- Capped the mobile disclaimer block at 150px with internal scrolling so captions appear sooner.

After-fix checks:

- Standard iPhone admin review strip: 354px, internal segment list: 130px.
- Large mode: review strip 523px, internal segment list 325px.
- Collapsed mode: review strip 58px and list hidden.
- Resize controls are visible, touch-sized, and do not introduce horizontal overflow.
- Final public iPhone check: no horizontal overflow; disclaimer is 150px; top sidebar control reads "经文侧栏".

Accessibility notes:

- The new controls have explicit `aria-label`, `title`, and `aria-pressed` state.
- Screenshot review cannot prove full keyboard or screen-reader behavior. The DOM and JS contract were checked through targeted tests.
