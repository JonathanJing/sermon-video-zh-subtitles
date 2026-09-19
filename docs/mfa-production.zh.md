# 生产阅读稿的 MFA 词级对齐

新生成的 reading 模式默认 `--reading-aligner mfa`。在冻结英文 ASR 之后、本篇翻译之前运行本地 MFA，将原稿句界定位到词/音素时间，取代字符比例估时。MFA 不生成语义句号；当前生产保留原英文标点作为句界依据，长度组织留给阅读块构建器。实验中的声学大模型分类器尚有漏断，不作为无人审核的生产句界来源。

## 安装与配置

在实际生产执行机建立独立环境。已实测组合为 MFA 3.4.2 + 官方 english_mfa 声学模型/词典、english_us_mfa G2P。GMM-HMM 模型可在 CPU 上运行，不依赖 Spark 服务。

```sh
conda create -n sermon-mfa -c conda-forge montreal-forced-aligner=3.4.2
conda activate sermon-mfa
mfa model download acoustic english_mfa
mfa model download dictionary english_mfa
mfa model download g2p english_us_mfa
```

设置以下环境变量，或给 `sermon_pipeline.py` / `run_post_live_subtitle_generation.py` 传对应 `--mfa-*` 参数：

- `MFA_EXECUTABLE`：该环境的 `bin/mfa` 绝对路径，或能激活环境的专用包装脚本。
- `MFA_DICTIONARY`：已下载的英文 `.dict` 文件绝对路径。
- `MFA_ACOUSTIC_MODEL`：已下载的英文声学模型 `.zip` 绝对路径。
- `MFA_G2P_MODEL`：已下载的 `english_us_mfa.zip`；建议配置，以处理讲道专名和未收录词。

MFA 默认将下载模型放在 `~/Documents/MFA/pretrained_models/`；若曾设置 `MFA_ROOT_DIR`，使用对应目录。自动化进程须获得这些环境变量；交互式终端的配置不会自动部署给后台 runner。运行中不下载模型，不修改全局 Python。

## 来源、缓存与失败

- 预检本地可执行文件及模型配置，依赖缺失时不进入付费转写。
- 原始 ASR 不改写。为对齐规范化大小写、展开明确整数，并保留原词到发音词的映射；含歧义数字表达时明确失败，需先提供确认的读法。G2P 候选不是人工验证发音。
- MFA 缓存绑定音频内容、参考文字、起止时间、模型/词典、工具版本及实现身份；内容变化使用新目录，缺失/损坏输出不复用。
- 没有成功对齐所有所需词、出现未知音素、越界或零长度语音时停止；不自动回退为估算时间。
- `wordTimes` 与 `phones` 保存剪辑内时间；`timingQuality=mfa_word_aligned` 标记来源，仍是模型估计，不代表人工 Gold。结果保留 `requires_operator_review`。
- 人工英文修订改变文本后再次对齐，不能把旧词时间套到新稿。
- 翻译复制源片段时间；阅读构建器保留 MFA 源单元，不再次做字符比例插值。中文配音仍按中文译稿和实际合成音轨组织，不能将英文音素时间当作中文 TTS 时间。

历史结果和仍有效的源窗口审批保持不变。新 MFA 默认值改变输入指纹，旧字符估时缓存不会冒充 MFA；只有显式 `--reading-aligner legacy` 才能恢复旧规则，其时间继续标为 `synthetic_not_for_subtitles`。这个选项不是失败自动降级。字幕模式现有 Whisper 时间流程不在此次 reading 接入范围。

## 验证边界

本地定向测试覆盖默认路由、无静默回退、来源身份、逐词匹配、词/音素时间、缓存损坏、阅读时间保留。真实音频冒烟记录另外保存。代码合并不等于生产执行机已安装模型，也不等于某周双 PDF 或配音完成；上线主机必须先安装并预检，再在新的 run 目录执行已获批准的来源窗口。

## 数字和特殊读法

原稿出现章:节、小数或序数时，使用 `--mfa-spoken-forms /absolute/spoken-forms.json`（环境变量 `MFA_SPOKEN_FORMS`）提供操作员确认的对齐读法。JSON 将原稿的空格分隔 token（连同其标点）映射到英文发音词列表，例如：

```json
{"73:16": ["seventy", "three", "sixteen"], "2nd": ["second"]}
```

这只是格式示例，不能默认代表音频中真实读法。原文仍保留73:16；映射仅供MFA对齐并纳入缓存哈希。未提供映射的歧义表达会明确失败，不能依赖在MFA之后才执行的source-text-review来修复。修改映射后原始ASR可复用，对齐进入新的身份目录。
