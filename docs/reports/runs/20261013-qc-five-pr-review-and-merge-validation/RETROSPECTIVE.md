# 复盘：20261013-qc-five-pr-review-and-merge-validation

## 实际覆盖范围

本报告汇总 #367、#369、#370、#371 的离线修复回归及五个 PR 组合树的定向测试。各阶段使用合成媒体、fake transport 或本机程序合同；没有新增真实模型请求、付费调用、Spark 运行、部署、通知、设备或现场验收。测试通过不证明音频质量或正式发布。

用户此前执行的真实模型运行使用未推送的本地组合实现，不能作为最终 dev／整合代码的正式验收。最终代码的实施闭包、规则与校准身份改变后，必须对实际绑定产物重新校准并签发新的 artifact-bound waiver；旧真实模型证据、旧豁免和本报告离线结果不能替代它。

## 分阶段结果与源码身份

| 阶段 | 冻结源码 | 已完成验证 | 时间 |
|---|---|---|---|
| #367 screening review | `9e29a875dee36a709d5040fd37eee45c851b4413` | audio package 单文件 47 tests passed | 27.68 s |
| #369 规则恢复及边界修复 | `dd9e3ceb72ccc606991d0881420e69b5a6566e03` | 六文件 core 635 tests／14 subtests；transport 定向 1 passed／13 deselected | 38.99／0.21 s |
| #370 校准与预检 | `909527694d91643f715f5be1d5b4b2c2d4b65197` | 四模块 126 tests／52 subtests；专门文件 7 tests；最后 require_audio 兼容断言 1 test | 968.04／10.28／0.17 s |
| #371 page-ID 预检 | `db76ad17f6b8ce59cdadeafc2de30b3b4a7507a0` | delivery driver 单文件 17 tests passed | 0.27 s |
| 五 PR 组合定向测试 | `978357084740264d439129382239f3c249577363` | 六模块 647 tests／3 subtests passed | 39.32 s |

这些数字有重复范围，不相加。#370 联合测试收集后又补充 producer／release-consumer 断言，最终专门文件和最后 require_audio 断言分别复验，联合测试期间实现代码未变。五 PR 组合 647／3 只绑定 `97835708`；#374 后续边界修复及 backlog 会产生新 head，不能声称这个组合测试已在最终 head 重跑。远端 required checks 和整合最终终态待主 Agent 另外确认、追加收据；本报告不宣称代码已合并。

## 错误、修复与保留的失败

- #367：评分前核对 v2 settings digest 和当前实现闭包；v1 保留从固定历史源码核实的 ratio／短句精确行为。离线 package 测试不替代真实 ASR 验收。
- #369：旧冻结政策保持 v2 book-only 行为，新任务使用规则 v3；export、cache、length 与 calibration transport 遵守原政策。计数名词及完整数字 token 的尾链边界修复。初始广范围运行出现四处失败（两个 fixture 预期、两个数字尾链转换），修复后再验证；初始矩阵在慢驱动测试前中止，`pytest-initial-fail-interrupted.log` 保留 4 failed／634 passed／14 subtests，105.30 秒，不能冒充完成回归。后续分数边界补丁不由此阶段验证。
- #370：短中文单元原先消耗 truncation trial 名额；现在跳过后继续扫描到有效名额满或输入耗尽。新 receipt 为 calibration-v3，v2 无排除字段按原语义及哈希守卫读取，v2 带新排除字段、v1 或过期实现拒绝；需要新语义时重新校准，不能只改 schema 标签。全短中文在创建 judge／transport 前拒绝。开发测试首次错误地比较跨 schema 的完整 JSON hash，相应失败日志保留；最终要求 artifact hash 不同、准入摘要相同，未因此放宽实现守卫。
- #371：真实入口在创建资产／publisher／seal 前拒绝已存在的 machine-only v4 page ID；模拟路径保留原 v3 行为。该预检结果不是一次实际部署。

## 耗时与资源边界

上表为各阶段 pytest／记录的进程时间，保留各自口径，不比较速度或宣称性能提升。等待、CPU 与各子进程时间未完整拆分。#370 离线 fake calibration 联合运行约 16 分钟，不是模型延迟。没有新增 API 费用；未从缺失成本字段推算真实历史账单。

