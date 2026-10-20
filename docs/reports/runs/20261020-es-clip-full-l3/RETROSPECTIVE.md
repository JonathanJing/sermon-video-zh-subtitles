# 复盘：20261020-es-clip-full-l3

数据见同目录 INDEX.md 和 manifest.json。

## 结论先行

交付类型：**测试性完整 Layer 3**（16 单元西语 clip），不是发布。

最终状态：Spark 上依次跑完 render → compact → screen → package → audio QC；音频 QC 通过并签发**机器试听豁免**（`machine_quality_waiver`，`humanApproval=false`）。渲染退出码 1 是 renderer 自己的单元标记码，驱动按 `known_terminal` 继续，由筛查与音频 QC 决定；screeen/package/QC 全部通过。

证据边界：机器豁免不是人审，也不是发布、设备或现场验收。音频包未进入 L4。

## 总时间

- render 94 s（含 TTS 冷加载）、compact 17 s、screen 36 s、package 5 s、audio QC 280 s
- Spark 会话 begin 3 s、finish 7 s；全程约 8–9 分钟

## 各层模型、耗时与速度

| 阶段 | 后端 | 调用 | 耗时 | 费用 |
|---|---|---|---|---|
| render | Qwen3-TTS（Spark GPU，seed 42） | 16 单元 | 94 s | 本地 |
| compact | CPU | — | 17 s | $0 |
| screen | Qwen3-ASR（本地） | 16 单元 | 36 s | $0 |
| package | 确定性 | — | 5 s | $0 |
| audio QC | 本地 ASR + gpt-transcribe（dev）239 次返回 | 239 | 280 s | **$0.299** |

预留上限 $5.525，批准总额 $6，实际结算 $0.299。

## 错误

| 现象 | 原因 | 处理 |
|---|---|---|
| 首次 speech-job 失败 | 取到 10-14 的旧文本豁免，QC 实现哈希与当前代码不同 | 改用 2026-10-19 es 文本豁免 |
| voice-auth 重复运行被拒 | 授权收据不可变 | 预建 speech job，跳过重复授权 |
| 预算规划 `does_not_fit` | QC 最坏预留 5.525 > 5 | 批准总额调到 6（实际 0.299） |

## 可以改进的地方

| 类别 | 改进 | 跟踪 |
|---|---|---|
| 流程 | 逐组流水线直接产出 L3 输入，而不是复用 clip 运行目录 | DEV-GRP-006 后续 |
| 质量 | 整轨人工听审（本轮是机器豁免） | 后续 |

## 实际覆盖范围

- 执行：完整 L3，机器音频 QC。
- 未执行：L4 发布、设备/现场验收、人工听审。

## 外部可见的变化

无；仅本报告。
