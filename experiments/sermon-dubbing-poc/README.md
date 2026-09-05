# Chinese sermon audio POC

A deployed weekly Chinese listening app, with local MP3 generation and isolated voice-training experiments. It remains separate from the Saturday PDF and Sunday live-caption paths. Open the [Firebase app](https://ai-for-god-sermon-audio.web.app) and see the [weekly release and corpus expansion report](./WEEKLY_APP_REPORT_20260905.zh.md). See the [authorized voice/training results](./AUTHORIZED_VOICE_REPORT_20260905.zh.md), [earlier preset results](./POC_REPORT_20260905.zh.md), [Chinese training plan](./TRAINING.zh.md) and [design](../../docs/saturday-to-sunday-chinese-voice-plan.zh.md).

The App starts in dark mode for dim venues. The header switches between dark and light and remembers the explicit choice on this browser. Warm gray text and muted jade controls cover every tab, the companion dialog and native audio controls; theme changes preserve playback. The small external `theme.js` applies the saved palette before CSS paints, within the existing Hosting content-security policy. Palette values and measured contrast are documented in [the display note](./DISPLAY_THEME.zh.md).

The user confirmed authorization for voice training and dubbing and accepted both Eric trained samples. Five additional speakers now have independent three-sermon training checkpoints and Chinese auditions: Jared Kirkwood, Christine Caine, Doug Fields, Kenton Beshore and Steve Bang Lee. Their 223 train-only candidate clips total 1,803 seconds. Short original-English references are available beside the Chinese samples; other speakers' human listening acceptance remains pending.

The new [Saturday audio extension runbook](./SATURDAY_AUDIO_RUNBOOK.zh.md) and [SVG workflow](../../docs/diagrams/saturday-chinese-voice-workflow.svg) cover the reusable weekly path. The [speaker / weekly-flow report](./SPEAKER_BANK_AND_WEEKLY_FLOW_REPORT_20260905.zh.md) records the actual artifacts and limitations. A complete August 30 candidate was generated, screened and revised for numeral/pronoun pronunciation: 122 units, 1,612.84 seconds. The App shows it as **整篇待审**. Nine acoustic boundaries and fifteen natural-speech timing overflows require review before same-video use. This is separate from the already accepted Eric voice sample.

## Run

From the repository root:

```bash
python3 experiments/sermon-dubbing-poc/server.py
```

This command serves the built weekly app on loopback. The current release pack is `artifacts/sermon-dubbing/2026-09-05-weekly-app-v4-dark-final/public`. To export another release, choose a new output directory:

```bash
python3 experiments/sermon-dubbing-poc/build_weekly_app.py \
  --expansion artifacts/sermon-dubbing/2026-09-05-corpus-expansion/chinese-audio \
  --out artifacts/sermon-dubbing/a-new-weekly-release
python3 experiments/sermon-dubbing-poc/deploy_firebase.py \
  --release artifacts/sermon-dubbing/a-new-weekly-release \
  --project ai-for-god-caption-dev --site ai-for-god-sermon-audio
```

The deploy command validates the explicit upload files; add `--execute` to publish the requested release. It targets only the dedicated listening site. The builder refuses to overwrite an existing release. To rebuild the earlier preset experiment:

```bash
python3 experiments/sermon-dubbing-poc/poc.py inventory
python3 experiments/sermon-dubbing-poc/poc.py prepare
```

For synthesis, use an isolated Python environment containing MLX Audio. This run used the existing local `mlx-audio 0.3.1` tool runtime with `mlx 0.32.2`, not the root Python environment. It downloads a pinned public model into the Hugging Face cache and generates locally:

```bash
/Users/jonathan_jing/.local/share/uv/tools/mlx-audio/bin/python \
  experiments/sermon-dubbing-poc/poc.py synthesize
/Users/jonathan_jing/.local/share/uv/tools/mlx-audio/bin/python \
  experiments/sermon-dubbing-poc/screen_audio.py
```

For the authorized run, the frozen `experiment.json` and `speaker-profile.json` bind reference audio, English reference text and authorization to hashes. With those local inputs present:

```bash
/Users/jonathan_jing/.local/share/uv/tools/mlx-audio/bin/python \
  experiments/sermon-dubbing-poc/poc.py synthesize \
  --out artifacts/sermon-dubbing/2026-09-05-authorized-voice-poc
/Users/jonathan_jing/.local/share/uv/tools/mlx-audio/bin/python \
  experiments/sermon-dubbing-poc/prepare_voice_candidates.py
```

`run_qwen_training_smoke.py` consumes a separately staged `research-inputs.json`, local authorization and audio in an isolated CUDA environment. The original single-source mode is limited to 32 English candidates; the v1 multisource schema accepts three Eric sermons; v2 supports a named speaker and isolated speaker slot. Both limit each run to 96 clips from exactly three train-split sermons and at most 15 minutes, with source/hash/reserved-set checks. Both use one epoch, batch 1, learning rate 2e-6 and refuse to overwrite a checkpoint. `probe_qwen_training.py` generates the same Chinese on the Torch Base and trained checkpoint. This engineering route does not change candidate records into human-approved training data. See the Chinese training report for the actual environment, compatibility fixes and remaining checks.

Open `http://127.0.0.1:18780`. Use `--port` if that port is occupied. The server is loopback-only and exposes static player assets, the explicit library manifest and its MP3 files; it does not expose source recordings or the repository directory.

Authorized outputs under ignored `artifacts/sermon-dubbing/2026-09-05-authorized-voice-poc/`:

- `eric_clone.mp3`: 77.44 seconds, 5 complete Chinese groups, using a 12.96-second English voice reference.
- `speaker-profile.json`, `reference-asr-check.json`: reference provenance and machine text verification.
- `training-candidates/`: 21 aligned English candidates totaling 168.48 seconds; individual human approval and full diarization remain pending.
- `spark-training-smoke/`: research input manifest, training logs, checkpoint hash and measured weight change. The full checkpoint is retained on Spark.
- `spark-chinese-audio/sft_pilot.mp3`: 78.64-second trained voice probe, with machine screening and full decode evidence; the failed Torch Base comparison stays in this diagnostic pack.
- `listening-comparison/`: explicit MP3-only player library, with per-track voice labels.

Earlier preset outputs remain under `artifacts/sermon-dubbing/2026-09-05-fluency-poc-v2/`:

- `flow.mp3`: 5 groups, 107.20 seconds; 100-character grouping budget, with complete sentences preserved.
- `sentence.mp3`: the same text, 14 sentences, 103.38 seconds.
- `experiment.json`, `chunks/`, `build-report.json`, `library.json`: frozen inputs, synthesis receipts, cache hashes and actual generated timing.
- `speaker-inventory.json`: 8 source records, including 5 protected evaluation sources. Metadata grouping is not verified diarization. No sources have been admitted to training.
- `asr-screening.json`: local Chinese ASR diagnostics, not human approval.

The first run remains in `artifacts/sermon-dubbing/2026-09-04-fluency-poc/`: 4 groups, 104.38 seconds, with a possible missing word ending flagged by ASR. The second run reduced the grouping budget from 140 to 100 characters. The flagged ending is now recognized; proper names and another possible omission still require listening. Neither variant has passed human listening approval.

The UI supports play/pause, MP3 download, a seek bar, ±5-second skips and ±1/±0.25-second adjustments. Selecting another comparison variant pauses and resets playback. Fine adjustments show the movement actually applied at the bounds. Audio plays as one continuous file per variant, with HTTP byte ranges for seeking.

The generation runner preserves exact text across segmentation variants, caches chunks by source/parameter identity, performs two-pass loudness processing and checks full MP3 decoding. Reference synthesis verifies the explicitly recorded authorization, source hash and voice-profile hash. Existing MLX runtime model-type/tokenizer warnings remain recorded and unresolved, so these samples are not a validated production runtime.

## Verification

```bash
python3 -m unittest discover -s experiments/sermon-dubbing-poc -p 'test_*.py'
node --test experiments/sermon-dubbing-poc/web/timing.test.mjs experiments/sermon-dubbing-poc/web/catalog.test.mjs
node --check experiments/sermon-dubbing-poc/web/app.mjs
git diff --check
```

These cover source-text preservation, range requests, directory/path isolation, missing media, seek bounds and cue boundaries. This is dependency-free static browser code; there is no bundler or production-build step. Real model generation, complete decode and browser playback are additional checks, not replacements for human listening and onsite end-to-end acceptance.

The Firebase release includes week selection, listening/transcript/production-progress/speaker-audition tabs, topic/speaker metadata, timecode jumps, subtitle seeking and a sermon-companion modal. August 23 has accepted Eric voice samples; August 30 has a complete review candidate. Published assets are explicit UI/content files, Chinese MP3s and five short authorized English voice references. Full source recordings, training data and checkpoints stay local. Same-video synchronization, real-phone background playback and venue readiness remain unverified.
