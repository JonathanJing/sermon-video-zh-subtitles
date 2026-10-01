# 下一次 Dev 性能测试参数

2026-10-01 用户决定：记录本轮参数建议，写入 [PR #204](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/204)，下一次 Dev 测试按本页执行。本页是未来测试配置与步骤，执行状态为 `not_run`；[机器可读参数表](../data/benchmarks/local-layer-latency/2026-10-01/next-dev-test-profile.json)升级为v2，Dev音频入口会自动读取其中的批次字段：配音2、回转写4。普通生产入口仍默认1；合并PR不触发GPU/API任务。本轮只用假模型验证参数传递，真实模型测试仍为`not_run`；未部署Dev。

## Dev测试主配置

| 路径 | 参数 | 采用理由与边界 |
|---|---|---|
| 本地模型后端 | Spark 优先；CUDA/BF16、SDPA | 已测执行栈；Mac fallback 使用 MPS/FP32。仅确认基础设施故障后切机；canonical 自动fallback未全接通，不能混拼CUDA/MPS音频 |
| legacy 语音批次驻留 | `--speech-batch-size 4` / `SERMON_SPEECH_BATCH_SIZE=4` | 一批hash/load一次，逐单元标量推理；正反序减少73%–75%，转写相同。输入总上限8个/32MiB，保留未知派发对账 |
| 正式 Layer 2 | `policy.batching.workers=3`、`batchSize=1` | 9/27三语既有policy已为3，沿用；保留每组Astra初译→Sol复核→语言插件。新周独立冻结policy，旧批准policy不原地修改 |
| 正式多语言配音 | Dev入口自动batch2；显式 `--batch-size 1` 作基线 | 新身份、新目录；正式生产省略Dev标志时仍默认1。此项与legacy中文renderer默认batch4不是同一路径 |
| 正式配音回转写 | Dev入口自动batch4；显式 `--batch-size 8` 作对照，1作基线 | 同WAV、各档独立receipt/cache；正式生产默认仍1。识别可因batch变化，已有疑点持续保留 |
| legacy CPU保存 | `--cpu-workers 1 --cpu-queue-batches 2` | 输出正确性通过；尚未证明worker2稳定提速。只适用于legacy renderer，不能传给正式renderer |
| 受限API适配器 | `maxInputTokens=16384`、`maxCompletionTokens=4096`、`wallTimeMs=300000`、`serviceTier=default` | input是本地保守预检，避免8247被8192误拦；保留该次总调用/token/费用硬上限。小样本completion2048不推广到长分组；普通runner不会自动套用这组限制，需由受限调用适配器实际传入并写回执 |

三个locale使用各自worker3，并发数是每个producer的上限。下一次先顺序运行locale，避免把三语同时启动变成9个在途组；同一Spark一次只运行一个本轮GPU工作。正式文字模型仍为 `gpt-6-astra` / `gpt-6-sol`，reasoning为medium。

TTS保留正式授权checkpoint `75d28ce6022b3df3a72df3dd6dbc01e53f584d685770d60ea04b341920968c9a`、模型config、声音绑定、base seed42＋固定窗口start、temperature0.7、repetition penalty1.05、max new tokens768、SDPA与自然语速。ASR固定本轮Qwen3-ASR-0.6B snapshot `5eb144179a02acc5e5ba31e748d22b0cf3e303b0`、CUDA/BF16、max new tokens2048，相似度门槛0.88。不得降低门槛来消除既有疑点。

## 已接入的音频入口

下一次真实Dev音频测试使用下面入口，**不需要再手填默认batch**。在Spark已校验的运行时和stage内执行；传入现有正式producer的所有必需来源、批准、声音授权、模型和输出参数，门禁继续由原producer校验。stage必须同时包含新helper及profile JSON；跨机复制不会由此入口自动执行。

```sh
PRODUCTION_PYTHON=/absolute/path/to/existing-production-env/bin/python
# 现有正式TTS参数接在tts后面；默认自动读取profile选batch2。
"$PRODUCTION_PYTHON" -m scripts.run_dev_local_audio_test tts --help
# 现有正式筛查参数接在back-asr后面；默认自动选batch4。
"$PRODUCTION_PYTHON" -m scripts.run_dev_local_audio_test back-asr --help
# 同一WAV的batch8对照：在back-asr原参数中显式加 --batch-size 8。
# baseline：在对应入口原参数中显式加 --batch-size 1。
```

这两条`--help`只显示原producer参数，不执行模型。真正运行时去掉`--help`并传入完整参数；TTS需要[正式renderer参数](formal-layer3-renderer.zh.md)，回转写需要`--job --render-manifest --artifact-root --model-path --model-revision --out-receipt --out-manifest`。ASR CLI的`--model-revision`是实际weights身份：`model.safetensors:sha256:79d6cbd4c98c7bbffe9db2edac07f56cd6637d0d5944b27f6c2b8353840323ea`；HF snapshot在profile中保留为来源，不冒充CLI revision。

等价地，原两个producer加`--dev-test`会启用同一配置；`--dev-test-profile /absolute/path/to/profile.json`可指定已stage的v2配置，必须同时启用Dev模式。v1是仅供操作员参考的旧配置，Dev loader拒绝它；迁移为v2时保留primaryBatchSize=1作为基线，新增devTestBatchSize=2/4。Dev模式TTS只允许1/2，回转写只允许1/4/8，显式参数优先，错误配置在模型执行前停止。

执行成功后，TTS保存`<job-parent>/dev-test-tts-b2.json`（baseline为b1）；ASR在指定筛查receipt旁保存`<receipt-stem>.dev-test.json`。消费回执绑定profile原始SHA、最终batch与实际producer artifact SHA；TTS另逐unit核对intent，ASR核对transcriptionBatchSize。此回执证明实际消费的音频batch，不声称一定新增GPU推理或人审批准；缓存命中仍可产生回执。失败不写verified回执、不自动重试。其他profile段（文字/CPU/路由/API预算）仍由原入口参数和操作员配置消费，不因音频入口启用而全部自动生效。

## 下一笔测试的步骤

1. 从已有已审来源选择包含长句、专名、经文和段落衔接的代表片段；使用完整原自然句及上下文，冻结来源/window、分组、文字、policy、模型/代码/运行时hash和初始缓存。先做几分钟片段，通过后再扩为10分钟；不把本轮开场八短组代称代表性整链。开始前按实际分组数冻结独立总预算，本轮历史48calls/$6不自动成为新测试预算。
2. 使用上表Dev参数跑真实生产路径，记录各层输入输出与审核状态；冷启动/import/load/hash/传输、热推理、CPU保存、排队、审核等待、总墙钟与token/费用分别计时。已有批准只在绑定身份仍匹配时复用；未审的新结果保留候选状态。准备及缓存命中用时不混为首次生成吞吐。
3. Dev主档TTS已为batch2。若做配音因果对照，在同一冻结Layer 2文本上显式另跑batch1，其余设置不变，并固定回转写档位；新执行身份、新目录，不覆盖任一档，不重新翻译。按中/韩/西分别检查完整自然句、长句、覆盖、完整解码、回转写与听审。mixed batch4/8旧引擎诊断不作为正式单语言默认值依据。
4. 回转写主档为batch4；固定同一组WAV，对照batch1/8；每档用独立输出与unit-cache目录，不能共享包含不同batch身份的缓存。保留所有批次的疑点并人工裁决，不能选择“机器通过”的档位抹掉其他档位发现的问题。西语 `es-short@es-b2` 的Soy/So差异继续待听审。
5. 仅CPU瓶颈实际出现时再独立比较worker1/2；仅需校准文字并发收益时再独立比较worker2/3，并计入预算。主配置组合测试不用于单变量归因；额外对照一次改变一个变量，记录provider cache-read/write和输出长度；恢复段、失败累计与不中断基线分开。单次结果不得宣布稳定整周增益。
6. Dev交付沿用[四层Dev流程](backend-four-layer-dry-run.zh.md)，从模拟接链到Layer 1–4交接与Dev测试页，分别核对HTTP/hash和设备状态。真实模型计时写在独立性能收据中；固定响应模拟器和已批准缓存回放只证明其各自范围，不能充当模型性能验收。缺少人审时不构造正式批准或发布包；任何Dev页面准确标注候选/模拟与实际覆盖范围。

## 接受与后续调整

结果至少保存实际argv/传入限制、模型和声音身份、有效batch与worker峰值、逐单元覆盖/质量、全轨解码、执行与资源等待时间、缓存命中、预算/usage、回转写差异及人工裁决。检查配置实际被producer消费后才标记该项 `executed`，日志写入profile路径本身不是证据。

批处理候选先通过代表性质量与听审，再通过10分钟整链，才讨论升级正式默认；整周仍须单独验收。本页不预设必须提速多少，不把既有机器复核改为人审批准。原7h15/3h15估算保留，CPU收益仍未证实。本轮数字依据见[组件验收报告](local-production-performance-acceptance-20261001.zh.md)，状态归属仍为 `DEV-SPD-001/002/003/004`。

## 接入验证

两处正式CLI、Dev入口与profile loader的定向回归通过；覆盖默认配音2/回转写4到实际batch调用、短尾、一次load、生产仍1、显式1/8、错配置/权重GPU前拒绝、失败无verified回执、不自动重试、重复选择复用旧音频、消费回执不覆盖，以及对照pass不删除旧requires_review。验证使用假模型与合成PCM，不能代称下一轮真实模型计时或音质验收。语法、两个入口CLI help、profile JSON、文档链接与git差异空白检查通过。

复现接入回归（使用已有项目依赖Python）：

```sh
PRODUCTION_PYTHON=/absolute/path/to/existing-production-env/bin/python
"$PRODUCTION_PYTHON" -m unittest tests.test_dev_audio_test_profile \
  tests.test_dev_local_audio_entry tests.test_formal_audio_batching \
  tests.test_render_formal_target_language_speech tests.test_screen_target_language_audio_units -q
```
