# 同行每周内容发行

本流程接收既有生产脚本生成的单周候选包，保存完整历史目录，再核验发布后的公共资源。它不调用模型、不重新生成音频、不授予内容审核或现场同步批准，也不创建或替换现有定时任务。生产和配音仍按 [本地生产 runbook](codex-local-production-runbook.zh.md) 执行。

## 每周路径

来源完整可用 → 现有流程生成候选 → 内容审阅与对应音轨收据 → 组装完整发行包 → 检查目录差异 → 发布 → HTTP 文件核验 → App 刷新/下载验收。

周次、source route 和 source ID 共同决定内容项。同一周的直播归档与独立 YouTube 视频分别保留。已存在的源身份不能借同一个 page ID 改写。音频与审核声明沿用各页原始数据，不因进入发行清单而升级。

## 一次性建立发行清单

从当前线上对应的本地完整发行包开始。`build-report.json`、`public/` 文件和反馈目录均须通过现有契约与哈希检查。先验证线上内容，再登记已发布基线：

```bash
python3 experiments/sermon-dubbing-poc/verify_weekly_release.py \
  --release /absolute/path/to/current-release \
  --origin https://ai-for-god-sermon-audio.web.app \
  --out artifacts/weekly-release/current-http-verification.json

python3 experiments/sermon-dubbing-poc/weekly_release.py bootstrap \
  --registry artifacts/weekly-release/registry \
  --release /absolute/path/to/current-release \
  --origin https://ai-for-god-sermon-audio.web.app \
  --verification artifacts/weekly-release/current-http-verification.json
```

不传 verification 时，只登记为 `baseline_registered_local`，不能称为线上验证通过。重复 bootstrap 拒绝覆盖。清单及媒体保存在 ignored artifacts 中。

## 准备新一周

用已有 `build_weekly_app.py` 生成本周候选包，再合入登记过的内容：

```bash
python3 experiments/sermon-dubbing-poc/weekly_release.py prepare \
  --registry artifacts/weekly-release/registry \
  --candidate /absolute/path/to/new-week-candidate \
  --out artifacts/weekly-release/new-release
```

查看新包的 `release-plan.json`。它列出 added、updated、unchanged、removed，不允许删除历史页。已有页面内容发生变化时，必须在 prepare 命令中用 `--replace-page <page-id>` 明确选择，多个页面可重复传入；同源重建也遵守这一规则，防止候选包的历史占位页覆盖旧音频。替换后保留候选页的审核状态，不自动升级批准。

该命令复用登记版本的 UI、声音库、反馈开关与其他设置，保留旧哈希媒体地址，并为合并后的全部页重建反馈目录。候选包中附带的页面代码更新需走单独 UI 发布流程；候选声音库与登记版本不一致时拒绝合并，声音库变更须单独审阅发布。

输出目录必须是新目录，不能位于 registry 或 candidate 内。准备过程不推进 registry head。`build-report.json` 与发行计划绑定候选输入、上一版本及上一代 generation，避免并发候选覆盖较新的发行记录。

## 发布与核验

使用既有发布程序及对应站点的已有授权。若启用反馈功能，须按既有反馈部署流程同步新包中的 `feedback-catalog.json`。本模块不自动修改反馈服务、发布 Hosting 或授权消息推送。

发布后立即执行：

```bash
python3 experiments/sermon-dubbing-poc/verify_weekly_release.py \
  --release artifacts/weekly-release/new-release \
  --origin https://ai-for-god-sermon-audio.web.app \
  --out artifacts/weekly-release/new-http-verification.json

python3 experiments/sermon-dubbing-poc/weekly_release.py record-published \
  --registry artifacts/weekly-release/registry \
  --release artifacts/weekly-release/new-release \
  --verification artifacts/weekly-release/new-http-verification.json
```

核验覆盖全部公开文件的实际 GET、大小与 SHA-256，并对每个 MP3 检查 HTTP 206、Content-Range 和首段字节。完整读取可能产生站点流量费用。失败会写报告并返回非零状态，不得继续登记成功。核验器限制总下载字节、总时长和单次请求时长，并拒绝跨来源或降级跳转。

