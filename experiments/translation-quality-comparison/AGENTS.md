# Translation quality comparison runbook

Follow the repository root [`AGENTS.md`](../../AGENTS.md) first. This is the repeatable operator/agent procedure for the blinded comparison of pastors.ai Mandarin against our production Chinese. Product/method details live in [`README.zh.md`](README.zh.md); this file is the checklist.

This experiment calls no model, uses no network and spends no money. Human ratings are the primary evidence; the deterministic checks only flag numeric/scripture hints.

## Preconditions

- A capture directory with `session.english.jsonl` and `session.mandarin.jsonl` (provider session logs with exact `ts`), plus the human `sermon.window.json`.
- One finished production run with either:
  - `segments_timed_zh.json` (Layer 2), or
  - `reading-edition-v2/reading_blocks.final.json` (reading edition; `sermon_zh_reading_revised.srt` is a fallback).
- Two independent bilingual raters. One rater is a pilot only; record that limitation.
- The comparison target is written down **before** looking at results: `--ours layer2` (translation quality) or `--ours reading` (reading-delivery quality). Never mix them in one conclusion.

## 1. Verify inputs and choose the candidate

- Confirm `sermon.window.json` is bound to `capture.json`; `compare.py prepare` rejects a mismatched hash.
- Confirm `session.mandarin.jsonl` has enough final lines to form units. Three lines for five minutes produce very coarse units; a full sermon is better. A 5-minute demo with 9 pastors finals yielded only 5 eligible units in the local prepare run; `--sample-size 30` will warn and use fewer. Treat that as a pilot, not a 30-unit comparison.
- Choose `layer2` or `reading`; do not edit that choice after seeing the scores.

## 2. Build alignment, sample and blind sheets (free)

```bash
.venv/bin/python experiments/translation-quality-comparison/compare.py prepare \
  --capture-dir artifacts/live-capture/mariners-north-irvine/2026-11-15 \
  --ours-dir artifacts/live-reading-tests/20261115-north-irvine \
  --ours layer2 \
  --outdir artifacts/translation-comparison/20261115-north-irvine \
  --sample-size 30 --seed 20261115
```

Inspect:

- `comparison.manifest.json`: counts high/medium/low; if `high` is too small, the unit builder or timestamps are wrong.
- `alignment.jsonl`: spot-check at least 10 units; confirm the English anchor and both Chinese candidates cover the same content. Low-confidence units are excluded from sampling by default; `--allow-medium` only with a recorded reason.
- `review.packet.md`: no source labels; A/B order is randomized.
- `ratings.rater*.csv`: templates only, no source labels.

If alignment is poor, do not proceed to rating. Adjust `--unit-seconds`/`--unit-max-chars`, or fix the input timestamps; a scored bad alignment is worse than no result.

## 3. Blind rating

- Give each rater only `review.packet.md` and their own `ratings.raterN.csv`.
- Raters must not see `sample.json` (it maps A/B to sources), the other rater's file, or the production run.
- Score `adequacy` and `fluency` 1–5, `preference` A/B/tie, and critical/major/minor counts; add a short reason in `notes`.
- Missing/blank rows are allowed; `score` reports rated vs sampled.

## 4. Aggregate

```bash
.venv/bin/python experiments/translation-quality-comparison/compare.py score \
  --outdir artifacts/translation-comparison/20261115-north-irvine
```

Read `summary.json` and `report.md`:

- preference counts: ours / pastors / tie / disputed / unrated;
- ours win rate with bootstrap 95% CI (disputed excluded);
- adequacy/fluency mean differences with CIs;
- critical/major/minor totals;
- per-stratum counts;
- inter-rater agreement;
- deterministic number/scripture hints (advisory only).

## 5. Gates before writing a conclusion

- At least two independent raters; preference agreement reported.
- Rated coverage is stated; unrated and disputed units are visible, not silently folded into a winner.
- The sample includes beginning/middle/end and content types; if one stratum dominates, say so.
- The report uses the pre-declared target (`layer2` vs `reading`); no switching after results.
- No claim of absolute quality or a "gold" reference.
- No raw sermon transcript, audio or full candidate text in docs; the report is aggregate-only.
- Machine checks are labeled advisory; no `humanApproval=true` unless a human review is actually recorded.

## 6. Decision rules

- Ours wins only if the human preference and score CIs support a stable advantage for the declared target.
- If the CIs cross 0/50% or the raters disagree materially, keep the current production chain or enlarge the sample; do not declare a winner.
- Either way, pastors.ai Chinese is comparison evidence, never a Layer 2 approval, training gold or verified example.
- If both candidates have critical errors, add deterministic checks/fixes before debating preference.
- Record the decision and its evidence in the run report; a new sermon/window/model/prompt needs a new comparison.

## 7. Artifacts and run report

Local, gitignored:

```text
artifacts/translation-comparison/<date>-<slug>/
  alignment.jsonl
  sample.json
  review.packet.md
  ratings.rater1.csv
  ratings.rater2.csv
  comparison.manifest.json
  summary.json
  report.md
```

Commit only docs/report: aggregate counts, CIs, rubric, limitations and hashes; never raw transcripts, audio, the full packet or rater identities. Export a redacted run digest and open its docs-only PR per [`docs/test-run-retrospective.zh.md`](../../docs/test-run-retrospective.zh.md).

## 8. Failure and edge cases

- **No session logs**: stop; the comparison needs provider `ts` on both sides. Do not substitute partials without documenting the change.
- **Too few pastors.ai finals**: units become coarse; use a longer window or report that the comparison is not meaningful.
- **Low confidence dominates**: inspect timestamps and candidate boundaries; do not sample medium/low just to hit 30.
- **Ratings malformed**: `score` rejects unknown unit IDs, invalid preference and non-numeric values; fix the CSV, do not edit `sample.json`.
- **Single rater**: pilot only; report the limitation and do not use it to change production.
- **Changed inputs**: any new capture/window/production run/model/prompt invalidates the old ratings; regenerate alignment and sample, do not reuse the old CSV.

## 9. Done definition

- Candidate target and seed are recorded.
- Alignment was spot-checked; low-confidence units excluded or explicitly discussed.
- Two independent raters completed the blind sheets (or the single-rater limitation is recorded).
- `summary.json`/`report.md` pass the gates in §5.
- The aggregate run report PR is open; no transcript or media is committed.
- No production policy changed unless the evidence supports a separate, explicit decision.
