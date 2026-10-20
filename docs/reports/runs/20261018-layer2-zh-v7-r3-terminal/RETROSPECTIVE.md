# 复盘：20261018-layer2-zh-v7-r3-terminal

证据见同目录 `INDEX.md`、`manifest.json`、`outcome.json`、`summary.json` 和 `terminal-receipt.json`。

## 结论先行

交付类型为 `four_layer_release` 的 Layer 2 中文生产尝试，终态 `failed`。v7 partial recovery 首轮把旧中文完整轮的 804 个模型角色全部以 `$0 reused` 验真；第二轮 402/402 组完成，395 组通过、7 组仍失败。第三轮在复用同一 job 第二轮新付费响应时以 `layer2_reuse_operation_missing` fail-closed。814/814 预算行均为 succeeded，active=0、unknown=0；没有生成 candidate、语言人审收据、Layer 3 或发布证据。

## 总时间

05:24:18Z–06:38:45Z，墙钟约 74 分 27 秒。该运行未单独记录人工等待；主要时间为两次完整 402 组本地重放、5 组实际修复和第三轮前 9 组重放。

## 各层模型、耗时与速度

L1、L3、L4 均 `not_run`。L2 复用 804 个旧角色，费用 $0；新执行 10 次 production API 调用（5 组 translator + reviewer），输入 23,352 tokens、输出 5,026 tokens、provider wall time 122.572 秒，实际费用估算 $0.108642，保守预留 $0.465166。没有 candidate，因此不能将这些调用写成 Layer 2 完成。

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| L2 round 3 | 前 9 组本地重放后失败 | 同一 job 第二轮的 direct-paid success sidecar 指向当前 destination budget root；`record_reuse` 只扫描外部批准的 reuse roots，报 `layer2_reuse_operation_missing` | 占用资源后；provider 调用前 | 保留 failed job、两轮完整结果和账本；停止重派 | 需加入同 job provenance 定向回归 | P1，待修复 PR |

## 可以改进的地方

| 类别 | 改进 | 依据 | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 预检 | 在进入第三轮前验证 current destination direct-paid row 可被同一 job 幂等复用 | 814 行全部已知成功，但 round 3 在第 10 组前失败 | 在 provider 调用前阻断或正确复用 | Layer 2 integration | P1 修复 |
| 质量 | 对完整人工修订稿建立版本化 manual-revision 接口，独立 reviewer 改字即停 | round 2 仍有 7 组失败，用户批准稿另有 8 处 hash-bound 修订 | 避免覆盖旧响应并保留真实机器复核 | Layer 2 integration | 独立代码 PR |

## 实际覆盖范围

Layer 2 zh-Hans：round 1 为 402 translator + 402 reviewer 角色的 `$0` 复用，391 组通过；round 2 完成 402/402，395 组通过、7 组失败；round 3 完成前 9 组后因 P1 停止。814/814 预算行 succeeded、0 unknown。L1 输入被复用；Layer 3、Layer 4、发布、设备与场地均 `not_run`。

## 遗留状态

旧 job 保持 `failed`，无 active 或 unknown 调用。round 2 的 402 组完整文字、7 组失败证据、用户批准草稿及机器逐字节比较均保留。candidate、language-review 和 partial recovery receipt 不存在；manual revision 仍须正式接入并重新做独立 reviewer/plugin 准入。

## 外部可见的变化

只有本 docs-only 运行报告 PR。没有 Dev 发布、TestFlight、App 页面、设备或场地验收。
