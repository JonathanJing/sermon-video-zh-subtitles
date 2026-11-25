# 复盘：20261121-mbp14-sermon-zh（第 10 周 zh 证道在本机重渲整轨）

## 结论先行

- **交付类型**：测试／验证（`component_verification` + 一条完整整轨），不是发布。线上第 10 周 zh 音轨不动、不回写、不替换，`humanApproval=false`，没有人耳听审。
- **最终状态**：`complete_diagnostic`。435 句全部渲染（435 个 WAV，0 个空文件），合并整轨 1,942.78 秒，完整解码 `ffmpeg -v error` 退出码 0。
- **本机 TTS 速度**：55 批（batch 8，seed 7，MPS/float32），合成墙钟 **535.1 秒**／音频 **1,586.1 秒**，**RTF 0.337（约 2.96× 实时）**；从进程启动到整轨合并完成约 **9 分 01 秒**（含 4.2 GB checkpoint 哈希、模型加载、逐句 WAV 写出与合并）。
- **内存（本轮问题的核心）**：起跑时 free+inactive+speculative **18.8 GiB**；全程 MPS 驱动峰值 **17.52 GB**，批后回落到 8.66 GB；可用内存最低 **9.53 GB**；swap 全程 3.49 GB 未增长。原默认门槛 20 GiB 在本机被证明过严，本轮据实测把门槛定为 **15 GiB**（见「可以改进」第 1 条）。
- **身份不同，字节不可互换**：同一 checkpoint、`seed=7`、batch 8 下，本机整轨 `8167d7e4…`（93,253,484 B／1,942.78 s）与已发布 zh 整轨 `93a031dc…`（93,245,804 B／1,942.6 s）长度几乎相同、字节不同（MPS/FP32 vs CUDA/BF16）。**这不是替换品**，只能作为本机路径的证据。

## 总时间

- 12:37:04 起进程（含 checkpoint SHA-256、加载模型），12:46:02 合并完成，12:46:05 收尾结束：**渲染+合并 9 分 01 秒**。
- 其中合成 535.1 秒；剩余约 3 分 26 秒是 checkpoint 哈希、模型加载、逐句 WAV 落盘与整轨合并/MP3/播放器。
- 导出器按 `journal.ndjson` 汇总出「墙钟 0m03s」，只覆盖 `finish_run.py` 的合并步骤：`tts_sentences.py` 不写 `journal.ndjson`/`timings.tsv`，本机 TTS 的墙钟在导出报告里会缺失（见「可以改进」第 2 条）。本轮数字取自 `tts-batches.jsonl` 与进程起止时间。

## 各层模型、耗时与速度

| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---|---|---|---|---|---|
| L1 来源 ASR | reused（2026-11-15 正式 run） | — | 0 | — | — | — | 0 | 来源 run 的 `sentences.jsonl` |
| L1 词级对齐（MFA） | reused | — | 0 | — | — | — | 0 | 同上 |
| L1 英文机器评审 | reused（人工已批准） | — | 0 | — | — | — | 0 | 同上 |
| L2 初译/审核/文本质检 | reused（2026-11-15 正式 run） | — | 0 | — | — | — | 0 | 复制来的 `translations.jsonl`、`review.json` |
| L3 配音（TTS） | Qwen3-TTS 12Hz 1.7B Base（Registry `fd4b254…`），checkpoint `75d28ce6…`，torch 2.14.0，MPS/FP32 | 固定 temperature 0.7、repetition 1.05、maxNewTokens 768、SDPA、seed 7 | 55 批（435 句） | 535.1 s | 1,586.1 s | RTF 0.337／2.96× 实时 | 0（本机 GPU） | `tts/tts-batches.jsonl`、`tts/tts-log.jsonl` |
| L3 回转写筛查（ASR） | not_run（2026-10-28 起退役） | — | 0 | — | — | — | — | — |
| 音频质检 | 仅完整解码（非听审） | — | 1 | — | 1,942.78 s | `ffmpeg -v error` 退出码 0 | 0 | `track.wav` |
| L4 构建与发布 | not_run | — | 0 | — | — | — | — | — |

运行时：`~/tts-runtime/venv`（CPython 3.12.16、torch 2.14.0、qwen-tts 0.1.1），经仓库 `artifacts/model-routing/macbook-tts/runtime` 符号链接使用。

### 内存与整轨事实

