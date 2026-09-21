# 多语言生产四层接口

状态：四个层间接口名称和 JSON Schema 已冻结为 v1；Layer 1 已有确定性生成器并接入未来周 shadow。Layer 2–4 的 schema 是迁移目标，不表示对应的多语言生产实现已经完成。

## 统一命名

全项目只使用下面四个生产层名称。审核、哈希、人工批准和验收是贯穿各层的门禁，不另算生产层。

| 层 | 中文名称 | English name | 唯一正式输出 |
|---|---|---|---|
| Layer 1 | 共享英文事实与锚点 | Shared English Source & Anchors | `English Source Package` / `sermon-english-source-package-v1` |
| Layer 2 | 目标语言文字 | Target-Language Text | `Target-Language Candidate` / `sermon-target-language-candidate-v2` |
| Layer 3 | 目标语言音频与同步 | Target-Language Audio & Synchronization | `Target-Language Audio Package` / `sermon-target-language-audio-package-v1` |
| Layer 4 | 多语言发布与播放 | Multilingual Delivery & Playback | `Target-Language Release Package` / `sermon-target-language-release-package-v1` |

`targetLocale` 一律使用 BCP 47：英文事实源为 `en`，简体中文内容为 `zh-Hans`，韩语为 `ko`，西班牙语为 `es`。现有 Web 界面使用的 `zh-CN` 是 legacy interface-locale adapter，不得写入新的内容、音频或发布包。

## 数据流与失效规则

```text
English Source Package
  ├─ anchorManifestJsonSha256 ──> Target-Language Candidate (zh-Hans)
  ├─ anchorManifestJsonSha256 ──> Target-Language Candidate (ko)
  └─ anchorManifestJsonSha256 ──> Target-Language Candidate (es)

Target-Language Candidate
  └─ candidate hash ────────────> Target-Language Speech Job
                                  └─ measured artifacts ─> Target-Language Audio Package

Target-Language Candidate + optional Target-Language Audio Package
  └─────────────────────────────> Target-Language Release Package
```

- Layer 1 的 `downstreamInvalidationKey` 改变时，所有目标语言文字、音频和发布审核失效。
- Layer 2 的 `downstreamInvalidationKey` 改变时，只使同一 `targetLocale` 的音频和发布失效，不影响其他语言。
- Layer 3 改变时，只使同一语言的发布包失效，不回写或修改译文。
- Layer 4 只聚合已存在且 hash 匹配的资产；不得补翻译、重写音频或提升上游审核状态。

## Layer 1：共享英文事实与锚点

输入：授权媒体身份、人工批准的证道范围、冻结英文转写、一个选定的词级对齐结果，以及可选的英文人工审核收据。

处理：

1. 验证英文转写与 aligned segments 的内容 hash。
2. 记录唯一 `alignment.provider`；MFA 和 Qwen ForcedAligner 可以做 A/B，但同一个正式包不能混合两条词时间轴。
3. 生成 `clause_stable_v2` 父句／子锚；只在标点或可听停顿处分句。
4. 绑定英文完整性、词级对齐、句界和停顿审核；任何来源改动产生新的失效 key。

输出 schema：[English Source Package](../schemas/sermon-english-source-package-v1.schema.json)。人工批准输入 schema：[English Source Review](../schemas/sermon-english-source-review-v1.schema.json)。底层锚点继续使用 [clause-stable v2 anchor manifest](../schemas/sermon-sentence-anchor-manifest-v2.schema.json)。

状态含义：

- `blocked`：锚点或对齐有未解决问题，不得调用翻译模型。
- `candidate_ready_for_translation`：结构检查通过，可用于 shadow 模型实验，但仍缺生产所需的来源或人工门禁。
- `ready_for_translation`：媒体身份、批准范围和四项英文人工检查均已绑定，允许正式 Layer 2 消费。

当前生成器：[build_english_source_package.py](../scripts/build_english_source_package.py)。未来周入口 [prepare_sentence_interpretation_shadow.py](../scripts/prepare_sentence_interpretation_shadow.py) 同时写出 `anchor-manifest.json` 和 `english-source-package.json`；`run_post_live_subtitle_generation.py` 可用 `--sentence-interpretation-english-review` 绑定人工审核收据并重跑 Layer 1。这一层不写入中文 prompt，也不生成目标语言文字。

## Layer 2：目标语言文字

输入：一个 `ready_for_translation` 的 English Source Package、`targetLocale` 和冻结的翻译策略 hash（模型、prompt、术语表、经文版本及排版规则）。

处理：只翻译目标 `sourceUnitIds`，上下文仅用于消歧；初译和独立复核使用不同 request；通用语义检查与语言专属检查分开；人工审核独立记录。

输出 schema：[Target-Language Candidate](../schemas/sermon-target-language-candidate-v2.schema.json)。一个文件只承载一个 locale。中文、韩语和西班牙语不得写进同一个对象，也不得通过中文回译产生其他语言。

现有 `sermon-sentence-interpretation-candidate-v1` 是把中文和音频耦合在一起的 legacy 合同；迁移时由 `zh-Hans` adapter 转成新文字包，历史产物保持可读。

## Layer 3：目标语言音频与同步

输入：一个 `human_translation_approved` Target-Language Candidate、支持相同 `targetLocale` 的授权 voice/checkpoint、同一个 English Source Package 锚点以及自然语速策略。准备阶段使用 [Target-Language Speech Job](../schemas/sermon-target-language-speech-job-v1.schema.json) 锁定 adapter 和输出目录。

处理：逐单元 TTS、完整解码、回转写筛查、实测时长、确定性滚动排程、字幕 cue、人耳全文听审和同视频 1 倍速检查。ASR 筛查不等于人工听审。

输出 schema：[Target-Language Audio Package](../schemas/sermon-target-language-audio-package-v1.schema.json)。`audio_unavailable` 是合法状态，可进入纯文字发布；不得借用另一语言音轨冒充当前 locale。

## Layer 4：多语言发布与播放

输入：目标语言文字包，以及同 locale 的可选音频包；页面来源身份和显式发布文件清单。

处理：按 `pageId + targetLocale` 聚合，分别记录 `interfaceLocale`、`contentLocale` 和 `audioLocale`，构建 allowlist，验证文件 hash、HTTP、Range 和客户端播放。

输出 schema：[Target-Language Release Package](../schemas/sermon-target-language-release-package-v1.schema.json)。HTTP 通过、设备通过和现场通过是三个独立状态。

## 当前实现边界

- Layer 1：代码已实现并进入 shadow；没有英文人工审核收据时只产生 `candidate_ready_for_translation`。
- Layer 2：中文 legacy runner 可工作，新通用文字包 producer 尚未实现。
- Layer 3：中文 legacy TTS／同步可工作，新通用音频包 producer 及韩语/西班牙语 speech adapter 尚未实现。
- Layer 4：当前生产仍为 `sermon-weekly-catalog-v1`；多语言 catalog 和 release package producer 尚未实现。
- Canonical English Content 是从英文事实派生的页面内容输入，可以作为 English Source Package 的可选绑定；它不是英文逐字稿，也不能替代 Layer 1 审核。
