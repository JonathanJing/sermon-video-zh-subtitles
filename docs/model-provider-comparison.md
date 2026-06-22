# Translation Model And Provider Comparison

Last updated: 2026-06-22

Chinese version: [model-provider-comparison.zh.md](./model-provider-comparison.zh.md)

## Recommendation

Use a hybrid architecture:

1. Realtime path: OpenAI `gpt-realtime-translate` or Gemini `gemini-3.5-live-translate-preview` for the lowest-latency Chinese caption stream.
2. English sidecar: streaming ASR in parallel so the operator can review, replay, and retranslate from a stable source transcript.
3. Stable correction path: every 5-15 seconds, send stable English transcript windows to a text model with glossary, scripture, and name constraints.
4. Offline path: after service, regenerate high-quality VTT/SRT, notes, and quote candidates.

OpenRouter should not be the realtime audio primary path. It is better used after ASR as a text-translation fallback and benchmark layer.

## Candidate Matrix

| Scenario | Provider / model | Fit | Latency view | Quality view | Main risk |
|---|---|---:|---|---|---|
| Realtime audio translation | OpenAI `gpt-realtime-translate` | High | Best fit for low-latency captions | Fast direct translation; needs sidecar corrections for terms/scripture | Scripture and name consistency must be benchmarked |
| Realtime English sidecar | OpenAI `gpt-realtime-whisper` | High | Runs in parallel | Provides correction and replay baseline | Adds cost |
| Realtime audio translation | Gemini `gemini-3.5-live-translate-preview` | High | Low-latency live translation | Strong OpenAI competitor | Preview behavior and noisy audio need testing |
| Low-cost realtime audio | Gemini `gemini-3.1-flash-live-preview` | Medium | Cheapest realtime audio candidate | Useful experiment group | Not a dedicated translation model |
| ASR-to-text translation | OpenAI `gpt-5.4-mini` | High | Segment-level translation, usually seconds | Good controllability and structured output | Requires ASR |
| ASR-to-text translation | Gemini `gemini-3.1-flash-lite` | High | Low-cost, high-throughput | Strong cost/performance for translation | Needs sermon-domain benchmark |
| ASR-to-text translation | OpenRouter Qwen / MiniMax | Medium | Depends on router and provider | Useful fallback/benchmark | Provider drift and SLA consistency |

## 50-Minute Cost Estimate

Realtime audio:

| Plan | Unit price | 50-minute estimate |
|---|---:|---:|
| OpenAI realtime translate only | $0.034 / min | $1.70 |
| OpenAI realtime translate + realtime whisper | $0.034 + $0.017 / min | $2.55 |
| Gemini 3.5 Live Translate | about $0.0368 / min | $1.84 |
| Gemini 3.1 Flash Live Preview | $0.005 audio input + $0.018 audio output / min | $1.15 |

Text translation is much cheaper than realtime audio. Based on the local POC VTT for the target sermon/live archive, the sample has about 30.94 minutes of captions, 1,672 cues, and 17,362 English words. Extrapolated to 50 minutes, that is roughly 37k English input tokens and 31k-45k Chinese output tokens.

| Plan | 50-minute text translation estimate |
|---|---:|
| OpenAI `gpt-5.4-mini` | $0.17-$0.23 |
| Gemini `gemini-3.1-flash-lite` | $0.06-$0.08 |
| Gemini `gemini-3.5-flash` | $0.33-$0.46 |
| OpenRouter `qwen/qwen3.7-plus` | about $0.05-$0.07 before platform fees |
| OpenRouter `minimax/minimax-m3` | about $0.05-$0.07 before platform fees |

The critical production cost is not text translation. The critical production risk is whether the audio source is available early enough and whether realtime captions remain readable, stable, and accurate for scripture-heavy speech.

## Benchmark Plan

Use `V6OKiwbjDZE` and the corresponding live archive candidate as the domain benchmark because it includes scripture references, sermon language, theological terms, names, and long-form speaking cadence.

Current status: only the local transcript-size and cost benchmark has been completed. Provider latency and quality benchmarks still require actual API keys and billable online calls.

Benchmark groups:

1. OpenAI realtime translate.
2. Gemini 3.5 Live Translate.
3. Gemini 3.1 Flash Live Preview.
4. OpenAI text model after ASR.
5. Gemini Flash-Lite after ASR.
6. OpenRouter Qwen / MiniMax after ASR.

Metrics:

- `first_partial_ms`
- `first_stable_ms`
- `segment_final_ms_p50`
- `segment_final_ms_p95`
- `revision_rate`
- `terms_accuracy`
- `omission_rate`
- `readability_mobile`
- `operator_fix_count`

Pass thresholds for the realtime path:

- p50 first caption under 2.5 seconds.
- p95 stable caption under 6 seconds.
- Clear scripture references recognized at least 90% of the time.
- iPhone portrait view remains readable without long-sentence flooding.

## Sources

- OpenAI API pricing: <https://openai.com/api/pricing/>
- Gemini API pricing: <https://ai.google.dev/gemini-api/docs/pricing>
- Gemini Live Translation docs: <https://ai.google.dev/gemini-api/docs/live-api/live-translate>
- OpenRouter quickstart: <https://openrouter.ai/docs/quickstart>
- OpenRouter pricing: <https://openrouter.ai/pricing>
- OpenRouter models API: <https://openrouter.ai/api/v1/models>
