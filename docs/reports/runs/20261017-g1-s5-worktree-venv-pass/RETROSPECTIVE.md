# 复盘：20261017-g1-s5-worktree-venv-pass

## 结论先行

交付类型为本地代码测试。#830 的唯一失败用例用工作树专属 `.venv/bin/python` 在同一 #579 head `0c3db833` 上复测，1 passed、退出码 0。包来源经 `scripts/worktree_venv.py --check` 确认为该工作树；这是单项复测，未重跑整组。

## 总时间

墙钟 0.94 秒，pytest 汇总 0.72 秒；本地计算，无等待或返工记录。结束时间和退出码见 `outcome.json`。

## 各层模型、耗时与速度

L1–L4 真实工作均为 `not_run`。没有模型请求、token、音频秒数或费用。

## 错误

本轮无失败。#830 的版本错配来自共享 venv 的 editable 包路径；切换现有工作树 venv 后，子进程清除 `PYTHONPATH` 仍能加载当前包。没有修改代码。

## 可以改进的地方

预检：工作树测试统一检查隔离模式下的包来源，避免仅靠父进程的 `PYTHONPATH`。依据为 #830 的失败；由 G1 整合者维护。

## 实际覆盖范围

只运行 1 个 facade 裸名导入用例；#830 其余 39 个通过项是另一运行。真实生产、Spark、付费 QC、发布均为 `not_run`。

## 遗留状态

四个 G1 PR 维持 draft/HOLD；旧运行边界仍未裁决。没有创建 Dev 文件、job hold 或构建号。

## 外部可见的变化

仅本脱敏报告 PR；没有 Dev 发布、TestFlight、设备或场地验收。
