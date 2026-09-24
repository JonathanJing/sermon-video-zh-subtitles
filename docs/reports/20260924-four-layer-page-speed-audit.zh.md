# Dev 四层页面生成耗时审计（2026-09-24）

基线：`origin/dev` 的 `e4cb621`。目标是缩短从来源就绪到页面 HTTP 核验通过的墙钟时间。代码调用次数不是耗时；并行阶段的时长也不能相加为页面总时长。

## 目前能量到什么

- 四层计时入口已经存在，但本地 `2026-09-20-178s-clip` tracker 的 46 个检查点中，19 个标记完成的步骤均无执行 span；`four_layer_measure.py audit` 的实测步骤数为 0。旧 [9 月 20 日生产 accounting](20260920-production-accounting.json) 主要属于中文 legacy 流程，不是本四层页面的墙钟基线。
- 已验证的三分钟样片含中文 45、韩语 44、西语 44 个正式文字／语音组，见[样片记录](20260923-sep20-three-minute-dev-run.zh.md)。它证明工作量和门禁，不提供可用于推断整篇周更时长的完整阶段计时。
- 当前 [Tracker 接入清单](../four-layer-production-tracker.zh.md#tracker-接入-backlog) 明确：正式模型调用、音频合成／同步和 Layer 4 producer 尚无自动 span；人工审核与资源排队也没有完整事件。因此本报告不声称页面已提速多少分钟。

## 按页面关键路径排序

| 优先级 | 层与现状 | 候选动作 | 放行条件 |
|---|---|---|---|
| P0 | [周计划编译器](../../scripts/prepare_multilingual_weekly_plan.py)只写每语言 lane 和 lease key，没有执行三语生产的调度器；人工顺次调用时会损失跨 locale 并行机会。 | 在现有 Supervisor lease 下验证三语 Layer 2 同时启动；某 locale 的文字批准后立即启动其正式 Layer 3，最终在 Layer 4 汇合。 | 不共享候选／音频写入目录；同源 hash、每语言审批与本次三语音轨齐全门禁保持独立。 |
| P0 | Layer 2 的[正式模型 runner](../../scripts/run_target_language_models.py)原来逐组执行 Astra 初译→Sol 复核且强制 `workers=1`；样片三语合计 133 组，每组两个独立 API 请求。 | 本轮支持**新冻结的 v2 policy** 选择 2、3 个跨组 worker；组内仍先 Astra 后 Sol，按源组顺序合并，保留原始响应、失败缓存与完整准入链。 | 同输入 A/B 记录每组 API latency、限流／重试、整 locale 墙钟和人工修订；policy hash、候选及人审收据变更须按新运行处理。 |
| P0 | Layer 3 [正式 renderer](../../scripts/render_formal_target_language_speech.py)逐单元合成；[ASR 筛查](../../scripts/screen_target_language_audio_units.py)逐单元转写。GPU 可能是共享瓶颈。 | 先记录模型加载、单元 TTS、解码和 ASR 耗时与 GPU 峰值，再比较现有缓存／预生成复用、ASR 微批和 1／2 路合成。 | 实测页面关键路径更短且音质、回转写、整轨听审与同步门禁不降级；不要假设增加 GPU 并发一定更快。 |
| P1 | Layer 4 的 Production 基线与发布后核验逐文件完整 GET/SHA，候选约 121 文件时网络往返串行累积。 | 本轮新增 `--http-workers 4`：最多四个文件同时下载，仍逐文件计算完整 SHA、字节数、Content-Type，并保持收据顺序；Range 与深链检查不变。 | 用同一候选分别运行 1 与 4 worker，比较两次核验墙钟、失败率和 Hosting 限流；发布前基线仍须在 30 分钟有效窗内。 |
| P1 | Layer 1 包中的 artifact 带绝对路径，Layer 2 policy 又绑定整包 JSON hash；移动相同字节的产物可能导致三语重新冻结策略。机器裁判虽按批串行，其结果只放行 shadow。 | 对包路径与稳定内容身份的分离设计版本化迁移，先核对同内容搬迁是否产生无意义失效；同时重叠媒体完整性、对齐、锚点及审核准备。 | 不放松真实媒体／窗口／英文变化的全语言失效；不把 shadow 通过当作正式放行。 |

三语可各自从 Layer 2 进入本语言 Layer 3；最终按本次要求在 Layer 4 等三条正式音轨汇合。审核等待期间可准备不依赖批准结果的工作，或使用已有 `preview_only` 配音复用机制；正式 Speech Job、Audio Package 与 Release Package 仍由各自 hash 与人审收据放行。参见[四层合同](../multilingual-production-interfaces.zh.md#审核与执行解耦)。

## 本轮代码验证与下一次实测

- [正式 Layer 2 runner](../../scripts/run_target_language_models.py)在冻结 policy 的 `workers=1..3` 范围内有界运行；观测到失败后不再提交新组，已经启动的请求完成后才返回错误。默认模板的旧 `workers=1` 仍串行。
- [线上核验器](../../scripts/verify_multilingual_hosting.py)新增有界并发选项；函数调用默认 1 worker 兼容原用法，Production 执行命令显式使用 4 worker。任何文件失败时不会产出通过收据；已启动请求结束后返回错误。
- [Layer 2 定向测试](../../tests/test_run_target_language_models.py)覆盖跨组并发、组内顺序、原序归并、缓存再运行、候选机器准入与失败停止后续组；[Layer 4 定向测试](../../tests/test_verify_multilingual_hosting.py)覆盖并发进入、收据原序、篡改基线拒绝，以及原有完整文件／Range／深链检查。测试只证明行为，不证明真实 API 或 Hosting 的延迟收益。
- 下一次同一新周运行应从开始就使用同一个四层 ledger：对未接入的 L2 模型、L3 合成／ASR／排程和 L4 构建／核验命令使用 `four_layer_measure.py run` 包裹；记录每 locale 的执行 span、审核发出／回复、缓存命中、重试及资源等待。最终按实际事件计算页面墙钟与最长语言分支，不能用文件修改时间补造。
