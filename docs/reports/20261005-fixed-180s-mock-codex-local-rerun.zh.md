# 固定三分钟：Mockup → Codex CLI → 本地模型重跑

本轮使用同一份 180.013167 秒样本（媒体 SHA `79bada8f2e960adb470a146f183449db433308b53c20d03ea9c7e2e0a66e906b`），39 个英文单元、13 个原分组。先完成零模型 Mockup，再用独立身份重新调用 Codex CLI，随后将本轮译文送入 Spark 本地模型。全部保留测试／诊断资格；模拟人工收据不构成内容批准。

## Mockup 实际结果

- 共享 Layer 2 循环回放 26 个历史完整响应，覆盖 13 组；未构造 Codex transport、未启动 CLI（包括 version）、未调用 API或本地模型。历史 token 不计入本轮调用统计。
- 持久 CLI/owner 使用同一真实片段完成 100 步、99 次交接，墙钟 59.847 秒，交接 p95 0.468489 秒。资源预留 100 次，全部释放；API／Codex／Spark／发布容量均为零。
- 固定片段及旧缓存音轨完整解码通过；未批准源进入下一层、fixture 进入真实发布均被拦截。该预检结果为 `blocked_before_page_generation`，这是门禁验证结果，不是发布成功。

首次调度回放在第 35 步因并行修改代码触发 `execution_closure_changed`，另一个预检在 submit 被同一门禁拒绝。保留原目录后固定实现、建立新身份重跑，未关闭身份校验，也未在旧身份下继续执行。以后应先冻结测试实现，再启动长链；当前 closure 覆盖所有 scripts/schema，相关修改会停止未完成任务。

## 真实调用和速度

Codex CLI `0.159.0-alpha.12.1`，ChatGPT 登录，Astra default → Sol Fast，medium 推理，workers=1。26 次独立调用全部正常退出，无工具调用；13 组覆盖和语义审核通过。本轮输入与旧片段一致，但重新生成中文内容，没有借用旧响应作为真实结果。CLI 总墙钟 315.516 秒；收到正常退出和完整报告后，0.126 秒启动本地阶段的调度脚本。这个交接不含随后上传、Docker/模型启动时间。

| 角色 | 调用数 | 进程秒合计 | 输入 token | 缓存输入 | 输出 token | reasoning token | 会话输出 token/s |
|---|---:|---:|---:|---:|---:|---:|---:|
| Astra 翻译 | 13 | 148.974 | 210,630 | 73,728 | 2,884 | 0 | 19.36 |
| Sol Fast 复核 | 13 | 165.787 | 210,738 | 144,384 | 9,445 | 4,740 | 56.97 |

输入共 421,368、缓存输入 218,112、输出 12,329 token。缓存输入是输入子集，reasoning 不重复相加。表中速度包含 CLI 启动、认证、排队、prefill 和等待；纯生成 TPS、服务端实际模型/档位、监督交互会话 token、订阅实际额度扣减均未独立取得。对照上一轮的不同输出不能得出固定速度提升倍数。

Spark GB10 使用现有注册 Eric checkpoint（权重 SHA `75d28ce6022b3df3a72df3dd6dbc01e53f584d685770d60ea04b341920968c9a`）、CUDA BF16、SDPA、天然语速，单模型 TTS batch=2；模型释放后运行 Qwen3-ASR-0.6B batch=4。两阶段容器均 `--network none`，权重本地挂载且 Hugging Face offline，API 调用 0。

| 阶段 | 批次/组 | 模型加载秒 | 推理秒 | worker 墙钟秒 | SSH+Docker 阶段秒 | 音频秒/推理秒 |
|---|---:|---:|---:|---:|---:|---:|
| TTS | 7 / 13 | 35.210 | 85.742 | 129.804 | 133.009 | 2.17 |
| 回听 ASR | 4 / 13 | 18.201 | 10.069 | 30.217 | 32.360 | 18.47 |

本地模型没有暴露 token 计数；逐批回执保留 null，而不是用字数代替 token。加载、推理和阶段墙钟分别记录；推理包含 GPU 同步，ASR 输入解码另列。CLI 开始到 ASR 阶段返回的调度区间约 481.566 秒（8 分 2 秒），由连续本地控制脚本串接，没有等待监督模型再决定下一步；不含前期准备/上传代码、历史 Layer 1、Mockup、下载和报告整理，也不是完整制作 SLA。

恢复验证：CLI 同参数恢复 0 新调用，105 份证据哈希不变；本地 TTS/ASR 同参数恢复 0 新推理批次，与首轮下载的 39 份文件哈希一致，manifest 不变。冷轮计量未被恢复耗时覆盖。

