# Run digest 20261020-dev-180s-e2e-20261020T161828Z

> **人工补充**：`preflight/summary.json` 的 `blocked_before_page_generation` 是“零模型生成”的测试标记，不是发布失败；`delivery-execute` 已通过，Dev 三语页面与 catalog 已回读。iOS Beta 使用现有 1.26.18 (59) 读取同一 Dev catalog v3；本轮没有上传新 TestFlight 构建，也没有真机验收。详见 `RETROSPECTIVE.md`。

Generated 2026-10-20T16:25:18+00:00. Redacted copies only; source hashes are in manifest.json.

## e2e-20261020T161828Z

Source: `<workspace>/artifacts/dev-180s-page-test-20261004/e2e-20261020T161828Z`

- summary `preflight/summary.json`: **blocked_before_page_generation**

Timings `timings.tsv`:

| stage | status | seconds |
|---|---|---|
| verify-clip | pass | 13 |
| build-inputs | pass | 12 |
| baseline | pass | 14 |
| delivery-preflight | pass | 4 |
| delivery-execute | pass | 367 |

Not copied: 2 .cache, 22 .css, 432 .html, 5 .jpg, 44 .js, 2591 .json, 8 .lock, 1 .md, 247 .mjs, 885 .mp3, 104 .mp4, 20 .pdf, 97 .png, 10 .srt, 18 .svg, 65 .wav
