# 多语言 Layer 4 发布与 App 改进 Backlog

状态：**接口与 iOS 路由 POC 开发中**。本文覆盖 Layer 4「多语言发布与播放」以及 Web/iOS 客户端的语言选择体验。v2 catalog／release receipt schema、fail-closed catalog builder，以及 iOS 语言发布页选择已开始实现；这仍不表示韩语音频、多语言正式发布或设备／现场验收已经完成。

## 当前实现切片（2026-09-21）

- 新增 `sermon-multilingual-catalog-v2` 和 `sermon-target-language-release-receipt-v1` schema。
- `scripts/build_multilingual_catalog.py` 只聚合精确 hash 匹配、人工翻译批准、HTTP 已验证且无 unresolved issue 的 Release Package；跨 locale source identity、同 locale 音频包绑定和完整听审任一不符即停止。
- iOS Core 解码并验证 v2 catalog 和 immutable Release Package；Infrastructure 下载时复算 package hash，并把 package/page URL 限定到配置的同一 HTTPS origin。
- Debug build 指向独立 Firebase Dev origin；Release build 继续指向 Production origin。运行时测试仍可显式注入隔离 origin。
- 标题附近的“证道语言”按钮打开语言 Sheet；只显示 catalog 中 `human_reviewed` 文字版本，并显示文字、字幕、音频和下载能力。选择后先取得并验证该 locale 的 Release Package，再打开其 `page` asset。
- 本切片不把其他语言页面伪装成原生音轨切换：返回 App 后原生播放器仍明确保留现有已验证中文轨道。原生多语言内容／音频切换、跨轨 source-unit 定位和 PlaybackHistory v2 仍在后续 backlog。

### 交互决策

1. **入口靠近内容，而不是藏在设置里**：用户先选择“要读哪种语言”；“更多 → 界面语言”只控制按钮和提示。
2. **能力先于语言名**：每行同时显示 `文字／字幕／音频／可下载`，避免看到“한국어”就误以为韩语配音已经存在。
3. **验证后再导航**：点击 locale 后先验证 catalog 引用、package SHA-256、page/locale/status 和同源 URL；失败时停留在当前内容，不改变播放器。
4. **迁移期明确边界**：已发布语言页面在对应页面打开；原生播放器不静默借用中文音频，也不把中文秒数直接应用到另一语言轨道。
5. **选择可恢复但不绑界面语言**：保存全局 content 偏好和 per-page 选择；locale 被撤回时回到该页 catalog 默认值，并显示原因。界面偏好继续独立保存。

正式上游仍是：

- Layer 2：`Target-Language Candidate`；
- Layer 3：可选的 `Target-Language Audio Package`；
- Layer 4：每个 `pageId + targetLocale` 一个 `Target-Language Release Package`，再聚合为 App 可消费的多语言 catalog。

本文不修改 Layer 1–3 的文本、音频或审核结论。发布层只能验证、聚合和暴露已有资产，不能补翻译、重新合成、借用另一语言的审核状态或把客户端可播放冒充内容验收。

## 1. 产品决定：三种语言状态必须解耦

App 同时维护三个不同概念：

| 状态 | 含义 | 谁控制 | 是否改变播放 |
| --- | --- | --- | --- |
| `interfaceLocale` | 按钮、菜单、错误、权限和无障碍提示使用的语言 | App 设置／系统语言 | 否 |
| `contentLocale` | 标题、摘要、大纲、全文和当前字幕使用的目标语言 | 用户的“证道语言”选择 | 可能请求匹配音轨，但不静默 fallback |
| `audioLocale` | 实际正在播放的音轨语言；没有音轨时为 `null` | 默认跟随内容语言，也可由用户显式另选 | 是 |

核心规则：

- 切换 App 界面语言只重绘界面文案，不换证道内容、不换音轨、不定位、不清空下载或反馈。
- 选择目标语言时，先切换 `contentLocale`，并优先选择相同 locale 的已发布音轨。
- 如果目标语言没有合格音轨，默认显示“仅文字”，`audioLocale=null`；不得自动播放中文并让用户误以为是韩语。
- 用户可以显式选择另一语言音轨，例如“韩语文字 + 中文音频”；主界面和系统媒体必须持续显示这个组合。
- 一个目标语言发布失败或撤回，不影响同一页面的其他语言。
- `contentLocale` 与 `audioLocale` 不同的同步高亮只能通过共同 `sourceUnitIds` 映射；不能按两个音轨的秒数直接套用。

