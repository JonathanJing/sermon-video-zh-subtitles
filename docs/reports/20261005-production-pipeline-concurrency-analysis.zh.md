# 降低整篇制作时间：模型并发与自动流水调度

2026-10-05。目标是降低从冻结来源到约定内容发布的关键路径，不是增加进程数。本次只分析与修正文档，不启动模型、不提高生产容量。数量基于上周9/27的420英文锚点、中文419／韩语420／西语420组；[数量和耗时代理](20261005-layer-model-control-worker-concurrency.zh.md)与[CLI至24路实测](20261005-codex-cli-concurrency-24.zh.md)分开记录。

## 结论

优先级是：**复用已完成工作与减少控制等待 → 有界扩大线上L2组并发 → 获批语言的本地TTS与下一语言线上L2重叠 → 补齐自动收据接续 → 再实验更细的音频流水线**。

CLI可以自动调度有依赖的下一步，只要依赖的收据、批准、资源与授权全部就绪。没有依赖的分支可以立即并行；有依赖不意味着每步都需要人工再次启动或监督模型重新选择命令。由一个持久owner执行固定DAG，Codex Luna监督异常、解释状态，Astra／Sol承担内容任务；确定性成功路径不必新增监督模型调用。

当前统一 `sermon` CLI／常驻owner仍是设计，现有canonical L2 adapter和legacy page controller是有限实现，不能称全四层自动流水已上线。

## 本地模型与线上模型分别怎样扩容

| 资源／角色 | 可行的提速 | 当前边界与代价 |
|---|---|---|
| 在线Astra／Sol：API或Codex CLI | 多组并发；某组翻译完成即进入该组审核，其他组继续翻译；同一全局预算内交错语言／任务 | 正式L2 API controller组上限16、同run一个active locale；policy当前1。CLI24是独立调用实测，正式controller接入和统一CLI预算未完成。API与CLI是不同传输／认证，模型仍在线，不消耗Spark TTS槽 |
| 在线source ASR／Astra judge | 已有legacy ASR工具支持workers1–8；独立judge支持1–8。可设计canonical切片／审核批有限并发 | unified source ASR串行、judge强制1；SourceBudget要求之前所有请求returned才能开始新请求，因此不能仅加线程。需版本化在途账本、原子预算预留、独立chunk身份、按序聚合与unknown对账 |
| Spark Qwen3-TTS | 一个正式job内部8驻留副本×batch8；复用原始音频；后续GPU窗口计算与已完成窗口的CPU处理重叠 | 已有8×8，不必另开第二个8副本job。8×8接近该组件GPU满载；16×4曾触发内存保护，无有效速度结果。跨jobGPU总配额缺失 |
| Spark Qwen3-ASR | 模型驻留，batch1／4／8比较，逐单元缓存，减少启动／加载 | 当前一个驻留模型、完整render后才screen；与8×8 TTS同时跑的容量没有验证。增加客户端线程不保证同GPU推理变快 |
| MFA／FFmpeg／hash／PDF／校验 | CPU池、有界队列；原声指纹与ASR并行；PDF与音频分支重叠 | MFA当前内部num_jobs2，不是两个来源job；canonical TTS已有GPU/CPU重叠，legacy CPU workers参数不能套给canonical。CPU仍受RAM、磁盘和媒体传输约束 |
| Mac本地模型fallback | 已配置资源槽1–2与内存预留；保持原job身份，已知基础设施故障后按策略恢复 | 不建议为并发主动把同一正式job拆成CUDA／MPS音频混合轨；当前canonical跨机dispatch并未统一接通 |
| 本地文字模型实验 | 后续单独比较质量与长队列吞吐 | Qwen文字代理不是当前正式Astra→Sol policy。不能用本地模型替换现行角色并据旧速度代理声称生产提速 |

线上共享预算应该按host/account/backend/runtime身份明确作用域，不能把“每层24”相加。已有API24槽只覆盖同job-root的L2请求，不能代称所有线上API或CLI的全局限额。CLI24候选预算与少量监督保留容量仍需实际设计／验证，账号最大容量未知。

