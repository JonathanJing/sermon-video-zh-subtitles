# Dev 三分钟诊断修复与监督验收

用户授权按既定计划持续推进：先测试第一批修复，再完成诊断 backlog 的产品实现，最后从新 ASR 跑到 Dev 发布及 HTTP/浏览器验收。允许放宽测试额度；新阶段仍显式冻结预算、身份和期限。测试人工门禁默认通过只记为 diagnostic simulation，正式人审、设备和现场状态独立记录。

## 第一批真实模型验收

固定代码 `a63e5bed2f7293944b1e201590bfc80072192211`，独立新运行 `artifacts/dev-contract-live-20261001`；原三分钟源和对齐保持 hash 核验后的复用。每语言使用前三个英文单元组成一组，普通 registerRules 和完整术语表范围，不使用原私有 JSON/术语 passthrough 补丁。

| 内容语言 | Astra 初译 / Sol 独立审核 | 语言插件 | 整 locale admission / 正式人审 |
|---|---|---|---|
| zh-Hans | `machine_review_passed` / `strict_review_passed` | pass | not_run / pending |
| ko | `machine_review_passed` / `strict_review_passed` | pass | not_run / pending |
| es | `machine_review_passed` / `strict_review_passed` | pass | not_run / pending |

新增六次真实返回请求，未知调用为空；worst-case reservation 为 **1,003,632 microUSD**，不是账单金额。冻结 config SHA `039d7aeddf57490f6f892515e526b6c5e3d6f7bcc7e11b739078b04b97f447d8`，18 request / 6,000,000 microUSD / 3,600 秒上限。第二次执行新增请求 **0**，三语 candidate revision SHA 与首次完全相同。收据、模型返回、D5、插件回执与两次日志保存在该 ignored 目录；不改旧账本，不将小样本提升为全三语验收。

这支持 `DEV-DIAG-001/011/012` 的普通输入单组解阻；原 HTTP400 缺失的供应商 error body 仍不能事后补写。39 组与整个三分钟流程留待本计划最后阶段。

## 后续实现与验收边界

| Backlog | 实现方向 | 还需实际证明 |
|---|---|---|
| 002/003 | 网络 worker 保留安全 code/param；版本化拒绝诊断；同锁配置范围止损与明确恢复 | 结构化失败矩阵、无额外派发、旧收据兼容 |
| 004 | 单 session / 单 root turn 的只读诊断、持久 intent/checkpoint、输出身份核验 | 一次真实 Agents 诊断；观察阈值不冒充服务端美元硬限额 |
| 005/008 | fresh Source adapter、实际上下游 leaf、worker 四事实时钟握手、Dev 候选 | 完整 live DAG、Dev 发布与 HTTP/浏览器证据；缺测保留 partial |
| 006 | 终态父运行绑定的新 attempt，累计授权、旧期限和旧账本保持不变 | 过期/unknown/父证据漂移测试；实际新阶段使用协议 |
| 009 | failed / blocked / pending / ready 与当前 locale/input 绑定，候选缺失不暗示可播 | 三语切换、失败页面与既有周次浏览器验证 |
| 010 | 进入新阶段前不可变声明允许新增模块和外部 runtime；严格身份扩展收据 | 禁止后补声明、改源码、改预算、改输入、旧 runtime 漂移 |
| 013 | returned/rejected/unknown/validation/plugin 分流，review 字段/枚举安全细分 | 无效响应和重启/篡改夹具，不重付失败缓存 |
| 014 | 独立冻结 Qwen runtime，25Hz 模块延迟 sox 导入，原 shell/network guard 保持 | 原生 guarded import、实际模型加载、三语单元推理及完整 WAV 解码 |
| 007 | 保留测试交付与正式门禁界线 | 回转写、疑点裁决、整轨听审、同步、正式包、设备/现场分别验收 |

实施状态和新验收结果随监督流程更新。上述表是执行计划，不是未执行项目的通过证明。

## 整合检查记录

