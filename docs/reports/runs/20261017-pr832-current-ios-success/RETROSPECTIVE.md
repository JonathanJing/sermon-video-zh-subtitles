# 当前 head iOS 路径门禁复盘

## 1. 结论先行

交付类型：`test`。成功；workflow 终态为 `success`，绑定 head `586dd21a763ba832b8d39c6d0c067f7357f888c6` 和 [GitHub Actions run](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/39076056506)。changes 与 native-client 成功；ios-validation 和 contract-validation 按变更范围跳过。 这只是 CI 证据，不代表生产 CUV 运行或交付验收。

## 2. 总时间

GitHub 的创建到更新时间为 19 秒（2026-10-17T22:40:53Z → 2026-10-17T22:41:12Z）。无独立 journal，无法拆出计算、排队等待或返工；与旧 run 的耗时不作性能比较。

## 3. 各层模型、耗时与速度

L1–L4 模型、音频和发布阶段均 `not_run`；这次 CI 没有真实模型调用、token、费用或速度数据。各 job 终态如下：

| Job | 终态 |
|---|---|
| changes | success |
| native-client | success |
| contract-validation | skipped |
| ios-validation | skipped |

## 4. 错误

本 workflow 无失败 job。跳过的验证按路径门禁处理，不计为通过。

## 5. 可以改进的地方

继续按 head 与 workflow run ID 分别存档终态，避免把路径跳过项写成 iOS 验证完成。

## 6. 实际覆盖范围

iOS 编译／设备验证未执行；这次成功只覆盖路径门禁。 L1–L4 生产链路均未执行，旧缓存和收据未改动。

## 7. 遗留状态

Python 和 Prefect mock 工作流另行核对终态。 没有本次产生的 Dev 文件、音频、hold 或构建产物需要清理。

## 8. 外部可见的变化

没有 Dev 发布、TestFlight 构建、设备播放或场地验收；也没有绕过分支保护的推送。报告为只读 CI 摘要。