## 哪些分支没有必要互相等待

以下“可以”是依赖分析；实现状态另列。无内容依赖的计算仍需要资源准入、冻结身份和原有授权。

| 可以重叠的工作 | 最早触发证据 | 实现状态／限制 |
|---|---|---|
| 来源指纹／媒体校验，与reference ASR | 原声hash、批准窗口冻结 | legacy `--fingerprint-precompute`已接线。指纹无需译文，最终绑定等真实音轨完成；canonical自动hook待接 |
| L2不同组的翻译→审核链 | 同一正式英文包、冻结policy、各组计划 | 组worker已实现。审核只等自己的翻译，不能先审核尚未返回的新稿；保留周边冻结英文上下文 |
| zh／ko／es文字分支 | 同一ready_for_translation英文包 | 内容审批独立，但当前L2 controller仍单active locale。跨语同run并行需要controller改造，不能复制job-root绕过 |
| 获批中文TTS，与韩／西线上L2 | 中文完整文字批准＋voice授权；其他语L2准入 | 四层合同允许，不需要三语文字都完成才启动第一语正式L3；统一跨层自动owner未完成。GPU与线上预算分开 |
| 某语言文字人审，与下一语言L2／已获批语言L3 | 完整机器候选、审核页／待审状态 | 人审是该语言的后继门，不是所有run的锁；仍遵守现有L2 runtime容量 |
| 大纲、默想生成，与同语言TTS | 该语批准文字／已验证源和学习产品输入 | 文本语义不依赖配音WAV；两种学习产品可独立生成／审核，不能因早完成而发布。统一协议已设计此分支，但独立学习产品审核schema未落地；当前页面outline收据还绑定音轨hash，需解耦而非伪造批准 |
| PDF渲染，与legacy中文配音 | 阅读稿与大纲均审完，v2 deferred-PDF job | 已有明确legacy并发合同；不是无条件提前在大纲审核前TTS。canonical App内容不应额外等待无关PDF |
| 当前窗口CPU保存／解码／hash，与后续TTS窗口 | 已返回窗口与其他在途窗口 | canonical scheduler已先refill再返回父进程，已有重叠；父进程提交仍有序，不把这项重复算成新的提速 |
| 音轨听审，与其他语言制作／页面骨架准备 | 完整可听轨、同期ASR／风险与同步证据按审核流程提供 | 完整整轨人审与ASR疑点裁决仍需记录；占用的是人的时间，其他独立语言机器任务可继续 |
| Dev／Beta独立准备与只读验证 | 相同已批准发布候选及各目标配置／授权 | 目标独立可重叠，写入同site仍持lease；生产晋级保留约定双端验收与发布计划 |

“上一语进L3、下一语继续L2”往往比“三语L2一起平均分槽”更早产出第一条可听音轨。在固定24槽中给三语各8，不会使总吞吐比总24再快3倍；反而可能让三语同时晚完成，延迟GPU启动与人审。建议优先完成第一语、其余公平轮转；选择顺序由release plan与审核者需要决定。

## 有依赖，但可以由CLI自动接续的步骤

