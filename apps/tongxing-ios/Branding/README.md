# 同行标识与外观

`Logo-source.png` 是用户提供的深绿底方形标识，`Brand-reference.png` 是用户提供的品牌组合参考，两份源文件保持原始字节。`Logo-light-source.png` 是基于这两份参考、由 imagegen 生成的浅色外观：米白底、深绿字形、鼠尾草绿书本。生成图沿用原有构图，但不是逐像素换色；深色外观继续使用用户原图。

## 生成与接入

从仓库任意目录运行：

```sh
swift apps/tongxing-ios/scripts/generate-app-icon.swift
```

脚本只做技术尺寸重采样，生成以下不透明资源；原图不被改写，App 图标不预先添加圆角。

| 用途 | 默认 / 浅色 | 深色 |
| --- | --- | --- |
| `AppIcon.appiconset`，1024×1024 | `AppIcon.png` | `AppIcon-dark.png` |
| `BrandMark.imageset`，128×128 | `BrandMark.png` | `BrandMark-dark.png` |

Xcode 的 `AppIcon` 资源中，默认图片不设 appearance，深色图片使用 `appearances: [{"appearance":"luminosity","value":"dark"}]`。在支持的 iOS 上，主屏幕图标按用户选择的图标外观显示；选择自动模式才跟随相应系统设置。旧系统使用默认图标。此次提供 Any 与 Dark 两种资源，没有单独制作 Tinted 资源。[Apple App Icon 配置](https://developer.apple.com/documentation/xcode/configuring-your-app-icon) · [主屏幕外观设置](https://support.apple.com/guide/iphone/customize-apps-and-widgets-on-the-home-screen-iph385473442/ios)

App 内页头使用 `BrandMark` 图片资源的 Any / Dark 变体，原生 SwiftUI 的 `Image("BrandMark")` 按当前视图外观选择。Mac SwiftPM 预览将两张 PNG 单独打包，并根据 `colorScheme` 选择。桌面图标与 App 内 Logo 的选择是两个机制，不通过程序调用更换备用 App 图标来模拟外观切换。

品牌参考图仅作设计参考，不作为整张界面背景或 App 图标打包。

## 验证与版本边界

2026-09-06 的深浅外观更新在本机开发源码中；验证证据放在忽略目录 `artifacts/tongxing-ios/2026-09-06-logo-appearances/`。此前导出的 `0.1.0 (2)` 分发 IPA 仍是单一深绿底图标版本，不包含本次新增浅色外观。

本轮 iOS Simulator 构建、Mac SwiftPM 预览构建通过；编译后的 `Assets.car` 已核对包含 AppIcon 与 BrandMark 的 Any / Dark 资源，iOS 27 模拟器浅色和深色页头截图均已检查。尚未进行真机主屏幕外观切换检查，也未重新导出 IPA。
