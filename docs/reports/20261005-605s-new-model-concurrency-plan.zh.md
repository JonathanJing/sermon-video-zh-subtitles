# PR #248：605.5 秒片段的新模型并发测试方案

核对基线：`17f7d026c0bb0aa183f75184599c573d0c2cb91a`，2026-10-05。本文交付代码审计及测试设计，真实并发实验 `not_run`；没有新增 CLI、API 或 GPU 模型调用，没有修改生产容量。

## 固定输入及模型

使用已准备的 `artifacts/next-iteration-repair-20261005/samples/drive-605s/`。母片窗口为 **63.32–668.820007 秒**，实际长 **605.500007 秒（10 分 5.5 秒）**，英文内容不截断句子；有 **136 个源锚点单元、114 个母片句子、46 个当前翻译组**。不是 136 个独立翻译任务，也不是已经准备好的正式音频 job。绝对母片窗口与相对片段时间线须同时冻结；目前没有独立裁出的 605 秒媒体文件。

采用[最新模型规范](../production-model-runtime-policy.zh.md)：初译及原 Astra 文字角色为 **GPT-6.1 Sol high fast**；独立复核为 **GPT-6.1 Sol medium fast**；监督为 **Codex GPT-6 Luna medium fast**。文字与监督使用 ChatGPT 认证 CLI，无自动 API fallback；新来源转录才使用 dev launcher 下的 `gpt-transcribe` API。旧模型及缓存身份保持原样。

这次应复用已验证的源包和锚点，测量从 `source_ready` 到诊断候选准入的机器耗时。另列冷启动、音频、同步及端到端耗时，不能把省去来源转录算成并发收益。新 Sol 6.1 medium 复核与 Luna medium CLI 尚无匹配实测速率，不能用旧 Sol 6 或 Agents API 的数字填补。

## 每一步当前能开多少

“当前”指此提交的实际入口，“试验”指完成对应适配后可比较的配置。资源单位、批大小、模型副本和业务 worker 分列，不能相乘为已支持的独立任务数。

| 步骤 | 当前实现与数量边界 | 本次试验配置／依赖 |
|---|---|---|
| Supervisor / owner | Luna 调用和有状态转移串行；canonical 每 run 最多 1 个 active locale，unknown 也占位 | 1 个监督；固定检查点。监督不应逐组批准机器任务，worker 可以在同一 locale 内并行 |
| L1 来源 ASR | canonical 180 秒分块后逐块执行：新跑此长度为 4 次请求，调用并发 1 | 首轮复用源包，新增 ASR 0。旧 pipeline 的默认 2／最多 8 不代表 canonical 支持 8 |
| L1 MFA | ASR 完成后一次对齐；内部 `num_jobs=2`，语料准备及媒体切块仍串行 | 复用锚点；若独测，固定 2 个内部 job，不与 CLI 并发档同时改变 |
| L1 英文纠错、复核、解释等 | 新文字模型已接 CLI；没有这份片段的多 worker 验收；bounded strict 入口缺 CLI 硬预算适配而阻断 | 保持已有源证据；不把模型迁移理解成所有 L1 分支已并行 |
| L2 初译→独立复核→语言插件 | canonical 组线程池 **1–16**；standalone **1–3**；当前诊断入口额外限制 **1**。每个 worker 持有一组，译后再审 | 补诊断能力后比较 **1 / 4 / 8 / 16**；**24** 需再扩组线程池、校验与能力版本。不是 16 译＋16 审同时运行 |
| L2 候选合并／准入 | 按源顺序合并；匹配全部组、规则及证据后准入。该 run 的状态写入仍受 lease 保护 | 1 个确定性合并／准入，不需要再调用监督模型代替程序校验 |
| L3 TTS | 正式 renderer 支持 **1 或 8 个 resident replicas**；8 副本必须 batch8。最终 candidate 每组一 WAV；Dev profile 强制 1 副本 | 若最终仍为 46 组：batch8 为 **6 个窗口**，同时有用窗口最多 6；仍加载 8 副本。单副本与 8×8 另做对比，不能从底层 pool 参数推导正式支持 24 副本 |
| L3 回转写 ASR | **1 个 resident 模型**，batch 允许 1/2/4/8；正式默认 1，Dev 默认 4，批循环串行 | 固定 1 模型、batch4；若 N=46，为 12 批。batch4 不是 4 个独立进程 |
| L3 同步／音轨组装 | 完整 WAV 实测后生成组级 schedule/cues 与整轨；不是另一套 MFA worker | 1 条有序组装；保留 delay/tail 门禁，单元过长不能靠增加 worker 修复 |
| 阅读稿、大纲、默想 | 新模型策略覆盖这些文字角色；同 run 当前 owner 仍逐 adapter 推进，多分支 DAG 未完整接入 | 可规划独立分支，但需先核对各自批准与输入绑定；本轮不宣称已与 TTS 自动重叠 |
| L4 构建／发布／HTTP | 同 broker publisher 容量最多 1，正式发布另有同 site lease 与快照锁 | 发布 1；设备／场地验收单列。构建 CPU 任务不能冒充已实现的发布并发 |

