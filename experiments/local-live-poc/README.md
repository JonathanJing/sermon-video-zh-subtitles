# Local Live Caption POC

Independent greenfield interface for a MacBook-based live sermon caption feasibility test.

## Current scope

- One desktop page.
- Microphone selection and live input meter.
- Start/stop audio recording in the browser.
- Large Simplified Chinese caption area with a smaller English source line.
- Downloadable audio and JSON event log after stopping.
- Clearly labeled simulated captions for UI verification.

The local ASR, translation model, canonical PCM writer, and offline replay runner are intentionally not implemented yet. The UI never presents simulated captions as real model output.

The intentionally small system and context-pack plan is in [DESIGN.zh.md](./DESIGN.zh.md). The verified desktop design review is in [design-qa.md](./design-qa.md).

## Run

```bash
npm run dev -- --host 0.0.0.0 --port 4173 --strictPort
```

Open the local page in a browser and allow microphone access when starting a recording.
