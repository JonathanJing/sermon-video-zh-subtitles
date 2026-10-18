# 复盘：20261017-wheel-resource-ci-repro

## 结论先行

交付类型：测试。PR #592 的 CI `root-2` 失败：711 个测试中 1 个失败、5 个跳过。失败仅在新加的 wheel 隔离测试中；修复提交 `f8f1b521` 后，本地定向重跑 1/1 通过。新提交的 CI 尚未结束，不宣称 CI 已通过。

## 总时间

失败 CI shard 678.144 秒；修复后的本地定向测试 2.823 秒。没有完整记录诊断和等待时间，不估算总墙钟时间或历史改善。

## 各层模型、耗时与速度

L1 至 L4 均为 `not_run`。没有模型调用、远程生产任务、token 或费用。

## 错误

CI 的 Python 解释器含有仓库 editable 安装的 `.pth`，即使测试子进程清除了 `PYTHONPATH`，`sys.path` 仍含 `packages/production/src`。测试原先直接断言该路径不存在，因此先于 wheel 的资源和导入检查失败。修复后，测试子进程在导入 wheel 前移除仓库源路径，仍检查导入模块来自临时安装目录且资源字节与源文件一致。

## 可以改进的地方

wheel 隔离测试应同时考虑环境变量和解释器的 editable 安装。等待修复提交的 CI 后再确认这项检查在 runner 中通过。

## 实际覆盖范围

失败来自 GitHub Actions `root-2`，运行链接在 `summary.json`。本地重跑只覆盖 `tests.test_production_wheel_resources` 1 个测试，使用现有虚拟环境；未重复整个 root shard。该测试构建非 editable wheel、安装到仓库外目录，并检查两个 Swift 模板资源及两个旧 CLI 的 `--help`。

## 遗留状态

PR #592 最新提交 `f8f1b521` 的 CI 仍待完成；正式合并须看新提交结果。

## 外部可见的变化

只有测试代码变动；发布、生产读取、设备和场地验收均为 `not_run`。
