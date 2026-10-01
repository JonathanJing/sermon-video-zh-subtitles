# Dev 统一 Backlog

更新：2026-10-01。本页是项目 **Dev 开发工作的唯一顶层 backlog**，统一管理四层生产、Firebase Dev、Web／iOS、现场对齐、审核后台、Tracker、CI/CD 和独立 `live_session` 的优先级与依赖。新增开发事项先在这里取得稳定 ID；专项文档只展开接口、实现和验收，不再各自形成互相竞争的顶层排期。

English index: [backlog.md](./backlog.md)

本页不代替：

- [四层接口合同](multilingual-production-interfaces.zh.md)：定义生产包、hash、门禁和失效规则；
- [四层制作 Tracker](four-layer-production-tracker.zh.md)：记录某一篇、某一语言、某一次运行的实际状态、证据与 ETA；
- 发布收据、设备收据和现场收据：分别证明对应环境的事实。

## 维护规则

1. 顶层优先级和跨模块依赖只在本页维护；专项 backlog 用本页 ID 反向引用。
2. `complete` 必须绑定已合并代码及对应测试；涉及发布时还要分别记录 Dev／Production HTTP、设备和现场证据。
3. 当前工作树、PR、单元测试、Dev 页面可播和 Production 可发布是不同状态，不能互相推断。
4. P0 是进入下一次完整周产或修复已观察现场问题所必需；P1 是稳定性、效率和可运营性；P2 是实验、扩展或历史方向。
5. 每周内容运行不在这里逐组打勾；使用 Tracker 的 `L1-01`—`L4-04`。这里管理让这些检查点可重复完成的工程能力。

状态枚举：`verified_baseline`、`in_progress`、`pending`、`waiting_evidence`、`blocked`、`complete`。`verified_baseline` 只说明列出的基线已验证，不代表该项所有未来周次完成；只有满足本页第 2 条维护规则和该项验收定义后才能标记 `complete`。

<a id="dev-180s-diagnostic-followup"></a>

## 2026-09-30 三分钟诊断问题与修复状态（2026-10-01 更新）

以下首轮结果保留为2026-09-30历史快照；表格状态按2026-10-01最终监督验收更新，当前边界见本文件末尾最终对账。

证据：[续跑与交付报告](reports/20260930-dev-180s-continuation.zh.md)；[首次阻断快照](reports/20260930-dev-180s-dag-log-agent-api-test.zh.md)保留原失败。测试代码为 `dev@63c0a18040b7f7744b334cebdb31778de228b064`。用户授权放宽额度后，三语 39 组 Astra→Sol→真实插件核验通过，独立 preview renderer 新合成 39 段 WAV 并完整解码；Dev 298 文件核验和 App 内三语超过 20 秒的短时播放通过。原生 TTS worker 三语仍在依赖导入阶段失败。合并日志为 3,409 events / 963 spans / 26 traces，全部 span 闭合，但 API 终态、依赖和跨时钟缺口使关键路径仍为 partial；live Agent 自动诊断未执行。**已交付真实三语 Dev preview，未完成统一 live DAG、原生 worker 验收或正式四层发布。**

以下稳定 ID 是既有顶层工程项的具体 follow-up，不新增竞品排期或替换旧项。`pending`表示尚未实施；`in_progress`表示还在实现/验收；`done`表示本次诊断范围的实现及指定验收完成于工作分支，不表示已合入dev、正式发布或所有顶层项目完成。测试暴露失败不等于代码已修复。人工 default-pass 仅属本次测试，不能补出缺失内容或关闭正式人工门禁。

| ID | 优先级／状态 | 既有归属／问题证据 | 待交付与验收条件 | 依赖 |
|---|---|---|---|---|
| `DEV-DIAG-001` | P0 / `done` | `DEV-L2-001`；F01 | 定位并修复 Astra 生成请求的 HTTP 400。先在同一冻结输入上验证单组最小请求和安全错误摘要，再跑三语 Astra→Sol→语言插件→候选 admission；记录 actual model、参数身份、请求与候选 hash。不得未经证据指定根因或以换模型绕过既定策略 | `DEV-DIAG-002` |
| `DEV-DIAG-002` | P0 / `done` | `DEV-TRACK-001`、`SPD6-LOG-03`；F02 | HTTP 拒绝收据保留可定位的结构化 error code/param 和限长脱敏摘要，绑定 call/attempt/HTTP status；固定错误夹具验证可诊断且无 key、正文或私人路径泄露。拒绝请求的 usage/billing 缺测保持 unknown | 无 |
| `DEV-DIAG-003` | P0 / `done` | `DEV-SPD-004`、`SPD6-ARCH-02`、`RQC-03`；F03 | 区分同配置系统性请求错误与局部可恢复失败；确认系统性错误后停止受影响配置的后续派发，保留已完成/在途收据及未启动单元的原因。只阻断受影响范围，其他有效 locale 不被拖停；恢复不重付成功单元、不静默重置账本 | `DEV-DIAG-002` |
| `DEV-DIAG-004` | P1 / `done` | `DEV-SPD-006`、`SPD6-READY-07`；F04 | 接通受授权和独立预算约束的 Agents live 只读诊断；用本次脱敏 trace 产生绑定 session/turn、evidence IDs、confidence 的诊断，验证 stale/越权输出拒绝。opaque call ID、required_actions绑定及期限重读已修复；第四真实phase已完成工具提交与final合同核验，root completed，diagnosisStatus=needs_more_evidence。旧阶段cancelled/usage照实保留且不双算。会话 GET 成功不作为诊断通过；Agent 无修订、重试、生成、人审或发布权限 | `DEV-DIAG-002`、`DEV-DIAG-008`；真实调用前冻结模型与预算 |
| `DEV-DIAG-005` | P0 / `done` | `DEV-SPD-006`、`DEV-E2E-001`、`DEV-L4-001/005`；F05 | 固定fresh入口已覆盖真实ASR/Source/MFA与可恢复三语Text/native/Dev，测试与正式门禁分别记录。v3真实Source与v7/v8真实三语原生通过，v8发布301文件HTTP/Range及三语/源视频完整Chrome1x通过。首次全ready汇合发现legacy Source目录不兼容，新增版本化Fresh专用检查并在闭父独立只读恢复通过，0新生成/0账本写；原incomplete/DAG失败不回填，未重新发布恢复badge。不是新代码全阶段冷启动性能证明 | 诊断scope通过；正式Audio/Release/device/venue仍007，完整性能仍DEV-TRACK-001 |
| `DEV-DIAG-006` | P1 / `done` | `DEV-SPD-004`、`SPD6-ARCH-02`；F06 | 为期限已过的暂停运行设计显式续期或新 attempt 恢复协议，绑定新授权/期限/预算及旧 run 的结果和身份。保留过期守卫和旧账本；测试暂停超时、未知结果与重启，确保不会自动重发付费请求或重复成功阶段 | 沿用 durable receipt / outcome reconciliation |
| `DEV-DIAG-007` | P0 / `waiting_evidence` | `DEV-L3-001`、`DEV-SPD-003`、`RQC-06`；F07、续跑音频收据 | 三语39组机器候选、原生worker39单元及完整解码、Dev301文件HTTP/Range均已核验；原生依赖问题已修复并真实验收，见 `014`。正式 Audio/Release 包、逐单元回转写筛查/疑点裁决、时间轴/同步、整轨1倍速人工听审和设备/现场仍待各自真实证据，分开记录事实。默认人审仅测试授权；独立 renderer 成功不关闭原生 worker 或正式发布门禁 | `DEV-DIAG-014`；统一端到端验收还依赖 `DEV-DIAG-005` |
| `DEV-DIAG-008` | P0 / `done` | `DEV-TRACK-001`、`DEV-SPD-002`、`SPD6-LOG-01`；F08 | 当前诊断合同已补真实executor、叶子dependsOn/blockedBy、run/workUnit/attempt与跨进程四事实。v8日志1819 events/311执行叶依赖无缺失，25条跨进程边通过，OTLP366 spans保留因果属性。UTC跳变/四个未观测本地ready/资源queue保持partial或unknown，active CP858.009秒不能冒充wall/ETA；原A缺口不补写。新发现的收尾观测空档移交015，真实资源队列/完整性能仍归原DEV-TRACK-001 | 诊断可追溯scope通过；原预算/日志历史不改，正式指标与015独立跟进 |
| `DEV-DIAG-009` | P1 / `done` | `DEV-L4-005`、`DEV-TRACK-001`；F09 | Dev App 区分 failed / blocked / pending / ready：机器候选缺失时不得显示“大纲已就绪”或暗示配音仍在生成；保留准确失败原因和禁用播放。失败/blocked/pending夹具和真实blocked页均禁用音频；v8三语ready绑定当前candidate/context，正式人审仍pending。三语切换及既有周次浏览器行为分别留证，不混淆内容语言与界面语言 | 实际业务状态/原因绑定；不要求为诊断展示重新生成内容 |
| `DEV-DIAG-010` | P1 / `done` | `DEV-SPD-006`、`SPD6-ARCH-01/02`；H02 | 定义跨阶段模块加载时 executionIdentity 的冻结/扩展收据协议；正常进入新阶段不需临时绕过 exact identity 校验，原模块/hash、输入和预算绑定仍严格有效。验证合法扩展、源码变化、旧输入及恢复时身份不一致均被正确处理 | 保留当前原身份及扩展收据，不放宽原 hash 守卫 |
| `DEV-DIAG-011` | P0／`done` | `DEV-L2-001`、`RQC-03`；衔接 `DEV-DIAG-001`。`sermon_strict_layer2.py:122–145,339–350`；`run_target_language_models.py:168–173`；`sermon_review_contracts.py:194–211`；`sermon-review-receipt-v1.schema.json:209–230` | role prompt 与真实 API／响应 schema 一致：JSON-mode 明确 JSON；coverage 指定有序数组和精确字段；verifier 仅四个 requiredChecks，插件另审；声明 check／issue 的合法枚举。合法普通 registerRules 无须私有格式补丁即可通过预检及单组真实 Astra→Sol。保留无效响应证据，不能将其提升为机器通过。原 39 次 HTTP400 的精确错误 body 未保留，JSON 声明缺失是代码观察及解阻探针支持的定位，不能补写供应商原 error code。 | `DEV-DIAG-002/013`；保留 API 与 schema 身份 |
| `DEV-DIAG-012` | P0／`done` | `DEV-L2-001`、`RQC-03`；衔接 `DEV-DIAG-001`。`target_language_policy.py:65–82,98–118`；`language_review_plugins/diagnostic_structural.py:84–96` | 解决全表 terminology coverage 与未使用 pending target=None 的合同冲突：明确 source scope、未使用项及使用项的验证规则，保留术语表来源 SHA 和有效术语约束；未使用项不应仅因空 target 使所有组失败。用零命中系列／确实使用系列／源码变化矩阵及真实插件收据验收。临时 English passthrough 仍 pending，不能称译名或审核通过；禁止全面放宽术语插件。 | `DEV-DIAG-011`；保留术语表 SHA 与有效约束 |
| `DEV-DIAG-013` | P0／`done` | `DEV-TRACK-001`、`SPD6-LOG-03`、`RQC-03`；衔接 `DEV-DIAG-002/003/008`。`sermon_strict_budget_adapter.py:166–205`；`sermon_strict_controller.py:147–158`；`sermon_strict_candidate_bridge.py:121–145`；`sermon_strict_locale.py:102–123` | 分别表达 known returned／known rejected／transport unknown／artifact validation failed／plugin failed；具体 reason、受影响组、call／revision／artifact hash 关联并持久化。provider 已返回不能仅显示泛化执行未知；插件失败需保存原始结构化回执后返回 failed locale。保持保守预算与 outcome reconciliation，不能退款、清账或猜测未执行。以真实无效 coverage、HTTP 拒绝、插件拒绝和未知运输夹具验收恢复与日志；其他成功 locale 独立保留；派发前预算拒绝也写具体 API 终态并标 dispatched=false，不能把未进网络的请求误称在途或靠猜测补账。 | `DEV-DIAG-002/003/008`；保守账本与 outcome reconciliation |
| `DEV-DIAG-014` | P0／`done` | `DEV-L3-001`、`DEV-SPD-003`、`RQC-06`；衔接 `DEV-DIAG-007/010`。`sermon_diagnostic_preview_worker.py:362–379,382–397`；`render_formal_target_language_speech.py:195–206` | 验收 native worker 的真实依赖导入、模型加载与安全 guard 兼容性。实际 qwen_tts→sox 导入通过 os.popen(sox -h) 触发 shell，被守卫正确拒绝；应提供明确、受控的依赖探测／导入路径，或移除该 import-time shell 需求，并冻结依赖与命令身份。不可全面开放 shell／任意子进程／网络。v7韩/中文26个真实native推理及v8西语13个真实native推理全部完成；v8韩/中文真实worker另以cacheHit准入26单元、0模型加载/合成，39个当前WAV完整解码/声音身份/runtime/checkpoint/原绝对期限/四事实clock核验通过。fixture或独立renderer不充当该实际证据。 | `DEV-DIAG-010`；完整验收关联 `DEV-DIAG-007` |
| `DEV-DIAG-015` | P1 / `todo` | `DEV-DIAG-008`、`DEV-TRACK-001`；v8真实收尾观测 | 给原生worker完成后的确定性收尾/历史绑定/文件核验增加独立monotonic执行叶子及限频安全进度。KO/ZH实际容器尾空档108.443/105.117秒；没有profiler不能指定hash/模型/排队根因。四个跨PID入口ready未观测，资源/provider队列没有真实仪表，保持unknown；全DAG active CP不充当总wall/ETA。验证进度、异常/未知结果、无重复生成和旧音频收据兼容；测量与优化分开 | 现有worker/helper/runtime身份不放宽；真实资源队列验收仍归原`DEV-TRACK-001` |

