# 证道视频中文字幕 Pipeline System Design

English version: [system-design.md](./system-design.md)

日期：2026-06-22  
更新：2026-06-23  
目标频道：Mariners Church  
主要目标：每周日 11:30 PT 场开始时，让正在听证道的中文会众有可使用的中文字幕
默认策略：优先使用 11:30 前最早可验证的同篇证道直播准备字幕；10:00 PT 作为保守生产默认；公开视频 VOD 作为离线质量补齐源

## 0. 产品北星

这个项目的核心目的不是单纯“生成字幕文件”，也不是只做事后归档。核心目的是：

```text
在 11:30 PT 场证道进行时，帮助听不懂英文或更依赖中文阅读的会众，实时理解正在被传讲的信息。
```

因此所有开发优先级按下面顺序排序：

1. 11:30 场会众是否能在证道开始时看到可用中文字幕。
2. 字幕是否足够及时，不打断听道节奏。
3. 圣经经文、人名、神学术语是否足够准确，帮助理解而不是制造干扰。
4. operator 是否能在 11:30 前确认源、发现问题、发布字幕。
5. 离线字幕、笔记、金句是否能帮助后续复盘和提升下周质量。

## 1. 设计结论

公开视频 VOD 不能满足 11:30 场会众实时使用的目标。目标视频 `V6OKiwbjDZE` 在公开层面约 12:28 PT 才可见，历史主证道视频也集中在 12:28-12:43 PT 公开。公开视频只能服务回看和离线质量补齐，不能作为现场会众字幕的主输入。

新的可行路径是使用 Mariners Online / YouTube Live 的早场直播源，为 11:30 场提前准备中文字幕。官方 Mariners Online 页面显示周日直播时间为 7:00、8:30、10:00、11:30 AM PT；YouTube `@marinerschurch/streams` 也存在同一篇证道的 live archive `FsUijL9uB1I`，metadata 显示 `live_status=was_live`、`media_type=livestream`，其 `release_timestamp` 换算为 2026-06-21 08:21:04 PDT。这个时间点说明 8:30 场很可能已经是可用来源。V1 应优先尝试 8:30 场；若 8:30 无法稳定验证或接入，则使用 10:00 PT 直播作为保守生产输入源。

系统分成两条链路：

- 会众字幕链路：8:20 PT 开始尝试 8:30 场；若失败，9:50 PT 再尝试 10:00 场；直播期间边听边生成中文字幕，11:30 前发布给 11:30 场会众使用。
- 离线质量链路：公开视频或直播归档可用后，生成高质量字幕、时间轴编辑、经文 sidebar、笔记和金句，用于修正、归档和提升下一次服务。

触发方式分成两种：

| 触发方式 | 负责人 | 用途 |
|---|---|---|
| Admin 手动触发 | operator/admin | 手动输入直播或直播归档链接，可选填写证道大致开始时间，例如 `00:23:25`，用于自动监控失败、已知链接可用、或需要快速定位时救场。 |
| 定时自动抓取 | 后端 | 每周日自动检查 8:30 和 10:00 场官方 live source，自动判断证道开始时间，自动开始字幕采集、翻译、经文解析、总结和金句生成。 |

普通会众打开网页时不触发生成任务。字幕采集、翻译、总结、金句抓取、发布状态都由 admin 或后端完成；普通用户只读取同一个周日切片里的发布内容。因此多个用户进入网页，理论上看到的是同一份正在生成或已经生成的字幕，而不是每人启动一套独立 pipeline。

周日切片作为主要页面和存储单位：

```text
public page: /sundays/2026-06-21
GCS prefix:  gs://<bucket>/sundays/2026-06-21/<session_id>/
session id:  sunday-20260621-1000
```

同一个周日切片下可以有 realtime session、offline job、review export、notes、quotes 等多类生成物，但会众页面只读取已发布或正在发布的 caption/scripture/insight state。

## 2. Source Strategy

### 2.1 输入源优先级

