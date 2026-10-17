# Run digest 20261017-backend-image-resources-smoke

Generated 2026-10-17T15:22:21+00:00. Redacted copies only; source hashes are in manifest.json.

## backend-image-resource-smoke

Source: `~/.codex/worktrees/docker-terminology/sermon-video-zh-subtitles/artifacts/backend-image-resource-smoke`

- outcome `outcome.json`: **passed** exit 0 (? → ?)
- summary `summary.json`: **passed**

Timings `timings.tsv`:

| stage | status | seconds | result |
|---|---|---|---|
| resource_smoke_job | pass | 53 | Docker build and two in-container reads |

## backend-image-parent-cancelled

Source: `~/.codex/worktrees/docker-terminology/sermon-video-zh-subtitles/artifacts/backend-image-parent-cancelled`

- outcome `outcome.json`: **cancelled** exit None (? → ?)
- summary `summary.json`: **cancelled**

Timings `timings.tsv`:

| stage | status | seconds | result |
|---|---|---|---|
| resource_smoke_job | cancelled |  | interrupted after runner start |

Failed stages: `resource_smoke_job`
