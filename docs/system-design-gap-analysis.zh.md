# System Design 实现差距审计

更新：2026-06-23

English version: [system-design-gap-analysis.md](./system-design-gap-analysis.md)

## 范围

这份审计把当前 repo 和已经部署的 POC，对照产品北星检查：

```text
每周日 11:30 PT 场证道进行时，中文会众应该能看到可用的中文字幕。
```

当前 POC 很有价值，但还不是 [system-design.zh.md](./system-design.zh.md) 描述的 production system。最大的风险是：把 live archive/offline replay 跑通，误认为已经可以稳定服务 11:30 现场会众。

## 当前证据

| 领域 | 当前状态 | 证据 |
|---|---|---|
| Public VOD 时间分析 | 已完成 | Public VOD 对 11:30 场太晚，设计已经正确转向早场 live source。 |
| Live archive POC | 部分完成 | `scripts/prepare_live_link_playback.py` 可以从 live archive URL 生成本地/GCS 播放数据。 |
| OpenAI 翻译 E2E | 部分完成 | `scripts/translate_playback_with_openai.py` 可以把 prepared playback 里的占位中文替换成真实 segment-level 翻译。 |
| 静态 PWA | 部分完成 | Cloud Run 当前能服务 web prototype，local/remote E2E 检查通过。 |
| 免责声明与 secret hygiene | 部分完成 | Public UI 有免责声明，测试会扫描 browser playback 输出，公开生成物不含 raw key 和 Secret Manager resource name。 |
| Backend scaffold | 部分完成，但未部署 | `backend/` 有 public Sunday read API、admin generation API、manifest filtering、worker planner；但当前 Dockerfile 只服务静态 `web/`。 |
| GCS artifact storage | 部分完成 | 生成物可以上传到 GCS，但还没有每周稳定的 Sunday manifest promotion 流程。 |

## 需求矩阵

| 需求 | 状态 | 缺口 |
|---|---|---|
| Admin 手动触发 live URL 和可选证道开始时间 | 部分完成 | UI 概念和 backend planner 字段存在，但线上服务没有真正可用的 admin generation API。 |
| 定时自动抓取 live source | 未完成 | 没有 `live-source-monitor`、Cloud Scheduler、same-sermon confidence check、09:58 fallback alert。 |
| 同一周日所有用户看到同一份生成物 | 部分完成 | 存储模型已写入设计，但没有 promoted `sundays/YYYY-MM-DD/cloud-manifest.json` 指针。 |
| 会众只读视图 | 未完成 | 当前页面仍混合了会众播放和 operator 控制；普通用户不应看到 generation/export/publish/admin controls。 |
| 11:25 readiness 和 publish gate | 未完成 | 没有 durable readiness state、publish timestamp、published artifact URI、fallback state。 |
| 真实生成中文字幕 | 部分完成 | prepared playback 已能 batch OpenAI 翻译，但 backend worker 还不会自动跑翻译步骤。 |
| 低延迟实时字幕 | 未完成 | 没有 streaming audio ingest、realtime ASR/translation provider、WebSocket/SSE caption stream、latency instrumentation。 |
| 经文、人名、术语优先 | 未完成 | UI 有静态 sidebar 示例，但没有 Bible index、glossary resolver、review queue。 |
| 笔记和金句提取 | 未完成 | 只在规划中；还没有可追踪的 `insights/*.json` 输出和 UI 集成。 |
| Cloud Run API 部署 | 未完成 | 当前 `Dockerfile` 用 `python -m http.server` 服务 `web/`；线上 `/api/*` 不是 backend API。 |
| Firestore 状态 | 未完成 | session 和 caption state 只在文档模型中，还没有持久化。 |
| GCS/Secret 边界 | 部分完成 | 当前 artifact 已做清理；后续 worker logs、runbook、manifest 也必须持续遵守。 |

## P0 阻塞缺口

