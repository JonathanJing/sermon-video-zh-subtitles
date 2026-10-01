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

第四只读Agent真实完成：16 polls/35.2017秒、36 transport methods全returned，两次required-action-binding-v2工具提交、final schema及推荐绑定通过，diagnosisStatus=needs_more_evidence。3次同session bounded GET补账确认唯一root completed，21459 input/1628 output/23087 total；四phase各root累计一次73441 input/3634 output/77075 total，actualModel/cost仍unknown、8M观察预留不退款。缺失原400正文不能追认根因。

v6实际Source-cache通过，历史2、本轮ASR/sourcecheck/MFA0；完整13-file checkpoint校验通过、未加载模型。DAG冻结plan559435字节重读误用private256KiB cap，所有nodes在派发前被blocked，本轮provider0/native0。流程继续发布blocked Dev状态并完成298文件约2040508528字节全部HTTP SHA校验、source Range206。三语真实Chrome blocked UI均播放禁用、无音轨、无大纲就绪误导、pageErrors0；失败reason仍unclassified_failure，需补精确安全映射。v6已以0provider请求闭父，下一v7从它追加恢复授权，不覆盖旧plan/收据。资产GET长阶段无中途日志已记录008/013，补数值下载及已验证进度；下载bytes不冒充hash已核验。

最终软件整合在无live任务的v6闭父后进行：加入原始MFA绝对期限、typed Source终态和唯一精确producer兼容映射，保留旧Source生产身份另记当前inspector，未知hash/semantic模块变动不放行。隔离实际v3缓存重验历史2/new0、45旧JSON不变，明确synthetic successor且未创建真实新权限。下一v7真实复用将再次核验这些绑定。另确认同一行lambda/genexpr归一后出现重复error frame，违反uniqueItems并造成AccountingWriteError，008/013补稳定去重；发布重放的检查span/原intent-returned SHA绑定属于观测改进，未观察变量未定义或重复部署事故。

最终软件根级整合：362 tests，361通过/1optionalSDKskip，131.292秒exit0。包括真实挂起子进程期限、精确历史Source兼容、历史12组恢复/失败修订、完整checkpoint/native固定夹具、发布重放零重复部署、数字HTTP进度、实际跨进程clock握手、异常帧去重与业务workload兼容。中韩未付费draft各追加一条原有非空匹配target表面约束说明，术语、pending、模型、引文及Source字段均原样，正常freezer/plugin loader通过；西语policy与v4付费原policy canonical bytes精确相等。预期故障注入AccountingWriteError保留失败语义，未调用真实provider。下一真实v7会核验迁移Source、新Text/native及发布；queue字段的local inline dispatch不代表资源/provider排队，编排耗时仅explicit bookkeeping小计，未观测工作保留unknown。


## 第七轮真实原生路径与局部恢复

固定 `bc955f1424c3b7db4aefa5a23114c9e616a4e127` 的 v7 复用已验证 Source（本轮 ASR/source-check/MFA 为0），实际返回56次新模型请求：韩语26、中文30（两组真实普通内容返工追加4次）。两语13组最终机器、插件及整 locale candidate admission 均通过；正式人审 pending。西语在HTTP-only守卫内执行Git身份查询，被正确拒绝，实际新provider请求为0；旧DAG将其记录为outcome_unknown，原观察不改写。

两语真实 native worker 在冻结MPS float32/sdpa/seed42、完整runtime与13-file checkpoint下加载模型并合成26个WAV，全部完整解码。新worker四事实时钟、绝对期限和终态收据核验通过；韩语213.68秒、中文191.52秒。两语可播、西语blocked的Dev候选已实际部署，300文件完成HTTP内容SHA与source Range206核验；Chrome仅观察两语约4秒播放和西语禁用，不能称整轨或三语完成。私有证据保存在 `artifacts/dev-fresh-180s-supervised-20261001-v7` 与 `artifacts/native-preview-acceptance-20261001/v7-partial-ui-observation-1`。

v7全部provider请求known-returned，按原instruction创建永久关闭收据。完整历史累计385请求、84,189,830 microUSD保守占额，仍承接旧42项D5未知、不退款。下一独立恢复规划最多16新请求、8,000,000 microUSD、5,400秒；累计430请求/110,000,000 microUSD，另保留Agents四phase合计8,000,000 microUSD观察预留。请求上界不表示必须重跑；预计只对西语失败组实际返工，其余已付费结果只读重绑定。

