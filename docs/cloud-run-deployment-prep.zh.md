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
| Realtime event GCS mirror prefix | `REALTIME_EVENT_GCS_PREFIX=gs://<bucket>/realtime-events` | 保存实时 deltas 的 durable JSONL mirror；后台尽力同步，失败不阻塞现场 SSE |
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
| Service account | Default Compute Engine service account，公开文档中已 redacted |
| Artifact bucket | `sermon-zh-artifacts-ai-for-god` |
| Max scale | `20` |
| Container concurrency | `80` |

当前 service account 是 default Compute Engine service account。真实生产周日前，建议迁移到专用 Cloud Run service account，例如 `sermon-caption-runner@PROJECT_ID.iam.gserviceaccount.com`，只授予本服务需要的 Secret Manager 和 GCS 权限。

## 9. 当前 Service Env Vars

当前 revision 已验证的配置：

| Env var | 值 | 是否 secret | 说明 |
|---|---|---:|---|
| `APP_TIMEZONE` | `America/Los_Angeles` | 否 | 11:30 PT workflow 判断需要。 |
| `SERMON_ARTIFACT_BUCKET` | `sermon-zh-artifacts-ai-for-god` | 否 | 与已验证 bucket 一致。 |
| `SERMON_ARTIFACT_PREFIX` | `sundays` | 否 | 会众页面读取稳定 Sunday manifest 的 prefix。 |
| `OPENAI_API_KEY_SECRET` | `projects/PROJECT_NUMBER/secrets/openai-api-key/versions/latest` | 只有 resource reference | 后端 server-side 用它读取 OpenAI key；不要暴露到 public artifacts 或浏览器 JS。 |

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

## 11. Cloud Scheduler live-source job

先用 redacted dry-run 检查 Cloud Scheduler job 形状：

```bash
python3 scripts/configure_live_source_scheduler.py \
  --project ai-for-god \
  --location us-west1 \
  --service-url https://sermon-zh-caption-web-wu7uk5rgdq-uw.a.run.app
```

这个 job 会打：

```text
/api/admin/sundays/current/discover-source
```

payload 形状：

```json
{
  "triggerSource": "cloud-scheduler",
  "service": "auto",
  "operatorAlertTime": "09:58",
  "autoGenerate": true
}
```

后端会先把 `current` 解析成当周 Sunday，再规划 artifact path，所以生成物仍然落在
`sundays/YYYY-MM-DD/runs/<session_id>/`，不会写成 `sundays/current/...`。dry-run
确认无误后，在 shell 里设置 `INTERNAL_TASK_TOKEN`，再加 `--apply` 创建或更新 job。脚本
输出会对 token 做 redaction；不要把 raw token 贴进文档、终端记录、ticket 或日志。

## 12. Observability Smoke

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

## 13. GCS Artifact Verification

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

Worker 导出中文字幕之后、把 run 视为可发布之前，先验证本地/offline chain：

```bash
python3 scripts/validate_offline_chain.py \
  --report /tmp/sermon-worker/YYYY-MM-DD/<session_id>/artifacts/report.json \
  --playback-js /tmp/sermon-worker/YYYY-MM-DD/<session_id>/web/playback-simulation.generated.js \
  --zh-vtt /tmp/sermon-worker/YYYY-MM-DD/<session_id>/artifacts/sermon.zh.live-aligned.vtt \
  --zh-srt /tmp/sermon-worker/YYYY-MM-DD/<session_id>/artifacts/sermon.zh.live-aligned.srt \
  --manifest /tmp/sermon-worker/YYYY-MM-DD/<session_id>/artifacts/cloud-manifest.json
```

通过标准：verifier 输出 `status=ok`，确认使用 caption source 或
`gpt-4o-transcribe` ASR fallback，翻译模型是 `gpt-5.5-mini`，offline path 没有使用
`gpt-realtime-translate`，确认 `offline_route.strategy=captions_first_then_asr`，
caption route 没有抽音频，ASR route 标记为 `no_requested_caption_track` fallback，
并且中文 VTT/SRT 与已翻译 playback JS 都可读。

