# 修复后的固定三分钟复测：Sol 6.1 high fast

2026-10-05 按用户指定，在同一三分钟片段上重新执行修复后的 mock、真实 Codex CLI 翻译／独立复核、Spark TTS／ASR、同步诊断及零新调用恢复。**调用、资源准入、自动接续和恢复检查通过；同步仍失败，不具备发布资格。** 下一轮按[生产 finding 开发规划](20261005-production-findings-next-iteration-plan.zh.md)推进。本报告没有开始下一轮功能实现。

## 本轮配置与身份

- 源媒体 180.013167 秒，39 个英文单元、13 个原分组；复用既有英文与模拟人工收据，不重新下载或转写。媒体 SHA256：`79bada8f2e960adb470a146f183449db433308b53c20d03ea9c7e2e0a66e906b`。
- 翻译使用 `gpt-6.1-sol`、high、fast；复核保持 `gpt-6-sol`、medium、fast；CLI workers=1。Fast 同时传 `service_tier="fast"` 与 `--enable fast_mode`。[官方模型资料](https://developers.openai.com/api/docs/models/gpt-6.1-sol)支持 high；实际执行设置以本轮 CLI 收据为准。
- Codex CLI `0.159.0-alpha.12.1`，ChatGPT 登录；子进程去除 API 凭据，不回退 API。收据保存请求模型、effort、tier；CLI 没有提供服务端实际 model/tier，保持 null。
- Spark TTS 保持 Eric checkpoint、BF16/SDPA、seed=42、batch2、自然语速；ASR 保持 Qwen3-ASR-0.6B、batch4。同前轮离线 Docker 配置，TTS 32 GiB/8 CPU、ASR 20 GiB/8 CPU、shm2g、network=none。未启用驻留 session 或新增冷暖基准。
- TTS 镜像 ID `sha256:e615da846c45d026d221bda0f168ae35022af18ac7ec4e5245d04fb62c314f14`；ASR 镜像 ID `sha256:a0a74493c2b670fc76ba04f30c849da4486e3ca3f9dbb8e9e588eb5abc9d0873`；checkpoint 权重 SHA `75d28ce6022b3df3a72df3dd6dbc01e53f584d685770d60ea04b341920968c9a`。

运行前冻结源码，CLI 身份及 Spark 部署使用相同版本。归档 SHA `2d23d3781ffa6ce95002dca2a287870a9994b11a2f1a6db7044b4b895d80096a`；本轮结束核对 5 个相关模块 SHA 均匹配。[机器汇总收据](20261005-sol61-high-fast-fixed-180s-retest-receipt.json)保留源码快照和原始证据 hash，不包含提示词、译文、音频或凭据。原始证据位于 ignored `artifacts/fixed-180s-sol61-high-fast-retest-20261005/`。

新增 `--translator-model gpt-6.1-sol` 只允许隔离测试配置；baseline policy 先验证，再绑定有效配置到 request、policy、transport、payload、cache 和首调用前 context。正式入口拒绝 simulation override，默认仍遵守原策略。历史 `astra` 文件后缀及 `astraDraft` wire 字段保留兼容，但模型调用及 accounting 如实记录 Sol 6.1。详见[测试入口说明](../codex-layer2-test.zh.md#隔离测试的-sol-61-翻译配置)。

## 验证修复是否奏效

| 验证 | 实际结果 | 验证范围 |
|---|---|---|
| 既有修复回归 | 126 项通过，40.528 秒 | L1 cache、本地音频恢复／资源／驻留机制／时间诊断；零真实模型 |
| CLI 配置与分组回归 | 67 项通过，1.388 秒 | 实际 model/effort/tier 传参、正式路径拒绝、cache 身份；零真实模型 |
| 精确历史 mock | 13 组、26 响应通过，0 新调用 | 原 Astra 配置的历史 payload；不把旧返回冒充新 Sol 配置。新配置另用 fake transport 验证 |
| 真实 CLI＋detached owner 的离线调度 | 100 步、99 交接；p95 0.528208 秒；100 reservation 全部释放 | 真实进程和固定媒体，provider/mock 产物；没有在线模型 |
| CLI busy | 容量拒绝、0 started marker、0 模型事件／调用 | 准入在发送前完成；后续正式调用使用同输出身份 |
| GPU busy | 容量拒绝、0 model factory、0 started marker、0 本地模型调用 | 真实 worker 前置准入；探针复用旧有效输入，不执行推理 |
| 真实翻译／复核 | 26 次独立 CLI 调用、13/13 机器通过；tool calls=0 | 结构、coverage、终态、身份、机器评审；尚未运行 language plugin／canonical candidate admission |
| TTS／ASR | 各 13 组，7＋4 批；13 WAV 全量解码；相似度 0.952381–1.000，低于 0.88 的组为 0 | 音频生成与回听筛查；ASR 相似度不代替人工听审 |
| GPU 收据与释放 | 两任务 cleanup_completed、manifest hash 与 outcome 匹配；TTS 释放早于 ASR 准入 | GPU 共用 whole-job 槽，探针＋两任务 3 reservation 均 released；CLI 探针＋26 调用 27 reservation 均 released |
| CLI 原身份恢复 | 0.571545 秒；213 份受保护文件 SHA 不变；0 新文件／模型调用 | 模型完成缓存命中，accounting 不重复记新调用 |
| 本地原身份恢复 | 11.053512 秒；47 份文件 SHA 不变；0 新文件／推理批次 | TTS/ASR 跳过模型，仍含 SSH、Docker 启动／验证和下载开销 |

本轮 CLI 和 GPU 使用分别位于 Mac 与 Spark 的显式 host-local broker；不是跨主机全局容量，也不能限制未接入 broker 的其他任务。GPU receipt 证明清理方法成功和持久化顺序，未独立测量 GB10 的残留显存。真实失败／unknown 的不重发和持槽路径由定向测试覆盖；未刻意制造线上超时或破坏 GPU 清理。

复测使用 `test_codex_layer2_transport`、`test_codex_layer2_fixture_replay`、`test_run_target_language_models` 三模块运行 67 项；另组既有修复测试 126 项。日志保留在 `/tmp/sol61-config-tests.log`、`/tmp/tongxing-retest-existing.log`；不是远端 CI 通过的证明。

## 时间与 token

| 阶段 | 调用／批数 | CLI 进程或本地进程时间 | 输入 token（其中缓存） | 输出 token（其中推理） | 会话输出 token/s |
|---|---:|---:|---:|---:|---:|
| Sol 6.1 high fast 翻译 | 13 | 174.709 秒 | 211,476（111,744） | 7,580（4,693） | 43.39 |
| Sol medium fast 复核 | 13 | 172.646 秒 | 210,722（156,416） | 9,447（4,469） | 54.72 |
| Qwen TTS | 7 批、13 组 | 126.644 秒 | 未提供 | 未提供 | 不可计算 |
| Qwen ASR | 4 批、13 组 | 31.509 秒 | 未提供 | 未提供 | 不可计算 |

CLI 墙钟 348.374 秒，UTC 17:21:46.812049→17:27:35.189018。TTS 加载 35.407 秒、推理 82.523 秒；ASR 加载 18.718 秒、推理 10.416 秒。Docker/SSH 调度包围时间分别 128.813／34.298 秒，不与进程时间相加重复计算。

CLI 完成并确认 durable 13-group test report 后，确定性 controller 0.511327 秒启动本地派发。CLI＋交接＋上传 evidence＋TTS＋ASR 的已测阶段合计 512.707 秒，约 **8 分 33 秒**；下载另约 2.034 秒。该数不包含前面的 mock、部署准备、诊断与恢复验证，也不包含 L1 新生成、人审、正式打包或发布。

本轮合计输入 422,198 token，其中缓存 268,160；输出 17,027，其中推理 9,162。缓存是输入子集、推理是输出子集，不重复相加。输出／CLI 进程总时间包含启动、排队、prefill、推理及等待，**不是纯生成 TPS**。扣除推理后的会话输出为翻译 16.52、复核 28.83 token/s，仍含 JSON/coverage 重复文字，不能称正文翻译速度。Fast 差异不能由单轮推导成稳定收益。

新 API 调用 **0**，新 Codex worker 调用 **26**，本地推理 **11 批**。CLI 订阅额度实际扣减、当前交互监督模型 token、纯生成 TPS 未独立提供，保持未知；本地模型 usage 标记 unavailable，不用 0 代替缺失。本轮确定性阶段接续不新增监督模型 turn，不表示整个交互任务消耗为 0。

## 仍存在的同步 finding

新音频合计 180.88 秒，比源长 0.866833 秒。保持正式 reaction lag=0.05 秒、句间 gap=0.05 秒、max end lag=8 秒，没有放宽政策或变速。新 v2 评估复用正式 scheduler，区分 8 组 own-span 超长警告、4 组真正 lag 失败和 1 组片尾溢出：

| 组 | 自身超窗 | 传入 start delay | end lag | 诊断结论 |
|---|---:|---:|---:|---|
| g003 | 3.070 秒 | 0 | 3.120 秒 | 最早超窗，但仍在 8 秒允许范围内 |
| g004 | 2.670 秒 | 2.960 秒 | 5.680 秒 | 继续累积 |
| g005 | 2.980 秒 | 5.680 秒 | 8.710 秒 | 首次超过 lag 上限 |
| g006 | 0.620 秒 | 8.530 秒 | 9.200 秒 | 大部分延迟来自前组 |
| g007 | 0.670 秒 | 9.200 秒 | 9.920 秒 | 继续传播 |
| g008 | 2.300 秒 | 9.920 秒 | 12.270 秒 | 最大 end lag |
| g011 | 4.290 秒 | 3.660 秒 | 7.999995 秒 | 超窗警告，不应因显示四舍五入误判失败 |
| g013 | 0.260 秒 | 5.500 秒 | 5.810 秒 | lag 合格，但计划末端 185.810 秒，超 clip 5.796834 秒 |

自然串行音频＋固定间隔＋最早起点的下界 181.53 秒，至少需要恢复 1.516833 秒才能装入源时长；这只是必要条件，不保证满足每组锚点。按当前源锚点排程，尾端实际需恢复 5.796834 秒。不能只改最后一组，更不能以所有 lag 组为全量改译清单。优先检查 g003–g005 的实际静音、语速、内容及锚点，再分析 g008/g011；本轮尚未声学裁定原因。

前一轮音频 185.92 秒，本轮 180.88 秒；译者和生成文字改变且运行时不同，这一差异不能归因于资源／缓存修复，也不能证明 Sol 6.1 稳定改善同步。已有修复的收益是准确暴露阻塞、可靠复用与资源释放；不自动修正文稿或音频。

`publicationEligible=false`。未运行正式 controller 全四层、language plugin、canonical candidate/audio admission、人工内容／听审、发布、HTTP 或设备验收。本轮不把模拟审核收据变成正式批准，不把诊断排程冒充 canonical Audio Package。