## 2. App 语言选择体验

### 2.1 主界面的“证道语言”入口

在证道标题附近增加一个清晰的语言按钮，例如：

```text
证道语言  한국어  ·  仅文字
```

点击后打开 `TargetLanguageSheet`。每个 locale 行显示真实能力，不只显示语言名称：

```text
简体中文        文字 · 音频 · 可下载
한국어          文字 · 音频待提供
English         原文 · 无配音
```

选择规则：

1. 只把有可发布文字的 locale 作为可选目标语言。
2. `draft`、`machine_reviewed` 或已撤回内容不进入正式 App 的可选列表；预览构建可单独显示并带“预览”标记。
3. 行内分别标记文字、字幕、音频、下载和现场对齐能力。
4. 当前选择用 checkmark 和 VoiceOver selected trait 表示，不能只靠颜色。
5. 语言名称使用该语言自称，并可用界面语言补充说明，例如 `한국어（韩语）`。

默认选择顺序：

1. 当前页面上次明确选择且仍可用的 `contentLocale`；
2. 用户全局偏好的目标语言；
3. catalog 的 `defaultTargetLocale`；
4. 第一个 `human_reviewed` 文字版本。

不得根据 `interfaceLocale` 自动覆盖用户已选内容语言。首次使用时可以用界面语言帮助选择，但保存后以目标语言偏好为准。

### 2.2 音频语言与文字版

目标语言选择完成后：

- 存在同 locale、`human_reviewed` 的音频：默认选择该音轨。
- 只有 candidate 音频：正式 App 不自动选择；预览 App 明确显示“待听审”。
- 没有同 locale 音频：进入文字版，不显示可播放假状态。
- 有其他语言音轨：在“音频语言”二级选择器中提供，必须由用户主动选择。

跨语言组合示例：

```text
正文：한국어
音频：简体中文
字幕按共同英文锚点映射；并非韩语配音
```

如果不同语言之间没有完整 source-unit 映射，允许阅读全文，但关闭同步高亮与跨语言自动定位，并解释原因。

### 2.3 播放中的语言切换

切换目标语言时按以下顺序处理：

1. 冻结当前 `pageId + contentLocale + audioLocale + track hash + position`。
2. 立即更新静态内容，但在新音轨准备完成前不销毁旧下载或历史。
3. 若音轨也改变，先暂停旧音轨。
4. 使用当前 cue 的 `sourceUnitIds` 在新音轨中寻找对应位置。
5. 映射唯一且新音轨完整可用时，定位到新 cue；只有用户原本正在播放且加载成功，才恢复播放意图。
6. 映射缺失或歧义时保持暂停，提供“从对应段落开始”或“从头开始”，不复制旧秒数。
7. 迟到的下载、播放或定位回调必须绑定完整选择 token，不能覆盖更新后的语言选择。

仅切换 `contentLocale`、保留现有跨语言音轨时，不重载播放器；字幕高亮改用 source-unit 映射。

### 2.4 App 界面语言

界面语言设置保留在“更多 → 界面语言”，支持：

- 跟随系统；
- 简体中文；
- English；
- 한국어（完整核心界面翻译通过后开放）；
- Español（以后有完整界面翻译时开放）。

实现规则：

- App 支持哪些界面语言由 App build/String Catalog 决定，不由每周 catalog 决定。
- `AppLanguage` 使用规范 BCP 47；新的内容合同用 `zh-Hans`，legacy `zh-CN` 只留在兼容 adapter。
- 界面切换即时更新导航、Sheet、错误、下载、权限、Live Activity、Now Playing 辅助文案和 VoiceOver label。
- 证道正文、讲员名和经文按 `contentLocale` 设置 language identifier；音轨/字幕按实际 `audioLocale` 或 cue locale 设置。
- App 名称和系统权限说明若受 iOS bundle 本地化限制，记录为“重启/系统语言生效”，不伪装为 App 内即时切换。

### 2.5 用户可见状态

主界面至少区分：

