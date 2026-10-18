# Run digest 20261017-source-failure-move

Generated 2026-10-17T15:29:45+00:00. Redacted copies only; source hashes are in manifest.json.

## source-failure-tests-20261017

Source: `~/.codex/worktrees/source-failure-move/sermon-video-zh-subtitles/artifacts/source-failure-tests-20261017`

- outcome `outcome.json`: **focused_pass_broad_incomplete** exit 0 (2026-10-17T15:29:42.777446Z → 2026-10-17T15:29:42.777446Z)
- summary `summary.json`: **focused_pass_broad_incomplete**

Error-like log lines (first 5 per log):

- `targeted.log`: Traceback (most recent call last):
- `targeted.log`: return subprocess.run(["git", "--no-optional-locks", "-C", str(root), *args], capture_output=True, text=True, timeout=5, check=False)
- `targeted.log`: stdout, stderr = process.communicate(input, timeout=timeout)
- `targeted.log`: stdout, stderr = self._communicate(input, endtime, timeout)
- `targeted.log`: ready = selector.select(timeout)
