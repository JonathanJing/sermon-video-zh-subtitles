# Live translate capture → reading PDF runbook

Follow the repository root [`AGENTS.md`](../../AGENTS.md) first. This file is the repeatable operator/agent procedure for the Sunday path:

```text
translate.pastors.ai live capture
  -> human-confirmed sermon window
  -> our own English cleanup and Chinese translation
  -> reading-edition-v2 SRTs
  -> Chinese-English reading PDF
```

Product/protocol details, current provider bounds and the latest evidence live in [`README.zh.md`](README.zh.md). Read the relevant section before changing a command, a prompt or a limit.

## Preconditions

- The capture directory exists and contains `capture.json` and `session.json`; the Sunday wrapper writes both. The capture intentionally keeps the whole 10:00–11:20 service.
- A human has reviewed the service and supplied the sermon start and end. Do not infer the window automatically and do not trim the capture itself.
- An explicit OpenAI environment is configured (`.env.openai` on the Mac, `~/.config/tongxing/openai.env` on Spark) and a budget is approved. Never use a bare inherited `.env` key, never pass a key on the command line, and never print one.
- The reading PDF is a local deliverable. Upload, publication and page release require a separate instruction.

## 0. Confirm the Sunday capture

The LaunchAgent runs `run-capture.sh` on Sunday at 09:55 for the 10:00–11:20 window. After 11:20 inspect:

- `capture.json`: `status`, `warnings`, `broadcast_timeline`;
- `session.json`: `comparison_with_live.match_fraction`;
- `run.status.json`: `capture_exit`, `session_fetch_exit`.

A non-broadcasting room produces `status: empty` and a failed session fetch; that is not a capture crash. If the room was wrong, do not build a PDF from the empty run.

## 1. Record the human window (free)

```bash
.venv/bin/python experiments/live-translate-capture/mark_window.py \
  --capture-dir artifacts/live-capture/mariners-north-irvine/2026-11-15 \
  --start 10:29:35 --end 11:02:10 \
  --approved-by "Jony (chat)" \
  --evidence "回看整场；讲道从宣布后开始，到回应诗歌前结束"
```

`HH:MM[:SS]`, ISO-8601 or `--start-offset/--end-offset` are accepted. The tool writes `sermon.window.json`, validates it against the capture bounds, binds `capture.json`/`session.json` by SHA-256, and is idempotent unless `--force` changes the values. Verify it with `--check`.

`sermon.window.json` is capture metadata, not a Layer 1 `approvedWindow`; downstream Layer 1 still needs its own evidence and approval.

## 2. Build the free plan

```bash
.venv/bin/python experiments/live-translate-capture/build_reading_pdf.py \
  --capture-dir artifacts/live-capture/mariners-north-irvine/2026-11-15
```

The adapter re-runs the deterministic window extraction, writes `<outdir>/segments_timed_en_raw.json` and `<outdir>/reading.plan.json` (default `<capture>/reading`), and prints the segment count, character count and the commands. It calls no model. Inspect `source.caption_lines`, `source.reading_segments` and `source.english_characters`; stop if the window looks wrong.

Useful overrides: `--outdir`, `--title`, `--speaker`, `--glossary`, `--max-segments`, `--max-chars`, `--hide-timecodes`, `--no-english-cleanup`.

## 3. Check the paid environment (free)

```bash
python3 tools/ops/run_with_openai_environment.py --environment dev --check
# or --environment prod
```

`--check` validates local configuration only; it does not prove provider access, model permission or budget. Use `dev` for tests and `prod` for real content. The adapter refuses `--execute` without an explicit `selected_route()`.

## 4. Run the paid chain

```bash
python3 tools/ops/run_with_openai_environment.py --environment dev -- \
  .venv/bin/python experiments/live-translate-capture/build_reading_pdf.py \
  --capture-dir artifacts/live-capture/mariners-north-irvine/2026-11-15 \
  --outdir artifacts/live-reading-tests/20261115-north-irvine \
  --title "..." --speaker "..." --execute
```

- Defaults are `gpt-6.1-sol` with `reasoning_effort=high`; override only with policy-approved model identities.
- `--translation-workers` defaults to 1; keep it conservative.
- `--max-segments`/`--max-chars` are preflight caps; `--allow-large` only after explicit review.
- Do not run the reading edition or `mobile_pdf` directly with hand-made SRTs; the adapter owns the input-bound sizes.
- The adapter uses the production `correct_english`, `translate_chinese`, two-pass reading editor and `mobile_pdf --layout reading`. It does not download YouTube, run ASR/MFA or fabricate video timing.

