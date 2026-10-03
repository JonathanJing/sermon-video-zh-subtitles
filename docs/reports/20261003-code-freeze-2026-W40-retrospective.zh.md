# 2026-W40 证道制作冻结与设置复盘

记录日期：2026-10-03。冻结检查点取自当时的 `origin/dev`，提交为 `d31cdc2aac87c5358a80b40e55cf908af4279302`。本复盘覆盖正式制作设置、冻结代码差距和修正分支验证；不把模拟 dry run 或本地并发模拟称为生产验收。

## 冻结结论

| 设置 | W40 请求 | 冻结版本观察 | 修正后状态 |
| --- | --- | --- | --- |
| Layer 2 API 并发 | zh-Hans、ko、es 合计最多 24 个请求在途 | 旧 runner 每种语言仅允许 1–3 个 group worker；历史 24 并发收据来自串行 locale 运行 | 新模板每种语言最多 16 个 worker；canonical controller 可同时启动三种语言；共享 `jobRoot` 文件锁信号量将同一 run 的 API 请求总数限制为 24 |
| Locale 进度 | 每种语言在自己的当前层满足依赖和审核门禁后独立前进 | canonical controller 仅派发 Layer 2，原实现每个 run 同时只有一个 locale job；没有跨层 dispatcher | 可并行准备三语 Layer 2。Layer 3 仍需 translation review 与 voice authorization；本修正没有建立自动音频派发器 |
| Spark TTS | 新单讲员任务使用 8 副本 × batch 8 | 正式 renderer 支持此入口；模型加载就绪有 barrier | 保持不变。正式路径没有专门的 dummy inference warmup |

每种语言的 group worker 上限保持为 16，以符合现有 policy schema；24 是三语共享的请求上限，由生产 run 下的 `jobRoot` 信号量执行。独立的非 canonical runner 不共享该信号量，因此不要把此上限扩展解读为跨所有进程、所有 run 或所有机器的账户级限流器。

## 冻结与验证证据

- 冻结清单位于本地忽略目录 `artifacts/code-freeze/2026-W40/freeze-manifest.json`，绑定来源分支 `origin/dev`、提交 `d31cdc2…` 和 tree `725b8808…`。模拟 backend dry run 记录 29 个事件，ASR、下载、Firebase、翻译与 TTS 外部调用均为 0。
- 当时的 frozen Dev App preview 因 feature parity 被拒绝，未部署、未做浏览器验收；W40 正式内容生产尚未开始。
- 修正提交为 `bc5a2ea34a0c2e022aba0d33068104ef270ac6e3`，基于冻结提交创建独立分支 `codex/code-freeze-fix-2026-W40`。PR 目标为 `dev`；冻结分支本身保持不变。
- 通过：Python 语法编译、三份 policy JSON 解析、`git diff --check`。80 次并发模拟通过共享槽，观察到的峰值恰为 24。
- 定向 unittest 未能加载：执行环境缺少 `jsonschema`，错误发生在测试模块导入阶段，断言未运行。没有声称该测试通过。

## 后续边界

正式生产启动前，应以本周已核准的源包、锚点、locale policy 和人工门禁建立实际 run，并观察三语并发请求收据。Spark 的 8×8 运行仍需按指定 checkpoint 实际执行；模型加载 barrier 不能代替推理预热证据。Layer 3/4、Dev App 预览、设备与现场验收各自保持独立状态。

此前播客制作结果与逐层证据见[播客 Layer 1–4 制作流程复盘](20261003-podcast-layer1-4-retrospective.zh.md)。
