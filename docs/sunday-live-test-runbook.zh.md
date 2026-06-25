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

2026-06-23 约 13:29 PT 验证结果：

- Cloud Run public URL 返回 `HTTP 200`，`content-type: text/html`。
- 静态资源 `/app.js` 和 `/playback-simulation.generated.js` 返回 `HTTP 200`。
- Cloud Run service 状态为 `Ready`。
- 快照验证时 `100%` 流量指向 revision `sermon-zh-caption-web-00012-bqj`。每次 deploy 或周日测试前都要重新确认 live revision。
- 当前 env vars 为 `APP_TIMEZONE=America/Los_Angeles`、`SERMON_ARTIFACT_BUCKET=sermon-zh-artifacts-ai-for-god`、`SERMON_ARTIFACT_PREFIX=sundays`，以及 server-side `OPENAI_API_KEY_SECRET=projects/PROJECT_NUMBER/secrets/openai-api-key/versions/latest`。
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
| 10:01 | 在 Cloud Logging 检查 `live_capture_triggered`。 | event 包含正确的 `sunday`、`triggerSource` 和 live-source hash。 |
| 10:10 | 检查第一批可用 caption segments。 | report/playback data 有非零 segments，且没有 secret material flag。 |
| 10:45 | 检查翻译完整度。 | `translationStatus=ready`，或记录明确 fallback 决策。 |
| 10:50 | 在 Cloud Logging 检查 `captions_ready`。 | event 对应目标 `sunday`，并指向稳定 Sunday manifest。 |
| 11:10 | operator 审阅。 | sermon title、source、首屏字幕看起来正确。 |
| 11:20 | 发布或冻结 11:30 audience artifact set。 | artifact prefix 稳定，并且和 Cloud Run env 或选定 manifest 一致。 |
| 11:30 | audience smoke test。 | 干净浏览器 session 可以加载当天发布的字幕体验，并产生 `congregation_page_view`。 |
| 11:50 | SLA 后检查。 | 字幕体验仍可用；失败和 fallback 时间已记录。 |
| 礼拜后 | 保存证据。 | 记录 revision、prefix、object generation、trigger/ready log 时间、设备数估算、rollback/fallback 动作。 |

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

```bash
curl -sS --max-time 20 https://sermon-zh-caption-web-wu7uk5rgdq-uw.a.run.app/api/health
curl -sS --max-time 20 https://sermon-zh-caption-web-wu7uk5rgdq-uw.a.run.app/api/sundays/current
```

## 日志验证

完整 event 字段见 [observability.zh.md](./observability.zh.md)。

周日必须留证的日志：

- 目标 `sunday` 的 `live_capture_triggered`。
- prepare、translate、upload、promote 阶段的 `worker_stage_completed`。
- 11:30 会众窗口前出现 `captions_ready`。
- 用干净浏览器 session 打开 public page 后出现 `congregation_page_view`。

Cloud Logging 示例：

```text
resource.type="cloud_run_revision"
jsonPayload.event="live_capture_triggered"
jsonPayload.sunday="YYYY-MM-DD"
```

```text
resource.type=("cloud_run_revision" OR "cloud_run_job")
jsonPayload.event="captions_ready"
jsonPayload.sunday="YYYY-MM-DD"
```

```text
resource.type="cloud_run_revision"
jsonPayload.event="congregation_page_view"
jsonPayload.viewMode="congregation"
jsonPayload.sunday="YYYY-MM-DD"
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

先跑 live path 的 realtime draft smoke：

```bash
python3 scripts/realtime_openai_smoke_test.py \
  --audio-file authorized-smoke.wav \
  --api-key-secret projects/PROJECT_ID/secrets/openai-api-key/versions/latest \
  --backend-url https://CLOUD_RUN_URL \
  --sunday YYYY-MM-DD \
  --admin-token "$ADMIN_TOKEN" \
  --realtime-event-gcs-prefix gs://sermon-zh-artifacts-ai-for-god/realtime-events \
  --out artifacts/realtime-openai-smoke/report.json
