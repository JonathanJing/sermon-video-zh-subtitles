# 复盘：20261023-sentence-first-dev-clip

数据见同目录 `INDEX.md` 和 `manifest.json`。本轮是逐句优先路线的 Dev 实验片段，交付类型 `four_layer_release`（Dev 环境），不是 Production 发布。

## 结论先行

- 2026-10-18 播客 *If I Had More Time*（YouTube `AKY0k5KiKns`）的锚点单元 179–365，187 句、10.3 分钟，中文 + 韩语。
- 机器阶段、人工听审、Dev 三次部署、HTTP/SHA 与英文对照核验全部完成；页面 `sentence-first-clip-20261023` 已上线 `https://ai-for-god-sermon-audio-dev.web.app`，最终 Hosting 版本 `f103d2909a9412a5`。
- 人工审核：用户 2026-10-23 11:39 PDT 在对话中明确「两条都通过」；收据绑定两条 `track.wav`、审核表与 MP3 的 SHA。
- 证据边界：Dev 页面可打开、资产与英文对照 HTTP 核验通过；iOS 真机/TestFlight、浏览器播放、现场验收均未做（`not_run`），不能据此声称正式版 App 可见或现场可用。

## 总时间

约 2 小时 16 分钟墙钟（09:31–11:47 PDT），其中约 1 小时 09 分钟在等用户听审。

| 段 | 约用时 | 说明 |
|---|---|---|
| 环境预检、worktree、clip | 25 min | 本地分支落后 2759 个提交；建 origin/main worktree；venv PYTHONPATH 修正 |
| 句表、讲员分配、中文复用 | 5 min | 从 Spark 的 2026-10-22 整期 `speech.jsonl` 逐单元复用讲员 |
| 韩语翻译（3 子代理） | 6 min | 12 句第二遍修订 |
| zh + ko TTS/ASR | 25 min | 4 个 TTS 任务 + 2 个 ASR 任务，187/187 成功 |
| finish_run + 审核表 | 6 min | 合并、打分、dub、640 预览、两个 CSV/MP3 |
| 发布预检 + 英文对照子集测试 | 20 min | assets 干跑、stage2 合同校验、Firebase/ADC、合成快照 |
| 用户听审（等待） | 69 min | 人工门禁 |
| 三次部署 + 核验 | 8 min | 资产 → release+目录 → 英文对照 |

## 各层模型、耗时与速度

| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---|---|---|---|---|---|
| L1 英文与锚点 | 正式 Layer 1（复用） | not_run（复用） | 0 | 0 | 746 单元 | — | 0 | `english-source.json` · `output-v20/anchor-manifest.json` |
| L1 词级对齐 | MFA（正式结果，复用） | — | 0 | 0 | — | — | 0 | 同上 |
| L2 zh | 正式 Layer 2 已批准译文（复用） | — | 0 | 0 | 187 句 | — | 0 | `candidate-approved.json` |
| L2 ko | 本会话 3 个翻译子代理 + 独立第二遍复核 | 未记录 | 3 | 约 6 min | 187 句 | — | 订阅额度 | `translate/output-*.jsonl` |
| L3 配音 zh | Qwen3-TTS 1.7B 讲员 SFT checkpoint，batch 1，seed 7 | bf16 | 187 句 | 556.7 s 墙钟 | 756.6 s 音频 | 1.36× 实时 | 本地 GPU | `tts/tts-log.jsonl` |
| L3 配音 ko | 同上，韩语 | bf16 | 187 句 | 546.1 s 墙钟 | 746.2 s 音频 | 1.37× 实时 | 本地 GPU | `tts/tts-log.jsonl` |
| L3 回转写 | Qwen3-ASR-0.6B，batch 8 | — | 2 次 | 40 s + 48 s | 187 句/语 | — | 本地 GPU | `asr.jsonl` · `asr-report.json` |
| L4 构建与发布 | Dev Hosting 受保护发布器 | — | 3 次部署 | 约 8 min | 8 资产 + 2 release + 3 目录 + 1 英文对照 | — | 0 | 部署版本见下 |

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| 预检 | 实验目录只有 5 个脚本，缺 11 个 | 本地分支落后 origin/main 2759 个提交 | 预检 | 建 `artifacts/worktrees/sfa-main` worktree | 逐脚本 `--help` | 本报告；AGENTS §0.5 |
| 预检 | 驱动导入旧 `tongxing_production`，`baseline()` 报 unexpected keyword | 主 checkout 的 venv editable 指向旧包 | 预检 | `PYTHONPATH="packages/production/src:."` 并核对 `__file__` | 发布驱动成功运行 | 同上 |
| L1/讲员 | 正式 diarization segments 与标签映射不在本机 | 2026-10-22 run 目录被清理 | 占用资源前 | 按整期已发布 `speech.jsonl` 逐单元复用，未重算置信度 | English/译文逐句对齐 | AGENTS §3 |
| 预检 | `speaker-checkpoints.dgx.json` 不存在 | AGENTS 指向的文件未保留 | 预检 | 按 Registry hash + 实际目录解析；记录 John checkpoint root 所有的限制 | Steve sha256 与 Registry 一致 | AGENTS §6 |
| 预检 | run 目录在 worktree 时 `slices.json` 相对路径失效 | `slices.json` 存仓库相对路径 | 占用资源前 | run 移到主 checkout 的 `artifacts/sentence-first-agent/`，从仓库根运行 | build_speech/finish_run 成功 | AGENTS §0.5 |
| L4 | 复制 `publish_podcast_page.py` 后仍会部署 Production | `stage()`/`baseline()` 写死 production，ORIGIN、句数、run 名、verdict 路径写死 | 预检 | 新建 dev 驱动 `publish_clip_page_dev.py` 并参数化 | 三次 Dev 部署成功 | 本报告；AGENTS §10 |
| L4 | `firebase projects:list` 报 credentials invalid | 沙箱下 `~/.config/configstore` 不可写 | 预检 | `XDG_CONFIG_HOME` 指向工作区副本；ADC 走 `application_default_credentials.json` | `firebase login:list` 与 ADC token 通过 | AGENTS §0.5 |
| L4/英文对照 | 规范 `build_reference` 拒绝 187 句片段 | 它要求页面覆盖英文来源包全部 746 个单元 | 发布前（合成快照） | dev 驱动加 `build_clip_reference`：同样审批/哈希检查，连续有序子集 | 两语各 187 blocks，与已发布整期英文对照 0 处不一致 | AGENTS §10 |
| L3 | 「千禧年论」被 ASR 识别成「迁徙年轮」（0.636） | 同音/ASR 误识，不是配音错读 | 发布前 | 交人工听审；用户通过 | 审核表标出 s0064 | `review-zh-Hans.csv` |
| L3 | 韩语 s0163「타임스탬프」被 ASR 写成 TimeStamp（0.500） | 拉丁转写/ASR 差异 | 发布前 | 交人工听审；用户通过 | 审核表标出 s0163 | `review-ko.csv` |