| 状态 | 用户文案方向 | 行为 |
| --- | --- | --- |
| 文字 + 同语言音频 | `한국어 · 音频可用` | 正常播放、字幕、下载 |
| 仅文字 | `한국어 · 仅文字` | 无播放按钮或明确禁用原因 |
| 跨语言音频 | `韩语文字 · 中文音频` | 显著标注；按 source-unit 映射 |
| 音频待审 | `韩语音频待审核` | 正式 App 不播放；预览可受控展示 |
| 离线缺少所选语言 | `已缓存中文，韩语需要联网` | 不静默回退；提供明确选择 |
| release 撤回 | `此语言版本已撤回` | 停止新下载；保留其他语言 |

## 3. Layer 4 接口

### 3.1 Target-Language Release Package

现有正式接口：`sermon-target-language-release-package-v1`。一个包只发布一个 `pageId + targetLocale`。

发布器除 JSON Schema 外必须做语义验证：

- `contentLocale == targetLocale`；
- `targetLanguageCandidateJsonSha256` 对应同一 English Source Package 和页面；
- 有音频时，Audio Package 必须绑定同一 candidate 且 `audioLocale == targetLocale`；
- 没有音频时，`audioLocale=null`、`audioStatus=unavailable`，不能放另一语言资产；
- `contentStatus=human_reviewed` 才能进入正式 catalog；
- `audioStatus=human_reviewed` 才能在正式 App 标记音频可用；
- assets 路径、hash、角色、下载文件名和页面 ID 必须唯一且安全。

v1 中的 `interfaceLocale` 不应用来驱动 App 界面偏好。为保持冻结 schema，v1 producer 暂时写为 `targetLocale`；App adapter 忽略它。未来 v2 应删除该字段，因为 App 界面语言属于客户端设置，而不是某个内容发布包的属性。

### 3.2 发布验证收据

新增建议接口：`sermon-target-language-release-receipt-v1`。它引用 immutable Release Package hash，独立记录发布后的事实：

```json
{
  "schemaVersion": "sermon-target-language-release-receipt-v1",
  "releasePackageJsonSha256": "<sha256>",
  "pageId": "<page>",
  "targetLocale": "ko",
  "publishedAt": "<timestamp>",
  "catalogJsonSha256": "<sha256>",
  "httpVerification": {
    "status": "pass",
    "assets": []
  },
  "deviceAcceptance": {"status": "not_run", "evidenceSha256": null},
  "venueAcceptance": {"status": "not_run", "evidenceSha256": null}
}
```

原因：HTTP 验证发生在上传之后，不应为了把结果写回包内而改变已发布 package hash。HTTP、设备和现场三个状态保持独立。

### 3.3 Multilingual Catalog v2

新增建议接口：`sermon-multilingual-catalog-v2`。Catalog 只汇总已发布 package，不复制上游审核逻辑：

```json
{
  "schemaVersion": "sermon-multilingual-catalog-v2",
  "generatedAt": "<timestamp>",
  "defaultPageId": "<page>",
  "pages": [
    {
      "id": "<page>",
      "date": "2026-09-20",
      "sourceLocale": "en",
      "sourceIdentitySha256": "<sha256>",
      "defaultTargetLocale": "zh-Hans",
      "targets": {
        "zh-Hans": {
          "releasePackageUrl": "/releases/<page>/zh-Hans.json",
          "releasePackageJsonSha256": "<sha256>",
          "contentStatus": "human_reviewed",
          "audioStatus": "human_reviewed",
          "capabilities": ["text", "captions", "audio", "download"]
        },
        "ko": {
          "releasePackageUrl": "/releases/<page>/ko.json",
          "releasePackageJsonSha256": "<sha256>",
          "contentStatus": "human_reviewed",
          "audioStatus": "unavailable",
          "capabilities": ["text"]
        }
      }
    }
  ]
}
```

Catalog 语义约束：

- `targets` key 必须等于对应 Release Package 的 `targetLocale`。
- `defaultTargetLocale` 必须存在且文字已人工审核。
- capability 必须由 assets 和状态推导，不能手填出不存在的能力。
- 同一 page 的各语言必须绑定同一个 source identity；不一致时拒绝聚合。
- 撤回一个 locale 时只移除该 target；若它是默认语言，必须在同一次原子更新中选择新的默认语言。
- catalog 指向 immutable package；媒体、字幕和下载继续内容寻址。

### 3.4 App 本地偏好与播放身份

客户端保存两个独立偏好：

```json
{
  "schemaVersion": "tongxing-language-preferences-v2",
  "interfacePreference": "system",
  "preferredContentLocale": "ko",
  "pageSelections": {
    "<pageId>": {
      "contentLocale": "ko",
      "audioLocale": "zh-Hans"
    }
  }
}
```