```

再跑 stabilized realtime smoke。这个脚本会自己创建 backend session，event token 只留在进程内，
用 `gpt-5.5-mini` 回写一条 stable correction，然后用 `--require-stable-correction`
验证保存下来的 realtime JSONL：

```bash
python3 scripts/realtime_stabilized_smoke_test.py \
  --audio-file authorized-smoke.wav \
  --api-key-secret projects/PROJECT_ID/secrets/openai-api-key/versions/latest \
  --backend-url https://CLOUD_RUN_URL \
  --sunday YYYY-MM-DD \
  --admin-token "$ADMIN_TOKEN" \
  --realtime-event-gcs-prefix gs://sermon-zh-artifacts-ai-for-god/realtime-events \
  --read-events-from-gcs \
  --out artifacts/realtime-stabilized-smoke/report.json
```

stabilized report 必须确认：

- `status` 是 `ok`。
- `models.realtimeDraft` 是 `gpt-realtime-translate`。
- `models.stableCorrection` 是 `gpt-5.5-mini`。
- `stableCorrection.postedStableCorrections` 大于 `0`。
- `validation.status` 是 `ok`。
- `eventTokenIncluded`、`apiKeyMaterialIncluded`、`secretResourceNamesIncluded` 都是 `false`。

11:30 现场运行时，用 live-session wrapper，不要拆成 worker 和 stabilizer 两条手动命令。
这个脚本会创建 backend session，把 event token 留在进程内，把授权音频源送进
`gpt-realtime-translate`，并基于保存下来的 realtime JSONL 周期性跑 `gpt-5.5-mini`
stable correction：

```bash
python3 scripts/run_realtime_live_session.py \
  --audio-url 'https://AUTHORIZED_AUDIO_SOURCE/live.m3u8?token=...' \
  --api-key-secret projects/PROJECT_ID/secrets/openai-api-key/versions/latest \
  --backend-url https://CLOUD_RUN_URL \
  --sunday YYYY-MM-DD \
  --admin-token "$ADMIN_TOKEN" \
  --realtime-event-gcs-prefix gs://sermon-zh-artifacts-ai-for-god/realtime-events \
  --read-events-from-gcs \
  --require-stable-correction \
  --out artifacts/realtime-live-session/report.json
```

如果授权源是 YouTube live，确认访问权限和平台规则后，把 `--audio-url ...` 换成
`--youtube-url 'https://www.youtube.com/watch?v=...'`。如果现场用 iPad/iPhone mic，
走 admin browser WebRTC；backend event contract 和 stabilizer 回写格式保持一致。浏览器创建
realtime session 后，用 admin/internal auth 跑后台 stabilizer loop，让 event token 留在浏览器
session 内：

```bash
python3 scripts/run_realtime_stabilizer_loop.py \
  --input-jsonl gs://sermon-zh-artifacts-ai-for-god/realtime-events/YYYY-MM-DD/<browser_session_id>.jsonl \
  --api-key-secret projects/PROJECT_ID/secrets/openai-api-key/versions/latest \
  --backend-url https://CLOUD_RUN_URL \
  --session-id <browser_session_id> \
  --internal-task-token "$INTERNAL_TASK_TOKEN" \
  --interval-seconds 6 \
  --min-age-seconds 4
