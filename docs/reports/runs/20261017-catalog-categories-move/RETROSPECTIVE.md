# 复盘：目录分类元数据工具迁移

证据见同目录 `INDEX.md`、`manifest.json`、`outcome.json`；合成目录在本机忽略的 `artifacts/catalog-categories-move-20261017/`。

## 结论先行

交付类型为本地代码测试。`scripts/update_catalog_display_categories.py` 原字节移至 `tools/ops/`，旧命令保留兼容门面。基线 11 项测试通过；修正动态文件加载测试的 patch 目标后，迁移后 12 项测试通过。旧、新 CLI 从仓库外运行，输出文件字节和去除目标路径后的收据一致，均退出 0。没有部署 catalog。

## 总时间

测试各自不到一秒；未记录完整准备和等待时长，不作性能比较。

## 各层模型、耗时与速度

L1–L4 为 `not_run`；无模型、token、音频或费用。

## 错误

| 阶段 | 现象与原因 | 发现时机 | 处理与回归 |
|---|---|---|---|
| 首次迁移后测试 | 三个子测试未得到预期退出：文件规格加载的旧门面与新实现是不同模块对象，原测试 patch 旧门面的函数 | 定向测试 | 将 patch 目标移到新实现；12 项测试通过，保留旧门面的文件规格 API |
| 帮助命令试跑 | 系统 `python3` 缺少 `jsonschema` 依赖 | 环境预检 | 改用仓库虚拟环境执行；新旧帮助命令和实际合成 CLI 均通过 |

## 可以改进的地方

遇到 `spec_from_file_location` 的旧路径消费者时，同时核对其函数引用和 mock patch 目标，不能只验证普通 import 的模块身份。

## 实际覆盖范围

catalog v2/v3/v4 schema、分类元数据更新、原子新文件、拒绝覆盖、非有限 JSON、旧/新 CLI 合成输出与模块身份；无真实 catalog 修改、Firebase 发布或设备检查。

## 遗留状态

代码 PR 和完整 CI 尚未建立。没有 job hold 或生产构建产物。

## 外部可见的变化

代码暂在工作分支。Dev 发布、TestFlight、设备和场地验收为 `not_run`。
