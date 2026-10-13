# Run digest 20261013-qc-five-pr-review-and-merge-validation

Generated 2026-10-13T14:53:23+00:00. Redacted copies only; source hashes are in manifest.json.

## 20261013-pr367-screening-review

Source: `/private/tmp/sermon-fix-367/artifacts/run/20261013-pr367-screening-review`

- outcome `outcome.json`: **pass** exit 0 (? → ?)

Timings `timings.tsv`:

| stage | status | elapsedSeconds |
|---|---|---|
| pytest | pass | 27.68 |

## 20261013-pr369-review-fixes

Source: `/private/tmp/sermon-fix-369/artifacts/run/20261013-pr369-review-fixes`

- outcome `outcome.json`: **pass** exit ? (? → ?)

Timings `timings.tsv`:

| stage | status | elapsedSeconds |
|---|---|---|
| core_pytest | pass | 38.99 |
| transport_pytest | pass | 0.21 |

Error-like log lines (first 5 per log):

- `pytest-initial-fail-interrupted.log`: E           AssertionError: assert {'g1': '하박국 이장과 팔장의 맨 첫 절'} == {'g1': '하박국 이장과 8장의 맨 첫 절'}
- `pytest-initial-fail-interrupted.log`: tests/test_ko_spoken_rule_versions.py:26: AssertionError
- `pytest-initial-fail-interrupted.log`: E       AssertionError: assert {'g1': {'spok...과 팔장의 맨 첫 절'}} == {'g1': {'spok...과 8장의 맨 첫 절'}}
- `pytest-initial-fail-interrupted.log`: tests/test_ko_spoken_rule_versions.py:44: AssertionError
- `pytest-initial-fail-interrupted.log`: E       AssertionError: assert '본문 1 .5장부터 칠장까지' == '본문 1 .5장부터 7장까지'

Not copied: 1 .md

## pr370-offline-fix

Source: `/private/tmp/sermon-fix-370/artifacts/pr370-offline-fix`

- outcome `outcome.json`: **pass** exit 0 (? → ?)

Timings `timings.tsv`:

| stage | status | elapsedSeconds |
|---|---|---|
| joint-four-modules | pass | 968.04 |
| focused-final | pass | 10.28 |
| final-audio-compatibility | pass | 0.17 |

Error-like log lines (first 5 per log):

- `short-focused-initial-assertion.log`: E       AssertionError: assert {'jsonSha256'...te': 1.0, ...} == {'jsonSha256'...te': 1.0, ...}
- `short-focused-initial-assertion.log`: tests/test_audio_calibration_short_truncation.py:84: AssertionError
- `short-focused-initial-assertion.log`: FAILED tests/test_audio_calibration_short_truncation.py::test_release_consumer_accepts_unchanged_v2_and_current_v3_counts
- `short-focused-initial-assertion.log`: 1 failed, 6 passed in 10.47s

## 20261013-pr371-page-id-preflight

Source: `/private/tmp/sermon-fix-371/artifacts/run/20261013-pr371-page-id-preflight`

- outcome `outcome.json`: **pass** exit 0 (? → ?)

Timings `timings.tsv`:

| stage | status | elapsedSeconds |
|---|---|---|
| pytest | pass | 0.27 |

## 20261013-five-pr-merge-validation

Source: `~/.codex/worktrees/merge-qc-dev-prs/sermon-video-zh-subtitles/artifacts/run/20261013-five-pr-merge-validation`

- outcome `outcome.json`: **pass** exit 0 (? → ?)

Timings `timings.tsv`:

| stage | status | seconds |
|---|---|---|
| combined_targeted_pytest | pass | 39.32 |
