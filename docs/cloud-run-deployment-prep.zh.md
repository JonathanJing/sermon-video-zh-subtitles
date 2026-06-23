# Cloud Run 部署准备与 Secret Manager 清单

English version: [cloud-run-deployment-prep.md](./cloud-run-deployment-prep.md)

更新日期：2026-06-23

本文用于把当前 POC 推进到 Cloud Run 部署。核心目标仍然是服务 11:30 PT 场中文会众：Cloud Run 应该可靠提供 PWA、实时字幕 API、生成物 manifest 和 operator 控制面；所有敏感值只进入 Google Secret Manager，不进入代码、Git、GCS artifact、浏览器 JS 或日志。

周日验证 runbook：[sunday-live-test-runbook.zh.md](./sunday-live-test-runbook.zh.md)

## 1. 部署边界

V1 Cloud Run 服务建议先拆成一个最小服务，后续再拆：

| 模块 | V1 形态 | 说明 |
|---|---|---|
| `web` | Cloud Run 静态资源 + API 服务 | 提供 PWA、会众视图、operator 视图 |
| `api` | 同一个 Cloud Run 服务内 | session、caption segments、manifest、publish |
| `worker` | 先用 Cloud Run job 或同服务后台任务 | 离线 ASR、翻译、笔记、金句 |
| `live-source-monitor` | Cloud Scheduler / Cloud Tasks 调 Cloud Run endpoint | 周日检查 live source |
| `realtime-relay` | 可选独立服务 | 只有当浏览器不能直接连 realtime provider 时才需要 |

## 2. 必须放入 Secret Manager

这些值不得写入 `.env`、README、GCS、Firestore 文档字段、前端 JS、Cloud Run 日志或 GitHub Actions 日志。

| Secret ID 建议 | Cloud Run env var | 必需性 | 用途 | 备注 |
|---|---|---:|---|---|
| `openai-api-key` | `OPENAI_API_KEY` | P0 必需，如果主链路用 OpenAI | `gpt-realtime-translate`、`gpt-realtime-whisper`、文本修正、离线笔记 | 第一版推荐先放 |
| `gemini-api-key` | `GEMINI_API_KEY` | P0/P1 强烈建议 | Gemini Live Translate、Flash-Lite 文本翻译、benchmark fallback | 用于 provider 切换和成本/质量对照 |
| `openrouter-api-key` | `OPENROUTER_API_KEY` | P1 可选 | OpenRouter 文本翻译 fallback、benchmark | 不作为实时音频主链路 |
| `operator-session-secret` | `OPERATOR_SESSION_SECRET` | P0 必需 | 签发 operator session/cookie/JWT | 至少 32 bytes 随机值 |
| `operator-admin-token` | `OPERATOR_ADMIN_TOKEN` | P0 临时必需 | 私测阶段 operator 登录或发布保护 | 后续可替换为 Google Identity / Firebase Auth |
| `internal-task-token` | `INTERNAL_TASK_TOKEN` | P0/P1 必需，若内部 endpoint 用 bearer token | Cloud Scheduler/Tasks 调用 live monitor、worker endpoint | 若完全使用 OIDC + IAM，可降为不需要 |
| `youtube-data-api-key` | `YOUTUBE_DATA_API_KEY` | P1 可选 | YouTube Data API 查询 live/video metadata | 公共页面抓取可不需要；API quota key 需要保护 |
| `youtube-oauth-client-secret` | `YOUTUBE_OAUTH_CLIENT_SECRET` | 仅授权 YouTube API 需要 | OAuth app client secret | 不要把 OAuth client secret 放进前端 |
| `youtube-cookies-txt` | secret volume file | 仅明确授权时使用 | 读取频道方授权账号可访问的字幕/直播元数据 | 不用于绕过权限、DRM 或平台规则；优先不用 cookies |
| `authorized-live-source-token` | `AUTHORIZED_LIVE_SOURCE_TOKEN` | 仅授权源需要 | 频道方授权音频、私有 relay、内部 stream 访问 | 不用于绕过平台权限或 DRM |
| `bible-api-key` | `BIBLE_API_KEY` | 可选 | 外部 Bible API / licensed scripture API | 如果使用本地授权经文索引，则不需要 |
| `alert-webhook-url` | `ALERT_WEBHOOK_URL` | 可选 | 9:58 无可用源、模型失败、发布失败提醒 operator | Webhook URL 应视为 secret |
| `sentry-dsn` | `SENTRY_DSN` | 可选 | 生产错误监控 | DSN 常被认为低敏，但本项目仍建议放 secret |