如果 `gpt-5.5-mini` 已经产出过保存的 model-output JSONL，但后续 caption/export
步骤需要续跑，可以不再调用 OpenAI，直接重放已保存翻译：

```bash
python3 scripts/translate_playback_with_openai.py \
  --input /tmp/sermon-worker/YYYY-MM-DD/<session_id>/web/playback-simulation.generated.js \
  --out /tmp/sermon-worker/YYYY-MM-DD/<session_id>/web/playback-simulation.generated.js \
  --out-dir /tmp/sermon-worker/YYYY-MM-DD/<session_id>/model-output \
  --translations-jsonl /tmp/sermon-worker/YYYY-MM-DD/<session_id>/model-output/openai-translation-output.jsonl \
  --model gpt-5.5-mini
```

这个 replay mode 只用于 artifact recovery。它能证明已保存翻译可以继续生成
playback/VTT/SRT/manifest，但不能当作新的 `gpt-5.5-mini` API 调用成功证据。

每次 Sunday worker run 和 promotion 后，用 verifier 检查稳定 Sunday manifest 和公开 artifacts：

```bash
python3 scripts/validate_sunday_manifest.py \
  --manifest gs://sermon-zh-artifacts-ai-for-god/sundays/YYYY-MM-DD/cloud-manifest.json \
  --sunday YYYY-MM-DD \
  --require-readable-artifacts \
  --out artifacts/evidence/sunday-manifest-validation.json
```

通过标准：verifier 输出 `status=ok`，包含已翻译中文 VTT/SRT，playback JS 的
`translationStatus=ready`，模型路由为离线 ASR `gpt-4o-transcribe`、离线翻译和稳定修正
`gpt-5.5-mini`、实时草稿 `gpt-realtime-translate`，并且没有 raw key material 或 Secret
Manager resource name。

实时 session 的 durable JSONL mirror 要单独验证：

```bash
python3 scripts/validate_realtime_session.py \
  --events-jsonl gs://sermon-zh-artifacts-ai-for-god/realtime-events/YYYY-MM-DD/<session_id>.jsonl \
  --require-stable-correction
```

通过标准：verifier 输出 `status=ok`，看到 `gpt-realtime-translate` model event、英文
input transcript events、中文 caption events、认可的 realtime sources；开启 correction
gate 时，还必须至少有一条 `gpt-5.5-mini-stable-correction` 的 `caption_final`，并且没有
raw key material、client secrets、event tokens 或 Secret Manager resource name。

因为当前 realtime public SSE stream 仍把 active session 放在 Cloud Run 进程内，同时把
sanitize 后的 deltas mirror 到 JSONL/GCS，第一版生产实时字幕部署必须先用单实例 service；
除非已经上线共享 realtime fanout store，否则不要让 media worker 和会众页随机落到不同实例。
部署后验证 Cloud Run 配置：

11:30 现场前如果要快速刷新只读证据，先跑这个汇总 wrapper。它不会执行
`gcloud run services update`，即使 `gpt-5.5-mini` access 或 Cloud Run realtime
config 失败，也会继续生成 matrix/audit。它还会刷新非变更的 Cloud Run update plan 和
apply dry-run 证据，但不会传 `--approve`：

```bash
python3 scripts/refresh_production_preflight_evidence.py \
  --out artifacts/evidence/production-preflight-refresh.json
```

生产 ready 的判断仍以 matrix/audit 为准，不是 wrapper 本身跑完就算通过。如果 wrapper 返回
`status=incomplete`，看 `failedSteps` 和它刷新到 `artifacts/evidence/` 下的报告，包括
update plan 和 dry-run execution report。

```bash
gcloud run services describe sermon-zh-caption-web \
  --project=ai-for-god \
  --region=us-west1 \
  --format=json > artifacts/evidence/cloud-run-service.json

python3 scripts/validate_cloud_run_realtime_config.py \
  --service-json artifacts/evidence/cloud-run-service.json \
  --out artifacts/evidence/cloud-run-realtime-config.json
```