- 006/010 与既有 bounded/continuation 入口：25 tests 通过；新增模块必须预先声明，不允许加载后补授权。
- clock/report/native worker/delivery/renderer/Agents 合同整合：126 tests 通过。
- 页面状态、catalog 与 i18n：28 Node tests 通过。
- 实际 App 在本地 Chrome DOM 中加载固定诊断夹具：zh-Hans failed、ko blocked、es pending 均禁用播放/大纲入口，无音频 src，不显示“大纲已就绪”或“配音准备中”；切回既有周次保留原大纲行为，page errors 为 0。该结果是 `synthetic_browser_real_app`，不是已部署 Dev 的真实产物验收。证据在 `artifacts/dev-ui-acceptance-20261001/browser-results.json`。
- 原 shell/network guard 下 Qwen 真实导入 smoke 通过：sox 未导入、模型未构造/加载、provider calls 0。独立 runtime v2 manifest SHA `5dc0f1968d96fc5a1c4ccbb09e70dcf12b4141d7d174d8d1b75e5abf878eee80`，runtime tree SHA `d24f4e7523464d7e5d29cd89bb48f0f96239759b518b8f247924b81a09e6b3e6`。模型推理另验。

预算恢复复核发现完整祖先计数、同一授权重复使用及父运行仍可派发三个边界，已补齐 v2 协议：固定新目录和 run、完整祖先 closure、父快照唯一后继、同锁永久关闭新派发；旧缓存可读。历史 A 的 provider 124 次调用已知 returned/rejected，但 D5 42 项未结算；保持原账本状态，不猜测结算、不退款。只读历史 observation 完整承接 A、v8、v9 和第一批，共 299 次请求、69,123,991 microUSD 最坏占额；A 未结算按原 $40 上界承接。v7 无初始化预算/provider，原 plan/hash 作为明确空尝试保留。baseline canonical SHA `3a2090d7d7afaa2b666b118316ef90a79663ddfd7a6659ad77c4be8e13b965e7`；新 fresh 测试不能假称旧未结算项已恢复。

最终整合回归覆盖 29 个受影响测试模块，**417 tests 通过，1 项既有 SDK 集成测试跳过**；28 Node tests 通过，`git diff --check` 通过。故障注入夹具输出的 `SERMON_LOGGING_WRITE_FAILED` 是预期拒绝路径，其终态与不重复派发由测试验证。

下一真实阶段冻结为 fresh 独立 attempt：bounded provider 最多 124 次新请求、25,000,000 microUSD、5,400 秒；完整历史累计请求上限 430、占额上限 110,000,000 microUSD。只读 Agent 另限单 session / 单 root turn，最多 8 steps / 16 metadata reads / 30 秒、2,000,000 microUSD 观察预留；其金额是 observer stop threshold，不能称服务端硬封顶。对应预算、代码、源与 runtime 在 ignored 运行目录持久化后执行。

## 真实启动暴露的兼容问题

固定 `8305b2e` 的 fresh 启动已保存两个派发前失败：原生 runtime 没有 `dotenv`，启动器改用匿名继承 FD 传递既有私有凭据，保留原 driver/input/plan hash，未改冻结 runtime；随后 `profile.session` 延迟加载 `sermon_workflow_evidence.py`，入口预加载遗漏该模块，引发 `diagnostic_continuation_code_changed`。两次都没有 provider 请求。失败 attempt 已初始化空账本并永久关闭新派发，0 requests / 0 reservation；继承该父 attempt 准备修复后的新运行，不重用已消耗的后继授权或覆盖旧计划。

真实只读 Agent 已创建一个 session/root turn，但合法 opaque function call ID 被本地 `call_` 固定前缀断言拒绝，未产出诊断。三个额外只读 GET 已确认 session idle / root turn cancelled，required actions 为空；根 turn 报告 input 9,796 / output 147 / total 9,943 tokens。session 汇总与之相同，不能再相加；GET 未报告 actual model，费用仍 unknown，原 2,000,000 microUSD 观察预留不退款。新阶段只能在保留旧账和明确独立授权/观察期限后执行。私有脱敏回读收据在 `artifacts/dev-agent-diagnostic-live-20261001/reconciliation`。

上述入口冻结遗漏归入 `DEV-DIAG-005/010`，opaque call 标识兼容归入 `DEV-DIAG-004`，凭据 FD 启动与原生依赖边界归入 `DEV-DIAG-014`；均需修复回归及真实续验，不因 GET 或零调用失败记为通过。

