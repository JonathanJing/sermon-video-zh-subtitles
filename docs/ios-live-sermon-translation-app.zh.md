# 证道实时翻译 iOS App 设计

状态：Design proposal

日期：2026-08-30

分支：`design/sermon-live-translation-ios`

## 1. 结论

第一版应做成一个 **会众端原生字幕接收器**，而不是让每一台 iPhone 各自录音、各自调用模型翻译。

推荐的 MVP：

- 复用当前后端已经生成的实时字幕和 stable correction。
- 将周六提前提取的版本编译成受控的 `Sermon Context Pack`，为周日现场提供经文、人名、术语和段落候选，但不把周六正文当作周日事实。
- App 通过公开 SSE 流接收 `draft -> stable -> final` 事件。
- 默认只显示大字号中文；英文原文、经文和历史字幕按需展开。
- App 不保存音频、不包含 OpenAI API key，也不默认申请麦克风权限。
- 音频采集作为后续独立的 operator/fallback 能力，不进入会众端第一版。

这让 App 聚焦于现场真正的问题：弱网络下仍能快速、安静、清楚地跟上证道，而不是在每台设备上重复一套不一致的翻译流水线。无论周六版本和周日现场多么接近，**周日实时英文始终是字幕事实来源**；周六内容只能帮助识别、检索和校正，不能提前填充讲员尚未说出的内容。

## 2. 产品边界

### 2.1 目标用户

主要用户是身处英文证道现场、希望阅读简体中文字幕的中文会众。用户通常：

- 单手持有 iPhone，注意力主要在讲员而不是 App。
- 不愿学习复杂控制，也不应看到 operator 日志和生产状态。
- 可能使用教会 Wi-Fi，也可能使用蜂窝网络。
- 需要大字、低干扰、低亮度和可靠的断线恢复。

次要用户是现场 operator。operator 需要音频源、模型状态、重连和发布控制，但这些能力应放在独立入口或后续独立 target 中，不能混入会众主界面。

### 2.2 MVP 成功定义

会众打开 App 后，不需要登录或配置直播链接，在 2 次点击以内看到当前中文字幕；网络短暂中断后能自动恢复，并清楚知道当前看到的是现场内容、正在重连，还是旧字幕。

建议产品指标：

| 指标 | MVP 目标 |
|---|---:|
| 打开 App 到显示已有现场字幕 | 正常网络 p95 <= 1.5 秒 |
| 新事件收到后 UI 更新时间 | p95 <= 100 ms |
| 首个中文 draft | 沿用后端目标 p50 <= 2.5 秒 |
| stable caption | 沿用后端目标 p95 <= 6 秒 |
| 断线恢复 | <= 10 秒 |
| 无新事件的冻结告警 | 15 秒内出现 |
| 现场 45 分钟 crash-free session | >= 99.5% |

前两个指标属于 App；其余指标涉及端到端系统，不能只凭 App 或后端单侧健康来判定。

### 2.3 非目标

MVP 不做：

- 每个会众设备独立录音和翻译。
- App 内直播视频播放。
- AI 朗读中文字幕或同声传译音频。
- 人工编辑、发布、时间轴 review 和模型调参。
- 会后 PDF 生成或取代现有两份 canonical PDF 流程。
- 把 draft 字幕当成正式讲员原文或正式圣经译文。

## 3. 核心体验

### 3.1 信息架构

MVP 只有三个一级界面：

1. **正在听道**：当前中文字幕，是 App 默认入口。
2. **经文与原文**：从底部 sheet 展开，不打断主字幕。
3. **显示设置**：字号、中文/双语、深色模式、自动跟随。

不使用底部 Tab Bar。现场任务只有一个，Tab Bar 会增加不必要的导航和误触。

### 3.2 主界面线框

```text
┌──────────────────────────────┐
│  11:30 现场           ● 已连接 │
│  Misplaced Fear               │
├──────────────────────────────┤
│                              │
│     神的百姓正站在应许之      │
│     地的边缘，那片土地就      │
│     在他们眼前。              │
│                              │
│  正在翻译…                    │  <- 仅 draft 时低调显示
│                              │
├──────────────────────────────┤
│  民数记 13–14        查看经文  │
├──────────────────────────────┤
│      回看上一段    Aa          │
└──────────────────────────────┘
```

视觉原则：