新增身份witness在守卫外获取精确Git/完整tracked tree身份，守卫内使用稳定文件读取重新校验；HTTP-only子进程allowlist不放宽。只有可信且有限reason的派发前拒绝标blocked；普通异常保守unknown。AccountingWriteError仍抛回原异常并停止后续回调，不能降级后继续执行。

历史Layer2增加 `sermon-historical-layer2-spec-v2` / `sermon-historical-layer2-rebind-v2`，支持同一闭父provider来源的普通内容返工最终修订及完整祖先证据，v1保持兼容；语言插件返工及混合来源不能冒充该普通返工路径。原paid/D5账本不迁移；当前candidate/context与审核收据重新生成。

原生worker迁移request/receipt v4，显式互绑historicalSeedProof；v3仅接受精确原worker `2ca16aac1ed10826307394ea6c277d37a4feeb117a4bb3bee67ea86e334d8172` 与原 `bc955f1` plan加载身份的只读核验，完整runtime/checkpoint/期限/clock校验仍执行。历史请求不能重执行。闭父完整直接v3原生lane可在新空目录复制已完整解码的WAV并重建当前candidate/context单位收据，再由真实新worker执行缓存准入、解码与postcheck；独立proof记录旧音频来源及本轮0模型合成，不复制旧worker时钟，不改旧账本或收据。部分lane、未知终态、不同声音身份、seed再seed与中断非空目录均拒绝。该版本实现和夹具不代替下一轮真实缓存worker及三语全程浏览器验收。


Fresh入口增加可选 `historical_native_specs`：每locale采用 `sermon-fresh-historical-native-locale-v1`，仅允许精确parentPlan/workerReceipt/parentPreflight的path+fileBytesSha256引用及targetLocale。首个付费动作前检查实际闭父、完整祖先与独占successor、新plan授权/source四项范围；Source准备后实际 `diagnostic.historical_native_preflight` leaf再次绑定当前Source/Anchor，冻结 `sermon-fresh-historical-native-inputs-v1`。sidecar、helper、runtime/checkpoint、旧单位/WAV及祖先refs进入DAG输入清单，每次接入仍稳定FD分块SHA重验；使用16MiB aggregate而非private256KiB收据上限。默认None保持普通执行，offline fixture不得采用原生历史缓存。该检查不授予模型、人审、预算或发布权。

整合后根级74项native/history/guard测试通过（77.486秒），入口、Source-cache、DAG、attempts、Dev、bounded 91项回归中90通过、1 optional SDK skip（48.251秒），18项Node页面/catalog测试通过。当前tracked版本在原冻结路径实际只读preflight_parent核验KO/ZH各13个完整闭父原生单元，0 provider/0 model；证据 `artifacts/native-preview-acceptance-20261001/v7-closed-parent-preflight`。Fresh新接线定向测试与下一轮实际worker另记，以上不提升为实际新attempt成功。


Fresh历史原生接线最新定向49项：48通过/1可选SDK跳过（23.588秒），含9项新接线回归；真实positive入口记录profile、workload及completed native-preflight leaf，并进入Source初始依赖。v7原始日志有1782 events/322对完整span，provider56次与API起止ID双射、D5全部result。缺少dependsOn的29个容器不属于执行叶子；288个执行叶子依赖均已记录，6条跨进程边有完整四事实证据。仅3个跨PID入口的local dependencyReadyAt未观测，保持unknown；没有实际资源排队证据。

UTC相关的局部/跨span跳变导致旧报告整体partial且抹去单调时钟下可验证的DAG关键路径。修复只允许完整monotonic区间及全DAG/跨进程证明下，有限UTC-correlation警告不抑制独立active critical path；图损坏、缺叶子、cycle、unknown outcome或缺clock proof仍拒绝。原UTC总wall、page UTC/比例与未测资源queue保留unknown，不重写原事件、不把active叶子时长称端到端耗时或ETA。v7只读投影的已验证active path为665.992194秒（Source为缓存、只两语原生成功的实际scope）；这不是完整生产性能基准。

报告时钟修复及Dev安全原因映射的最新整合50项全部通过（18.105秒），包含真实子进程UTC跳变的单调DAG正例、四事实任一缺失、混合时钟、缺依赖、稳定时钟错误run边界等否定测试；保持renderer、native runtime与Source十模块原字节。


