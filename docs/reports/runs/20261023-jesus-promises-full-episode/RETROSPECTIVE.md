# 复盘：20261023-jesus-promises-full-episode

数据见同目录 `INDEX.md` 和 `manifest.json`。本轮是逐句优先线的整期双讲员 Production 发布，交付类型 `four_layer_release`。

## 结论先行

- 《If I Had More Time — Jesus promises》（2026-09-19，YouTube `NfJx9YHGGe4`），59:15，946 句，Steve Bang Lee + Eric Geiger，三语 zh-Hans / ko / es。
- 英文来源由提供的滚动 SRT 重建（1751 cue → 946 单元，时间按 cue 内插，**不是正式 ASR/MFA**）；用户 2026-10-23 12:27「英文通过」。
- 讲员区分 pyannote community-1（3554 s 音频，52 分钟，678 段）；用户 13:20 确认 `SPEAKER_01=Eric`、`SPEAKER_00=Steve`；72 句占比 <0.8 已在审核表标记。
- 中文 14:20、韩语 15:04、西语 15:31 PDT 分别「通过」；每条收据绑定 track/CSV/MP3 的 SHA。
- Production 页面 `if-i-had-more-time-jesus-promises` 已上线：资产 `e579fd99fe7cb2a6` → release+目录 `e8b98832e5164f13` → 英文对照 `25986755c1843f5b`。
- 证据边界：HTTP/SHA/Range、目录与 release 回读、英文对照 946 blocks/语言均通过；iOS 真机/TestFlight、浏览器播放、现场验收 `not_run`。

## 总时间

约 3.5 小时墙钟（12:15–15:45 PDT），主要构成为 TTS 约 1.85 小时、说话人区分 52 分钟、三语翻译与复核约 25 分钟、发布 3 次部署约 10 分钟，以及三次人工听审的等待。

## 各层模型、耗时与速度

| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---|---|---|---|---|---|
| L1 英文与锚点 | 滚动 SRT 重建（实验脚本） | — | 1 | 秒级 | 946 单元 / 59:04.9 | — | 0 | `layer1-srt/anchor-manifest.json` |
| L1 英文审核 | 用户逐句审核 | — | 1 | 等待 | 946 句 | — | 用户时间 | `english-approval.json` |
| L1 说话人区分 | pyannote/speaker-diarization-community-1 | CPU | 1 | 52 min | 3554 s | ~0.88× 实时 | 本地 | `jp-diarize/diarization.json` |
| L2 zh | 本会话 4 个子代理 | 未记录 | 4 | 约 6 min | 946 句 | — | 订阅额度 | `translate/output-*.jsonl` |
| L2 ko | 本会话 4 个子代理 | 未记录 | 4 | 约 6 min | 946 句 | — | 订阅额度 | 同上 |
| L2 es | 本会话 4 个子代理 | 未记录 | 4 | 约 7 min | 946 句 | — | 订阅额度 | 同上 |
| L3 TTS zh | Qwen3-TTS 1.7B 讲员 SFT，batch 1 | bf16 | 946 | 2482.7 s | 3378.2 s | 1.36× | 本地 GPU | `tts/tts-log.jsonl` |
| L3 TTS ko | 同上 | bf16 | 946 | 2766.3 s | 3748.5 s | 1.36× | 本地 GPU | 同上 |
| L3 TTS es | 同上，batch 8（Steve 224 句 batch1 + 58 句 batch8，Eric 664 句 batch8） | bf16 | 946 | 1418.2 s | 3797.3 s | 整体 2.68×；batch 段 3.87× | 本地 GPU | 同上 |
| L3 回转写 | Qwen3-ASR-0.6B | — | 3 | 约 2.5 min | 946 句/语 | — | 本地 GPU | `asr-report.json` |
| L4 构建与发布 | Production 受保护发布器 | — | 3 次部署 | 约 10 min | 12 资产 + 3 release + 3 目录 + 1 英文对照 | — | 0 | 部署版本见上 |

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| L1 SRT | 句表出现 start>end 与句间重叠，切片失败两次 | 滚动 cue 时间倒退、短句被拉到 0.5 s | 占用资源前 | token 时间轴严格单调 + 句界不重叠 | `prepare_clip` 946 句切片成功 | 实验脚本；待整理 PR |
| L1 说话人 | 全片 pyannote 用时 52 分钟 | 本机 CPU、3554 s 音频 | 占用资源后 | 等待完成；未并行化 | 678 段、用户确认映射 | 本报告 |
| L2 韩语 | 部分句用「당신」，其他部分用「여러분」 | 4 个子代理独立翻译 | 发布前 | 审核表标出；未统一改写 | 用户听审通过 | 待后续术语/称呼统一 |
| L3 TTS | Eric 第一次任务 33 s 退出 | checkpoint 内部 speaker key 是 `eric_pilot`，speech 用了 `eric_geiger` | 占用资源后 | `review.json` 映射 `eric_geiger→eric_pilot`，重建 speech 续跑 | 946/946 成功 | 实验脚本；AGENTS 待补 |
| L3 es | 8×8 正式路径不能用于双讲员 | 正式 renderer 拒绝多讲员 | 用户询问时 | 改逐句线 batch-8（单副本），用户选 1 | es 946/946；batch 3.87× | 本报告 |
| L3 es | Steve 224 句串行 + 58 句 batch-8 混合 | 串行中途切换 | 发布前 | 审核表标出；用户听审通过 | es 通过 | 本报告 |
| L4 英文对照 | 规范 builder 找不到证据文件 | 英文包证据路径是仓库相对路径，从 worktree cwd 解析不到 | 发布后（第三次部署前） | 从仓库根目录运行 stage 命令；包/页面身份不变 | 946 blocks/语言、SHA 一致 | 本报告 |

