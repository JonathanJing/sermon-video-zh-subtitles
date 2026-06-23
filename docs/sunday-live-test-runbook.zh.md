# 周日 Live Test Runbook

English version: [sunday-live-test-runbook.md](./sunday-live-test-runbook.md)

更新日期：2026-06-23

本文用于 Cloud Run PWA 与 GCS artifact 路径的上线验证和真实周日 live test。范围只覆盖部署、验证、回滚和证据记录，不修改 UI 样式或翻译 worker 行为。

## 线上资源

| 项目 | 值 |
|---|---|
| Cloud Run project | `ai-for-god` |
| Cloud Run region | `us-west1` |
| Cloud Run service | `sermon-zh-caption-web` |
| Public URL | `https://sermon-zh-caption-web-wu7uk5rgdq-uw.a.run.app/` |
| Artifact bucket | `gs://sermon-zh-artifacts-ai-for-god` |
| Time zone | `America/Los_Angeles` |

## 当前已验证状态

2026-06-23 约 11:34 PT 验证结果：

- Cloud Run public URL 返回 `HTTP 200`，`content-type: text/html`。
- 静态资源 `/app.js` 和 `/playback-simulation.generated.js` 返回 `HTTP 200`。
- Cloud Run service 状态为 `Ready`。
- 快照验证时 `100%` 流量指向 revision `sermon-zh-caption-web-00002-58c`。每次 deploy 或周日测试前都要重新确认 live revision。
- 当前普通 env vars 为 `APP_TIMEZONE=America/Los_Angeles`、`SERMON_ARTIFACT_BUCKET=sermon-zh-artifacts-ai-for-god`、`SERMON_ARTIFACT_PREFIX=runs/2026-06-23/openai-translation-e2e-FsUijL9uB1I`。
- service IAM 允许 `allUsers` 以 `roles/run.invoker` 访问，适合公开 PWA smoke test。
- GCS bucket 位于 `US-WEST1`，启用 uniform bucket-level access，并强制 public access prevention。
- 当前配置的 GCS prefix 下有 translated report、model JSONL 和 playback JS。
- 验证时该 OpenAI translation E2E prefix 下没有 `cloud-manifest.json`。在这个路径补齐 manifest 发布前，report 和 playback JS 是本次已确认 artifact。
- 已下载检查 public HTML 和 playback JS，未匹配到检查范围内的 API key、operator token 或 Secret Manager resource name pattern。

## 周日前准备

周日早上前完成：

- 确认当天 live source。生产保守默认是最早可验证、且能给 11:30 PT 前留出审阅时间的同场证道服务；当前更稳妥的 baseline 是 10:00 PT。
- 确认当天 artifact prefix，例如 `runs/2026-06-28/live-test-1000-service`。
- 任何 deploy 或 env 更新前，先记录可回滚 revision：

```bash
gcloud run revisions list \
  --service=sermon-zh-caption-web \
  --project=ai-for-god \
  --region=us-west1
```

- 确认 Cloud Run env vars 指向当天 prefix：

```bash
gcloud run services describe sermon-zh-caption-web \
  --project=ai-for-god \
  --region=us-west1 \
  --format=json
```

- 如果需要修改 `SERMON_ARTIFACT_PREFIX`，请在 live window 前完成并记录新 revision：

```bash
gcloud run services update sermon-zh-caption-web \
  --project=ai-for-god \
  --region=us-west1 \
  --update-env-vars=SERMON_ARTIFACT_PREFIX=runs/YYYY-MM-DD/live-test-1000-service
```

## 周日 Live Test 时间线

以下时间均为 Pacific Time。