播放、下载和恢复身份扩展为：

```text
pageId + sourceId + contentLocale + audioLocale + trackId + audioSha256
```

Release Package hash 进入缓存引用；同一音频 hash 可以共享 bytes，但不同 locale/track 保留独立引用和显示身份。

## 4. Adapter 设计

### 4.1 Legacy Weekly Catalog v1 → Multilingual Catalog v2

用途：迁移期间保持现有中文 App/Web 可用。

规则：

- 每个 legacy week 只映射为 `targets["zh-Hans"]`。
- 没有字段证据时不创造英文、韩语或西班牙语 target。
- 保留原 page/source/track/cue/hash、审核声明和同步状态。
- `audioStatus` 根据已有明确状态转换；未知状态降级为 candidate/unavailable，不升级为 reviewed。
- legacy interface locale `zh-CN` 只转换为内容 locale `zh-Hans`；不改变用户 App 界面语言。
- adapter 输出迁移收据，记录输入 catalog hash、实现 hash、映射数量、warnings 和输出 hash。

### 4.2 Release Package Aggregator

用途：将同一 page 的多个 Release Package 合并进 catalog。

规则：

- 合并键为 `pageId + targetLocale`，不是日期或标题。
- 新包只能替换同 locale 的旧包；不能覆盖其他语言。
- 比较 source identity、candidate/audio package hash、状态和 asset allowlist。
- 发布过程持有 page/catalog lease 或 CAS；并发更新不能丢失另一 locale。
- catalog 最后上传；资产或 package 上传失败时继续保留旧 catalog。

### 4.3 Web Catalog Adapter

- 将 v2 target 转为现有 week view，但把 `interfaceLocale`、`contentLocale`、`audioLocale` 分开保存。
- 旧 URL `?week=<pageId>` 保持有效；可增加 `&lang=ko`，缺失/无效 locale 使用明确默认并更新可复制 URL。
- 浏览器分别保存界面偏好和内容语言偏好；不能复用现有单一 `sermon-audio-locale` 表示三种状态。
- legacy catalog 继续通过 v1 adapter 工作；旧浏览器不理解 v2 时保留静态中文发布或明确升级策略。

### 4.4 iOS Domain Adapter

- Core 新增 `MultilingualCatalog`、`PageTarget`、`ReleasePackage` 和 `LanguageCapabilities`，保持 UI 无关。
- `SermonWeek`/`SermonTrack` legacy 模型由 adapter 生成，不直接把多语言字段塞进旧类型后靠 optional 猜测。
- `AppModel` 分别管理 selected page、content target 和 audio target；`PlaybackController` 仍是唯一播放器。
- `OfflineLibrary` 引用加入 page/locale/track/release hash；共享 blob 保留现有按 SHA-256 去重。
- `PlaybackHistory` v2 加入 locale；legacy history 只恢复到 legacy 中文 target，不跨语言套用秒数。
- 指纹/现场对齐能力绑定实际 audio track；切换语言时必须重新核对 alignment 与 track hash。

## 5. Layer 4 发布流程

```text
验证 Layer 2 candidate
  + 可选验证同 locale Layer 3 audio package
  → 生成 locale release package candidate
  → 构建内容/字幕/音频/下载资产 allowlist
  → 上传 immutable assets
  → 上传 immutable release package
  → CAS 合并 multilingual catalog
  → 最后发布 catalog
  → 在线核对 package、hash、HTTP、Range、客户端解析
  → 写 release receipt
  → 独立执行设备与现场验收
```

发布规则：

- 资产先于 catalog；catalog 是唯一可变入口，必须最后更新。
- 每次发布记录旧 catalog hash 和新 catalog hash，可按单 locale 回滚。
- 回滚只切换 catalog 指针；不删除 immutable 历史资产。
- HTTP 验证至少覆盖状态码、完整 hash、Content-Type、音频 Range、cache header 和同源路径。
- “部署成功”不等于 HTTP 内容正确；HTTP 通过不等于设备播放或现场听感通过。
- `withdrawn` target 从新客户端选择中移除；已离线内容的继续使用策略必须由撤回原因决定并显式记录。

## 6. Layer 4 与 App 改进 Backlog

### L4-P0：发布接口与原子聚合

#### L4-001 Release Package 语义 validator

