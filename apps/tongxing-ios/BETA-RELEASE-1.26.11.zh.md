# Beta 1.26.11 (52) 分发记录

2026-10-04，用户授权将全文定位与跟随播放候选上传 Beta，并配置 fastlane + App Store Connect API Key。API Key 已由账户持有人创建；本机只保存仓库外的私钥路径与标识，文件权限 `600`，未将凭据提交 Git。实际 API 认证、Beta 构建清单与 Rooted 组查询通过。

## 冻结源码与归档

| 项目 | 实际结果 |
|---|---|
| 候选源码 | `codex/ios-testflight-api-automation` / `67c3dd34648072a53809960addd012a9eeee1dd5` |
| iOS module tree | `fb2a31ec39564f85abc98cc07a26400c1ff8574f` |
| Scheme / configuration | `TongxingBeta` / `BetaRelease` |
| 版本 / Build | `1.26.11 (52)`，App 与 Activity extension 一致 |
| App 身份 / 内容源 | `com.jonathanjing.tongxing.beta` / Firebase Dev |
| Xcode / SDK | Xcode 27.1 (`27A9269`) / iOS 27.1 (`24A94403`) |
| Archive manifest SHA-256 | `79ed40bb1e08265819b905c199bda7c8866d3b694250af4f0595c7d3f2b6fd8b` |
| IPA SHA-256 | `149a1a7cb7627c700f9247d7d88b1cf2e94f098b403afe444f2f8de01d081af9` |
| 归档与签名 | 成功，严格 `codesign --verify --deep --strict` 通过 |

版本分配前，实际 Apple 查询最新 Beta 为 `1.26.10 (51)`；拉取全部现存远端分支并检查已分配 project.yml，最大迭代号为 10、最大 Build 为 51。仅调整 Beta app 与 extension 的四个配置，正式渠道仍为 `1.26.10 (51)`。冻结后未重建或修改上传 IPA。

第一次归档缺少本机 Development Team，保留失败日志；从历史私有配置与本机开发证书核对一致 Team 后补入忽略的 `Config/Local.xcconfig`，同 commit / 版本成功重试。API Key 的 App Manager 权限通过 TestFlight 查询与分发，但导出时 Apple 拒绝其云托管分发证书权限；已有 Xcode 账户成功导出同一 Archive。上传与 TestFlight 操作仍使用 API Key，不将该结果称为 API Key 已具备云签名权限。

## TestFlight 实际读回

- fastlane 2.240.1 于 2026-10-04 22:03:18（America/Los_Angeles）确认二进制上传成功。
- Apple build ID：`7d446780-16cc-4b61-a243-e7a9ac7ac3df`。
- `2026-10-05T05:18:46Z` 读回 `processingState=VALID`、`internalBuildState=IN_BETA_TESTING`、未过期；Rooted 内部组的 build ID 清单包含该构建。
- What to Test 已保存并通过 API 读回一致，说明全文自动跟随、自由阅读、当前句／底部时间返回和暂停状态不变，并保留 Duo 时间显示人工检查项。notes SHA-256：`7b7191cd78bae2d57623544bffc44b7ed4fcffc65fbb8d621d2e9dde4818afbe`。
- 未新建测试者或组，未提交外部 Beta Review，未晋升或发布正式 App。`device=not_run`、`venue=not_run`。

首次上传在 Transporter 初始化前因 Command Line Tools 路径导致 `Helper.xcode_version=nil` 失败；没有创建上传执行器。独立 Apple 清单未见该候选，保留对账记录后用明确 `DEVELOPER_DIR`、同一 IPA 显式重试。随后为 CLI 添加完整 Xcode 的默认选择与 `--developer-dir`，无需修改全局 `xcode-select`；此修复不改写已冻结 Archive 或 IPA。

## 已执行验证与验收边界

- 9 项新的离线配置／上传守卫测试与 16 项归档准入测试通过；Python／Ruby 语法、CLI help / dry-run、fastlane lanes 加载与 diff 检查通过。新增完整 Xcode 选择经独立只读审核。
- 全文功能复用本轮实际 [返回当前句验证](../../docs/reports/20261004-ios-transcript-return-current.zh.md)、[自动跟随与时间入口验证](../../docs/reports/20261004-ios-transcript-follow-playback.zh.md)、[iPhone Duo / iPhone 17 Pro 正常字体截图](../../docs/reports/20261004-ios-transcript-normal-devices.zh.md)。本次只有分发配置与工具变更，未重跑界面测试。
- 测试组可用不证明真机已安装。真机请核对长全文、大字体、手动阅读后恢复跟随、播放／暂停保持及 Duo 时间是否完整；声音与现场同步仍需实际验收。

私有归档、导出、失败尝试与分发 receipt 位于 `artifacts/tongxing-ios/beta-1.26.11-build52-retry1/`；首次归档失败保留在 `beta-1.26.11-build52/`。API / 上传 / 分发运行证据位于 `artifacts/tongxing-ios/testflight/`，准确指针在私有 `distribution-record.json`。原归档记录保持不变，以分发 receipt 追加实际状态。
