# 2026-10-05 Dev／正式模型默认值迁移

用户指定的新任务策略已接入 PR #248：[统一模型与 CLI 策略](../production-model-runtime-policy.zh.md)。原 Astra Medium 文字角色为 Sol 6.1 high fast；原 Sol Medium 独立审核为 Sol 6.1 medium fast；Supervisor 为 GPT-6 Luna medium fast。dev、测试与正式本地新任务采用同一参数。文字与监管默认 Codex CLI，API key 仅保留给 Transcribe；不删除 ASR 所需安全凭据，不自动回退文字 API。

## 实现与验证

- 三语 L2 policy 与 component hashes 更新；同模型通过 high／medium 区分角色，payload 和执行身份绑定 fast。历史 fixture／缓存保持原参数，新调用拒绝旧 live 配置。
- 正式非预算 L2 入口使用 CLI，controller 状态绑定 wrapper 保留 CLI decoder、身份及资源钩子。独立 mock 集成走实际 runner→plugin→candidate，人工门禁仍 pending。
- 英文纠错、源稿机器复核、解释、阅读稿、CUV、大纲和片段 POC 默认采用新模型。纯文字入口不为 CLI 读取 API Secret；新 CLI 子进程过滤 API 凭据。
- CLI Supervisor 只接收最小状态、返回结构化操作；本地 ProductionTools 负责审批、lease、阶段去重与完成检查。旧未决会话阻止新会话；旧 API 仅可明确原会话续跑，新 SDK 调用禁用。
- 调用前冻结身份与 started，保存私有原始事件／返回／outcome，未知结果阻断重发。缓存 hash、schema、并发锁、工具拒绝、图片完整传递与 API 输出 cap 前置拒绝均有定向检查。

最终集中回归 **487 passed、214 subtests passed，104.04 秒**，27 个受影响模块的 mock／无效认证派发拒绝检查。`git diff --check` 与模型策略相对链接检查通过；没有本轮新模型质量或速度 benchmark。结果与日志 hash 见[结构化收据](20261005-cli-model-defaults-migration-receipt.json)，原日志在 ignored `artifacts/cli-model-defaults-migration-20261005/validation/`。

## 明确保留的边界

API bounded strict L1／L2 契约仍依赖 provider 输出 token 硬上限和美元预算；CLI 尚无等价适配。这些路径在发送前阻断，L1 在新的审校预算不兼容时亦在 ASR／写产物前阻断，不静默删除预算或回退 API。实际 canonical controller 的预算准入也仍受此限制；新模型默认值接线不代表该入口已可完成全流程。

没有部署／合并、定时任务现场更新、新的完整生产、人工听审、发布或设备验收。本地合成验证不能授予这些状态。旧 API／CLI 结果与批准不就地换成新模型身份。

速度按统一策略表记录：Sol 6.1 high fast 初译已有13组174.709秒、43.39会话输出token/s（扣推理16.52）；Sol 6.1 medium fast 和 Luna medium fast CLI 尚无匹配实测，原 Sol／Luna API 数据不改名充当新速度。

## 验证隔离遗漏

前两轮旧 controller 测试把无 API key 当作零模型派发条件，改 CLI 后该条件失效。`test_actual_worker_cli_without_key_stops_before_any_model_cache` 和 `test_two_real_controllers_launch_one_durable_attempt_and_preserve_failure` 各运行两轮，最多4个可疑 worker 尝试；实际 CLI 发起／完成／token／credit 无独立收据，保持 unknown，不把测试超时等同于未调用。

原 TemporaryDirectory 自动清理后没有恢复出逐次模型收据，未重发。日志 `/tmp/l2-tests.txt` 与 `/tmp/l2-tests2.txt` 已保留并 hash；末次进程检查未见相关 worker 或 CLI。测试已改为明确无效 Codex auth，在构造 transport 时拒绝；最终集中回归另外设置无效 CODEX_HOME 和不存在的 CLI 路径，真实子进程入口不再依赖 API key 缺失。该未知消耗不计成0，也不包含在历史 benchmark 的费用中。
