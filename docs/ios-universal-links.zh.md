# iOS Universal Links 与二维码深链

状态：代码已接入，**尚未随新 App 版本发布**。旧版 App 仍只会打开网页；AASA 也必须和下一次 Hosting 发布一起上线。

## 支持的目标

正式站二维码继续使用海报规范里的固定格式：

```text
https://ai-for-god-sermon-audio.web.app/?week=<pageId>&contentLang=<locale>&lang=<interfaceLang>
```

App 也接受：

```text
https://ai-for-god-sermon-audio.web.app/pages/<pageId>/<locale>/
tongxing://page/<pageId>?contentLang=<locale>
```

`lang` 只影响界面语言，不改变内容语言；`contentLang` 才选择 `pageId + targetLocale`。

## 路由规则

- HTTPS 链接必须命中配置的 `TongxingContentOrigin` 主机；自定义 scheme 只接受 `tongxing` / `tongxing-beta`。
- `pageId` 只允许 `[A-Za-z0-9._-]`，且必须存在于当前发布目录；不认识的语言回退到该页默认语言。
- 页面不在目录、被撤回或没有独立发布目标时不打开另一篇缓存页，也不伪造成功。
- App 冷启动、前台、后台被 URL 唤起都走同一个 `AppModel.openDeepLink` 路径。

## 文件与身份

| 项目 | 值 |
|---|---|
| Team ID | `G2P4DTQNBA` |
| 正式 App Bundle ID | `com.jonathanjing.tongxing.dev` |
| Beta App Bundle ID | `com.jonathanjing.tongxing.beta` |
| 正式域名 | `ai-for-god-sermon-audio.web.app` |
| Dev 域名 | `ai-for-god-sermon-audio-dev.web.app` |

- 正式版 entitlement：`Config/AssociatedDomains.entitlements`，只含正式域名。
- Debug entitlement：`Config/AssociatedDomainsDev.entitlements`，只含 Dev 域名。
- Beta entitlement：`Config/BetaPush.entitlements`，含 Dev 域名。
- Dev AASA：`firebase/dev/public/.well-known/apple-app-site-association`，包含 Beta 与 Dev App ID。
- 正式 AASA：`firebase/production-overlay/public/.well-known/apple-app-site-association`，只包含正式 App ID。
- 两个 Hosting 配置都为该精确路径设置 `Content-Type: application/json`，并保留 `/.well-known` 文件。

## 发布要求

1. 服务端 AASA 必须出现在正式 Hosting 根目录，且不能重定向、不能带 `.json` 后缀；Apple 会缓存，改完后用新安装或开发模式验证。
2. App 必须用包含 Associated Domains entitlement 的新签名 build；仅改代码、不重新发布 App，现有安装不会获得 Universal Link 能力。
3. 版本号必须按 App Store Connect 当前状态递增；Beta 与正式 App 使用不同 Bundle ID，不能拿正式域名给 Beta 做自动打开。
4. 正式发布前在真实 iPhone 上分别验证：已安装/未安装、冷启动/前台、有效页/撤回页、三种内容语言、Beta 与正式渠道。

## 二维码

用 `tools/development/make_deep_link_qr.swift <https-url> <out.png>` 生成；CoreImage 编码、Vision 解码核对，输出包含 payload、模块数、静区和校验结果。二维码只编码 HTTPS Universal Link，不直接编码自定义 scheme，保证未安装 App 的用户仍有网页落点。

## 已知限制

- Universal Link 从不同扫码器打开时，少数会先进入 Safari，需要再点一次；不能承诺所有扫码器 100% 无感。
- 旧版 App 不会因为站点新增 AASA 而获得深链能力。
- 当前页面二维码在 App 新版本发布前仍按普通网页打开。
