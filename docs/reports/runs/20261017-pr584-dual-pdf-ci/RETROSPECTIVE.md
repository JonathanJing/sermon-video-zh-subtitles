# 复盘：PR #584 双 PDF run_status 底层迁移 CI

## 结论先行

测试交付。PR head `dd49c7fe4bf9c9fcf76286f1dcb6d177e2890392` 的 GitHub Actions Python tests run `39064539058` 成功：8/8 root 分片与 unittest 汇总通过。此提交包含最新 `dev` 的合并和底层 `run_status` 工具迁移。工作流的 Native and shared client contracts 按路径规则跳过，同 head 的 Tongxing iOS native-client 单独成功。

## 总时间

CI 从 2026-10-17T19:55:34Z 到 20:10:48Z，约 15 分 14 秒，含排队及执行。收据未拆分计算和等待时间。

## 阶段与成本

本轮为代码 CI，L1–L4 均 `not_run`。未运行生产模型或付费提供方，收据无 token、音频速度或费用。

## 错误与处理

本轮无失败。合并 `dev` 后另以当前工作树确认包路径并运行 55 个定向 unittest；相关合并回归见此前报告 #768。该本地检查与本轮完整 CI 是不同证据。

## 实际覆盖范围

完整 Python CI 分片和汇总通过。CI 不证明真实双 PDF 生成、发布 HTTP、设备或场地验收；上层四个待合并 PR 也不由此底层 CI 单独覆盖。

## 遗留状态与外部变化

代码 PR #584 待合并，随后需顺序处理 #594、#598、#602、#607。无发布、TestFlight、HTTP、设备或场地验收；本轮无外部可见内容变化。
