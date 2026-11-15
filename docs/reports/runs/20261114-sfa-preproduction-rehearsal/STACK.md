# 模型栈锁定：2026-11-15 第 10 周

本附录冻结今晚使用的转录、翻译和 TTS 身份；完整字段和脚本哈希在忽略目录的 `artifacts/sentence-first-agent/20261115-rehearsal/stack-lock.json`，面向操作的说明见 [模型栈文档](../../../sentence-first-model-stack.zh.md)。

| 层 | 身份 | 冻结参数 | 2026-11-14 验证 |
|---|---|---|---|
| L1 英文转录 | OpenAI prod 项目：`whisper-1`（词级时间）+ `gpt-4o-transcribe`（文本），经 `run_with_openai_environment.py --environment prod` 注入 | whisper-1 `verbose_json` + word/segment，`language=en`；gpt-4o-transcribe `text`，每 240 s 在最近词界切块，单块上限 1400 s | models 列表可见（98 个模型，两项都在）；未发起付费转写 |
| L2 逐句翻译 | Claude Code CLI `2.1.325`；`--model opus` 实际为 `claude-opus-5-5`；claude.ai 登录，有效期至 2026-12-12 | 每语 4 片、4 并发、`--permission-mode acceptEdits`；合并后独立 Opus 只读审计 | 两句冒烟：两行合法 JSON，`done 2`，9.8 s，$0.1485 |
| L3 Spark TTS | Qwen3-TTS 12Hz 1.7B Base（Registry revision `fd4b254…`）；镜像 `nvcr.io/nvidia/pytorch:26.06-py3`（`sha256:9629b436…`） | batch 8、seed 7、`--steps tts`，ASR 已退役；Eric `75d28ce6…`、Steve `b480bc6a…` 与 Registry 一致 | 三句 Eric 冒烟：3×0.96 s / 24 kHz，`MemAvailable` 111.5→111.6 GiB，`cudaReservedBytes` 峰值 4032 MiB，合并 26.9 s、maxLag 0.82 s |

## 开工前安装与处理

1. `firebase` CLI 15.29.0 已装并登录（`publish` 走 `firebase deploy`）；`firebase login:list` 必须显示已登录。
2. Claude Code CLI 2.1.325 已装并登录；`claude auth status` 必须 `loggedIn: true`，过期后重新 `claude auth login`。
3. OpenAI 凭据在 `.env.openai`（权限 600）；正式内容用 `--environment prod`，先用 models 列表确认两个模型可见。
4. Synology 镜像不落点目录：`firebase/dev/public/.well-known/apple-app-site-association` 与 `firebase/production-overlay/public/.well-known/apple-app-site-association` 已从锁定提交补回，复检 0 缺失。
5. Spark 的 `h3image`（SGLang）容器与 `h3-image-studio.service` 已停；今晚生产结束前保持停止，结束后再启。
6. 停 `spark-api`/`llama-server` 后单元可能变 `failed`：`systemctl --user reset-failed <unit>` → `reconcile` → `resume-begin`；不要新开 session。
7. 锚点单元 0 从 0.0 开始时，裁切显式带 `--margin-before 0 --margin-after 8`。
8. 发布门禁在 stage2 之后立刻跑；此时本页应已是目录 `defaultPageId`，并发发布别的页面会让 gate 失败。
9. Bark 钥匙串条目不存在；`notify` 只做 plan，不阻断生产。

## 边界

- 今天验证的是模型/CLI 可见性、Opus 两句翻译与文件写入、Spark 三句 TTS 与合并；**未执行**整期转录、三语整期翻译、batch 8 整期 TTS、页面发布。
- 机器复核不是人审：英文表、三语译文、每条整轨和每次部署仍由用户批准。
- 改变模型、CLI 版本、镜像、batch/seed 或任何脚本哈希，都要新建 stack lock，不要就地改这份记录。