监督记录及每次原失败见[2026-10-01修复与真实验收](reports/20261001-dev-diagnostic-supervised-plan.zh.md)。启动预加载、opaque IDs/required_actions、aggregate读取、Source-cache与修订恢复、原生runtime/checkpoint、MFA期限和日志终态均在对应诊断项留证；旧账本、unknown和耗时不回填。最新真实三语/HTTP/Chrome和闭父只读恢复结果见最终对账，015与正式007仍独立待验。

诊断软件已完成本次计划的修复及监督验收。后续分别推进007正式内容/设备/现场证据与015收尾观测；资源排队、Prefect实际引擎和完整性能继续使用既有归属。该状态不自动授权Production发布或代替正式人工审核。

累计 provider 请求 293（254 returned / 39 rejected），终态 unknown/reserved 均为 0。最坏情况预算保留 $51.582263；已知 returned usage 估算 $5.140327，非供应商账单，39 次 rejected 的 usage/billing 未知。旧 A/B 账本未清空，新的预算/期限/输入 lineage 显式冻结。

H01（测试脚本插件哈希）、H03（首次 deploy 选错 Dev project，CLI 拒绝且未发布）、H04（World War pending target 输入）和 H05（helper 冻结次序）已在测试中纠正并留证，**不新增未修复产品缺陷**。H02后续已由010的严格身份冻结/扩展及006恢复合同覆盖，见最终监督证据。私有 v6 driver 的异常漏写与过长 registerRules 被正确上限拒绝，分别作为测试准备问题；错误原因泛化归 `013`。原报告 F01—F09/H01—H03 保留；媒体、日志、输入版本和账本留在 ignored artifacts。上述首轮历史诊断当时未实施源码修复；下表保留开始开发前的复盘快照，当前进度见最终对账，不关闭既有 `DEV-SPD-*`、Layer 2/3 或 Prefect/Agents 验收。


<a id="dev-180s-first-implementation-batch"></a>

### 2026-10-01 复盘覆盖检查与第一批开发

以下为第一批开始开发前的历史复盘快照；最终对账记录后续结果。复盘十个环节优先复用既有 ID；已经执行的诊断证据与尚未完成的工程验收分开维护，不重复新建顶层事项。

| 复盘环节 | 已验证范围 | 未完成事项归属及补充验收 |
|---|---|---|
| 素材／英文源 | 新 ASR、英文源检查与 hash；下载和 MFA 复用 | `DEV-L1-001`、`DEV-DIAG-005`：从视频链接进入同一运行，绑定下载/媒体/窗口、ASR、对齐来源及英文逐字审核；复用与新执行分别记录 |
| 三语生成／审核 | 39 组在私有输入调整后机器与插件通过 | `DEV-DIAG-001/011/012`：正常版本化 prompt/policy 无私有补丁即可通过，保留失败输入、输出和枚举证据 |
| 内容返工 | 四次内容 repair，新 revision 生成并重审 | `DEV-DIAG-003/013`：系统性错误止损、执行失败与内容失败分流、只恢复受影响范围、已返回无效产物不重复付费 |
| 人工门禁 | default-pass 独立标记、正式人审 pending | `DEV-L1-001`、`DEV-L2-001`、`DEV-DIAG-007`：真实英文/全文文字/听审收据绑定当前 hash，preview 不提升正式资格 |
| 音频 | 独立 renderer 新合成 39 WAV、完整解码 | `DEV-DIAG-007/014`：原生 worker、逐单元回转写筛查、疑点裁决、整轨 1 倍速听审、原视频同步和正式 Audio Package；设备/现场独立验收 |
| Dev 交付 | 298 文件/Range 与三语短时可播 | `DEV-DIAG-005`、`DEV-L4-003/005`：同一可恢复入口生成正式 Release、发布/HTTP 收据；保留旧资产与目标身份，上传/HTTP 失败不重跑 ASR/翻译/TTS |
| 预算／身份 | 显式 linked attempts、期限、账本与绑定 | `DEV-DIAG-006/010`：通用续期/新 attempt 协议、跨阶段代码身份扩展，旧账本/paid caches 与真实 unknown 结果严格保留 |
| DAG | 固定已有 Source→Text→Preview→只读交付图 | `DEV-DIAG-005/008`：覆盖 fresh ASR 到实际发布/HTTP，真实 executor、依赖与跨进程因果，不依赖私有串接脚本 |
| 日志／ETA | 3,409 events、963 spans 闭合并导出 | `DEV-DIAG-002/008/013`、`DEV-TRACK-001`：API 未派发也有终态、typed failure receipts、完整关键路径/资源排队与工作量分母；缺测保持 partial，不能用闭合 span 推断 ETA |
| Agent API | 真实会话读取及离线诊断合同 | `DEV-DIAG-004`：授权且有独立预算的真实只读诊断，绑定当前 snapshot/evidence/session/turn；stale/越权拒绝，诊断没有执行/发布权限 |

用户已明确授权开始开发。第一批范围为 `DEV-DIAG-011/012/013`，同时补 `008` 的派发前拒绝 API 终态；代码与验证边界见[第一批开发报告](reports/20261001-dev-diagnostic-contract-fixes.zh.md)。实现独立分支 `codex/dev-diagnostic-contract-fixes-20261001`，先以实际 adapter/provider/controller 和固定 HTTP/错误响应回归验证。旧测试 run、媒体、账本和发布证据不改写；新的代码不能套用旧模型或插件通过收据。真实新模型调用、原生 TTS、完整 live DAG 和设备验收按各项条件单独留证。`013` 本批覆盖生成产物结构失败、插件拒绝及未派发拒绝；review 非法 enum/字段目前仍为粗粒度 `invalid_review_response`，安全细节收据留作该项剩余交付。响应合同增加后的审核输入须在原授权的 request caps 内预检，本批不自动提高默认上限。

## 2026-09-30：生成、独立审核、门禁与返工闭环

