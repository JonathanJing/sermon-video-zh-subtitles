# 复盘：20261017-pr846-docker-preflight-fix

数据见同目录 `INDEX.md`、`manifest.json` 和 `pr846-docker-preflight-fix/summary.json`。

## 结论先行

交付类型为测试。PR #846 的新 head `6298c7be2326472207d8b8a8fd71103547a252b2` 已纳入 `origin/dev` 的 `bd190d33`，并在 Dockerfile 中复制迁移后的 preflight 实现。定向 6 个单元测试、临时镜像目录布局中的旧入口导入与 `code_identity()`、`git diff --check` 均通过，`outcome.json` 记录 `passed`。本机没有 `docker` 命令，故未执行真实镜像构建；这份报告只支持本地定向验证。

## 总时间

单元测试报告 0.911 秒执行时间。临时目录模拟、Git 检查与整个操作过程没有统一计时记录，无法准确拆分总墙钟时间、等待和返工；没有人、服务或凭据等待的记录。上一轮同类 preflight 定向测试也为 6 项通过，本轮新增检查聚焦镜像文件布局，覆盖范围不同，不作速度比较。

## 各层模型、耗时与速度

| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---:|---|---|---|---|---|
| L1 来源 ASR／对齐／英文评审 | not_run | 不适用 | 0 | 不适用 | 不适用 | 不适用 | 0 | `summary.json` |
| L2 初译／审核／文本质检 | not_run | 不适用 | 0 | 不适用 | 不适用 | 不适用 | 0 | `summary.json` |
| L3 配音／回转写／音频质检 | not_run | 不适用 | 0 | 不适用 | 不适用 | 不适用 | 0 | `summary.json` |
| L4 构建与发布 | not_run | 不适用 | 0 | 不适用 | 不适用 | 不适用 | 0 | `summary.json` |
| 本地定向验证 | Python unittest 与镜像目录布局模拟 | 不适用 | 6 tests + 1 simulation | unittest 0.911 秒；模拟未计时 | 不适用 | 不适用 | 未计量 | `summary.json` |

## 错误

正式检查无失败。审查在旧 head 发现 Dockerfile 未复制 `tools/ops/sermon_unified_preflight.py`，使镜像内旧入口导入与 Layer 2 code identity 受影响；新提交 `6298c7be` 补上单文件 COPY。模拟在修复后通过。真实 Docker 构建因本机没有 `docker` 命令而未执行，属于未验证范围。

## 可以改进的地方

| 类别 | 改进 | 依据 | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 预检 | 后续迁移 CLI 文件时核对 Dockerfile 所复制的源闭包 | 本轮审查指出遗漏，临时目录模拟通过 | 降低镜像运行时缺文件风险 | 维护者 | PR #846 |

## 实际覆盖范围

L1–L4 生产层未执行或复用。本轮仅检查兼容入口、代码身份和 Dockerfile 所需文件布局；未调用模型、远端服务或生产工作流。

## 遗留状态

没有 Dev 文件、Spark job hold 或构建号。实际 Docker build 与部署镜像导入仍待具备 Docker 的环境验证；PR #846 的新 head CI 和代码／安全审查另行跟踪。

## 外部可见的变化

只推送 PR #846 的新代码提交；没有 Dev 发布、TestFlight 构建或受保护分支推送。设备播放与场地验收均为 `not_run`。
