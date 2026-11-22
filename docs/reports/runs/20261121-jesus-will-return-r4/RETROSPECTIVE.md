# 复盘：20261121-jesus-will-return（第 11 周《耶稣必再来》）

## 结论先行

- 交付类型 `four_layer_release`，**正式页已上线**：`revelation-jesus-will-return-20261122`，三语 zh-Hans / ko / es。
- 结束信号：`sfa_publish_gate --require-guide --require-alignment` = **pass**（failed 空）；三语页面 smoke 200；
  `/english-reference`、`/alignment`、`/weekly-guides`、`/weekly-announcements`、`/api/session`（本页三语 + 上周三语）全部 200。
- 证据边界：人工听审是 `flagged_only`（用户逐条在对话中确认通过；最终音轨到确认的时间短于整轨时长，
  收据没有写成整轨）。统计目录本轮做了追加式写入（保留旧 49 条，加本页 3 条），**没有**修复 11-01/11-08/11-15
  的历史目录缺陷（那些属独立热修）。

## 总时间

墙钟 19:43–23:45 PDT（约 4 小时 02 分）。大致拆分：L1 约 35 分、三语翻译+审计约 20 分、L3 配音与三语重渲约 70 分、
L4 发布（两条发布意图共 4 次托管部署 + 一次函数部署）约 75 分、人工听审等待约 60 分、返工约 40 分。

## 各层模型、耗时与速度

| 层／阶段 | 模型或后端 | 调用 | 计算耗时 | 音频或 token | 速度 |
|---|---|---|---|---|---|
| L1 转写 | OpenAI `whisper-1` + `gpt-4o-transcribe` | 2 遍（9 块） | 79 s + 90 s | 6710 / 6676 词 | — |
| L2 初译 | Claude Code CLI `opus` 2.1.325 | 12 分片（6 并发） | 约 8 分钟 | 457 句 × 3 语 | — |
| L2 独立审计 | Opus（只读） | 3 | 58 / 57 / 42 s | 3–5 条问题 | — |
| L3 配音 | Qwen3-TTS 12Hz 1.7B Base，本机 MPS batch 8 | 3 语 × 457 句 | zh 675 s、ko 808 s、es 786 s | 34–36 分钟/条 | 2.5–3.1× 实时 |
| L3 同步 | 剪静音 + 逐句 atempo ≤1.15 | 3 语 | 每语 30–60 s | 回收 170–184 s/语 | — |
| L4 发布 | `sfa_publish` + guarded publisher | 2 意图 / 4 次部署 | 约 5 分钟 | 12 + 6 + 1 + 1 文件 | — |

## 错误

| 阶段 | 现象 | 原因 | 发现时机 | 处理 | 跟踪 |
|---|---|---|---|---|---|
| L2/L3 | 2000 年前后的年份读成「一千九百八十」「二千二十四」 | `spoken_forms.py` 把年份当普通数字 | 用户听审 | 加中文年份逐位读规则，只重配含年份的 2 个窗口 | PR #1617 |
| L3 | `lag_loop` 在重建 speech 时崩：`spokenForms keys not found` | 先跑 `spoken_forms`（读旧 translations）再让 `build_speech` 应用修订 | 资源占用后 | 先把采纳修订写回 `translations.jsonl` 再生成读法 | PR #1617 |
| L3 | 第一次追落后把 82 句压成残句（「可后靠，我不因失礼。」） | 用全局词数压缩代替静音裁剪 | 资源占用后 | 整轮作废、还原自然文本，改为「去静音 → 逐句加速 ≤1.15 → 最小删字」 | PR #1617 |
| L4 | 对齐 sidecar 绑不上目录（schemaVersion / release 哈希口径 / 窗口末值 0.0003 s 偏差） | sidecar 手工构造，三处口径与 binder 不一致 | 发布前 | 逐项对齐 binder 期望，索引按精确窗口重算 | 本轮 run.md |
| L4 | 目录重绑后 `publish` 报 `Baseline catalog differs` / `Baseline snapshot is incomplete` | 快照 seal-report 没跟着目录与新增文件更新 | 发布前 | 用 `baseline.catalog_report` + `files_report` 重新封存 | 本轮 run.md |
| L4 | `stage1` 拒绝覆盖已发布 content（想补 `sourceWindow`） | 已发布身份字节不能原地改 | 发布前 | 改为用精确窗口让 binder 接受无 `sourceWindow` 的旧字节；`sourceWindow` 只进驱动供以后使用 | PR #1617 |

## 可以改进的地方

| 类别 | 改进 | 依据 | 收益 |
|---|---|---|---|
| 流程 | 把「目录重绑后必须重封存」写进发布 playbook | 本轮两次 publish 失败均因此 | 每期省 10–15 分钟 |
| 质量 | 同步 run 默认「先剪静音、再逐句加速 ≤1.15」 | zh 24.79 s → 2.73 s、ko 16.94 s → 5.06 s、es 11.47 s → 7.65 s，且零删字 | 免掉全文重渲与残句风险 |
| 预检 | 第 11 周手册 candidate 只能等 release 上线后跑，要预留第 4 次部署 | 本轮把手册与海报合并成第二次发布意图 | 计划里写明部署预算 |
| 工具 | 反馈目录追加脚本（导出→追加→打包→部署→核验）目前是一次性脚本 | 本轮按 prep 文档手工执行 | 下期一条命令 |

## 实际覆盖范围

- L1：OpenAI 双遍转写、24 处修订、4 处合并、1 处批准后经文纠正；用户批准英文表。
- L2：三语各 4 分片 Opus 初译 + 独立 Opus 审计（zh 3 / ko 4 / es 5 条全部采纳）+ 口播读法。
- L3：三语本机 MPS 渲染、剪静音、逐句加速、落后闸门全 clean；人工听审（flagged_only）通过。
- L4：页面/文稿/字幕/MP3、release v2、目录 v3/v4/v5、英文对照、现场对齐、研读手册 week 11、统计目录、三语海报。

## 遗留状态

- 反馈目录历史缺陷（11-01 旧音轨、11-08/11-15 cue/时长口径）未修，建议单开热修意图。
- 三语海报的 600×900 预览文件未上传到 `/posters/`（公告只引用 1200×1800 主图）。
- DSH 右侧「进度」插件未在 web/desktop profile 启用；Bark 监听与局域网审核服务在听审结束后由用户停止。

## 外部可见的变化

- 生产页面：`https://ai-for-god-sermon-audio.web.app/pages/revelation-jesus-will-return-20261122/{zh-Hans,ko,es}/index.html`（smoke 200）
- 版本：`984daa88` → `211a29d7` → `baa21e9b` → `5d53e41c`；函数 `sermon-feedback-api-00026-yer`（updateTime 2026-11-22T06:35:11Z）
- 未做：真机 App 播放验收、物理扫码、TestFlight 推送（`not_run`）。