| 优先级 | 输入源 | 用途 | SLA 可行性 | 说明 |
|---:|---|---|---|---|
| 1 | 频道方授权音频或导播音频 | 实时字幕 | 高 | 最稳定，推荐长期方案 |
| 2 | 8:30 PT YouTube Live / Mariners Online | 实时字幕 | 高 | 若同篇证道确认，SLA 余量最大 |
| 3 | 10:00 PT YouTube Live / Mariners Online | 实时字幕 | 高 | 保守生产默认，仍有足够 11:30 前处理余量 |
| 4 | Operator 设备麦克风/外接音频 | 实时兜底 | 中 | iPhone/iPad 可用，但音质依赖环境 |
| 5 | YouTube live archive | 会前补齐/复核 | 中 | 若归档及时可辅助 11:30 前复核，否则进入事后质量链路 |
| 6 | 公开视频 VOD | 高质量离线 | 低 | 不满足 11:30 会众实时使用，只适合事后字幕 |

### 2.2 周日运行时间线

| 时间 PT | 系统行为 |
|---|---|
| 08:20 | `live_source_monitor` 启动，检测 8:30 场 Mariners Online、YouTube streams、已知 live URL |
| 08:30 | 如果 8:30 场确认同篇证道并可接入，启动 realtime caption session |
| 09:20 | 若 8:30 场成功，产出第一版 stable captions 并进入快速 review |
| 09:50 | 若 8:30 场失败或内容不匹配，重新检测 10:00 场 |
| 09:58 | 如果 10:00 直播源仍未发现，提醒 operator 准备手动音频输入 |
| 10:00 | 开始接入 10:00 场直播音频，启动或重启 realtime caption session |
| 10:00-10:55 | 实时生成英文转写、中文字幕、经文候选、术语标注 |
| 10:55-11:15 | 自动整理 stable captions，补齐低置信片段，突出经文/人名待确认项 |
| 11:15-11:25 | operator 快速 review，修正关键经文、人名、术语 |
| 11:25-11:30 | 发布会众可用字幕视图，并确认 iPhone/iPad/会场显示可访问 |
| 11:30-11:50 | 会众实时使用字幕听道；operator 只做轻量监控和必要热修正 |
| 12:28+ | 公开视频 VOD 出现后进入离线高质量重处理 |

### 2.3 合规边界

系统不绕过权限、DRM 或平台访问控制。生产方案优先使用频道方授权音频、官方播放器可播放的直播、或 operator 自己设备的实时音频输入。若后续需要自动下载或归档第三方平台内容，应先确认授权和平台规则。

## 3. Architecture

```mermaid
flowchart TD
  A["Scheduler / Cloud Scheduler"] --> B["live_source_monitor"]
  AA["Admin manual trigger"] --> BB["manual live URL + optional start hint"]
  B --> C{"Live source found?"}
  BB --> C
  C -->|yes| D["realtime_session_api"]
  C -->|no| E["operator_audio_fallback"]
  E --> D

  D --> F["audio_ingest"]
  F --> G["RealtimeTranslateProvider"]
  F --> H["StreamingASRProvider"]
  G --> I["draft Chinese captions"]
  H --> J["English transcript sidecar"]
  I --> K["stable caption assembler"]
  J --> K
  K --> L["Firestore caption_segments"]
  K --> W["GCS Sunday artifacts"]
  L --> M["PWA caption UI"]
  W --> M
  K --> N["async scripture resolver"]
  N --> O["sidebar scripture cards"]
  L --> P["VTT/SRT exporter"]

  Q["Public VOD / live archive"] --> R["offline_job_worker"]
  R --> S["offline ASR / translation / alignment"]
  S --> T["review timeline editor"]
  T --> P
  T --> U["notes and quotes generator"]
```

### 3.1 Services

| Service | 责任 |
|---|---|
| `web` | iPhone/iPad PWA，面向 operator 和 11:30 会众字幕视图，显示实时字幕、经文 sidebar、review/publish UI |
| `api` | session、job、segments、exports、operator auth |
| `realtime-relay` | 可选，接入非浏览器音频源并转发给 realtime provider |
| `worker` | 离线 ASR、翻译、时间轴归一、经文解析、笔记和金句 |
| `live-source-monitor` | 周日定时检查官方 live 页面、YouTube streams、fallback 状态 |

