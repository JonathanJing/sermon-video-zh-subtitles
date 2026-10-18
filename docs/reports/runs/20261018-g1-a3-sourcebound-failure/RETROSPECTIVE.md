# 复盘：20261018-g1-a3-sourcebound-failure

证据：同目录 `INDEX.md`、`manifest.json`，以及子目录 `g1-a3-sourcebound-failure/outcome.json`、`g1-a3-sourcebound-failure/summary.json`。

## 结论先行

交付类型：本机定向代码测试。本轮定向检查失败，4 个 source-bound 用例暴露新 worker 身份与旧 timing-only 兼容的范围冲突，并在 CPU 线程发现搬迁后 validator 门面首次导入问题；随后修复并另行验证。

## 总时间

未保留精确开始与结束时间；pytest 输出只保留本次结果，不据此推断性能变化。

## 各层模型、耗时与速度

| 层／阶段 | 状态 | 模型、调用、耗时、速度、费用 | 证据 |
|---|---|---|---|
| L1 来源 ASR、MFA、机器评审 | not_run | 无 | summary.json |
| L2 初译、独立审核、文本质检 | not_run | 无 | summary.json |
| L3 配音、回转写、音频质检 | not_run | 无 | summary.json |
| L4 构建与发布 | not_run | 无 | summary.json |
| 本机 pytest | fail | 无模型和费用；4 failed, 15 passed | outcome.json、summary.json |

## 错误

失败为 `diagnostic_resume_identity_changed` 与并发首次导入的 `ImportError`；旧运行应留在冻结 checkout，validator 改走包内实现。

## 可以改进的地方

预检：A3 搬迁时把诊断 worker 的真实实现身份、旧运行恢复边界和多线程首次导入纳入定向检查；负责人：G1 集成；跟踪：PR #570/#579。

## 实际覆盖范围

命令与测试文件见 summary.json；没有真实音频、模型、付费请求、校准、豁免或发布检查。

## 遗留状态

本轮结果与前后轮次分别记录；完整 exact-head Python CI 和 iOS workflow 另行判断。

## 外部可见的变化

只有本地代码测试收据；无 Dev 发布、TestFlight、设备播放或场地验收。
