# Codex CLI 并发测试至 24 路与各层容量审计

2026-10-05，按操作者要求扩展至 24 个独立 CLI 调用。结果：**本账号／客户端在本轮短任务中成功承载24路，24/24通过；1、2、4、8、16路也全部通过。** 这证明已测试到24，不证明账号最大并发数，更不证明每个Layer可以同时执行24个正式生产任务。

## 真实测试设置

CLI 为 `0.159.0-alpha.12.1`，ChatGPT 登录，移除 API key 环境，无 API fallback；复用 PR 中的 [Codex transport](../../scripts/codex_layer2_transport.py)。业务输入取自已冻结三分钟样本的前四组：每组一项 Astra 普通速度翻译、一项 Sol Fast 独立审核，共8种调用输入；均 medium 推理。审核消费冻结的旧候选译文，而不是本轮同时执行、尚未完成的翻译结果。这些是独立测试任务，不能据此将同一正式group的翻译→审核依赖改为并行。

1/2/4/8宽度每轮执行相同8项任务；16/24宽度每轮执行同样24项任务，即原8项业务输入各3个独立副本。副本的job、输出目录和thread ID独立，但不是24篇不同内容。两组实验总共80次新在线CLI调用，不复用生成缓存；provider缓存输入照实记录。四轮小宽度和两轮大宽度按顺序执行，不能用任务数不同的批次墙钟直接比较加速。

并发由进程外 ThreadPoolExecutor 限定；每项任务调用一个独立 `codex exec --ephemeral` 进程、临时cwd、schema和输出文件。每项保存自己的accounting、raw、result，transport日志另用UUID隔离。检查CLI完成回执、无工具、schema、group/unit身份、coverage及机器复核；统计主机monotonic任务区间的重叠峰值。峰值证明同时在途的任务，不是服务端实际GPU同时推理数或排队深度。

## 结果

| 并发宽度 | 固定任务数 | 成功 | 主机任务峰值 | 批次墙钟秒 | 单任务中位秒 | 单任务最大秒 |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 8 | 8/8 | 1 | 105.09 | 13.25 | 18.05 |
| 2 | 8 | 8/8 | 2 | 51.21 | 11.50 | 16.22 |
| 4 | 8 | 8/8 | 4 | 35.30 | 13.55 | 22.48 |
| 8 | 8 | 8/8 | 8 | 21.81 | 14.64 | 21.81 |
| 16 | 24 | 24/24 | 16 | 31.54 | 15.69 | 22.03 |
| 24 | 24 | 24/24 | 24 | 30.15 | 18.68 | 30.15 |

16→24宽度：批次墙钟减少 4.39%，单任务中位耗时增加 19.03%，最大耗时增加 36.88%。本轮24路没有明显的批次收益，尾延迟上升；短样本和不同输出、CLI上下文／provider缓存命中会影响数字，不能据一次测试定永久最优宽度或说所有任务都会如此。

80个thread ID全部不同，80条accounting完成观察均成功。没有显式限流／429错误，也没有超时、终态失败或语义校验失败；这不排除服务端排队。CLI stderr 的历史state DB查找警告另行保留，没有被当成模型失败。

本轮共输入 1,407,988 token（缓存 742,912），输出 42,144 token。业务payload固定不保证CLI代理上下文和token数逐次完全相同。调用耗时包括启动、认证、prefill、排队及等待；没有纯生成时间，generation TPS为null。服务端实际模型和速度档位未另行返回，账号并发limit也未返回；未用token推算订阅额度扣减或费用。

## 每层的真实限制