默认部署在 Cloud Run。Firestore 存储状态和字幕片段，Cloud Storage/GCS 存储所有生成物，包括音频片段、原始模型输出、字幕 VTT/SRT、播放模拟 JS、离线笔记和金句。Secret Manager 存储模型/API key；Cloud Run 只通过 service account 读取 secret，代码和生成文件不包含 key 明文。Cloud Tasks 用于离线 job 编排。部署前 secret 清单详见 [Cloud Run 部署准备与 Secret Manager 清单](./cloud-run-deployment-prep.zh.md)。

Admin UI 与会众 UI 的权限边界：

| UI | 可做的事 | 不应暴露 |
|---|---|---|
| Admin/operator view | 设置周日切片、手动 live URL、可选开始时间、启动自动抓取、发布/冻结字幕、review 经文和术语 | API key 明文、普通用户 token、内部 model trace |
| Congregation view | 读取当前周日已发布或正在发布的中文字幕、经文 sidebar、证道笔记和金句 | 手动触发按钮、Secret Manager resource name、后台 job 控制 |

### 3.1.1 生成物与 Secret 边界

所有“内容物生成”默认进入 GCS bucket，而不是只留在 Cloud Run 容器本地磁盘：

| 类型 | GCS 路径建议 | 说明 |
|---|---|---|
| POC report | `gs://<bucket>/runs/<date>/<session_id>/artifacts/report.json` | 记录 live link、匹配 VOD、证道开始时间、warnings |
| 字幕文件 | `gs://<bucket>/runs/<date>/<session_id>/artifacts/*.vtt|*.srt` | live-aligned 与 local timeline 都保留 |
| 播放数据 | `gs://<bucket>/runs/<date>/<session_id>/web/playback-simulation.generated.js` | PWA/Cloud Run 可加载的字幕播放数据 |
| 模型原始输出 | `gs://<bucket>/runs/<date>/<session_id>/model-output/*.jsonl` | 只存生成内容，不存 secret |
| 笔记/金句 | `gs://<bucket>/runs/<date>/<session_id>/insights/*.json` | 后续离线功能输出 |

Secret Manager 只保存敏感 key，例如：

```text
projects/<project-id>/secrets/openai-api-key/versions/latest
```

系统配置只保存 Secret Manager resource name，例如 `api_key_secret`。任何 report、playback JS、manifest、日志都必须标记 `apiKeyMaterialIncluded=false`，不能写入 key 值。
生产版 public playback JS 和公开 GCS artifact 不应包含 Secret Manager resource name；secret resource name 只允许保留在非公开部署配置中。

### 3.2 Frontend

V1 使用 Web/PWA，而不是先做 iOS App。Web 端必须同时支持两个使用面：

- operator view：11:30 前确认源、字幕质量、经文/人名、发布状态。
- congregation view：11:30 场会众打开后只看到清晰、稳定、低干扰的中文字幕和必要经文提示。

原因是：

- iPhone/iPad Safari 可以快速访问和部署，适合 operator 和会众现场使用。
- 主要 UI 是字幕监控、review、经文 sidebar、时间轴编辑，Web 足够。
- iOS 浏览器不能可靠捕获其他 app 或标签页系统音频，所以音频输入要通过官方源、服务器 relay、外接输入或后续 iOS companion app 解决。

PWA 布局要求：

- iPhone 竖屏会众视图：主字幕大字显示，经文提示可收起，不显示复杂控制。
- iPhone 横屏会众视图：字幕优先，保留少量经文/当前段落提示。
- iPad 竖屏 operator 视图：字幕区 + 下方时间轴，经文 sidebar 可折叠。
- iPad 横屏 operator 视图：三栏布局，左侧源/状态，中间字幕，右侧经文/笔记。
- Admin settings 必须保留手动触发入口：直播链接输入、证道大致开始时间、周日切片 selector、自动抓取状态。

## 4. Realtime Pipeline

### 4.1 Main Flow

