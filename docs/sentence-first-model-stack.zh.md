# 逐句优先：模型栈与开工前安装清单

本文冻结 2026-11-15 第 10 周生产使用的转录、翻译和 TTS 身份，并列出开工前必须安装或处理的环境项。代码身份见同日锁定标签 `sfa-prod-20261115`；逐条哈希在忽略目录的 `artifacts/sentence-first-agent/20261115-rehearsal/stack-lock.json`。

冻结的是**模型、CLI、镜像、参数和脚本**，不是某一期的标题、经文、讲员或 run 名。每周按来源更新这些内容字段，不另换模型栈；要换栈就新建一份锁定并在 `run.md` 记明。

## 冻结表

| 层 | 身份 | 冻结值 | 关键参数 |
|---|---|---|---|
| L1 英文转录 | OpenAI API（`--environment prod`） | `whisper-1` 提供词级时间；`gpt-4o-transcribe` 提供文本 | whisper-1：`verbose_json`，`timestamp_granularities=["word","segment"]`，`language=en`；gpt-4o-transcribe：`response_format=text`，每 240 s 在最近词界切块，单块上限 1400 s |
| L2 逐句翻译 | Claude Code CLI | 2.1.325；`--model opus` → `claude-opus-5-5` | 每语 4 片、4 并发；`--permission-mode acceptEdits`；合并后另一 Opus 子代理只读审计 |
| L3 Spark TTS | Qwen3-TTS 12Hz 1.7B Base | Registry revision `fd4b254…`；镜像 `nvcr.io/nvidia/pytorch:26.06-py3` | batch 8、seed 7、`--steps tts`；ASR 已退役；独占会话最低 96 GiB |

## L1 OpenAI 转录

- 启动器：`tools/ops/run_with_openai_environment.py --environment prod -- <command>`；凭据文件 `.env.openai`（权限 600）。正式内容用 `prod`，实验和测试用 `dev`，两套都在同一文件里。
- 模型可用性：2026-11-14 在 prod 项目用 models 列表核对，`whisper-1`、`gpt-4o-transcribe`、`gpt-4o-mini-transcribe` 均可见；本轮没有发起付费转写。
- 脚本（`20261108-sermon-source/layer1/`）：
  - `transcribe_openai.py` — `76cf462d…`，whisper-1 词级时间；
  - `transcribe_second_pass.py` — `d7abd45e…`，gpt-4o-transcribe 分块文本，检查每块尾部是否落在词界；
  - `build_anchor_manifest.py` — `43c182e6…`，按词序对齐两路，生成 `sermon-sentence-anchor-manifest-v2`；
  - `build_english_source.py` — `63529cb7…`，绑定窗口、媒体哈希、审批收据和模型身份。
- 提示词是**本期内容**：标题、经文、讲员、已核实人名写入 `PROMPT`，不能沿用上一期；`words.json`/`TOTAL` 也按本期媒体更新。
- 英文表仍要人审：转录模型身份只证明文本来源，不代替人工批准。

## L2 Opus 翻译

- CLI：`/opt/homebrew/bin/claude`，版本 `2.1.325`（npm `@anthropic-ai/claude-code@2.1.325`）；`claude auth status` 显示 `loggedIn: true`、`authMethod: claude.ai`，登录有效期到 2026-12-12；过期后重新 `claude auth login`。
- 模型：`--model opus` 解析为 `claude-opus-5-5`（由 `--output-format json` 的 `modelUsage` 确认）。
- 调用：`claude -p <prompt> --model opus --permission-mode acceptEdits`；每语 4 片、4 并发，单片超时 3600 s。
- 脚本：`dispatch_translation.py` — `64ee82a2…`（提示词与三语术语/语气约定）；`dispatch_audit.py` — `aa1c8b3f…`（只读保真审计）；`translate_parts.py` — `4bca6800…`（切分与合并）。
- 审计：主代理先把 `translations.jsonl` 复制成 `audit/translations.audit.jsonl` 并记哈希，审计子代理只读该副本、只写 `audit/audit-<locale>.jsonl`；改哪些句子由主代理决定。
- 冒烟（2026-11-14）：两句英文，输出两行合法 JSON，`done 2`，9.8 s，`claude-opus-5-5`，费用 $0.1485（含 15.7k cache creation）。整期 460 句的三语翻译本轮没有执行。
- 派发脚本里的 week-9 run 名是本期占位，今晚改成 `20261115-*`；提示词、模型和参数不变。

## L3 Spark TTS