## 第八轮三语原生与真实交付终态

v8固定代码 `1848f420508da57162528b291081ae844b605c08`（已包含最新 `origin/dev` 的 `63c0a18040b7f7744b334cebdb31778de228b064`），原生/source/runtime/checkpoint全过程保持冻结。实际会话退出0且已按原instruction追加永久关闭收据。Source来自v3真实ASR/英文检查/MFA，本轮三者均0新执行；这是完整诊断恢复，不是全阶段冷启动性能测试。

三语共39组最终Sol审核、完整locale语言插件和候选admission全部pass，人审pending/releaseEligible=false。ES只对原g010插件失败建立真实修订并重新Astra→Sol，2次新provider均returned，usage4040 input/703 output/4743 total各累计一次；12组ES和13组KO复用v1，ZH13组复用v2并保留两组普通返工祖先。选用历史provider响应76，另外保留4个ZH失败修订调用及2个ES原插件失败父调用，82个独立历史调用不重计新费用。本轮新D5预约为空，enforcementScope保持new_provider_ledger_historical_parent_repair，不伪称旧D5已settled。新保守占额373,965 microUSD，业务历史累计387请求/84,563,795 microUSD；加Agents8,000,000观察预留仍在110,000,000总上界内，均不作账单或退款。

v8 ES原生MPS worker实际加载一次模型、合成13单元；KO/ZH当前真实worker各13单元cacheHit、0加载/0合成。三份v4原生收据、完整runtime与13-file checkpoint、当前candidate/context/Source/声音身份、原期限、四事实clock和39个WAV完整解码已由独立只读审计核验。26个历史WAV字节SHA不变；v7原959JSON不变，v8仅追加两份精确绑定的新授权/successor sidecar。私有审计在 `artifacts/v8-layer2-final-audit` 和 `artifacts/v8-final-delivery-audit`；审计0provider/0TTS，账本前后SHA不变。

本轮也首次走到全部ready后的 `delivery.readonly`，发现旧preflight硬读 `simulated-review-inputs/simulation-authorization.json`，Fresh根目录没有该legacy布局，真实FileNotFoundError保留。原 `final-result.status=incomplete` 和DAG blocked/callback_or_evidence_not_confirmed不改写；外层run_finished=completed只证明执行已封闭，不提升业务验收。流程继续完成真实Dev发布，301文件全部HTTP内容SHA、源视频Range206通过；manifest canonical SHA `d3ea6bc1165a20feeb8ce77cc230492b6b501851e3a3cac7f7d224e195a50e59`。原295公开资产0丢失、正式catalog不改；独立12资产readback及4媒体Range也通过。App为三语ready的诊断试听页，正式Audio/Release包未创建。

终态日志1819 events、361对完整stage、311执行叶，缺叶子dependsOn=0；1 run和4 workflow均封闭。三套真实worker四事实握手，25条已记录跨进程边全部验证。OTLP1 trace/366 spans保留dependsOn属性；没有创建原生OTLP links。周报为partial，三项UTC跳变/UTC-wall警告仍保留；独立可验证的monotonic active critical path=858.008982秒，不能作整周wall、完整生产性能或ETA。UTC wall/pageReady、资源/provider排队均unknown。四个叶子没有本地ready观测（3×preview.validate_inputs、dev_snapshot），不根据其他字段补写。当前两次provider费用只有1项estimated $0.0362925，另一项cost missing；这个数是已知小计。

独立审计量得KO/ZH在worker结束后的容器尾空档分别108.443/105.117秒，全部preview直接子stage未覆盖时间ES42.610/KO130.597/ZH122.939秒。没有profiler证据，不能归因为hash、模型或排队。此观测进入backlog，要求补确定性收尾检查的monotonic叶子和安全进度，不把容器差值自动称为资源排队。日志证据在 `artifacts/v8-final-dag-audit`。


## 真实 Chrome 完整播放验收

第一份full-playback私有脚本在Chrome原生视频页的测试按钮被video覆盖，click超时；未处理的pending watch在页面关闭时reject，浏览器任务提前退出，没有整轨通过收据。这是测试工具故障，原source失败回执保留，不作为媒体、App或供应商故障。只修正测试按钮的固定位置/层级，并将源视频与三语音频隔离重测；没有改发布文件、伪造事件或加速播放。

