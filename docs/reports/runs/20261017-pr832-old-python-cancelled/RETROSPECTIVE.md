# 旧 head Python CI复盘

## 1. 结论先行

交付类型：`test`。取消；workflow 终态为 `cancelled`，绑定 head `d97938c34ed6972dbf5a2307d913d5b4f96b4fa1` 和 [GitHub Actions run](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/39075673268)。旧 head d97938c3 被后续提交取代，8 个 root 测试分片取消；unittest 汇总门禁因预期的分片 success 未出现而失败。此结果没有证明测试断言失败。 这只是 CI 证据，不代表生产 CUV 运行或交付验收。

## 2. 总时间

GitHub 的创建到更新时间为 366 秒（2026-10-17T22:35:11Z → 2026-10-17T22:41:17Z）。无独立 journal，无法拆出计算、排队等待或返工；与旧 run 的耗时不作性能比较。

## 3. 各层模型、耗时与速度

L1–L4 模型、音频和发布阶段均 `not_run`；这次 CI 没有真实模型调用、token、费用或速度数据。各 job 终态如下：

| Job | 终态 |
|---|---|
| changes | success |
| test-group (root-5) | cancelled |
| test-group (root-1) | cancelled |
| test-group (root-7) | cancelled |
| test-group (root-3) | cancelled |
| test-group (root-4) | cancelled |
| test-group (root-0) | cancelled |
| test-group (root-2) | cancelled |
| test-group (root-6) | cancelled |
| Native and shared client contracts | skipped |
| unittest | failure |

## 4. 错误

unittest 汇总门禁失败的直接原因是 root 分片被取消后结果为 `cancelled`，不满足 `success` 条件；后续新 head 的 CI 是修复后的判定来源。

## 5. 可以改进的地方

在报告中保留取消原因与旧 head，避免把门禁失败误判为测试断言失败；不因此重派旧 head。

## 6. 实际覆盖范围

root-0…7 为 cancelled，changes success，unittest failure；需要看新 head 的 Python 终态。 L1–L4 生产链路均未执行，旧缓存和收据未改动。

## 7. 遗留状态

取消后的测试结果不能用于验收；等待 586dd21a 同工作流。 没有本次产生的 Dev 文件、音频、hold 或构建产物需要清理。

## 8. 外部可见的变化

没有 Dev 发布、TestFlight 构建、设备播放或场地验收；也没有绕过分支保护的推送。报告为只读 CI 摘要。