| 时间 | 动作 | 通过标准 |
|---|---|---|
| T-60 min | 用普通浏览器 session 打开 Cloud Run URL。 | 页面能加载，无 auth 或浏览器 console blocker。 |
| T-45 min | 验证 Cloud Run readiness 和静态资源。 | root、`/app.js`、`/playback-simulation.generated.js` 均返回 `HTTP 200`。 |
| T-40 min | 验证 bucket 和当天 prefix。 | bucket 可访问；目标 prefix 存在，或在生成前按计划为空。 |
| T-30 min | 确认 rollback revision 和 log URL。 | 已记录 previous known-good revision。 |
| 9:55 或 10:00 | 对选定 source 启动 live-source 或 E2E generation workflow。 | artifact 开始写入计划中的 GCS prefix。 |
| 10:10 | 检查第一批可用 caption segments。 | report/playback data 有非零 segments，且没有 secret material flag。 |
| 10:45 | 检查翻译完整度。 | `translationStatus=ready`，或记录明确 fallback 决策。 |
| 11:10 | operator 审阅。 | sermon title、source、首屏字幕看起来正确。 |
| 11:20 | 发布或冻结 11:30 audience artifact set。 | artifact prefix 稳定，并且和 Cloud Run env 或选定 manifest 一致。 |
| 11:30 | audience smoke test。 | 干净浏览器 session 可以加载当天发布的字幕体验。 |
| 11:50 | SLA 后检查。 | 字幕体验仍可用；失败和 fallback 时间已记录。 |
| 礼拜后 | 保存证据。 | 记录 revision、prefix、object generation、rollback/fallback 动作。 |

## Cloud Run Smoke Commands

```bash
curl -I -L --max-time 20 https://sermon-zh-caption-web-wu7uk5rgdq-uw.a.run.app/
curl -I -L --max-time 20 https://sermon-zh-caption-web-wu7uk5rgdq-uw.a.run.app/app.js
curl -I -L --max-time 20 https://sermon-zh-caption-web-wu7uk5rgdq-uw.a.run.app/playback-simulation.generated.js
```

```bash
gcloud run services describe sermon-zh-caption-web \
  --project=ai-for-god \
  --region=us-west1 \
  --format=json
```

## GCS Artifact Verification

列出当天 prefix：

```bash
gcloud storage ls --recursive gs://sermon-zh-artifacts-ai-for-god/runs/YYYY-MM-DD/live-test-1000-service
```

检查关键对象：

```bash
gcloud storage objects describe \
  gs://sermon-zh-artifacts-ai-for-god/runs/YYYY-MM-DD/live-test-1000-service/web/playback-simulation.generated.js \
  --format=json
```

```bash
gcloud storage cat \
  gs://sermon-zh-artifacts-ai-for-god/runs/YYYY-MM-DD/live-test-1000-service/artifacts/openai-translation-e2e/LIVE_ID/openai-translation-report.json
```

必须确认：

- `apiKeyMaterialIncluded` 是 `false`。
- Public playback JS 不包含 raw API key、operator token、webhook URL 或 Secret Manager resource name。
- 绿色测试需要 `translationStatus=ready`；如果没有 ready，必须记录 fallback 状态。
- 完整 OpenAI translation E2E run 中，`translatedSegments` 等于 `totalSegments`。
- 记录最终 playback JS 和 report 的 object generation number。

## Rollback

如果部署后的静态 app 或 env vars 有问题，用 revision rollback：

```bash
gcloud run services update-traffic sermon-zh-caption-web \
  --project=ai-for-god \
  --region=us-west1 \
  --to-revisions=sermon-zh-caption-web-00001-mqg=100
```

然后重新跑 Cloud Run smoke commands，并确认实际 revision：

```bash
gcloud run services describe sermon-zh-caption-web \
  --project=ai-for-god \
  --region=us-west1 \
  --format=json
```

如果只是 artifact prefix 指错，优先把 `SERMON_ARTIFACT_PREFIX` 指向 last known-good prefix，并记录因此创建的新 revision。事故处理中不要删除失败的周日 artifact，保留用于复盘。

## 周日证据记录模板

```text
Date:
Operator:
Cloud Run revision before test:
Cloud Run revision after test:
Artifact prefix:
Live source URL:
First artifact write time PT:
First usable caption time PT:
Ready/publish time PT:
11:30 audience smoke result:
11:50 SLA result:
Rollback used: yes/no
Known issues:
Next fix:
```