- [x] 在 JSON Schema 外验证 page/source/locale/candidate/audio 的跨包 hash。
- [x] 强制 content locale 与 target locale 相同；audio 只能同 locale 或不存在。
- [x] capability 从真实资产和状态推导。
- [x] 正式 catalog builder 拒绝 draft/machine-only 文字和未人工听审音频。

验收：错 locale、错 candidate、借用中文音频、伪造 reviewed 状态和 asset hash 漂移均 fail closed。

#### L4-002 Release receipt schema 与 writer

- [x] 定义 `sermon-target-language-release-receipt-v1`。
- [ ] 绑定 immutable Release Package 与 catalog hash。
- [ ] HTTP、设备、现场分别记录；后两者默认 `not_run`。
- [ ] 重跑 HTTP 验证生成新 receipt，不改写旧 package。

#### L4-003 Multilingual Catalog v2 schema 与 validator

- [x] 定义 page/targets/defaultTargetLocale/capabilities/release package 引用。
- [x] 校验同 page 各 locale 的 source identity 一致。
- [x] 禁止 default 指向撤回、draft 或缺失 target。
- [x] 建立大小、路径、重复 ID 和 locale 上限。

#### L4-004 Release Package Aggregator

- [ ] 按 `pageId + targetLocale` 合并。
- [ ] 使用 CAS/lease 防止并发语言发布互相覆盖。
- [ ] 保留其他 locale、历史周次和未知兼容字段。
- [ ] 输出 build report、旧/新 catalog hash 和 locale diff。

#### L4-005 Legacy v1 adapter

- [ ] 把现有 catalog 映射为单一 `zh-Hans` target。
- [ ] 保存输入/实现/输出 hash 和降级 warnings。
- [ ] 用当前已发布完整目录做 golden round trip。
- [ ] 未解释差异前不切换线上 catalog。

#### L4-006 原子发布、核验与单语言回滚

- [ ] immutable 资产/package 先上传，catalog 最后上传。
- [ ] 在线下载 catalog/package/资产并复算 hash。
- [ ] 验证音频 Range 和客户端真实解析。
- [ ] 演练只回滚 `ko`、不改变 `zh-Hans`。

### L4-P1：App 数据与选择状态

#### L4-007 iOS/Web 多语言 domain model

- [ ] 解码 v2 catalog 和 per-locale release package。
- [ ] legacy v1 通过 adapter 进入相同 domain model。
- [ ] 明确 capabilities，不靠是否有 URL 猜状态。
- [ ] 未知新字段保留安全忽略；未知审核状态不升级。

#### L4-008 语言偏好与默认解析

- [ ] 分开保存 interface preference、preferred content locale 和 per-page selection。
- [ ] 实现本文默认选择顺序。
- [ ] locale 不再可用时选择安全 fallback，并显示变化原因。
- [ ] 升级旧偏好时只迁移界面语言，不把它当内容/音频偏好。

#### L4-009 TargetLanguageSheet

- [ ] 显示每个目标语言的文字/音频/字幕/下载能力。
- [ ] 正式版只列可发布文字；预览能力单独标识。
- [ ] 支持大字、窄屏、横屏、VoiceOver 和键盘/遥控导航。
- [ ] 切换后标题、正文、大纲、字幕和来源说明全部来自同 target。

#### L4-010 音频语言与安全切轨

- [ ] 同语言音频默认，缺失时默认文字版。
- [ ] 跨语言音频只能显式选择并持续显示组合。
- [ ] 用 sourceUnit 映射位置；无映射时不复制秒数。
- [ ] 切轨 token 阻止迟到下载/播放覆盖新选择。

#### L4-011 历史、下载与离线隔离

- [ ] TrackIdentity/PlaybackHistory v2 加入 page、content/audio locale 和 hash。
- [ ] OfflineLibrary 引用加入 locale/release hash，blob 继续按音频 hash 去重。
- [ ] 离线 catalog/package/文本/字幕与音频作为同一受验证快照保存。
- [ ] 缺少所选 locale 的离线资产时不静默回退。

#### L4-012 界面语言扩展

- [ ] iOS String Catalog 和 Web 字典补齐韩语核心流程后再开放 `ko` 界面。
- [ ] interface switch 不重载播放器或改变 target。
- [ ] 动态错误、权限、下载、Now Playing、Live Activity 和 VoiceOver 无硬编码中文。
- [ ] 正文与界面分别设置 language identifier。

