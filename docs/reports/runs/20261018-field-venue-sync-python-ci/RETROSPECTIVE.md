# 复盘：20261018-field-venue-sync-python-ci

## 结论先行

交付类型为代码测试。#1019 与 `dev@909d1eab` 同步后的精确 head `1e7a024620645a28946cc3eba01675a80b86b459` 在 [Python CI run 39108155476](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/39108155476) 完成且成功：8/8 root 分组与 `unittest` 汇总均成功。Native/shared contracts 按改动范围跳过。当前 head 的 Codex 代码与安全审查因账户用量上限未能执行；旧 head 的通过结果不能移作本次审查。CI 通过不代表真实声学或生产验收。

## 总时间

导出的 `outcome.json` 未记录起止时间或阶段计时，本报告不提供可审计的总耗时与跨轮速度比较。GitHub 工作流页面保留各 job 时间。

## 各层模型、耗时与速度

| 阶段 | 结果 | 模型、费用与速度 | 证据 |
|---|---|---|---|
| Python CI root-0–root-7、`unittest` | 成功 | 无模型；速度未测量 | `outcome.json`、工作流链接 |
| Native/shared contracts | 跳过，按改动范围路由 | 无模型 | `outcome.json` |
| L1–L4 真实生产 | `not_run` | 无本轮供应商请求或结算 | `outcome.json` |

## 错误

本次 Python CI 无失败。当前 head 的代码与安全审查请求因账户用量上限失败，属于未完成审查，不是代码发现；没有重试或启用付费额度。此前已解决的三条兼容性 P2 仍保留在 #1019 的历史审查记录。

## 可以改进的地方

审查用量不可用时，应把当前 head 标为未审查，并保留明确的精确提交 CI 收据；不要借旧 head 的审查结论。后续整合由代码 PR #1019 跟踪。

## 实际覆盖范围

执行了 Python CI 全部八个 root 分组及汇总；本地 Node 15/15、旧 CLI 与合成音频检查另见报告 PR #1069。未执行真实媒体、Spark、付费请求、完整 iOS 验证、设备或场地验收。

## 遗留状态

当前 L2 `code_identity()` 哈希所有 `scripts/**/*.py`，旧 facade 的变化会改变新运行的 L2 代码身份。只读预检在先前暂停收据后发现三名活动 L2 worker；#1019 保持未合并，直到其终态及冻结 checkout/收据绑定核验。此 CI 未触碰生产运行。

## 外部可见的变化

只有草稿代码/报告 PR 与 CI 状态可见。无 Dev 发布、TestFlight、HTTP 读回或真实设备验收。