1. `live_source_monitor` 优先发现 8:30 PT live source；若失败则发现 10:00 PT live source。
2. `api` 创建 realtime session，返回短期 token 和 session id。
3. `audio_ingest` 将音频以低延迟方式送入 provider。
4. `RealtimeTranslateProvider` 生成 draft Chinese captions。
5. `StreamingASRProvider` 同时生成英文 sidecar transcript。
6. `stable_caption_assembler` 合并、去重、修正断句，产出 stable captions。
7. `scripture_resolver` 异步解析经文、人名、术语，不阻塞字幕显示。
8. `publisher` 在 11:25 前发布会众可用字幕视图；`exporter` 同步生成 rolling VTT/SRT 作为兜底和归档。

### 4.2 Latency Budget

| 阶段 | 目标 |
|---|---:|
| 音频采集/上传 | 300-800 ms |
| 首个中文 draft caption | p50 <= 2.5 s |
| stable caption | p95 <= 6 s |
| 经文 sidebar 更新 | stable 后 1-3 s |
| 断线重连恢复 | <= 10 s |
| 会众视图热修正生效 | <= 3 s |

### 4.3 Caption States

| 状态 | 用途 |
|---|---|
| `draft` | 快速显示，可被替换，不导出 |
| `stable` | 已确认片段，可进入 sidebar 和 rolling export |
| `reviewed` | 人工确认后用于会众视图和最终导出 |
| `published` | 已发布给 11:30 场会众使用，可被热修正 |
| `locked` | 关键经文、人名、金句引用，不再被自动流程覆盖 |

## 5. Offline Pipeline

离线链路服务主目标：为 11:30 会众字幕体验提供会前准备、质量复核和事后修正。它不是产品核心体验的替代品；如果离线链路不能帮助 11:30 场会众听道，就应降级为后续质量工具。

状态机：

```text
submitted
-> source_checking
-> source_ready | source_waiting | source_failed
-> caption_probe
-> source_captions_imported | audio_extracting
-> audio_ready
-> asr_running
-> english_transcript_ready
-> translation_running
-> chinese_segments_ready
-> alignment_normalizing
-> captions_ready
-> scripture_enriching
-> enriched
-> insights_generating
-> insights_ready
-> reviewed
-> export_ready
```

离线规则：

- 如果 URL 中已有人工字幕或可用英文字幕，先导入字幕。
- 如果没有字幕，提取音频后 ASR。
- 翻译完成后做时间轴归一，保留原 segment id。
- 时间轴 UI 支持上下滑动、单句拖动、批量 offset、split、merge、lock。
- 导出只使用 `edited_zh` track。

## 6. Data Model

### 6.1 Realtime Session

```json
{
  "session_id": "rt_2026_06_28_1000",
  "channel": "Mariners Church",
  "source_type": "youtube_live | mariners_online | authorized_audio | operator_audio",
  "source_url": "https://...",
  "scheduled_start_at": "2026-06-28T10:00:00-07:00",
  "actual_start_at": "2026-06-28T10:00:12-07:00",
  "status": "monitoring | live | reconnecting | ended | failed",
  "sla_target_at": "2026-06-28T11:30:00-07:00",
  "hard_deadline_at": "2026-06-28T11:50:00-07:00"
}
```

### 6.2 Caption Segment

```json
{
  "segment_id": "seg_000123",
  "session_id": "rt_2026_06_28_1000",
  "start_ms": 742000,
  "end_ms": 748500,
  "source_text": "Aaron stood between the dead and the living.",
  "zh_text": "亚伦站在死人和活人中间。",
  "state": "stable",
  "confidence": 0.91,
  "revision": 3,
  "locked": false,
  "scripture_refs": ["Numbers 16"],
  "model_trace": {
    "asr_provider": "openai:gpt-realtime-whisper",
    "translation_provider": "openai:gpt-realtime-translate"
  }
}
```

### 6.3 Insight Output

```json
{
  "job_id": "offline_2026_06_28",
  "summary_zh": "...",
  "outline_zh": ["..."],
  "scriptures": [{"ref": "Numbers 16", "confidence": "exact"}],
  "quotes": [
    {
      "quote_zh": "...",
      "source_segment_id": "seg_000123",
      "timecode": "12:22",
      "source_text": "..."
    }
  ]
}
```