## 发现的交付问题

13 份 WAV 全量解码和哈希通过；使用现有中文归一化与 SequenceMatcher 口径，ASR 相似度 0.949–1.000，均超过诊断阈值 0.88。这个结果只用于筛查，不代替听审。

**配音合计 185.92 秒，比源视频长 5.906833 秒。** 第 3、4、5、6、7、8、11、13 组超过各自源窗口；第 11 组超过 5.33 秒，第 5 组为 6.24 秒音频对 3.26 秒源窗。总时长以及逐组时间窗是两个独立问题，即使拼接总时长适合视频，也不证明各锚点同步有效。

新增 [诊断评估入口](../../scripts/experiments/assess_fixed_clip_local_models.py) 实际核验本轮输出，将 `diagnostic_audio_exceeds_source_duration` 和 `diagnostic_groups_exceed_source_windows` 写入 `publicationBlockers`；`publicationEligible=false`。未截断、改写、强制变速或伪造批准。时长问题尚未解决：后续需要按正式 Layer 3 同步策略处理这些组，保持完整意思，并取得匹配的人审/同步收据后重新验证。当前结果不能发布成正式可播放内容。

## 代码改动与复盘

1. 增加显式 `--mock-responses-dir`：独立 fixture envelope／backend，绑定原 payload、raw 和 context 共 53 个文件哈希；要求当前 payload 精确匹配，拒绝缺失、漂移和 API key。真实 CLI 和回放不能混用缓存。
2. 调度验收增加 `--media`，不再只能用 0.1 秒静音文件；记录实际媒体哈希和时长，子进程移除 API 环境变量，失败输出只显示阻塞摘要。
3. 增加固定样本本地 TTS／ASR 诊断 worker，校验媒体、39 单元、13 组及中文 Eric 授权/checkpoint。TTS batch=2、ASR batch=4，离线加载，天然语速，不强行压到源时长。started/completed 回执包含调用 ID、模型身份、UTC 时间、推理耗时和输出 SHA；未知结果拒绝自动重播，完整结果可验证后复用。
4. 接入时发现 coverage 文本与 `targetUtterances` 数组不必相等。改为保留原始朗读 utterances，按共享规则校验 coverage 子串；避免拒绝正常输出或从覆盖表重新构造朗读稿。历史 13 组输入离线验证通过。

## 后续改进顺序

1. 先处理 8 个时间窗问题，验证实际同步/播放，再做速度优化；机器通过与模型执行完成不能成为发布资格。
2. 将本轮独立真实诊断链接入 canonical adapter 的同一资源 broker。当前真实链采用空载核验和独立目录锁；这次没有证明全局 broker 已管理实际 CLI 调用或跨任务 GPU 并发。保持本轮已有回执，避免重新生成不变的上游。
3. ASR 加载 18.20 秒、推理 10.07 秒，TTS 加载 35.21 秒。持久本地 worker/同身份模型驻留是下一项实验；需要实际冷暖对照，再报告时间收益。本轮没有为了测热加载重复推理。
4. CLI 固有上下文让输入达到 42 万 token；按真实 usage 和缓存口径监测，不能仅按片段文字长度预估额度。监督会话需宿主 telemetry 单独归因。

相关验证分两组运行：48 项调度/资源/fixture 测试、36 项本地诊断/fixture/CLI 测试通过（其中 4 项重叠）；新增评估入口 4 项测试通过。独立只读审核未发现本轮目标内 P1/P2 缺陷，`git diff --check` 通过。

## 证据和范围

Ignored 证据：`artifacts/codex-cli-layer2-180s-mock-replay-20261005/`、`artifacts/fixed-180s-resource-mock-20261005{,-stable}/`、`artifacts/fixed-180s-preflight-mock-20261005{,-stable}/`、`artifacts/fixed-180s-codex-local-real-20261005/`。原始媒体、文本、模型返回、私有调用日志、权重和本地 checkpoint map 不入 Git。

本轮不把独立诊断链称为 canonical controller 全四层 dispatch：语言插件、正式 candidate admission、人审、源时间轴同步、Beta／Dev 发布和设备验收需各自收据。已有真实 Layer 2 入口仍 workers=1；本次不据此宣称吞吐提升或 24 路生产调度已上线。CLI 使用 ChatGPT 登录，不加载项目 API key；Spark 模型容器网络关闭。订阅额度扣减和纯生成 TPS 未独立取得，本地模型 token 缺失保持 null。
