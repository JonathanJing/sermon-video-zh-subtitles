# 复盘：20261017-sidecar-ci-root1-failure

## 结论先行

交付类型：测试。#571 提交 745dea66 的 Python CI root-1 分片失败：701 项运行、1 项失败、3 项跳过，退出码 1。其他分片与聚合在此报告生成时仍在运行；本报告不代表整轮最终状态。来源：[Actions run 39048017127](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/39048017127)。

## 总时间

该分片 382.238 秒；不含 CI 排队、其他分片和修复耗时。

## 各层模型、耗时与速度

L1–L4 均未执行。CI 用合成 fixture；模型调用 0、费用 0。

## 错误

`test_ambiguous_http_and_transport_failures_stay_unknown_without_retry` 将 `pipeline.time.sleep` 打桩，实际改变了进程全局 `time.sleep`。同进程后台线程的轮询调用被误计为 API 重试：断言记录约 99 万次 `sleep(0.05)`。它没有记录额外 provider transport 调用；测试自身同时断言该调用仅一次。修复让 sleep probe 只替换 legacy transport 模块的 `time` 绑定，保留 monotonic，避免修改其他线程。单测和并行后台线程模拟均通过，待新 head CI。

## 可以改进的地方

对并发分片中用于断言“不重试”的打桩，应限定到被测模块绑定，不改全局标准库对象。负责人 #571。

## 实际覆盖范围

本报告只覆盖 root-1 的代码测试失败与本地定向修复；不是 L1–L4 生产、发布或设备验收。

## 遗留状态

等待旧 head 其他分片结束，再推送测试隔离修复并重新运行 CI。没有远程生产作业。

## 外部可见的变化

仅 CI 状态；Dev 发布、TestFlight、设备播放和场地验收均为 not_run。
