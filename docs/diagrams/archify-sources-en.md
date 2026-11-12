# Archify 英文版源（English specs）

两张图的英文交互版发布在 Dev 预览站：

- <https://tongxing-diagrams-dev.web.app/en/tongxing-system-architecture>
- <https://tongxing-diagrams-dev.web.app/en/sentence-first-weekly-workflow>

英文版由[中文 spec](archify-sources.md) 逐条翻译展示文案得到：节点／组件／泳道／阶段／连线 id、`sources`（仓库路径与行号）、`meta.repository.revision` 全部不变，只改 `meta.title`、`meta.locale`（`zh-CN` → `en`）以及用户可见的标签、副标签、卡片与边界文字。因此证据绑定与中文版一致，图稿同样不证明上线、人工审核、设备或现场验收。

再生成：

```bash
node <archify-skill>/bin/archify.mjs finalize architecture \
  artifacts/diagrams/en/tongxing-system-architecture.json \
  artifacts/diagrams/en/tongxing-system-architecture.html \
  --repo-root . --quality showcase --json

node <archify-skill>/bin/archify.mjs finalize workflow \
  artifacts/diagrams/en/sentence-first-weekly-workflow.json \
  artifacts/diagrams/en/sentence-first-weekly-workflow.html \
  --repo-root . --quality showcase --json
```

与中文版的一处布局差异：英文标签更长，工作流节点宽度按标签实测宽度逐列收窄（列宽 147/103/140/113/140/147），使隐式画布保持在 1240px 以内，满足 showcase 的副标签可读性下限；标签本身额外缩短过（例如 `English table human review` → `English table review`，补充事实放在卡片里）。

## Tongxing: four-layer multilingual production and publishing architecture