- 使用 SwiftUI 系统语义色、Dynamic Type、SF Symbols 和标准 safe area。
- 当前 stable/final 中文字幕占据主要视觉面积。
- draft 可实时更新，但降低颜色对比，并用“正在翻译”标识；stable 到达后原位替换，避免页面跳动。
- 状态用文字加图形表达，不能只靠红/绿颜色。
- 默认隐藏长免责声明，只在首次使用和信息页展示简短提示。
- 活跃字幕页面可以提供“保持屏幕常亮”开关；离开现场或 session 结束后自动恢复系统行为。

### 3.3 状态设计

| 状态 | 用户看到什么 | App 行为 |
|---|---|---|
| 等待直播 | “字幕尚未开始”与预计场次 | 保持低频重试，不显示错误页 |
| 连接中 | 当前已有字幕或 skeleton | 连接 SSE，读取 snapshot |
| 实时 draft | 较弱颜色的滚动中文 | 可被 stable 原位替换 |
| stable/final | 高对比主字幕 | 写入当前 session 的本地轻量缓存 |
| 用户回看 | 历史列表与“回到现场”浮动按钮 | 继续接收事件，但不强制滚动 |
| 重连中 | 保留最后字幕，加“正在重连” | 指数退避并携带 cursor |
| 字幕停滞 | “字幕可能已暂停 · 15 秒前” | 不把旧字幕伪装成现场内容 |
| session 切换 | 短暂显示新场次标题 | 清理旧 draft，保留上一场历史分隔线 |
| 已结束 | “本场已结束” | 停止重连，允许只读回看 |

### 3.4 可访问性

- 支持所有 Dynamic Type 档位；最大字号下隐藏次要元数据，不能截断主字幕。
- VoiceOver 只在 stable/final 到达时播报，不逐字播报 draft delta。
- 支持“减少动态效果”；字幕替换使用淡入而不是位移动画。
- 支持竖屏和横屏。横屏仍以字幕为主，不增加 operator 控件。
- 深色模式使用接近纯黑的背景和低亮度状态色，减少现场干扰。
- 中英双语是可选项，中文永远保持主要层级。

## 4. 技术架构

### 4.1 推荐技术栈

- SwiftUI + `NavigationStack`。
- Swift Concurrency；UI state 由 `@MainActor` view model 管理。
- `URLSession.AsyncBytes` 逐行解析 SSE。
- 一个 `actor` 负责连接生命周期、去重、cursor 和退避。
- 一个纯函数 reducer 将网络事件折叠为稳定的字幕 view state。
- 只把当前 session 的少量 stable/final 字幕写入 Application Support；不保存音频或 token。