## 3. 不要放 Secret Manager 的配置

这些不是 secret，应该作为普通 Cloud Run env var、Terraform variable、README 示例或 Firestore 配置保存：

| 配置 | 建议 env var | 说明 |
|---|---|---|
| GCP project id | `GOOGLE_CLOUD_PROJECT` | Cloud Run 通常自动提供 |
| GCS bucket name | `SERMON_ARTIFACT_BUCKET` | bucket 名不是 secret |
| GCS prefix | `SERMON_ARTIFACT_PREFIX` | 例如 `runs` |
| Firestore database / collection names | `FIRESTORE_DATABASE`, `FIRESTORE_COLLECTION_PREFIX` | 名称不是 secret |
| 默认时区 | `APP_TIMEZONE=America/Los_Angeles` | 用于 11:30 PT SLA |
| 默认 live URL / channel URL | `MARINERS_LIVE_URL`, `MARINERS_CHANNEL_URL` | 公共 URL 不是 secret |
| 默认 provider | `REALTIME_TRANSLATE_PROVIDER=openai` | 控制 OpenAI/Gemini 切换 |
| provider 超时 | `MODEL_TIMEOUT_MS`, `MODEL_RECONNECT_MS` | SLA 配置，不是 secret |
| 会众页面公开 base URL | `PUBLIC_BASE_URL` | 前端需要知道 |
| feature flags | `ENABLE_OFFLINE_NOTES`, `ENABLE_OPENROUTER_BENCHMARK` | 不含 key 即可普通配置 |

## 4. 不要用 secret 存 Google Cloud 凭证 JSON

Cloud Run 应使用专用 service account 和 IAM，不要创建并保存 Google service account JSON key。

建议 service account：

```text
sermon-caption-runner@<project-id>.iam.gserviceaccount.com
```

最小 IAM：

| 权限 | 作用 |
|---|---|
| `roles/secretmanager.secretAccessor` | 只授予需要读取的 secret，最好逐个 secret 绑定 |
| `roles/storage.objectAdmin` 或更窄自定义 role | 读写生成物 GCS bucket |
| `roles/datastore.user` | 读写 Firestore session、caption segments、publish state |
| `roles/cloudtasks.enqueuer` | 如果 API 需要 enqueue 离线 job |
| `roles/run.invoker` | 给 Scheduler/Tasks 调 Cloud Run endpoint |

## 5. Cloud Run env var 映射建议

运行时推荐让 Cloud Run 直接把 Secret Manager value 注入 env var：

```text
OPENAI_API_KEY        <- secret openai-api-key:latest
GEMINI_API_KEY        <- secret gemini-api-key:latest
OPENROUTER_API_KEY    <- secret openrouter-api-key:latest
OPERATOR_SESSION_SECRET <- secret operator-session-secret:latest
OPERATOR_ADMIN_TOKEN  <- secret operator-admin-token:latest
INTERNAL_TASK_TOKEN   <- secret internal-task-token:latest
```

公开生成物不需要知道 raw secret resource name。只有非公开部署配置可以记录 resource name，例如：

```text
projects/<project-id>/secrets/openai-api-key/versions/latest
```

浏览器可加载文件必须满足：

- 不包含 `OPENAI_API_KEY` / `GEMINI_API_KEY` / `OPENROUTER_API_KEY` 等值。
- 不包含 operator token、session secret、webhook URL。
- 生产版 public playback JS 和生成到 GCS 的 artifact 不包含 Secret Manager resource name。
- `cloud-manifest.json` 如果需要记录 secret resource name，只能由 server-side endpoint 读取，不直接公开给会众页面。

## 6. Secret 创建命令模板

以下命令只展示形状，不要把真实 key 写进 shell history。实际执行时建议用交互式输入、临时文件或 CI secret 注入。

```bash
gcloud secrets create openai-api-key --replication-policy=automatic
gcloud secrets versions add openai-api-key --data-file=/path/to/openai_api_key.txt

gcloud secrets create gemini-api-key --replication-policy=automatic
gcloud secrets versions add gemini-api-key --data-file=/path/to/gemini_api_key.txt

gcloud secrets create openrouter-api-key --replication-policy=automatic
gcloud secrets versions add openrouter-api-key --data-file=/path/to/openrouter_api_key.txt

gcloud secrets create operator-session-secret --replication-policy=automatic
gcloud secrets versions add operator-session-secret --data-file=/path/to/operator_session_secret.txt

gcloud secrets create operator-admin-token --replication-policy=automatic
gcloud secrets versions add operator-admin-token --data-file=/path/to/operator_admin_token.txt

gcloud secrets create internal-task-token --replication-policy=automatic
gcloud secrets versions add internal-task-token --data-file=/path/to/internal_task_token.txt
```

