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
| Backend scaffold | 部分完成 | `backend/` 有 public Sunday read API、admin generation API、realtime session/event API、manifest filtering、worker planner；当前 Dockerfile 启动 `python -m backend.app`。 |
| GCS artifact storage | 部分完成 | 生成物可以上传到 GCS，但还没有每周稳定的 Sunday manifest promotion 流程。 |

## 需求矩阵

| 需求 | 状态 | 缺口 |
|---|---|---|
| Admin 手动触发 live URL 和可选证道开始时间 | 部分完成 | UI 概念和 backend planner 字段存在，但线上服务没有真正可用的 admin generation API。 |
| 定时自动抓取 live source | 未完成 | 没有 `live-source-monitor`、Cloud Scheduler、same-sermon confidence check、09:58 fallback alert。 |
| 同一周日所有用户看到同一份生成物 | 部分完成 | 存储模型已写入设计，但没有 promoted `sundays/YYYY-MM-DD/cloud-manifest.json` 指针。 |
| 会众只读视图 | 未完成 | 当前页面仍混合了会众播放和 operator 控制；普通用户不应看到 generation/export/publish/admin controls。 |
| 11:25 readiness 和 publish gate | 未完成 | 没有 durable readiness state、publish timestamp、published artifact URI、fallback state。 |
| 真实生成中文字幕 | 部分完成 | prepared playback 已能 batch OpenAI 翻译，worker plan 已包含 prepare -> translate -> notes -> upload -> promote；仍需用真实周日输入做 production 验证。 |
| 离线 ASR fallback | 部分完成 | 没有英文 captions 时，live-archive preparation path 可以抽音频并请求 `gpt-4o-transcribe`，再进入 `gpt-5.5-mini` 翻译；还需要用真实 YouTube/archive 验证。 |
| 低延迟实时字幕 | 部分完成 | Admin iPad/iPhone mic 可以创建 OpenAI Realtime translation session，用 browser WebRTC 送音频，把英文/中文 deltas 发回 backend memory/JSONL，并通过 SSE 推给会众字幕页。`scripts/realtime_media_worker.py` 可以创建 backend-only session、规划授权音频/YouTube source prep，把 24 kHz PCM16 音频送入 OpenAI translation WebSocket，并把英文/中文 deltas 发布到同一条 session stream。`scripts/stabilize_realtime_deltas_with_openai.py` 可以用 `gpt-5.5-mini` 把保存的 realtime 英文窗口生成 stable Chinese corrections。还缺真实授权源 live validation 和 durable state storage。 |
| 经文、人名、术语优先 | 未完成 | UI 有静态 sidebar 示例，但没有 Bible index、glossary resolver、review queue。 |
| 笔记和金句提取 | 部分完成 | Worker plan 已包含 `generate_notes_with_openai.py` 和 `gpt-5.5-mini`；production review 和 UI 展示还要继续硬化。 |
| Cloud Run API 部署 | 部分完成 | 当前 `Dockerfile` 启动 `backend.app`；仍需验证部署环境里的 `/api/*`、Secret Manager 和 realtime session creation。 |
| Firestore 状态 | 未完成 | session 和 caption state 只在文档模型中，还没有持久化。 |
| GCS/Secret 边界 | 部分完成 | 当前 artifact 已做清理；后续 worker logs、runbook、manifest 也必须持续遵守。 |

## P0 阻塞缺口

1. **拆分 public 和 operator surface。** 11:30 会众页面必须是干净的只读字幕视图；operator controls 需要放在 admin route 或认证模式里。
2. **验证并部署 backend/API surface。** 仓库 container 现在由 `backend.app` 同时服务 static assets 和 `/api/*`；production 还需要验证 routing、auth、Secret Manager 和 realtime session creation。
3. **稳定 Sunday manifest promotion。** 每个周日需要稳定 server-side pointer，例如 `gs://<bucket>/sundays/YYYY-MM-DD/cloud-manifest.json`，并包含 completion/readiness state。
4. **用新周日输入验证真实 generation chain。** `backend.worker` 现在规划 prepare -> translate -> notes -> upload -> promote，但还需要用 live archive captions 和无 captions 的 ASR fallback 各跑一次 E2E。
5. **加入 readiness/publish state。** Operator 需要在 11:25 PT 前看到 `source_detected`、`caption_generating`、`needs_review`、`ready`、`published`、`fallback` 等状态。
6. **实现 source discovery。** 手动链接有救场价值，但 Sunday system 仍需要自动发现 8:30/10:00 live source，并验证是否同篇证道。

## P1/P2 缺口

- Durable realtime session/segment storage 和 latency budget enforcement。
- Browser WebRTC 之外的 YouTube live / 授权音频 server-side OpenAI Realtime audio streaming 的 live validation 和生产加固。
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
- Docker/API shape test：避免文档声称 production-ready，但 `/api/*`、auth、Secret Manager、realtime session creation 尚未验证。
- 11:25 no-go checklist：明确 operator 发布给 11:30 会众前必须看到的证据。
- 11:30 congregation smoke evidence：记录 mobile/tablet 访问、字幕可读性、当前 Sunday slice，以及发布字幕是真实生成还是 placeholder。

## 推荐下一步开发顺序

1. **P0-A: Public/operator split。** 增加明确的 congregation/operator mode，从 public mode 隐藏所有 admin controls，并补 iPhone/iPad E2E。
2. **P0-B: Sunday manifest promotion。** 写一个小的 promotion command，验证 run manifest 后复制/提升到稳定 Sunday pointer。
3. **P0-C: 验证 backend API deployment。** 部署或重部署 `backend.app` container，并 smoke test `/api/health`、admin status、realtime session creation、public Sunday reads。
4. **P0-D: Full worker chain E2E。** 跑 prepare -> 必要时 ASR fallback -> translate -> notes -> upload -> promote，并保留 dry-run mode 和测试。
5. **P0-E: Readiness/publish gate。** 持久化 readiness state，并暴露给 operator UI 和 public Sunday read path。
6. **P1: Scheduled live monitor。** 加 Sunday source discovery，并先用 fixture tests 覆盖，再依赖 live network 行为。

## 部署判断

当前 PWA 可以继续保留在线上，用于 UI 和 playback simulation 测试。但 production-style redeploy 应该使用 `backend.app` container；只有在 Cloud Run 中验证 `/api/health`、admin status、realtime session creation、Sunday manifest reads、Secret Manager access 后，才算接近 11:30 production-ready。
