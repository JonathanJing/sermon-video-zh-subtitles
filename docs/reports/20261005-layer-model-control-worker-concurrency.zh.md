# 各层模型、controller 与 worker 并发分析

2026-10-05，基于分支 `codex/dev-rerun-20261005` 的代码和已完成测试。这里的“当前配置”指已提交的配置／入口默认，不是后台正在运行的进程数。本次只读审计与文档修订，没有新模型调用、扩容或更改生产容量。

操作者指出短片段任务不足以代表整篇吞吐，这个判断成立。上一轮每轮只有24项短调用，16路仅有两波、24路仅有一波；因此 **24路成功已验证，16路是否比24路适合整篇尚未验证**。不能把4.39%的批次墙钟差异当作服务端已饱和的证据。

## 模型与数量限制

control 是准入、状态与派发；worker 是实际执行单位；batch 是一次调用里的内容数量。三者不应相乘成“同时运行的独立流程数”。

| 层／角色 | 模型与后端 | control／任务限制 | worker／batch：当前与允许范围 |
|---|---|---|---|
| 全程监督 | 已有 Agents API／SDK 入口默认 `gpt-6-sol` Medium；Codex Luna 是可选监督模型，不是已提交入口的默认值 | 同 run 的依赖 mutation 顺序执行；SDK 禁用并行 tool calls。没有统一跨所有 run 的监督会话数量池 | 一次控制循环派发后检查／等待；模型会话数与业务 worker 数分开统计。CLI24 实测是 Astra／Sol 业务调用，没有验证24个 Luna Supervisor |
| L1 来源转写 | `gpt-transcribe` API | unified source 持同输出 work lock；来源→对齐→judge 顺序消费证据 | 单 job 内按180秒音频块串行转写：1在途；没有跨所有来源的统一 API 槽位上限 |
| L1 英文锚点对齐 | MFA English dictionary／acoustic／G2P；Spark优先 | 同 Spark 请求身份有锁；不是全 Spark 统一任务配额 | 每个来源阶段调用一次对齐流程；MFA内部CPU并行不等于多个生产 job，没有仓库统一的跨 job 数值上限 |
| L1 英文机器 judge | `gpt-6-astra`，独立工具默认 Medium，API | unified source 配置强制 `workers=1` | unified：1 worker、batchSize 1–15；standalone judge：允许1–8 workers，默认1、batch15 |
| L2 初译 | `gpt-6-astra` Medium；正式 API，测试 CLI 普通速度 | canonical controller 每个 run 最多1个 active locale job；unknown owner继续占位 | zh-Hans／ko／es policy均 workers=1、batchSize=1；controller允许组 worker 1–16；standalone CLI入口仅允许1–3 |
| L2 独立复核 | `gpt-6-sol` Medium；正式 API，CLI测试选Fast | 同一组必须先完成初译再复核；其他组可交错 | 与初译共用同一个组 worker预算，**不是初译16加复核16**；一个组 worker一次只做其中一个模型调用 |
| L2 CLI 测试入口 | Astra→Sol，ChatGPT认证 | test scope，无正式controller／candidate准入切换 | 固定 workers=1；共享底层组循环支持1–16，但入口不会放行多worker。本轮外部独立调用基准成功到24，不改变此限制 |
| L3 正式单讲员配音 | Qwen3-TTS，registry `Qwen/Qwen3-TTS-12Hz-1.7B-Base`，实际授权 speaker checkpoint | 一个renderer持job输出锁，父进程顺序验证／提交；pool在途窗口≤replicas | 新周日单讲员 `--spark-production`：8驻留副本×batch8；兼容默认1×1。正式renderer只允许replicas 1或8；batch 1／2／4／8 |
| L3 回转写筛查 | `Qwen/Qwen3-ASR-0.6B`，CUDA/BF16 | 单job按批次顺序筛查，缓存绑定音频／模型／文字身份 | 1个驻留模型，无多副本pool；正式默认batch1，可选1／2／4／8，Dev默认4 |
| L3 Mac legacy 模型资源 | 现有本地语音模型 | 使用同一 `SERMON_LOCAL_MODEL_LOCK_ROOT` 的调用共享准入槽，并检查可用内存 | slots仅允许1或2；≥48GiB总内存默认2，否则1；默认预留12GiB。它不控制云端CLI／API，也不能据此给Spark配额 |
| L4 构建／同步／发布 | 打包、hash、FFmpeg、HTTP、Firebase为确定性程序；legacy大纲／默想文字生成由reading Astra处理 | legacy page controller同run依赖阶段顺序派发；同Hosting site发布持远端lease，同snapshot有本地锁 | 独立构建／校验没有统一worker池数值；同site遵守lease的发布者最多1个。没有L4专属“24模型worker”配置 |

代码依据：

