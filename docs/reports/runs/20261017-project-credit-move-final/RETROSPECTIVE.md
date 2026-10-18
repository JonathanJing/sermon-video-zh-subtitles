# 复盘：20261017-project-credit-move-final

证据见同目录 `INDEX.md`、`manifest.json`、`outcome.json`、`summary.json` 和脱敏 `test.log`。

## 结论先行

测试通过：6 项合成离线测试。旧脚本、新脚本、旧模块、新模块四个 CLI 入口生成逐字节相同的账本及投影清单；来源哈希绑定一致，原账本不变。无远端或付费调用；不代表生产投影运行。

## 总时间

墙钟 2.973 秒，全部为本地测试计算；无等待或返工。相比先前 3 入口测试，本轮新增新脚本直接执行入口。

## 各层模型、耗时与速度

L1–L4 均 `not_run`。仅本地 Python 合成测试；模型调用 0，token、音频速度与费用均不适用。证据：`summary.json`、`test.log`。

## 错误

本轮无错误。先前系统 Python 缺依赖失败另见 env-fail 与 deps-fail 报告。

## 可以改进的地方

预检：在 worktree 内先运行 `scripts/worktree_venv.py`，核对生产包路径，避免无效测试启动。依据为先前两次导入失败；负责人为本地测试操作者，跟踪于迁移 PR。

## 实际覆盖范围

覆盖离线投影、原账本不变、来源 hash 与派生 hash、私有身份 sidecar、篡改拒绝和四个 CLI 入口等价。L1–L4 均未执行或复用。

## 遗留状态

无 Dev 文件、job hold、构建号。合成测试临时目录已清理；本地忽略的报告源保留供审阅。

## 外部可见的变化

Dev 发布、TestFlight、设备播放和场地验收均 `not_run`；仅此 docs-only 报告 PR 可见。