## 5. Verify the gates before calling it done

| Gate | Required evidence |
|---|---|
| Pipeline QA | `qa_report.json`: every `hardFailures` value is 0 |
| Reading quality | `reading-edition-v2/reading_quality_report.json`: `status == "pass"` |
| PDF QA | `sermon_zh_en_reading.qa.json`: `failures == []`, `allPagesChecked == true`, no overflow/missing glyphs |
| Deliverable | `sermon_zh_en_reading.pdf` exists, nonempty, title/date/window correct, footer disclaimer present |
| Manifest | `reading.manifest.json`: `status == "completed"`, PDF SHA-256 recorded |
| Source identity | `sermon.window.json` and `capture.json` hashes match the manifest |

Quick check:

```bash
.venv/bin/python - <<'PY'
import json
from pathlib import Path
outdir = Path("artifacts/live-reading-tests/20261115-north-irvine")
qa = json.loads((outdir / "qa_report.json").read_text())
assert not any(qa["hardFailures"].values()), qa["hardFailures"]
quality = json.loads((outdir / "reading-edition-v2" / "reading_quality_report.json").read_text())
assert quality["status"] == "pass", quality["status"]
pdf_qa = json.loads((outdir / "sermon_zh_en_reading.qa.json").read_text())
assert pdf_qa["failures"] == [] and pdf_qa["allPagesChecked"] is True
manifest = json.loads((outdir / "reading.manifest.json").read_text())
assert manifest["status"] == "completed"
print("gates pass", manifest["outputs"]["pdf_sha256"])
PY
```

## 6. Cost, accounting and run report

- Read `accounting/summary.json` and `reading-edition-v2/accounting/summary.json`; `model-calls.csv` has calls, tokens and latency.
- The legacy text path may leave cost `unknown`/partial. Report calls, input/output tokens and a **list-price estimate**, explicitly marked "estimate, not an invoice". Never invent a settled cost.
- Export a redacted run digest and open its docs-only PR per [`docs/test-run-retrospective.zh.md`](../../docs/test-run-retrospective.zh.md):

```bash
.venv/bin/python tools/development/export_run_digest.py \
  artifacts/live-reading-tests/20261115-north-irvine \
  --name 20261115-north-irvine
tools/development/publish_run_report.sh artifacts/run-reports/20261115-north-irvine
```

Never commit `artifacts/`, the PDF, audio or raw transcripts.

## 7. Failure playbook

- **`provider_input_bound_exceeded`**: no paid call was dispatched. The current implementation uses a 45-second English correction window, reading batch size 1, reading blocks of 12 s / 150 English chars (hard 30 s / 300), because the legacy path hard-caps input at 8,192 bytes. If it recurs, measure the payload locally and reduce a block/window; do not raise the bound without policy and a new measurement.
- **Reading quality not `pass`**: do not render the PDF. Inspect `reading_blocks.final.json`; a repair needs a review manifest and evidence, not a bypass flag.
- **PDF QA failure**: do not publish. Inspect `sermon_zh_en_reading.qa.json` for overflow, missing glyphs or blank pages.
- **Rate limit/network**: rerun; correction/translation caches in the outdir are reused. An unknown remote outcome must be reconciled before a new paid dispatch, per the root AGENTS rules.
- **Changed window**: do not edit `sermon.window.json` by hand. Re-record it with `mark_window.py --force`; the adapter re-extracts the window and hashes the new file.

## 8. Honest labels and limits

- English is the provider's live ASR with synthetic reading-layout timing. It is not subtitle timing, not video-synchronized and not human-reviewed; fillers such as `uh` and `you know` may remain.
- Chinese is our own machine translation, not the service's `session.mandarin` machine Chinese and not a human approval.
- Test/demo PDFs must be titled as non-published. Real PDFs keep the `mobile_pdf` disclaimer; no page or file is published by this runbook.
- An 80-minute service scales to roughly 200 reading blocks × 2 passes plus translation; estimate the budget before running. The 5-minute dev reference is in [`README.zh.md`](README.zh.md).

## 9. Done definition

- The human window is recorded and bound by hash.
- All gates in §5 pass.
- PDF path, size, SHA-256 and QA status are recorded; cost/token evidence is recorded and labeled.
- The redacted run report PR is open.
- Publication/upload is still a separate, explicitly authorized action.