真实Chrome154.0.8037.59 headless直接使用已发布URL，三条音轨从0以1倍速到ended，未seek/变速：ZH191.52秒（实际elapsed192.376秒）、KO213.68秒（214.609秒）、ES199.36秒（200.490秒）；源MP4180.013167秒（180.133秒）完整ended。页面和媒体错误均0，旧正式周次入口真实播放进度超过5秒；旧周次这条观察不称完整讲道播放。App人审状态仍pending，subtitleTiming仍preview_unsynchronized。

两次独立播放收据绑定同一v8 manifest，严格合并记录在 `artifacts/native-preview-acceptance-20261001/chrome-complete-fresh-v8-aggregate.json`，保留原初次失败。原始完整时序、10秒采样、起止截图及收据在 `chrome-audio-fresh-v8-3` 和 `chrome-source-fresh-v8-2`。这是实际浏览器完整解码及经过时长的播放验收；不是人工语言质量/整轨听审、原视频同步、物理iOS设备或现场验收。


## Fresh 交付兼容修复与零生成恢复

新增固定 `sermon_fresh_source_evidence.py`，显式识别current Fresh证据v1与closed-parent cached证据v1/v2，校验plan、context、原provider receipt/payload/usage、Source/Anchor/对齐/MFA、simulation pending及生产代码绑定；未知schema不会回退旧目录。`inspect_fresh_delivery`采用该专用合同，FreshSession真实入口override并预载新模块。旧 `inspect_delivery` 的四条pending finding合同与原v1报告保持不变。

独立 `inspect_completed_fresh_delivery` 先核永久关闭收据、原终态账本与provider receipts，再执行同一Fresh交付检查，记录原执行身份和新的检查器文件SHA。它是只读重验，不重入旧FreshSession执行入口，不延长原deadline、不授予dispatch或publish权。

实际v8闭父恢复退出0，`status=diagnostic_traversal_complete`，完整重新核验3语×13原生单元及Source历史绑定；ASR/Text/TTS/MFA/provider新增调用、账本写入均0。运行期间provider chat/transcribe及provider/store锁均被显式禁止；原920个JSON/WAV及日志SHA前后完全一致。独立monotonic检查耗时196.764727秒，仅是本次读取/核验耗时。原final-result=incomplete、原失败DAG/日志和原HTTP receipt不回填；页面继续使用原已核验三语ready音轨，原production-stages仍显示那次汇合失败历史，不声称新代码整轮冷启动重跑或恢复状态已重新发布。

恢复证据在 `artifacts/v8-fresh-delivery-recovery-20261001/recovery-result.json`，绑定原plan/final/closed/log、301文件HTTP、完整Chrome验收及三个新检查器源码SHA。此结果完成本计划的诊断交付核验；正式人审、Audio/Release包、人工整轨听审/语言质量/同步、设备/现场仍不在本次诊断通过范围。原生收尾观测缺口另作为DEV-DIAG-015跟进，资源队列/正式性能与原DEV-TRACK-001继续独立验收。


最终兼容补丁验证：5个受影响Source/Fresh/cache/delivery/legacy模块58 tests全部通过（40.299秒），含实际FreshSession constructor/_check/profile及真实Source读取重复检查、冷预载身份、cached v1/v2、闭父过期只读、tamper/unknown拒绝；MFA分支使用合成completed runtime链并保持0实际MFA/模型。根级DAG/会话回归26 tests中25通过、1既有optional Prefect SDK skip（13.199秒）。独立只读代码review无阻断；恢复报告绑定的三个检查器文件SHA与最终补丁完全相等。文档本地链接与git diff --check通过，不重复已验证native/runtime全套。所有代码均提交到工作分支；dev合入和正式验收仍独立。

### PR CI 发现与修复

PR #198 首轮 `f559fac` 的 Local Prefect pilot（run 36905429735）在156项测试中报1个CLI夹具错误：旧夹具缺少新增必需的runtime/checkpoint输入，生产守卫在读取凭据前正确拒绝。补齐明确不可执行的静态runtime夹具及完整惰性checkpoint/declaration后，复现出真实live preflight只读scope遗漏`binding`属性的问题。生产修复仅增加`binding={}`，未放宽输入、身份、期限或派发守卫。

