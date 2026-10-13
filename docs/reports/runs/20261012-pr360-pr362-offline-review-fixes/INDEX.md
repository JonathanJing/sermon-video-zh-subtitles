# Run digest 20261012-pr360-pr362-offline-review-fixes

Generated 2026-10-13T00:49:10+00:00. Redacted copies only; source hashes are in manifest.json.

## 20261012-pr360-margin-validation

Source: `/private/tmp/sermon-fix-360/artifacts/run/20261012-pr360-margin-validation`

- outcome `outcome.json`: **passed** exit 0 (? → ?)

Timings `timings.tsv`:

| stage | status | elapsedSeconds |
|---|---|---|
| pytest | pass | 11.37 |

## pr362-offline-review-20261012

Source: `/private/tmp/sermon-fix-362/artifacts/pr362-offline-review-20261012`

- outcome `outcome.json`: **pass** exit 0 (? → ?)
- summary `summary.json`: **pass**

Timings `timings.tsv`:

| stage | status | elapsedSeconds |
|---|---|---|
| premerge-offline-regressions | pass | 67.868 |
| final-numeric-separator-guard-pytest | pass | 25.06 |

## pr362-final-base-quickcheck-20261012

Source: `/private/tmp/sermon-fix-362/artifacts/pr362-final-base-quickcheck-20261012`

- outcome `outcome.json`: **pass** exit 0 (? → ?)

Timings `timings.tsv`:

| stage | status | elapsedSeconds |
|---|---|---|
| pytest | pass | 0.86 |

## pr362-range-chain-review-20261012

Source: `/private/tmp/sermon-fix-362/artifacts/pr362-range-chain-review-20261012`

- outcome `outcome.json`: **pass** exit 0 (? → ?)

Timings `timings.tsv`:

| stage | status | elapsedSeconds |
|---|---|---|
| pytest | pass | 0.23 |

## pr362-range-fold-contract-20261012

Source: `/private/tmp/sermon-fix-362/artifacts/pr362-range-fold-contract-20261012`

- outcome `outcome.json`: **pass** exit 0 (? → ?)

Timings `timings.tsv`:

| stage | status | elapsedSeconds |
|---|---|---|
| pytest | pass | 0.83 |

## pr362-counter-structure-contract-20261012

Source: `/private/tmp/sermon-fix-362/artifacts/pr362-counter-structure-contract-20261012`

- outcome `outcome.json`: **pass** exit 0 (? → ?)

Timings `timings.tsv`:

| stage | status | elapsedSeconds |
|---|---|---|
| pytest | pass | 0.95 |

Error-like log lines (first 5 per log):

- `pytest.log`: E       AssertionError: assert '요한복음 3장십육-17절' == '요한복음 3장16-17절'
- `pytest.log`: tests/test_ko_spoken_numerals.py:149: AssertionError
- `pytest.log`: E       AssertionError: assert '요한복음 3장16절벽' == '요한복음 삼장16절벽'
- `pytest.log`: tests/test_ko_spoken_numerals.py:160: AssertionError
- `pytest.log`: tests/test_ko_spoken_numerals.py:175: AssertionError

## pr362-terminal-compound-contract-20261012

Source: `/private/tmp/sermon-fix-362/artifacts/pr362-terminal-compound-contract-20261012`

- outcome `outcome.json`: **pass** exit 0 (? → ?)

Timings `timings.tsv`:

| stage | status | elapsedSeconds |
|---|---|---|
| pytest | pass | 0.97 |
