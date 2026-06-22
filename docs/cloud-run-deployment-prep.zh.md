# Cloud Run 部署准备与 Secret Manager 清单

English version: [cloud-run-deployment-prep.md](./cloud-run-deployment-prep.md)

更新日期：2026-06-22

本文用于把当前 POC 推进到 Cloud Run 部署。核心目标仍然是服务 11:30 PT 场中文会众：Cloud Run 应该可靠提供 PWA、实时字幕 API、生成物 manifest 和 operator 控制面；所有敏感值只进入 Google Secret Manager，不进入代码、Git、GCS artifact、浏览器 JS 或日志。

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

生产代码不需要知道 raw secret resource name。只有 server-side manifest 或部署配置可以记录 resource name，例如：

```text
projects/<project-id>/secrets/openai-api-key/versions/latest
```

浏览器可加载文件必须满足：

- 不包含 `OPENAI_API_KEY` / `GEMINI_API_KEY` / `OPENROUTER_API_KEY` 等值。
- 不包含 operator token、session secret、webhook URL。
- 生产版 public playback JS 不包含 Secret Manager resource name。
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
- 生产 manifest 与 public playback JS 分离；server-side manifest 可以引用 secret resource name，public JS 不可以。
- 11:30 SLA 相关 env var 已设置：`APP_TIMEZONE`、`SERMON_ARTIFACT_BUCKET`、`REALTIME_TRANSLATE_PROVIDER`、`MODEL_TIMEOUT_MS`。