部署时给 Cloud Run service account 授权：

```bash
gcloud secrets add-iam-policy-binding openai-api-key \
  --member=serviceAccount:sermon-caption-runner@PROJECT_ID.iam.gserviceaccount.com \
  --role=roles/secretmanager.secretAccessor
```

对每个需要的 secret 重复授权。不要给整个项目的所有 secret 一次性授予宽权限，除非只是临时开发环境。

## 7. 第一版 Cloud Run 部署前检查

- Secret Manager 已创建 `openai-api-key`、`operator-session-secret`、`operator-admin-token`。
- 如果要跑 Gemini/OpenRouter benchmark，已创建 `gemini-api-key`、`openrouter-api-key`。
- Cloud Run service account 只能读取本服务需要的 secrets。
- GCS bucket 已创建，Cloud Run service account 可读写该 bucket。
- Firestore 已启用，Cloud Run service account 可读写 session/caption state。
- public PWA 文件不包含 secret value 或 secret resource name。
- 日志过滤策略确认不会打印 provider request headers、API keys、cookies、operator token。
- 非公开部署配置与 public playback JS 分离；public JS 和公开 GCS artifact 都不写入 secret resource name。
- 11:30 SLA 相关 env var 已设置：`APP_TIMEZONE`、`SERMON_ARTIFACT_BUCKET`、`REALTIME_TRANSLATE_PROVIDER`、`MODEL_TIMEOUT_MS`。

## 8. 当前线上部署快照

2026-06-23 约 13:29 PT 已验证：

| 字段 | 值 |
|---|---|
| Project | `ai-for-god` |
| Region | `us-west1` |
| Service | `sermon-zh-caption-web` |
| URL | `https://sermon-zh-caption-web-wu7uk5rgdq-uw.a.run.app/` |
| Status | `Ready` |
| 快照验证时的 revision | `sermon-zh-caption-web-00012-bqj` |
| 快照验证时近期 ready rollback candidates | `sermon-zh-caption-web-00011-2nz`, `sermon-zh-caption-web-00010-54f`, `sermon-zh-caption-web-00009-bqz`, `sermon-zh-caption-web-00008-frx` |
| Traffic | `100%` 指向 latest ready revision |
| Public invoker | `allUsers` 拥有 `roles/run.invoker` |
| Service account | `760303847302-compute@developer.gserviceaccount.com` |
| Artifact bucket | `sermon-zh-artifacts-ai-for-god` |
| Max scale | `20` |
| Container concurrency | `80` |

当前 service account 是 default Compute Engine service account。真实生产周日前，建议迁移到专用 Cloud Run service account，例如 `sermon-caption-runner@ai-for-god.iam.gserviceaccount.com`，只授予本服务需要的 Secret Manager 和 GCS 权限。

## 9. 当前 Service Env Vars

当前 revision 已验证的配置：

| Env var | 值 | 是否 secret | 说明 |
|---|---|---:|---|
| `APP_TIMEZONE` | `America/Los_Angeles` | 否 | 11:30 PT workflow 判断需要。 |
| `SERMON_ARTIFACT_BUCKET` | `sermon-zh-artifacts-ai-for-god` | 否 | 与已验证 bucket 一致。 |
| `SERMON_ARTIFACT_PREFIX` | `sundays` | 否 | 会众页面读取稳定 Sunday manifest 的 prefix。 |
| `OPENAI_API_KEY_SECRET` | `projects/760303847302/secrets/openai-api-key/versions/latest` | 只有 resource reference | 后端 server-side 用它读取 OpenAI key；不要暴露到 public artifacts 或浏览器 JS。 |

`gcloud run services describe` 返回的 Cloud Run env var 列表中没有可见 raw provider API key 或 operator token。Secret Manager resource reference 属于部署元数据，必须保持 server-side。

## 10. 上线后验证命令

```bash
curl -I -L --max-time 20 https://sermon-zh-caption-web-wu7uk5rgdq-uw.a.run.app/
curl -I -L --max-time 20 https://sermon-zh-caption-web-wu7uk5rgdq-uw.a.run.app/app.js
curl -I -L --max-time 20 https://sermon-zh-caption-web-wu7uk5rgdq-uw.a.run.app/playback-simulation.generated.js
curl -sS --max-time 20 https://sermon-zh-caption-web-wu7uk5rgdq-uw.a.run.app/api/health
curl -sS --max-time 20 https://sermon-zh-caption-web-wu7uk5rgdq-uw.a.run.app/api/sundays/current
```

