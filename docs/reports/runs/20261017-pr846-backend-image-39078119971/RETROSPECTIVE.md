# 复盘：20261017-pr846-backend-image-39078119971

数据见同目录 `INDEX.md`、`manifest.json` 和 `pr846-backend-image-resources-39078119971/summary.json`。

## 结论先行

交付类型为测试。精确 head `6298c7be2326472207d8b8a8fd71103547a252b2` 的 Backend image resources GitHub Actions run `39078119971` 以 `success` 结束，`outcome.json` 记录 `passed`。`resource-smoke` 成功：真实 Docker image build、镜像内 schema loader、镜像内 terminology loader 均成功。该工作流没有直接执行 preflight facade 导入；其镜像文件 COPY 经 build 检查，本地临时镜像布局模拟另见报告 #879。

## 总时间

GitHub Actions 的 `createdAt` 到 `completedAt` 为 1 分 21 秒。本轮没有 journal，无法将墙钟时间精确拆分为计算、排队等待和返工；没有人、服务或凭据等待记录。旧 head 的同类运行输入与路由不同，不据此声称速度改进。

## 各层模型、耗时与速度

| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---:|---|---|---|---|---|
| L1 来源 ASR／对齐／英文评审 | not_run | 不适用 | 0 | 不适用 | 不适用 | 不适用 | 0 | `summary.json` |
| L2 初译／审核／文本质检 | not_run | 不适用 | 0 | 不适用 | 不适用 | 不适用 | 0 | `summary.json` |
| L3 配音／回转写／音频质检 | not_run | 不适用 | 0 | 不适用 | 不适用 | 不适用 | 0 | `summary.json` |
| L4 构建与发布 | not_run | 不适用 | 0 | 不适用 | 不适用 | 不适用 | 0 | `summary.json` |
| Backend image resources CI | GitHub Actions | 不适用 | 1 run | 墙钟 1 分 21 秒 | 不适用 | 不适用 | 未计量 | `summary.json` |

没有付费模型调用；CI 平台成本未计量。

## 错误

本轮未见失败。旧 head 的 P2 Dockerfile 缺失已由新提交修复，实际镜像成功构建。 无新增修复项。

## 可以改进的地方

保留本报告注明的覆盖边界；若后续生产发布需要镜像内 preflight CLI 或真机行为证据，应在相应环境执行并单独报告。当前报告没有可量化的速度或成本改进依据。

## 实际覆盖范围

真实镜像构建与两个资源 loader；未运行 preflight CLI、L1–L4 生产层或设备验收。 `resource-smoke` 的三个核心步骤均成功；未直接执行 preflight facade。

## 遗留状态

没有本轮 Dev 文件、Spark job hold 或构建号；代码 PR #846 的新 head 审查状态单独核对。生成报告所用的本地摘要源位于被 Git 忽略的 `artifacts/`。

## 外部可见的变化

外部可见的是 run `39078119971` 的 GitHub Actions `success` 状态。没有 Dev 发布、TestFlight 构建或受保护分支推送；设备播放和场地验收均为 `not_run`。