启动兼容修复整合 **77 tests 通过**：fresh 的冷进程真实日志身份回归，以及 Agent opaque call ID、唯一 function-call item／turn／name／arguments 绑定和错配拒绝。session/turn 身份约束不变；工具结果 POST 前增加实际 item 证据核验。`git diff --check` 通过。

只读审查新增待验边界：fresh Source 捕获部分非 `fresh_*` 受控错误时仍泛化原因，归 `013`；变化 ASR 的本地 MFA 分支尚未透传原 provider 剩余 deadline，归 `005`；native checkpoint 回执绑定主权重/config，辅助 tokenizer 权重全树绑定尚缺，归 `014/010`。这些审查发现不作为已通过或已观察故障，保留验收要求。

## 第二轮真实结果与修复

固定 `e9d1ad7` 的 v2 fresh 已实际返回 ASR 和英文检查两次请求，无未知；占额 **474,113 microUSD**。新 ASR 规范化后与原 ASR 完全一致，可继续核验复用 MFA。Source 准备失败的准确原因是旧对齐文件 **616,744 字节**被 private review 的 262,144 字节 reader 拒绝；现仅对齐文件改用既有 16 MiB aggregate 稳定读写，保留 review/receipt 上限。真实旧对齐经实际 Anchor/English Source builder 产生 39 units，媒体 SHA 保持、translationEligible=false、不可变重放通过；该定向检查没有 API 请求。v2 父运行在两请求 known-returned 后永久关闭，旧计划、收据和账本未覆写。

HTTP worker 的真实 `-I` 启动遗漏 `-B`，忽略环境中的禁止字节码设置，生成唯一 `_distutils_hack` pyc，导致 native runtime inventory 拒绝。启动与对应 subprocess 守卫同时加 `-B`，环境仍为空，shell/network 约束不变。25 项定向测试包括独立 venv 的实际 `.pth` 导入对照；原 runtime 唯一派生缓存已精确副本隔离后移出，原 manifest/inventory 校验恢复。真实 native HTTP worker 空 packet 的零请求 probe 不生成缓存，但 `outcome_unknown` 不能当业务成功。隔离与恢复收据在 `artifacts/native-runtime-cache-quarantine-20261001-provider-no-bytecode-v1`。

第二个只读 Agent session 仍未产出诊断：额外要求 items 已存在 pending function_call 的断言失败。真实 required_actions 有调用，而取消后的完整 items 只有 user message/reasoning，不能推断列表当时已同步。该前提不能用作 API 可用性条件；提交仍须绑定实际 session.required_actions 和唯一实际 root turn、call/name/arguments，并落版本化证据。v2 终态 cancelled；root usage 9,791 input / 291 output，两阶段各累计一次为 **19,587 input / 438 output**，actual model 和费用仍 unknown，4,000,000 microUSD 预留保留。第三独立 bounded 诊断阶段累计预留为 6,000,000 microUSD，仍承接完整业务累计授权内。

第二轮修复整合验证：provider/bounded/fresh/aggregate/attempts/identity 的 **94 tests 通过**；Agent core/live/API 的 **84 tests 通过**，覆盖 required_actions 唯一调用、同 poll 根 turn/snapshot、缺失／重复／参数错配／陈旧响应和工具输出错配拒绝。绑定证据使用 `sermon-live-diagnostic-required-action-binding-v2`，不改写旧 item-binding-v1。下一 fresh 独立 attempt 承接 **301 请求 / 69,598,104 microUSD** 历史占额，124 新请求 / 25,000,000 microUSD / 5,400 秒，累计 430 请求 / 110,000,000 microUSD；额外 Agent 三阶段共 6,000,000 microUSD 观察预留纳入累计规划，不是服务端硬费用限制。

## 第三轮 Source 成功与恢复边界

