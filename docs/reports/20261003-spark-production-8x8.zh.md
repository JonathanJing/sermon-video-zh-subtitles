# 周日单讲员 Spark：生产选择 8 副本 × batch8

2026-10-03 决定：单讲员周日证道的正式 Layer 3 TTS 使用 **8×8**，入口为 [正式 renderer 的 `--spark-production`](../formal-layer3-renderer.zh.md#周日单讲员spark-生产按-88)。此 PR 实现同机八个驻留模型副本与固定窗口调度；不改变 Layer 1/2、回转写 ASR、听审、发布或双讲员路由。

## 选择证据

以 2026-09-27 中文 Eric 单讲员已有正式 job 的 **419 个完整片段、9539 字符**为工作量。抽取 64 个长度分位句，恢复来源顺序；最短／中位／平均／最长 3／20／22.94／70 字，完整任务对应 3／20／22.77／70 字。两配置使用相同文字、同授权 Eric checkpoint、相同 BF16/SDPA、temperature 0.7、repetition penalty 1.05、max tokens 768。冻结代码为 dev `b638dc9d30cf1ade606bd2c411074d5806564bd9`，模型 `75d28ce6022b3df3a72df3dd6dbc01e53f584d685770d60ea04b341920968c9a`。

| 配置 | 实际结果 | 64 段热运行墙钟 | 最低宿主 MemAvailable |
|---|---|---|---|
| 8 副本 × batch8 | 完成 warmup 和三次测量 | 57.01 / 56.78 / 56.81 秒，中位 **56.81 秒** | **38.43 GiB** |
| 16 副本 × batch4，同步加载 | 触发保护；0 worker 完成加载 | 无有效测量 | 23.65 GiB |
| 16 副本 × batch4，每次加载4个 | 16 个加载完成，随后并发 warmup 触发保护 | 无有效测量 | 22.73 GiB |

16×4 的分批加载共 162.20 秒，模型全部加载后尚余 36.47 GiB，但 warmup 仍突破 24 GiB 保留线。因此当前资源约束下选 8×8；不能从失败臂宣称 16×4 比它慢，也不能宣称硬件绝对无法运行 16 副本。未观察到 cgroup OOM 或新增 swap。8×8 测得峰值 GPU 使用率 96%、68°C。GB10 的 `nvidia-smi` 不提供可用的显存占用数字，宿主 UMA、cgroup 和 PyTorch CUDA 数据各有统计范围，不能相加。

每次热测量从同时释放全部 worker 到最后一个 worker 完成，含生成、PCM 保存、完整解码与哈希；每轮 286.4 秒音频。192 个测量文件 SHA 完成核验，三轮重复相同；连 warmup 共 256 个 WAV 完整解码。完整数字见[比较收据](../../data/benchmarks/spark-production-8x8/2026-10-03/comparison.json)。

## 419 段组件预算

- 均匀吞吐外推：`56.8056 × 419 / 64 = 371.90 秒`，约 **6.2 分钟**热 TTS。
- 加入实测 cold load barrier 54.65 秒：约 **7.1 分钟**。
- 若粗略按七轮满载计量：397.64 秒，约 6.6 分钟；它不是上下界。

这些是中文单讲员 TTS 组件估算。长短句负载不均、固定窗口、末批及资源竞争可改变实际值；未测完整 419 段，不包含回转写 ASR、整轨组装、正式输入验证、人工听审或 Layer 4。此前 4×8 试验用32句样本，不直接与这里的64句秒数对比。

## 新生产调度入口验证

在 Spark 同一 checkpoint/runtime 上运行新 pool、window scheduler 和正式 Qwen factory：64 个来源样本加3句诊断性重复，共 **67 段／9 个窗口**。八个模型全部 ready 后派发，验证 worker 驻留后处理第二轮的3句尾批。含 cold load、生成、PCM 保存及完整解码的墙钟 **119.88 秒**，模型 load barrier **52.01 秒**，采样最低 MemAvailable **38.51 GiB**。取回全部67个 WAV，逐个验证 SHA 和完整 PCM 读取；pool 的九个窗口结果和八条 ready 事件均齐全。测试 container 已退出，GPU 回到0%，宿主可用内存约117.8 GiB。

[新入口组件收据](../../data/benchmarks/spark-production-8x8/2026-10-03/dispatcher-smoke.json)绑定 pool／scheduler hash。此探针不运行完整来源、人审、声音授权和 Audio Package 准入，故标记 `complete_diagnostic`、`releaseEligible=false`；正式输入准入、419段覆盖、失败续跑与门禁保留由离线回归覆盖。探针后 renderer 的八副本 intent schema 标为 v2，合成 factory、pool 与 scheduler 未变；不将组件探针冒称整篇正式验收。

原始忽略产物位于本地 `artifacts/benchmark-spark-16b4-vs8b8-20261003-1755/`，新入口验证为 `artifacts/spark-8x8-dispatch-smoke/`；Spark 原始目录分别为 `results/sunday-single-speaker-16b4-vs8b8-20261003-1755`、同名 `-staged16` 和 `results/sunday-production-8x8-dispatch-20261003`。Git 只保存脱敏数字及实现，不提交原文、WAV、模型或运行时 archive。

离线相关回归共85项通过，覆盖实际 spawn 的乱序／有界派发、故障／进程退出／超时／内存保护清理，以及正式 renderer 的419句、尾批、CLI preset、重复写锁、未来缓存错误、部分提交恢复、原单副本／Dev profile 和裁剪路径。复现命令（使用已含 jsonschema 的项目 Python 环境）：

```bash
python -m unittest tests.test_spark_tts_production tests.test_spark_tts_replica_pool \
  tests.test_formal_audio_batching tests.test_render_formal_target_language_speech \
  tests.test_dev_audio_test_profile tests.test_compact_formal_target_audio
```

文档相对链接、证据 JSON、被测 pool／scheduler SHA、CLI help 与 `git diff --check` 均通过。本 PR 未部署后台服务、生成整周正式 Audio Package 或改动发布配置。
