# Archify 源与再生成

`tongxing-system-architecture.svg` 与 `sentence-first-weekly-workflow.svg` 由 [Archify](https://github.com/tt-a1i/archify) 的 `finalize` 生成。每张图的证据绑定在 spec 的 `meta.repository.revision` 上，节点的 `sources` 指向该提交里的代码与文档；图稿不证明上线、人工 Gold、设备或现场验收，事实以当前代码与合同为准。

## 再生成

```bash
# 1) 把下方对应 spec 复制成本地文件（例如 artifacts/diagrams/<name>.json），
#    从仓库根运行；--repo-root 会按 spec 钉的提交核对每个 sources 引用。
node <archify-skill>/bin/archify.mjs finalize architecture \
  artifacts/diagrams/tongxing-system-architecture.json \
  artifacts/diagrams/tongxing-system-architecture.html \
  --repo-root . --quality showcase --json

node <archify-skill>/bin/archify.mjs finalize workflow \
  artifacts/diagrams/sentence-first-weekly-workflow.json \
  artifacts/diagrams/sentence-first-weekly-workflow.html \
  --repo-root . --quality showcase --json

# 2) 打开生成的 HTML，点「导出 → SVG」。
# 3) 两处清理后再覆盖 docs/diagrams/ 下的同名文件：
#    - 删除 <style> 里的 @font-face 块（内嵌 WOFF2 base64，仓库约定不嵌字体）
#    - 根节点 <svg> 加 data-theme="light"，并去掉强制像素尺寸的 style 属性
```

spec 里的 `meta.output` 保留首次生成时的本地路径；`finalize` 的位置参数会覆盖输出位置，因此复制后可直接运行。改图必须重跑 `finalize`（它会同时校验 spec 与仓库证据、并跑浏览器门禁），再导出 SVG，不要手改 SVG。

## 系统总览（architecture）

证据提交 `7ddacddf1ec6b0142304926c8e57f10a5e682f14`：14 个组件、1 个本地环境边界、15 条关系、4 张卡片。README 中英两版「架构 / Architecture」章首引用。

```json
{
  "schema_version": 1,
  "diagram_type": "architecture",
  "meta": {
    "title": "同行（Tongxing）：四层多语言制作与发布架构",
    "locale": "zh-CN",
    "output": ".archify/architecture-tongxing-20261030-174309/tongxing-system.html",
    "quality_profile": "showcase",
    "repository": {
      "url": "https://github.com/JonathanJing/sermon-video-zh-subtitles.git",
      "provider": "github",
      "link_mode": "web",
      "revision": "7ddacddf1ec6b0142304926c8e57f10a5e682f14"
    }
  },
  "components": [
    {
      "id": "source",
      "type": "external",
      "label": "授权证道媒体",
      "sublabel": "YouTube / Resi 归档",
      "pos": [10, 300],
      "size": [132, 64],
      "sources": [
        { "path": "docs/workflows/README.zh.md", "line": 3, "end_line": 3, "label": "media source" },
        { "path": "packages/production/src/tongxing_production/workflows/dual_pdf/local_post_live_download.py", "line": 1, "end_line": 8, "label": "download + hash" }
      ]
    },
    {
      "id": "l1",
      "type": "backend",
      "label": "Layer 1 英文来源",
      "sublabel": "English Source Package",
      "tag": "source_review",
      "pos": [204, 300],
      "size": [132, 64],
      "sources": [
        { "path": "packages/production/src/tongxing_production/source/unified_stage.py", "line": 1, "end_line": 6, "label": "ASR + MFA + anchors" },
        { "path": "packages/production/src/tongxing_production/source/english_source_package.py", "line": 1, "end_line": 5, "label": "source package" }
      ]
    },
    {
      "id": "l2",
      "type": "backend",
      "label": "Layer 2 候选",
      "sublabel": "zh-Hans / ko / es",
      "tag": "机器复核",
      "pos": [398, 300],
      "size": [132, 64],
      "sources": [
        { "path": "packages/production/src/tongxing_production/text/candidate.py", "line": 1, "end_line": 5, "label": "candidate compile" },
        { "path": "packages/production/src/tongxing_production/text/policy.py", "line": 1, "end_line": 2, "label": "frozen locale policy" },
        { "path": "config/target-language-policies/zh-Hans.json", "label": "policy file" }
      ]
    },
    {
      "id": "l3",
      "type": "backend",
      "label": "Layer 3 音频",
      "sublabel": "Audio Package",
      "tag": "1× 听审",
      "pos": [592, 300],
      "size": [132, 64],
      "sources": [
        { "path": "packages/production/src/tongxing_production/audio/renderer.py", "line": 1, "end_line": 5, "label": "resume speech job" },
        { "path": "packages/production/src/tongxing_production/audio/package.py", "line": 1, "end_line": 4, "label": "fail-closed package" },
        { "path": "config/speaker-voice-registry.json", "line": 1, "end_line": 8, "label": "Qwen TTS base" }
      ]
    },
    {
      "id": "l4",
      "type": "backend",
      "label": "Layer 4 发布包",
      "sublabel": "Release Package",
      "tag": "七种资源",
      "pos": [786, 300],
      "size": [132, 64],
      "sources": [
        { "path": "packages/production/src/tongxing_production/delivery/app_release.py", "line": 1, "end_line": 6, "label": "prepare / verify / seal" },
        { "path": "docs/layer4-four-product-public-delivery.zh.md", "line": 9, "end_line": 20, "label": "seven public resources" }
      ]
    },
    {
      "id": "publish",
      "type": "backend",
      "label": "受限发布器",
      "sublabel": "guarded_hosting_publish",
      "tag": "基线 CAS",
      "pos": [980, 300],
      "size": [132, 64],
      "sources": [
        { "path": "tools/ops/guarded_hosting_publish.py", "line": 1, "end_line": 6, "label": "L4 publisher entry" },
        { "path": "packages/production/src/tongxing_production/delivery/publication.py", "line": 1, "end_line": 6, "label": "lease + live baseline" },
        { "path": "packages/production/src/tongxing_production/storage/hosting.py", "line": 1, "end_line": 7, "label": "Hosting + GCS adapter" }
      ]
    },
    {
      "id": "hosting",
      "type": "cloud",
      "label": "Firebase 托管",
      "sublabel": "Hosting · Dev/Prod",
      "pos": [1210, 300],
      "size": [132, 64],
      "sources": [
        { "path": "firebase/production-overlay/firebase.json", "label": "site config" },
        { "path": "docs/layer4-four-product-public-delivery.zh.md", "line": 9, "end_line": 20, "label": "public URL layout" }
      ]
    },
    {
      "id": "web",
      "type": "frontend",
      "label": "Web 阅读器",
      "sublabel": "listening-web",
      "pos": [980, 600],
      "size": [132, 64],
      "sources": [
        { "path": "apps/listening-web/app.mjs", "label": "reader module" },
        { "path": "docs/layer4-four-product-public-delivery.zh.md", "line": 54, "end_line": 54, "label": "v4 then v3 readback" }
      ]
    },
    {
      "id": "ios",
      "type": "frontend",
      "label": "iOS App",
      "sublabel": "SwiftUI + AVPlayer",
      "pos": [1210, 600],
      "size": [132, 64],
      "sources": [
        { "path": "apps/tongxing-ios/README.zh.md", "label": "iOS client" },
        { "path": "README.zh.md", "line": 92, "end_line": 92, "label": "consumes Layer 4 only" }
      ]
    },
    {
      "id": "listeners",
      "type": "external",
      "label": "听众",
      "sublabel": "Web / 手机",
      "icon": "person",
      "pos": [1050, 720],
      "size": [132, 64],
      "sources": [
        { "path": "README.zh.md", "line": 92, "end_line": 92, "label": "primary listening client" }
      ]
    },
    {
      "id": "artifacts",
      "type": "database",
      "label": "本地制品库",
      "sublabel": "artifacts/ 与收据",
      "pos": [786, 470],
      "size": [132, 64],
      "sources": [
        { "path": "packages/production/src/tongxing_production/orchestration/jobs.py", "line": 1, "end_line": 8, "label": "durable local jobs" },
        { "path": "docs/layer4-four-product-public-delivery.zh.md", "line": 68, "end_line": 68, "label": "snapshot + HTTP manifest" }
      ]
    },
    {
      "id": "providers",
      "type": "external",
      "label": "模型 API",
      "sublabel": "DeepSeek · OpenAI",
      "tag": "付费调用",
      "pos": [398, 110],
      "size": [132, 64],
      "sources": [
        { "path": "packages/production/src/tongxing_production/compute/transports/deepseek_layer2.py", "line": 1, "end_line": 5, "label": "Layer 2 transport" },
        { "path": "packages/production/src/tongxing_production/compute/transports/openai_layer2.py", "label": "OpenAI transport" },
        { "path": "packages/production/src/tongxing_production/compute/transports/claude_layer2.py", "label": "Claude transport" }
      ]
    },
    {
      "id": "spark",
      "type": "backend",
      "label": "DGX Spark",
      "sublabel": "CUDA · Qwen TTS",
      "tag": "算力主机",
      "pos": [592, 110],
      "size": [132, 64],
      "sources": [
        { "path": "docs/local-production-compute-policy.zh.md", "line": 1, "end_line": 3, "label": "Spark default, MacBook fallback" },
        { "path": "config/speaker-voice-registry.json", "line": 1, "end_line": 8, "label": "Qwen base model" },
        { "path": "packages/production/src/tongxing_production/audio/renderer.py", "line": 3, "end_line": 5, "label": "render cache identity" }
      ]
    },
    {
      "id": "receipts",
      "type": "security",
      "label": "审核收据",
      "sublabel": "人审 / 机器豁免",
      "pos": [398, 470],
      "size": [132, 64],
      "sources": [
        { "path": "packages/production/src/tongxing_production/text/human_review.py", "line": 1, "end_line": 5, "label": "text worksheet + admit" },
        { "path": "packages/production/src/tongxing_production/audio/human_review.py", "line": 1, "end_line": 4, "label": "listening is the only gate" },
        { "path": "packages/production/src/tongxing_production/review/waiver.py", "line": 1, "end_line": 6, "label": "machine quality waiver" }
      ]
    }
  ],
  "boundaries": [
    {
      "kind": "region",
      "label": "本地 MacBook 生产环境",
      "wraps": ["l1", "l2", "l3", "l4", "artifacts", "publish", "receipts"],
      "pad": 20
    }
  ],
  "connections": [
    { "id": "e-media", "from": "source", "to": "l1", "label": "下载" },
    { "id": "e-source-package", "from": "l1", "to": "l2", "label": "来源包", "variant": "emphasis" },
    { "id": "e-candidate", "from": "l2", "to": "l3", "label": "候选" },
    { "id": "e-audio", "from": "l3", "to": "l4", "label": "音频包" },
    { "id": "e-seal", "from": "l4", "to": "artifacts", "label": "封存", "fromSide": "bottom", "toSide": "top" },
    { "id": "e-snapshot", "from": "artifacts", "to": "publish", "label": "快照", "fromSide": "right", "toSide": "bottom", "via": [[1046, 502]] },
    { "id": "e-deploy", "from": "publish", "to": "hosting", "label": "部署", "variant": "emphasis" },
    { "id": "e-catalog-web", "from": "hosting", "to": "web", "label": "目录", "fromSide": "bottom", "toSide": "top" },
    { "id": "e-catalog-ios", "from": "hosting", "to": "ios", "label": "目录", "fromSide": "bottom", "toSide": "top" },
    { "id": "e-web-listeners", "from": "web", "to": "listeners", "fromSide": "bottom", "toSide": "top" },
    { "id": "e-ios-listeners", "from": "ios", "to": "listeners", "fromSide": "bottom", "toSide": "top" },
    { "id": "e-model-calls", "from": "providers", "to": "l2", "label": "翻译 / 复核", "fromSide": "bottom", "toSide": "top" },
    { "id": "e-render", "from": "spark", "to": "l3", "label": "TTS 渲染", "fromSide": "bottom", "toSide": "top" },
    { "id": "e-text-receipt", "from": "l2", "to": "receipts", "label": "人审", "variant": "dashed", "fromSide": "bottom", "toSide": "top" },
    { "id": "e-audio-receipt", "from": "l3", "to": "receipts", "label": "听审", "variant": "dashed", "fromSide": "bottom", "toSide": "right", "via": [[658, 502], [568, 502]] }
  ],
  "cards": [
    {
      "dot": "cyan",
      "title": "四层与门禁",
      "items": [
        "Layer 1 身份变化使全部 locale 失效；Layer 2/3 产物变化只影响该 locale 下游。",
        "human_gates 定义在 contracts/pipeline_definition.py：source_review、translation_review + voice_authorization、audio_listening_review、exact_release_authorization。",
        "该模块返回 dispatchEnabled=false：没有端到端派发器，操作员按层运行 tools/ops/run.py <area.module>。",
        "模型与算力：来源判定、翻译与复核走模型 API；MFA 词级对齐与 Layer 3 TTS 在 DGX Spark 运行，MacBook 为受限故障 fallback。"
      ]
    },
    {
      "dot": "emerald",
      "title": "制品与恢复",
      "items": [
        "artifacts/ 保存发布包、快照与收据；durable job 身份单次使用，未知结果先对账，不自动重跑。",
        "config/ 冻结模型与策略，schemas/ 版本化每个包与收据。",
        "每个包按哈希绑定来源、媒体、模型、提示与审核收据，过期证据只使后代失效。"
      ]
    },
    {
      "dot": "amber",
      "title": "发布与证据边界",
      "items": [
        "发布器先取线上基线并逐文件核对，部署后回读 v5/v4/v3 目录，传播窗口内重复只读。",
        "HTTP、浏览器 smoke、设备与现场验收分别记录；截图不等于现场验收。",
        "机器质量豁免写入 disclosure，页面标为机器质检，永不显示为人工批准。"
      ]
    },
    {
      "dot": "violet",
      "title": "未画入主线的路径",
      "items": [
        "周日实时字幕 live_session：experiments/local-live-poc，本地麦克风 → ASR → 中文字幕，保留独立录音。",
        "双 PDF 阅读版：workflows/dual_pdf，输出 output/pdf/，不进入发布包身份。",
        "反馈与推送：Cloud Functions（services/feedback、services/push）+ Firestore，客户端只走同源 /api/*。"
      ]
    }
  ]
}
```

## 逐句优先流程（workflow v2）

证据提交 `c32d53a09672d968c4173b5c6c4ea03c0961dd1e`（`dev` 上的 `experiments/sentence-first-agent/AGENTS.md`，该文件在钉住的提交里为 452 行）：12 个节点、3 条泳道、6 个阶段、12 条关系、5 张卡片。README 中英两版「工作流 / Workflows」章的逐句优先小节引用。

```json
{
  "schema_version": 2,
  "diagram_type": "workflow",
  "meta": {
    "title": "逐句优先、代理直做的配音：每周运行流程",
    "locale": "zh-CN",
    "output": ".archify/workflow-sentence-first-20261030-175502/sentence-first-weekly.html",
    "quality_profile": "showcase",
    "repository": {
      "url": "https://github.com/JonathanJing/sermon-video-zh-subtitles.git",
      "provider": "github",
      "link_mode": "web",
      "revision": "c32d53a09672d968c4173b5c6c4ea03c0961dd1e"
    }
  },
  "lanes": [
    {
      "id": "user",
      "label": "用户：人审与授权"
    },
    {
      "id": "local",
      "label": "本机：主代理与脚本"
    },
    {
      "id": "spark",
      "label": "DGX Spark：独占会话"
    }
  ],
  "phases": [
    {
      "id": "open",
      "label": "开工与冻结",
      "fromCol": 0,
      "toCol": 0
    },
    {
      "id": "source",
      "label": "拆句与英文表",
      "fromCol": 1,
      "toCol": 1
    },
    {
      "id": "text",
      "label": "英文人审与逐句翻译",
      "fromCol": 2,
      "toCol": 2
    },
    {
      "id": "audio",
      "label": "口播与配音",
      "fromCol": 3,
      "toCol": 3,
      "variant": "emphasis"
    },
    {
      "id": "finish",
      "label": "收尾、闸门与听审",
      "fromCol": 4,
      "toCol": 4
    },
    {
      "id": "ship",
      "label": "发布与学习内容",
      "fromCol": 5,
      "toCol": 5
    }
  ],
  "mainPath": [
    "m_pre",
    "u_freeze",
    "m_clip",
    "u_english",
    "m_translate",
    "m_speech",
    "k_tts",
    "m_finish",
    "u_review",
    "u_auth",
    "m_publish"
  ],
  "semanticChecks": {
    "allowedRoots": [
      "m_pre"
    ],
    "allowedTerminals": [
      "m_publish"
    ],
    "requiredEdges": [
      {
        "from": "u_english",
        "to": "m_translate"
      },
      {
        "from": "m_finish",
        "to": "u_review"
      },
      {
        "from": "u_auth",
        "to": "m_publish"
      }
    ]
  },
  "nodes": [
    {
      "id": "u_freeze",
      "lane": "user",
      "col": 0,
      "type": "external",
      "label": "冻结决策",
      "sublabel": "语言 · 同步 · 发布",
      "icon": "person",
      "width": 150,
      "sources": [
        {
          "path": "experiments/sentence-first-agent/AGENTS.md",
          "line": 89,
          "end_line": 107,
          "label": "questions + frozen table"
        }
      ]
    },
    {
      "id": "u_english",
      "lane": "user",
      "col": 2,
      "type": "external",
      "label": "英文表人审",
      "sublabel": "english-review.csv",
      "icon": "person",
      "width": 150,
      "sources": [
        {
          "path": "experiments/sentence-first-agent/AGENTS.md",
          "line": 111,
          "end_line": 111,
          "label": "approve English table"
        },
        {
          "path": "experiments/sentence-first-agent/AGENTS.md",
          "line": 150,
          "end_line": 158,
          "label": "review checklist"
        }
      ]
    },
    {
      "id": "u_review",
      "lane": "user",
      "col": 4,
      "type": "external",
      "label": "整轨听审",
      "sublabel": "审核收据 approved",
      "tag": "唯一音频结论",
      "icon": "person",
      "width": 150,
      "sources": [
        {
          "path": "experiments/sentence-first-agent/AGENTS.md",
          "line": 347,
          "end_line": 369,
          "label": "human review step"
        },
        {
          "path": "experiments/sentence-first-agent/AGENTS.md",
          "line": 13,
          "end_line": 13,
          "label": "receipt before go-live"
        }
      ]
    },
    {
      "id": "u_auth",
      "lane": "user",
      "col": 5,
      "type": "external",
      "label": "发布授权",
      "sublabel": "每次 deploy 授权",
      "icon": "person",
      "width": 150,
      "sources": [
        {
          "path": "experiments/sentence-first-agent/AGENTS.md",
          "line": 402,
          "end_line": 402,
          "label": "per-deploy authorization"
        },
        {
          "path": "experiments/sentence-first-agent/AGENTS.md",
          "line": 426,
          "end_line": 426,
          "label": "humanApproval"
        },
        {
          "path": "experiments/sentence-first-agent/AGENTS.md",
          "line": 199,
          "end_line": 199,
          "label": "human owns approval"
        }
      ]
    },
    {
      "id": "m_pre",
      "lane": "local",
      "col": 0,
      "type": "backend",
      "label": "预检与开工",
      "sublabel": "preflight.py",
      "width": 150,
      "sources": [
        {
          "path": "experiments/sentence-first-agent/AGENTS.md",
          "line": 81,
          "end_line": 87,
          "label": "environment preflight"
        },
        {
          "path": "experiments/sentence-first-agent/AGENTS.md",
          "line": 109,
          "end_line": 109,
          "label": "preflight command"
        },
        {
          "path": "experiments/sentence-first-agent/preflight.py",
          "label": "preflight script"
        }
      ]
    },
    {
      "id": "m_clip",
      "lane": "local",
      "col": 1,
      "type": "backend",
      "label": "裁音频 / 拆句",
      "sublabel": "prepare_clip.py",
      "width": 150,
      "sources": [
        {
          "path": "experiments/sentence-first-agent/AGENTS.md",
          "line": 224,
          "end_line": 236,
          "label": "clip + sentences"
        },
        {
          "path": "experiments/sentence-first-agent/prepare_clip.py",
          "label": "clip script"
        }
      ]
    },
    {
      "id": "m_translate",
      "lane": "local",
      "col": 2,
      "type": "backend",
      "label": "逐句翻译",
      "sublabel": "translate_parts.py",
      "width": 150,
      "sources": [
        {
          "path": "experiments/sentence-first-agent/AGENTS.md",
          "line": 248,
          "end_line": 268,
          "label": "per-sentence translation"
        },
        {
          "path": "experiments/sentence-first-agent/translate_parts.py",
          "label": "split / merge"
        }
      ]
    },
    {
      "id": "m_speech",
      "lane": "local",
      "col": 3,
      "type": "backend",
      "label": "口播规格",
      "sublabel": "build_speech.py",
      "tag": "spoken_forms",
      "width": 150,
      "sources": [
        {
          "path": "experiments/sentence-first-agent/AGENTS.md",
          "line": 288,
          "end_line": 296,
          "label": "speech spec + spoken forms"
        },
        {
          "path": "experiments/sentence-first-agent/build_speech.py",
          "label": "speech builder"
        }
      ]
    },
    {
      "id": "m_finish",
      "lane": "local",
      "col": 4,
      "type": "backend",
      "label": "收尾与落后闸门",
      "sublabel": "finish_run · lag_loop",
      "tag": "--require-clean",
      "width": 150,
      "sources": [
        {
          "path": "experiments/sentence-first-agent/AGENTS.md",
          "line": 323,
          "end_line": 345,
          "label": "finish + lag gate"
        },
        {
          "path": "experiments/sentence-first-agent/finish_run.py",
          "label": "merge + score"
        },
        {
          "path": "experiments/sentence-first-agent/lag_loop.py",
          "label": "lag gate"
        }
      ]
    },
    {
      "id": "m_publish",
      "lane": "local",
      "col": 5,
      "type": "backend",
      "label": "发布驱动",
      "sublabel": "assets → stage → publish",
      "width": 150,
      "sources": [
        {
          "path": "experiments/sentence-first-agent/AGENTS.md",
          "line": 382,
          "end_line": 392,
          "label": "ordered publish steps"
        },
        {
          "path": "experiments/sentence-first-agent/AGENTS.md",
          "line": 417,
          "end_line": 417,
          "label": "fixed public paths"
        },
        {
          "path": "experiments/sentence-first-agent/publish_podcast_page.py",
          "label": "page driver"
        }
      ]
    },
    {
      "id": "k_session",
      "lane": "spark",
      "col": 0,
      "type": "backend",
      "label": "独占会话",
      "sublabel": "status / begin",
      "width": 150,
      "sources": [
        {
          "path": "experiments/sentence-first-agent/AGENTS.md",
          "line": 219,
          "end_line": 223,
          "label": "exclusive session"
        },
        {
          "path": "packages/production/src/tongxing_production/compute/spark_exclusive_session.py",
          "label": "session tool"
        }
      ]
    },
    {
      "id": "k_tts",
      "lane": "spark",
      "col": 3,
      "type": "backend",
      "label": "逐句 TTS 容器",
      "sublabel": "spark_run.sh · batch 8",
      "tag": "GPU 串行",
      "width": 150,
      "sources": [
        {
          "path": "experiments/sentence-first-agent/AGENTS.md",
          "line": 298,
          "end_line": 321,
          "label": "queue + GPU memory"
        },
        {
          "path": "experiments/sentence-first-agent/spark_run.sh",
          "label": "TTS runner"
        },
        {
          "path": "experiments/sentence-first-agent/tts_sentences.py",
          "label": "per-batch TTS"
        }
      ]
    }
  ],
  "edges": [
    {
      "id": "e-ask",
      "from": "m_pre",
      "to": "u_freeze",
      "label": "问清",
      "role": "main"
    },
    {
      "id": "e-frozen",
      "from": "u_freeze",
      "to": "m_clip",
      "label": "开工",
      "role": "main",
      "fromSide": "right",
      "toSide": "top"
    },
    {
      "id": "e-english",
      "from": "m_clip",
      "to": "u_english",
      "label": "送审",
      "role": "main"
    },
    {
      "id": "e-approved",
      "from": "u_english",
      "to": "m_translate",
      "label": "批准",
      "role": "main",
      "variant": "emphasis"
    },
    {
      "id": "e-final",
      "from": "m_translate",
      "to": "m_speech",
      "label": "定稿",
      "role": "main"
    },
    {
      "id": "e-speech",
      "from": "m_speech",
      "to": "k_tts",
      "label": "上传",
      "role": "main"
    },
    {
      "id": "e-wav",
      "from": "k_tts",
      "to": "m_finish",
      "label": "拉回",
      "role": "main"
    },
    {
      "id": "e-ready",
      "from": "m_finish",
      "to": "u_review",
      "label": "可审",
      "role": "main",
      "variant": "emphasis"
    },
    {
      "id": "e-receipt",
      "from": "u_review",
      "to": "u_auth",
      "label": "approved",
      "role": "main"
    },
    {
      "id": "e-auth",
      "from": "u_auth",
      "to": "m_publish",
      "label": "授权",
      "role": "main",
      "variant": "emphasis"
    },
    {
      "id": "e-session",
      "from": "m_pre",
      "to": "k_session",
      "label": "begin",
      "role": "branch",
      "variant": "dashed"
    },
    {
      "id": "e-register",
      "from": "k_session",
      "to": "k_tts",
      "label": "登记容器",
      "role": "branch",
      "variant": "dashed"
    }
  ],
  "cards": [
    {
      "dot": "cyan",
      "title": "三个人类闸门",
      "items": [
        "英文表必须先人审：preflight --english-package 要在第 6 步 TTS 之前通过。",
        "整轨听审是唯一音频结论；审核收据 approved 先于 assets，发布过的收据不再改写。",
        "human_reviewed、humanApproval 和每次 deploy 授权都只来自用户，子代理审计不算人审。"
      ]
    },
    {
      "dot": "emerald",
      "title": "并行与串行",
      "items": [
        "Spark 独占会话一次只接纳一个任务；8 副本已占 96% GPU，第二条队列只会互相拖慢。",
        "一种语言配音时，上一种语言的 finish_run 与听审在本机并行。",
        "子代理只做翻译分片与独立保真审计，只写固定文件；单写者文件由主代理写。"
      ]
    },
    {
      "dot": "amber",
      "title": "发布与旁路",
      "items": [
        "顺序固定：assets → baseline → stage1 → publish → verify → stage2 → publish → readback。",
        "旁路三件套（english-reference、catalog.json、公告 sidecar）哈希一变就重生成，verify 要覆盖。",
        "固定路径 /pages|content|captions/<pageId>/<locale>；正式 App 会隐藏别的路径。"
      ]
    },
    {
      "dot": "violet",
      "title": "改句与学习内容",
      "items": [
        "第 9 步改句：改 translations.jsonl 或 review.json → 重跑第 5 步 → repair_sentence 重配窗口 → 再听审。",
        "第 10.5 步大纲默想：build_study → publish_study；humanApproval 只来自用户。",
        "第 11 步：finish 关闭会话、按标签删容器、导出运行报告；等待靠 waiting/resumed 记录。"
      ]
    },
    {
      "dot": "slate",
      "title": "诚实边界",
      "items": [
        "这条线不走正式流水线与哈希绑定校验；产物只写 ignored artifacts/sentence-first-agent/<run>/。",
        "2026-10-28 起回转写退出流程：spark_queue 只排 TTS，人工整轨听审是唯一音频结论。",
        "图不等于运行证据：页面、设备与现场验收各自记录。"
      ]
    }
  ]
}
```
