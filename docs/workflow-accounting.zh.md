# 周六流程日志、耗时、Token 与费用记录

自 2026-09-05 起，正式时间线、生成和配音入口自动记录本次执行。失败后续跑会追加新 `runId`，不会覆盖第一次失败的耗时和用量。原有生产 QA、审批及缓存判断保持独立。

每次本地周六流程必须持久保存各环节耗时、Token 与费用字段，包括失败、重试、缓存复用和未完成运行。无法取得的数值写为 `null`，同时说明缺失原因或计量不适用；不能省略字段或以 0 代替未知。这里的 log 包含结构化事件和可关联的业务证据文件，不能只依赖对话中的总结。费用完整性与产物质量分别判断。

## 查看记录

本地自动化入口、Supervisor、时间线与双 PDF 生成保存在 `<work-root>/<Sunday>/accounting/`；独立配音保存在 `<work>/accounting/`。独立运行 pipeline 或阅读／解读脚本时位于各自输出目录的 `accounting/`。由已记录的父流程调用时，子进程共享父目录与 `runId`，各自保留 `workflowId` 和 `parentWorkflowId`。

| 文件 | 内容 |
|---|---|
| `events.jsonl` | 追加写入的开始、结束、失败、缓存命中及逐次 API 用量收据；事实来源 |
| `summary.json` | 每次执行与各阶段汇总，保留缺失用量、未知费用和未结束阶段 |
| `stages.csv` | 可用 Excel 打开的逐次、逐阶段明细 |
| `operations.log` | 自动汇总时重建的可读事件列表，含运行、阶段、错误类型及项目内代码位置；实时查看以 `events.jsonl` 为准 |

先查看最近一次执行，命令不会重写文件、调用模型或读取远端：

```bash
.venv/bin/python scripts/sermon_logs.py artifacts/post-live-runs/YYYY-MM-DD/accounting

# 只看警告和错误；--run-id 也可传具体 runId 或 all
.venv/bin/python scripts/sermon_logs.py artifacts/post-live-runs/YYYY-MM-DD/accounting \
  --run-id latest --level WARNING --tail 30

# 给脚本读取的诊断结果
.venv/bin/python scripts/sermon_logs.py artifacts/post-live-runs/YYYY-MM-DD/accounting --json --check
```

`--check` 退出码：0 表示所选执行没有检测到错误／未结束记录；2 表示错误、未结束阶段／调用或账本损坏；3 表示账本不可读或找不到所选运行。API 重试中的失败也会保留并触发 2。`interrupted_or_running` 无法区分仍在运行与已被终止；它不是进程探活。账本完整性按整个文件检查，即使只筛选最近一次运行，旧损坏也不会被隐藏。这些检查均不代表业务 QA、人工批准或发布验收通过。

每次执行退出时自动汇总；进程被强制终止后，可只读事件、重新生成汇总：

```bash
.venv/bin/python scripts/sermon_accounting.py artifacts/post-live-runs/YYYY-MM-DD/accounting
```

若中断留下不完整的 JSONL 行，汇总保留其余有效事件，`ledgerIntegrity` 明确标记损坏行号、字节数、hash 和无法归属的未知费用，不抄录损坏正文。原始字节保留；下次追加先隔开未结束行，避免损坏后续运行记录。

合法 JSON 但缺少事件必需字段也归为损坏记录，避免一条坏记录让整个汇总崩溃。写入和读取使用文件锁；JSON／CSV／可读日志各自以临时文件原子替换。进程在多个文件替换之间中断时，这些派生文件可能来自不同快照，重新汇总即可；唯一事实来源仍是追加账本。

新建账本目录权限为 `0700`，新文件为 `0600`；已有原始文件和目录权限不自动修改。按周／任务目录隔离，默认不轮转删除账本，不清理历史失败或原始收据。生产目录位于 Git 忽略的 `artifacts/` 内。不要为排错把完整 `stdout`、环境变量或命令行重定向进这套结构化日志。

## 统一事件与错误追踪

`accounting_session` 管理运行身份，`stage` 管理阶段与父子 span，`record_log` 用固定事件 code 记录业务状态。新字段仍属于 v2 的可选扩展，既有 v1/v2 字节不改写。事件携带 UTC 时间、进程／线程 ID、运行／流程／阶段 ID；独立线程会话使用各自上下文，主线程启动的子进程通过环境变量继承关联。若从 worker 线程启动子进程，需要显式传递该 worker 的会话环境，不能假设主线程环境属于该 worker。

```python
from scripts.sermon_accounting import accounting_session, stage, record_log

with accounting_session(work / "accounting", "weekly_task", {"sunday": sunday}):
    with stage("validate_inputs"):
        validate_inputs()
    record_log("review.required", level="WARNING", fields={"status": "waiting"})
```

