# 复盘：20261017-field-venue-alias-exact-head-ci

## 结论先行

交付类型为代码测试。PR #1019 的精确 head `f5664cb8e28733f0971d5923fc81228e3fcf8491` 在 [Python CI run 39094839657](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/39094839657) 完成且成功：8 个 root 分组与 `unittest` 汇总均成功。当前 head 的代码和安全审查均无发现；三条先前 P2 讨论已回复并解决，未解决线程读回为空。这个结果只证明该提交的代码与模拟测试，不是实际声学或生产验收。

## 总时间

导出的 `outcome.json` 没有起止时间或阶段计时，本报告不提供可审计的总耗时和跨轮速度比较。GitHub 工作流页面保留各 job 时间。

## 各层模型、耗时与速度

| 阶段 | 结果 | 模型／成本／速度 | 证据 |
|---|---|---|---|
| Python CI root-0–root-7 与 `unittest` | 成功 | 无模型；速度未测量 | `outcome.json`、工作流链接 |
| Native/shared contracts | 跳过，按改动范围路由 | 无模型 | `outcome.json` |
| L1–L4 真实生产 | `not_run` | 无本轮供应商请求或结算 | `outcome.json` |

## 错误

本次当前 head 的 CI 无失败。前两个提交的兼容性 P2 已通过 `f5664cb8` 的确定路径模块别名、旧导入名注册和定向回归修复；旧 head 的 CI 被取消，分别见报告 PR #1027、#1030，不能作为当前通过证据。

## 可以改进的地方

后续迁移 Python 脚本时，同批核验 CLI、普通导入、赋值、通配符导入与 pickle。#1019 当前回归已覆盖这些旧接口；真实音频质量需另行授权评估。

## 实际覆盖范围

执行了完整 Python CI 的八个 root 分组和汇总。另有本地 Node 15/15、缺参 CLI 和一次性合成音频比较，见报告 PR #1029。未执行 Spark、真实媒体、现场设备或 L1–L4 生产。

## 遗留状态

当前 `packages/production/src/tongxing_production/text/controller.py` 的 `code_identity()` 哈希所有 `scripts/**/*.py`。因此本次旧 scripts facade 修改会改变新运行的 L2 代码身份；旧哈希绑定收据不能直接移用于新身份。活动中的真实 L2 运行达到终态并核验冻结 checkout 与收据绑定之前，#1019 不应合并。本报告没有触碰该生产运行。

## 外部可见的变化

无 Dev 发布、TestFlight、HTTP 读回、设备或场地验收。#1019 与本报告 PR #1038 仍为草稿，均未合并。