固定 `a0769fc` 的 v3 实际返回两次 provider 请求，占额 **474,100 microUSD**。本次 ASR 与原文本不同，执行了真实本地 MFA；`diagnostic.alignment` 和 `diagnostic.source_package` 均完成，39 English units、Source 真实 humanApproval=false / translationEligible=false，保留一条受测试上下文允许的短句边界 warning。随后 DAG 的配置 allowlist 漏了 native worker 已支持的 `runtime_manifest_path`，在进入 Text/native 前失败：0 worker request / 0 native WAV / 无发布收据。Source/MFA 产物和真实收据保留；父运行已在两次 known-returned 后永久关闭。

修复将该字段纳入 DAG 及输入 inventory，并在任何付费 Source 阶段前校验 preview shape/执行模式/实际 runtime prefix 与 manifest。恢复采用独立新 attempt 的明确 Source-cache inspector：绑定已关闭父计划、Source/Anchor/summary/对齐、实际 ASR/source-check 收据、MFA 外部文件和源生产代码；保留 Source canonical 和原引用路径，生成属于新 config/store/code 的 pending diagnostic context。当前确定性 cache 检查记录 historicalSourceProviderCalls=2，而 newASR/newSourceCheck/newMFA 均为0，不向新 provider ledger 复制旧收据，不重置原账本或期限。

只读 Agent 的 8 轮观察在前两次真实阶段均到第 8 轮才出现 action，故显式新授权可选 16 轮，默认与旧授权仍为8；30秒/16 metadata reads/44 transport/单 session-root/2,000,000 microUSD 预留均不变。晚到 action 第9轮完成、无动作截止和 transport 截止新增回归；Agent core/live/API **87 tests 通过**。原 v3 已准备但未运行，0 session，状态 `not_started`，不计入第三次 usage。

恢复阶段承接历史 **303 requests / 70,072,204 microUSD** 占额；新124 requests /25,000,000 microUSD/5,400秒，以及累计三 Agent phase 6,000,000 microUSD观察预留，共保守规划101,072,204 microUSD，仍在110,000,000上界内。模型 unknown 与预留不作实际账单。

恢复入口与 Agent 合并后的定向集成 **97 tests 全部通过**（16.829秒）：包括 Source-cache 与冷启动身份、Agent core/live/API 和晚到 action 观察。该验证没有调用 provider、加载 TTS 模型或发布 Dev；实际恢复验收在固定代码后执行。

## 缓存恢复的真实结果

固定 `d786693` 的 v4 Source-cache 确认历史2请求、本轮 ASR/source-check/MFA为0。西语13组26次生成/审核全部 returned，无未知，保守占额 **4,367,422 microUSD**。插件拒绝 `fresh-g010` 的术语表面保留检查，失败 language receipt、revision bindings 和结构化组证据已持久化。进入另两 locale 时 exact identity 发现延迟加载模块，Dev build 同守卫拒绝；本轮0 native worker、0 WAV、未发布。v4已在全部请求 known-returned、预算无未结算项时永久关闭；后续恢复必须复用有效付费产物、对失败组建立新修订并重审。

准备 v4 时旧 A/v8/v9 因原 clock domain 的期限证明不可用被拒绝；现用追加的关闭收据禁止这三个旧 attempt 新派发，不改原状态、预算、期限或未知结果。历史 A 的42项未知预算保留，仍按原完整40,000,000 microUSD保守承接。

第三只读 Agent phase 在第6/8轮真实提交两次工具结果并得到返回，required-action-v2 绑定核验通过。第15轮 retrieve_session 无 returned 收据，随后 cancel 得到确认；额外3个 bounded GET 确认唯一 root `cancelled`、session idle/无 actions，usage **32,395 input / 1,568 output / 33,963 total**。三次唯一 root 只各累计一次，为 **51,982 input / 2,006 output / 53,988 total**；actualModel、账单仍 unknown。尚未取得经过合同验证的最终诊断，不能称 Agent 验收通过。

第三 phase 真实 checkpoint elapsed=30.17549383302685秒，旧 validator 因超过30秒拒绝重读。这是终态证据兼容缺陷，不能截短实际耗时或丢弃未知调用。修复保留原elapsed，耗尽 checkpoint 仅返回截止/待对账且0派发；显式版本化新授权允许120秒/60轮/132 API方法调用，默认与旧授权不变，单HTTP I/O仍30秒、cleanup5秒、16 metadata reads、单session/root/2,000,000 microUSD观察预留。方法调用上限不等于分页HTTP请求上限。

