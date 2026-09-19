# 生产阅读稿的 MFA 词级对齐

新生成的 reading 模式默认 `--reading-aligner mfa`。在冻结英文 ASR 之后、本篇翻译之前优先在 MacBook 运行 MFA，将原稿句界定位到词/音素时间，取代字符比例估时。MFA 不生成语义句号；当前生产保留原英文标点作为句界依据，长度组织留给阅读块构建器。实验中的声学大模型分类器尚有漏断，不作为无人审核的生产句界来源。

## MacBook 优先，DGX Spark 备用

所有本地模型的目标路由为 **MacBook 优先、DGX Spark 备用**。MFA 与可选 G2P 先使用 MacBook 的独立环境；本机健康时不预检或联系 Spark。云端转写／语言模型继续调用原 API；听众浏览器的声音指纹是确定性匹配，不受模型路由影响。MacBook 的授权讲员检查点 TTS 也已单独完成真实短样本合成：一个 10 字中文单元生成 2.56 秒音频；整篇吞吐、音质与人工听审仍需独立验收。

MFA 本机组合为 3.4.2、官方 `english_mfa` 声学模型／词典与 `english_us_mfa` G2P，可在 CPU 上运行。安装独立环境并预先下载模型：

```sh
conda create -n sermon-mfa -c conda-forge montreal-forced-aligner=3.4.2
conda activate sermon-mfa
mfa model download acoustic english_mfa
mfa model download dictionary english_mfa
mfa model download g2p english_us_mfa
```

在实际 MacBook 调度进程中配置本机绝对路径：

- `MFA_EXECUTABLE`／`--mfa-executable`：MFA 可执行文件，或激活环境的包装脚本。
- `MFA_DICTIONARY`／`--mfa-dictionary`：本机英文 `.dict`。
- `MFA_ACOUSTIC_MODEL`／`--mfa-acoustic-model`：本机声学模型 `.zip`。
- `MFA_G2P_MODEL`／`--mfa-g2p-model`：本机 `english_us_mfa.zip`；建议配置处理未收录词。
- `MFA_SPOKEN_FORMS`／`--mfa-spoken-forms`：本机已确认读法 JSON；备用执行时连同哈希传给 Spark。

### 配置 Spark 备用

默认启用 Spark 备用；可用 `MFA_SPARK_FALLBACK=0` 或 `--no-mfa-spark-fallback` 明确禁用。`MFA_SPARK_FALLBACK=1`／`--mfa-spark-fallback` 则明确启用。Spark 使用独立的参数，不能把本机路径当成远端路径：

```sh
export MFA_SPARK_FALLBACK=1
export MFA_SPARK_HOST=achillesjing@192.168.1.152
export MFA_SPARK_PYTHON=/home/achillesjing/sermon-mfa-runtime/env/bin/python
export MFA_SPARK_ROOT=/home/achillesjing/sermon-mfa-runtime/jobs
export MFA_SPARK_EXECUTABLE=/home/achillesjing/sermon-mfa-runtime/bin/mfa-run
export MFA_SPARK_DICTIONARY=/home/achillesjing/sermon-mfa-runtime/models/english_mfa.dict
export MFA_SPARK_ACOUSTIC_MODEL=/home/achillesjing/sermon-mfa-runtime/models/english_mfa.zip
export MFA_SPARK_G2P_MODEL=/home/achillesjing/sermon-mfa-runtime/models/english_us_mfa.zip
```

`sermon_pipeline.py` 和 `run_post_live_subtitle_generation.py` 支持对应的 `--mfa-spark-host`、`--mfa-spark-python`、`--mfa-spark-root`、`--mfa-spark-executable`、`--mfa-spark-dictionary`、`--mfa-spark-acoustic-model`、`--mfa-spark-g2p-model` 参数。

MacBook 不在同一局域网时，经 Tailscale 的 Mac mini 中转：

```sh
export MFA_SPARK_RELAY_HOST=jonyopenclaw@100.73.116.52
export MFA_SPARK_RELAY_HOST_KEY_ALIAS=jonys-mac-mini.local
```

对应参数是 `--mfa-spark-relay-host` 与 `--mfa-spark-relay-host-key-alias`。已有本机可认证到 Spark 的 SSH 跳板配置时，也可使用 `MFA_SPARK_PROXY_JUMP`／`--mfa-spark-proxy-jump`；它与 relay 互斥。relay 在 mini 上发起第二段 SSH；ProxyJump 只转发连接，不取得 mini 的 SSH 身份。正常校验主机密钥，不关闭验证。