## 可以改进的地方

| 类别 | 改进 | 依据 | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 预检 | 开工前自动核对分支/venv/run 路径/Firebase/checkpoint | 本轮前 4 个错误都在占用资源前发现 | 少一次 worktree/导入返工 | 本会话 | AGENTS §0.5 |
| 流程 | 发布后保留小文本表，只删音频/视频/切片 | 上一期 run 目录被清理，讲员分配只能从 Spark 找回 | 可 resume、可复用讲员与已批准译文 | 本会话 | AGENTS §11 |
| 流程 | 规范英文对照 builder 增加片段子集模式 | 片段页 187 单元被 `mapped_ids == unit_ids` 拒绝 | 片段页不再需要复制驱动 | 本会话 | AGENTS §10；建议另开仓库 PR |
| 预检 | 发布前在本地合成快照跑一次 stage2 + 英文对照 | 本轮在部署前发现并修掉片段阻塞 | 避免部署后才发现合同拒绝 | 本会话 | 本报告 §错误 |
| 速度 | 短片段评估同语言两讲员共用容器 | 4 个 TTS 任务各加载一次模型；10 分钟片段约 4 次加载 | 省 2–3 分钟/短片段 | 本会话 | 待评估，先问用户 |
| 质量 | 审核表对同音/数字/神学术语加提示 | s0064/s0045/s0134 需人听 | 听审更有针对性 | 本会话 | 本报告 |
| 成本 | Dev 发布驱动参数化 environment/ORIGIN/句数/run/verdict | 复制后仍需改 4 处代码 | 少一次复制 | 本会话 | `publish_clip_page_dev.py` |

## 实际覆盖范围

- L1：复用正式批准的英文来源包与锚点（746 单元，`humanApproval=true`），未重跑 ASR/MFA。
- L2：中文复用正式已批准译文；韩语本轮新译并复核。
- L3：两语逐句 TTS、回转写、合并、打分、dub 与 640 预览全部执行。
- L4：Dev 页面、文稿、字幕、MP3、release v2、v5/v4/v3 目录、英文对照全部发布并 HTTP 核验。
- 未执行：iOS 真机/TestFlight、浏览器播放、现场验收、PDF 交付、Production 发布。

## 遗留状态

- Spark 会话 `sfa-clip-20261023` 已于 2026-10-23T17:29:44Z `finish`，模型服务恢复，5 个停止容器已删除。
- Dev 上新增页面 `sentence-first-clip-20261023`（zh-Hans、ko）与 `/english-reference/sentence-first-clip-20261023.json`；没有未引用的临时文件被部署。
- 本地保留两条 `track.wav`、`dub.mp4`、`dub-preview-640.mp4`、`tts/`、`slices/`；小文本表保留。
- `deviceAcceptance`、`venueAcceptance` 仍为 `not_run`。

## 外部可见的变化

- Dev Hosting 最终版本 `f103d2909a9412a5`（assets `6a58571b22d09277` → release+目录 `8f4a50c4a7b9dd04` → 英文对照 `f103d2909a9412a5`）。
- 页面：`https://ai-for-god-sermon-audio-dev.web.app/pages/sentence-first-clip-20261023/zh-Hans/index.html`（`ko` 同路径）。
- release：`/releases-v2/sentence-first-clip-20261023/{zh-Hans,ko}.json`；英文对照 `/english-reference/sentence-first-clip-20261023.json`（两语各 187 blocks，SHA `6acbe060…`）。
- 核验：8 个新资产 HTTP/SHA 全过（MP3 Range 206）；目录与 release 回读 5/5；页面/文稿/字幕 200 且与发布字节一致；content/captions/英文对照 textGroupId 顺序一致。
- 没有 TestFlight、没有 Production 发布、没有受保护分支推送。
