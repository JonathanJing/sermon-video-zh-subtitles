# 复盘：20261018-field-venue-sync-ios-ci

## 结论先行

交付类型为 CI 测试。#1019 合并 `dev` 后的精确 head `1e7a024620645a28946cc3eba01675a80b86b459` 对应 [Tongxing iOS run 39108155412](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/39108155412)，工作流终态成功。`changes` 与 `native-client` 成功；`contract-validation` 和完整 `ios-validation` 按路径及草稿 PR 路由跳过。这不是完整 iOS 构建、模拟器、真机或场地验收。

## 总时间

导出的 `outcome.json` 未记录起止时间或阶段计时，本报告不提供可审计总耗时。GitHub 工作流页面保留各 job 时间。

## 各层模型、耗时与速度

| 阶段 | 结果 | 模型、费用与速度 | 证据 |
|---|---|---|---|
| iOS 路由与 native-client | 成功 | 无模型；速度未测量 | `outcome.json`、工作流链接 |
| 完整 iOS/共享合同验证 | 跳过 | 无模型 | `outcome.json` |
| L1–L4 真实生产 | `not_run` | 无本轮供应商请求或结算 | `outcome.json` |

## 错误

本次工作流无失败。完整 iOS 验证的跳过是现行范围路由结果，不是通过证明。

## 可以改进的地方

报告 iOS 状态时保留 job 级别结果，避免把工作流成功误写为模拟器或真机通过。#1019 的代码修改仅涉及场地实验入口，后续真实设备验收需要单独证据。

## 实际覆盖范围

执行了 iOS 工作流的变更判定与 native-client 汇总。未执行完整 iOS 验证、真实媒体、Spark、付费请求、Dev 发布或设备与场地验收。精确 head 的 Python CI 另行记录。

## 遗留状态

#1019 中旧 `scripts/` facade 的字节变化会影响 L2 的 `code_identity()`，不能沿用旧哈希绑定收据。只读预检发现活动 L2 worker，代码 PR 保持未合并，待终态与冻结 checkout/收据绑定核验。

## 外部可见的变化

只有草稿 PR 与 CI 状态可见；无 Dev 发布、TestFlight、HTTP 读回或设备验收。