```json
{
  "schema_version": 1,
  "diagram_type": "architecture",
  "meta": {
    "title": "Tongxing: four-layer multilingual production and publishing architecture",
    "locale": "en",
    "output": "artifacts/diagrams/en/tongxing-system-architecture.html",
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
      "label": "Authorized media",
      "sublabel": "YouTube / Resi archive",
      "pos": [
        10,
        300
      ],
      "size": [
        132,
        64
      ],
      "sources": [
        {
          "path": "docs/workflows/README.zh.md",
          "line": 3,
          "end_line": 3,
          "label": "media source"
        },
        {
          "path": "packages/production/src/tongxing_production/workflows/dual_pdf/local_post_live_download.py",
          "line": 1,
          "end_line": 8,
          "label": "download + hash"
        }
      ]
    },
    {
      "id": "l1",
      "type": "backend",
      "label": "Layer 1 source",
      "sublabel": "English Source Package",
      "tag": "source_review",
      "pos": [
        204,
        300
      ],
      "size": [
        132,
        64
      ],
      "sources": [
        {
          "path": "packages/production/src/tongxing_production/source/unified_stage.py",
          "line": 1,
          "end_line": 6,
          "label": "ASR + MFA + anchors"
        },
        {
          "path": "packages/production/src/tongxing_production/source/english_source_package.py",
          "line": 1,
          "end_line": 5,
          "label": "source package"
        }
      ]
    },
    {
      "id": "l2",
      "type": "backend",
      "label": "Layer 2 candidates",
      "sublabel": "zh-Hans / ko / es",
      "tag": "Machine review",
      "pos": [
        398,
        300
      ],
      "size": [
        132,
        64
      ],
      "sources": [
        {
          "path": "packages/production/src/tongxing_production/text/candidate.py",
          "line": 1,
          "end_line": 5,
          "label": "candidate compile"
        },
        {
          "path": "packages/production/src/tongxing_production/text/policy.py",
          "line": 1,
          "end_line": 2,
          "label": "frozen locale policy"
        },
        {
          "path": "config/target-language-policies/zh-Hans.json",
          "label": "policy file"
        }
      ]
    },
    {
      "id": "l3",
      "type": "backend",
      "label": "Layer 3 audio",
      "sublabel": "Audio Package",
      "tag": "1× listening",
      "pos": [
        592,
        300
      ],
      "size": [
        132,
        64
      ],
      "sources": [
        {
          "path": "packages/production/src/tongxing_production/audio/renderer.py",
          "line": 1,
          "end_line": 5,
          "label": "resume speech job"
        },
        {
          "path": "packages/production/src/tongxing_production/audio/package.py",
          "line": 1,
          "end_line": 4,
          "label": "fail-closed package"
        },
        {
          "path": "config/speaker-voice-registry.json",
          "line": 1,
          "end_line": 8,
          "label": "Qwen TTS base"
        }
      ]
    },
    {
      "id": "l4",
      "type": "backend",
      "label": "Layer 4 package",
      "sublabel": "Release Package",
      "tag": "Seven resources",
      "pos": [
        786,
        300
      ],
      "size": [
        132,
        64
      ],
      "sources": [
        {
          "path": "packages/production/src/tongxing_production/delivery/app_release.py",
          "line": 1,
          "end_line": 6,
          "label": "prepare / verify / seal"
        },
        {
          "path": "docs/layer4-four-product-public-delivery.zh.md",
          "line": 9,
          "end_line": 20,
          "label": "seven public resources"
        }
      ]
    },
    {
      "id": "publish",
      "type": "backend",
      "label": "Guarded publisher",
      "sublabel": "guarded_hosting_publish",
      "tag": "Baseline CAS",
      "pos": [
        980,
        300
      ],
      "size": [
        132,
        64
      ],
      "sources": [
        {
          "path": "tools/ops/guarded_hosting_publish.py",
          "line": 1,
          "end_line": 6,
          "label": "L4 publisher entry"
        },
        {
          "path": "packages/production/src/tongxing_production/delivery/publication.py",
          "line": 1,
          "end_line": 6,
          "label": "lease + live baseline"
        },
        {
          "path": "packages/production/src/tongxing_production/storage/hosting.py",
          "line": 1,
          "end_line": 7,
          "label": "Hosting + GCS adapter"
        }
      ]
    },
    {
      "id": "hosting",
      "type": "cloud",
      "label": "Firebase hosting",
      "sublabel": "Hosting · Dev/Prod",
      "pos": [
        1210,
        300
      ],
      "size": [
        132,
        64
      ],
      "sources": [
        {
          "path": "firebase/production-overlay/firebase.json",
          "label": "site config"
        },
        {
          "path": "docs/layer4-four-product-public-delivery.zh.md",
          "line": 9,
          "end_line": 20,
          "label": "public URL layout"
        }
      ]
    },
    {
      "id": "web",
      "type": "frontend",
      "label": "Web reader",
      "sublabel": "listening-web",
      "pos": [
        980,
        600
      ],
      "size": [
        132,
        64
      ],
      "sources": [
        {
          "path": "apps/listening-web/app.mjs",
          "label": "reader module"
        },
        {
          "path": "docs/layer4-four-product-public-delivery.zh.md",
          "line": 54,
          "end_line": 54,
          "label": "v4 then v3 readback"
        }
      ]
    },
    {
      "id": "ios",
      "type": "frontend",
      "label": "iOS App",
      "sublabel": "SwiftUI + AVPlayer",
      "pos": [
        1210,
        600
      ],
      "size": [
        132,
        64
      ],
      "sources": [
        {
          "path": "apps/tongxing-ios/README.zh.md",
          "label": "iOS client"
        },
        {
          "path": "README.zh.md",
          "line": 92,
          "end_line": 92,
          "label": "consumes Layer 4 only"
        }
      ]
    },
    {
      "id": "listeners",
      "type": "external",
      "label": "Listeners",
      "sublabel": "Web / phone",
      "icon": "person",
      "pos": [
        1050,
        720
      ],
      "size": [
        132,
        64
      ],
      "sources": [
        {
          "path": "README.zh.md",
          "line": 92,
          "end_line": 92,
          "label": "primary listening client"
        }
      ]
    },
    {
      "id": "artifacts",
      "type": "database",
      "label": "Local artifact store",
      "sublabel": "artifacts/ and receipts",
      "pos": [
        786,
        470
      ],
      "size": [
        132,
        64
      ],
      "sources": [
        {
          "path": "packages/production/src/tongxing_production/orchestration/jobs.py",
          "line": 1,
          "end_line": 8,
          "label": "durable local jobs"
        },
        {
          "path": "docs/layer4-four-product-public-delivery.zh.md",
          "line": 68,
          "end_line": 68,
          "label": "snapshot + HTTP manifest"
        }
      ]
    },
    {
      "id": "providers",
      "type": "external",
      "label": "Model API",
      "sublabel": "DeepSeek · OpenAI",
      "tag": "Paid calls",
      "pos": [
        398,
        110
      ],
      "size": [
        132,
        64
      ],
      "sources": [
        {
          "path": "packages/production/src/tongxing_production/compute/transports/deepseek_layer2.py",
          "line": 1,
          "end_line": 5,
          "label": "Layer 2 transport"
        },
        {
          "path": "packages/production/src/tongxing_production/compute/transports/openai_layer2.py",
          "label": "OpenAI transport"
        },
        {
          "path": "packages/production/src/tongxing_production/compute/transports/claude_layer2.py",
          "label": "Claude transport"
        }
      ]
    },
    {
      "id": "spark",
      "type": "backend",
      "label": "DGX Spark",
      "sublabel": "CUDA · Qwen TTS",
      "tag": "Compute host",
      "pos": [
        592,
        110
      ],
      "size": [
        132,
        64
      ],
      "sources": [
        {
          "path": "docs/local-production-compute-policy.zh.md",
          "line": 1,
          "end_line": 3,
          "label": "Spark default, MacBook fallback"
        },
        {
          "path": "config/speaker-voice-registry.json",
          "line": 1,
          "end_line": 8,
          "label": "Qwen base model"
        },
        {
          "path": "packages/production/src/tongxing_production/audio/renderer.py",
          "line": 3,
          "end_line": 5,
          "label": "render cache identity"
        }
      ]
    },
    {
      "id": "receipts",
      "type": "security",
      "label": "Review receipts",
      "sublabel": "Human review / machine waiver",
      "pos": [
        398,
        470
      ],
      "size": [
        132,
        64
      ],
      "sources": [
        {
          "path": "packages/production/src/tongxing_production/text/human_review.py",
          "line": 1,
          "end_line": 5,
          "label": "text worksheet + admit"
        },
        {
          "path": "packages/production/src/tongxing_production/audio/human_review.py",
          "line": 1,
          "end_line": 4,
          "label": "listening is the only gate"
        },
        {
          "path": "packages/production/src/tongxing_production/review/waiver.py",
          "line": 1,
          "end_line": 6,
          "label": "machine quality waiver"
        }
      ]
    }
  ],
  "boundaries": [
    {
      "kind": "region",
      "label": "Local MacBook production environment",
      "wraps": [
        "l1",
        "l2",
        "l3",
        "l4",
        "artifacts",
        "publish",
        "receipts"
      ],
      "pad": 20
    }
  ],
  "connections": [
    {
      "id": "e-media",
      "from": "source",
      "to": "l1",
      "label": "Download"
    },
    {
      "id": "e-source-package",
      "from": "l1",
      "to": "l2",
      "label": "Source pack",
      "variant": "emphasis"
    },
    {
      "id": "e-candidate",
      "from": "l2",
      "to": "l3",
      "label": "Candidates"
    },
    {
      "id": "e-audio",
      "from": "l3",
      "to": "l4",
      "label": "Audio package"
    },
    {
      "id": "e-seal",
      "from": "l4",
      "to": "artifacts",
      "label": "Seal",
      "fromSide": "bottom",
      "toSide": "top"
    },
    {
      "id": "e-snapshot",
      "from": "artifacts",
      "to": "publish",
      "label": "Snapshot",
      "fromSide": "right",
      "toSide": "bottom",
      "via": [
        [
          1046,
          502
        ]
      ]
    },
    {
      "id": "e-deploy",
      "from": "publish",
      "to": "hosting",
      "label": "Deploy",
      "variant": "emphasis"
    },
    {
      "id": "e-catalog-web",
      "from": "hosting",
      "to": "web",
      "label": "Catalog",
      "fromSide": "bottom",
      "toSide": "top"
    },
    {
      "id": "e-catalog-ios",
      "from": "hosting",
      "to": "ios",
      "label": "Catalog",
      "fromSide": "bottom",
      "toSide": "top"
    },
    {
      "id": "e-web-listeners",
      "from": "web",
      "to": "listeners",
      "fromSide": "bottom",
      "toSide": "top"
    },
    {
      "id": "e-ios-listeners",
      "from": "ios",
      "to": "listeners",
      "fromSide": "bottom",
      "toSide": "top"
    },
    {
      "id": "e-model-calls",
      "from": "providers",
      "to": "l2",
      "label": "Translate / review",
      "fromSide": "bottom",
      "toSide": "top"
    },
    {
      "id": "e-render",
      "from": "spark",
      "to": "l3",
      "label": "TTS render",
      "fromSide": "bottom",
      "toSide": "top"
    },
    {
      "id": "e-text-receipt",
      "from": "l2",
      "to": "receipts",
      "label": "Human review",
      "variant": "dashed",
      "fromSide": "bottom",
      "toSide": "top"
    },
    {
      "id": "e-audio-receipt",
      "from": "l3",
      "to": "receipts",
      "label": "Listening review",
      "variant": "dashed",
      "fromSide": "bottom",
      "toSide": "right",
      "via": [
        [
          658,
          502
        ],
        [
          568,
          502
        ]
      ]
    }
  ],
  "cards": [
    {
      "dot": "cyan",
      "title": "Four layers and gates",
      "items": [
        "A Layer 1 identity change invalidates every locale; a Layer 2/3 artifact change invalidates only that locale's downstream work.",
        "human_gates is defined in contracts/pipeline_definition.py: source_review, translation_review + voice_authorization, audio_listening_review, exact_release_authorization.",
        "The module returns dispatchEnabled=false: there is no end-to-end dispatcher, and operators run each layer with tools/ops/run.py <area.module>.",
        "Models and compute: source verdicts, translation and review go through the model API; MFA word-level alignment and Layer 3 TTS run on DGX Spark, with the MacBook as a restricted failure fallback."
      ]
    },
    {
      "dot": "emerald",
      "title": "Artifacts and recovery",
      "items": [
        "artifacts/ holds release packages, snapshots and receipts; a durable job identity is used once, and an unknown result is reconciled instead of being retried.",
        "config/ freezes models and policy; schemas/ versions every package and receipt.",
        "Every package binds source, media, model, prompt and review receipts by hash; stale evidence invalidates only its descendants."
      ]
    },
    {
      "dot": "amber",
      "title": "Publishing and evidence boundaries",
      "items": [
        "The publisher takes the live baseline first and checks it file by file; after deploy it reads back the v5/v4/v3 catalog, repeating reads inside the propagation window.",
        "HTTP, browser smoke, device and venue acceptance are recorded separately; a screenshot is not venue acceptance.",
        "A machine quality waiver is written into the disclosure; the page is labelled machine-checked and is never shown as human approval."
      ]
    },
    {
      "dot": "violet",
      "title": "Paths outside the main line",
      "items": [
        "Sunday live captions live_session: experiments/local-live-poc, local microphone → ASR → Chinese captions, keeping a separate recording.",
        "Dual-PDF reading edition: workflows/dual_pdf, written under output/pdf/, not part of release-package identity.",
        "Feedback and push: Cloud Functions (services/feedback, services/push) + Firestore; clients only use the same-origin /api/*."
      ]
    }
  ]
}
```

