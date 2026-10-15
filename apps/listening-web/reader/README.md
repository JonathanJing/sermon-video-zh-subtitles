# Dev reader entry

The multilingual Dev reader: the page shell that `assemble_multilingual_hosting.py` turns into the Production overlay (`data-reader-mode="production"`) and that the Dev dry-run, voice-demo and speaker-clip stagings copy by name into hosting candidates. It is a second entry of the listening app, not a second app; it shares the app root's icons, brand images, `playback-memory.mjs`, `speaker-clip-demos.mjs` and `voice-demo.css`, and ships no copies of them.

| File | Owner here | Copied by |
|---|---|---|
| `index.html`, `app.js`, `styles.css`, `404.html` | reader shell; `styles.css` starts with the app's `style.css` and adds Dev overrides | `assemble_multilingual_hosting` (`READER_FILES`, `index.html`), `multilingual_dev_preview` |
| `formal-dev-adapter.mjs`, `dev-integrity.mjs` | formal-release adapter and integrity checks; `formal-dev-adapter.mjs` is a shared client contract for the iOS route | same, plus `tests/test_formal_dev_adapter.mjs`, `tests/test_dev_integrity.mjs` |
| `dry-run-app-weeks.mjs`, `published-weeks-dry-run.mjs` | weekly dry-run app | `install_firebase_dev_dry_run_app` |
| `voice-demo.mjs` | Dev voice-demo panel over the shared renderer | `stage_voice_demo_dev`, `stage_speaker_clip_demo_ui` |
| `sep27-page-audio-extension.mjs` | page-specific spoken-caption module | `build_sep27_page_audio_extension` |

Relative imports inside these files (`./icons.mjs`, `./playback-memory.mjs`, `./speaker-clip-demos.mjs`) resolve in the assembled bundle, where every file sits in one `public/` directory, not in this source tree.

`firebase/dev/public/` now holds only the POC content package (`content/`, `packages/`, `releases/`, `weekly.json`, `multilingual.json`) written by `stage_multilingual_fragment_poc_firebase.py` and sealed by `seal_multilingual_dev_catalog.py`; it is real published Dev data that several tests read, and nothing deploys that directory directly.
