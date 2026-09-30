# RQC 私有运行适配器：当前集成范围与证据

本批连接 PR #164 的 D1—D5 私有接口，保持旧生产默认路径。它不是 D6/D7 验收、付费运行授权或自动 rollout。当前修改为 Python 后端与离线实验诊断，没有新增 Swift/App 客户端行为。

## 已连接的接口

| 接口 | 实际约束 | 当前开发证据 |
|---|---|---|
| `StrictBudgetAdapter.generate/review` | 同一个可信全局预算根；先持久化 reservation/request，再调用注入的单次 transport；稳定 identity 不含输出目录；未知 usage 保持未结算 | 真实文件与模拟 transport，断点、日志失败、恢复、已知拒绝、重复请求限制 |
| `RepairPlanner.plan_group` | 在现有 admission lock 和预算锁内，读取实际候选、完整 review inventory、预算回执、源/policy/rubric；保存单组计划和依赖闭包；实际消费过的失败 fingerprint 跨 revision 保留 | 原候选不变、只创建绑定的新 revision；重复失败及陈旧证据阻断；计划记录进入 LOGC profile |
| `AdmissionBoundary.snapshot/admit/reconcile` | 整个 locale 所有组的当前 generation/review 与 durable ledger；现有公共 Candidate、语言插件、独立人审 receipt；锁内重新加载和 CAS，原子保存唯一 `prepare_layer3` intent | 两组、修订链、遗漏/未知回执、复制目录、并发、commit 前后故障；不产生人审批准 |
| `sermon_strict_layer3_preparation.prepare` | 消费已验证 intent，重新检查整组证据、voice/adapter 输入；生成原有 speech-job schema，固定输出位置；已有 job 丢失或变化时阻断 | 实际 speech-job builder，未知落盘确认后复用同一 job；未启动 TTS/worker；原来的 `synthesisEligible` 门禁保留 |

`BudgetStore` 现在在 reservation 前为所有 pending/unknown 行预留最大合法结果的格式化 JSON 空间；锁竞争不消耗尚未开始的执行许可，不确定持久化仍然消耗许可。内容修订还必须在同一锁内匹配持久化计划、sidecars 和失败 fingerprint，不能提交另一个合法格式的计划绕过 planner。缓存 generator/reviewer 的 terminal envelope 与新返回响应执行同一校验，`length`、`content_filter` 或多 choice 不能变成 machine pass。

只有显式开启 LOGC profile 的调用记录结构化轨迹。没有提供的 dependency/queue/context 不推断为零或独立并行。使用者可传入真实完成 span 的 `depends_on`；修复规划可返回 `completion_spans` 供后续调用引用。候选、Review Receipt、Gate Decision 和 Repair Plan 的安全 hash/状态进入观察事件；完整私有文本不进入这些观察事件。

## 冻结的当前工作清单

| 范围 | 本地实现状态 | 合入/验收仍需满足 |
|---|---|---|
| D1 合同、D2 LOGC、D3 strict adapters | 已与修正后的 D1 `f731e988` 及 D2/D3 提交统一 ancestry | 当前远端 head 的 CI/独立审查；不能沿用旧 head 的结论 |
| D4 公共/human bridge、durable intent、L3 job 准备 | 已连接，上表列出边界 | 当前集成差异审查；默认 canonical dispatcher/rollout 仍未切换 |
| D5 单组修订、review-only recovery、持久化单位/全局预算 | 已连接并有聚焦回归 | 完整跨组自动 dispatcher、模糊范围 proposal 的真实 responder 接入尚未打开；依赖组必须各自具备绑定的计划和证据，不能用一个单组计划授权全部闭包 |
| #174 delivery intent | 已包含 manifest、离线 preflight 和 `freeze_binding/validate_preflight_binding` 实际文件适配器，绑定旧版 source/L2/L3 独立凭据及 release plan | strict-v3 交付显式阻断；尚未安装默认 release hook，完整 L3 资产/voice/时长与发布门禁保留；不能据此关闭整个 DEV-WEEK-001 |
| #170 TTS 诊断 | 包含已审查的纯诊断修复 | fake chunk 检查不代表持续实时性能或实际声音验收 |
| 文档、#168 Xcode 流程 | 已继承 dev 的 #164/#167；#168 由父任务协调 | 不并发重构 README，不据文档标记运行层完成 |

组合检查包括合同、日志 profile/导出、strict adapters、预算、修订、Gate、L3 job 准备、交付意图和实验诊断。另有 122 项旧 producer/policy、speech-job、accounting/Weekly 与交付绑定兼容检查通过；57 项终态修复、30 项预算修复原分支检查通过。它们使用合成 transport/批准 fixture；不是完整 Stage 0 acceptance，也不是 fresh 3 分钟内容生成。远端 CI 和最终组合检查数量以对应 commit 的 PR 证据为准。

## 保留的实际门槛

- 先由父任务核对当前所有 PR 的完整范围、依赖、审查和 exact-head CI，再协调合入 dev；本分支不自行合并。
- 统一从固定 dev 开始完整测试仍等待该集成完成。D7 fresh 3 分钟 → 10 分钟 → 完整视频逐级 sign-off 保留。
- 真实 metered transport 尚未执行。预算配置中的 approval hash 是引用，不能自行证明已授权；可信调用者仍须提供已批准的总额、模型/输入范围和真实 usage resolver。缺失费用/token 不填零，不用 reservation 上限冒充实测值。
- 人工窗口/译文/音频审核、voice 授权、MFA/对齐工具、真实 decode、HTTP/QR、设备与现场指标分别验收。App 安装版本不会因这些后端代码变化自动更新；本批无新增 native 改动。
- 所有新接口为显式 opt-in；没有 merge/main、production deploy、App Store 发布或真实付费调用。