`record_log` 接受 `DEBUG/INFO/WARNING/ERROR/CRITICAL` 和固定机器 code；不接收自由正文 message。允许的字段是数字计数／耗时／HTTP 状态／退出码、布尔缓存标志、短状态／原因 code。元数据、请求设置也统一白名单过滤；不能以这些字段传入提示词、密码或用户正文。

异常只保留类型及最多 12 个项目内栈帧的文件、函数、行号，不保存异常 message、源码行、局部变量或第三方绝对路径。成功、失败、等待／阻塞的业务状态分别记录；CLI 非零返回不会变成成功 run。日志写入失败时不继续静默执行：无其他异常时抛出；已有业务异常时保留原异常并向 stderr 发出固定的 `SERMON_LOGGING_WRITE_FAILED` 提示。无论哪种失败都恢复会话／阶段上下文，避免污染下一次运行。日志写入故障也不会触发新的模型请求；已返回的响应不会因收据落盘失败而重复计费请求。

Supervisor 的 `Runner.run` 另记录 `sdk_call_started/finished`，保存 SDK 报告的请求数、输入／输出／总 Token 和整次调用耗时，位于 `runs[].sdkCalls`。该耗时含工具执行；SDK 聚合值不是原始逐 HTTP 收据，缺失值为 `null`，失败后拿不到用量也不补零。`httpAttemptsKnown=false`、`unpricedSdkInvocations` 和 `overallCostStatus=partial` 明确保留内部重试／费用缺口，不把它们混入直接 HTTP API 的次数、延迟分位数或已知费用小计。

记录覆盖元数据、下载、时间线 ASR 与分类、裁剪、分段、来源修订、翻译、两轮阅读审核、PDF、Context Pack、上传，以及配音传输、渲染、恢复、装配、对齐、ASR 筛查和时间预算。对话内额外模型审核、人工审听与手工操作无法由子进程计时器自动归属；若没有独立收据，报告必须明确列为未记录，不将整段对话时间或音频长度当作执行耗时。

## 已接入的指标与保留边界

本地入口现写入 `sermon-workflow-accounting-v2`：每个子流程都有独立 `workflowId`、状态、起止时间、执行代码身份、开始／结束资源快照，以及运行前后的业务证据摘要。汇总器仍可读取原有 v1 事件；旧事件不改写，也不会凭新字段补造历史值。

证据采集仅查看已知相对路径，记录 JSON 文件 hash 和白名单字段；不遍历任意目录、不读取报告指向的任意外部文件、不抄录机器中文。`currentRunExecutionProven=false` 表明这些是现存文件快照；本次是否执行、复用或失败，以对应阶段事件为准。

| 类别 | 需要记录的内容 | 用途与当前边界 |
|---|---|---|
| 执行身份 | 周次、来源 ID／hash、日期、`runId`、子流程／阶段／调用 ID、父子关系、恢复证据 | 已关联来源、审批、任务和运行报告摘要；讲题、讲员全文及 URL 留在原业务报告，用路径与 hash 查阅。跨次恢复不猜测因果关系 |
| 可复现版本 | Git commit、已跟踪文件修改标志、已加载项目 Python 文件 hash、Python／平台、模型、reasoning effort、请求 payload hash、声音检查点 hash | 本地代码身份与请求设置已记录；未导入模块、远程代码和训练环境仍以各自收据为准。请求仅保存摘要，不保存正文或密钥 |
| 输入与工作量 | 音视频 hash／时长、已批准起止点、段数、字符数、批数、并发数、预期／已有／新生成／修订复用单元数 | 翻译、阅读和配音已接入工作量事件；配音仅按有效收据核算。新增文件数不能代替模型实际批输入数，旧报告未保存的批输入数为 `null` |
| 速度与资源 | 阶段／API 延迟、重试退避、传输、延迟 p50／p95 与样本数、进程内存高水位／CPU 计数、磁盘余量 | 已接入上述本地指标；RSS 是进程生命周期高水位，子进程 CPU 只含已结束子进程。GPU 峰值为 `null` 并说明不可用；历史 TTS 时间注明模型加载后口径。进程外等待、远程模型加载和统一音频处理倍率仍需专门收据 |
| 失败与恢复 | 脱敏错误类别、HTTP 状态、发生阶段、逐次尝试、退避、被中断请求、缓存命中、业务阻塞 | 已记录失败／完成 API 数和未结束调用；无结束收据的调用保持费用未知。详细退出码和缓存失效原因以已有业务收据为准，不记录异常响应全文 |
| 内容质量 | ASR 覆盖、空译／缺段／ID 错配／时间重叠计数；阅读两轮修改数量与未解决问题；PDF 页数、文字 QA 和视觉检查状态 | 对每项结果保留检测方法、工具版本、样本范围及证据 hash。没有参考稿时不把 ASR 自评分当作真实准确率 |
| 配音与同步 | 自然／同步音轨时长、超时段数与最大超时、播放位置调整、漏读／重复的筛查疑问、解码／波形核验、待听审清单 | ASR 文字差异、模型复核与实际听到的错误分开记录；时间预算通过不能替代视频播放听审 |
| 审批与交付 | 人工／模型审核类型、审核对象 hash、时间与范围；PDF／音频／Context Pack 证据路径和 hash、过期／同篇确认／降级原因、发布状态 | 已关联业务报告快照，包括实际 `pipeline/sunday-context` 四文件；文件存在不代表本次批准、发布或远端仍可用 |
| 账目完整性 | 预计／已完成工作单元、已取得 usage 的响应数、缺用量／价格／延迟的数量、费用已知小计、未分摊项目 | 已记录 `usageReceipts`／`usageReceiptCoverage`；完整输入输出 Token 或计费音频秒数算有效 usage，未结束调用也计入分母。Token 字段缺失与总 usage 覆盖分开判断 |

