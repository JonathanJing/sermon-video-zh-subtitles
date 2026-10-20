# 复盘：20261018-zh-poster-announcement

## 结论先行

中文海报与 weekly announcement 已发布到 Production Hosting version `457567bed866aec7`。海报、预览图和 sidecar 均完成 HTTP 全字节 SHA-256 读回；announcement 绑定 family `resi-20261018-15030286`、中文 locale、broadcast source identity 和现有 human-reviewed release。v5/v4/v3 catalog 字节未改变。

## 总时间

约 1 分钟；无模型调用。包括 live baseline、绑定、Hosting 发布和 HTTP 读回。

## 各层模型、耗时与速度

L1–L3 与海报图片全部复用；L4 仅上传已验证 PNG、预览 PNG，并更新 `weekly-announcements-v1.json`。费用 `US$0` model。

## 错误

无发布错误。候选在部署前通过 live version 和 v3/v4/v5 catalog CAS。

## 可以改进的地方

后续将海报 full/preview 与 announcement binding 继续作为一个原子 Hosting 候选，避免只更新 sidecar 或只上传图片。

## 实际覆盖范围

- 完整海报：1200×1800，SHA `9f67e356…`。
- 预览图：600×900，SHA `00818874…`。
- 中文 announcement：pageID `resi-20261018-15030286`，release SHA `3b0fbbfc…`。
- 未执行：App 实际弹出 announcement 的实体设备验收。

## 遗留状态

无待上传文件；海报和 preview 均在线。实体设备 App announcement 展示仍是独立验收项。

## 外部可见的变化

Production 新增中文海报原图、预览图，并在 weekly announcement sidecar 中增加中文条目。目录、文稿、配音和定位未改变。