本次核查 `dev@fc3e2fbc60b0fd2c5b59c64fcd515c465efc6b0b`；[PR #163](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/163) 已将 #121—#162 的冻结实现整合到 Dev。下方早期“draft/尚未合并”的段落是对应批次的历史快照，不应再当作当前合并状态。合并及历史组件测试不等于完整生产、内容、设备或现场 sign-off。

新增方案见 [生成—独立审核—门禁—有界返工完整设计](generation-review-gate-design.zh.md)，开发步骤见 [RQC 开发 Backlog](generation-review-gate-backlog.zh.md)。它细化 `DEV-SPD-006` 的业务角色，关联 `DEV-L2-001` 的生产策略和 `DEV-TRACK-001` 的计量，不新增顶层 Epic；不取代四层包、人工批准、发布授权或 [LOGC-01—07 日志合同](workflow-accounting-log-contract.zh.md)。

核心闭环：**Generator 生成冻结候选 → 固定预检 → Reviewer 只读审核 → 固定 Gate → 必需人工门禁 → 下一层**。内容失败时创建绑定失败审核和候选的 Repair Plan，在新 revision 中仅修复受影响范围并重审；审核执行失败优先恢复审核，不默认重生成。已知失败路径用固定程序；仅合法修复路径不唯一时调用 bounded Decision Agent；未知程序缺陷另开 Codex engineering run。

当前 Astra→Sol 已有独立请求、逐组审校及 partial repair，不从零重建。现有 Sol 可修改最终译文，属于 reviewer-editor；新 strict-verifier 是独立 policy/prompt 行为，必须新版本、新目录、A/B 后才启用，不能悄悄改变默认模型策略或把旧收据重标成严格只读审核。正常路径不增加常规第三遍 Astra/Gemini；审核 token 是生产质量成本，不是 Codex orchestration。

| 子项 | 新增实现状态 | 交付与关键验收 | 对应顶层项 |
|---|---|---|---|
| `RQC-01` | `pending` | Generator/Reviewer 权限和输入输出隔离、strict 模式、legacy adapter；审核不改候选，旧 policy/cache/批准不退化 | `DEV-L2-001`、`DEV-SPD-006` |
| `RQC-02` | `pending` | Candidate Revision、Review Receipt、Gate Decision、Repair Plan 的闭合 schema/validator；精确 hash、覆盖、rubric、stale/冲突收据与人工门禁 | `DEV-SPD-006`、`DEV-L2-001` |
| `RQC-03` | `pending` | 固定错误路由、修复依赖闭包、有界决策/预算、partial repair 与 crash reconciliation；无关单元不重付，未知结果不盲重发 | `DEV-SPD-004`、`DEV-SPD-006` |
| `RQC-04` | `pending` | 沿 LOGC-01—07 增加 executionStatus/reviewVerdict/admissionStatus 三状态和生成/审核/返工/重审因果链；每单元真实 model/token/time 可重建 | `DEV-TRACK-001`、`DEV-SPD-006` |
| `RQC-05` | `pending` | 人工标注保留集与 rubric、editor/strict 对照、漏检/误拒/新错误、最终质量及每合格单元累计成本 | `DEV-SPD-005`、`DEV-SPD-006` |
| `RQC-06` | `pending` | Stage 0→约3分钟真实片段→10分钟→完整往期视频逐级 sign-off、Dev交付/旧客户端兼容、guarded rollout和回滚 | `DEV-SPD-003`、`DEV-SPD-006`、`DEV-TRK-002` |

开发顺序：**D1 合同/legacy fixtures → D2 日志 payload 与重放 → D3 生成/只读审核适配器 → D4 固定 Gate → D5 有界返工/预算/恢复 → D6 Stage 0 与人工校准准备 → D7 短片段/10分钟/完整视频 → D8 新周 rollout**。各批次的文件触点、依赖、Owner 角色和完成证据在 RQC backlog 中定义；这些是计划批次，不是已创建的代码 PR。

D1 合同实现可以开工；真实 A/B 前仍须冻结实际样本、工具/模型可用性、具名人审、rubric、预算与量化阈值。新 RQC 实现均未完成，`DEV-SPD-006` 仍为 `in_progress`，不因文档齐备而关闭。3 分钟素材剪辑或历史缓存回放不等于 fresh inference/sign-off。

本轮目标保持后端私有 sidecar、controller 和日志改动，不改变 public catalog/Release/URL 或 iOS binary。每个实现 PR 独立检查兼容性；若需要客户端修改，转入 `DEV-IOS-*` / `DEV-CICD-004`，不能将本方案的 backend-only 范围套用到 #163 里其他客户端变更。

## 当前已验证基线

- 2026-09-20 的 2:58 中文、韩语、西语样片已有正式 Layer 1–4 包、三语文字和音频人审、Firebase Dev HTTP／Range 及浏览器短时播放证据；iOS 真机和现场仍是 `not_run`。
- Firebase Dev 已有可保留旧 POC、旧中文九周和正式三语样片的完整预览；Production 仍按独立发布授权和核验流程处理，不能从 Dev 自动晋升。
- Layer 2 的 Astra 初译 → Sol 独立逐组复核、语言插件和人工批准链已有通用实现；9 月 27 日整篇三语音轨、听审与正式站 HTTP 已有本次收据。可移植媒体恢复和第二周复现仍未完成。
- iOS 已有正式站 v3 catalog／v2 Release reader、自动准备同语言音频和试听资料修复；相关代码已由 #102／#115 合入 `dev`，再由 #116 晋升 `main`，不再只是工作分支。原 PR 记录模拟器定向检查；实体设备上的三语下载、离线、播放和 WebView 正文可见性仍须验收。
- 远距离座位的自动声音对齐“不容易触发”是已观察现场问题；当前只有 backlog 设计，没有 AGC／10→15 秒自适应采集的运行实现或现场通过证据。
- GitHub Actions 已按改动范围运行 Python、Web／反馈 API、Swift 合同或 iOS 模拟器检查，并保持固定的 required-check 名称；Firebase 内容发布仍使用本机显式入口和独立 HTTP 收据。代码合并、内容发布、TestFlight、设备与现场各自留证。
- [9 月 27 日语言统计报告](sermon-language-listening-statistics.zh.md)已记录 Web／API 发布及真实读回、原生 URLSession／模拟器验证和 `1.0.0 (42)` 签名上传。它是有日期的历史证据，不代表本次重新查询线上或当前 `dev` 二进制已分发；实体设备验收仍未完成。

### 2026-09-30 开发中的 PR 与验收边界

本轮已开始实际实现，`DEV-SPD-002`—`006` 与 `DEV-FIELD-001` 更新为 `in_progress`。这些状态表示隔离分支/draft PR 中有代码和测试，不表示已合并或整项完成。完整 38 项逐项对照、精确提交、CI 范围及仍待人工/真实媒体/设备的门槛见 [本轮实施与剩余证据](reports/20260930-overnight-implementation-checkpoint.zh.md)。

目前包含 accounting/DAG/Weekly report、legacy 确定性 controller、canonical 只读规划与正式包检查、bounded decision/budget、崩溃与 paid-cache 持久性回归、Layer 4 共用资产复制、Web 诊断/索引预检及共享客户端 fixture。Canonical production dispatch、生产 Decision runner、完整 Stage 0 和 Stage 1–3 仍未验收；真实周产时长/token 节省没有测得，不能写百分比。当前 draft CI 的 `ios-validation`／`contract-validation` 为 skipped，`native-client` 成功只是路由结果。

### 2026-09-29 Dev／release 对照：已完成的限定范围

核查 `dev@7a35d0b`、`release/2026-W40@542ba17`、`release/2026-W39@e30258b` 与 `main@c2dcedf`。W40 已通过 #115 整合到 Dev，#116 完成代码晋升，#118 回同步 main 祖先；提交祖先分叉不等于功能未回迁。完整 SHA、来源 PR、代码差异和验证边界见[分支与 Backlog 对照](reports/20260929-dev-release-backlog-audit.zh.md)。

| 已完成的实现或历史验证 | 对应顶层项 | 仍未完成 |
|---|---|---|
| W40 代码回迁、Dev→main 晋升及回同步 | `DEV-GOV-001`／`DEV-PROD-001` | 后续每次内容部署授权、候选核验和对应环境收据 |
| iOS v3／v2 reader、默认本周、双稿阅读、自动音频及试听修复已合入 | `DEV-IOS-001` | 完整跨轨历史／定位合同、最新三语真机与系统体验验收 |
| v3 候选组装器、跨包绑定审计及负例测试已合入 | `DEV-L4-003`／`DEV-L4-004` | 真实新周候选、发布／回滚和双 App 刷新验证 |
| Dev `preview_only` 页面、模拟链接到四层页面、共用控制循环和 CI 失败注入 | `DEV-L4-005`／`DEV-E2E-001` | 通用新周追加、真实批准包回放和故障后完整恢复 |
| Producer 逐组／单元记账接线、Tracker 子阶段及时间线投影 | `DEV-TRACK-001` | 同一周账本的完整耗时、等待、重试和 token 覆盖 |
| 三维语言统计实现、Web／API 真实读回与历史 build 42 上传 | `DEV-USAGE-001`／`DEV-CICD-004` | 实体 iPhone 统计验收、目标源码與分发产物绑定及安装／审核状态 |

上表只承认限定范围，不关闭尚有剩余验收的整个工程项；原 PR 的测试结果不算本次重新运行。远场对齐、人工审核后台、第二周恢复复现及效率计划不因代码回迁而完成。

### 2026-09-27 完整视频复盘输入

以下保留当时的复盘事实；其后已合入的实现及剩余工程工作按上方 9 月 29 日对照与各项当前状态读取。

- 正式站已对指定的 31:31.677 视频提供三语页面与音轨；111/111 文件 HTTP／SHA、三条 MP3 Range 206 和 App 内浏览器短时播放有收据。它们不代替 iOS 新版安装、现场麦克风定位和会场验收。
- 当前公开 `/packages/layer3/<page>/<locale>.json` 是旧文字版 `audio_unavailable` 包，与旧 `/releases/` v1 候选哈希一致；`/releases-v2/` 绑定的是私有、已听审的正式音频包规范化 JSON 哈希。两条版本链各自成立，不能覆盖旧路径，也不能把含本机绝对路径的正式包直接放进 Hosting。缺的是正式 v2 发布前可复查的跨包证明与版本说明。
- 本周 Tracker 虽显示 46/46，公开快照仍有 43 个已完成步骤缺实测执行 span。Layer 2 模型 runner 和 Layer 3 renderer 已有逐组／逐单元计时能力，但本次正式运行没有统一归入周账本；历史时长保持未知。
- 本周先产出独立 `/pages/` 页面，后经 App 截图纠正为 App 内本周入口。下次在制作前冻结入口、语言、音频、英文对照、二维码落点及 Web／iOS 验收定义；页面 HTTP、浏览器、真机与现场状态分别报告。

## P0：下一次完整 Dev 周产与已观察问题

| ID | 范围 | 当前状态 | 下一可验收结果 | 详细合同／证据 |
|---|---|---|---|---|
| `DEV-GOV-001` | 分支、CI 与 Dev→main 晋升 | `verified_baseline` | #115／#116／#118 已完成本轮整合、晋升和回同步；后续功能仍从最新 `dev` 经 required checks 合并，晋升后按受检查 sync PR 回同步，不直接修改受保护分支 | [分支与 Firebase 环境](development-branch-and-firebase-environments.zh.md)、[版本对照](reports/20260929-dev-release-backlog-audit.zh.md) |
| `DEV-L1-001` | Layer 1 完整英文事实与锚点 | `in_progress` | 一篇真实整篇完成媒体／范围／英文逐字／词时间／句界停顿／人工审核的可重复 hash 绑定，并产出 `ready_for_translation` | [Tracker 的 Layer 1 工程项](four-layer-production-tracker.zh.md#layer-1-工程-backlog) |
| `DEV-L2-001` | Layer 2 每周多语言文字 | `in_progress` | `zh-Hans`、`ko`、`es` 从同一正式 Layer 1 独立运行 Astra→Sol→语言插件→人工批准；逐组失败可恢复且不污染其他语言 | [Layer 2/3 backlog](multilingual-layer-2-3-backlog.zh.md#3-layer-2目标语言文字-backlog) |
| `DEV-L3-001` | Layer 3 正式整篇音频包 | `in_progress` | 同语言正式 Candidate 经授权音色、自然语速合成、完整解码、回转写、滚动排程、字幕、全文听审与 1 倍速同步形成可移植 Audio Package | [Layer 2/3 backlog](multilingual-layer-2-3-backlog.zh.md#4-layer-3目标语言音频与同步-backlog) |
| `DEV-L3-002` | 英文声学停顿驱动的自然表达 | `in_progress` | 目标语言完整自然句只在已审英文声学锚点处排程；局部 overrun 返回翻译／句界修订，不以词组拼接或拉伸掩盖 | [多语言 Prosody POC](multilingual-prosody-poc.zh.md) |
| `DEV-WEEK-001` | 周产交付定义与时长预检 | `pending` | 在正式合成前锁定完整视频、App 内入口、三种语言的页面／音轨／英文对照、二维码落点及 Web／iOS 验收矩阵；对已审全文先测自然语速时长，超出窗口时先形成另审的短口播稿 | 本节复盘输入；[四层接口合同](multilingual-production-interfaces.zh.md) |
| `DEV-L4-001` | 可重复的 Firebase Dev 周更新 | `in_progress` | `build-update → preflight → deploy → verify` 从完整线上 Dev 基线追加新周，保留所有仍被 catalog 引用的旧资产，并生成逐文件 HTTP／SHA／Range 收据 | [Dev 预演](evidence/2026-09-23-production-readiness/DEV-PREVIEW.zh.md#后续-dev-周次) |
| `DEV-L4-005` | 正式制作前的 v3 Dev 页面预演 | `in_progress` | #108 的 `preview_only` 页面生成器及已审旧样本 Dev HTTP／浏览器预演已完成；下一步接入真实新周的通用 v3 追加构建器。Dev 先包含最新 App 功能，验证语言、播放、字幕及定位；未审 fixture 不进正式目录 | [页面预演](firebase-dev-weekly-dry-run.zh.md)、[版本对照](reports/20260929-dev-release-backlog-audit.zh.md) |
| `DEV-E2E-001` | 模拟链接到四层的快速后端 dry run | `in_progress` | 模拟链接到隔离 Dev 测试页的入口、真实 Layer 1 锚点、Layer 2 Astra→Sol 逐组控制循环、Layer 3 排程与 PCM16 拼接及 CI 成功／四处失败注入已合入。后续补真实批准包只读回放、Layer 4 纯资产组装共用和故障后的完整恢复；正式门禁仍独立 | [后端 dry run](backend-four-layer-dry-run.zh.md)、[CI/CD backlog](ci-cd-backlog.zh.md) |
| `DEV-CICD-001` | 代码与每周内容发布的统一身份和收据 | `pending` | 每次 Dev／Production 发布都绑定目标环境、站点或服务、代码 SHA、线上基线和发布计划；内容发布再绑定候选包与上游审核 hash，纯功能部署明确记录内容未变；部署后分别记录 HTTP、Web、iOS 设备和现场状态，可指向上一可恢复版本 | [CI/CD backlog](ci-cd-backlog.zh.md) |
| `DEV-L4-003` | 正式 v2 发布包跨层绑定审计 | `in_progress` | 审计脚本及负例测试已由 #115 合入；下一步对真实待发布候选留证：逐语言校验 v3 catalog → v2 Release → 私有已听审 Layer 3 原件／审核收据 → 已批准短口播稿与公开 MP3／字幕 SHA，错绑阻止发布；旧 v1 文字包保留，报告不泄露本机路径 | [Layer 4 backlog](multilingual-layer-4-delivery-app-backlog.zh.md)、[版本对照](reports/20260929-dev-release-backlog-audit.zh.md) |
| `DEV-L4-004` | Production v3 每周内容发布器与双 App 刷新验收 | `in_progress`（2026-09-27 开始） | v3 候选组装器、跨包审计及负例测试已合入 Dev 并随 #116 晋升 main；仍须以同一真实新周候选证明正式音频审计、完整线上基线预检、目录最后发布、逐文件 HTTP／Range、回滚及同一 Web/iOS App 版本刷新选页与播放；代码晋升不是部署收据 | [每周发行清单](tongxing-weekly-release.zh.md#v3-周更发布清单与验收) |
| `DEV-IOS-001` | 原生多语言消费与真机验收 | `in_progress` | v3 catalog／v2 Release、默认本周、三语内容消费及自动音频已合入；仍须证明完整跨轨 source-unit 定位与 `PlaybackHistory` v2 合同，再由真机完成 v3 主路径／v2 回退、下载、离线恢复、历史隔离、WebView 正文、VoiceOver 和系统媒体验证 | [iOS backlog](../apps/tongxing-ios/BACKLOG.zh.md)、[版本对照](reports/20260929-dev-release-backlog-audit.zh.md) |
| `DEV-FIELD-001` | 远场声音指纹与字幕对齐 | `in_progress` | 按 FIELD-01—09 补齐诊断、离线预备、版本化 10→15 秒连续采集、raw/AGC A/B、采样时钟、三语映射、防误跳和设备验收；不降低匹配门槛，保留远处同源至少 9/10 正确、30 次负样本零误跳的小规模门槛；FIELD-10 后续实验不阻塞本项 | [本页专项设计](#dev-field-001远场声音对齐)、[执行与验收](field-fingerprint-alignment-backlog.zh.md) |
| `DEV-TRACK-001` | Producer 自动记账、状态与 ETA | `in_progress` | Layer 2 逐组／Layer 3 逐单元记账接线、子阶段和时间线投影已合入；下一次真实周产验证同一账本覆盖筛查、构建、部署、审核等待、失败与重试，并按效率计划汇总整周时间和 token；公开 Tracker 只投影脱敏状态，未测步骤保持未知；新增总体进度／ETA 投影为 pending，须当前单次 180 秒诊断完成后实现，见[进度与 ETA 待办](#progress-eta-followup) | [Tracker 接入项](four-layer-production-tracker.zh.md#tracker-接入-backlog)、[版本对照](reports/20260929-dev-release-backlog-audit.zh.md) |
| `DEV-REVIEW-001` | 私有多语言人工审核后台 | `pending` | 两位不同语言审核者可并行审阅 Layer 2/3；权限、hash、版本、移交、修订失效和不可变收据均 fail closed | [审核后台设计](four-layer-production-tracker.zh.md#多语言人工审核后台-backlog) |
| `DEV-LIVE-001` | 独立 Sunday `live_session` | `in_progress` | 现场 ASR final 保持事实源；翻译、术语、延迟、发布和 fallback 有独立真实回放／现场证据，不借用四层预制完成状态 | [工作流总览](workflows/README.zh.md)及本页历史附录 |
| `DEV-PROD-001` | Dev 代码晋升与后续内容发布 | `blocked`（后续内容部署门禁） | W40 代码已由 #116 晋升 main，并由 #118 回同步 Dev；此处不再表示代码未合并。后续内容部署仍须逐次具备完整周产、Dev HTTP、回滚基线、Production 发布授权及部署前核验；设备／现场另记，不因已有代码晋升而放行 | [Production 合并检查](multilingual-production-premerge-2026-09-23.zh.md)、[版本对照](reports/20260929-dev-release-backlog-audit.zh.md) |

### `DEV-FIELD-001`：远场声音对齐

现场反馈表明后排座位经常无法触发可靠定位。先从 Layer 4 采集／匹配排查，同时核对源版本、索引绑定和目标时间轴；没有分层诊断前，不把 AGC、录音时长或索引生成中的任一项当作已确认根因。

- [ ] Web 保留 `raw-v1` 基线，新增 `far-field-agc-v1`，请求 `autoGainControl:{ideal:true}`；读取授权后 track 的实际 settings，只记录布尔值与区间化质量数据，不记录 device ID、PCM 或 landmark。
- [ ] 同一次麦克风会话最多 15 秒：10 秒 checkpoint 可靠匹配即停止；`silence`、`insufficient_audio`、`no_consensus`、`low_confidence` 或 `ambiguous` 时继续 5 秒并以完整 15 秒重试。
- [ ] 延长只增加证据，不降低 votes、anchor、覆盖、runner-up ratio、match fraction 或三段覆盖门槛；失败不改变播放位置。
- [ ] UI 区分麦克风未启动、音量／特征不足、没有共识、含糊和低置信，并显示“声音较远，继续听 5 秒”；取消、切后台、换篇／换轨和超时立即关闭麦克风。
- [ ] iOS 保留 `.measurement` 基线；AGC POC 必须实际启用 `AVAudioEngine` Voice Processing 并核对 route／mode，不能只改成 `.voiceChat` 后宣称生效。
- [ ] 近／中／远 × 安静／附近说话／纯环境声做 Web／iOS 独立冻结 A/B；远处有效同源至少 10 次中 9 次正确定位，非同源／纯噪声／含糊片段至少 30 次零误跳。

Firebase Hosting 只发布静态运行时和指纹索引；采集、特征和匹配留在客户端。复用现有 fingerprint runtime 文件不需要改变 Hosting 架构；新增模块时必须同步 build allowlist、deploy allowlist 和哈希验证。

**2026-09-29 补充：** 这里识别的是同一录音的音频指纹，不是说话者身份。当前 Web 已使用 AudioWorklet，published 查询已有多条件匹配门槛，iOS 已有耗时及恢复播放校正；这些不重复列为从零开发。iOS 采集 guard 为 7—12 秒，Web 录音长度校验为 9—11 秒且 binding 固定 10 秒，因此 15 秒策略须同时更新能力版本、两端采集/校验和总预算，不能只改时长常量。代码依据与具体测试见 [专项 Backlog](field-fingerprint-alignment-backlog.zh.md)。

| 子项（01／02／09 为 `in_progress`，其余 `pending`） | 待交付优化 | 关键验收边界 |
|---|---|---|
| `FIELD-01` | 失败分类、音量/削波/特征质量、分阶段耗时 | 可解释失败；诊断白名单，不上传现场 PCM/特征 |
| `FIELD-02` | 选篇时预备索引/字幕/音轨，离线 readiness | “可播放”不等于“可离线对齐”；不提前打开麦克风 |
| `FIELD-03` | 兼容协议的连续 10→15 秒与统一预算 | 不拼接两次录音，不用重试重置占麦上限；不足窗口按真实时长处理 |
| `FIELD-04` | 输入 route 与 raw/AGC profile 对照 | 核对实际设置；降噪/回声消除分开试验，不预设提升 |
| `FIELD-05` | 首样本时钟、处理/恢复播放与输出延迟 | 源定位、实际声音和字幕误差分别测，不重复补偿 |
| `FIELD-06` | 英文源→三语音轨→字幕/阅读映射 | 来源/语言/版本绑定；不按行号或时长比例换算 |
| `FIELD-07` | 重复片段、跨窗口一致性与大跳转保护 | 新证据去重，原门槛不降低，含糊位置不自动跳 |
| `FIELD-08` | 取消/撤销/微调、新鲜度与资源清理 | 用户新操作优先；不持续监听或后台重开 |
| `FIELD-09` | 真实声学保留集、跨端 parity、设备/会场 A/B | 成功率、误跳、P50/P95 耗时及对齐误差分别留证 |
| `FIELD-10` | 更早 checkpoint、增量特征、鲁棒匹配或受控播放器信号 | 非阻塞后续实验，须独立预算/保留集；不引入默认 ASR/说话人识别 |

实施顺序：先 `FIELD-01` + `FIELD-09` 建立可核对基线，再 `FIELD-02`—`04`，随后 `FIELD-05`—`06`；`FIELD-07`—`08` 贯穿全部步骤，`FIELD-10` 不作为本轮 P0 关闭条件。跨轨映射复用 `DEV-IOS-001` 和 Layer 4 合同，不在现场修复上游内容。专项中的样本扩围和精度数值是待基线后、试验前冻结的候选目标，不是当前成绩；未实施优化继续保持 `pending`。

## P1：稳定性、恢复与运营效率

| ID | 工作 | 当前状态 | 完成定义 | 详细入口 |
|---|---|---|---|---|
| `DEV-VOICE-001` | Speaker Voice Registry 授权与可移植恢复 | `in_progress` | 每语言 checkpoint 的授权范围、能力、hash、媒体恢复位置和归档验证可在干净环境重建，不依赖原工作站绝对路径 | [Speaker Voice Registry](multilingual-speaker-voice-registry.zh.md) |
| `DEV-L4-002` | 原子 catalog、单语言回滚与旧资产保护 | `in_progress` | 新语言／周次更新不删除其他 locale 或旧周资产；catalog 最后发布；单 locale 可回滚 | [Layer 4 backlog](multilingual-layer-4-delivery-app-backlog.zh.md#6-layer-4-与-app-改进-backlog) |
| `DEV-IOS-002` | iOS WebView／CI 偶发空白与系统表面 | `in_progress` | 相同 CI 系统和真机稳定显示正文；Now Playing、锁屏、耳机／中断、Live Activity、无障碍分别验收 | [iOS backlog](../apps/tongxing-ios/BACKLOG.zh.md) |
| `DEV-CICD-002` | 四类代码改动的 CI 测试路由 | `in_progress` | #52 的 iOS 路由／固定 native-client 与 #114 的后端 dry-run CI 已实现；继续按四类改动和失败矩阵验收，跨端合同变更同时验证 Web 与 iOS，文档快路径不跳过固定 required checks，失败定位到具体改动和测试 | [CI/CD backlog](ci-cd-backlog.zh.md)、[版本对照](reports/20260929-dev-release-backlog-audit.zh.md) |
| `DEV-CICD-003` | Firebase 页面与后端功能的 Dev→Production 交付 | `pending` | Dev 功能候选在隔离项目／服务完成页面、API、权限和真实读回 smoke；Production 只使用已核对代码版本与当前基线，按实际服务分别部署并保存 HTTP／API 收据及回退目标，不由 `main` push 自动发布 | [CI/CD backlog](ci-cd-backlog.zh.md) |
| `DEV-CICD-004` | iOS 安装包与 TestFlight 交付链 | `in_progress` | 9 月 27 日报告已有 build 42 签名归档、上传及当时 TestFlight 状态，不能继续笼统写未上传；仍须绑定本次目标源码 SHA、版本／build、签名产物和上传结果，再分别记录实际安装、真机、App Store 审核／上线。历史构建不替代当前 Dev 分发；内容周更不强制重发 App | [CI/CD backlog](ci-cd-backlog.zh.md)、[build 42 历史证据](sermon-language-listening-statistics.zh.md) |
| `DEV-TRK-002` | 第二周真实全流程复现与恢复 | `pending` | 用新周次验证缓存、断点恢复、上游失效、旧资产保留和 ETA 校准，不复用第一周人工结论 | [四层 Tracker](four-layer-production-tracker.zh.md) |
| `DEV-SPD-001` | 并发、审核等待与模型路由优化 | `in_progress` | 2026-10-01 SPD-OPT-01—04代码／离线验证完成，真实组件验收取得ASR驻留减少73%–75%、正式权重三语TTS对照、两端CPU输出正确，以及正式Astra/Sol八组/档48次响应与独立预算证据。TTS听审、10分钟／整周与rollout仍待完成，不改变内容模型和批准门禁 | [四项开发](local-production-speed-backlog.zh.md)、[组件验收](local-production-performance-acceptance-20261001.zh.md)、[提速 backlog](four-layer-production-tracker.zh.md#周日页面提速-backlog本轮结束后按审计证据实施) |
| `DEV-SPD-002` | 流程环节与时间／token 基线 | `in_progress` | 从收到视频链接到 Dev App 交付画出实际依赖图，逐环节绑定入口、输入输出、缓存、审批、耗时与用量；交付可复查的关键路径及 token 消耗排名，缺测项明确列出；本轮诊断结束后冻结版本化工作量分母与分桶耗时基线，支持[资源约束 ETA](#progress-eta-followup) | [本页效率计划](#每周流程效率计划)、[记账规则](workflow-accounting.zh.md) |
| `DEV-SPD-003` | 三类 dry run 与恢复演练 | `in_progress` | 在 `DEV-E2E-001` 现有模拟器上扩展快速回放、真实代表片段、故障后恢复；区分模拟与真实调用，验证恢复后的完整交付，保留失败和中断证据 | [本页效率计划](#每周流程效率计划)、[后端 dry run](backend-four-layer-dry-run.zh.md) |
| `DEV-SPD-004` | 局部重试与修订依赖范围 | `in_progress` | 验证并接通已有翻译 partial repair、响应恢复和音频单元复用；受控故障恢复时，不受影响的成功组新增付费调用为 0、已验证音频重新合成为 0，旧收据与失效范围可追溯 | [本页效率计划](#每周流程效率计划)、[Layer 2/3 backlog](multilingual-layer-2-3-backlog.zh.md) |
| `DEV-SPD-005` | 整周总 token 与调度开销优化 | `in_progress` | 汇总调度、内容生成、机器复核、失败与修订的去重用量；减少重复上下文和无效模型调用，按相同工作量比较恢复后总 token 与完成时间，保留费用及缺测边界 | [本页效率计划](#每周流程效率计划)、[模型实验结果](reports/20260928-model-production-ab-results.zh.md) |
| `DEV-SPD-006` | Codex 编排三层重构与 bounded context | `in_progress` | 将正常周产拆为确定性 Workflow Engine、只处理窄歧义的 bounded Decision Agent、仅负责系统开发/未知故障的 Codex Engineer；按 TEST-A—G 验证 happy path 0 个 runtime Codex 编排 turn、State Packet 白名单/预算、子 Agent 不继承父全文、stale decision fail closed、页面 hard stop 与 token 分口径 A/B；不通过削弱质量门禁制造下降 | [Codex token 分析与测试计划](reports/20260929-codex-orchestration-token-analysis.zh.md) |
| `DEV-LOCALE-001` | 界面本地化母语复核 | `in_progress` | 中文、英文、韩语、西语、越南语界面候选分别完成核心流程、错误、权限、VoiceOver 和长文本复核；界面语言不改变内容／音频选择 | [Layer 4 语言设计](multilingual-layer-4-delivery-app-backlog.zh.md#24-app-界面语言) |
| `DEV-USAGE-001` | 按三种语言维度统计收听 | `waiting_evidence` | 三维语言／pageId 统计、私有报表、Web／API 发布与真实读回、原生 URLSession／模拟器 UI 已有 9 月 27 日记录；下一步完成实体 iPhone 实际播放／关闭／撤回、跨端口径及原始收据核对。界面语言、正文语言和实际音轨语言仍分别记录，不从界面选择推断收听 | [使用统计](sermon-app-usage.zh.md)、[三维统计与发布证据](sermon-language-listening-statistics.zh.md) |

### 每周流程效率计划

2026-09-29 确认：下一阶段先搞清楚每周制作的实际环节，再减少从视频链接到 Dev App 交付的总时间和流程总 token。以下是待实施／验收的工程计划，不是已完成优化，也不预设节省百分比。工程优先级只在本页维护；`TRK-*`、`SPD-*` 继续作为专项验收项，复用现有 `DEV-TRACK-001`、`DEV-E2E-001`、`DEV-L2-001`、`DEV-L3-001` 和 `DEV-TRK-002`。

研究依据见[每周证道流程耗时与 token 研究发现](reports/20260929-weekly-workflow-efficiency-findings.zh.md)，记录核查版本、代码与测试入口、缓存计量风险、模型实验边界及旧分支结论的修正。

**当前可复用能力与证据边界**

- [后端快速 dry run](backend-four-layer-dry-run.zh.md)已共用部分生产控制循环、保存逐步计时及失败报告，并有 CI 故障注入；固定响应和测试音不测真实 ASR／翻译／TTS 性能。较早的 [30 秒 bucket 演练](firebase-dev-four-layer-bucket-dry-run.zh.md)是另一条复用素材的交付检查，不能替代真实生成基线，也不应据其旧失败处理推断新版模拟器行为。
- [Layer 2 runner](../scripts/run_target_language_models.py)已有 `--partial-repair-brief`、`--reuse-from`、`--resume-cache-from`；[Layer 3 renderer](../scripts/render_formal_target_language_speech.py)已有逐单元恢复和跨修订复用。先验证这些能力在同一周编排中的实际恢复边界，补缺口，不重建平行缓存系统。保留付费响应、旧失败及身份校验；未知请求结果不得盲目重付。
- [9 月 28 日模型实验](reports/20260928-model-production-ab-results.zh.md)已有三语 135 组／臂对照：Luna→Sol 有 10 组结构失败，尚无人审分数或修订分钟数；调度样本也未证明稳定速度优势。延续现有样本、失败证据和盲评材料，不能把较低 token 费用当作较少 token、较短总时间或正式质量通过。

**Codex 编排三层重构（DEV-SPD-006）**

历史 2026-09-20 收据显示：生产 Astra 文本 API 为 1,716,038 token，而 Codex 主任务与三个明确子任务的可观察小计为 169,298,693 token，其中 166,824,192 为已包含在输入中的缓存读取，非缓存输入为 2,148,134，输入缓存占比 98.73%。这说明优先问题是长生命周期 Agent context 与父子任务重复承载状态，不能把 1.69 亿解释成页面正文或同额非缓存成本。完整分析见 [Codex 编排 Token 消耗分析与三层重构方案](reports/20260929-codex-orchestration-token-analysis.zh.md)。

目标架构：

1. **Layer A — Deterministic Workflow Engine。** 已知的 hash/gate/cache/retry/deploy/verify 状态转换由持久化 state + receipt 驱动，stage 必须 idempotent；可唯一决定下一步时不调用 Codex。
2. **Layer B — Bounded Decision Agent。** 只处理未分类失败、多个合法恢复路径或质量问题归类等窄歧义；输入为版本化 State Packet 与 evidence refs，不携带完整 production conversation/tool history；输出必须属于 controller 给定的 allowlisted actions，state revision 变化后旧 decision 作废。
3. **Layer C — Codex Engineer。** 负责新功能、schema、未知 bug、pipeline 优化、实验、PR 与 review；正常周产不让工程上下文长期驻留。修复后把稳定规则下沉 Layer A/B。

需要实施并测试的改动：

| 测试 | 待改动 | 最小验收 |
|---|---|---|
| SPD6-TEST-A | 已知 stage transition 下沉确定性 controller；stage 提供 inspect/execute/verify 与 identity-aware reuse | 固定 happy-path fixture 从 source-ready 到 page-ready，runtime Codex orchestration turn = **0**；审批/hash/发布/HTTP gate 不减少；重复运行不重复发布或新增生产调用 |
| SPD6-TEST-B | 新增版本化 State Packet，仅含 stage、身份 hash、blocker code、允许 action、短计数与 evidence refs | 初始实验预算：serialized packet ≤ **32 KiB**、evidence refs ≤ **16**；大转写/长日志/完整 tool output/secret 不进入 packet；关键 gate 不因截断丢失 |
| SPD6-TEST-C | Decision Agent 使用结构化输入/输出、allowed actions 与 state revision | retry/open_revision/request_review fixture 通过；未知 action fail closed；模型返回前 state 改变则 decision 作废；歧义超预算后停止而非无限扩 context |
| SPD6-TEST-D | page_route、delivery_builder、local_tts_route 等改为显式输入合同，默认不继承父 conversation/tool history | 将父 context 人工放大 10×，子任务输入大小不随之同倍率增长；缺证据安全停止；父子 usage 分列且不与 SDK 聚合重复计数 |
| SPD6-TEST-E | 定义 page_ready/delivery_complete hard stop；海报、代码、文档/PR 默认成为后续 bounded task | page_ready 后 production controller 不再启动新生产 stage；后续工程任务只接 release receipt/必要引用；生产 token 报告在 hard stop 冻结 |
| SPD6-TEST-F | failure code + affected unit + receipt 持久化；已知 transient/partial repair/reuse 由 controller 处理 | 翻译组失败时未影响组新增调用 0；音频单元失败时未影响单元重新合成 0；upload/HTTP 失败时 ASR/翻译/TTS 新调用 0；重复同类失败不线性增加 Decision Agent turn |
| SPD6-TEST-G | 统一记录 Agent context 与生产调用口径 | 每次运行分别报告 total input、cached input、non-cached input、output/reasoning、decision turns、State Packet bytes、子 Agent usage、production API token、失败/重试 token、wall time 与质量 gate；不得只报 total token |

A/B 顺序固定为：**A 当前 Agent-heavy 基线 → B1 只引入 bounded State Packet → B2 Layer A + bounded Layer B → B3 加 page hard stop/工程任务拆分**。每轮只改变一个主要变量，并保持同一输入、同一语言、同一人工/质量/发布门禁。历史 9 月 20 日只能作为参考；若当前版本无法等价复现，不把旧数字冒充新的 A 基线。

候选验收原则：正常 happy path 可由 Layer A 表达时 runtime Codex orchestration turn 为 0；Layer B 不携带完整会话；生产 API token 不能因“省 Codex”而无界增加；不得通过减少语言、取消人工审核、跳过 QA/设备/发布门禁制造 token 降幅。具体百分比在真实基线形成后、A/B 前冻结，不预先承诺。


完整实施设计见 [三层编排重构：Pipeline、日志、验证与分阶段 Sign-off](codex-orchestration-pipeline-design.zh.md)。现有 codebase 审核结论是：这不是“两条独立并行流水线”，而是 **dependency-aware 业务 DAG + control plane**。Control plane 只在 dependency 满足时 dispatch durable job；job 运行期间应等待/退出，完成后重新读取 evidence。业务 DAG 内仅在依赖允许处并行，例如同一 frozen Layer 1 后的 zh/ko/es Layer 2、各语言已批准后的 Layer 3；Layer 4 前重新汇合。

**DEV-SPD-006 完整实施 Backlog**

| 子项 | 状态 | 工作 | 完成条件 |
|---|---|---|---|
| `SPD6-ARCH-01` | `in_progress` | 将现有 snapshot/recommendedAction 明确建模为 dependency DAG + deterministic controller | 依赖、convergence、human gate、waiting、terminal scope 均有机器可读状态；不改变现有业务 gate |
| `SPD6-ARCH-02` | `in_progress` | Layer A dispatch durable job、wait、reconcile、idempotency、retry budget、hard stop | outstanding job 不重复启动；exit 0 不代替 evidence；未知 outcome fail closed |
| `SPD6-ARCH-03` | `in_progress` | Layer B State Packet / Decision schema、allowed actions、state revision、budget | 只处理窄歧义；旧 state decision 作废；未知 action 拒绝 |
| `SPD6-ARCH-04` | `pending` | Layer C engineering run 与 production run 解耦 | engineeringRunId 独立；生产报表不混入 Codex 工程 token/time |
| `SPD6-LOG-01` | `in_progress` | accounting v3 已开始写入 executorType、dependsOn、blockedBy、ready/queue、workUnit/attempt/decision identity；DAG/critical-path 初始投影已实现，下一步接入 producer 完整依赖与等待证据 | 可重建 DAG 和 critical path；旧 v1/v2 历史仍可读 |
| `SPD6-LOG-02` | `pending` | 固定程序记录 script/hash/input/output receipt/runtime/CPU/RSS/cache | 固定程序耗时不记为 Codex orchestration |
| `SPD6-LOG-03` | `in_progress` | 模型调用记录 requested/actual model、role、input/cached/non-cached/output/reasoning、latency/attempt | 关键 model call usage 覆盖 100% 或显式 unknown；不重复计量 SDK 聚合与底层 receipt |
| `SPD6-LOG-04` | `in_progress` | bounded proposal 已记录 packet bytes/hash、引用/动作数量、预约/响应/验证/提交耗时；真实 SDK/model usage 与 packet 构建仍待接入，未知不补零 | 能单独得到 orchestration time/token；parentContextInherited 目标为 false |
| `SPD6-LOG-05` | `in_progress` | 生成 Weekly Pipeline Report JSON + Markdown | 同时给 end-to-end、critical path、active compute、human/external wait、production model、Decision Agent、engineering Codex、热点 work unit |
| `SPD6-VAL-00` | `pending` | 现有 synthetic/短 fixture dry run | happy path 0 runtime Codex turn；failure injection、stale decision、convergence、hard stop、账本重建全通过并生成 Stage 0 sign-off |
| `SPD6-VAL-01` | `pending` | 经授权往期视频约 2–3 分钟真实小片段 dry run | 三语真实 ASR/翻译/review/TTS/组装/Dev candidate；happy path 0 Codex turn；bounded decision 注入通过；相同输入 rerun 未影响单元不新增付费调用；Stage 1 sign-off |
| `SPD6-VAL-02` | `pending` | 连续 10 分钟真实片段 A/B | A 当前路径 → B1 bounded packet → B2 Layer A+B → B3 hard stop；同输入/模型/prompt/gate/cache 条件比较时间、token、质量、恢复；Stage 2 sign-off |
| `SPD6-VAL-03` | `pending` | 一篇完整往期视频 replay + guarded Dev delivery | 完整三语、人工 gate、Layer 4、Dev HTTP/Range/SHA、Web smoke、受控故障恢复、cold/warm rerun、旧资产保护；Stage 3 sign-off |
| `SPD6-ROLLOUT-01` | `pending` | 新周 shadow/guarded rollout + feature flag | 可切回 legacy_agent；首两周 enhanced logging；Production 仍按既有授权，不由新 controller 自动放宽 |
| `SPD6-IOS-01` | `in_progress` | backend-only / iOS contract gate | 每个 sign-off 比对 iOS 源码、App bundle、catalog/release client contract、权限/隐私；均未变时记录 ios_review_required=false；任一客户端变化立即转入 DEV-CICD-004/DEV-IOS backlog |

**开工前工业化缺口审查（已补齐设计）**

对照 durable workflow 的常见实现后，开发前补齐以下合同；详细设计、Epic、依赖和文件目标见 [完整设计 §19–22](codex-orchestration-pipeline-design.zh.md#19-工业界模式对照与本项目取舍)。

| 子项 | 状态 | 开发合同 |
|---|---|---|
| `SPD6-READY-01` | `ready` | workflowDefinitionVersion/stateSchemaVersion；in-flight run 固定版本，不兼容升级显式 migrate/finish-old/restart |
| `SPD6-READY-02` | `ready` | side-effect idempotency key + intent-before-side-effect + outcome-unknown reconciliation；覆盖 paid model/TTS/deploy/registry |
| `SPD6-READY-03` | `ready` | 每 stage timeout/heartbeat/no-progress/retryable/non-retryable/max-attempt matrix；不再只依赖统一长 timeout |
| `SPD6-READY-04` | `ready` | compensation/rollback matrix：reversible/compensatable/append-only/manual reconciliation |
| `SPD6-READY-05` | `ready` | bounded concurrency/backpressure：paid API、TTS、本地 CPU/RAM/GPU、queue fairness、同 identity 单 worker |
| `SPD6-READY-06` | `ready` | human approval correlation：run/stage/candidate hash/revision/reviewer/schema；新 revision 自动失效旧批准 |
| `SPD6-READY-07` | `ready` | Decision Agent security：packet allowlist、evidence-as-data、no shell/path/deploy control、action 二次校验、prompt-injection fixture |
| `SPD6-READY-08` | `ready` | trace identity 可映射标准 tracing：trace/span/parent/workflow/stage/workUnit/attempt/executor；critical-path projector |
| `SPD6-READY-09` | `ready` | Stage 2 前冻结 SLO/promotion gate；duplicate side effect/stale decision/missed mandatory gate 必须为 0 |
| `SPD6-READY-10` | `ready` | sign-off ownership 分 Engineering/Content/Release/Compatibility/Performance，自动化不得自签人工/内容门禁 |

**实施 Epic 与依赖**

1. **E1 Accounting/Trace foundation**：schema extension → critical-path projector → weekly JSON/Markdown report。无前置依赖。
2. **E2 Deterministic Controller**：versioned DAG → controller loop → durable dispatch/reconciliation → migration → feature flag。依赖 E1 schema。
3. **E3 Bounded Decision Agent**：State Packet → runner → validator → failure taxonomy。依赖 E1 + E2 workflow definition。
4. **E4 Reliability/Safety**：side-effect、timeout/heartbeat、backpressure、human correlation、crash-window tests。依赖 E2。
5. **E5 Validation harness**：Stage 0 → 2–3 min → 10 min A/B → full historical → rollout。按 E1–E4 能力逐级启用。
6. **E6 Compatibility gate**：freeze Web/iOS contract → automated compatibility diff → iOS review decision receipt。可与 E1–E4 并行，但 Stage 1–3 sign-off 必须执行。

Definition of Ready 已在完整设计中逐项勾选；剩余的 implementation branch/issue/owner 是“开始开发”的执行动作，不再是架构缺口。2026-09-29 冻结设计时，`DEV-SPD-006` 从 `pending` 更新为 `ready_to_start_dev`；2026-09-30 已有实际 draft PR 和组件回归，现为 `in_progress`。未完成的 canonical 执行、真实媒体与 sign-off 门槛按本页最新实施对照处理。

**分阶段 Sign-off 规则**

1. **Stage 0 — synthetic/现有短 fixture：** 不测真实内容质量，先证明 controller、dependency、logging、failure/recovery、安全停止。所有 deterministic happy path 不调用 Codex runtime。
2. **Stage 1 — 2–3 分钟真实小片段：** 片段必须含普通叙述、专名、经文/术语、长句、自然停顿和多个翻译/TTS 单元；走真实生产模型和 Dev candidate，但不 Production deploy。
3. **Stage 2 — 10 分钟连续真实片段：** 冻结同一输入、模型/prompt、质量门禁和初始 cache；逐步 A/B，不能一次改多个变量；形成 full-video 前的性能/质量阈值。
4. **Stage 3 — 完整往期视频：** 使用已有 frozen source/审核/发布参考的历史视频，在隔离目录 replay，再做 guarded Dev delivery；要求完整人工/HTTP/Range/SHA 和兼容 smoke。只有 Stage 3 签字后才进入新周 rollout。
5. **每级失败不得由后一级结果覆盖。** 修复后重新跑当前级并生成新的 sign-off receipt；sign-off 必须绑定 code SHA、config、source/slice、模型/prompt、初始 cache、结果 hash 和 reviewer。

**iOS / App Store 边界**

本优化目标是后端编排和 accounting。只要最终 diff 不修改 iOS 源码/App bundle，不改变旧 App 无法解析或语义不兼容的 catalog/Release/URL 合同，不新增客户端权限、SDK、隐私采集、背景行为或远程可执行代码，就不需要为了这次后台优化制作新 iOS build。每个 Stage sign-off 都必须重新跑 `SPD6-IOS-01`，而不是一次性永久豁免。若任何客户端代码/合同必须改变，立即撤销 backend-only 结论并进入 `DEV-CICD-004` 的 build/TestFlight/App Review 链。

**实施顺序与交付物**

1. **`DEV-SPD-002` + `DEV-TRACK-001`：流程图和可核对基线。** 列出接链、下载、范围审批、ASR／对齐、英文审核、三语翻译／机器复核／人审、TTS／筛查／排程／听审、构建／上传／HTTP／App 检查的实际入口及先后依赖。逐项标记实现／模拟／人工／未接通、输入输出 hash、最小工作单元、并发限制、缓存条件、重试范围与审核等待。冻结运行身份、样本、模型／prompt／策略、代码和初始缓存；区分执行、资源排队、审核等待、外部阻塞和返工，计算三语最长路径，不能把父子 span 或并行时间相加。分别报告首次执行、恢复后成功尝试及包含全部失败／修订的整周累计，完整用量不可得时只报已知小计及缺口。
2. **`DEV-SPD-003`：复用同一生产路径的三类演练。** 快速回放使用固定夹具和已核验缓存，检查合同及交付；真实片段选择含经文、专名、长句和衔接段落的几分钟素材，实际调用 ASR、翻译、复核和 TTS 并走各层门禁；故障演练在指定组／单元／发布步骤失败或中断后恢复，检查重复工作与新产物。先复用现有 CI 注入点，再补音频单元中断、坏缓存、上传及 HTTP 核验失败。追加记录开始、失败、重试和恢复事件，即使强制中断也保留已持久化证据；模拟用量为 0 不作为真实性能收益。片段通过后按 `DEV-TRK-002` 做完整周次验证，不从片段线性外推整篇提速。
3. **`DEV-SPD-004`：先缩小返工范围。** 从失败的翻译运行建立新修订，复用身份匹配的成功组，只重做失败及有上下文依赖的组，继续未执行组，并重新走规定复核／插件／准入链。音频修复记录具体单元、原因、旧 hash 和新 attempt，只合成受影响的完整自然句；重新排程／组装／整轨验证与重新 TTS 分开计量。以稳定单元身份核对复用，测试重排、重分组和策略变化造成的真实失效；不能靠忽略全局绑定扩大复用。临时故障采用有界退避，质量失败进入修订，未知付费请求进入状态核对；相同失败且无新证据不得无限循环。
4. **`DEV-SPD-005` + `DEV-SPD-001`：在基线上逐项优化。** 先减少重复上下文、无变化轮询、已知规则的模型判断和无效重试，再比较有界并发及模型分工。调度传最小必要的状态摘要、失败单元和证据引用，由确定性程序执行已知规则；翻译／复核仍保留所需英文上下文、术语、经文及质量合同。提示词或上下文改变须有版本与质量回归；缓存命中减少实际生成或费用，不自动等于总输入 token 下降。每次只改变一个变量，记录回退方案；基线形成后、实验前冻结接受阈值和调用预算，报告时间、token、费用及质量的取舍，不预设全部同时下降。

**整周 token 统计口径（`DEV-SPD-005`，采集由 `DEV-TRACK-001` 承接）**

- 以同一周次／来源／语言关联所有 `runId`、恢复 attempt 和 revision，统计到约定交付终点；保留成功、失败、废弃修订及返工的实际消耗。范围包括 Supervisor／Codex 调度、子 agent、ASR 中可获得的 token、翻译、机器复核、筛查模型及其他流程模型调用；编写工具的开发对话与正式生产调用分列，不能把编排消耗遗漏后称作流程总量。
- 按模型、角色、层、语言、组／单元、尝试记录输入、其中缓存输入、输出及可得推理 token。按 provider 口径去重：缓存输入是输入的子集、推理是输出的子集时不再相加；同一响应或 SDK 聚合与底层收据不能重复计算。本地磁盘缓存复用不重新计入旧调用，但旧调用若属于本周统计范围仍计一次。无法证明 SDK 与底层去重关系时分列而不相加。
- 核实实际缓存命中，而非仅凭 `--reuse-from`／`--resume-cache-from` 存在就计为命中：当前 Layer 2 某些 span 的 `cache_hit` 标志依据复用参数设置，未开始组仍可能发起新调用。补充实际缓存来源、复用响应 ID、新调用数与用量证据，并覆盖“部分命中、部分新调用”的恢复测试，不能从该布尔值推算省下的 token。
- 无法取得的 Codex／子 agent／失败请求用量为未知，列明缺失调用数、覆盖率和来源；调用总数也未知时不伪造覆盖率。迟到 usage 只读补录并去重。仅有音频计费秒数的 ASR、无 API token 的本地 TTS 单列，不换算成 token。跨模型汇总是观察到的用量汇总，模型 tokenizer 与单价可能不同，不能代替费用或账户额度。
- 交付表同时列出完整性、整周已知总 token、非缓存输入／输出拆分、失败／返工 token、调用数、每个合格源单元或每分钟源视频的用量、端到端时间和人工修订分钟数。不同模型实验以相同工作量及质量门禁比较；未完成组保留在计划总量和失败栏，另报完成量，不能通过少做工作制造节省。实际费用另按可核实价目和收据统计，实验成本与每周生产成本分列。

**恢复与优化验收**

- 指定一个翻译组失败后恢复：未受影响且通过身份校验的成功组新增付费调用为 **0**；失败组按规定修订，其他语言不重做。
- 中断一个音频单元后恢复：已验证且未受影响的单元重新合成为 **0**；坏音频进入可追溯的新尝试，旧证据保留。修改时长后重算所需排程／字幕并检查整轨，不把“免重新合成”当作“免重新验证”。
- 上传或 HTTP 核验失败后恢复：ASR、翻译、TTS 重跑为 **0**；重试受影响的交付步骤，并按基线时效重新核验必要证据。进程重启和重复调度不产生重复发布或未知重复付费。
- 源身份变化仍按合同使所有语言下游失效；文字／音频修订按语言和上下文依赖重开。人审收据默认整候选失效，只有已证明独立的 `connected_blocks` 可局部保留。保持三语音频齐备后发布的汇合点，HTTP、设备、现场分别留证。
- 并发与模型实验报告包含成功率、质量问题、恢复后总时间／token、审核修订时间和样本波动；优先完成已有 Sol→Sol 盲评及 Luna 结构失败实验，并核清调度影子模式的状态规则，再决定新路由。新模型／提示词使用独立版本和同批对照，正式 Astra→Sol 与 Qwen TTS 不因 backlog 登记而切换。

<a id="progress-eta-followup"></a>

### 总体进度与剩余时间：先实现，再恢复本轮诊断

**2026-10-01 新增要求，状态 `pending`（仅文档，尚未实现）。** 归属既有 `DEV-TRACK-001`（进度投影与采集）、`DEV-SPD-002`（工作量／耗时基线）和 `DEV-SPD-001`（资源约束关键路径），沿用 Tracker 的 `TRK-002/003/005b/006`、`SPD-006`，不新增 Epic、独立看板平台或第二套调度器。

**本轮后续决定：用户明确要求放宽额度、继续跑完全程以暴露问题，已完成真实三语 Dev preview，见[续跑报告](reports/20260930-dev-180s-continuation.zh.md)。下方暂停检查点是历史快照，不是当前暂停指令；完整 DAG、进度／ETA 和 live Agent 能力仍待实现验收。**

**较早顺序（2026-10-01）：先实现有界 Prefect 可执行 DAG、进度／ETA 和 Agents API 只读诊断接口，再恢复本轮单次 180 秒 diagnostic／dry run。** 当时此顺序取代“本轮结束后开发”的要求：主线程在用户 00:52 条件指令后，于 00:53:41 报告 L2 为 0/39、TTS 为 0、无在途请求／新增调用，真实续跑已暂停。这是主线程提供的当时检查点，不是本页实时监测或整轮未执行的声明；原 ASR、source/window、代码版本、缓存、收据及预算账本均保留。续跑已核对输入/版本绑定、已知终态、独立 attempt 的预算与期限；不把等待、心跳停止或未知结果当作安全重启许可。本文不声称扩展已启用，不给出当前总体百分比或 ETA。试点边界及原顺序见[试接合同](prefect-agents-diagnostic-pilot.zh.md#sequencing)。

#### 冻结分母与进度语义

在既有私有运行账本中增加**版本化只读投影所需的计划快照**：绑定 `runId + source/window identity + target + selected locales + delivery endpoint`、DAG definition/version/hash、稳定 work-unit IDs、依赖、适用门禁、初始 revision，以及 `planVersion/planHash/weightPolicyVersion`。以上是待实现字段语义，不表示现有 schema 已支持；扩展须走兼容 profile／版本迁移，旧账本与历史收据不改写。

- 冻结原计划工作集合 `U0`、每单元权重 `w(u)` 和总分母 `D0 = sum(w(u), u in U0)`。权重须为有限正数，单元 ID 唯一；空适用集合为 `not_applicable`，不能除以 0 或显示 100%。同质单元可用等权；跨阶段权重取冻结的同类历史服务耗时基线，保留来源、样本数及冷启动假设。权重衡量计划工作量，不是内容质量、费用或完成时间占比。共享 L1 只计一次，zh-Hans/ko/es 分支独立计量；每个所选 locale 的 L3（含允许纯文字的显式 `audio_unavailable`）仍在计划中。
- 分组／单元总数尚未确定、权重依据不足或计划范围不完整时，总体百分比为 `null/unknown`，显示已知阶段计数和缺口，不拿当前已发现文件数当分母。估时基线可以随本轮样本更新，**冻结权重与分母不能随之漂移**。
- 总体条命名为**“计划工作已处理进度”**：`100 × sum(w(u) × processed(u)) / D0`。`processed` 只在身份匹配、无冲突的终态执行／有效缓存复用证据存在时取 1；执行失败也可表示“已处理”，必须同屏显示失败、阻塞和审核状态。待执行为 0；未知结果、缺失或冲突证据导致状态不可判定时，受影响百分比为 unknown，仍展示已证实数量和 `unknownUnits`。退出零码、心跳、时间流逝或文件存在都不能单独计为完成。
- 分开显示 `processed done/total`、`reviewPassed done/total`、`actualHumanApproved done/total`、`simulatedHumanApproved done/total`，并给出各自适用单元集合／分母。机器审核通过需绑定**当前候选 revision/hash**的有效 Review Receipt；真实人工批准需独立有效人审收据，模拟批准永不计入真实人审或正式准入。诊断／synthetic／真实调用模式同时标识；不适用为 `not_applicable`，未知不是 0%。处理进度到 100% 也不能自动写业务 `complete`、发布、设备或现场通过。
- retry/repair 不新增原计划单元，不将同一单元重复加到分子或分母。单列 `reworkUnits/attempts/elapsed/token/cost`，保存旧失败、新 revision 与依赖闭包；修订使当前机器审核／人审通过计数按既有失效规则回退，历史“曾处理”事实保留。新内容、增减 locale、改变终点或单位拆分导致范围变化时生成新 `planVersion`，记录旧／新分母、变更原因和单元映射；不覆盖旧快照，也不把两版百分比当同口径连续曲线。

#### 每阶段／语言的可复用数据

| 观察面 | 拟议投影及复用来源 |
|---|---|
| 阶段、语言、工作量 | 沿 [Tracker 账本](four-layer-production-tracker.zh.md)及 [four_layer_progress.py](../scripts/four_layer_progress.py) 的检查点/history/doneUnits/totalUnits，补齐计划单元到 phase/locale/revision 的映射；每格显示上述分开的 done/total、pending/running/failed/unknown 数量 |
| 尝试、阻塞、因果 | 复用 [LOGC-01—07](workflow-accounting-log-contract.zh.md) 与 [RQC 日志 profile](rqc-accounting-profile.zh.md) 的 workUnit/attempt/revision、executionStatus/reviewVerdict/admissionStatus、dependsOn/blockedBy、request/response/reconciliation 身份；显示 retry 数、脱敏 blocked reason 和对应证据，不从缺失日志猜成功 |
| 存活与进展 | 复用 [现有 L2 liveness](canonical-layer2-liveness.zh.md) 的 exact job/request binding、heartbeat sequence、progressSequence 与 policy；同时显示最近心跳、最近真实单元进展、观测时间及 freshness。心跳不增加完成量；其他层无此证据时为 unknown，不宣称全局心跳已接通 |
| 耗时、缓存与资源 | 复用 [记账规则](workflow-accounting.zh.md)、[four_layer_measure.py](../scripts/four_layer_measure.py) 与 [Weekly DAG 投影](../scripts/weekly_pipeline_report.py) 的可信 elapsed、dependency/queue、模型加载、缓存复用及真实并行区间；读取实际 worker/资源容量与队列证据，缺项明确列出 |
| 费用与用量 | 沿既有 provider/SDK 去重口径展示累计 token、`known subtotal`、unknown/conflict/coverage 和额外返工费用；原始尝试均保留。本地缓存不是新模型调用，缺 usage 不补 0，不将模拟费用当真实费用；费用估算、实际账单与预算预留分开 |

聚合只读上述事实，沿已有本地摘要／Weekly report／脱敏 Tracker projection 输出，不将原文、私有路径、完整 hash 或自由错误正文送入公开页面。缺失字段通过既有 producer 计量接线补齐，不能为“补数据”重新调用模型、回填文件时间或改业务身份。重放同一账本应得到相同计数；实时 `updatedAt` 与原事件时间分列，重新渲染不能把旧证据刷新成在线。

#### 剩余 DAG 的资源约束 ETA

1. **明确估计终点。** 以冻结计划的剩余 DAG 和当前有效产物／批准为输入，区分“机器工作到下一门禁”和“到约定交付终点”。真实人审等待、未知外部请求结果、服务中断或不可确定的恢复／发布窗口使受影响的交付 ETA 为 unknown；可以另列已有证据的子图或条件情景，但不能把它标为整轮完成时间。
2. **建立可比耗时样本。** 按阶段、实际模型／runtime、locale、输入长度或组／单元规模、冷／热启动、缓存状态、设备与并发配置分桶。使用完成且时间可信的同类历史服务时长，并由本轮已完成单元更新速率／分布；样本计数按独立完成单元去重。失败尝试／重试退避、排队、人审与模型加载分别估计；正在运行的尝试是未完成观测，不能当成功样本。诊断中的真实模型耗时与模拟步骤分列，模拟人审的零等待不进入真实人审基线。
3. **投影实际可运行的剩余排程。** 串行依赖累加服务／必要等待；真正并行的分支取汇合前最长完成路径。按照实际启用的并发上限、共享 API／CPU／GPU／模型资源、当前占用和前方队列，在依赖 ready 与资源 available 两者都满足后才估计开始时间；资源竞争可使两条业务独立分支串行。队列等待只计一次，不能把父子 span、并行 wall 或资源等待重复相加，也不能因有三个 locale 就假设三路已并发。此排程仅用于估计，不 dispatch、抢占或调整 concurrency。
4. **覆盖恢复并保留未知。** 已验证缓存只估核验／读取成本，不再估完整生成；已确定且获准的剩余返工按真实依赖加入 ETA，但不改 `D0`。未来可能返工只作带假设的范围／情景，不预授重试预算。活动阶段的剩余服务时间按可比已完成单元与实际进展更新；不能因经过历史均值就倒计时到 0。缺依赖、未知队列/资源容量、跨时钟不可信、无完成样本或 stale/outcome_unknown 时，不能伪造完整 ETA。
5. **输出区间与可信度。** 每次估计同时给出 `remainingSecondsRange`／对应完成时间范围、`sampleCount`（历史／本轮、分桶覆盖）、`confidence`、`assumptions`、方法／基线版本、计划版本、`updatedAt` 和输入证据截止时间；说明区间方法与校准误差，区间不是保证。冷启动无可比历史时，仅在有显式人工先验／可解释粗基线时给低置信宽区间，否则 unknown。局部高置信不能掩盖关键路径上的未知；日期用带时区值，不声称本轮已有可用 ETA。

#### 开发顺序与验收夹具（待实现，本文未运行）

按上述更新顺序，先完成 `TRK-002/005b` 的版本化计划／事实映射与缺口标识，再完成 `TRK-003` 的只读进度与 ETA 投影，最后由 `TRK-006`／`SPD-006` 校准历史预测与实测误差。优先重放脱敏固定事件与 fake clock；真实模型／设备验证需按原有任务和预算单独执行，不能由此 backlog 自动发起。

| 固定夹具 | 预期验收 |
|---|---|
| 并行 | A=4 秒、B=6 秒，均无前驱且有独立空闲资源；join=2 秒、依赖 A/B。确定性夹具剩余时间为 8 秒，不是 12 秒；两分支单元各计一次 |
| 串行／实际容量 | 同图但 A/B 共用容量 1 且顺序已知，join 在两者之后：12 秒；不能按 DAG 可并行性忽略资源串行 |
| 排队 | 上述容量 1 的唯一资源还有 3 秒已知占用：15 秒；去掉可靠队列／占用证据则总体 ETA unknown，不能默认立即开工 |
| 重试／修订／缓存 | 原计划两等权单元，A 失败后新 attempt 修复与重审；A 的计划处理量最多 1/2，额外尝试、返工时长及成本单列。旧 hash 审核不能批准新 revision；有效缓存不新增调用／费用，失效缓存不能算复用成功 |
| 状态与人审隔离 | processed 已满而 review 有 needs_rework 或尚无人审，业务仍阻塞；simulatedHumanApproved 增加时 actualHumanApproved 不变，正式包／Gate 不获批准 |
| 心跳与 stale | 心跳递增但无工作进展时完成量不增；超过绑定 policy 的 freshness／no-progress 界限，展示 stale/unknown 原因并撤下受影响 ETA。投影更新不能恢复活性或续期任务 |
| 未知结果／停机／人工等待 | 缺 finish、outcome_unknown、外部 outage 或人审待回复：对应 ETA unknown，保留已知子计数、费用小计与未知缺口；不盲重发、不填零成本或固定人审分钟数 |
| 分母变化 | 冻结 10 个等权单元后计划扩为 12，必须新版本、原因及映射；旧版 5/10 不被改写，新版按映射显示 5/12，不展示成同口径“进度倒退”或隐匿新增范围 |
| 样本与缺测 | 冷启动、只有缓存样本、跨模型／locale／长度不可比、缺时钟或队列证据分别降级低置信／unknown；缺分母显示已知 done/unknown total，不输出假百分比 |
| 重放与行为不变 | 乱序、重复、冲突、迟到收据按现有日志合同处理；相同证据的计数稳定。开／关投影及重放前后，dispatch／模型调用、重试策略、审批、缓存身份、预算预留／消费、业务 artifact 与业务决定完全一致；唯有观测输出可变 |

本项完成需要绑定实现 commit、夹具结果、缺测降级和预测校准报告；文档齐备不关闭 `DEV-TRACK-001`／`DEV-SPD-*`，不提升任何生产或人工验收状态。

<a id="prefect-diagnostic-pilot"></a>

### 有界 Prefect DAG 与 Agents API 只读诊断试点

当前运行证据与未解决项见[三分钟真实诊断 follow-up](#dev-180s-diagnostic-followup)；下方为设计登记时的范围与状态，不能作为当前 live 集成通过的证明。

**2026-10-01 设计登记，状态 `pending`（实现由独立分支交付，本文不声明已接通）。** 这是现有 `DEV-SPD-006` 的窄试接，不新建调度平台或重写 producer。原方案的[顺序](prefect-agents-diagnostic-pilot.zh.md#sequencing)是先完成本地实现／固定夹具，再恢复诊断；用户后续授权继续测试，本轮已通过独立桥接交付 preview，不能据此关闭本项。完整接口、官方依据、失败矩阵和退出条件见 [Prefect + Agents API 试点合同](prefect-agents-diagnostic-pilot.zh.md)。

| 既有子项 | 此次新增工作与验收边界 |
|---|---|
| `SPD6-ARCH-01/02`、`SPD6-READY-02/05/06` | Prefect flow/task 仅包装现有 DAG node、durable job、receipt、预算与 gate；保持单一 controller 执行授权、本地 GPU 容量和人审身份约束。覆盖 API 响应后收据前崩溃、worker 重启、人审等待重启、并发预算争用；未知结果不自动重发付费请求 |
| `DEV-TRACK-001`、`DEV-SPD-002/001`、`SPD6-LOG-01/05` | 复用上节冻结计划／进度／资源约束 ETA 与既有日志，关联 flow/task/job/workUnit/revision；Prefect task completed 不能替代业务完成、机器审核或真实人审 |
| `SPD6-ARCH-03`、`SPD6-READY-07` | Agents API 仅诊断脱敏日志、失败单元引用和版本差异，输出 cause/hypothesis、evidence IDs、confidence、impact、affected units、suggested repair；固定 validator 拒绝过期／越权建议，controller 另行授权执行。诊断 agent 无修改、重试、内容生成、人审或发布权限 |
| `SPD6-LOG-03/04`、`SPD6-VAL-00` | session/turn/call 与证据关联、缺测费用保持 unknown；先运行固定／mock 故障矩阵。当前 $40 运行预算不包含新 Agents API 试点调用，真实诊断调用须另定模型／限制／独立批准预算；本次文档工作无真实测试或模型调用 |

本试点不改变既有 `DEV-EXP-004` Harness/Terra A/B，不启用生产云部署、定时调度或 rollout；真实诊断与生产／设备／现场验收分别留证。

## P2：实验与非阻塞扩展

| ID | 工作 | 当前状态 | 边界 |
|---|---|---|---|
| `DEV-EXP-001` | Gemini 音视频 sidecar／事件分类 | `in_progress` | 继续 Discovery/shadow；没有人工 Gold 和按类别质量证据前，不改写 Layer 1、翻译、TTS 或发布状态。 |
| `DEV-EXP-002` | VoxCPM2、MOSS、AuK 等 TTS challenger | `pending` | 只做同输入盲听 A/B；不能因为短样本更好替换 Qwen3-TTS SFT 正式 checkpoint。 |
| `DEV-EXP-003` | Cloud Run、笔记、金句与历史回放 | `pending` | 不阻塞四层 Dev 周产或独立 live session；引用必须保留 source unit 与 timecode，历史 Cloud 方案不自动成为当前部署方向。 |
| `DEV-EXP-004` | DeepSeek Harness／Terra 调度 A/B | `pending` | 先隔离比较 CUV 状态检查、工具调度和恢复；保持生产翻译／核验模型及人工门禁不变。未测量前不替换正式入口。详见[实验提案](scheduler-harness-ab-experiment.zh.md)。 |
| `DEV-CICD-005` | 评估将受控 CD 迁到 GitHub runner | `pending` | 先证明大媒体候选可恢复、短期凭据、环境隔离、同站点串行、审核收据和回退均可在 runner 重现；未通过前保持本机受控 CD | [CI/CD backlog](ci-cd-backlog.zh.md) |

## 专项文档归属

| 文档 | 现在负责什么 | 不再负责什么 |
|---|---|---|
| [四层制作 Tracker](four-layer-production-tracker.zh.md) | 单次生产检查点、证据、耗时、阻塞和 ETA | 全项目 Dev 优先级 |
| [Layer 2/3 backlog](multilingual-layer-2-3-backlog.zh.md) | 文字与音频 producer 的原子实现、schema 和验收 | 跨层排序 |
| [Layer 4 backlog](multilingual-layer-4-delivery-app-backlog.zh.md) | catalog、发布、Web／App 交互和验证矩阵 | Layer 1–3 优先级 |
| [iOS backlog](../apps/tongxing-ios/BACKLOG.zh.md) | 原生客户端详细需求与平台验收 | 上游内容／音频完成声明 |
| [分支与 Firebase 环境](development-branch-and-firebase-environments.zh.md) | Dev／Production 隔离和晋升规则 | 某次发布已完成的证明 |
| [CI/CD backlog](ci-cd-backlog.zh.md) | 上述 `DEV-CICD-*` 的执行步骤、依赖和验收样例 | 顶层优先级及具体周次／设备的运行状态 |
| [RQC 完整设计](generation-review-gate-design.zh.md)与[开发 Backlog](generation-review-gate-backlog.zh.md) | 生成/只读审核/固定门禁/返工的私有合同、D1—D8步骤及分级验收 | 新顶层排期、生产策略切换授权或任何已完成声明 |

## 历史附录：2026-06-22 11:30 会众中文字幕 Backlog

以下内容保留早期 `live_session` 的需求来源，**不再是当前顶层排期**。仍有效的工作已映射到 `DEV-LIVE-001`、`DEV-EXP-003`；实施前必须以当前 live POC、运行手册和真实现场证据重新校准。

### 产品目标

北星目标：在每周日 11:30 PT 场证道开始时，中文会众可以打开一个稳定、低干扰、可阅读的中文字幕界面，帮助他们在现场听道。

Backlog 排序原则：

1. 先保证 11:30 会众能看到可用中文字幕。
2. 再降低延迟、提高经文/人名/术语准确度。
3. 最后完善离线字幕、笔记、金句和运营工具。

### 当前基线

- 已有静态 Web/PWA 原型，可展示 operator 控制台、证道标题、生成状态、字幕片段、经文 sidebar、VTT/SRT 导出。
- 已有 `prepare_live_link_playback.py`，可从 YouTube live archive link 生成播放模拟数据。
- 已有 GCS 发布参数和 Secret Manager resource name 边界，生成物可进入 GCS，API key 明文不进入 artifact。
- 当前播放模拟仍以可用字幕源为基础；如果只有英文字幕，中文行显示 `AI 中文待生成`，下一步必须接入真实翻译/生成。

### P0 - 11:30 会众可用闭环

#### P0.1 接入真实中文生成链路

目标：把 `AI 中文待生成` 替换为真实可读中文字幕。

开发 owner：Fix/Dev agent  
测试 owner：Review/Test agent  
Debug owner：Fix/Debug agent

验收标准：

- 给定直播链接运行 POC 后，`web/playback-simulation.generated.js` 中每个可展示 segment 有非占位中文 `zh` 文本。
- 英文 sidecar 保留，可用于回查翻译来源。
- 生成失败的 segment 明确标记为 `needs_review` 或等价状态，而不是静默显示空字幕。
- API key 只通过 Secret Manager resource name 配置，不写入 report、manifest、JS、日志或字幕文件。
- 单元测试覆盖：英文输入生成中文占位替换、失败 fallback、secret 不落盘。

#### P0.2 会众视图与 operator 视图分离

目标：11:30 会众看到的是干净字幕页，operator 才看到监控、按钮、日志和导出。

开发 owner：UI/Dev agent  
测试 owner：Review/Test agent  
Debug owner：Fix/Debug agent

验收标准：

- Web 原型至少支持 `operator` 和 `congregation` 两种 view mode。
- iPhone 竖屏会众视图默认只显示证道标题、当前中文字幕、必要经文提示和连接/生成状态。
- 会众视图不显示 `开始监控`、`生成会众字幕`、`模拟播放`、导出按钮、运行日志等 operator 控件。
- iPad 横屏 operator 视图保留监控、发布、review、经文 sidebar。
- 手动 smoke test 覆盖 iPhone 竖屏、iPhone 横屏、iPad 竖屏、iPad 横屏。

#### P0.3 发布状态与 11:25 readiness gate

目标：operator 能在 11:25 前判断是否可以发布给 11:30 会众。

开发 owner：Dev agent  
测试 owner：Review/Test agent  
Debug owner：Fix/Debug agent

验收标准：

- UI 有明确状态：`未开始`、`正在生成`、`可发布`、`已发布`、`需要人工处理`。
- 至少基于 segment 数量、中文可用率、低置信片段数量、证道标题和开始时间存在性，计算 readiness。
- 当 readiness 不满足时，`冻结并发布` 或等价发布动作需要显示原因。
- 当 readiness 满足并发布后，会众视图显示 `已发布` 或等价状态。
- 测试覆盖 readiness pass/fail、发布后状态、缺标题/缺中文/segment 太少时的阻止逻辑。

#### P0.4 GCS artifact manifest 可被 Cloud Run / Web 加载

目标：生成物上传到 GCS 后，前端或服务端可以根据 manifest 找到最新播放数据。

开发 owner：Dev agent  
测试 owner：Review/Test agent  
Debug owner：Fix/Debug agent

验收标准：

- `cloud-manifest.json` 包含 playback JS、report、字幕文件、生成时间、live URL、sermon title、translation status。
- 支持 dry-run 测试，不需要真实上传即可验证 manifest shape。
- 支持真实 GCS URI 的路径规范：`gs://<bucket>/runs/<date>/<session_id>/...`。
- 任何 artifact 都不包含 API key 明文。
- 测试覆盖 manifest shape、路径、secret 边界、dry-run 输出。

### P1 - 质量、延迟与现场可用性

#### P1.1 翻译质量策略：经文、人名、术语优先

目标：字幕不是逐字机器翻译，而是服务听道理解。

开发 owner：Dev agent  
测试 owner：Review/Test agent  
Debug owner：Fix/Debug agent

验收标准：

- 支持术语表输入，至少覆盖 `Numbers`、`Moses`、`Aaron`、`Rebellion`、`Mediator`、`Intercede` 等当前证道词汇。
- 支持经文引用检测并给 segment 附上 `scripture_refs` 或等价字段。
- 术语/经文命中时，中文翻译优先使用固定译法。
- 低置信术语进入 operator review 列表。
- 测试覆盖术语固定、经文命中、低置信标记。

#### P1.2 延迟指标与生成进度可观测

目标：知道字幕是否足够快，能不能跟上现场听道。

开发 owner：Dev agent  
测试 owner：Review/Test agent  
Debug owner：Fix/Debug agent

验收标准：

- segment 数据包含 `received_at`、`generated_at`、`published_at` 或等价时间戳。
- UI 显示最近字幕延迟、平均延迟、最慢片段。
- 当 stable/published 延迟超过目标时，operator view 显示 warning。
- 日志或 manifest 可追溯每次生成的延迟摘要。
- 测试覆盖延迟计算和 warning 阈值。

#### P1.3 Live source monitor POC

目标：从手动 live archive POC 推进到周日自动发现源。

开发 owner：Dev agent  
测试 owner：Review/Test agent  
Debug owner：Fix/Debug agent

验收标准：

- 新增或实现 `live_source_monitor`，检查 Mariners Online、YouTube streams、手动配置 fallback。
- 输出结构化 evidence：source URL、状态、时间、标题、是否同篇证道候选。
- 8:30 失败时自动标记 10:00 fallback。
- 09:58 前没有可用源时生成 operator alert。
- 测试使用 fixture/mock，不依赖实时网络。

#### P1.4 时间轴 review 工具最小可用版

目标：operator 可以修正对齐，而不是只看模拟播放。

开发 owner：UI/Dev agent  
测试 owner：Review/Test agent  
Debug owner：Fix/Debug agent

验收标准：

- 支持单个 segment 的时间平移、split、merge、lock。
- 批量 offset 不改动 locked segment。
- 修改后 VTT/SRT 导出使用 edited timeline。
- UI 在 iPad 横屏上可操作，不挤压主字幕。
- 测试覆盖 offset、lock、split/merge、导出时间码。

### P2 - 离线增强与会后复盘

#### P2.1 证道笔记与金句生成

目标：会后自动生成可追溯笔记、摘要、应用问题和金句。

开发 owner：Dev agent  
测试 owner：Review/Test agent  
Debug owner：Fix/Debug agent

验收标准：

- 从 reviewed/published captions 生成摘要、大纲、应用问题、金句候选。
- 每条金句保留 source segment id、英文原文、中文字幕、timecode。
- 生成结果写入 GCS `insights/*.json`。
- UI notes tab 可以显示生成结果。
- 测试覆盖 schema、timecode、source traceability。

#### P2.2 Cloud Run 部署骨架

目标：让 POC 从本地静态页面走向可部署服务。

开发 owner：DevOps/Dev agent  
测试 owner：Review/Test agent  
Debug owner：Fix/Debug agent

验收标准：

- 有最小 Cloud Run 服务入口，可提供 PWA 静态资源和 manifest/playback 数据。
- 配置说明包含 service account、GCS bucket、Secret Manager 权限。
- 使用 [Cloud Run 部署准备与 Secret Manager 清单](./cloud-run-deployment-prep.zh.md) 作为部署前 checklist。
- 本地启动命令和部署命令写入 README 或 deployment doc。
- 健康检查 endpoint 可用。
- 测试覆盖本地服务启动和静态资源加载。

#### P2.3 历史质量回放集

目标：用多场证道回放持续测试字幕质量和 UI 稳定性。

开发 owner：Dev agent  
测试 owner：Review/Test agent  
Debug owner：Fix/Debug agent

验收标准：

- 至少保存 3 场不同证道的 sanitized playback fixture 或生成命令。
- 每场包含标题、sermon start、若干字幕片段、已知经文/术语样例。
- Smoke test 可以切换 fixture 验证 UI。
- 质量回归测试能发现占位中文、空字幕、时间倒序、secret 泄漏。

### 历史下一步建议

最优先启动 P0.1 和 P0.2：

- P0.1 让当前 POC 从“显示正在生成的字幕”推进到“显示真正中文生成结果”。
- P0.2 让产品形态从 operator demo 变成 11:30 会众可以实际打开的界面。

并行安排：

- Review/Test agent 先为 P0.1/P0.2 写验收测试和 smoke checklist。
- Fix/Debug agent 先检查当前播放模拟、secret 边界、GCS manifest 是否有已知失败点。
- UI/Dev agent 先做 view mode 分离，不要等待完整后端。

2026-09-30 实施证据：[PR #122](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/122) 在 #121 基础上修复 v3 分类/字段/导入校验，新增 E1.2 DAG/slack 与 E1.3 JSON→Markdown 初始投影、E6 commit-bound 保守快照。状态为实现中：模拟单测不是 producer 全覆盖，不是 Stage 0–3 人工 sign-off。真实 source/locales/page-ready 计量、controller/Decision Agent、真实媒体阶段与合同变化后的 decoder 验证仍待后续证据。

E2 后续批次：版本化 action registry 与 opt-in deterministic controller 已开始接入既有 `legacy page_release` adapter；默认 shadow、page_ready hard stop，复用 durable jobs/admission locks/outcome reconciliation。canonical 四层 DAG/三语汇合、E3 Decision Agent、迁移收据与阶段人工验收仍待实现，不能按 legacy fixture 关闭 DEV-SPD-006。

2026-09-30 后续实现证据：canonical 四层/三语定义已有纯 planner；Source/Text/Audio 与现有 formal-dev Release candidate 的真实 validator 已接入[只读 package inspection](canonical-package-inspection.zh.md)，验证独立批准、媒体/时间表/逐句文本与 revision，并保留 lane isolation。E3 已有 bounded packet/allowlist/stale decision 验证及单次注入 responder 的 proposal 接口；E4 已加入真实子进程 crash-window 与 intent/receipt 恢复测试。上述证据是本地 synthetic 测试及 shadow inspection，尚无 canonical durable dispatch、完整跨进程 DAG/accounting、生产 Decision Agent runner、迁移/并发资源策略或 Stage 0 人工 sign-off。E1–E6 子项仍按各自完整完成条件保留未完成状态；真实小片段、10 分钟、历史完整视频、真机与现场验收不能据此关闭。

E1 producer 后续批次：已接入真实 L2 同组翻译→审校 span、L3 模型加载→推理→校验 span，并以缓存恢复与模拟音频测试验证；跨 layer/source/queue 尚不完整，SPD6-LOG-01/03 保持实现中。#122/#123 审查回归覆盖冲突 usage、非法 dependency-ready、shadow 无文件变更以及 bridge/candidate 身份变化，不能替代新 head 独立审查或真实媒体分阶段 sign-off。

E2/E3 契约后续批次：canonical definition 已编码共享 source、zh-Hans/ko/es 独立 Text→Audio→Page、显式 text-only Layer 3 与 delivery terminal 汇合；纯 shadow planner 测试按 source/单语身份失效，不读取 tracker 作为批准。它只消费本地 validator adapter 的观察，尚未接入真实 package inspection/durable dispatch，dispatchEnabled 固定 false。Bounded Decision 契约限制 32 KiB/16 refs/一个 structured turn、两次以内预留预算，固定 failure/action/reason allowlist、hash-only evidence、二次 revision/approval identity 检查，fake responder 与真实锁/预留文件验证 crash 后不重放。未接 SDK、没有付费模型或 mutation tools，返回 proposal 仍须原有锁内业务 admission；不是生产 E2/E3/E4 全验收。

E4 crash-window 证据补充：新增真实短子进程在本地 side effect 已发生、success receipt 写入前/后直接退出的测试；前者返回 uncertain，后者保留 succeeded，复用同一 identity 都不重新执行。另验证 controller 在 durable intent 后/dispatch 前、job success 后/controller commit 前中断并重建实例，均要求 reconciliation、不凭 exit 0 宣布 page-ready。40 项相关本地回归通过；这些是惰性文件 fixture，不代表真实发布、付费模型、真机或人工验收。

Canonical package adapter 第一批：Source/Text shadow inspection 已复用生产 Source/Anchor、完整 source/candidate schema、policy、机器 review 与独立人工 receipt validators，额外核对冻结 transcript 与 source review evidence。纯读取真实路径，输出只含 identity hashes 与固定诊断；缺/过期 policy/candidate/review 按语言阻塞。Audio/Release inspection 与任何 canonical dispatch 仍未接通；文本批准不会生成 voice authorization。

监督执行已启动：先完成第一批三语真实单组验收（六次返回请求，重启零新增），再整合后续修复并运行 fresh 三分钟 Dev 全链路。当前实现与证据边界见[监督验收记录](reports/20261001-dev-diagnostic-supervised-plan.zh.md)。尚未通过整链路或正式门禁的条目继续保持 in_progress / waiting_evidence。

2026-10-01 监督续跑新增实际证据：第四只读Agent合法final=needs_more_evidence（004真实合同验收通过、400根因仍证据不足）；v5历史账本1730059字节/v6 DAG计划559435字节误用private reader分别归006/005，均0新provider；只扩大版本化aggregate读写。v6 blocked状态真实Dev部署、298资产HTTP与Range通过、三语Chrome禁播/无误导通过；安全reason映射及长HTTP数值进度归009/008/013。原生合成与ready完整播放仍待下一恢复，007正式听审/同步/设备/现场未执行。完整收据见监督报告。


## 2026-10-01 监督续跑更新

实施和真实验收以[监督计划及证据](reports/20261001-dev-diagnostic-supervised-plan.zh.md)为准，原问题观察保持原时间边界。

- `DEV-DIAG-004`：真实只读Agent第四phase已完成两次实际工具提交及最终诊断合同核验，唯一root completed；诊断为needs_more_evidence，因为旧HTTP400正文缺失。只读诊断没有生成、人审或发布权限，四phase成本仍unknown，观察预留保留。
- `DEV-DIAG-005/008/014`：v7真实Source-cache→韩语/中文13组最终文字→26个原生WAV→Dev300文件HTTP全部SHA/Range206已经观察。西语派发前守卫失败，三语join仍blocked；Chrome两语仅短播放，整轨三语验收尚待续跑。原sox启动问题在冻结native runtime中已解阻并真实加载/合成；不得继续将两语状态写为原生尚未运行。
- `DEV-DIAG-006/010/013`：新增派发前Git/tree身份witness，守卫内不用Git子进程；精确受控失败blocked，未知结果及日志写失败仍保守处理。Layer2 v2可复用同闭父普通返工最终修订；完整直接原生v3 lane可按worker v4独立历史proof重绑定，必须在新attempt完整冻结后实际复验。旧预算、期限、42项D5未知保留。
- `DEV-DIAG-007`：继续保持waiting_evidence。诊断试听与default-pass不关闭正式逐单元回转写、疑点人工裁决、整轨听审、同步、正式Audio/Release、设备与现场验收。将这些作为正式交付的独立验收项，不能用本次preview验收替代。

本次用户已授权按plan持续开发和续验；下一恢复局部修西语并复用已验证中韩产物，完成同一Dev诊断页三语整轨浏览器播放，再更新上述软件诊断项终态。


### 2026-10-01 监督验收最终对账

`DEV-DIAG-001–006/008–014` 的本次隔离诊断软件范围已完成实现、定向回归和相应真实路径核验；`done`不关闭既有正式Layer1–4/Prefect/Agents执行权限或完整性能项目。旧HTTP400正文缺失，原供应商精确原因仍无法追认。008通过的是已记录因果/终态/单调时钟合同，资源/provider排队没有真实测量；新收尾空档明确留在015，不冒充完整ETA。

- 39组最终机器/完整语言插件/admission通过；v7/v8合计39个真实native单元，本轮13新合成+26缓存完整核验，人审pending。
- Dev301文件HTTP内容SHA/源Range通过；旧295资产无丢失、正式catalog未改。真实Chrome三语音轨和180.013秒源视频均从0、1倍速到ended；旧周次观察5秒进度。初次浏览器工具按钮遮挡/未处理watch退出已保留，只修工具后独立重测，不作为产品故障或人工听审。
- 首次ready汇合的Fresh/legacy Source目录错误已修复。闭父只读恢复检查三语交付通过，0新provider/ASR/Text/TTS/MFA/账本写，原920个证据文件不变。原v8 final=incomplete/失败日志仍保留，恢复报告独立绑定旧执行与新检查器；没有重新发布App中的恢复状态标记。
- 本轮2条provider returned、0unknown、新D5为空；累计业务387请求/84,563,795 microUSD保守占额，Agents四phase8M观察预留另保留，旧42项未知不退款/不补结算。费用缺测仅报已知小计。
- `DEV-DIAG-004`真实只读Agents完成工具提交和final合同核验；needs_more_evidence是缺少原400正文的正确诊断结果，不代表故障根因已确定。Prefect实际SDK引擎测试仍为可选skip，不把固定Python DAG等同引擎验收。
- `DEV-DIAG-007`继续waiting_evidence：正式源文/译文/术语人审、逐单元回转写与疑点裁决、人工整轨听审/语言质量/同步、正式Audio/Release、物理设备与现场逐项验收；诊断default-pass和浏览器播放不能替代。

证据与验证边界统一见[监督最终报告](reports/20261001-dev-diagnostic-supervised-plan.zh.md)。私有模型/媒体/日志/账本留在ignored artifacts，不进入Git。

PR #198 首轮CI进一步发现旧CLI夹具缺runtime/checkpoint声明，补齐后暴露live preflight只读scope遗漏`binding`属性；两项均已修复，守卫不放宽。相关48项回归47通过、1本地可选Prefect SDK跳过，0真实API/模型调用；原失败保留，远程实际引擎及测试结果以最新PR head检查为准。此项归入既有诊断入口修复范围，详见报告的PR CI记录。

收尾head `885d0f1` 的实际Prefect SDK CI157项全部通过，仍只证明模拟/本地回放引擎合同。随后dev合入PR #194图标更新：保留新SVG按钮及diagnostic文案两者，补齐Dev snapshot固定15个UI资产依赖（包括真实旧baseline遗漏的fingerprint-diagnostics.mjs），避免旧baseline缺icons模块/精灵图。此项归入DEV-DIAG-005交付兼容；原v8发布/完整播放版本与新合并代码验证分开，正式catalog/旧媒体/历史证据不改。

最新CI还发现两处旧测试兼容：POC父修订测试误取时钟workload，现精确选render_output；历史actual-trace测试逐项验新增clock/telemetry缺测字段后完整比较旧合同。生产指标、收据守卫和历史报告未变；全POC346项、报告/时钟90项及最终15资产快照20项定向回归通过，原失败保留。

CI环境还暴露工具下载占用原job期限：18ae2f0的root-0已通过1609 tests/8可选skip；Prefect安装阶段被10分钟上限取消，root-1安装后测试被20分钟上限取消，均保留日志且不冒充完整测试终态。仅将CI job上限改为30/40分钟，测试和业务provider预算/期限/守卫不变；归入既有诊断验证接线，最终远程结果以最新head检查为准。