每次完成或停止时，摘要应能回答：本次处理了哪个来源、执行到哪里、花了多少时间、已知 Token 和费用是多少、缺哪些计量、生成了哪些产物、还有什么阻塞。失败运行也生成摘要。输出日志只追加，汇总可以重建；旧收据和有效恢复材料继续保留，不因成功续跑而覆盖。

日志不应保存 API key、cookies、完整授权头、Secret Manager 的返回值、未脱敏错误正文、重复的长篇转写或逐 Token 流。大型音频、提示词、模型响应和审核内容保存在既有受控产物目录，日志用路径与 hash 关联。日志精度应足以解释一次运行，不为常规周六生产开启高频系统采样。

## 计时与用量口径

- 每个阶段保存独立开始／结束、实际经过秒数、失败状态、父阶段和缓存标记。API 每次尝试保存调用时间与结果；包括将来未能通过内容 QA 的已完成响应。
- 同一周多次运行分别保留。父阶段包含子阶段，API 并行调用也可能重叠，因此不能把全部阶段或 API 延迟相加当作端到端耗时。`runs[].wallSeconds` 是该次程序执行的墙钟时间；等待操作员及进程外审核不在其中。
- 分开保留输入、输出、缓存读取、缓存写入、推理 Token。推理 Token 已包含于输出 Token，不额外计费。缺失的字段为 `null`，并记录覆盖缺口；`known_subtotal` 只表示已知部分。
- 每个真实 HTTP 尝试记一次；同一 provider `responseId` 的重复记录不会重复计费。本地文件缓存命中只记录核验耗时，不把旧响应重新记为新调用。失败请求的实际计费可能未知，已知小计不会把它默认为免费。
- GPT-Transcribe 返回的 `usage.seconds` 是计费音频时长，不是调用耗时。自有 Mac／Spark 模型的 API Token 计费不适用；本地生成的音频秒数也不是执行秒数。
- 日志仅保留模型、响应 ID、数值用量与状态，不记录密钥、请求正文、转写内容、完整命令或异常响应正文。

## 费用口径

费用为美元 API 公开价估算，保存模型、处理档位、价格核实日期和来源；不是账户账单。当前价格快照核实于 2026-09-05，新增／改价模型须重新核实并更新。未核实的模型、处理档位或不完整的缓存用量不估价。地区附加费、协议优惠、税、电力、硬件折旧、云存储／流量及对话内 Codex 费用未分摊。

当前 Astra 标准短上下文每百万 Token：普通输入 $10、缓存读取 $1、缓存写入 $12.50、输出 $50。费用公式为 `(input − cached − cache_write) × 输入单价 + cached × 缓存读取单价 + cache_write × 缓存写入单价 + output × 输出单价`，再除以一百万。Astra 超过 272K 输入 Token 时及 Fast／Batch／Flex 档位按对应倍率记录。依据：[官方价格](https://developers.openai.com/api/docs/pricing)、[缓存计价公式](https://developers.openai.com/api/docs/guides/prompt-caching)、[Astra 模型计价说明](https://developers.openai.com/api/docs/models/gpt-6-astra)。

`knownEstimatedUsd` 是有收据、能估价的 API 小计；必须同时查看 `unknownCostAttempts`、`usageMissingAttempts`、`missingTokenFields` 和阶段 `billing`。不能仅因小计为 0 就宣称整次流程免费，也不能用 API Token 单价替 Codex 订阅或对话额度生成账单。

## 本次历史验证补录

`artifacts/saturday-validation/2026-09-05-aug30-astra/accounting-history-audit.json` 保存本次 8 月 30 日视频验证的逐项证据与缺口；同目录 `accounting-report.json`、`accounting-report.md`、`accounting-stages.csv` 给出可读汇总和价格快照。

114 条新翻译／阅读缓存只保留了解析后文本，无法恢复旧 Token、请求重试数和独立延迟；没有重新调用模型来“补齐”账目。已保存的证道解读原始响应单独计入已知小计。旧 ASR、旧模型缓存和同一失败报告的副本均不重复计费。原报告里相同的 core 耗时被填入三个阶段、PDF QA 耗时又包含两份 PDF 的时间，本次补录均显式去重，原始证据保留不改。