1. **拆分 public 和 operator surface。** 11:30 会众页面必须是干净的只读字幕视图；operator controls 需要放在 admin route 或认证模式里。
2. **部署 backend/API surface。** 当前 Cloud Run 是 static-only。Production 需要 combined static/API service，或拆成 `web` 与 `api` 两个服务并明确 routing。
3. **稳定 Sunday manifest promotion。** 每个周日需要稳定 server-side pointer，例如 `gs://<bucket>/sundays/YYYY-MM-DD/cloud-manifest.json`，并包含 completion/readiness state。
4. **让 backend generation 跑完整真实翻译链路。** `backend.worker` 目前只规划 `prepare_live_link_playback.py`，还没有自动执行 OpenAI translation、发布 translated playback、promote Sunday manifest。
5. **加入 readiness/publish state。** Operator 需要在 11:25 PT 前看到 `source_detected`、`caption_generating`、`needs_review`、`ready`、`published`、`fallback` 等状态。
6. **实现 source discovery。** 手动链接有救场价值，但 Sunday system 仍需要自动发现 8:30/10:00 live source，并验证是否同篇证道。

## P1/P2 缺口

- Realtime streaming provider interface 和 latency budget enforcement。
- Firestore 或等价的 durable session/segment state。
- Cloud Scheduler/Tasks 触发 Sunday monitor 和 worker job。
- Dedicated service account 和 GCS/Secret Manager 最小权限 IAM。
- Operator authentication 真正接入 deployed admin API。
- 确定性的经文、Bible book、人名、神学术语 resolver。
- Timeline editing persistence：split、merge、lock、reviewed export。
- 笔记、总结、应用问题、金句提取，并保留 source segment traceability。
- Historical replay fixtures，用来回归测试翻译质量和 UI 稳定性。
- 中英文文档 parity：当前中文 system design 的 API/data-model 细节比英文版更完整。

## 需要补上的验证缺口

- Congregation-mode DOM/E2E test：public view 不能出现 monitoring、manual trigger、simulation playback、export、publish、logs 或其他 operator controls。
- Manifest contract test：public Sunday manifest 必须包含 readiness/completion state、generation time、live URL、sermon title、translation status 和完整 output references，才能被视为 ready。
- Docker/API shape test：避免文档声称部署了 API，但 container 实际只服务 static files。
- 11:25 no-go checklist：明确 operator 发布给 11:30 会众前必须看到的证据。
- 11:30 congregation smoke evidence：记录 mobile/tablet 访问、字幕可读性、当前 Sunday slice，以及发布字幕是真实生成还是 placeholder。

## 推荐下一步开发顺序

1. **P0-A: Public/operator split。** 增加明确的 congregation/operator mode，从 public mode 隐藏所有 admin controls，并补 iPhone/iPad E2E。
2. **P0-B: Sunday manifest promotion。** 写一个小的 promotion command，验证 run manifest 后复制/提升到稳定 Sunday pointer。
3. **P0-C: 部署 backend API。** 把 static-only Cloud Run container 换成能同时服务 API 和 static assets 的 server，或部署单独 API service 并更新文档。
4. **P0-D: Full worker chain。** 让 backend worker 执行 prepare -> translate -> sanitize -> upload -> promote，保留 dry-run mode 和测试。
5. **P0-E: Readiness/publish gate。** 持久化 readiness state，并暴露给 operator UI 和 public Sunday read path。
6. **P1: Scheduled live monitor。** 加 Sunday source discovery，并先用 fixture tests 覆盖，再依赖 live network 行为。

## 部署判断

当前 static PWA 可以继续保留在线上，用于 UI 和 playback simulation 测试。但 production-style redeploy 应该等到至少 public/operator split 和 backend API routing 完成。再次部署当前 static-only image 不能降低主要 11:30 风险，因为它仍然不能通过 backend API trigger、publish 或 serve Sunday manifests。
