# 2026-10-01 本地制作性能验收

用户授权“你来开始验收”后执行真实 GPU 组件对照，生产代码基线为 `bcf79aec610299daee26193f7c9b72edc2c18a45`。本页与[四项开发 backlog](local-production-speed-backlog.zh.md)配套；[机器可读证据](../data/benchmarks/local-layer-latency/2026-10-01/performance-acceptance.json)保留回执 hash、计时范围、资源与质量状态。组件测试结果不能替代 10 分钟或整周四层生产验收。

## 输入与计时合同

- 使用 9/27 原已审自然句：中、韩、西各一短一长，再加两句原文补足实际 batch8；没有重新切句。新音频是诊断候选，原人审回执只证明输入来源。
- 两端正式权重均为 `75d28ce6022b3df3a72df3dd6dbc01e53f584d685770d60ea04b341920968c9a`；实际模型 config hash 为 `9dd6cf2c1b1fdfb1c90dcee20ab81ee5367925bb7a8123b6046af9bce8b2941c`。逻辑 speakerId `eric_geiger` 对应配置 speakerKey `eric_pilot`，二者用途不同。原 job 的 adapter.configSha256 是 adapter 文件身份，不是模型 config hash。
- M1 Max 64GB 使用 MPS/FP32，Spark GB10 使用 CUDA/BF16；权重与生成设置相同，运行时与精度保留各端实际配置。因此测的是现有两套执行栈，不能把全部速度差归因于硬件。
- base seed42＋固定窗口 start（b1 长句为43，b2 整批为42）、temperature0.7、repetition penalty1.05、max tokens768、SDPA、自然语速。高层 TTS API 不暴露 EOS/finish-reason，返回、数量匹配与解码通过均不能证明正常 EOS。
- 同语言 b1/b2 使用相同短长两句；mixed b4/b8 使用全部八句，仅测混合语言引擎，不代称单语言正式 producer 的 b4/b8 验收。warm 每条件一次预热及三次测量，记录中位数与范围。
- cold 指新进程和新模型实例，未清 OS/驱动缓存。cold b1 只有首短句，与 warm b1 两句的工作量不同。模型 hash、import、load、合成、额外 CPU 转换、保存、完整解码/hash 和总墙钟分别记录；合成本身包含内部 codec 解码和返回传输。
- 每台机器同时只有一个本轮 GPU 工作。Spark 的既有服务保留，环境并非独占实验室；温度、系统可用内存和既有 swap 单列观察，不把 UMA 的进程与系统内存重复相加。
- Spark 使用直接 LAN SSH；默认 Mac mini 中转本次连接超时。独立 stage 与正式产物隔离，任何 unknown dispatch 保留记录，不自动重试或切机。

## 结果

### 正式权重配音组件

时间单位为秒，三次测量中位数（最小–最大）；倍率按相同文本工作量的组件墙钟计算。RTF 为合成时间/生成音频秒数，两端生成音频时长不同，保留各端实值。

| 条件 | Spark | Mac | Mac/Spark 时间比 | Spark / Mac 合成 RTF |
|---|---:|---:|---:|---:|
| `zh-Hans-b1` | 20.41（14.23–20.46） | 35.59（34.54–37.22） | 1.74× | 1.295 / 2.083 |
| `zh-Hans-b2` | 12.29（12.05–14.56） | 29.83（28.40–32.27） | 2.43× | 0.773 / 1.819 |
| `ko-b1` | 14.15（10.63–16.97） | 28.46（26.62–30.72） | 2.01× | 1.092 / 2.111 |
| `ko-b2` | 11.99（9.73–13.68） | 20.47（20.29–21.88） | 1.71× | 0.890 / 1.606 |
| `es-b1` | 6.77（6.73–10.95） | 20.44（19.95–21.20） | 3.02× | 0.710 / 2.050 |
| `es-b2` | 5.01（5.01–5.01） | 16.33（15.87–16.43） | 3.26× | 0.537 / 1.654 |
| `mixed-b4` | 15.69（15.63–15.86） | 53.57（53.19–56.09） | 3.41× | 0.312 / 1.069 |
| `mixed-b8` | 11.37（11.36–11.85） | 39.86（38.86–40.62） | 3.51× | 0.231 / 0.808 |

同语言 b1→b2 的组件时间下降：Spark 中/韩/西约 39.8%/15.3%/26.0%，Mac 约 16.2%/28.1%/20.1%。mixed b4/b8 是八句引擎诊断，不能外推为正式单语言完整包吞吐。旧 4.5×来自另一权重/样本，不能套用本轮 1.71–3.26×的同语言组件对照。

两端各 32 个 warm trials、112 个 WAV 全部返回、身份/覆盖/hash 与完整解码通过；另各两次 cold（首短句1个、mixed8八个）。Spark warm媒体已下载并重新读取全部112个PCM帧/hash。三个测量重复的音频 hash 在每条件内一致；不同设备或batch的音频不要求字节相同。

