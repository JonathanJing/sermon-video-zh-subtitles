# Canonical Layer 2 已完成产物的显式对账

固定 L2 worker 可能已保存有效 candidate，却在写 durable job 最终状态前退出。原控制器会保留 unknown/failed 并阻塞。本入口只解决这个窗口：在当前 Source、policy、plugin、候选及原执行身份仍匹配时，明确记录已有产物足够完成该 canonical 节点。不会再次运行模型、plugin、worker，也不会创建人工翻译批准。

## 使用与身份

先通过 [L2 controller](canonical-layer2-controller.zh.md) 默认 shadow 获得当前 `stateRevision`，检查对应候选及原 job 证据，再显式调用：

```sh
python scripts/canonical_layer2_reconciliation.py \
  --config /absolute/execution.json --locale zh-Hans \
  --expected-state-revision <shadow输出的精确stateRevision>
```

这是固定本地工程操作，不是自动 tick 或 bounded agent 的默认重试。API 不接受任意状态、路径、argv、人工批准或错误豁免。只有同一配置/代码、相同固定 worker 命令、相同 request/state 和已验证当前候选可以对账。代码升级导致 command identity 改变时拒绝；跨版本迁移没有因此实现。

依次持有现有 admission lock、原 job lock、输出 work lock；活跃 owner 或 writer 无法被对账。准入时再次验证完整 revision，取得 job lock 后核对已绑定的 request/state hash、完整 package revision 与各 producer gate。自身持有 job lock 不能被误认作原 worker 复活，因此先做只读 revision 核对，再在锁内对原始文件身份做比较。

## 原始事实与对账结果分开

不会把原命令状态改成 `succeeded`：该状态仍只表示进程零退出。原 `request.json`、`state.json`、`worker.log` 不改写；新增 `canonical-reconciliation.json` 绑定原 request/state、节点身份、候选 hash、配置/代码身份。

收据在原 job lock 下原子保存并 fsync 文件与目录祖先。重复请求仅接受完全一致的已有收据并补做持久化，不覆盖历史；旧 revision 的重复操作拒绝。写入失败不重新执行模型。

只读 projector 每次核对收据、原始文件和当前候选。成立时 canonical job 显示 `artifact_reconciled` 并同时保留 `originalJobStatus`；机器候选后继仍停在人工翻译审核门槛。候选丢失/变坏、Source/policy/身份变化、收据不一致或活跃 owner 都不能用旧收据解锁工作。failed/unknown 但没有有效候选的情况继续阻塞，不扩大重试预算。

## 验证边界

回归使用实际 L2 runner/plugin/候选 validator 与固定合成模型响应；覆盖完成产物后的崩溃状态、原命令失败保留、缺/坏候选、过期 revision、锁冲突、状态变化、损坏收据、原子写与 fsync 失败、幂等恢复、双 CLI 竞争（空 API key）和只读文件不变。

这不对账一个已经发出但没有返回收据的模型调用，不重构缺失 candidate，不修复失败 group，不证明翻译质量或人工批准；更不是通用 Layer 3/4、部署、未知付费调用或跨版本迁移。完整 Stage0 与真实媒体验证仍未完成。