登记命令要求完整文件与 Range 检查均通过，且绑定本次 build-report、站点和当前 registry head。成功状态为 `published_http_verified`，不等于真机或现场验收。重复登记同一已验证版本保持幂等。

随后验证 App 刷新能列出新内容、来源与审核提示正确、下载及离线读取可用。新内容的现场同步另行验收；HTTP 报告始终明确标注客户端未测试，不能代替此步骤。

## 历史与恢复

`registry/releases/<release-id>/` 保留每版完整内容和媒体，`registry.json` 保留版本顺序。上一版本由 release-plan 的 `rollbackReleaseId` 指明。回退前应明确选择该快照，经已有发布入口重新部署并重新核验；本版没有自动回退或删除历史的命令。

准备失败只清理本次临时目录，不修改当前 head。并发期间 head 变化会使旧候选的登记失败；使用新 head 重新 prepare。核验旧收据不能代替实际发布后的新检查。

音频指纹索引现通过 `sermon-audio-fingerprint-binding-v1` 接入：只接收同源、哈希命名的 `/fingerprints/<sha16>-landmarks.json`，并核对源视频 SHA、页面、证道窗口、同步中文音轨 SHA 和数值特征结构；不发布原声或采集音频。历史页及指纹文件随发行快照保留，未绑定或损坏的索引会阻止发布。浏览器匹配使用同源 Worker；使用限制见 [现场声音定位](sermon-app-field-alignment.zh.md)。旧的 `track.alignment` 外部索引接口仍不支持。

## 验证命令

```bash
python3 -m unittest discover -s experiments/sermon-dubbing-poc -p 'test_weekly_release.py'
python3 -m unittest discover -s experiments/sermon-dubbing-poc -p 'test_verify_weekly_release.py'
python3 -m unittest discover -s experiments/sermon-dubbing-poc -p 'test_build_weekly_app.py'
```

前两组测试使用合成文件与可控 HTTP 响应，覆盖历史保留、来源冲突、哈希/路径、验证失败、并发登记与恢复。真实网络验证、App 验收及生产发布分别记录。

## Agents API 与费用边界

发行清单与 HTTP 核验仍是普通程序，本身不增加模型调用。2026-09-11 上游生产 Supervisor 已实现 Agents API 默认后端（Astra Medium）：以最小状态白名单选择现有确定性生产工具，保持人工审批、租约及发布校验。具体切换状态见 [生产 runbook](codex-local-production-runbook.zh.md) 与 [Supervisor 设计](sermon-production-supervisor-agent.zh.md)。配音候选审核及本章的 Firebase 发行流程仍需各自的有效收据，不能用 Agent 会话完成代替。

此前在 Codex 对话中完成的上层处理，使用的是所选 Codex 登录/计费方式。脚本内部单独调用的转写、翻译等 API 仍有自己的费用。切换到 Agents API 后，上层 Agent 模型调用也按 API 计费，不能视为已经包含在 ChatGPT 订阅里。

费用口径为全部模型调用的输入、缓存、输出（含 reasoning）之和，再加实际使用的工具、沙箱与第三方服务。多轮工具结果、子 Agent 和重试都会贡献用量；任务不是按“每篇页面”固定收费。使用 `environment: none` 和本机函数可避免托管沙箱这一项，但模型 token 与底层生产成本仍存在。

2026-09-10 查得 Astra 标准价：每百万 tokens 普通输入 $10、缓存读取 $1、缓存写入 $12.50、输出 $50。超过 272K 输入的单次请求有长上下文加价，其他运行模式也可能有不同价格。简单算例：累计 100K 普通输入与 10K 输出，在没有缓存写入、工具、沙箱和其他加价的条件下约 $1.50。这不是本项目每周实测费用或账单承诺。

Agents API turn usage 为 best-effort，可为 null，且不单列 cache-write count；费用报告必须保留 unknown 并与 Platform 账单核对，不能把未知记为零。实测会话既出现已知 token 计数，也出现 null；最终费用须对账。

来源：[Agents API 计费](https://developers.openai.com/api/docs/guides/agents-api/overview)、[用量口径与限制](https://developers.openai.com/api/docs/guides/agents-api/observability)、[Astra 价格](https://developers.openai.com/api/docs/models/gpt-6-astra)、[Codex 计费](https://learn.chatgpt.com/docs/pricing)。