Apple 的 `URLSession` 支持以 `AsyncSequence` 方式在传输过程中读取 bytes，适合原生实现 SSE 客户端。参考 [URLSession](https://developer.apple.com/documentation/foundation/urlsession) 和 [bytes(from:delegate:)](https://developer.apple.com/documentation/foundation/urlsession/bytes(from:delegate:))。

### 4.2 组件关系

```mermaid
flowchart LR
    A[SwiftUI LiveCaptionScreen] --> B[LiveSessionViewModel]
    B --> C[SessionBootstrapClient]
    B --> D[SSEClient actor]
    D --> E[CaptionEventDecoder]
    E --> F[CaptionReducer]
    F --> B
    B --> G[SessionSnapshotCache]
    C --> H[Existing Sunday manifest API]
    D --> I[Existing realtime SSE API]
    I --> J[RealtimeSessionStore]
    J --> K[Realtime translation + stabilizer]
    L[Saturday reviewed artifacts] --> M[Sermon Context Pack Builder]
    M --> N[Versioned Context Pack]
    N --> O[Live Alignment and Retrieval]
    O --> K
```

建议的 Xcode 模块边界：

```text
ios/SermonLive/
  App/
  Features/LiveCaption/
  Features/Scripture/
  Features/Settings/
  Core/Networking/
  Core/Models/
  Core/Storage/
  DesignSystem/
  Tests/
```

先保持单一 app target 和内部模块目录，不在 POC 阶段引入复杂 package 拆分。

### 4.3 复用现有后端

当前仓库已经具备：

- `GET /api/sundays/current`：当前 Sunday/manifest 信息。
- `GET /api/realtime/sessions/current/events`：公开 SSE 字幕流。
- SSE event `id`、`sessionId`、`createdAt`。
- `session_started`、`caption_delta`、`caption_stable`、`caption_final`、英文 sidecar 事件。
- query string `cursor` 重连入口。

因此 iOS MVP 不需要直接调用 OpenAI。App 只消费本项目后端已经 sanitize 的字幕事件。

### 4.4 iOS 事件 reducer 规则

对每个 `(sessionId, segmentId)`：

1. 丢弃 `id <= lastAppliedEventId` 的重复事件。
2. `caption_delta` 只更新 draft buffer，不写历史。
3. `caption_stable` 替换同 segment 的 draft，并进入历史。
4. `caption_final` 覆盖 stable；如果 source 是 stable correction，保留修正标记供诊断但不干扰会众。
5. 新 `sessionId` 出现时先处理 `session_started`，再重置 event cursor；不能把不同 session 的相同数字 id 当成重复。
6. 未识别的新 event type 安全忽略并记录计数，不能让流解析失败。

字幕优先级：`final > stable > draft`。同一优先级只接受更大的 event id。

### 4.5 后端契约需要补齐的缺口

现有 SSE 足够做原型，但 production iOS App 前建议增加一个向后兼容的 contract v1：

1. `GET /api/realtime/sessions/current/snapshot`
   - 返回当前 `sessionId`、`streamEpoch`、最新 event id、最近 20 条 stable/final 字幕和 session 状态。
   - App 首屏先 snapshot，随后从 `cursor=latestEventId` 接 SSE，避免启动空白和竞态。
2. SSE 同时支持 `Last-Event-ID` header 和现有 `cursor` query。
3. 增加 `session_ended`、`heartbeat` 和 `stream_reset` 事件。
4. heartbeat 包含 server time、当前 session 和 last event id，但不含 secret 或音频信息。
5. 当 cursor 已超出 500-event 内存窗口或服务重启时返回显式 `stream_reset`，让 App 重新拉 snapshot，不能静默漏字幕。

`streamEpoch + sessionId + eventId` 才是完整 cursor。只保存 event id 会在 session 切换或服务重启后误判。

## 5. 用周六内容增强周日实时翻译

### 5.1 问题定义

实际情况不是“周六稿等于周日稿”，而是：

- 主要方向通常一致。
- 核心经文通常一致。
- 人名、书卷名、神学术语和关键例证有较高复用价值。
- 具体措辞、段落顺序、开场、临场发挥、故事细节和结束呼召可能不同。

因此周六版本既不是可直接播放的字幕，也不是无关资料。它更适合作为一个**可撤销、可追踪、按片段检索的先验**。

### 5.2 设计原则

1. **Live source of truth**：任何最终字幕都必须能由周日实时英文支持。
2. **Prior may suggest, never assert**：周六内容可以建议译法，不能补写现场未出现的事实。
3. **片段级匹配**：不能因为整篇主题相同就宣布“版本一致”；每个 rolling window 独立判断，同时利用段落顺序。
4. **匹配随时可撤销**：讲员一旦偏离周六结构，当前片段立即退回无先验翻译。
5. **快慢通道分离**：周六检索不能阻塞第一条 draft；它主要提高 stable caption 的速度与质量。
6. **一个会众输出**：匹配、检索和校正在后端完成，所有 App 收到同一份字幕。
7. **保留来源证据**：每次先验辅助都记录 pack、候选片段和分数，便于回放和审计。

### 5.3 周六 Sermon Context Pack

周六完成视频提取、转写和翻译后，增加一个只读构建步骤，生成版本化 Context Pack：

```json
{
  "contextPackId": "ctx_2026-08-30_sha256prefix",
  "sourceVersion": "saturday-video",
  "sourceSha256": "...",
  "intendedSunday": "2026-08-30",
  "status": "reviewed",
  "sermon": {
    "title": "...",
    "speaker": "...",
    "themeSummaryZh": "...",
    "primaryScriptures": ["Romans 8:1-17"]
  },
  "terms": [
    {
      "en": "adoption",
      "preferredZh": "得儿子的名分",
      "aliases": ["sonship"],
      "evidenceSegmentIds": ["sat_0042"]
    }
  ],
  "anchors": [
    {
      "id": "anchor_03",
      "order": 3,
      "summaryEn": "Life in the Spirit rather than condemnation",
      "scriptureRefs": ["Romans 8:1-4"],
      "keywords": ["condemnation", "Spirit", "flesh"],
      "segmentIds": ["sat_0071", "sat_0072"]
    }
  ],
  "segments": [
    {
      "id": "sat_0071",
      "en": "...",
      "approvedZh": "...",
      "anchorId": "anchor_03"
    }
  ]
}
```

Pack 中可以包含：

- 已人工确认的主经文和相关经文。
- 人名、地名、书卷名、神学术语及首选中文。
- 主题大纲和有序语义锚点。
- 可检索的短英文片段及已审校中文。
- 讲员、系列名和教会常用表达。
- 原始 artifact hash、生成版本、review 状态和时间。

Pack 不应包含：

- “下一句一定是什么”的预测指令。
- 没有英文证据即可输出的预制中文字幕。
- 未经允许的整本圣经译文或其他受限内容。
- API key、client secret、管理 token 或原始音频。

### 5.4 周日双通道流水线

```mermaid
flowchart TD
    A[Sunday live audio] --> B[Fast realtime translation]
    B --> C[Draft Chinese under 2.5s target]
    A --> D[English sidecar transcript]
    D --> E[Rolling live window]
    P[Saturday Context Pack] --> F[Sequence-aware retrieval]
    E --> F
    F --> G{Segment-level match confidence}
    G -->|high| H[Terms + scripture + matched candidate]
    G -->|medium| I[Terms + scripture only]
    G -->|low or diverged| J[No Saturday prior]
    C --> K[Stable correction]
    E --> K
    H --> K
    I --> K
    J --> K
    K --> L[Final Chinese from live English]
    L --> M[Public SSE to every App]
```

#### 快通道

- 音频持续进入 `gpt-realtime-translate`，尽快输出 draft。
- 不等待向量检索、Context Pack 或较慢的 stable model。
- 如果 Context Pack 不可用，快通道仍然完整工作。

#### 先验通道

- 英文 sidecar transcript 形成最近 8–15 秒 rolling window。
- 用英文语义、经文命中、关键词和上一 anchor 位置检索 Context Pack。
- 检索必须考虑顺序，优先当前 anchor 附近的候选，而不是每句都在整篇中自由跳转。
- 输出 `high / medium / low / diverged`，而不是简单 yes/no。

#### 稳定修正通道

stable correction 的输入包括：

- 周日 live English window，唯一事实来源。
- realtime draft Chinese。
- 当前术语表和经文 canonical wording。
- 最多 2–3 个周六候选片段及其 match score。
- 上一段已确认 anchor，帮助保持顺序。

输出使用结构化 schema：

```json
{
  "segmentId": "live_0123",
  "zh": "如今，那些在基督耶稣里的人就不被定罪了。",
  "priorAssist": "matched_segment",
  "contextPackId": "ctx_2026-08-30_sha256prefix",
  "matchedPriorSegmentIds": ["sat_0071"],
  "matchConfidence": 0.91,
  "liveEvidenceCoverage": 1.0,
  "divergenceReason": null
}
```

修正提示的硬规则：

> 只翻译 live English 中实际出现的内容。周六候选只用于术语、经文和表达选择。若候选与 live English 冲突、增加细节或顺序不符，忽略候选。不得为了贴合周六版本而补齐现场未说出的句子。

### 5.5 匹配与降级策略

建议使用三层门禁，而不是单一 embedding 分数：

| 门禁 | 信号 | 失败时行为 |
|---|---|---|
| 主题/经文门禁 | 主经文、书卷、主题关键词 | 仅保留通用术语表 |
| 片段语义门禁 | live English 与周六候选语义相似度 | 不使用 matched segment |
| 忠实度门禁 | stable 输出的每个实质信息能否回指 live English | 拒绝修正，保留无先验版本 |

还要加入顺序约束：

- 已匹配到 `anchor_03` 后，优先检索 `anchor_02–05`。
- 只有强证据才允许大幅向前或向后跳转。
- 连续 2–3 个窗口低置信时进入 `diverged`。
- `diverged` 后仍使用经文/术语表，但停止使用周六具体句子。
- 后续重新出现明确经文或高置信语义锚点时可以恢复匹配。

### 5.6 哪些内容可以安全复用

| 周六资产 | 周日用法 | 风险等级 |
|---|---|---|
| 主经文与书卷名 | 预加载、ASR/翻译术语提示、即时经文卡 | 低 |
| 人名与神学术语 | 术语表和拼写/译名纠正 | 低 |
| 主题与大纲 | 缩小检索范围、预测可能 anchor | 中 |
| 已审校中文短片段 | 仅在 live English 高置信匹配后作为译法候选 | 中高 |
| 完整周六中文字幕 | 只做检索库和 A/B 评估，不直接播放 | 高 |
| 周六音频时间轴 | 不映射到周日现场时间轴 | 禁止直接复用 |

### 5.7 “加速”的准确含义

Context Pack 不一定让 realtime 模型的网络响应更快；错误地加入大段上下文反而可能增加处理成本。这里追求的是：

- 经文、人名、神学术语更早正确。
- stable correction 少一次或少几次来回修改。
- Scripture card 可以在现场提到时立即显示。
- operator 更早知道当前证道是否沿用周六结构。
- 低置信或偏离时更快退回安全基线。

因此核心指标应是 **time-to-correct-stable-caption**，而不只是 first draft latency。

### 5.8 App 与 operator UI

会众 App 不显示复杂的 Context Pack 分数。会众只看到：

- 当前中文字幕。
- 必要时的“正在校正”状态。
- 已确认经文卡。
- 连接与字幕新鲜度。

operator 视图增加：

- `Context Pack 已加载 / 未加载 / 未审核`。
- 当前匹配模式：`matched / terms-only / diverged / unavailable`。
- 当前 anchor、match confidence、prior-assisted coverage。
- 最近一次因 live evidence 不足而拒绝的修正数量。
- “关闭具体片段复用，只保留经文和术语”的一键降级。

App 本地可以预下载经文卡和术语表以加快展示，但断网时绝不能把周六字幕继续滚动并标记为“现场”。

### 5.9 OpenAI API 落点

截至本设计日期，官方 OpenAI Docs 显示 `gpt-realtime-translate` 通过专用 Realtime Translation endpoint 持续接收音频并输出翻译 audio/transcript deltas；创建 translation session 的公开配置主要是 model、input transcription/noise reduction 和 output language。不要假设可以把整篇周六稿直接注入这个 translation session。参考 [GPT-Realtime-Translate](https://developers.openai.com/api/docs/models/gpt-realtime-translate) 和 [Create translation client secret](https://developers.openai.com/api/reference/resources/realtime/subresources/translations/subresources/client_secrets/methods/create)。

官方模型说明同时表明 `gpt-transcribe` 支持 unstructured context、keyword hints 和 language hints，可用于提高领域术语、多语言和 code-switching 转写质量。具体能否通过当前 Realtime Translation 内嵌 transcription 配置传递这些 hints，必须用当前 API schema 和真实请求验证；在验证前，设计上把它视为独立 English sidecar 能力。参考 [GPT-Transcribe](https://developers.openai.com/api/docs/models/gpt-transcribe)。

当前仓库已有 delayed stable correction 层，最小实现路径是先扩展这一层：

1. 为 stabilizer 加载 Context Pack。
2. 在每个 English window 上做检索和匹配。
3. 把候选片段作为受限 hint 送入 stable correction。
4. 记录 prior provenance 和拒绝原因。
5. 保持现有 realtime draft 完全不依赖 Context Pack。

另外，当前 `backend/realtime.py` 使用 general realtime client-secret payload 和 `instructions`；production 实施前应把它与当前专用 `/v1/realtime/translations/client_secrets` schema 做一次兼容性 preflight，不能只依据历史 smoke 结果推断当前接口仍一致。

### 5.10 数据与 API 建议

建议新增：

| Method | Path | 用途 |
|---|---|---|
| `POST` | `/api/admin/sundays/{date}/context-pack:build` | 从已验证周六 artifacts 构建 pack |
| `GET` | `/api/admin/sundays/{date}/context-pack` | 查看 hash、review 和覆盖状态 |
| `POST` | `/api/admin/sundays/{date}/context-pack:approve` | 人工确认经文、术语和使用范围 |
| `POST` | `/api/admin/realtime/sessions` | 增加可选 `contextPackId` |
| `GET` | `/api/admin/realtime/sessions/{id}/context-status` | 查看匹配、偏离和辅助覆盖 |

Context Pack 必须绑定：

- intended Sunday。
- 周六 source URL 与 SHA-256。
- transcript/translation artifact hashes。
- builder 版本。
- reviewer、review time 和批准范围。

### 5.11 A/B 评估与硬门禁

使用相同的周日现场录音回放三条路线：

1. baseline：纯 realtime + 现有 stabilizer。
2. glossary：只使用经文和术语。
3. contextual retrieval：术语 + 有序片段检索。

比较：

- 经文、人名、神学术语准确率。
- time-to-correct-stable-caption。
- stable caption revision 次数。
- 周六先验实际覆盖率。
- 讲员偏离周六版本后的降级时间。
- prior-induced addition：live English 没说、但字幕因周六内容而加入的信息。

硬门禁：

- `prior-induced addition` 必须为 0。
- contextual retrieval 不能恶化 first draft latency。
- 低置信和 diverged 窗口必须与 baseline 等价。
- 所有 prior-assisted final caption 必须保留 live English evidence 和 pack provenance。

## 6. 音频采集与 OpenAI 边界

### 6.1 为什么不进入会众 MVP

每台会众 iPhone 独立采集会带来：

- 距离讲员不同造成的声学质量差异。
- 扬声器回声、会众谈话和多设备结果不一致。
- 每台设备单独计费和限流。
- 麦克风隐私说明、录音授权和更复杂的 App Store 审核材料。
- 来电、锁屏、耳机切换和后台挂起造成的现场中断。

因此应保留一条受控、可观察的 operator 音频源，然后向所有会众广播同一份字幕。

### 6.2 operator capture 的后续方案

如果后续需要 iPhone 作为应急麦克风：

- 入口必须需要 operator 身份与 feature flag。
- OpenAI 标准 API key 只存在服务端，绝不能嵌入 App。官方文档明确要求 API key 不暴露在 browser 或 app 客户端；Realtime 支持 WebRTC/WebSocket/SIP。参考 [OpenAI API authentication](https://developers.openai.com/api/reference/overview#authentication) 和 [Realtime WebRTC call](https://developers.openai.com/api/reference/typescript/resources/realtime/subresources/calls/methods/create)。
- 后端按 session 签发短期 client secret；App 不持久化该 secret。
- 原生 WebRTC 需要经过评估的 iOS WebRTC dependency，不为了 POC 自行实现传输协议。
- 麦克风权限只在用户明确进入“应急采集”并点击开始时请求。
- 处理 audio interruption、route change、前后台切换和显式停止；界面持续显示录音指示。

Apple 要求录音必须获得用户许可，并由音频 session 表达录音意图；较新的 API 可通过 `AVAudioApplication` 管理录音许可。参考 [AVAudioApplication](https://developer.apple.com/documentation/avfaudio/avaudioapplication)、[AVAudioSession](https://developer.apple.com/documentation/avfaudio/avaudiosession) 和 [setActive(_:options:)](https://developer.apple.com/documentation/avfaudio/avaudiosession/setactive(_:options:))。

## 7. 安全、隐私与数据

- 会众 MVP 不申请麦克风权限。
- 不在 App bundle、Keychain、日志或 crash report 中放 OpenAI API key。
- 公共字幕 API 只返回 sanitize 后的字幕和 session 状态。
- 本地只缓存当前 session 的 stable/final 文本、cursor 和显示设置，并提供“清除本地字幕”入口。
- telemetry 使用随机匿名 install id；不采集姓名、精确位置、通讯录、麦克风或广告标识符。
- 日志中只记录 event type、延迟、cursor、HTTP 状态和匿名 session id；正文默认不进入远程诊断日志。
- AI 字幕提示保持简洁可见：“AI 辅助字幕，可能有延迟或错误；以讲员原文和正式圣经译本为准。”

## 8. 失败与降级

| 故障 | App 降级行为 |
|---|---|
| 没有 active session | 等待页，不循环弹错误 |
| SSE 断开 | 保留最后 stable 字幕，标注时间并自动重连 |
| cursor 失效 | 拉 snapshot，显示一次轻量“已恢复到现场” |
| 只有 draft | 显示 draft，但保持“正在翻译”状态 |
| stabilizer 失败 | 继续显示 draft；不能把后端健康误报为 stable 可用 |
| manifest 可用但 realtime 不可用 | 可选显示已发布的 post-live 字幕，并明确标注“非实时” |
| App 进入后台 | 保存 cursor；回到前台立即 snapshot + reconnect |
| session 已结束 | 停止高频重试，保留只读历史 |

## 9. 验证计划

### 9.1 自动化

- SSE parser：多行 data、comment、空行、UTF-8、分片边界和未知 event。
- reducer：draft/stable/final 覆盖、重复、乱序、跨 session 和 correction。
- reconnect：网络中断、HTTP 5xx、cursor reset 和前后台切换。
- snapshot/SSE race：snapshot 后到达的第一条事件不丢失也不重复。
- SwiftUI snapshot：小屏、横屏、深色模式、超大 Dynamic Type。
- VoiceOver：只播报 stable/final。
- Context Pack：hash 绑定、未审核拒绝、跨 Sunday 拒绝和 schema 兼容。
- retrieval：有序 anchor、低置信降级、重新匹配和 prior provenance。
- faithfulness gate：周六存在但周日没说的内容绝不进入 final caption。

### 9.2 现场验收

至少在真实 iPhone 上完成一次完整证道时长演练，并分别验证：

- 教会 Wi-Fi、蜂窝网络和两者切换。
- 锁屏/解锁、切后台 1 分钟、低电量模式。
- 10 秒网络中断后的恢复。
- draft 到 stable correction 的原位替换。
- 周六/周日版本一致片段的术语质量提升，以及偏离片段的自动降级。
- 用户回看时新字幕继续进入，点击“回到现场”正确定位。
- 后端进程重启或 session 切换后不会显示假实时旧字幕。
- Dynamic Type 最大档和 VoiceOver。

Cloud Run health、SSE smoke 和 simulator 测试都不能替代这次物理设备现场验收。

## 10. 分阶段实施

### Phase 0：契约与可点击原型

- 固化 mobile contract v1 和 fixture JSONL。
- 固化 Context Pack schema，并从一组已验证周六 artifacts 生成 fixture。
- 使用真实的周六/周日成对录音完成 baseline、glossary、contextual retrieval 三路回放。
- 用 SwiftUI 做等待、实时、重连、回看四种状态的本地 fixture 原型。
- 在 iPhone 真机确认字号、低亮度和现场可读性。

### Phase 1：只读 MVP

- 接入 Sunday bootstrap、snapshot 和 SSE。
- 后端接入 approved Context Pack、sequence-aware retrieval 和有 provenance 的 stable correction。
- 完成 reducer、缓存、重连、经文 sheet、显示设置与匿名 telemetry。
- TestFlight 小范围现场试用。

### Phase 2：可靠性与发布

- 加入 stream epoch、server heartbeat 和真实 production observability。
- 完成隐私说明、App Store 元数据、支持页和崩溃诊断边界。
- 通过一场完整 rehearsal 和一场真实 service 后再扩大使用。

### Phase 3：operator 应急采集

- 独立鉴权入口、短期 client secret、原生 WebRTC 音频链路。
- 音频中断、路由切换、后台行为和成本告警。
- 仍由后端汇总并广播唯一字幕流。

## 11. 实施前需要确认的决策

这些问题不阻碍设计分支，但会影响开始写 App：

1. 部署最低版本暂定 **iOS 17+**；实施前用实际会众设备范围验证。
2. App 是公开 App Store、TestFlight 邀请，还是教会内部分发。
3. 是否使用现有 Cloud Run 公网域名作为唯一 production API origin。
4. 会众是否需要繁体中文；MVP 当前只定义简体中文。
5. Scripture sheet 是否沿用当前 `cmn-cu89s` 内容和归属展示方式。
6. operator capture 是否确实需要进入同一 App，还是保持独立工具更安全。
7. 哪一组周六/周日视频可以作为首个 paired replay golden set。
8. Context Pack 中哪些字段必须人工确认：建议至少确认主经文、人名和首选术语。

## 12. 建议的下一步

先不要直接写完整 App。最小、可验证的下一步是：

1. 选定一组真实周六/周日成对材料，建立 live-English 对齐的 golden set。
2. 定义 Context Pack schema，先只包含经文、术语、anchors 和短片段，不直接修改 realtime draft。
3. 扩展现有 stabilizer，完成 baseline、glossary、contextual retrieval 三路离线回放。
4. 确认 `prior-induced addition = 0` 且 time-to-correct-stable-caption 有改善后，再接入周日 realtime session。
5. 同时补齐 snapshot、heartbeat、stream epoch 和 cursor reset contract。
6. 新建 SwiftUI fixture prototype，用 enriched SSE 回放 45 分钟并做 iPhone 真机断网测试。
7. 通过后再接 production SSE，并把 operator capture 留到最后阶段。

相关现有文档：

- [系统设计](./system-design.zh.md)
- [周日 live test runbook](./sunday-live-test-runbook.zh.md)
- [Admin 工作流](./admin-workflow.zh.md)
- [观测与日志](./observability.zh.md)