- [监督入口](../../scripts/run_sermon_production_supervisor_agent.py)：`parallel_tool_calls=False`、`--model`默认；[监督合同](../sermon-production-supervisor-agent.md)：串行mutation与scope；[legacy reading配置](../../scripts/sermon_production_supervisor.py)：Astra reading／interpretation。
- [unified source](../../scripts/sermon_unified_source.py)：judge配置、180秒ASR串行循环与输出锁；[standalone judge](../../scripts/judge_english_source_for_translation.py)：workers 1–8；[MFA路由](../../scripts/mfa_backend.py)、[Spark请求锁](../../scripts/mfa_spark.py)。
- [三语policy](../../config/target-language-policies/zh-Hans.json)（同目录ko／es相同模型及worker设置）、[L2 controller](../../scripts/canonical_layer2_controller.py)、[组循环及standalone入口](../../scripts/run_target_language_models.py)、[CLI测试入口](../../scripts/run_codex_layer2_test.py)。
- [TTS registry](../../config/speaker-voice-registry.json)、[正式renderer](../../scripts/render_formal_target_language_speech.py)、[窗口scheduler](../../scripts/spark_tts_window_scheduler.py)、[回转写ASR](../../scripts/screen_target_language_audio_units.py)、[Mac资源准入](../../scripts/sermon_model_resources.py)。
- [page controller](../../scripts/sermon_deterministic_controller.py)、[durable job锁](../../scripts/sermon_workflow_jobs.py)、[Hosting lease](../../scripts/guarded_hosting_publish.py)。

## 哪些是共享上限

| 预算 | 实际作用域 | 数值／状态 |
|---|---|---|
| L2付费API槽位 | 同主机、同job-root对应的邻接锁目录 | 24；每次网络调用持一个槽。不同job-root、其他层API调用不自动共享 |
| L2组worker | 每个locale job | 当前1，canonical允许16；同run只准入一个active locale，不是三语各16同时运行 |
| CLI会话 | 本次基准的外部进程池 | 测到24成功；仓库尚无跨层／跨run统一CLI semaphore，账号硬上限未知 |
| Spark GPU模型 | 每个renderer pool | 正式TTS pool8副本；不存在全Spark跨job总8副本的调度器。两个独立8副本job可能争用同GPU与内存 |
| 发布 | 同site，使用相同远端lease的publisher | 1；外部控制台发布不能由此lease完全阻止 |

因此，现有API的24并不是整个工程的全局24，CLI的24也不是各层可以分别开24。底层TTS pool API允许1–32 replicas，但正式入口仅1或8；底层接受参数不等于正式支持或硬件验证。8×8最多对应一个pool中的8个在途窗口、每窗8句，不是64个独立生产任务；多讲员不能套用单讲员preset。

## 长任务吞吐应怎样计算

对L2，设冻结英文有G组、组worker为W、共享可用调用槽为C、当前可执行组数为R：

`有效在途模型调用 ≤ min(W, C, R)`

每个组的依赖为 `Astra翻译 → 校验 → Sol复核 → 校验`。不同组可以交错，worker完成一组后领取下一组。模型服务速度稳定、长队列且忽略控制／写入开销时：

`单语言理想耗时 ≈ G × (平均翻译耗时 + 平均复核耗时) / W`

此前完整三分钟串行实测13组，Astra进程区间合计144.155秒、Sol Fast189.684秒，平均每组约25.68秒。这只能作为该片段的代理值；它包含CLI启动、认证、prefill与等待，而且并发会改变单调用耗时，不能当作整篇固定服务时间或纯生成速度。

当前三语policy W=1，所以单run当下最多一个L2模型调用；改到16仍是单locale最多16在途，不会因为模型角色有两个就变成32。三语的语言任务仍由controller依次准入，语言runtime独立扩容需要控制器及资源预算设计，不能只改worker字段。CLI正式接入也仍未完成。

上一轮16路的24任务完成31.54秒，24路完成30.15秒，测的是有限批次完成时间。24路末尾只剩慢任务时槽位空闲；这个尾部占比会随G增长下降。反过来，长期共享服务排队也可能随负载上升。因此，短批次无法确定长任务16／24谁的稳态吞吐更高。

## 按上周实际片段数量估算

采用2026-09-27已存工作量，而不是把三分钟13组直接当整篇数量。[可复算工作量](../../data/benchmarks/local-layer-latency/2026-10-01/weekly-20260927-projection.json)记录来源31:31.677、420英文锚点，中文419组、韩语420组、西语420组，共1259组／1259配音单元。成功版本的初译＋复核为2518次请求，不含此前返修、失败与废弃版本。这里沿用其**数量**，不沿用旧Qwen文字模型的耗时代理。

| 阶段 | 上周数量对应的工作量 | 并发分析 |
|---|---:|---|
| L1 source ASR | 按当前180秒切片规则需11块 | 当前单来源串行；CLI文字并发不能加速这些API ASR |
| L1 英文judge | batch15时28批；batch1时420批 | unified目前1 worker；standalone最多8。没有匹配CLI耗时，暂不报分钟数 |
| L2 初译→复核 | 1259组、2518次基础调用 | 三语任务数足以做长队列分析；同run语言仍依次准入 |
| L3 TTS | zh419／ko420／es420句；batch8每语53窗，共159窗 | 每语8副本时约7轮窗口，长短句负载不均；不是159个模型副本 |
| L3 back-ASR | batch1共1259批；batch4共315批；batch8共159批 | 一个驻留模型串行批处理，实际速度需匹配语言／音频长度测量 |
| L4 发布 | 三个locale包、同site发布 | 随文件／媒体大小变化，不能按1259次CLI调用估计 |

