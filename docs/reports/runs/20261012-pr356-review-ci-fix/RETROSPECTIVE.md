# 复盘：20261012-pr356-review-ci-fix

## 实际覆盖范围

本轮仅执行 #356 修复的离线软件回归，L1–L4 内容生产均未执行。App delivery 使用合成批准夹具运行真实本机子进程，未派发模型、未连接 Spark、未部署或通知，不构成正式批准或交付验收。prompt 检查仅验证指令合同，不证明真实模型质量。

## 结果和结束信号

`outcome.json` 为 pass／exit 0。`tests.log` 记录 53 tests、46 subtests 通过，代码版本为 `793b68b2862054a99fb871b886be853d08105d57`，工作分支已合入 dev 基线 `a217924050d4a101e707de3ed02715331cd6b5d7`。首次修复基线的定向测试为 26 tests、20 subtests 通过；数字属于不同验证范围，不相加。

## 耗时

`timings.tsv` 记录合并基线后四文件回归的进程 wall 为 36.94 秒；pytest 自报 36.48 秒。首次两文件回归 pytest 为 36.78 秒。范围不同，不能据此宣称性能变化；并发子进程等待包含在进程 wall，未独立计量。

## 错误

历史 [Actions run 38293337080](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/38293337080) 的 root-7 唯一失败是两实际 Supervisor CLI 进程准入测试。snapshot 扫描时任务状态尚未写出，随后按当前 key 读取到 queued，却将未完成 bundle 当成失败并要求人工检查，使一个 CLI 退出 2。修复提交 `8e89806a` 对第二次读到的 queued/running 保持 waiting；确定性回归覆盖两种状态，原两进程测试保留并通过。

同一提交修复 review 指出的单复数反向放宽：只容许 ORIGINAL 复数读回单数的未标数歧义；ORIGINAL 单数而回译复数明确仍为 major。中韩字幕及口播 prompt 均覆盖，Spanish 保持原合同。此前真实模型/校准收据属于旧 prompt，不外推到本次修订。

## 占用资源之后才暴露的错误

本轮未占用 Spark、付费模型或部署资源。已将并发快照窗口化为确定性离线测试，后续无需等待 CI 的偶然进程调度才发现该问题。

## 遗留状态

夹具子进程与临时目录由测试清理，未创建正式生产 job hold。忽略目录保留本轮摘要与测试日志。未使用新构建号；线上 Dev 文件及运行状态未在本轮检查。

## 外部可见的变化

仅推送 #356 工作分支至 `793b68b2`，未直接推送受保护 dev/main。此报告单独创建 draft PR，不合并。Firebase/TestFlight/设备播放/现场验收均 not_run。

## 后续

主 Agent 在 #356 核对当前 head 的远端 required checks 后决定合并。新 prompt 的真实付费质量验证须沿新的冻结实现与校准身份独立执行；本报告不授权调用，也不重标旧实测。报告保持 draft 供独立复核。