| 项 | 值 |
|---|---|
| 起跑可用（free+inactive+speculative） | 18.8 GiB |
| 本轮采用的起跑门槛 | **15 GiB**（原默认 20 GiB） |
| 冷首窗 MPS 驱动峰值 | 16.73 GB（探针）／全程 17.52 GB |
| 批后驱动分配（稳定） | 8.66 GB |
| 可用内存最低 | 9.53 GB |
| swap | 3.04 → 3.49 GB（探针阶段 +0.45 GB），整期未再增长 |
| 整轨 | 1,942.78 s，`8167d7e4…`，93,253,484 B |
| 已发布 zh 整轨（对照，未改） | 1,942.6 s，`93a031dc…`，93,245,804 B |
| 逐句时长差异（对照发布版） | 平均 0.32 s、最大 2.00 s；总音频 1,586.1 s vs 1,598.7 s |
| 同步 | `merge_track --gap 0.05`：`maxLagSeconds=4.93`，`sentencesOverLag8s=0`（闸门干净） |

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| 预检／内存门槛 | 20 GiB 默认门槛在本机不可达（桌面常开时 11.6–18.8 GiB） | 20 GiB 来自 2026-10 的 11.45 GiB 估算，未含整批激活峰值；实测冷首窗 16.73 GB | 占用资源前（dry run 拒绝） | 先用 16 句探针在 10 GiB 门槛下测真实峰值，再据实测把默认改为 15 GiB | `tests/test_sentence_first_local_tts.py`；探针 16 句 | 本 PR |
| 报告／导出器 | 导出器把整段墙钟算成 0m03s | `tts_sentences.py` 不写 `journal.ndjson`/`timings.tsv`，导出器只看到 `finish_run.py` | 占用资源后（导出报告时） | 报告按 `tts-batches.jsonl` 与进程起止手工记墙钟；改进项见下 | 无自动测试 | 本 PR |

## 可以改进的地方

| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 预检 | 起跑门槛改用实测值 15 GiB（已改默认与 runbook） | 冷首窗峰值 16.73 GB、13.7 GiB 起跑也能完成、整期最低 9.53 GB | 36 GiB 机器不必先退出浏览器才能开工，同时保留 ~1.3 GiB 余量 | 本地模型开发者 | 本 PR |
| 流程 | `tts_sentences.py` 写 `journal.ndjson` 的 `l3.tts` started/finished 与 TTS 墙钟，让导出器能自动汇总本机渲染 | 导出器只看到 3 秒 | 报告不用手工补数 | 本地模型开发者 | 待建 backlog |
| 速度 | 本机 RTF 0.337，优于 2026-11-09 组件估计（0.368），整期 zh 约 9 分钟；可据此更新 runbook §0.1 的保守估计 | 535.1 s／1,586.1 s | 排期更准 | 本地模型开发者 | 本 PR 已更新 15 GiB；速度取 2.4× 保守值暂不动 |
| 质量 | 本机整轨与发布版逐句时长平均差 0.32 s、最大 2.0 s，属于不同执行身份；若要替换线上音轨，必须人工整轨听审并另立收据 | `8167d7e4…` vs `93a031dc…` | 避免把「能跑」当成「可发布」 | 用户 | 遗留 |

## 实际覆盖范围

- 执行：L3 单讲员 zh-Hans 435 句、batch 8、seed 7、MPS/FP32；整轨合并（`--gap 0.05`）、review MP3（96 kbps）、逐句播放器；整轨完整解码。
- 复用：2026-11-15 正式 zh run 的 `sentences.jsonl`、`speech.jsonl`、`review.json`、`clip.json`、`translations.jsonl`、`decisions.json`；人工已批准译文；线上已发布音轨（只读对照）。
- 未执行：L1、L2 重跑；ko/es；人工整轨听审；发布、部署、回写；音频机器听审（已退役）。

## 遗留状态

- 产物在本机忽略目录 `artifacts/sentence-first-agent/20261115-jesus-is-better-zh-mbp14/`：435 WAV、`track.wav`、`review.mp3`、`review-player.html`、`schedule.json`、`tts-run.log`、`run.md`。
- 本机 `~/tts-runtime/{venv,checkpoint-75d28}` 是运行时身份；清 `artifacts/` 前要另存。
- 输出未上传、未替换线上；已发布 zh 音轨与页面保持原样。

## 外部可见的变化

- 无部署、无页面改动、无推送。本报告以分支 `feat/mbp14-sermon-track-20261115` 的 PR 进入 `dev`；同时该 PR 把本机起跑内存门槛从 20 GiB 调为 15 GiB（实测依据见上）。