通过标准：`status=ok`、`maxInstances=1`、已配置 `REALTIME_EVENT_GCS_PREFIX`，
Sunday artifact env vars 已配置，OpenAI key 仍只在 server-side，operator/internal task
tokens 存在，并且敏感 env var 没有以 plaintext direct value 形式配置。

如果 config verifier 失败，先生成审批包，再改 service：

```bash
python3 scripts/prepare_cloud_run_realtime_update_plan.py \
  --config-report artifacts/evidence/cloud-run-realtime-config.json \
  --service sermon-zh-caption-web \
  --project ai-for-god \
  --region us-west1 \
  --realtime-event-gcs-prefix gs://sermon-zh-artifacts-ai-for-god/realtime-events \
  --out artifacts/evidence/cloud-run-realtime-update-plan.json
```

这个 plan 不会改线上。它会记录失败项、精确 apply 命令、rollback 命令和 apply 后验证命令。
只有 operator 明确批准 Cloud Run runtime/secret wiring 变更后，才执行 apply 命令。

因为 update plan 的 `--update-secrets` 会包含短 Secret Manager 引用，所以它会标记
`secretReferencesIncluded=true`。但它仍必须保持 `apiKeyMaterialIncluded=false` 和
`secretResourceNamesIncluded=false`；去敏后的 execution report 还会移除这些短 secret 引用。

获批后，用 plan runner 执行，这样 apply、validation 和可选 rollback 会写进同一份去敏执行报告：

```bash
python3 scripts/apply_cloud_run_realtime_update_plan.py \
  --plan artifacts/evidence/cloud-run-realtime-update-plan.json \
  --approve \
  --rollback-on-failure \
  --out artifacts/evidence/cloud-run-realtime-update-execution.json
```

validation token 会先读 shell 环境；如果环境里没有，runner 会从已批准 plan 的
`--update-secrets` mapping 读取 Secret Manager。若 token 读取失败，runner 会在
`gcloud run services update` 前停止。

不加 `--approve` 时，runner 只做 dry-run，不会改 Cloud Run。

然后跑部署后的 API preflight。第一条命令只读，会把 realtime session creation 留成 warning：

```bash
python3 scripts/run_cloud_run_realtime_preflight.py \
  --base-url https://sermon-zh-caption-web-wu7uk5rgdq-uw.a.run.app \
  --cloud-run-config-report artifacts/evidence/cloud-run-realtime-config.json \
  --out artifacts/evidence/cloud-run-api-preflight-readonly.json
```

等 operator/internal token 部署获批后，再跑会创建 session 的 smoke，并把这份报告交给最终 audit：

```bash
python3 scripts/run_cloud_run_realtime_preflight.py \
  --base-url https://sermon-zh-caption-web-wu7uk5rgdq-uw.a.run.app \
  --cloud-run-config-report artifacts/evidence/cloud-run-realtime-config.json \
  --create-realtime-session \
  --internal-task-token "$INTERNAL_TASK_TOKEN" \
  --out artifacts/evidence/cloud-run-api-preflight.json
```

通过标准：root HTML、`/api/health`、`/api/sundays/current`、`/api/admin/status`
都可读且响应中无 secret material。最终 audit 使用的报告还必须显示 realtime local
session creation 成功，模型是 `gpt-realtime-translate`；报告只记录 event token 是否返回，
不写 token 值。

同时验证 public SSE contract，不调用 OpenAI：

```bash
python3 scripts/run_realtime_public_sse_smoke.py \
  --base-url https://sermon-zh-caption-web-wu7uk5rgdq-uw.a.run.app \
  --sunday YYYY-MM-DD \
  --internal-task-token "$INTERNAL_TASK_TOKEN" \
  --realtime-event-gcs-prefix gs://sermon-zh-artifacts-ai-for-god/realtime-events \
  --session-validation-out artifacts/evidence/realtime-public-sse-session-validation.json \
  --out artifacts/evidence/realtime-public-sse-smoke.json
```