代码入口：[L2 线程池](../../scripts/run_target_language_models.py)、[诊断限制](../../scripts/codex_layer2_diagnostic.py)、[canonical controller](../../scripts/canonical_layer2_controller.py)、[source producer](../../scripts/sermon_unified_source.py)、[TTS job](../../scripts/prepare_target_language_speech_job.py)、[正式 renderer](../../scripts/render_formal_target_language_speech.py)、[回转写](../../scripts/screen_target_language_audio_units.py)、[broker](../../scripts/sermon_unified/resources.py)。

当前固定诊断音频脚本绑定 **39 源单元／13 组**，单模型 TTS batch2、ASR batch4；它会拒绝新长片段，不能先报 23 个 TTS 批／12 个 ASR 批已经可执行。须提供版本化、源窗口绑定的通用适配。上述 46 WAV / 6 窗 / 12 批均以最终候选仍有 46 组为条件；修订重新分组后从实际 job 重算。

GPU 方面，显式 shared broker 的重模型 job 容量为 1，诊断 TTS 与 ASR共用；一个 job 内可以含多个 TTS 副本。直接启动不同 render-root 的脚本不能保证都受该全局约束。当前 ASR 必须等完整 render manifest、全单元与整轨，尚无 TTS→ASR 按单元流水。CPU 容量 64 是 broker 资源单位上限，不是已经实现 64 worker。

## CLI 总量与监督预留

当前 L2 的 24 槽 semaphore 以 **job-root** 区分，不是账号全局池；canonical 默认 CLI 也未自动接入持久 broker，Supervisor 尚未共用这个池。因此“配置了 codex_cli=24”不等于所有入口已共同限流。失败退出后的进程锁释放也不能替代 unknown 的持久占位。

试验采用同一 host／backend 的持久总池，保留 unknown，并接入监督调用。建议有两个明确模式：

- **带监督运行：总池 24，监督预留 1，业务最多 23**；先测业务 1/4/8/16，末档 23。
- **纯 L2 24 路能力试验：业务 24，业务窗口内监督调用 0**；Luna 在窗口前后检查，单列耗时。不能另加第 25 路监督并称总量 24。