## 可以改进的地方

| 类别 | 改进 | 依据 | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 预检 | SRT 派生 Layer 1 的句表先做零时长/重叠检查 | 两次切片失败 | 少一次重切 | 本会话 | 实验脚本 |
| 流程 | 明确 `speakerId` 与 checkpoint `speakerKey` 的映射 | Eric 首次 TTS 失败 | 少一次 33 s 失败与重建 | 本会话 | AGENTS §6 |
| 速度 | 逐句线 batch-8 选项 | es 整体 2.68×、batch 3.87× | 短片段/整期提速 | 本会话 | `--batch-size` |
| 流程 | 英文对照证据路径用绝对路径或固定从仓库根运行 | 第三次部署前失败 | 少一次重跑 | 本会话 | 发布驱动/AGENTS |
| 流程 | 双讲员正式 8×8（8 副本 × batch 8）仍缺 | 正式 renderer 只支持单讲员 | 更大吞吐 | 待评估 | 本报告 |
| 质量 | 三语称呼/术语跨子代理统一（韩语 당신/여러분） | 韩语翻译不一致 | 译文一致性 | 待后续 | 翻译简报 |

## 实际覆盖范围

- L1：SRT 重建 + 用户英文审核 + pyannote 讲员区分 + 用户映射确认；未跑正式 ASR/MFA，英文来源包明示这一点。
- L2：三语各 946 句，4 份并行子代理 + 合并检查；修订 zh 120、ko 93、es 102 句。
- L3：三语 × 两讲员逐句 TTS、回转写、合并、打分；zh/ko batch 1，es batch 8。
- L4：Production 资产、release v2、v5/v4/v3 目录、英文对照；三次部署与回读。
- 未执行：iOS 真机/TestFlight、浏览器播放、现场验收、PDF、Dev 页面。

## 遗留状态

- Spark 会话 `sfa-jp-20261023` 已 `finish`，模型服务恢复（modelHealth healthy），按标签删除容器。
- 工作树 `artifacts/worktrees/sfa-main` 里 Registry 更新、新发布驱动、batch-8 脚本与审核收据尚未提交/推送；报告 PR 只含文档。
- `artifacts/sentence-first-agent/20261023-jesus-promises-*` 保留 track/tts/asr/审核表；原片与切片留在本机忽略目录。
- 本地 `artifacts/podcasts/if-i-had-more-time-jesus-promises/` 保留媒体、SRT、英文包与 946 句句表。

## 外部可见的变化

- Production Hosting 最终版本 `25986755c1843f5b`（资产 `e579fd99fe7cb2a6` → release+目录 `e8b98832e5164f13` → 英文对照 `25986755c1843f5b`）。
- 页面：`/pages/if-i-had-more-time-jesus-promises/zh-Hans|ko|es/index.html`；release：`/releases-v2/if-i-had-more-time-jesus-promises/<locale>.json`；英文对照：`/english-reference/if-i-had-more-time-jesus-promises.json`。
- 核验：12 个资产 HTTP/SHA 通过（MP3 Range 206）；目录与 release 回读 6/6；页面/文稿/字幕 200 且 SHA 一致；英文对照 200、946 blocks/语言、`human_approved`。
- 没有 TestFlight、没有受保护分支推送、设备/场地验收 `not_run`。
