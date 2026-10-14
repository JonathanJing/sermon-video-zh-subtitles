# 复盘：20261014-pr390-compat-catalog-fix

数据见同目录 INDEX.md 和 manifest.json。未填写的小节删掉前请写明原因。

## 结论先行

- 本轮定向测试通过：`test_feedback_rollout.py` 共 22 项，22 项通过、0 项失败；结束状态为 `pass_after_expected-contract-update`，退出码为 0。
- 可高置信确认的范围仅是兼容发布 catalog 的离线合同：当前与历史来源会补齐运行时页面／语言身份，准备产物使用补齐后的 catalog，旧 v1 release catalog 本身不被改写。
- 生产部署、生产 API 回读和浏览器上传均未执行。因此本报告支持合入 PR #390 的回归修复记录，不支持生产发布、线上行为或设备验收结论。

## 实际覆盖范围

<!-- 按 L1–L4 写本轮执行、复用和未执行的部分；模拟审核和诊断级结果原样写出。 -->

本轮不是 L1–L4 内容生产运行，也没有翻译、配音、同步、发布或 Spark／付费模型阶段。实际执行范围是 PR #390 兼容发布器的离线定向回归：

- 对 `experiments/sermon-dubbing-poc/test_feedback_rollout.py` 执行合同测试。
- 验证当前版本和上一版本来源都会补齐运行时 `pageId` 与 `audioLocale`。
- 验证兼容发布准备写出补齐后的运行时 catalog。
- 验证旧版 v1 release catalog 保持原样，没有把运行时扩展字段回写到冻结输入。
- 执行 Python 编译检查和 `git diff --check`。

未执行生产部署、生产 API 回读、浏览器上传、真实设备或会场验收。

## 结果和结束信号

<!-- 各运行目录的 outcome.json；独占 Spark 的运行以 round: 行为准。 -->

- `outcome.json`：`pass_after_expected-contract-update`，退出码 0。
- `summary.json`：`pass`；22 项测试全部通过，0 项失败。
- 本轮不使用独占 Spark，因此没有 `round:` 结束信号。
- `outcome.json` 记录的 `baseCommit` 是 `ace03ce8`。报告没有记录最终被测工作树的 tree/diff 哈希；PR #390 的最终修复提交 `32f63ace` 及其 GitHub CI 是另一份代码验证证据，不能由本报告单独替代。

## 耗时

<!-- 按 timings.tsv 列阶段并与上一轮比较，把等待和计算分开。 -->

| 阶段 | 状态 | 秒 |
|---|---|---:|
| 合同更新前的定向测试 | fail | 0.57 |
| 合同更新后的定向测试 | pass | 0.58 |
| Python 编译检查 | pass | 0.10 |
| `git diff --check` | pass | 0.20 |

四个已记录阶段合计 1.45 秒。`outcome.json` 的墙钟区间为 17:07:00–17:09:01 UTC（121 秒）；报告没有 journal，无法把其余时间可靠拆成等待或计算。本轮没有同口径上一轮可比较。

## 错误

<!-- 现象、原因、处理、回归测试、对应提交或 PR。 -->

- 现象：合同更新前有 2 条断言失败。
- 原因：旧断言要求兼容运行时 catalog 与旧 release catalog 逐字节相等；新合同要求只在运行时副本中加入已验证的 `pageId` / `audioLocale`，两者不应继续完全相等。
- 处理：更新断言以分别核对运行时扩展字段和旧 v1 catalog 不变，并补上当前来源、历史来源及兼容准备产物的覆盖。
- 回归：同一测试文件更新后 22/22 通过；修复进入 PR #390 的 `32f63ace`。

## 占用资源之后才暴露的错误

<!-- 哪些本可以在预检发现，要补哪项预检。 -->

不适用。本轮没有占用远端、Spark、部署或付费资源；失败发生在 0.57 秒的本地定向测试阶段。它属于随合同变更同步更新测试预期的问题，不需要新增远端资源预检。

## 遗留状态

<!-- Dev 上无引用的文件、未结束的 job hold、已用构建号、待删除的本地产物。 -->

- 本报告没有产生 Dev 发布文件、Spark job hold 或构建号。
- 本地原始证据保留在被 Git 忽略的 `artifacts/pr390-compat-catalog-fix-tests/`；公开报告只包含脱敏副本及其哈希。
- 报告缺少最终被测工作树 tree/diff 哈希；由 `DEV-RUNREPORT-001` 继续跟踪运行报告的身份绑定改进。

## 外部可见的变化

<!-- Dev 发布、TestFlight、受保护分支推送各自的证据；没做的验收写 not_run。 -->

- 生产部署：`not_run`。
- 生产 API 回读：`not_run`。
- 浏览器上传：`not_run`。
- TestFlight、设备播放、会场验收：`not_run`。
- 代码状态（与上述外部验收分开）：PR #390 后续以 `32f63ace` 为 head 合并到 `dev`；其 GitHub CI 是代码层证据，不改变本轮线上项目均未执行的状态。

## 后续

<!-- 每条写负责人和跟踪的 PR 或 backlog 条目。 -->

- 维护者：将本报告 PR 填完复盘后合并进 `dev`；不要把关闭未合并的报告 PR 当作报告入库。
- `DEV-RUNREPORT-001`：后续让定向测试报告记录最终被测 commit 或工作树 tree/diff 哈希，并用 journal 覆盖完整墙钟区间。
- PR #390 的部署前事项仍按其原范围单独执行和留证；本报告不触发部署，也不把未运行项补写成通过。