下一业务恢复承接 **329 requests / 74,439,626 microUSD** 历史占额；规划80新请求/25,000,000 microUSD/5,400秒，累计最多409请求。第四 Agent 累计8,000,000 microUSD观察预留后，保守规划107,439,626 microUSD仍在110,000,000上界内；不得把预留当实际费用。

v4 真实日志独立安全导出为248 events、62 spans、1 trace；OTLP diagnostics为空、event/receipt integrity均consistent，26直接provider收据无未闭合调用。运行在 native 前失败，因此周报仍明确 crossProcessCriticalPath=not_established、queueTiming=missing_instrumentation，不能把可计算的已记录DAG称完整跨进程/排队观测。原始和脱敏导出各保留ledger SHA，不改写旧日志。

零请求冷进程用实际 v4 响应缓存复现生成产物冻结，定位新增模块仅 `scripts/sermon_trace_artifacts.py`：`strict_layer2` 首次原子写 candidate 时才导入它，下一 locale 才再次检查身份。修复显式预加载并以实际冻结路径回归，保留旧模块/hash严格校验；单独重放 bridge 没有触发该生成冻结分支，不能代替这个回归。

Agent 延长观察/终态重读修复93项测试通过；checkpoint全树及worker/delivery版本兼容41项测试通过。真实checkpoint已冻结13文件，包含主权重、tokenizer/config与speech tokenizer辅助权重，树SHA `a4ab384856b5c68ceeb4c93610bf0035a3f9ac2216543d7b85c3ceec7d77a456`；manifest文件SHA `6b807bf500b6c265b8fb28062df71435fc0eaa210be627f0ba860c4bd9bbdabe`（与canonical SHA分别记录）。新native worker要求v3 spec/预先声明的manifest文件SHA及tree SHA，父/子/完成前重新验证；旧v1/v2仅保留实际旧证据范围的只读兼容，不允许旧request重执行。FD无follow、读前后inode/size/mtime/ctime与路径lstat一致，文件替换/符号链接竞争回归通过。该清单准备未加载模型、未调用provider或发布。

历史L2重绑定在隔离 successor 与测试 execution identity 下消费真实 v4 的12个通过插件的组：实际 strict.generate/review cache-only全部通过，生成与审核完整payload均逐一相等，新provider调用0、新D5预约0，旧parent JSON快照不变。该离线验证明确标注 synthetic successor，不能称新live运行通过。新组收据重建并单独绑定闭父lineage/provider/candidate/review/hash；不复制旧预算预约、revision manifest或review receipt到新账本，不因不匹配回退付费重发。实际新plan继续核验这些绑定。

g010的真实语言插件失败走版本化 `sermon-language-plugin-repair-v1`：保留原Sol semantic pass及失败语言回执，不伪造Sol needs_rework；只修被冻结pending `World War`目标表面，保留policy各字段和未人审状态，建立带parentRevisionId的新修订，重跑Astra、Sol和完整locale插件/admission。该跨run历史父修订的两次新请求使用新provider总请求/成本/绝对期限与单请求上限，enforcementScope=`new_provider_ledger_historical_parent_repair`，显式不声称旧D5父预约已在新账本settled；普通新组仍走既有D5。正式跨run D5父历史记录迁移不在这条诊断路径中伪造。

恢复补丁根级集成验证：249 tests，248通过、1 optional SDK skip，91.108秒、exit 0；覆盖Agent、完整checkpoint/native/DAG、真实Source缓存和历史Layer2修订/桥接。预期AccountingWriteError故障注入保留退出语义，未调用真实provider。代码固定后执行v5真实恢复及第四只读Agent。

v5在准备阶段0请求失败：1,730,059字节linked-history误用256KiB private reader。修复仅版本化linked-attempt aggregate用既有16MiB stable reader，其他收据上限不变、对读取精确bytes验证SHA。v5原plan与失败记录保留，新v6恢复仍承接同一闭父v4、源缓存v3和329历史请求，未启动v5不重复计数。第四Agent准备时私有driver原因值不在固定schema枚举；改用receipt_observed和事实packageVersion historical_http_400_body_missing，未改schema或推定根因，零API。