```bash
gcloud run services describe sermon-zh-caption-web \
  --project=ai-for-god \
  --region=us-west1 \
  --format=json
```

```bash
gcloud run revisions list \
  --service=sermon-zh-caption-web \
  --project=ai-for-god \
  --region=us-west1
```

通过标准：

- Root URL 返回 `HTTP 200`，且 `content-type: text/html`。
- 必要静态 JS assets 返回 `HTTP 200`。
- `/api/health` 返回 `status=ok`。
- `/api/sundays/current` 返回过滤后的 public Sunday payload，并且不暴露 Secret Manager resource name。
- Service condition 为 `Ready=True`。
- Traffic 指向预期 revision。
- Public browser artifacts 不暴露 raw API key、operator token、webhook URL 或 Secret Manager resource name。

## 11. Observability Smoke

事件字段和标准查询见 [observability.zh.md](./observability.zh.md)。

部署后发送一次测试 page-view telemetry，并在 Cloud Logging 中确认收到 `congregation_page_view`：

```bash
curl -sS -X POST \
  -H 'content-type: application/json' \
  -d '{"anonymousDeviceId":"dev-deploy-smoke","visitId":"deploy-smoke","sunday":"2026-06-28","viewMode":"congregation","path":"/","timezone":"America/Los_Angeles","language":"en-US","viewport":{"width":390,"height":844},"screen":{"width":390,"height":844}}' \
  https://sermon-zh-caption-web-wu7uk5rgdq-uw.a.run.app/api/telemetry/page-view
```

Cloud Logging 查询：

```text
resource.type="cloud_run_revision"
jsonPayload.event="congregation_page_view"
jsonPayload.anonymousDeviceId="dev-deploy-smoke"
```

周日 workflow 还需要按当天 `sunday` 确认 `live_capture_triggered`、`worker_stage_completed` 和 `captions_ready`。

## 12. GCS Artifact Verification

Bucket 验证：

```bash
gcloud storage buckets describe gs://sermon-zh-artifacts-ai-for-god --format=json
gcloud storage ls gs://sermon-zh-artifacts-ai-for-god
```

2026-06-23 bucket 验证通过：

- Bucket 位于 `US-WEST1`。
- 已启用 uniform bucket-level access。
- 已强制 public access prevention。
- 顶层 `runs/` prefix 存在。

当前 E2E run prefix：

```text
gs://sermon-zh-artifacts-ai-for-god/runs/2026-06-23/openai-translation-e2e-FsUijL9uB1I
```

已验证对象：

| Object | Content type | Size | Generation |
|---|---:|---:|---:|
| `artifacts/openai-translation-e2e/FsUijL9uB1I/openai-translation-report.json` | `application/json` | `1005` | `1782239054691283` |
| `web/playback-simulation.generated.js` | `text/javascript` | `42750` | `1782239345874920` |

Report 中 `status=ok`、`translationStatus=ready`、`totalSegments=80`、`translatedSegments=80`、`apiKeyMaterialIncluded=false`、`secretResourceNamesIncluded=false`。Public browser JS 和生成报告都必须继续移除 Secret Manager resource name。

验证时该 OpenAI translation E2E prefix 下没有 `cloud-manifest.json`。这是 E2E publish path 的后续缺口；周日运行时不要假设 manifest 存在，除非当场明确验证。

## 13. Rollback Notes

当前 service 的 revision rollback：

```bash
gcloud run services update-traffic sermon-zh-caption-web \
  --project=ai-for-god \
  --region=us-west1 \
  --to-revisions=REVISION_NAME=100
```

`REVISION_NAME` 应从当前 `gcloud run revisions list` 输出中选择。2026-06-23 13:29 PT 快照时，近期 ready candidates 包括 `sermon-zh-caption-web-00011-2nz`、`sermon-zh-caption-web-00010-54f`、`sermon-zh-caption-web-00009-bqz` 和 `sermon-zh-caption-web-00008-frx`。Rollback 后重新跑上线后验证命令，并确认 traffic 指向预期 revision。

如果只是 artifact prefix 指错，优先把 `SERMON_ARTIFACT_PREFIX` 更新到 last known-good prefix，而不是回滚静态 assets：

```bash
gcloud run services update sermon-zh-caption-web \
  --project=ai-for-god \
  --region=us-west1 \
  --update-env-vars=SERMON_ARTIFACT_PREFIX=runs/YYYY-MM-DD/last-known-good
```

这会创建新 revision。请在周日证据记录里同时记录旧 revision 和新 revision。