角色预留及等待队列是待实现能力。若 broker 满即返回 busy，必须由有界调度等待，不能把准入 busy 当作 provider 失败或自动重发。上述 24 是项目拟用容量，不是 OpenAI 公布的账号最大并发；[官方用量说明](https://learn.chatgpt.com/docs/pricing)按计划、任务及模型说明额度，不能据此承诺无限并发或 24×提速。

## 同工作量比较

每档固定 46 组，基础 **46 初译＋46 复核＝92 次 CLI 调用**；审核必须消费本档该组新生成的译文，插件与候选准入完整执行。失败后的修订另计，不拿旧译稿复核代替这条依赖链。

| 组 worker 档位 | 理想等时情况下的组链批次 `ceil(46/W)` | 这次的状态 |
|---:|---:|---|
| 1 | 46 | 当前诊断并发能力支持；样本的经文／术语门禁尚需补齐 |
| 4 | 12 | 待诊断入口和共享准入适配 |
| 8 | 6 | 同上 |
| 16 | 3 | canonical 线程池支持；诊断适配尚未完成 |
| 23（监督预留）／24（监督在窗口外） | 2 | 待扩上限与能力版本；46 组不足以证明长队列稳态吞吐 |

这是任务数推导，不是预测分钟数。单组仍是翻译后复核，长尾、启动、输入上下文、排队及 provider 负载都会改变收益。历史[24 路短任务测试](20261005-codex-cli-concurrency-24.zh.md)在同样 24 任务的 16→24 档仅约 **4.4%** wall 改善，且审核不消费同时新译稿；它只证明当时可以重叠启动 24 个 CLI，不构成本轮新模型完整链基线。

执行次序：先无模型 mock 验证 46 组依赖、在途上限、组顺序、unknown 占位与恢复；随后真实 1 档完整基线，4 档检查限流／质量，再测 8、16，条件满足后末档 23/24。各档使用独立 run 与响应缓存、相同源／分组／规则／模型／reasoning／fast／timeout，保持请求内容一致；只改变调度容量。第二轮反向或交错执行，记录 provider 缓存，避免把后跑档的缓存收益全归因于并发。

最高档 **23 或 24 二选一**，因此五档一轮基础 **460 次调用**，重复两轮 **920 次**，监督和返修另计；若两个最高档都测，六档为 **552 次／轮**、两轮 **1,104 次**。增加并发本身不减少 token，也不保证 credit 更少。记录实际 usage、cached input、输出和 reasoning token、冻结费率估算，额度实际扣减未知就保留 unknown。官方 Fast 的订阅用量／购入 credit 倍率是计费说明，不能当成速度倍率；详见[官方 Fast 说明](https://learn.chatgpt.com/docs/agent-configuration/speed)。

每档必须交付以下观测，而不是只有总 token/秒：

1. L2 与端到端 wall、组/分钟、相对 1 档加速比；各组初译／复核调用耗时 p50/p95、最大尾延迟，CLI 启动及准入等待尽可能单列。
2. 实际峰值与平均在途数、队列深度／等待、busy／限流、失败、unknown；请求开始／终止事件可回放。不用累加调用秒数冒充 wall。
3. 分角色输出 token/调用秒及全 run 输出 token/wall；监督单列。并发下后者是系统吞吐，不是单模型纯生成速度。保存[CLI JSON 用量事件](https://learn.chatgpt.com/docs/non-interactive-mode)。
4. 全 46 组译审覆盖、同组因果绑定、语言插件／候选准入；抽取固定术语、经文、长句做同标准盲评，不能只凭全部进程退出 0 判定质量相同。
5. L3 WAV 解码／覆盖、回转写与同步 delay/tail；若完整链阻断，分层 wall 仍可报告，但端到端完成为 false。人审、发布、HTTP、设备分别记录。

若升档后 wall 改善很小，而 p95、限流、unknown 或返修明显增加，不继续升档；依据重复结果选择最低的接近最佳档位。初译／复核并发改善只影响可并行的 L2 部分，其他层和人审仍会限制整体时间。

## 开跑前仍需补的内容

- 完整保留 `0-u067/0-u068` 的启示录 4:2–3；绑定 edition／quote parts／组映射及诊断术语 surface。当前 structural preflight 因经文阻断、0 次调用，不能跳过经文或制造正式人审。新诊断源没有正式人审批准；测试收据需明确 `productionEligible=false`。
- 版本化的 46 组诊断并发入口、共享 CLI 池与监督预留、满池等待及 unknown 恢复；之后才能证明 4/8/16/24 路真实链，而非用多个 run 绕过单 locale 限制。
- 605 秒本地音频通用适配及新媒体窗口身份；固定片段脚本不得仅替换组数或沿用三分钟媒体 hash。
- bounded strict L1/L2 仍缺 CLI provider token 硬上限／美元 reservation 适配；诊断试验不能宣称已跑通这一正式预算链。
- 最新提交的一个 [fresh-full-mock CI job](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/37368484694/job/111959392882) 已观察到 `invalid_strict_policy_schema`，发生于 fixture 冻结 policy、模型发送前；当前不能把最新 PR 称为全部检查通过。修复／核实基线后再验收新的并发入口。

完成后先用该片段挑选档位，再用完整母片或上周 419／420／420 组进行长队列复验；605 秒的 46 组不足以代替实际生产规模测试。关联[调度设计](../production-concurrency-scheduler-design.zh.md)、[测试缺口审计](20261005-pr248-test-coverage-backlog-audit.zh.md)及[长片段准备与实际短片段收据](20261005-cli-rule-chain-expanded-sample-retest.zh.md)。
