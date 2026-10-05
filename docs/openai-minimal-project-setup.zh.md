# 单人维护：两个 OpenAI Project、两把运行 key

创建 `tongxing-dev` 和 `tongxing-prod` 两个 OpenAI Project，各创建一把项目范围的运行 key，建议命名 `tongxing-dev-runtime`、`tongxing-prod-runtime`。转写（仅使用 OpenAI 时）、翻译、模型审核共用所在环境的 key；角色和阶段靠逐调用日志区分。Codex 的 ChatGPT 登录不需要这两把 key。

## 本地配置

本地可以用 env 文件。使用独立的 `.env.openai`，保留既有 `.env`，避免手动替换旧 key。以下准备命令不会覆盖已有文件：

```sh
python3 -c 'from pathlib import Path; p=Path(".env.openai"); f=p.open("x"); f.write(Path("config/openai-runtime.env.example").read_text()); f.close(); p.chmod(0o600)'
```

在本地编辑 `.env.openai` 填入四个字段（不要把 key 发到聊天）：

| 字段 | 填写内容 |
|---|---|
| `OPENAI_DEV_PROJECT_ID` | dev 的真实 OpenAI Project ID，`proj_…` |
| `OPENAI_DEV_API_KEY` | dev 项目范围 key |
| `OPENAI_PROD_PROJECT_ID` | prod 的真实 OpenAI Project ID，`proj_…` |
| `OPENAI_PROD_API_KEY` | prod 项目范围 key |

该文件已由 `.env.*` 规则忽略。只接受字面赋值，不执行 shell、不做变量展开；文件权限必须为 600。启动器仅把选中环境的 key 注入子进程 `OPENAI_API_KEY`，Project ID 注入 `OPENAI_PROJECT_ID`，并移除另一环境的 key 和继承的旧 key／secret 引用。SDK 可消费 Project ID；共享 JSON／转写 HTTP、canonical Layer 2 budget transport 和 Agents API 在显式环境下发送 `OpenAI-Project`，并拒绝不同 key 覆盖选定凭据。英文 source judge 在显式环境下拒绝旧 `--api-key-secret` 覆盖。填写的 ID 是配置证据，不能代替 provider 侧身份验证。

```sh
# 只检查本地配置，不请求 OpenAI、不计费。
python3 scripts/run_with_openai_environment.py --environment dev --check
python3 scripts/run_with_openai_environment.py --environment prod --check

# 用显式环境启动现有命令；后面的 producer 参数仍须按原合同提供。
python3 scripts/run_with_openai_environment.py --environment dev -- \
  python3 scripts/run_target_language_models.py --help
```

实际生成时将 `--help` 替换为生产命令及其参数。必须从启动器进入；直接运行旧 producer 仍遵循原环境／`.env`／Secret Manager 行为，不会自动切换到两项目配置。现有 `sermon_pipeline.load_env` 使用 setdefault，不覆盖启动器已选择的 key。

长期 supervisor／controller 应在启动整个进程时选定环境，切换环境要重启。已有持久任务不自动迁移到新凭据；需检查其实际 worker 启动方式，不能仅改变父 shell 就宣称续跑已切换。当前启动器只保证直接子进程及正常继承环境的后代，不改 Cloud Run 或持久 job 的凭据配置。

## 费用合同与云端

使用 `sermon-cost-isolation-v2`，每个环境的 transcription／translation／reviewer 指向同一个 `tongxing-dev-runtime` 或 `tongxing-prod-runtime` 别名；两个环境必须使用不同 Project 和凭据。v1 保留旧的严格用途拆分规则，旧证据无需重写。Project ID 和安全别名可以入账，key 原值不入账。

离线对账配置模板为 [openai-cost-isolation-minimal.example.json](../config/openai-cost-isolation-minimal.example.json)，将两个 `REPLACE_…` 替换为真实 Project ID 后使用；这个 JSON 不存 key，也不会自动发起模型请求。显式环境下的 direct API／SDK 账本事件自动增加 `openaiRoute`，逐调用报告及 CSV 保留该字段：environment、projectId、credentialAlias 和 `identitySource=configured_runtime`。该归因来自调用配置，不冒充 provider 账单或 API key ID；Codex 的订阅登录、其他 provider 和旧调用无此配置时保持未知。

日志兼容迁移：`openaiRoute` 使用独立 `sermon-openai-runtime-route-v1` envelope，作为现有日志合同的可选扩展；旧事件无需改写，旧事件没有此字段时报告 null。使用旧版严格 schema 的外部消费者需更新 schema 才能读取新事件，不要为历史调用补造归因。

Dev 和 Beta 测试可共用 dev 项目；正式内容生成使用 prod，环境取决于调用用途而非页面发布目标。云端继续使用 Secret Manager，分别保存 dev／prod secret，并让服务绑定对应 secret；本地文件不是自动同步来源。本次不改云端凭据。

创建后先检查本地配置，再单独核验真实 Project／模型权限和预算。`--check` 不证明 key 有效、Project 归属、费用限额生效或真实账单。Dev 建议低 hard limit；Prod 设置预警及留有余量的上限。具体金额由操作者确定。