Cloud Run 前的本地 backend smoke，可以把 GCS prefix 换成本地 event log directory：

```bash
python3 scripts/run_realtime_public_sse_smoke.py \
  --base-url http://127.0.0.1:8080 \
  --sunday YYYY-MM-DD \
  --internal-task-token "$INTERNAL_TASK_TOKEN" \
  --event-log-dir /tmp/sermon-realtime-events \
  --session-validation-out artifacts/evidence/realtime-public-sse-session-validation-local.json \
  --out artifacts/evidence/realtime-public-sse-smoke-local.json
```

这个 synthetic smoke 会创建 realtime session，写入一条英文 transcript delta、一条中文
caption delta 和一条 `gpt-5.5-mini` stable correction，再从
`/api/realtime/sessions/current/events` 读回来。传入 GCS prefix 时，它还会验证同一批
events 已保存到 durable session JSONL；传入 `--event-log-dir` 时，则验证本地 JSONL 文件。
它证明 backend/public stream contract 和 archive contract，但不能替代真实 OpenAI realtime
smoke。

跑 OpenAI realtime smoke 前，先验证授权音频源本身，不调用 OpenAI：

```bash
python3 scripts/run_realtime_audio_source_preflight.py \
  --sunday YYYY-MM-DD \
  --audio-file /path/to/authorized-rehearsal-audio.wav \
  --prepare-audio \
  --out artifacts/evidence/realtime-audio-source-preflight.json
```

`--audio-file`、`--audio-url`、`--youtube-url` 三选一。报告会去掉 URL query string，
只记录 source kind/display path、readiness checks 和 sanitize 后的命令结果。

把浏览器侧 iPad/iPhone mic contract 也单独验证成一份本地 evidence：

```bash
python3 scripts/validate_web_realtime_contract.py \
  --out artifacts/evidence/web-realtime-contract.json
```

通过标准：`status=ok`，报告确认浏览器 `getUserMedia`、`gpt-realtime-translate`
WebRTC session 创建、OpenAI transcript event normalization、backend event posting、
public SSE subscription，以及 stable correction display；报告里不能包含 client secret、
event token、API key 或 Secret Manager resource name。

跑离线 OpenAI/翻译链路前，先验证 YouTube archive route，不下载 captions，也不调用 OpenAI：

```bash
python3 scripts/run_offline_archive_preflight.py \
  --live-url "https://www.youtube.com/watch?v=VIDEO_ID" \
  --sunday YYYY-MM-DD \
  --out artifacts/evidence/offline-archive-preflight.json
```

通过标准：`status=ok`，并且 `offlineRoute.strategy=captions_first_then_asr`。如果
`offlineRoute.decision=use_caption_track`，继续 caption route；如果
`decision=use_asr_fallback`，确认后续 ASR fallback 使用 `gpt-4o-transcribe`，且不走
realtime。

跑离线翻译或 stable-correction 前，先用生产同款 OpenAI Responses 路径预检文本模型：

```bash
python3 scripts/run_openai_model_access_preflight.py \
  --cloud-run-service sermon-zh-caption-web \
  --project ai-for-god \
  --region us-west1 \
  --model gpt-5.5-mini \
  --out artifacts/evidence/openai-model-access-preflight.json
```

通过标准：报告是 `status=ok`，并且 `responses_model:gpt-5.5-mini`
检查通过。如果这里出现 model 404 或 access error，不要把离线中文字幕 VTT/SRT 或稳定修正版
视为 production-ready；先修正模型名/权限，再重跑翻译和 stable-correction 验证。

三份证据都可用后，跑统一 readiness gate：