## Sentence-first, agent-direct dubbing: the weekly run

```json
{
  "schema_version": 2,
  "diagram_type": "workflow",
  "meta": {
    "title": "Sentence-first, agent-direct dubbing: the weekly run",
    "locale": "en",
    "output": "artifacts/diagrams/en/sentence-first-weekly-workflow.html",
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
      "label": "User: human review and authorization"
    },
    {
      "id": "local",
      "label": "Local machine: lead agent and scripts"
    },
    {
      "id": "spark",
      "label": "DGX Spark: exclusive session"
    }
  ],
  "phases": [
    {
      "id": "open",
      "label": "Kickoff and freeze",
      "fromCol": 0,
      "toCol": 0
    },
    {
      "id": "source",
      "label": "Clip and English table",
      "fromCol": 1,
      "toCol": 1
    },
    {
      "id": "text",
      "label": "English review and sentence translation",
      "fromCol": 2,
      "toCol": 2
    },
    {
      "id": "audio",
      "label": "Speech spec and dubbing",
      "fromCol": 3,
      "toCol": 3,
      "variant": "emphasis"
    },
    {
      "id": "finish",
      "label": "Finish, gates and listening",
      "fromCol": 4,
      "toCol": 4
    },
    {
      "id": "ship",
      "label": "Publish and study content",
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
      "label": "Freeze decisions",
      "sublabel": "language · sync · release",
      "icon": "person",
      "width": 147,
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
      "label": "English table review",
      "sublabel": "english-review.csv",
      "icon": "person",
      "width": 140,
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
      "label": "Full-track listening",
      "sublabel": "review receipt approved",
      "tag": "sole audio verdict",
      "icon": "person",
      "width": 140,
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
      "label": "Publish authorization",
      "sublabel": "authorized per deploy",
      "icon": "person",
      "width": 147,
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
      "label": "Preflight and kickoff",
      "sublabel": "preflight.py",
      "width": 147,
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
      "label": "Clip and split",
      "sublabel": "prepare_clip.py",
      "width": 103,
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
      "label": "Sentence translation",
      "sublabel": "translate_parts.py",
      "width": 140,
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
      "label": "Speech spec",
      "sublabel": "build_speech.py",
      "tag": "spoken_forms",
      "width": 113,
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
      "label": "Finish and lag gates",
      "sublabel": "finish_run · lag_loop",
      "tag": "--require-clean",
      "width": 140,
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
      "label": "Publish driver",
      "sublabel": "assets → stage → publish",
      "width": 147,
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
      "label": "Exclusive session",
      "sublabel": "status / begin",
      "width": 147,
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
      "label": "Per-sentence TTS",
      "sublabel": "spark_run.sh · batch 8",
      "tag": "GPU serial",
      "width": 113,
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
      "label": "clarify",
      "role": "main"
    },
    {
      "id": "e-frozen",
      "from": "u_freeze",
      "to": "m_clip",
      "label": "kickoff",
      "role": "main"
    },
    {
      "id": "e-english",
      "from": "m_clip",
      "to": "u_english",
      "label": "submit",
      "role": "main"
    },
    {
      "id": "e-approved",
      "from": "u_english",
      "to": "m_translate",
      "label": "approve",
      "role": "main",
      "variant": "emphasis"
    },
    {
      "id": "e-final",
      "from": "m_translate",
      "to": "m_speech",
      "label": "finalize",
      "role": "main"
    },
    {
      "id": "e-speech",
      "from": "m_speech",
      "to": "k_tts",
      "label": "upload",
      "role": "main"
    },
    {
      "id": "e-wav",
      "from": "k_tts",
      "to": "m_finish",
      "label": "pull back",
      "role": "main"
    },
    {
      "id": "e-ready",
      "from": "m_finish",
      "to": "u_review",
      "label": "reviewable",
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
      "label": "authorize",
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
      "label": "register container",
      "role": "branch",
      "variant": "dashed"
    }
  ],
  "cards": [
    {
      "dot": "cyan",
      "title": "Three human gates",
      "items": [
        "The English table takes human review first: preflight --english-package must pass before TTS in step 6.",
        "Full-track listening is the sole audio verdict; the approved review receipt precedes assets, and a published receipt is never rewritten.",
        "human_reviewed, humanApproval and each deploy authorization come only from the user; a subagent audit is not human review."
      ]
    },
    {
      "dot": "emerald",
      "title": "Parallel and serial",
      "items": [
        "An exclusive Spark session admits one task at a time; 8 replicas already hold 96% of the GPU, so a second queue only slows both down.",
        "While one language is being dubbed, the previous language's finish_run and listening review run in parallel on the local machine.",
        "Subagents only take translation shards and independent fidelity audits and write fixed files; single-writer files are written by the lead agent."
      ]
    },
    {
      "dot": "amber",
      "title": "Publishing and sidecars",
      "items": [
        "The order is fixed: assets → baseline → stage1 → publish → verify → stage2 → publish → readback.",
        "The three sidecars (english-reference, catalog.json, announcement sidecar) are regenerated whenever their hash changes, and verify must cover them.",
        "Fixed paths /pages|content|captions/<pageId>/<locale>; the release App hides the other paths."
      ]
    },
    {
      "dot": "violet",
      "title": "Sentence edits and study content",
      "items": [
        "Step 9 sentence edits: change translations.jsonl or review.json → rerun step 5 → repair_sentence re-fits the window → listen again.",
        "Step 10.5 outline meditation: build_study → publish_study; humanApproval comes only from the user.",
        "Step 11: finish closes the session, deletes containers by label and exports the run report; waiting is recorded as waiting/resumed."
      ]
    },
    {
      "dot": "slate",
      "title": "Honest boundaries",
      "items": [
        "This route skips the formal pipeline and its hash-bound checks; outputs are written only to the ignored artifacts/sentence-first-agent/<run>/.",
        "Since 2026-10-28 the re-voice flow retires into this route: spark_queue only queues TTS, and human full-track listening is the sole audio verdict.",
        "The diagram is not run evidence: page, device and venue acceptance are recorded separately."
      ]
    }
  ]
}
```