| 层／范围 | 当前代码能力与边界 |
|---|---|
| L1 英文来源与锚点 | 未接入全局CLI scheduler；独立机器审计可以设计成并行，但本轮没有实际跑L1 producer。来源／输出锁、上游批准和本地ASR/对齐资源仍各自有效，不能给所有L1工具一个统一数字。 |
| L2 CLI transport | 本轮测试24个独立调用成功；正式入口/controller尚未切换CLI。三分钟test entry仍强制workers=1，没有在本轮改成24。 |
| L2 standalone runner | 冻结policy允许1–3组workers。 |
| L2 canonical controller | 每个run最多一个active locale job，uncertain继续占位；当前组workers代码为1–16。不同run/job可分别准入，但必须各自满足来源／策略／锁和预算；本轮未跑多个真实controller。 |
| L2 API共享槽 | `MAX_IN_FLIGHT_API_CALLS=24`，按相同job-root的邻接锁目录共享。不是所有job-root或Codex账号的统一限额，不能拿它作为CLI的已知上限。 |
| L3 正式TTS／同步 | Spark新单讲员TTS是8驻留副本×batch8，同pool按其window容量调度；不是64个独立CLI任务，也不允许任意24个GPU生产任务。Mac本地模型slot为1或2且受内存保护。文本诊断和监督可使用CLI，但本轮未测试TTS。 |
| L4 构建与发布 | 独立prepare／只读校验可按资源并行；同一Hosting site发布持远端lease，同snapshot还有本地锁。同site发布仍串行，不能用CLI24路绕过发布保护。本轮没有构建或发布。 |
| Supervisor | 同run依赖状态转换／mutation串行；只读独立审计可并发。现有Agents supervisor禁用parallel tool calls，不等同禁止独立CLI进程。 |

代码依据：[standalone/组循环](../../scripts/run_target_language_models.py)、[CLI测试入口](../../scripts/run_codex_layer2_test.py)、[controller](../../scripts/canonical_layer2_controller.py)、[API槽位](../../scripts/layer2_api_concurrency.py)、[本地模型slots](../../scripts/sermon_model_resources.py)、[Spark窗口scheduler](../../scripts/spark_tts_window_scheduler.py)、[发布lease](../../scripts/guarded_hosting_publish.py)、[监督合同](../sermon-production-supervisor-agent.md)。发现controller文档仍写1–3，已按实际controller代码修正为1–16，同时保留standalone的1–3限制；没有修改运行容量。

## 建议与尚未实现部分

建议后续实现**跨Layer、跨run共享的CLI在途预算**，将24作为长队列复测目标，监督另设小预算／优先级。此前“日常先用16个工作槽”仅是暂定工程建议；每轮24项短任务不足以确定整篇最优宽度。操作者要求按上周实际419／420／420组分析，详见[各层模型、control、worker与上周工作量估算](20261005-layer-model-control-worker-concurrency.zh.md)。共享预算尚未部署；不是每层各24、叠加为96，也不是账号官方限额。不同独立任务可交错使用，某组的审核必须等其翻译完成，上下游阶段必须消费匹配且已获准的包。TTS使用独立GPU预算，发布使用site lease，CLI槽位只覆盖模型会话。

共享dispatcher需覆盖排队、公平调度、唯一输出/运行身份、失败/未知结果对账和取消，不用重复启动代替恢复。遇到明确限流时停止新增dispatch并降低在途宽度，不重发结果未知的任务、不转付费API。当前transport和test entry没有跨进程统一CLI semaphore；直接在各层各开24进程会超出这个建议预算。

官方 [长任务说明](https://learn.chatgpt.com/docs/long-running-work)建议独立任务分别并行，避免共享写入同一来源；[子Agent说明](https://learn.chatgpt.com/docs/agent-configuration/subagents)的 `agents.max_concurrent_threads_per_session` 限制单session内spawned agents，不是此次多个外部 `codex exec` 进程的账号并发上限。所读资料和本轮回执未建立一个账号硬上限，故结论是“至少测试成功到24路”，不能写“最多只能24”。

## 证据与验收范围

Ignored产物：`artifacts/codex-cli-concurrency-20261005/`（1/2/4/8）及 `artifacts/codex-cli-concurrency-24-20261005/`（16/24）。包括 frozen inputs、context、run.py、每任务accounting/raw/result、transport CLI日志、summary和 `combined-validation.json`。没有秘密、原始返回或片段文本入Git。单轮脚本不能在原目录重跑覆盖回执；复测需要新目录与输入身份。

本次只验证CLI模型调用并发和各层现有代码限制；没有Layer1/3/4正式生产执行、controller多run联跑、24组端到端翻译→复核DAG、长期压力或人工内容批准。上一轮完整三分钟13组顺序DAG验证见 [流程实测](20261005-codex-cli-layer2-180s.zh.md)。本轮不改生产容量或凭据。