```bash
python3 scripts/run_sunday_evidence_bundle.py \
  --sunday YYYY-MM-DD \
  --session-id <worker_session_id> \
  --artifact-location gcs \
  --artifact-bucket sermon-zh-artifacts-ai-for-god \
  --artifact-prefix sundays \
  --realtime-location gcs \
  --realtime-event-gcs-prefix gs://sermon-zh-artifacts-ai-for-god/realtime-events \
  --require-readable-sunday-artifacts \
  --realtime-smoke-report artifacts/realtime-openai-smoke/report.json \
  --cloud-run-config-report artifacts/evidence/cloud-run-realtime-config.json \
  --cloud-run-api-preflight-report artifacts/evidence/cloud-run-api-preflight.json \
  --realtime-audio-source-preflight-report artifacts/evidence/realtime-audio-source-preflight.json \
  --web-realtime-contract-report artifacts/evidence/web-realtime-contract.json \
  --realtime-public-sse-smoke-report artifacts/evidence/realtime-public-sse-smoke.json \
  --realtime-openai-smoke-report artifacts/evidence/realtime-openai-smoke/report.json \
  --realtime-session-validation-report artifacts/evidence/realtime-openai-smoke/realtime-session-validation.json \
  --offline-archive-preflight-report artifacts/evidence/offline-archive-preflight.json \
  --offline-chain-validation-report artifacts/evidence/offline-chain-validation.json \
  --offline-asr-smoke-report artifacts/evidence/offline-asr-fallback-smoke/report.json \
  --offline-translation-report artifacts/evidence/offline-caption-route/model-output/openai-translation-report.json \
  --sunday-manifest-validation-report artifacts/evidence/sunday-manifest-validation.json \
  --openai-model-access-preflight-report artifacts/evidence/openai-model-access-preflight.json \
  --openai-alternative-model-access-preflight-report artifacts/evidence/openai-model-access-preflight-gpt-5.5.json \
  --cloud-run-update-plan artifacts/evidence/cloud-run-realtime-update-plan.json \
  --cloud-run-update-execution artifacts/evidence/cloud-run-realtime-update-execution.json \
  --out artifacts/evidence/caption-route-readiness.json \
  --evidence-matrix-out artifacts/evidence/production-evidence-matrix.json \
  --goal-audit-out artifacts/evidence/production-goal-readiness-audit.json \
  --bundle-report-out artifacts/evidence/sunday-evidence-bundle.json
```

把 `run_sunday_evidence_bundle.py` 当作周日 evidence 入口：它会展开标准 local/GCS
路径、调用 `validate_production_readiness.py`，并可继续调用
`collect_production_evidence_matrix.py` 和 `audit_production_goal_readiness.py`；
任何必需证据缺失或失败都会返回非零。如果已经知道 session id，也可以直接传
`--realtime-session-id`；否则 runner 会从 realtime smoke report 读取。如果 smoke report
里包含 `realtimeEventsJsonl`，runner 会优先使用这个精确 JSONL URI。如果传了
`--evidence-matrix-out` 或 `--goal-audit-out` 但没有传 `--out`，runner 会自动在
`artifacts/evidence/` 下写一份带日期和 session id 的 production-readiness report。
用 `--bundle-report-out` 保存顶层 runner summary，里面包含展开后的命令和每一步 return code。
alternative model access report 只是旁证；`gpt-5.5` preflight 变绿，并不代表 required
`gpt-5.5-mini` stable/offline route 已满足。
如果 production-readiness verifier 在写出 `--out` 前就退出，bundle 会写一份最小 failed
readiness report，然后继续跑 matrix/audit；这样早期 artifact 缺失时，周日交接仍然能看到
最终状态板和下一步动作。
同样，如果 matrix generation 在写出 `--evidence-matrix-out` 前退出，bundle 会写一份最小
incomplete matrix，让 goal audit 仍然可以运行并记录交接失败点。

收集到 provider、offline、Cloud Run、Sunday-manifest 证据后，先生成更可读的 evidence
matrix：

