# 周六 Context Pack 到周日实时字幕完整声学 E2E

日期：2026-09-04（America/Los_Angeles）

## 目标与边界

- 验证 `main` 提交 `8f24961` 上的完整链路：扬声器播放英文音频 → Chrome 麦克风采集 → 本地录音与 PCM 事件持久化 → Qwen3-ASR final → MiLMMT 翻译 → Context Pack 检索 → 可读字幕 UI → drain 与会话完成。
- 这是确定性合成语音和本机设备上的集成证据，不代表教会现场声学、真实讲员 WER 或生产就绪。
- 默认 4173/8766 端口当时被另一个本地工作树占用。本轮使用隔离端口 5174/9766，并仅在测试进程中允许 5174 WebSocket Origin；产品代码未因此修改。

## 输入与运行配置

- 播放音频：macOS `say`，Samantha，145 words/minute，8.882 秒。
- 播放文本：`Grace leads us through the truth. God is faithful in every season. The promised land is before us. Jesus Christ gives hope to his people.`
- 当前系统输出：FIIO K17；Chrome 输入：MacBook Pro Microphone (Built-in)，48 kHz、单声道。
- 浏览器音频处理：echo cancellation、noise suppression、auto gain control 均关闭。
- ASR：Qwen3-ASR 0.6B 8-bit，经 MLX Audio WebSocket。
- 翻译：`sermon-milmmt-46-4b-v1-q8:benchmark`。
- 展示策略：`readable_chunks`。
- Pack：`weekly-2026-09-04-30c66ce15b91`，SHA-256 `7cc38b846aadffca5c73ab761b9c7da7fe15af210a9f9a5b3fc2c3abff208fa9`。
- Pack readiness：`degraded / english_map_only`；运行策略为 `english_alignment_v1`，机器中文没有进入翻译 prompt。

## 结果

- 完成会话：`20260904T183533.380Z-40a8046b`。
- 状态：`completed`；会话时长 34,453 ms。
- 浏览器录音：554,207 bytes；PCM：1,097,600 bytes / 343 个 100 ms frame。
- 事件：80；`asr.final` 8 个、`translation.final` 8 个、`caption.display` 8 个。
- 停止门：`asrWorkerDrained=true`、`translationWorkerDrained=true`、`storageHealthy=true`、`workerDrained=true`。
- manifest 保存了录音、PCM、PCM WAV 三个 SHA-256，以及 Pack 版本、Pack SHA-256 和 `english_alignment_v1` 策略。

| 延迟指标 | P50 | P95 | Max |
|---|---:|---:|---:|
| 音频段结束 → ASR final | 1,254 ms | 1,261 ms | 1,263 ms |
| ASR final → 中文首 token | 140 ms | 178 ms | 189 ms |
| ASR final → 中文 final | 268 ms | 399 ms | 424 ms |
| 音频段结束 → 中文首 token | 1,394 ms | 1,425 ms | 1,432 ms |
| 音频段结束 → 中文 final | 1,514 ms | 1,657 ms | 1,678 ms |

代表性真实输出：

| ASR final | MiLMMT final | Context |
|---|---|---|
| `Grace leads us through.` | `格蕾丝带领我们度过难关。` | `english_alignment_v1`，1 个命中 |
| `Through the truth, God is faithful in every season.` | `上帝凭着真理，在每一个时代都保持忠诚。` | `english_alignment_v1`，2 个命中 |
| `The promised land is before us. Jesus Christ.` | `应许之地就在我们面前。耶稣基督。` | 无命中，安全降为 `none` |
| `Christ gives hope to His people.` | `基督给他的子民带来了希望。` | 无命中，安全降为 `none` |

## 观察与风险

- Chrome UI 实际显示了中英文字幕、Pack 标识、延迟指标、手机只读 viewer、会话目录和安全停止状态。
- Pack 命中只提供英文顺序/对齐信息；未命中的句子继续由周日实时英文驱动，没有复用周六机器中文。
- 第一句被拆为 `Grace leads us through.` 与下一段，说明本轮是链路验证，不应作为逐字准确率证据。
- 静音/设备噪声期间出现 4 个 `The.` ASR final，并被翻译为 `The。`。已有抑制器另行拦截了 4 个候选，但仍有短幻觉通过；在扩大 suppression 规则前需要冻结输入和人工 Gold，避免误杀真实短句。
- 本轮没有修改系统音频路由，也没有干扰占用默认端口的现有会话。

## 结论

周六导出的受控 Context Pack 已在真实浏览器声学链路中帮助周日实时字幕，同时保持周日音频/英文为权威来源。录音、事件、字幕、Pack provenance 和 drain 均形成闭环；本轮通过的是本机 E2E 集成门，不替代教会现场 rehearsal 与人审 ASR Gold 门。
