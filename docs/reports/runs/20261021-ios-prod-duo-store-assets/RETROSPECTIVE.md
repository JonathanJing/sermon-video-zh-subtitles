# 复盘：20261021-ios-prod-duo-store-assets

## 结论先行

状态：prepared_for_submission。Apple prepared the 1.26.21 version and four iPhone Duo screenshots in the Chinese and English localization placements, with order read back.

## 耗时与成本

未触发付费模型阶段或群发 APNs；精确墙钟时间未从收据提取。

## 错误与修复

Build 62 的隐私说明缺口由 Build 63 修复。支持站旧发布命令因 public 目录在 Firebase 项目目录外失败，改用忽略目录内冻结的四文件 staging 后部署成功。

## 覆盖范围与遗留状态

正式 App 真机订阅、单设备 APNs、App Privacy 后台声明与 App Review 尚未完成。

## 外部可见变化

本报告只证明对应收据的范围；Apple 构建处理、TestFlight 分发与正式审核分别核对。