```bash
python3 scripts/collect_production_evidence_matrix.py \
  --cloud-run-config-report artifacts/evidence/cloud-run-realtime-config.json \
  --cloud-run-api-preflight-report artifacts/evidence/cloud-run-api-preflight.json \
  --realtime-audio-source-preflight-report artifacts/evidence/realtime-audio-source-preflight.json \
  --web-realtime-contract-report artifacts/evidence/web-realtime-contract.json \
  --realtime-public-sse-smoke-report artifacts/evidence/realtime-public-sse-smoke.json \
  --realtime-openai-smoke-report artifacts/evidence/realtime-openai-smoke/report.json \
  --realtime-session-validation-report artifacts/evidence/realtime-openai-smoke/realtime-session-validation.json \
  --offline-archive-preflight-report artifacts/evidence/offline-archive-preflight.json \
  --offline-chain-validation-report artifacts/evidence/offline-chain-validation.json \
  --offline-asr-smoke-report artifacts/evidence/offline-asr-fallback-smoke/report.json \
  --offline-translation-report artifacts/evidence/offline-caption-route/model-output/openai-translation-report.json \
  --sunday-manifest-validation-report artifacts/evidence/sunday-manifest-validation.json \
  --openai-model-access-preflight-report artifacts/evidence/openai-model-access-preflight.json \
  --openai-alternative-model-access-preflight-report artifacts/evidence/openai-model-access-preflight-gpt-5.5.json \
  --update-plan artifacts/evidence/cloud-run-realtime-update-plan.json \
  --update-execution artifacts/evidence/cloud-run-realtime-update-execution.json \
  --production-readiness-report artifacts/evidence/caption-route-readiness.json \
  --production-readiness-report artifacts/evidence/asr-route-readiness.json \
  --out artifacts/evidence/production-evidence-matrix.json
```

把 matrix 当作周日状态板：它会列出每个要求、证明它的具体 evidence file，以及每个
failed/missing row 的下一步动作。Realtime OpenAI smoke report 只证明 provider 行为；
要同时传入 `realtime-session-validation.json`，让已保存 JSONL 经过 session id 连续性、
event id 严格递增、英文 input transcript events、中文 caption events 的检查。离线翻译
report 要配合 `offline-chain-validation.json`，这样模型访问失败导致中文 VTT/SRT/playback/manifest
未产出的事实也会留在 matrix 里。

当前交接流程优先使用 refresh wrapper 再读 matrix。它会先重建
`artifacts/evidence/manifest-promotion-guard` 下的本地 Sunday manifest evidence，
写出 `artifacts/evidence/offline-chain-validation.json`，准备
`artifacts/evidence/gcs-sunday-manifest-publish-plan.json`，然后刷新 matrix/unblock/audit；
这个流程不会 apply Cloud Run，也不会上传 GCS：

```bash
python3 scripts/refresh_production_preflight_evidence.py \
  --sunday YYYY-MM-DD \
  --out artifacts/evidence/production-preflight-refresh.json
```

生成 matrix 后，再跑目标级审计：

```bash
python3 scripts/audit_production_goal_readiness.py \
  --production-readiness-report artifacts/evidence/caption-route-readiness.json \
  --production-readiness-report artifacts/evidence/asr-route-readiness.json \
  --cloud-run-config-report artifacts/evidence/cloud-run-realtime-config.json \
  --cloud-run-api-preflight-report artifacts/evidence/cloud-run-api-preflight.json \
  --evidence-matrix-report artifacts/evidence/production-evidence-matrix.json
```

这个 audit 故意比单次 Sunday bundle 更严格：只有 realtime live evidence、stable-correction
evidence、caption-route archive run、no-caption ASR fallback archive run、Cloud Run/GCS
manifest evidence，以及 realtime-safe Cloud Run config/API evidence 都齐了，才会从
`incomplete` 变成 `complete`。matrix 是人类可读交接视图，也是 audit 的输入，避免
已经证明的 row-level evidence，例如 realtime session JSONL validation，在目标级验证里被漏掉。

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

## 14. Rollback Notes

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