## 7. APIs

### 7.1 Realtime

| Method | Path | 说明 |
|---|---|---|
| `POST` | `/api/realtime/sessions` | 创建 realtime session，返回短期 token |
| `GET` | `/api/realtime/sessions/{id}` | 查询状态、源、SLA |
| `GET` | `/api/realtime/sessions/{id}/events` | SSE 推送 caption/status/scripture events |
| `POST` | `/api/realtime/sessions/{id}:reconnect` | 断线重连，从最新 cursor 恢复 |
| `POST` | `/api/realtime/sessions/{id}:freeze` | 冻结 rolling captions 进入 review |
| `POST` | `/api/realtime/sessions/{id}:publish` | 发布给 11:30 场会众字幕视图 |

### 7.2 Offline

| Method | Path | 说明 |
|---|---|---|
| `POST` | `/api/offline/jobs` | 提交 YouTube URL / live archive URL |
| `GET` | `/api/offline/jobs/{job_id}` | 查询 job 状态 |
| `GET` | `/api/offline/jobs/{job_id}/segments` | 获取字幕片段 |
| `PATCH` | `/api/offline/jobs/{job_id}/segments/{segment_id}` | 修改字幕文本或时间轴 |
| `POST` | `/api/offline/jobs/{job_id}/segments:batchOffset` | 批量平移时间轴 |
| `POST` | `/api/offline/jobs/{job_id}/segments/{segment_id}:split` | 拆分片段 |
| `POST` | `/api/offline/jobs/{job_id}/segments:merge` | 合并片段 |
| `POST` | `/api/offline/jobs/{job_id}/exports` | 生成 VTT/SRT |

## 8. Model Strategy

默认使用 provider interface，避免业务代码绑定单一模型。
模型价格、延迟和 benchmark 方案详见 [翻译模型与 Provider 比较](./model-provider-comparison.zh.md)。

| 任务 | Primary | Fallback |
|---|---|---|
| 实时中文字幕 | OpenAI `gpt-realtime-translate` | Gemini Live / Google STT + Translation |
| 实时英文转写 sidecar | OpenAI `gpt-realtime-whisper`, delay=low | Google STT V2 |
| 离线 ASR | OpenAI `gpt-4o-transcribe` | `gpt-4o-mini-transcribe` / Google batch STT |
| 离线翻译 | OpenAI GPT-5.5, reasoning effort medium | Google Translation Advanced + glossary |
| 经文识别 | deterministic Bible index + fuzzy model | rules only |
| 笔记和金句 | OpenAI GPT-5.5, reasoning effort medium | smaller model + stricter review |

Provider interfaces：

- `RealtimeTranslateProvider`
- `StreamingASRProvider`
- `OfflineASRProvider`
- `BatchTranslateProvider`
- `ScriptureResolver`
- `InsightProvider`

Glossary 数据：

- 圣经书卷中英文名
- 圣经人名
- Mariners Church 常见人名
- 常见神学术语
- 公开授权中文圣经文本索引

## 9. Scripture, Notes, And Quotes

经文处理分两层：

- deterministic：识别明确引用，例如 `Numbers 16`、`John 3:16`。
- fuzzy：识别隐含经文或 paraphrase，只作为候选，需要 review。

笔记和金句在 `captions_ready` 后生成：

- 中文摘要
- 证道大纲
- 经文列表
- 应用问题
- 5-8 条证道金句

金句必须满足：

- 忠于 source segment，不做营销式改写。
- 每条都有 `source_segment_id`、timecode、英文原文依据。
- 没有可追溯 source 的金句不能进入最终输出。

## 10. Reliability And Failure Modes