- 模型：`Qwen/Qwen3-TTS-12Hz-1.7B-Base`，revision `fd4b254389122332181a7c3db7f27e918eec64e3`；Registry `config/speaker-voice-registry.json`（sha256 `8553d2a9…`）。
- 镜像：`nvcr.io/nvidia/pytorch:26.06-py3`，镜像 ID `sha256:9629b436…`；voice packages 在 Spark 固定路径。
- 讲员 checkpoint（路径见 runbook §6；Eric/Steve 已在 2026-11-14 重算哈希并与 Registry 一致，John 为 root 所有、只沿用 Registry 值）：
  - `eric_pilot` — `75d28ce6…`；
  - `steve_bang_lee` — `b480bc6a…`；
  - `john_thomas` — `3f722b17…`（Registry 记录）。
- 脚本：`spark_run.sh` — `4a73e62d…`；`tts_sentences.py` — `f22afce3…`；`tts_pool.py` — `559de1c6…`；`asr_check.py` — `a1a8e011…`；`spark_queue.py` — `266f2368…`；`spark_session_job.py` — `41e167f7…`。
- 参数：整期 batch 8、seed 7、`--steps tts`；单讲员 8 副本，双讲员 `--pool-replicas 8`（4+4）；不拉伸、不变速；改批量要先问用户。
- 冒烟（2026-11-14）：Eric、3 句、batch 1；3 个 0.96 s / 24 kHz wav，`MemAvailable` 111.5→111.6 GiB，`cudaReservedBytes` 峰值 4032 MiB，合并 26.9 s、maxLag 0.82 s。batch 8 的整期速度沿用 2026-10-23 的 2.68× 证据，本轮没有再跑整期。
- 会话：`spark-38f8`，最低 96 GiB；`begin` 前后按 runbook §0.5/§1 处理未登记容器与 `failed` 单元。

## 开工前安装与处理清单

| 项 | 状态 | 操作 |
|---|---|---|
| `firebase` CLI | 已装 15.29.0 | `npm i -g firebase-tools@15.29.0`；`firebase login:list` 必须已登录；`publish` 走 `firebase deploy` |
| Claude Code CLI | 已装 2.1.325 | `npm i -g @anthropic-ai/claude-code@2.1.325`；`claude auth login`；`claude auth status` 为 `loggedIn: true` |
| OpenAI 凭据 | 已配置 | `.env.openai` 权限 600；正式内容用 `--environment prod`；先用 models 列表确认 `whisper-1`/`gpt-4o-transcribe` |
| Synology 点目录 | 已补 | `firebase/dev/public/.well-known/apple-app-site-association` 与 `firebase/production-overlay/public/.well-known/apple-app-site-association` 缺失时从锁定 checkout 复制；Synology 不落点目录 |
| Spark `h3image` | 已停 | `bash ~/h3image/web/deploy/spark-h3.sh --stop`；`systemctl --user stop h3-image-studio.service`；生产后再启 |
| 停服务后的 `failed` 单元 | 有流程 | `systemctl --user reset-failed spark-api.service llama-server.service` → `reconcile` → `resume-begin`；不要新开 session |
| 裁切边距 | 有流程 | 单元 0 从 0.0 开始时 `--margin-before 0 --margin-after 8` |
| 发布门禁顺序 | 有约束 | 本页 stage2 部署后立刻跑 `sfa_publish_gate --require-guide --require-alignment`；此时本页应已是目录 `defaultPageId` |
| Bark 推送 | 未配置 | 钥匙串服务 `org.sermonvideo.production-progress` 不存在；`notify` 只做 plan，不阻断生产 |

## 验证命令

```bash
claude --version && claude auth status
firebase --version && firebase login:list
tools/ops/run_with_openai_environment.py --environment prod --check
# 模型可见性（免费，不转写）：
tools/ops/run_with_openai_environment.py --environment prod -- .venv/bin/python -c \
  "import openai; ids=[m.id for m in openai.OpenAI().models.list()]; print([i for i in ids if 'whisper' in i or 'transcribe' in i])"
ssh achillesjing@192.168.1.152 'sha256sum ~/dgx-spark-benchmark/results/sermon-voice-poc-20260905/checkpoints/checkpoint-epoch-0/model.safetensors'
```

## 边界

- 2026-11-14 验证的是：OpenAI 模型可见性、Opus 两句翻译与文件写入、Spark 三句 TTS 与合并；**未执行**整期转录、三语整期翻译、batch 8 整期 TTS、页面发布。它们仍按 runbook 在今晚执行并各自留证据。
- 机器复核不是人审：英文表、三语译文、每条整轨和每次部署仍由用户本人批准。
- 改变模型、CLI 版本、镜像、batch/seed 或任何脚本哈希，都要新建 stack lock；不要就地改这份记录。
