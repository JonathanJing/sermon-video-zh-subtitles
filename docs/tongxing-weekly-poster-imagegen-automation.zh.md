# 周海报主视觉：headless ImageGen 接入与设计流程合同

状态：**2026-11-01 已接入 `delivery.posters.artwork` 入口，未接入默认周更或 Supervisor**。本文记录一条可用的 `codex exec` → 内置 ImageGen 路径、已验证的边界，以及把「设计 → 主视觉 → 合成」接成流程所需的三段合同。它不改变[海报格式规范](tongxing-weekly-poster-format.zh.md)、不提升任何页面或海报状态，也不授权上传或发送。

## 结论先行

1. **能连，且不需要图片 API key。** 当前 Codex CLI（`0.166.0-alpha.5.1`）内置 `image_gen.imagegen` 工具（feature `image_generation` 为 stable），`codex exec --json` 可以在无会话、无 shell 的情况下调用它，一次产出一张 2:3 竖版 PNG。
2. **缺口不在「调用」，在「交接」。** 现在的主视觉 prompt 由会话里的 agent 手写，图片靠人工从 `~/.codex/generated_images/` 拷给 `delivery.posters.build --art`；收据只绑定 `artSha256` 和 `promptSha256`，没有绑定线程、模型和图片自带来源。每周都要重做同一套手工动作。
3. **建议接成三段**：`design`（把已核实 brief 变成可校验的 prompt 文件）→ `artwork`（headless 生成，已实现并验证）→ 现有 `build --art`（合成二维码与文案）。每段都留下可 resume 的收据，任何一段失败都不阻塞页面发行。
4. **不要让图像模型解经。** 设计阶段的证据必须引用已发布文稿的 `textGroupId`；图像只负责画，不负责选主题、写标题或判断内容。

## 已核实的调用事实（2026-11-01）

一条最小调用（无 shell、只允许图像工具；实现里另固定 `approval_policy=never` 并抑制实验功能警告）：

```bash
codex exec --json --ephemeral --skip-git-repo-check \
  -m gpt-6.1-sol -c model_reasoning_effort="medium" \
  -s read-only --enable image_generation \
  --disable shell_tool --disable unified_exec --disable apps \
  --disable browser_use --disable computer_use -c web_search="disabled" \
  -o result.txt -
```

| 事实 | 观察值 | 对流程的含义 |
|---|---|---|
| 工具合同 | `image_gen.imagegen`，参数 `prompt`、`transparent_background`、`referenced_image_paths`、`num_last_images_to_include`；无尺寸参数 | 比例只能写进 prompt 再校验产物；不合格要重写 prompt，不能裁切 |
| 产物位置 | `$CODEX_HOME/generated_images/<thread-id>/exec-<uuid>.png`（文件夹名等于 `thread.started` 的 thread id） | 用生成前后的快照 diff + 线程目录校验来绑定，不解析正文 |
| 尺寸 | 1024 × 1536（精确 2:3） | 与 1200 × 1800 画布同比例，现有 Swift 渲染器直接复用 |
| 事件流 | `thread.started` → `item.completed`(agent_message) → `turn.completed` | 本版本**没有**图像生成 item；不能像文本工具那样从事件里读参数或 generation id |
| 图像自带来源 | C2PA `caBX` chunk：manifest URN、`xmp:iid`、`softwareAgent=ChatGPT`、`version=gpt-image`、创建时间 | 收据可绑定来源字节；但版本字段只到 `gpt-image`，**不能**据此声称 2.5 或具体子版本 |
| 用量 | 端到端一次（`gpt-6.1-sol`）：输入 51,223 / 缓存 30,976 / 输出 235 tokens，24.9 秒 | 工具说明占输入大头；每周一张可接受，但按文本调用的 10 倍量级预留时间与额度 |
| 认证 | ChatGPT 登录；`auth.json` 无 API key；子进程剥掉 `OPENAI_*` / `CODEX_API_KEY` | 符合「不加额外 key、不走隐藏 API」的既有边界 |

历史记录里的 `gpt-image-2.5-sunburst` 来自**回退 CLI**（`scripts/image_gen.py`，要求 `OPENAI_API_KEY`），与本文的内置工具不是同一条路径；两者不能混写成一个模型身份。

## 目标流程

