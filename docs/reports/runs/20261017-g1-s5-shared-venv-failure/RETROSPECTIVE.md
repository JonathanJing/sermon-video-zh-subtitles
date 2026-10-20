# 复盘：20261017-g1-s5-shared-venv-failure

## 结论先行

交付类型为本地代码测试。#579 合入 S5 后的定向运行结束于 39 passed、552 subtests passed、1 failed（退出码 1）。失败是工作树测试解释器指向共享主 checkout 的 editable 包；这份报告保留失败证据，不作全部通过声明。

## 总时间

墙钟 5.6 秒，测试汇总 5.39 秒；本地计算，无等待或返工记录。结束时间和退出码见 `outcome.json`。

## 各层模型、耗时与速度

L1–L4 真实工作均为 `not_run`。没有模型请求、token、音频秒数或费用。

## 错误

`test_every_facade_imports_by_bare_name_from_a_script_run_in_scripts` 在独立子进程清除 `PYTHONPATH` 后，读到共享 venv 指向主 checkout 的包版本，导致宿主的新观测绑定与旧 `ObservabilityBackend` 不匹配。发现于本地预检；使用既有工作树专属 `.venv/bin/python` 重跑同一用例，1/1 通过，见 #831。未改生产代码或测试。

## 可以改进的地方

预检：工作树测试前运行 `scripts/worktree_venv.py --check`，并用该工作树 `.venv/bin/python` 启动 pytest。依据是本轮唯一失败；由 G1 整合者执行。

## 实际覆盖范围

执行 S5 sentence shadow、post-live 加载身份、包结构、语速身份、实现冻结、QC 闭包及 review 端口的定向测试；精确命令见 `outcome.json`。39 个通过项属于本运行，唯一失败由 #831 单独复测。真实生产、Spark、付费 QC、发布均为 `not_run`。

## 遗留状态

四个 G1 PR 维持 draft/HOLD；旧运行未知结果与预留、locale 裁决仍待处理。没有创建 Dev 文件、job hold 或构建号。

## 外部可见的变化

仅推送 G1 草稿分支与本脱敏报告。没有 Dev 发布、TestFlight、设备或场地验收。