实际CLI四项通过（1.761秒）；CLI/Flow/DAGSession/native runtime/checkpoint/Fresh preview相关48项中47通过、1项本地可选实际Prefect SDK跳过（13.329秒）。有效夹具走真实preflight/config/inventory，禁止网络；缺清单、未知配置及缺checkpoint声明均在读凭据和执行前拒绝。原失败与回归日志、两文件冻结SHA留在`artifacts/v8-source-delivery-gap-audit/ci-cli-fixture`。此次修复0真实API/模型调用、0账本或旧媒体证据写入；远程CI结果以PR最新head检查为准。

修复head `885d0f1` 的实际Prefect SDK CI（run 36907031278，SERMON_TEST_PREFECT=1）157项全部通过（453.337秒），业务仍为模拟/本地回放，不提升为全阶段真实生产引擎验收。Python分片首轮因新head替代由GitHub取消；其取消不记为单元测试失败。

### 收尾与新 dev UI 的兼容

CI期间remote dev合入PR #194并推进到`d927032c408e581cd3e787ec124188095700310d`。合并只发生一处文本冲突：播放按钮同时需要新SVG `setIcon`和本分支无音轨时的diagnosticNotice；保留两者，locale文案自动合并。原Fresh/Source三个恢复检查器源码SHA不变，原v8执行身份、HTTP和Chrome收据仍绑定原冻结版本，不把新UI当作已经发布或播放验收。

兼容检查还发现旧Dev snapshot仅复制3模块，但新app/fingerprint依赖icons.mjs/icons.svg；实际旧v8 baseline也没有新图标与两个brand SVG。真实本地Chrome进一步发现旧baseline也缺少新fingerprint-ui导入的fingerprint-diagnostics.mjs，HTTP404导致App模块未启动；原失败截图/请求记录保留。快照构建固定同步15个当前源码UI资产，保留published-weeks wrapper、正式catalog、旧媒体与Firebase目标。合并前端368项Node测试全部通过（7.530秒）；快照定向检查与最新合并head CI结果独立记录，不重跑paid阶段或改写原证据。

最终15资产快照20项回归全部通过（13.574秒）；缺第5资产的14资产版本先用同一旧baseline夹具实际复现依赖缺失，未由复制当前目录掩盖。固定源码SHA、模块/HTML依赖与旧非UI字节逐项核验。

head `885d0f1` 的Python CI进一步暴露两处历史测试兼容问题：POC渲染测试取首个任意workload，误取新时钟握手事件；改为精确选render_output，实际父修订receipt指标完整，12项accounting与346项全POC通过（14.445秒），未改生产renderer/守卫。旧sanitized报告比对只允许旧网络字段delta，未考虑已实现的clock provenance新增字段；精确递归比较cache/asr/audio分别48/6/5项全为added，原字段changed/removed均0。测试先逐字段核UTC-only durationBasis、readiness not_established及完整telemetry缺测合同，再比对整份旧报告；历史报告和生产reporter不改。actual-trace/report/clock/telemetry90项通过（14.330秒）。失败日志与冻结摘要留在ignored审计目录，最终远程结果以合并head CI为准。

实际旧v8公开301资产独立复制为本地UI兼容候选，固定15源码资产覆盖后306文件；旧资产无丢失，全部非UI与原媒体SHA不变，原snapshot不改。真实Chrome154.0.8037.59三语各1倍速实际播放超过5秒（ZH5.012/KO5.016/ES5.006），SVG暂停图标24px；页面错误/HTTP404/非预期请求失败均0。39项成功200/206媒体元数据或range读取被浏览器取消的观察保留，不能称网络失败全为0。该工具最初将正常取消也当成失败，原工具退出和截图保留，改为只接受有实际成功HTTP证据的媒体取消，模块404仍拒绝。收据在`artifacts/v8-fresh-delivery-recovery-20261001/merged-ui-local-v3/browser-v4`；这是新UI的本地短播放，0provider/模型/发布，不是新版本公开整轨验收。原v8公开整轨证据仍独立有效。

随后dev的main同步推进到`aece2e8b20439fe675ca25d74155be9e498d268b`，tree与`d927032`完全相同，只同步历史祖先；合并保留已核验的相同UI/业务代码，不重跑paid阶段。