| 风险 | 处理 |
|---|---|
| 8:30 live source 未发现或不是同篇证道 | 自动转入 10:00 场监控 |
| 10:00 live source 未发现 | 9:58 提醒 operator，切换麦克风/外接音频 |
| 11:25 前无法发布会众视图 | 触发 no-go 告警，转为人工解释/备用翻译方式 |
| 直播页面变更 | 保留 YouTube streams、Mariners Online、manual URL 三种入口 |
| Cloud Run 连接超时 | 主动重连，Firestore 保存 cursor |
| Realtime provider 限流 | 降级为 streaming ASR + batch translation |
| 网络抖动 | 本地短 buffer + server cursor + gap backfill |
| 经文误识别 | exact 自动显示，fuzzy 仅候选 |
| 翻译漂移 | glossary + reviewed lock + offline 重处理 |
| iOS 后台/锁屏中断 | operator 模式要求前台常亮，V2 考虑 iOS companion app |

## 11. Acceptance Criteria

Realtime：

- 每周日 8:30 PT 或 10:00 PT 场直播可被系统接入或明确 fallback。
- first Chinese caption p50 <= 2.5 秒。
- stable Chinese caption p95 <= 6 秒。
- 30 分钟内断线重连不丢失 stable segment。
- 11:25 PT 前 operator 能确认并发布会众字幕视图。
- 11:30 PT 场开始时，会众可在 iPhone/iPad 打开可读中文字幕。
- 11:30-11:50 PT 证道进行中，字幕持续更新，热修正可在 3 秒内进入会众视图。
- VTT/SRT 导出作为兜底和归档，不是唯一成功标准。

Offline：

- 已有字幕时优先导入，不重复 ASR。
- 无字幕时自动音频提取、ASR、翻译、对齐。
- VTT/SRT 100% 可解析。
- 时间轴编辑后 segment id 稳定。
- 每条金句 100% 可追溯到 source segment。

UI：

- iPhone 竖屏/横屏会众视图可读、低干扰、无需复杂操作。
- iPad 竖屏/横屏 operator 视图可完成 review、经文查看、时间轴调整和发布。
- 字幕、按钮、sidebar 不重叠。

## 12. Implementation Phases

### Phase 1: Live Source Proof

- 实现 `live_source_monitor`，每周日 8:20 PT 检查 8:30 场 Mariners Online 和 YouTube streams；9:50 PT 检查 10:00 场作为兜底。
- 记录 live source 发现时间、URL、状态、metadata。
- 在一次真实周日 8:30 PT 或 10:00 PT 场完成端到端 dry run。

### Phase 2: Realtime MVP

- 实现 PWA operator screen 和 congregation caption view。
- 实现 realtime session API。
- 接入 realtime translation provider。
- 保存 stable captions 到 Firestore。
- 发布 11:30 会众字幕视图，并导出 rolling VTT/SRT 作为兜底。

### Phase 3: Offline Quality Pipeline

- 实现 offline job worker。
- 支持 YouTube VOD/live archive URL。
- 支持字幕导入、ASR、翻译、时间轴归一。
- 实现 review timeline editor。

### Phase 4: Scripture And Insights

- 建立 Bible index 和 glossary。
- 实现 scripture sidebar。
- 实现笔记、摘要、证道金句。
- 加入人工 review 和锁定机制。

### Phase 5: Production Hardening

- Cloud Run 部署。
- Auth、日志、告警、成本监控。
- Provider fallback。
- 周日自动运行 runbook。
- 评估是否需要 iOS companion app。

## 13. Source Evidence

- Mariners Online 官方页面：周日直播时间 7:00、8:30、10:00、11:30 AM PT，页面说明所有时间为 Pacific Time。  
  https://www.marinerschurch.org/online/
- Mariners Church 官方首页：Irvine 周日场次 8:30、10:00、11:30 AM。  
  https://www.marinerschurch.org/
- YouTube channel streams：Mariners Church live archive 列表。  
  https://www.youtube.com/@marinerschurch/streams
- 目标 VOD：`V6OKiwbjDZE`，公开视频，约 12:28 PT 可见。  
  https://www.youtube.com/watch?v=V6OKiwbjDZE
- 同篇证道 live archive：`FsUijL9uB1I`，`live_status=was_live`，`media_type=livestream`，`release_timestamp=2026-06-21 08:21:04 PDT`。  
  https://www.youtube.com/watch?v=FsUijL9uB1I
