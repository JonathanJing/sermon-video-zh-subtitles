#if os(iOS)
import SwiftUI
import UserNotifications

/// Single-device, operator-driven APNs testing. No token leaves this device automatically.
@MainActor
final class BetaRemotePush: ObservableObject {
    static let shared = BetaRemotePush()
    @Published private(set) var status = "远程推送尚未登记。"
    @Published private(set) var exportURL: URL?
    private var requested = false
    private var revision = UUID()

    static func environment(profile: Data?, productionDistribution: Bool) -> String? {
        if let profile {
            // CMS embeds a plist; only inspect its signed entitlement payload.
            let start = Data("<?xml".utf8), end = Data("</plist>".utf8)
            guard let a = profile.range(of: start), let b = profile.range(of: end, in: a.lowerBound..<profile.endIndex),
                  let plist = try? PropertyListSerialization.propertyList(from: profile.subdata(in: a.lowerBound..<b.upperBound), format: nil),
                  let dictionary = plist as? [String: Any], let entitlements = dictionary["Entitlements"] as? [String: Any],
                  let value = entitlements["aps-environment"] as? String else { return nil }
            if value == "production" { return "production" }
            if value == "development", !productionDistribution { return "sandbox" }
            return nil
        }
        // TestFlight removes the embedded profile. This distribution-only build
        // flag requires archive/export signature verification before uploading.
        return productionDistribution ? "production" : nil
    }

    private var environment: String? {
        #if TONGXING_APNS_PRODUCTION
        let distribution = true
        #else
        let distribution = false
        #endif
        let profile = Bundle.main.url(forResource: "embedded", withExtension: "mobileprovision").flatMap { try? Data(contentsOf: $0) }
        #if targetEnvironment(simulator)
        return nil
        #else
        return Self.environment(profile: profile, productionDistribution: distribution)
        #endif
    }

    private func receiptURL() throws -> URL {
        let root = try FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true)
            .appendingPathComponent("BetaPush", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        var resource = root
        var values = URLResourceValues(); values.isExcludedFromBackup = true
        try resource.setResourceValues(values)
        return root.appendingPathComponent("apns-device-v1.json")
    }

    func register() async {
        guard BetaNotificationController.isBeta, BetaNotificationController.shared.enabled else { return }
        let permissionRevision = revision
        let settings = await UNUserNotificationCenter.current().notificationSettings()
        guard permissionRevision == revision else { return }
        guard BetaNotificationController.shared.enabled, settings.authorizationStatus == .authorized else {
            status = "请先开启通知测试并允许系统通知。"; return
        }
        guard environment != nil else {
            status = "无法确认签名的推送环境；请使用已核验签名的真机 Beta。"; return
        }
        revision = UUID()
        exportURL = nil
        try? FileManager.default.removeItem(at: receiptURL())
        requested = true
        status = "正在向 Apple 登记本机推送。"
        UIApplication.shared.registerForRemoteNotifications()
    }

    func didRegister(_ data: Data) {
        guard requested, BetaNotificationController.isBeta, BetaNotificationController.shared.enabled,
              let environment, !data.isEmpty else { return }
        requested = false
        let acceptedRevision = revision
        Task {
            let settings = await UNUserNotificationCenter.current().notificationSettings()
            guard acceptedRevision == revision else { return }
            guard BetaNotificationController.shared.enabled, settings.authorizationStatus == .authorized else { revoke(); return }
            do {
                let receipt: [String: String] = ["schemaVersion": "tongxing-beta-apns-device-v1",
                    "bundleID": Bundle.main.bundleIdentifier ?? "", "environment": environment,
                    "deviceToken": data.map { String(format: "%02x", $0) }.joined(),
                    "registeredAt": ISO8601DateFormatter().string(from: Date()), "locale": BetaNotificationController.shared.locale]
                let url = try receiptURL()
                try JSONSerialization.data(withJSONObject: receipt, options: [.sortedKeys]).write(to: url, options: [.atomic, .completeFileProtection])
                try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
                exportURL = url
                status = "本机推送已登记。可主动导出设备登记文件给本机测试工具。"
            } catch { exportURL = nil; status = "无法安全保存登记文件，请重试。" }
        }
    }

    func didFail() {
        guard BetaNotificationController.isBeta, requested else { return }
        revision = UUID()
        requested = false; exportURL = nil
        status = "Apple 推送登记失败，请检查 Beta capability、签名及网络后重试。"
    }

    func revoke() {
        guard BetaNotificationController.isBeta else { return }
        revision = UUID()
        requested = false; exportURL = nil
        try? FileManager.default.removeItem(at: receiptURL())
        UIApplication.shared.unregisterForRemoteNotifications()
        status = "已清除本机推送登记。"
    }
}
#endif
