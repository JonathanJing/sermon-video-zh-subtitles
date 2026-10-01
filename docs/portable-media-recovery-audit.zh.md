# 私有媒体恢复审计

[English](portable-media-recovery-audit.md)

现有 [Layer 3 producer](../scripts/build_target_language_audio_package.py) 会把媒体引用
解析为本机绝对路径。直接修改路径会改变已批准 package 的 JSON SHA，导致独立人审收据
失效。这个新增工具使用独立 sidecar 验证私有归档，不改写原包、人审收据、producer 或
staging 接口。

## 合同与信任边界

- 输入必须是原版、已人审的 Audio Package、独立 v1/v2 音频人审收据、恢复 sidecar，以及
  操作者显式选择的本地归档根目录。无路径的精简快照不能替代原版 package。
- [sidecar v1 schema](../schemas/sermon-private-media-recovery-manifest-v1.schema.json)
  同时绑定原包与人审收据的文件字节 SHA-256、canonical JSON SHA-256，保留英文来源包、
  目标语言 candidate（不可变文字 revision）、speech job、locale、package ID 及
  downstream invalidation key 身份。
- 每次调用都必须从所选运行的可信证据指定预期 source／locale／candidate hash。
  不要从未经信任的新 sidecar 反推这些预期值。哈希证明输入之间的完整性关系，不是数字
  签名，也不证明审核者身份。
- 每个 unit 音频、track、captions、schedule 必须有且只有一条明确映射。artifact ID
  是原包中的位置，例如 `/units/0/audio`、`/track`、`/captions`、`/schedule`；文件必须
  匹配原包 SHA，原包带有 JSON SHA 时也必须相符。
- 归档路径采用 `languages/<targetLocale>/` 下的标准 POSIX 相对路径。使用特定 revision
  的归档根目录；`archiveId` 只是非敏感逻辑标签，不是路径，也不用于查找文件。
- 工具不会打开原包中的绝对媒体路径，不会将其写入 sidecar 或日志。不搜索同名文件、
  不按哈希猜位置、不读隐式环境根目录、不自动远端下载、不使用缺失文件的替代品。
- 拒绝路径穿越、绝对／Windows／URL 路径、非标准分隔符、符号链接（包括根目录祖先）、
  重复映射和多个映射指向同一硬链接文件。使用目录文件描述符和 `O_NOFOLLOW` 防止
  目录符号链接替换竞态；目前需要支持这些能力的 POSIX 系统，其他系统 fail closed。
  审计期间应保持归档静止；检测到的文件变动会失败，结果不是对后续文件状态的锁定。

真实 sidecar、mapping、package、收据、媒体和私有文件名继续放在忽略目录或授权私有
归档，不入 Git。仓库只保存实现、schema、文档和合成测试。

## 使用

先保持原包、收据字节不变，通过独立获授权流程准备媒体归档。工具不复制媒体。
私有 mapping JSON 的结构为 `{"artifacts": [...]}`，每行只含 `artifactId` 和
`archiveRelativePath`。必须列出所有单元与三个汇总产物；完整单元示例见英文说明。
以下变量需由操作者本地设置，工具不会自动发现它们：

```sh
python3 scripts/audit_portable_media.py prepare \
  --package "$ORIGINAL_PACKAGE" --approval "$ORIGINAL_APPROVAL" \
  --archive-root "$ARCHIVE_ROOT" --mapping "$PRIVATE_MAPPING" \
  --archive-id weekly-ko-r2 \
  --expected-source-sha256 "$EXPECTED_SOURCE_JSON_SHA256" \
  --expected-locale ko \
  --expected-candidate-sha256 "$EXPECTED_CANDIDATE_JSON_SHA256" \
  --out "$NEW_PRIVATE_SIDECAR"
```

`prepare` 先只读验证全部映射，再显式创建一个全新 sidecar。父目录须已存在，不覆盖任何
已有文件、符号链接、原包或收据。输出写入失败时可能留下不完整新文件；处理错误后使用
新的输出文件名。失败不会报告创建成功。

经独立授权流程转移媒体与证据后，在第二台机器显式选择归档根目录；继续使用原包、
收据和 sidecar 的原字节：

```sh
python3 scripts/audit_portable_media.py audit \
  --package "$ORIGINAL_PACKAGE" --approval "$ORIGINAL_APPROVAL" \
  --manifest "$PRIVATE_SIDECAR" --archive-root "$DESTINATION_ARCHIVE_ROOT" \
  --expected-source-sha256 "$EXPECTED_SOURCE_JSON_SHA256" \
  --expected-locale ko \
  --expected-candidate-sha256 "$EXPECTED_CANDIDATE_JSON_SHA256"
```

`audit` 不执行应用写入，只输出无路径 JSON 报告。退出码 0 表示绑定的 Layer 3 产物
字节验证通过；1 表示阻塞，缺失／损坏按 artifact ID 与稳定错误码列出；结构或身份
错误在媒体读取前停止。参数语法错误沿用 argparse 退出码 2。命令行参数仍按一般私有
终端信息保护。

## 范围与未完成事项

结果固定声明 `scope=layer3_package_artifacts_only` 和
`releaseEligibilityEstablished=false`。成功只证明相应文件的字节恢复，不证明解码、
听感、新人审、声音权利、所有上游 package、ASR 原始证据、完整视频、其他渲染收据或
整份生产归档恢复。v1 收据保持 v1，不会变为 v2 ASR 人工裁决。工具不调用模型、网络、
上传／下载、staging、发布或部署。

现有 staging 仍读取原绝对路径并执行完整门禁，因此审计成功不能宣称旧 staging 已可
跨机器使用。后续须为 staging 设计显式版本化的映射读取入口，不改写获批 package，
并保留现有全部门禁。更广的恢复 backlog 仍未关闭。

运行 `python3 -m unittest tests.test_audit_portable_media -v` 验证合成场景：删除源媒体树
后的双目录迁移、原字节保留、真实 package／review producer、缺失／损坏／空文件、
穿越与符号链接／特殊文件、错 source／locale／revision、原包与收据仅格式变动、
identity／JSON SHA 漂移、重复／硬链接别名、同名文件不猜选及 CLI 日志脱敏。
合成人审字段只用于测试，不代表真实内容已批准。