| 前一步的收据／事件 | 自动下一步 | 必须检查的门禁 |
|---|---|---|
| ASR完整返回、不可变finals齐全 | MFA对齐→锚点→Astra英文judge→英文审核材料 | 媒体／窗口hash、预算、完整性；目前内部已有串行流程，不能在缺片时形成正式源 |
| 英文人工审核有效、Source Package ready | 准入L2 locale、提交组任务 | 固定policy／plugin／模型、同run容量、执行身份 |
| 一个Astra组返回并校验通过 | 同组Sol独立复核 | 同sourceUnitIds、coverage、payload／响应绑定；已有组循环 |
| 全组Sol／plugin／覆盖检查通过 | 汇总候选、生成全文审核页、推进下一语言L2 | 机器通过不等于人审；L2 unknown不能自动释放名额 |
| locale全文文字批准有效 | 准备正式speech job→排队TTS；并行学习产品准备 | 完整候选与独立人审同hash、checkpoint／音色／语言授权 |
| render完整manifest、整轨与单元全部有效 | 当前ASR screen→风险清单／听审资料 | 此命令现在要求完整轨，不能以partial目录调用 |
| ASR覆盖完整＋整轨听审／同步批准 | 构建Audio Package→该locale Release Package | 机器ASR疑点的人裁决、正式全文听审、完整绑定 |
| release plan要求的locale与学习产品全部齐全 | 构建／预检Dev与Beta候选 | join条件、页面字段批准、客户端能力、目标授权；无关PDF不加入App join |
| 授权目标部署完成 | HTTP／Range／资源读回→保存发布收据 | 部署未知先对账，不能自动重发；设备验收单独记录 |

正式L1源、完整locale文字批准、完整音轨和整轨听审、发布计划join都是真依赖。普通CLI可检查批准收据并继续，不能由模型替代人审、用上一阶段退出码代替产物校验，或把`waiting`改成`approved`。

## 两条值得开发、目前不能宣称接通的流水线

### 1. 待审文字的batch8预生成

现有preview需要**完整机器通过candidate**，然后才可按group选择合成。不是单组Sol回执一到即可调用的streaming工具。[正式复用函数](../../scripts/render_formal_target_language_speech.py)在`batchSize!=1`或spokenText存在时直接返回None。因此当前逐句preview不能减少正式8×8的合成工作量。

要提前消化人审等待，需新增与正式8×8完全一致的窗口、文字／上下文、checkpoint、seed、dtype／设备和代码身份，并实现preview→formal窗口准入与失败续跑。先做新版本与真实音频对照，再扩大计算。改文会使相应完整窗口失效；不要只删除batch保护。预生成只在空闲GPU和预期较高复用率下划算，不应抢已批准任务的GPU。

### 2. 单元TTS commit→ASR cache

当前screen要求所有单元和整轨manifest均完整。可新增独立的单元screening worker：消费已提交WAV、完整解码、文字／音频／模型hash，写不可变ASR结果；最后完整manifest只做全覆盖join。这个设计可以让CPU处理与ASR准备提前，不能直接把partial manifest交给现有正式screen。

TTS与ASR都在同一Spark GPU时未必更快：八副本TTS已经占大量UMA与GPU。先实施CPU／传输重叠、ASR批内驻留与缓存；再测降低TTS副本给ASR留资源是否降低整篇关键路径，比较纯TTS→ASR串行基线。单任务变慢可被重叠收益抵消，也可能完全没有收益，不能仅看并发数。

## 调度器的具体形态

```text
CLI提交一次冻结运行意图
  ↓
单一持久owner：收据事件／批准入库 → ready检查 → 原子资源预留 → dispatch
  ├─ 在线L2／学习产品队列：统一在途预算，监督小预算／优先级
  ├─ Spark队列：先一个重TTS job（内部8×8），ASR按可用容量排队
  ├─ CPU／I/O队列：指纹、解码、PDF、同步、hash、传输
  └─ 发布队列：按site lease与release plan汇合
worker完成 → 保存原始返回／产物与不可变收据 → owner验证 → 唤醒后继
```

任务至少绑定source/window、locale、policy/candidate、执行代码和checkpoint身份，父owner是唯一写运行状态的主体。worker拥有独立输出；共享资源锁作用域明确。一个owner串行处理状态转移并不意味着一次只允许一个业务worker。

ready节点自动接续，waiting仅订阅相关收据／低频健康校验；CLI客户端退出不应取消worker。人工批准到达后自动唤醒该语言，不再发送常规“继续吗”。Codex Luna处理异常、解释和复盘，不占用每个确定性转移的必经模型轮次。持久执行器与Codex CLI内容调用是两个不同组件；不是保持一个监督CLI进程开着就获得可靠DAG调度。