冷入口到回执：Spark 首句47.41s/mixed8 60.13s，Mac首句23.46s/mixed8 48.63s。Spark两次load38.26/35.91s，Mac11.02/5.69s；Spark启动并不占优。Spark远端dispatch另为49.63/62.33s，不能与Mac进程入口计时混成同一列。权重首次同步是环境准备，不计为每周生产时间。

Spark warm最大CUDA allocated约7.02GiB（mixed8），reserved单列保留；Mac MPS driver每200ms采样峰值约21.12GiB，精确峰值不可得。Spark Torch2.13.0a0 nv26.06，Mac Torch2.14.0；qwen-tts两端均0.1.1。Spark TTS/回转写容器4CPU/12GiB/无额外swap；CPU重叠容器实际6CPU/24GiB/总内存加swap28GiB，不能混称同一资源限制。TTS期间点观察Spark58℃、可用系统内存约25.6GiB，既有swap约4.64GiB；这是共享环境点观察，不是峰值或OOM证明。

### ASR 批次驻留

同一英文30秒音频冻结为四个7.5秒单元。未传输权重期间正反序各做一次：

| 执行顺序 | 四次单请求总墙钟 | 一次batch4总墙钟 | 时间减少 | 加速 |
|---|---:|---:|---:|---:|
| single-first | 93.38s | 25.25s | 72.96% | 3.70× |
| batch-first | 87.57s | 22.31s | 74.52% | 3.92× |

模型load4→1，两组四段转写完全相同；16个单元receipt的身份、顺序、modelFilesSHA通过，10个容器exit0并无残留。较早同期权重传输pilot108.07→26.58s仅作为历史试测保留。这里每单元仍标量推理，收益来自减少dispatch/hash/load；不是ASR张量批处理吞吐。

### CPU 保存重叠

同一八句中文、batch4、queue2，CPU0/1/2 各一个新进程，顺序运行。GPU 精度/生成设置在同机器三组内不变。

| 机器 | CPU0 / CPU1 / CPU2 总墙钟 | 合成时间 | CPU任务累计 |
|---|---|---|---|
| Spark | 56.85 / 43.65 / 43.78s | 15.19 / 8.95 / 8.78s | 0.059 / 0.049 / 0.093s |
| Mac | 38.13 / 36.60 / 36.38s | 29.22 / 28.92 / 28.60s | 0.016 / 0.026 / 0.020s |

两台各27个WAV（24单元＋3整轨）完整解码及下载/本地PCM回读通过；各机器内部三组的unit PCM、整轨PCM、cues均完全一致。队列峰值为1/4/4，cap8，背压0。输出正确性通过，但本样本CPU保存不足0.1秒，arm只各跑一次且包含load/OS与驱动缓存影响，**不能把总墙钟差归因于CPU并发，也尚未证明可重复的时间收益**。

### 回转写吞吐与生成质量

两端各取warm-1的28个WAV（八句在八种条件中的覆盖），都由同一Spark上的固定Qwen3-ASR-0.6B snapshot `5eb144179a02acc5e5ba31e748d22b0cf3e303b0` 复测，以固定ASR环境评估两端音频。每个ASR batch1/4/8 一次预热＋三次测量，模型只加载一次；这不是Mac ASR硬件速度对照。

| 配音产地 | ASR batch1 / 4 / 8 推理中位数 | batch8相对batch1减少 |
|---|---|---:|
| Spark | 9.525 / 6.082 / 4.533s | 52.4% |
| Mac | 9.374 / 5.967 / 4.497s | 52.0% |

Mac音频28/28在三种ASR批次和重复中均通过机器相似度门槛。Spark音频有一处 `es-short@es-b2`：期望 `Soy Eric, si no nos conocemos.`，ASR batch1/8识别成 `So Eric, si no nos conocemos.`，相似度0.833低于0.88；batch4识别正确并28/28通过。差异来自同一冻结WAV上的回转写判断，不能据此确定TTS漏字、截断或ASR误识别，保留 `requires_review`，待西语听审。原人审回执不自动批准新音频。

两端每条件三个measured重复的WAV hash一致，所以warm-1语音内容也覆盖其余两次相同字节的测量；warmup另有解码/hash证据。此处只检查短/长句样本，未覆盖整周所有句长、经文与姓名。高层TTS仍无EOS字段，人工听审 `not_run`。因此尚不提升正式batch默认值，也未进入10分钟/整周生产验收。

首次回转写尝试因只读容器漏配Triton临时缓存路径，首推理确认失败并退出；原dispatch/log/started保留。补充 `/tmp` Triton/Numba/CUDA cache 后在新目录完成，没有清除未知marker或覆盖旧结果。CPU flat-stage首次路径错误也在GPU前退出，原stage保留后新stage成功。这些失败不纳入成功吞吐计时，但保留故障证据。