#### L4-013 系统媒体、现场对齐与无障碍

- [ ] Now Playing/Live Activity 显示实际内容/音频语言。
- [ ] 指纹索引绑定 audio locale/track/release hash，换语言后撤销旧对齐请求。
- [ ] 跨语言组合的 VoiceOver 先读界面标签，再按正文 locale 读内容。
- [ ] 颜色之外同时使用文字和图标表达仅文字/音频待审/跨语言。

### L4-P2：Web 迁移

#### L4-014 拆分 Web 三种 locale 状态

- [ ] 将现有单一语言按钮拆成 interface 与 sermon language。
- [ ] 内容选择写入 URL `lang`，界面偏好留在本地存储。
- [ ] 音频选择独立，并在跨语言时持续标注。
- [ ] 切换界面语言不重新 fetch catalog、重建 audio 或丢反馈表单。

#### L4-015 v1/v2 双读与链接兼容

- [ ] 旧 `?week=` URL、下载和书签继续工作。
- [ ] v1 catalog 通过 adapter 显示为中文单语言。
- [ ] v2 link 的 locale 无效时使用显式默认并纠正可复制 URL。
- [ ] 页面/locale 发布和回滚不破坏其他页面链接。

### L4-P3：验证矩阵

#### L4-016 自动化能力组合

至少覆盖：

- [ ] 中文文字+音频，韩语仅文字；
- [ ] 中韩都有文字+音频；
- [ ] 韩语音频 candidate 但正式 App 不可用；
- [ ] 选择韩语后显式使用中文音频；
- [ ] 当前语言撤回／离线缺失／catalog 更新；
- [ ] 播放中切换、下载中切换、迟到回调、重启恢复；
- [ ] legacy v1 catalog 和旧语言偏好迁移；
- [ ] 大字、横屏、VoiceOver 和不同系统界面语言。

#### L4-017 真实发布与设备验收

- [ ] 至少一页同时发布 `zh-Hans` 与 `ko` Release Package。
- [ ] 在线逐资产核验和音频 Range 通过。
- [ ] Web 与 iOS 分别验证语言选择、文字版、跨语言标注、下载和恢复。
- [ ] 实体 iPhone 验证 Now Playing、锁屏、耳机、中断、VoiceOver 和离线。
- [ ] 现场验收单独记录，不由 HTTP 或模拟器结果替代。

## 7. Layer 4 完成门槛

- [ ] 每个 `pageId + targetLocale` 有独立 immutable Release Package。
- [ ] Multilingual Catalog v2 能原子聚合、单语言更新和单语言回滚。
- [ ] v1 adapter 保持当前中文发布可读，无审核升级或身份漂移。
- [ ] App 的 interface/content/audio locale 真正分离且偏好可恢复。
- [ ] 没有同语言音频时默认文字版；跨语言音频必须显式且持续标注。
- [ ] 播放历史、下载、字幕、指纹与 locale/hash 正确绑定。
- [ ] HTTP、设备、现场验收分别有收据。
- [ ] 韩语真实文字/音频质量仍以 Layer 2/3 审核为准，Layer 4 不重新判定。

## 8. 推荐实施顺序

```text
L4-001 release validator
  → L4-002 receipt
  → L4-003 catalog v2
  → L4-004 aggregator
  → L4-005 legacy adapter
  → L4-006 atomic publish/rollback

L4-007 app domain model
  → L4-008 preferences
  → L4-009 target language sheet
  → L4-010 safe audio switching
  → L4-011 offline/history
  → L4-012 interface localization
  → L4-013 system surfaces/accessibility

L4-014 Web locale split
  → L4-015 URL/v1 compatibility
  → L4-016 automated matrix
  → L4-017 real HTTP/device/venue acceptance
```

客户端 UI 可以用合成 v2 fixture 提前开发，但正式语言选项只能由真实、已核验的 Release Package 开启。建议先完成发布接口、legacy adapter 和 App domain model，再做语言选择器，避免 UI 先依赖临时字段。

## 9. 明确不在本轮自动完成

- 不生成韩语/西班牙语翻译或音频；
- 不修改 Layer 2/3 审核状态；
- 不自动部署 Firebase、上传 TestFlight 或发布 App Store；
- 不因模拟器、schema 测试或 HTTP 200 宣称设备/现场通过；
- 不把 App 界面翻译完成等同于该语言内容或音频已经发布。