必须保留：先写dispatch intent、原子预算reservation、stateRevision/CAS、lease、heartbeat、unknown对账、drain换版本、缓存身份验证、结束scope。timeout不自动重发；取消后未知线上调用仍占reservation。需要复用[已有统一CLI设计](../unified-cli-pipeline.zh.md)和durable jobs，不再建另一套并存owner。

## 上周工作量下的时间收益方向

L2的两个耗时代理场景为16路三语约33.7／39.9分钟，24路约22.5／32.1分钟。现有正式入口尚不能执行24组worker；这是扩容后待测的方案，不是当下制作预算。

若仅用更保守的并发场景B，假设每语TTS约7.1分钟（只有中文组件证据，韩／西相同速度是未验证假设）、语言均能立即人审、忽略ASR／传输／发布：

| 调度情景 | 16路L2 | 24路L2 |
|---|---:|---:|
| 三语L2全部完成后才逐语TTS | 约61分钟 | 约53分钟 |
| 各语L2依次完成，获批即TTS，与后续L2重叠 | 约47分钟 | 约39分钟 |

算式分别是`三语L2总耗时+三语TTS总耗时`和（L2单语言长于TTS时）`三语L2总耗时+最后一语TTS尾部`。约14分钟差异只是消除两条不必要阶段等待的敏感度示例，不是实际已获收益；真实人审、ASR与GPU排队可改变关键路径。它说明先接好分支，不必靠增加Spark副本取得所有收益。

若三条交付轨均按来源31:31时长计，单人逐条完整听审约94.6分钟，实际以交付轨时长为准；增加模型worker不会缩短同一人的播放时间。最大实际收益常来自把人审等待与机器计算重叠、早交付第一语审核材料、局部修订不重跑全部、避免缓存重复计费；不能仅以模型token/s评价整个制作流程。

## 开发顺序与验收

1. **P0：持久owner与账本作用域**。补跨层ready、全局CLI／API与GPU预算、事件唤醒／人工收据入库、结束scope；先保证不重复dispatch和自动接续，再测速度。
2. **P1：正式L2 Codex transport接入与长队列验证**。保留Astra→Sol和plugin，分级8／16／24，在上周冻结输入测组/分钟、每角色排队、实际平均在途、p95、token与unknown。并发扩容与跨locale放行分开变更；优先测试单locale高并发和跨层交错，不先开三语各24。
3. **P1：获批语言L3与后续L2／学习产品重叠**。接正式门禁和GPU队列；解耦学习产品独立批准schema，不把当前音轨绑定的outline收据搬用成提前批准。
4. **P2：L1有限并发**。更新SourceBudget并发reservation／unknown语义与judge准入，legacy已有线程池不能证明canonical可并行；按实际L1关键路径决定投入。
5. **P2：batch8 preview复用、逐单元ASR cache**。分别版本化、质量与恢复对照，验证是否减少整篇时间及返工，而非只增加并发。

整篇验收记录从source-ready到各locale machine-ready、human-approved、audio-ready、listening-approved、各目标HTTP完成的墙钟，区分模型计算、queue、人审等待、CPU／I/O、传输。先测单因素，再联跑10分钟和整篇；真实质量／批准／设备证据仍分别保存。本次没有执行以上开发或新模型测试。

依据：[四层合同](../multilingual-production-interfaces.zh.md)、[层内解耦](../multilingual-intralayer-review-decoupling.zh.md)、[PDF／配音并发](../parallel-dubbing-contract.zh.md)、[当前提速实现](../local-production-speed-backlog.zh.md)、[SourceBudget](../../scripts/sermon_source_budget.py)、[legacy ASR与指纹](../../scripts/sermon_pipeline.py)、[L2 controller](../../scripts/canonical_layer2_controller.py)、[正式TTS](../../scripts/render_formal_target_language_speech.py)、[preview](../../scripts/render_speculative_target_language_speech.py)、[ASR screen](../../scripts/screen_target_language_audio_units.py)、[统一协议学习产品边界](../unified-cli-protocol.zh.md)。
