# 复盘：最终 dev 的 mock 音频 QC

证据见同目录 `INDEX.md`、`manifest.json`、`outcome.json` 与 `summary.json`；原始测试输出未复制。

## 结论先行

交付类型为本地 mock 测试。在最终 `dev@974862e6` 上，合成 fixture 的文字→音频 QC fake 路径 1/1 测试通过，状态 `fake_plumbing_pass`；fake waiver 只在内存构造，未保存。没有调用 Spark、GPU、OpenAI API，也没有为三语实际音频签发豁免。

## 总时间

命令耗时 47.991 秒。没有独立 journal，不能再拆分等待/计算；测试内部 fake 校准占主要时间，非真实模型速度。

## 各层模型、耗时与速度

全部传输为 fake，模型调用、真实 token、真实音频秒数和 API 费用均为 0。L1–L4 正式运行均为 `not_run`。

## 错误

测试退出码 0。测试进程输出了若干未关闭临时锁句柄的 `ResourceWarning`，不影响本次判定；若后续测试清理出现问题，按具体失败再修复。

## 可以改进的地方

保留 mock 与真实交付的明确边界：另一个生产任务占用 Spark，本轮不解除其会话或重派音频模型。负责人为本任务主 Agent；真实音频 QC 需以后独立授权和现场资源门禁。

## 实际覆盖范围

覆盖单个韩语合成 fixture 的路径发现、fake 主次 ASR/校准、无持久化 fake waiver 逻辑。未覆盖 es/zh-Hans 真实音频、三语新 speech job 的渲染、Spark、设备播放或发布。

## 遗留状态

三语新 speech job 与真实文字机器豁免仍在本地忽略目录；真实音频渲染和签发未执行。为本轮短暂创建的独立 Spark 代码目录已清理，其他任务的独占会话未动。

## 外部可见的变化

无 Dev 发布、TestFlight、实体设备或场地验收。仅此脱敏 docs-only 报告 PR 对外可见。