```text
Layer 4 页面发布 + HTTP 核验
        │
        ├── 1 prepare   delivery.posters.build（不传 --art）  → poster-brief.json
        │                                                        status=awaiting_image_generation
        ├── 2 design    poster-design.json（12 个字段 + 证据 + 完整 prompt）
        ├── 3 artwork   codex exec + image_gen                  → art.png / art-prompt.txt / art-receipt.json
        ├── 4 compose   delivery.posters.build --art --art-prompt → 各语言 PNG + 双二维码解码 + receipt
        └── 5 review    目视检查 → --visual-reviewed；上传/发送另需明确授权
```

第 1、4、5 段已经存在，本节只新增 2、3 两段。

### 第 2 段：设计合同

产物是一个 JSON（建议 `poster-design.json`），字段与 [内容 brief](tongxing-weekly-poster-content-brief.zh.md) 的表格一一对应：

| 字段 | 校验 |
|---|---|
| `pageId`、`sourceIdentitySha256`、`contentSha256` | 与第 1 段 brief 逐字相同 |
| `centralMessage`、`tension`、`response`、`visualConcept`、`primarySubject`、`setting`、`supportingElement`、`mood`、`colorAndLight`、`meaningToPreserve`、`meaningToAvoid` | 非空；`supportingElement` 至多一个 |
| `evidence` | 至少两条 `{textGroupId, quote}`，`textGroupId` 必须存在于该 locale 已发布 content 的 `cues[].textGroupId` |
| `artPrompt` | 由[提示词模板](prompts/tongxing-weekly-poster-content-template-v1.txt)展开，不得残留 `{{...}}`，长度上限固定 |

填写者可以是人、交互式 agent 或一次有 schema 的文本调用；**合同先于实现**：只有通过上述校验的 JSON 才能进入第 3 段。若由文本模型生成，复用现有无工具文本通道（`gpt-6.1-sol`），并把 prompt 哈希、模型身份和 call id 写入收据；它仍然只是机器起草，不因此获得内容批准。

### 第 3 段：主视觉合同（已实现）

实现在 [`delivery/posters/artwork.py`](../packages/production/src/tongxing_production/delivery/posters/artwork.py)，通过统一入口运行：

```bash
.venv/bin/python tools/ops/run.py delivery.posters.artwork \
  --prompt artifacts/sermon-poster/YYYY-MM-DD/design/art-prompt.txt \
  --out artifacts/sermon-poster/YYYY-MM-DD/artwork
```

它做且只做这些事：

1. 拒绝未展开的 prompt、拒绝非 ChatGPT 认证、剥离子进程里的 API key；
2. 先写 `started.json` 再派发，超时记为 `unknown_outcome`，不自动重派；
3. 用快照 diff 找出本次线程目录里**恰好一张**新 PNG，并核对外层回复指向同一文件；
4. 校验 PNG 签名与精确 2:3，抽取 C2PA 来源；
5. 复制 `art.png`、`art-prompt.txt`，写 `art-receipt.json`；
6. 已有收据且 prompt 与图片哈希未变时直接复用，不再派发；
7. 不合成、不上传、不修改 release，也不把机器检查写成人工审核。

命令与参数：`--prompt`（已展开的 prompt 文件）、`--out`（全新目录）、`--model`（默认 `gpt-6.1-sol`）、`--timeout-seconds`（默认 600）、`--dry-run`。

收据字段（`tongxing-poster-artwork-v1`）包含：`promptSha256`、`artSha256`、`width/height`、`threadId`、`savedPath`、`c2pa`（manifest URN、`xmp:iid`、`softwareAgent`、版本、chunk 哈希）、`usage`、`cliVersion`、`cliSha256`、`adapterSha256`、`elapsedSeconds`、`promptDelivery=model_mediated_unverified`、`humanApproval=false`。

**必须诚实标注的未知项**：真正送给图片后端的 prompt 由模型在工具调用里生成，`codex exec --json` 看不到，也没有 `revised_prompt`/`generationId`。因此收据只声明「意图 prompt 的哈希」和「产物的哈希与 C2PA」，不声明 prompt 逐字送达。若以后需要这一证据，改走 app-server 协议：其 `ImageGenerationThreadItem` 明确定义了 `savedPath`、`generationId`、`revisedPrompt` 与 `failure`。

### 第 1/4/5 段如何衔接

第 4 段不变：

```bash
.venv/bin/python tools/ops/run.py delivery.posters.build \
  --release artifacts/weekly-release/new-release --page-id '<pageId>' \
  --origin https://ai-for-god-sermon-audio.web.app \
  --art artifacts/sermon-poster/YYYY-MM-DD/artwork/art.png \
  --art-prompt artifacts/sermon-poster/YYYY-MM-DD/artwork/art-prompt.txt \
  --out artifacts/sermon-poster/YYYY-MM-DD/four-locale
```

