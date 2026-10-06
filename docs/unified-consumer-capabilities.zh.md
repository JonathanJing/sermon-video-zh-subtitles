# Unified 消费端能力预检

`scripts/sermon_unified_capabilities.py` 在未来 Layer 1/2/3/4 产物尚未生成时，只检查可事前验证的真实输入。`inspect(path)` 不写文件、不访问网络、不调用模型；`freeze(path, output)` 仅以排他创建方式写入新配置，要求同目录以保留相对路径含义。

```sh
.venv/bin/python -m scripts.sermon_unified_capabilities capabilities.json --freeze-out capabilities.frozen.json
.venv/bin/python -m scripts.sermon_unified_capabilities capabilities.frozen.json
```

配置字段（不接受其他字段）：

- `schemaVersion`: `sermon-unified-consumer-capabilities-v1`。
- `source`、`bindings`：与 unified manifest 一致的原始 source identity / window，及 `windowApproval`、`timelineReport`、`sourceDescriptor` 文件绑定。重用原人工窗口 receipt，检查 URL、媒体 hash、时长、窗口和原始 timeline。
- `locales`: 非空 locale 映射；每项必须有 `policy`、`adapter`、`registry`、`voiceAttestation` 文件路径。严格 v3 policy 另加 `rubric`。调用现有完整 policy validator 并要求 productionPolicyReady。
- `terminology`: 完整术语表路径，由 policy validator 检查其 hash 和术语覆盖。
- `voiceAttestation`: 已存在的 `sermon-source-user-voice-attestation-v2`，绑定该 source/media/window/duration/locale/speaker/checkpoint 与 formal audio 授权。adapter/registry 用现有 validator 校验身份和授权证据，另要求 verified adapter 和 human_reviewed locale evidence。没有真实授权必须失败，不能生成或替代人工授权。
- `releaseIntents`: 恰好 `dev` 和 `production` 两项真实 release intent；`routes` 同时包含两环境，各项经现有 route validator 校验，且 site 必须不同。
- `targetSchemaVersions`: 精确采用模块的 `SCHEMAS` 映射，绑定仓库内实际 schema 文件 hash。

预检通过 ffmpeg stdin/stdout 管道，把固定一秒 16 kHz、单声道 s16le PCM 编码为 WAV 后解码，逐字节比较结果，并绑定 ffmpeg executable hash。该检查证明本机 PCM 编解码能力，不证明远程 TTS 健康、其他编码格式或真实产物播放成功。

冻结配置新增 `inputSnapshotSha256`，绑定配置内容、全部输入文件路径与 bytes hash、目标 schema、编解码二进制；检查结束再次读取所有 hash，变更即失败。结果包含 `snapshotBound`、`inputHashes`、`configSha256`、`sourceIdentity` 和逐语言结果。消费者必须要求 `snapshotBound=true` 并将该配置绑定到当前 run。

本预检明确返回 `futureArtifactsValidated=false`、`modelCalls=0`。它不伪造尚未存在的 English source package、candidate、candidate-bound voice authorization、audio package 或 release package，不能替代其后独立内容审核、正式声音授权、产物验证及终端验收。policy 中未来 source package scope 仍须在真实产物存在后重新匹配；本步骤只验证冻结 policy 本身。