### Layer 2 正式 Astra/Sol 受限小样本

用户随后选择“用正式 Astra/Sol 做受限小样本，保留独立预算与账本”。从 9/27 中文原419组中冻结8个原分组及原上下文；没有构造不完整的批准 source package。实验捕获当前正式 producer 的完整分组 prompt，再按每组 Astra 初译→Sol 独立复核→语言插件运行。使用 `gpt-6-astra` / `gpt-6-sol`、medium、standard/default；实验 completion 上限2048（含 reasoning），正式严格默认4096，差异单列。本项模型在 API 端执行，不是 Mac/Spark 本地文字模型性能对照。

| workers | 八组耗时 | 计时范围 | 实际新增 API 调用 |
|---|---:|---|---:|
| 1 | 69.10s＋15.00s | 原段＋恢复段；缓存13次，只补3次；不是不中断串行墙钟 | 16（原13＋补3） |
| 2 | 44.96s | 全新八组，16次调用 | 16 |
| 3 | 30.40s | 全新八组，16次调用 | 16 |

本轮 worker2→3 墙钟减少32.4%。每档仅一次，执行顺序固定，缓存读 token 分别为0/23,291/21,355，提供方缓存与服务波动没有隔离；不能据此声称可重复增益或 worker1→3 精确加速比。八组集中在开场短句，未覆盖整周经文、长分组与全部语言。24次分组复核与语言插件检查均pass，48个响应/请求ID唯一、model/usage与缓存身份通过；这是机器证据，未产生候选入库、人审批准或发布包。

独立硬上限48calls、393,216 input tokens、98,304 completion tokens、$6；每档16calls/$2。最终预留成本$5.565972（最坏请求预算），48次全部返回；实际usage为87,036 input＋12,139 completion，共99,175 tokens，其中reasoning3,917、cache-read44,646、cache-write42,246。按全部input采用最坏cache-write费率计算的费用上界$0.870552，**不是账单费用**。价格按本轮核实的 [Astra](https://developers.openai.com/api/docs/models/gpt-6-astra) / [Sol](https://developers.openai.com/api/docs/models/gpt-6-sol)标准档快照；native accounting 的Sol价格仍为unknown，以独立账本为准，账单对账未做。

首段13次全部已返回后，下一次Sol调用因本地保守输入估算8247超过8192在dispatch前停止；未发生未知API请求。审计旧raw/cache/model/usage/预算后，在新revision中只把本地单调用预检上限改为16384，48calls/$6总预算及实际API payload不变。旧manifest、源码、账本与失败状态完整归档，原13项预留及响应未改且未重付。迁移中断或unknown记录仍拒绝续跑。恢复成功验证缓存与局部恢复，但串行完整基线待测；本轮没有增加预算重跑。


## 复现与边界

新增五个实验入口：`benchmark_speech_residency.py`、`benchmark_formal_tts.py`、`benchmark_back_asr.py`、`benchmark_cpu_overlap.py`、`benchmark_layer2_bounded.py`，均位于 `scripts/experiments/`。使用新输出目录和固定输入，保留模型/脚本/音频身份；`--help` 给出参数。前两项分别复用未改动的 production speech worker 与正式 `QwenSynthesizer`，CPU 项调用实际 legacy renderer，回转写复用正式文本归一规则，文字项捕获正式分组prompt但隔离部分覆盖结果。没有创建批准或发布包。

```sh
PRODUCTION_PYTHON=/absolute/path/to/existing-production-env/bin/python
"$PRODUCTION_PYTHON" -m unittest tests.test_benchmark_back_asr tests.test_benchmark_cpu_overlap \
  tests.test_benchmark_formal_tts_preflight tests.test_benchmark_layer2_bounded \
  tests.test_benchmark_translation_safety -q
```

新增验收回归 **56项通过（1.915秒）**，覆盖缺条件/缺尾单元、错snapshot/音频/文本身份、路径越界、批次尾部、只加载一次、GPU前拒绝错误输入、异常结果无完整回执，以及CPU串并行PCM/cues、超时与冻结设置漂移。文字项覆盖硬预算、跨caller停止、unknown不重放、账本写失败、错model/usage/cache、原预留绑定及迁移中断。系统Python缺jsonschema；验证使用已有项目`.venv/bin/python`，未安装新环境。

10 分钟及整周生产仍需质量问题解释、生成音频听审和代表性整链计时；原 7h15/3h15 外推暂不替换为实测。正式 batch 默认仍为 1，Spark 默认与 Mac fallback 策略沿用现有合同。

用户已决定下一次Dev测试采用[固定参数与分步候选验收](local-production-next-dev-test-parameters.zh.md)；对应profile为`not_run`，不代表本轮已执行新参数或升级生产默认。