同一份主视觉继续被中／韩／西（可选英语参考）复用；`build` 已负责语言范围、双二维码解码、`--visual-reviewed` 与收据。第 5 段仍是目视检查与人工决定；本流程不新增任何自动上传。

## 失败、成本与边界

- **未知结果不重派**：超时留下 `started.json` + `unknown_outcome`，与现有 Codex transport 的处理一致；核对后换新目录重做。
- **已知失败可换目录重跑**：完成但没出图、出两张、比例不对、回复与产物不一致，都会写 `outcome.json` 并保留事件日志；这些是已知失败，不触发自动重试。
- **每周一张**：主视觉只生成一次，各语言复用；不要按语言分别生成。
- **成本不进四层预算**：内置 ImageGen 没有金额收据，`usage` 只有 token；报表保留 unknown，不记零，也不把这张图算进 Layer 1–4 的付费阶段预算。
- **生成有随机性**：同 prompt 不保证同构图；重做意味着新的 `promptSha256` 或新目录，旧收据不覆盖。
- **版本漂移**：`codex exec --json` 的事件形状可能随 CLI 升级变化；收据已绑定 `cliVersion`/`cliSha256`/`adapterSha256`，升级后需回归一次。

## 分阶段落地

| 阶段 | 内容 | 验收 |
|---|---|---|
| P0 ✅ 2026-11-01 | 已落地 `packages/production/src/tongxing_production/delivery/posters/artwork.py`，注册 `tools/ops/run.py delivery.posters.artwork`，13 个离线单测；未改默认 Supervisor | 单测 + `--dry-run` + 一次真实生成，收据字段齐全 |
| P1 | 定义 `poster-design.json` 合同与校验器（证据 `textGroupId`、无占位符、字段非空），先由人工/agent 填写，再评估是否用文本模型起草 | 一份真实本周设计通过校验并驱动 P0 |
| P2 | 周更编排里在 Layer 4 HTTP 核验后自动跑 P0/P1，停在「待目视」状态；定时任务仍不自动上传或发送 | 连续一周真实产物与既有 `build` 串通 |
| P3（可选） | 改走 app-server 线程事件，拿到 `generationId`/`revisedPrompt` | 与 P0 收据逐项对齐 |

## 验收

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_poster_artwork.py' -v
.venv/bin/python tools/ops/run.py delivery.posters.artwork --prompt <prompt.txt> --out <fresh-dir> --dry-run
.venv/bin/python tools/ops/run.py delivery.posters.artwork --prompt <prompt.txt> --out <fresh-dir>
```

离线单测覆盖：成功绑定、续跑复用、prompt 变化拒绝、图片被篡改拒绝、无图/多图/比例不符/失败回合、超时未知结果、API key 剥离、非 ChatGPT 认证、占位符拒绝、dry-run。真实调用另见「已验证的调用事实」。

## 未验证与风险

- 本文只验证了「能生成一张合格的 2:3 无文字底图」和「能绑定产物」；**没有**验证 prompt 原样送达、图像内容与证道的语义正确性、上传或真机展示。
- 内置工具没有尺寸参数，比例由模型按 prompt 决定；比例不符时必须重写 prompt，不能靠裁切掩盖。
- C2PA 在本入口里只抽取字段与 chunk 哈希，**未验证签名链**；版本只给到 `gpt-image`，不能据此声称具体模型子版本，也不构成内容审核证据。
- 图像模型可能画出不经意的宗教符号或文字残影；第 5 段目视检查仍然必要，`humanApproval=false` 不变。

## 证据位置

- 实现与单测：`packages/production/src/tongxing_production/delivery/posters/artwork.py`、`tests/test_poster_artwork.py`（13 个用例全部离线通过）。
- 真实调用产物、prompt、事件日志与收据在本地忽略目录 `artifacts/poster-imagegen/`，不提交 Git。
- 2026-11-01 通过统一入口实测：`gpt-6.1-sol`、24.9 秒、1024 × 1536、`artSha256=45ab4796…`、`threadId=01a197e5…`、`savedPath=generated_images/01a197e5…/exec-95e7af25….png`、C2PA `urn:c2pa:009f0a85…`；同 prompt 再次运行直接复用收据，没有第二次派发。
- 验证命令见「验收」。
- 相关既有合同：[海报格式规范](tongxing-weekly-poster-format.zh.md)、[内容 brief](tongxing-weekly-poster-content-brief.zh.md)、[每周海报交付](tongxing-weekly-release.zh.md#每周海报交付)、[环境准备](environment-preparation.zh.md)。