## 占用资源之后才暴露的错误

本轮没有真实 Spark、模型或部署资源占用。错误在离线负例、身份变异与预检合同中发现；缺失的真实校准和发布证据保持未完成，不要求为了报告重跑付费阶段。

## 遗留状态及外部可见变化

本地保留各阶段 ignored artifacts 与失败日志。此报告仅创建独立 docs-only 草稿 PR；不修改 Firebase／TestFlight，不产生正式 job hold 或新构建号。真实线上内容、设备播放与现场状态未在本轮检查。主代码分支及 #374 的合并／CI 终态与本报告分开记录；报告保持草稿、不合并。

## 报告副本与后续

报告使用 export_run_digest.py 导出并脱敏；仅清理导出日志副本的行末空白，不改变原运行文件或失败语义。manifest 的 sha256／bytes 保留来源含义，规范化副本另记 exportedCopy.sha256／bytes／normalization。

主 Agent 负责最终 #374 head、CI 终态及基线晋升；收到最终证据后在本报告追加对应收据，不覆盖旧阶段。正式生产负责人须在最终实施身份下完成实际产物重新校准和新 waiver，再独立核对发布授权及目标。此报告不授权新增模型调用或部署。

## 最终边界修复与组合树追加验证

#369 分数／直接数学运算保护绑定 `e1c26b39`：两个数字规则文件 619 passed，1.92 秒。直接分数、数学运算和一元带符号数量保护完整表达式及其尾链；支持的 chapter／dash／tilde 范围仍按原合同处理，冻结 v2 不重标。该轮无模型或部署；619 与此前 635 阶段的测试范围不同，不相加。

五 PR 整合最终源码 head `5cbe68443d89e547769b5bd0a1cfa741aafbae36` 的离线定向组合测试为 **693 passed／3 subtests，41.77 秒，exit 0**。本轮最终测试范围与完整实现身份见 `20261013-five-pr-final-validation/summary.json`；旧 `97835708` 的 647／3 只作旧阶段证据，不外推到新代码。当前 QC implementation SHA256 为 `8daff00357a597d704d262c8e734d2aa086e3104bc8bd557a6b83bc08399e6d3`，scoring hash 由同一 summary 记录；代码最终 hash、模型实际运行身份与 waiver 产物 hash 是不同证据。

本次追加时 #374 CI 为 14 queued／1 success／1 skipped，尚未终态，不能称全部 CI 通过或整合已合并。backlog `DEV-QC-001` 保持 waiting_evidence：最终实施下的真实校准、新 artifact-bound waiver 与正式发布仍未执行；用户此前未推送本地组合的真实运行不补作最终身份验收。报告继续 draft，不合并。

## 原 CI local-mock 失败及隔离调查

`5cbe6844` 的 Actions run `38417312621` 出现 local-mock 失败：complete pilot CLI 返回 2，原测试未保存其 stdout／pilot 临时 root，不能还原具体业务失败原因。原 CI 日志已作为脱敏副本 `report-input/original-ci-localmock.log` 保留；下载到的 mock-TTS artifact 属于其他 mock 测试，不包含失败 pilot root。此前 693 项离线通过不覆盖这一 CI 结果，不能写全部 CI 通过。

相同隔离 runtime 下，current `5cbe6844` 的定向测试 1 passed／42.158 秒，base `c1719208edd37073201efd3c827e1afd7e4cc62a` 的同一测试 1 passed／37.703 秒，两者观测到的三次 CLI 返回值均为 `[0,0,2]`。19 个 runtime 闭包文件及目标测试（共 20 文件）字节一致；这只界定已比较的闭包，不能证明整个仓库没有差异。调查没有修改源码或调用真实模型。

结论严格为 **failure not reproduced／root cause unknown**：没有证据证明改动回归，也没有证据将其称为既有 flake。Mac／Python 3.11 隔离复现不等同 CI Linux／Python 3.12，原失败临时证据缺失是具体限制。完整摘要和两阶段时间见 `report-input/summary.json`、`timings.tsv`。后续实际 review 修复会形成新 head，并独立运行新 head CI；不是重试旧 job 来改写原失败。本报告继续保留原失败，等待新 head 和 CI 终态追加。
