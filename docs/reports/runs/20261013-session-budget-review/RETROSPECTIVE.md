# 复盘：20261013-session-budget-review

## 实际覆盖范围

本轮仅执行代码修复和离线测试，未执行 L1–L4 实际内容生产、付费 API/CLI 模型、Spark/GPU、SSH、Firebase 部署、HTTP 线上读回、设备播放或场地验收。模拟 publisher、fake transports 和进程测试均为测试证据。

- #379 `c960a6db8758bb0df0de7b277ec94c0182732ce3`：发布后首次观测版本持久化 pin，重试/核对不允许换版本；只读 GET 重试共享 deadline，剩余 deadline 传给 reader，超时成功也拒绝。离线 publisher 断言 deploy 调用一次。
- #380 `4a84ef3602934550048eac0d531c7ecf9c586cdb`：API/CLI 不占 Spark，以 accounting 输出目录内的 started/returned/unknown 收据阻断未知结果重发；显式真实响应核对后重放，canonical/source-budget/Supervisor 保留原 ledger。GPU 原 Spark gate 保持。本轮没有真实首次模型运行；首次新运行必须使用 fresh 输出目录且不复用旧 cache proof。未知运行不得通过换目录重发。
- #381 `a6e18cd22d1d14fc66af6e4df627026d91839d8e`：新 source-budget ledger v4 冻结 reuse roots，验证已有返回的绑定/来源后以零新增费用复用；任一匹配未知/损坏返回阻断。v2/v3 保留旧字段与行为，显式迁移保留未知与预算。源目录只读，approval/route 在 dispatch 前验证。
- #383 整合 head `d3688e3344cbd6a8cf82bc5b84dd6605d2a0636b`：离线组合测试日志已收集；正式 CI 和 merge 仍 pending。#382 需在 #381 进入 dev 后再验证并生效，本报告将追加其证据。

## 结果和结束信号

| 阶段 | 实际测试终态 | 耗时 |
|---|---|---|
| #379 五个发布相关模块 | 63 passed | 0.57s |
| #380 admission 与九模块兼容矩阵 | 139 passed, 43 subtests passed | 3.46s |
| #381 reuse/settlement/source budget | 44 passed, 8 subtests passed | 0.59s |
| 整合现有 pytest.log | 124 passed, 4 subtests passed | 3.55s |

各组有重叠，不能相加作为唯一测试数。整合 outcome/summary/timings 已绑定该 head，正式 CI queued；不能凭本地组合测试宣称正式合并完成。未启动 Spark，因此没有 round/service-restored 终态收据。

## 耗时

上表是各 pytest 的真实运行耗时；未统计 agent 思考、CI 排队或等待合并时间，也没有可比较的同环境性能基线。不据此宣称速度提升。

## 错误

#379 开发阶段最初使用零 timeout、缺失 pin/finalized/ACTIVE 的 fake fixture，与新真实合同冲突；修正正例和 fixture，保留 initial/development 失败日志，未放宽原 guard。#381 初始迁移测试缺目标目录引发 FileNotFoundError，修正测试准备，保留失败日志。#380 最终离线矩阵通过；没有模型失败或线上部署失败的本轮观测。导出器抽取的 Error-like 行包含故意拒绝测试，不能逐行当作未解决失败。

## 占用资源之后才暴露的错误

没有占用 Spark/GPU，也没有付费 dispatch。新增 admission、reuse identity 与 publication deadline 负例都在 fake/离线场景验证，不声称已验证真实 provider 断线或线上 CDN 收敛。

## 遗留状态

保留 ignored 原始测试目录与失败阶段日志供本地复查；没有本轮远端 job hold、Dev 无引用上传文件或新构建号。报告日志是脱敏副本，规范化尾空格；manifest 原 sha256 保留 source hash，exportedCopy 记录副本 hash/bytes。

## 外部可见的变化

三个修复分支及整合 #383 已推送；dev 合并、#382 最终生效仍 pending。报告本身保持 docs-only draft。部署、线上 HTTP、TestFlight、设备及场地验收均 not_run；未绕过分支保护。

## 后续

主 Agent 等正式 CI 并按序整合 #379/#380/#381 到 dev，再处理 #382；把 #382 tests 与各最终 head/CI/merge/dev 收据追加同一报告。首次真实运行不得使用历史 cache 当作此次代码的证明。此草稿不自动 merge。
