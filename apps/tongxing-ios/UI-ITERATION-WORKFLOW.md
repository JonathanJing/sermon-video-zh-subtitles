# Tongxing: Xcode-first UI and UX iteration

[简体中文](UI-ITERATION-WORKFLOW.zh.md) · [iOS design rules](DESIGN.zh.md) · [Implementation and validation](AGENTS.md)

Decision date: 2026-09-30. **iOS is the primary experience; the Firebase-hosted browser app is secondary. Figma is not part of the current workflow.** This document records the agreed process, not completed preview automation, UI changes, testing, or publication.

## 1. Design in the running app

For small layout, copy, control, and interaction changes, use existing SwiftUI code in Xcode as the design workspace. Use Canvas/Previews for isolated views when suitable fixtures exist; use the iPhone simulator for the complete flow and a real iPhone for device-dependent acceptance. Apple describes previews as interactive, code-backed views in the Xcode canvas: [Previews in Xcode](https://developer.apple.com/documentation/swiftui/previews-in-xcode).

Open the existing project from the repository root on the development Mac:

```sh
open apps/tongxing-ios/Tongxing.xcodeproj
```

Start with `App/ContentView.swift`, `App/PlaybackDock.swift`, and `App/DesignSystem.swift`. Reuse `AppModel` and the existing `PlaybackController`; do not create another player or duplicate application state to make a screenshot look right. A view requiring model dependencies may need a fixture-backed preview; opening the file alone does not prove a preview works. Use the running simulator rather than blocking a small change on a new preview system.

The design baseline is the **accepted iOS revision, its actual screenshots, and its interaction rules**, not an unversioned image. SwiftUI code defines implementation; existing design rules define shared intent; screenshots demonstrate only the captured state. System materials, safe areas, Dynamic Type, and accessibility take precedence over matching fixed pixels.

## 2. The small-change loop

**Screenshot/annotation → scoped SwiftUI change → build and real interaction checks → independent review and iOS acceptance → browser applicability decision → optional web adaptation → authorized weekly release.**

| Step | Action and exit evidence |
| --- | --- |
| Request | Jonathan supplies a screenshot with numbered marks and the desired result. For UX, add current state → action → expected result. Codex records the affected screen and what must remain unchanged; infer routine spacing from existing rules instead of asking for pixel values. |
| Baseline | Read current branch/diff and local instructions. Use a dedicated branch from current `dev`, without modifying concurrent branches. Reproduce the relevant state and record its base commit before editing. |
| Native iteration | Patch only affected SwiftUI/components/localized strings. Return actual before/after captures using the same content, device configuration, and state. Generated mockups are not execution evidence. |
| Check and review | Run affected checks, retain failures/skips, and have a separate reviewer inspect the exact revision read-only. The author repairs findings and reruns affected checks; the reviewer does not edit and approve their own repair. |
| iOS acceptance | Jonathan or an explicitly delegated human accepts the exact revision and changed interaction. Machine review does not supply this approval. Do not ask again for unchanged evidence; a material change invalidates only its affected acceptance. |
| Browser decision | Record `required`, `not_applicable`, or `deferred` with a reason and, for deferred work, a linked follow-up. Adapt only after the iOS baseline is accepted. |
| Release candidate | Open/update the PR with evidence, independent review status, browser disposition, and remaining gaps. Group accepted changes into the weekly candidate; merging, TestFlight distribution, and production deployment remain separately authorized actions. |

Keep the loop bounded: record the repair limit in the task (default: two targeted repair rounds). On exhaustion, preserve the best verified revision and report the specific blocker; do not endlessly regenerate or silently widen scope. A blocked item may move to the next candidate without holding unrelated accepted changes. This is a collaboration rule, not a new production scheduler, model policy, or RQC implementation.

A large navigation change or a new multi-screen feature needs a scoped interaction plan before coding; it does not automatically introduce Figma or a separate design-tool dependency.

## 3. Evidence and proportional checks

The user provides the problem, not a testing form. Codex fills in a short record in the PR/task:

| Record | Minimum information |
| --- | --- |
| Identity | Task/annotation IDs, base and candidate commit, app build identity, affected files. |
| Reproduction | Device class, OS/Xcode, orientation, appearance, UI/content language, text size, fixture/content identity, playback/download state, and exact interaction steps. Avoid private device identifiers in public records. |
| Results | Before/after captures, commands and exit codes, actual passed/failed/skipped counts, independent-review result, human-acceptance receipt, and unresolved checks. Use `not_run` for unexecuted work. |
| Web handoff | Accepted iOS commit and capture references, intended shared changes, allowed platform differences, browser scope and result. |

Use synthetic or already authorized fixtures; keep private sermons, personal data, credentials, recordings, and raw logs out of Git. Store captures/build outputs in ignored `artifacts/tongxing-ios/<date>/...`; attach only sanitized evidence to an authorized PR or artifact store. A local path alone is not a reviewer-accessible attachment. Do not replace old evidence or relabel it for a new commit.

For UI changes, build first, select relevant `TongxingUITests` from the current source, and exercise the affected interaction. The supported entry point is [scripts/ios.sh](scripts/ios.sh); command and shared-simulator rules remain in [AGENTS.md](AGENTS.md). `launch` uses an existing build and does not rebuild. Inspect the current UI hierarchy before operating controls; refresh it after layout changes. Use available local tools, and report a missing simulator/tool connection rather than claiming remote screenshots were taken. See OpenAI's [image-input guidance](https://learn.chatgpt.com/docs/image-inputs).

Check affected layouts with long subtitles, small screens, large text, and light/dark appearances; add landscape, reduced transparency, contrast, VoiceOver/focus, or long localized labels where affected. An interaction change must be exercised, not accepted from a static picture. Label actual platform coverage; missing required coverage blocks that acceptance, not unrelated work.

Preserve these boundaries unless the task explicitly changes them: playback intent/position, audio source, download/hash integrity, subtitle synchronization, interface-language versus audio-language semantics, source/review notices, privacy/telemetry choices, and microphone permissions. A changed menu or control can affect behavior even when the patch is called cosmetic. Run the relevant player/storage/core checks when those boundaries are touched. Do not rerun ASR, translation, TTS, full-video production, or paid model stages merely to adjust UI.

## 4. Browser adaptation, not a pixel clone

The secondary client is the **Firebase-hosted web UI**; Firebase content hosting remains independent of this product priority. Codex edits the existing web implementation using the accepted iOS captures **plus** interaction notes and semantic styling, not an image alone. Do not assume SwiftUI turns into web code or that screenshots encode responsive rules.

Share brand, terminology, content hierarchy, primary-action emphasis, and honest state labels. Preserve browser-appropriate responsive layout, semantic controls, keyboard/focus behavior, scrolling, and capability fallbacks. Do not copy iPhone chrome, system sheets, or native-only capabilities literally. Check affected pages in mobile Safari and desktop browsers; record exact browsers/viewports tested and gaps. Preserve supported non-iOS access.

A typography change may require adaptation; a native toolbar adjustment may be `not_applicable`. Browser support for a capability must be proven before displaying its native-style success state, especially offline/download or background-playback claims. Shared labels must describe the platform's actual behavior.

Keep catalog/release schemas, immutable content identities, URLs, hashes, and existing clients compatible. Cosmetic web follow-up need not delay an independently compatible iOS release. A shared-contract change or explicitly coupled release plan requires the corresponding cross-client gate; visual acceptance does not waive it. This workflow does not authorize upstream content edits or deployment.

## 5. Weekly delivery and release boundaries

Collect small requests during the week, complete short verified loops, then freeze a candidate and run the applicable release regression. Record native build/tests, human UI acceptance, device acceptance, browser checks, TestFlight, App Store review, web deployment, and venue acceptance separately. Reuse unchanged valid evidence; follow [RELEASE-READINESS.zh.md](RELEASE-READINESS.zh.md), not historical test counts, for remaining release work.

Docs-only changes do not deliver a new UI. Bundled SwiftUI changes require a new app build; Firebase deployment does not update installed native SwiftUI. App Store versions go through review, and external TestFlight builds may need beta review; weekly iteration is a target cadence, not a guaranteed approval date. See Apple's [App Review overview](https://developer.apple.com/help/app-store-connect/manage-submissions-to-app-review/overview-of-submitting-for-review/) and [TestFlight overview](https://developer.apple.com/help/app-store-connect/test-a-beta-version/testflight-overview/).

Before an authorized release, identify the candidate commits/build and known-good fallback. A code revert still requires a new native build and the applicable distribution/review process; do not promise instant rollback of installed App Store apps. A web rollback must retain content compatibility and follow its own deployment authorization. Avoid last-minute UI experiments in the Sunday service window.

## 6. Reusable Codex task

```text
Tongxing UI/UX iteration. Use the attached numbered screenshot and requested results.
Keep Xcode/SwiftUI iOS primary; do not introduce Figma.
Changes: [numbered annotations; for UX: state -> action -> expected result].
Read current instructions and diffs. Reuse components and preserve unrelated behavior.
Record the baseline; implement on a dedicated dev-based branch; default to two repair rounds.
Build/run, exercise changed interactions, and provide comparable before/after captures.
Report exact commits, actual checks/skips, independent review and remaining gaps.
Do not mark human acceptance yourself or perform unrelated refactors/production runs.
After iOS acceptance, assess and optionally adapt the Firebase web UI; keep responsive behavior.
Submit a PR. Do not merge, distribute TestFlight, or deploy without applicable authorization.
```

## 7. First implementation slice (not completed by this document)

Use the next real annotated request on the existing listening page as the pilot. First reuse existing UI-test fixtures and screenshot tools. Add a small preview fixture or stable accessibility identifier only when needed; do not start a generalized screenshot platform. Complete one real native before/after loop, read-only review, and human acceptance; then record the browser decision and any separate adaptation evidence. Measure whether the task reduced rework before expanding tooling. No UI implementation, screenshot capture, test pass, or sign-off is claimed here.