Spark 运行根目录为 `/home/achillesjing/sermon-mfa-runtime/`，分别保存 `env/`、`models/`、`bin/mfa-run`、`jobs/`。本次 ARM64 部署发现 Conda 的 `kalpy` 包不可直接取得，使用 [Spark MFA 安装脚本](../scripts/setup_spark_mfa.sh) 在独立环境源码构建。安装脚本包含 SQLite 依赖；修复原生 SQLite 运行依赖后，已验证 MFA 3.4.2 在 Spark 完成真实 A 样本对齐，详见下方冒烟记录。此结果只确认已测样本路径，不代表完整周次验收。MFA 可在 Spark CPU 执行，不必占用或重启现有 GPU 模型服务。

### 哪些失败可以使用备用

缺失本机环境／依赖、版本启动失败，以及推理过程中明确的运行故障（超时、进程被终止、可执行文件消失）可触发已配置的 Spark 备用。必须记录实际后端、触发原因和模型身份。禁用备用时保留本机错误并停止。

**文字不合法、未确认读法、未知音素、词序不符、对齐结果损坏、声音身份或人工审核问题都不能靠备用绕过。** 两端不可用则停止，保留已有产物。任务中不下载模型、不修改全局 Python；交互式终端的环境变量不会自动部署给后台 runner。

## 来源、缓存与失败

- 先预检 MacBook 环境。只有符合备用条件且已启用备用时才通过 SSH 预检 Spark；两端不可用时不进入付费转写。
- 原始 ASR 不改写。为对齐规范化大小写、展开明确整数，并保留原词到发音词的映射；含歧义数字表达时明确失败，需先提供确认的读法。G2P 候选不是人工验证发音。
- MFA 缓存绑定音频内容、参考文字、起止时间、模型/词典、工具版本及实现身份；内容变化使用新目录，缺失/损坏输出不复用。缓存绑定实际后端；本机成功无需联系 Spark。使用 Spark 时核对传输适配器、音频与读法映射的哈希，保留远端身份；复用 Spark 缓存仍须核对当前远端模型身份。
- 没有成功对齐所有所需词、出现未知音素、越界或零长度语音时停止；不自动回退为估算时间。
- `wordTimes` 与 `phones` 保存剪辑内时间；`timingQuality=mfa_word_aligned` 标记来源，仍是模型估计，不代表人工 Gold。结果保留 `requires_operator_review`。
- 人工英文修订改变文本后再次对齐，不能把旧词时间套到新稿。
- 翻译复制源片段时间；阅读构建器保留 MFA 源单元，不再次做字符比例插值。中文配音仍按中文译稿和实际合成音轨组织，不能将英文音素时间当作中文 TTS 时间。

历史结果和仍有效的源窗口审批保持不变。新 MFA 默认值改变输入指纹，旧字符估时缓存不会冒充 MFA；只有显式 `--reading-aligner legacy` 才能恢复旧规则，其时间继续标为 `synthetic_not_for_subtitles`。这个选项不是失败自动降级。字幕模式现有 Whisper 时间流程不在此次 reading 接入范围。

## 验证边界

定向离线测试覆盖默认路由、受限备用、来源身份、逐词匹配、词/音素时间、缓存损坏、阅读时间保留。

2026-09-19 使用同一冻结 A 样本与固定模型，完成两端真实 MFA 冒烟：

| 执行路径 | 结果 | 本次观测耗时 |
|---|---|---|
| MacBook 本机 | 16 个片段、148 个空格分隔原稿词 | 29.491 秒 |
| DGX Spark，未命中结果缓存 | 16 个片段、148 个空格分隔原稿词 | 28.104 秒 |
| DGX Spark，复用结果缓存 | 同一结果 | 4.405 秒 |

冻结英文逐字保留，输出继续要求操作员审核。上述耗时只是一轮样本冒烟记录，不是性能基准，也不能用来宣称 Spark 比本机更快或断句准确率提升。备用环境已在该样本完成真实对齐；整篇周次、中文翻译、双 PDF、配音和人工听审分别验收。MacBook TTS 已用同一授权讲员检查点完成 10 字中文短样本合成，输出 2.56 秒音频；该证据不批准整篇配音，也不衡量整篇吞吐或最终音质。之后在新 run 目录运行已获批准的来源窗口，不改写既有产物或审批。

## 数字和特殊读法

原稿出现章:节、小数或序数时，使用 `--mfa-spoken-forms /absolute/spoken-forms.json`（环境变量 `MFA_SPOKEN_FORMS`）提供操作员确认的对齐读法。JSON 将原稿的空格分隔 token（连同其标点）映射到英文发音词列表，例如：

```json
{"73:16": ["seventy", "three", "sixteen"], "2nd": ["second"]}
```

这只是格式示例，不能默认代表音频中真实读法。原文仍保留73:16；映射仅供MFA对齐并纳入缓存哈希。未提供映射的歧义表达会明确失败，不能依赖在MFA之后才执行的source-text-review来修复。修改映射后原始ASR可复用，对齐进入新的身份目录。

紧凑验证记录见 [MFA 路由样本](reports/20260919-mfa-routing-smoke.json)，本机缓存复跑为 4.534 秒。