### L2 CLI时间代理

两个计算场景均使用上周419／420／420组，结果是**基础翻译与复核机器耗时代理，不是全流程完成时间或预测置信区间**。

- 场景A：完整三分钟串行实测的平均每组25.67993秒，在并发后保持不变，即理想线性扩容。
- 场景B：沿用16／24并发基准中实际单调用变慢的幅度。每轮含12次翻译、12次复核，所有进程区间之和除12，得到每组30.44163秒（16路）／36.74325秒（24路）；再按组数÷并发宽度外推。基准审核用冻结旧稿，并非新稿DAG，故仍是敏感度场景。

| 组worker／目标宽度 | 中文419组，场景A | 三语1259组，场景A | 三语，场景B | 当前入口支持情况 |
|---:|---:|---:|---:|---|
| 1 | 179.3分钟 | 538.9分钟（约9小时） | 未单列 | 当前三语policy及CLI测试入口 |
| 2 | 89.7分钟 | 269.4分钟 | 未单列 | API standalone／canonical允许 |
| 4 | 44.8分钟 | 134.7分钟 | 未单列 | API canonical允许，standalone不允许 |
| 8 | 22.4分钟 | 67.4分钟 | 未单列 | API canonical允许 |
| 16 | 11.2分钟 | 33.7分钟 | 39.9分钟 | API canonical允许；CLI正式dispatch未接入 |
| 24 | 7.5分钟 | 22.5分钟 | 32.1分钟 | CLI独立调用已测；canonical组worker上限需显式设计修改 |

同样的1259组，在场景A中24对16节省约33.3%，在场景B中节省约19.5%。这些数字说明**上周规模下24仍值得长队列验证**，不能从24项短批次只省4.39%推导长任务收益也只有4.39%。场景B不是服务端排队稳态测量，也不是预期下界／上界。

三分钟测试是39英文单元合成13组，平均每组3单元；上周420锚点对应419／420组，粒度不同，三语输出长度与修订率也不同。较小组可能降低输出时间，但整篇上下文、经文长句、缓存、服务端排队可能增加耗时。因此不能宣称16路必定34–40分钟、24路必定22–32分钟。这两个范围只是上述场景的简写；更可靠的下一轮应直接使用上周冻结组与上下文。

### L3与全流程边界

[中文Spark8×8组件报告](20261003-spark-production-8x8.zh.md)用上周419段中的64段长度分位样本，热运行中位56.8056秒；外推419段约6.2分钟，加cold load约7.1分钟。该已有估算不含ASR、组装、听审和发布。韩语／西语没有匹配的8×8组件速度；若仅为排程敏感度假设三语每句吞吐与中文相同，则1259句热合成约18.6分钟，三个独立cold load合计约21.4分钟，**不是三语实测预算**。

L1、L3 back-ASR、传输与L4缺少本轮匹配的完整耗时，不能把“L2约22–32分钟＋TTS约21分钟”称作整篇总时长。阶段是否可重叠还取决于批准包就绪、GPU准入和多语统一发布计划。监督Luna的token与时间另计，不按1259组×一次监督轮次推算；现有controller可以派发worker后等待，监督会话次数由状态变化决定。

## 下一轮分析与改进顺序

1. **先统一预算作用域**：为CLI建立跨run共享预算；GPU单独计量，发布继续site lease。24可作为下一轮测试目标，16仅是暂定候选值，未建立永久最优值。监督需要独立小预算／优先级，不能让大量翻译阻塞监控。
2. **再测试真实依赖和长队列**：用同一冻结输入、同一Astra→Sol DAG，分别测8／16／24，至少准备最大宽度10倍的就绪工作量，持续补充队列并记录暖机与稳定区间；任务不足时准确报告实际利用率。重复轮次、交错测试顺序，避免把时间段／缓存差异当并发收益。超过现有入口上限的方案先实现隔离测试dispatcher，不能偷偷绕过正式准入。
3. **记录能够解释瓶颈的指标**：分别记录controller排队、CLI进程区间、每角色token与耗时、峰值及平均在途数、组完成/分钟、输入／输出token/秒、p50/p95、错误／超时／未知结果。无服务端首token与生成时长时，generation TPS保持未知，不将进程区间TPS称作纯模型速度。
4. **GPU测量独立进行**：先核验单TTS job8×8，再测ASR是否可与TTS安全重叠。当前没有跨jobGPU准入；在重叠容量实测前，单个正式重TTS job是保守运行建议，不是现有代码全局硬限制。
5. **最后才调整正式配置**：CLI24调用成功、组循环能力、controller多worker准入、全层生产联跑各自需要证据。不要只把policy从1改24；当前validator会拒绝，且不会获得公平调度、恢复或资源隔离。

相关实测：[完整三分钟翻译→复核](20261005-codex-cli-layer2-180s.zh.md)、[独立CLI调用至24路](20261005-codex-cli-concurrency-24.zh.md)。本次未执行稳态复测，也未验证后台live容量。
