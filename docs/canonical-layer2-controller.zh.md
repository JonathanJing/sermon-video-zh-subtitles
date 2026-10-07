# Canonical Layer 2 固定执行适配器

这是四层 controller 的第一条真实 producer dispatch 路径，不是完整四层 end-to-end。
它复用已有 Source/候选 validator、Astra → Sol group runner、语言插件、paid cache、
`sermon_workflow_jobs` 与 work/admission locks。它只生成
`machine_review_pass_human_review_pending`、`releaseEligible=false` 的候选；不会创建人工
批准、启动 TTS、构建/发布页面、提交 App Store，或调用 bounded decision agent。

默认配置 `sermon-canonical-layer2-execution-v1` 只接受以下字段：

```json
{
  "schemaVersion": "sermon-canonical-layer2-execution-v1",
  "productionRunId": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "inspectionConfig": "inspection.json",
  "jobRoot": "production-run/jobs",
  "locales": {
    "zh-Hans": {"outputDirectory": "production-run/text/zh-Hans", "plugin": "pinned-zh-plugin.py"}
  }
}
```

示例 run ID 仅演示格式；真实 run 需按冻结计划绑定来源/业务范围，所有修订保留同一 job root。
inspectionConfig 使用现有 v1 Source/Text inspection 合同，已批准 Source/anchor/policy
必须可由真实 validator 验证。可选的既有 candidate 路径只能指向该 lane 的 `candidate.json`；
该注册输出尚未存在时作为待生产节点，存在但无效时阻止覆盖。其他已完成 locale 可以保留在
inspectionConfig 而不列入本批执行 lanes。每个 lane 输出、输入及 job root 不得互相覆盖。
配置不能给任意 argv、model、secret 或 approval override。

```sh
# 默认只读：不建 job/lock/output，不读取 API key。
python scripts/canonical_layer2_controller.py tick --config /absolute/execution.json

# 只在该次来源、生产预算与运行授权已具备后使用；可能调用既有生产 API。
python scripts/canonical_layer2_controller.py tick \
  --config /absolute/execution.json --mode deterministic_execute
```

一个 tick 至多派发一个固定 worker 然后返回。第一版同一 production run 至多一个 active
locale job；uncertain owner 继续占用该名额直到 reconciliation。当前 controller 代码允许冻结 policy 的 1–16 个组 workers，共享 job-root 对应的 API 槽位最多 24 个；独立 `run_target_language_models.py` CLI 仍限制 1–3 workers。API 槽位不等于 Codex CLI 账号并发额度，也不是跨所有 job-root 的全局 API/TTS 资源调度器。见 [并发实现](../scripts/layer2_api_concurrency.py) 与 [controller 准入](../scripts/canonical_layer2_controller.py)。
显式并发配置使用新的 `sermon-canonical-layer2-execution-v2`，在 v1 字段上增加 `concurrencyProfile` 和 `resourcePolicy` 两个文件路径；v1 不接受这两个新字段，也不会自动升档。迁移时创建新配置与运行身份，绑定文件内容 hash，勿修改旧 job 的容量／凭据／输出目录。当前 profile v1 将最多活动 locale 升到 3，CLI 业务池 23、监督专槽 1；uncertain 仍阻止整个 run 的新派发。正式预算／批准仍须各自通过，详见[本轮诊断准备](reports/20261005-next-concurrency-test-preparation.zh.md)。

默认顺序是排序后的可准入 locale，没有循环轮询或无限 Agent 对话。工作中可重复调用 tick
检查，但 active/failed/unknown durable receipt 不会产生第二个相同工作。

准入在既有持久锁内重新检查完整 package/job revision、固定模型策略、plugin hash 和
输出位置；worker 再验证实际 durable request/运行 owner、配置/代码闭包、node/upstream
身份，并持有 canonical output work lock。运行代码/配置不得在中途改写：worker 在每个
外部模型调用前及最终候选准入前重新核验。身份变化立即阻止后续调用；已返回的模型结果
保留在既有缓存，不能靠重新 tick 自动付费重试。未知结果仍需显式 reconciliation。

固定代码闭包包括 scripts Python、schemas JSON 和共享术语表；plugin 另绑定实际字节。
控制器不暴露任意命令接口，public result 不含源文本/路径/凭据。worker 日志仍是私有本地
job evidence。正式 CLI 只在实际生产 gate 后读取既有 `OPENAI_API_KEY`，不会保存它。

本批验证界限：真实双控制器/worker 进程使用空 key，证明重复准入和缺配置失败保留；
成功模型路径由注入式固定响应驱动实际 runner/plugin/validator；三语合成回归各完成 4 次假响应后全部停在人工翻译审核门槛。没有真实模型 token、
付费金额、翻译内容质量或现场验收结论。候选 admission 的独立 deterministic 计时 run
消费已完成模型 evidence，不伪造跨进程四层关键路径。

仍未完成：Layer 1 生产 dispatch、Layer 3/4 adapters、显式 unknown-outcome reconciliation/
版本迁移、局部失败 repair 接线、完整跨进程 DAG/usage、全局资源与 stage heartbeat、
生产 bounded responder、完整 Stage 0 及按顺序的真实片段/10分钟/整篇/第二周和人工签字。
一般 canonical planner 仍 `dispatchEnabled=false`；只有该显式 opt-in 固定 L2 adapter 获得
上述有限执行路径。三层架构与所有质量/批准 gate 不变。

## 已有候选的显式恢复

若 owner 已退出但当前候选完整且通过原 validator，可用 [固定 L2 产物对账](canonical-layer2-reconciliation.zh.md) 显式绑定当前 stateRevision。它保留命令原始失败/未知状态并新增独立不可变收据，不自动重试，不消除缺失产物或未知付费调用的门槛。没有有效候选的失败仍阻塞；跨版本与 group repair 继续未完成。

若候选缺失但原执行的所有模型响应均完整返回，可先用[cache-only 本地恢复](canonical-layer2-cache-recovery.zh.md)重建证据与候选，再独立对账。任何未返回调用继续阻塞；不会扩大重试预算。

## 运行心跳边界

固定执行路径绑定[专项心跳与无进展超时](canonical-layer2-liveness.zh.md)：command startup 60 秒、heartbeat 30/90 秒、no-progress 900 秒，以及原总上限。超时仍是需要对账的未知结果，不重新派发；默认 shadow 保持只读。L1/3/4、全局资源与真实吞吐验收没有因此完成。