```

loop 会先写 `<browser_session_id>.model-access-preflight.json`。如果
`gpt-5.5-mini` 在 OpenAI Responses 上不可用，它会在读取 event log 或回写修正版前退出；
低延迟的 `gpt-realtime-translate` draft session 应继续运行。

先生成 combined evidence command：

```bash
python3 scripts/run_sunday_evidence_bundle.py \
  --sunday YYYY-MM-DD \
  --session-id <worker_session_id> \
  --artifact-location gcs \
  --artifact-bucket sermon-zh-artifacts-ai-for-god \
  --artifact-prefix sundays \
  --realtime-location gcs \
  --realtime-event-gcs-prefix gs://sermon-zh-artifacts-ai-for-god/realtime-events \
  --realtime-smoke-report artifacts/realtime-live-session/report.json \
  --require-readable-sunday-artifacts \
  --cloud-run-config-report artifacts/evidence/cloud-run-realtime-config.json \
  --cloud-run-api-preflight-report artifacts/evidence/cloud-run-api-preflight.json \
  --web-realtime-contract-report artifacts/evidence/web-realtime-contract.json \
  --realtime-public-sse-smoke-report artifacts/evidence/realtime-public-sse-smoke.json \
  --realtime-session-validation-report artifacts/evidence/realtime-live-session/realtime-session-validation.json \
  --offline-chain-validation-report artifacts/evidence/offline-chain-validation.json \
  --offline-asr-smoke-report artifacts/evidence/offline-asr-fallback-smoke/report.json \
  --sunday-manifest-validation-report artifacts/evidence/sunday-manifest-validation.json \
  --openai-model-access-preflight-report artifacts/evidence/openai-model-access-preflight.json \
  --openai-alternative-model-access-preflight-report artifacts/evidence/openai-model-access-preflight-gpt-5.5.json \
  --out artifacts/evidence/caption-route-readiness.json \
  --evidence-matrix-out artifacts/evidence/production-evidence-matrix.json \
  --goal-audit-out artifacts/evidence/production-goal-readiness-audit.json \
  --bundle-report-out artifacts/evidence/sunday-evidence-bundle.json \
  --dry-run
```

确认路径正确后去掉 `--dry-run` 重跑。该命令会调用 production readiness gate，并继续写出
production evidence matrix 和 goal audit；如果 offline artifacts、promoted Sunday manifest、
realtime JSONL、Cloud Run config 或 API preflight 证据缺失/无效，会直接失败。如果已经知道
realtime session id，可以用 `--realtime-session-id` 代替 `--realtime-smoke-report`。如果 smoke
report 里包含 `realtimeEventsJsonl`，runner 会优先使用这个精确 JSONL URI。11:30 production
gate 使用 live-session report；rehearsal evidence 可以使用 stabilized smoke report。两种情况下，
realtime JSONL 都必须已经包含至少一条 `gpt-5.5-mini` stable correction event。如果
production-readiness verifier 在写 report 前退出，bundle 会写一份最小 failed report，并继续生成
matrix/audit，让 operator 仍然能看到一张状态板。如果 matrix generation 在写 report 前退出，
bundle 会写一份最小 incomplete matrix，并继续跑 goal audit。
alternative model access report 只作为旁证记录；不要把 `gpt-5.5` 可用当作 required
`gpt-5.5-mini` access 的替代。

## Rollback

如果部署后的静态 app 或 env vars 有问题，用 revision rollback：

```bash
gcloud run services update-traffic sermon-zh-caption-web \
  --project=ai-for-god \
  --region=us-west1 \
  --to-revisions=REVISION_NAME=100
```

然后重新跑 Cloud Run smoke commands，并确认实际 revision：

```bash
gcloud run services describe sermon-zh-caption-web \
  --project=ai-for-god \
  --region=us-west1 \
  --format=json
```

如果只是 artifact prefix 指错，优先把 `SERMON_ARTIFACT_PREFIX` 指向 last known-good prefix，并记录因此创建的新 revision。事故处理中不要删除失败的周日 artifact，保留用于复盘。

`REVISION_NAME` 应从当前 `gcloud run revisions list` 输出中选择。2026-06-23 13:29 PT 快照时，近期 ready candidates 包括 `sermon-zh-caption-web-00011-2nz`、`sermon-zh-caption-web-00010-54f`、`sermon-zh-caption-web-00009-bqz` 和 `sermon-zh-caption-web-00008-frx`。

## 周日证据记录模板

```text
Date:
Operator:
Cloud Run revision before test:
Cloud Run revision after test:
Artifact prefix:
Live source URL:
Generation trigger source:
live_capture_triggered log time PT:
First artifact write time PT:
First usable caption time PT:
Ready/publish time PT:
captions_ready log time PT:
11:30 audience smoke result:
Unique device estimate:
11:50 SLA result:
Rollback used: yes/no
Known issues:
Next fix:
```
