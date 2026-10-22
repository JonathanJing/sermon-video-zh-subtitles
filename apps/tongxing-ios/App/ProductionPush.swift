#if os(iOS)
import Foundation
import Security
import SwiftUI
import TongxingCore
import UserNotifications

extension Notification.Name {
    static let productionNotificationOpened = Notification.Name("TongxingProductionNotificationOpened")
}

/// Explicit opt-in for the formal App. Tokens and the installation secret stay in Keychain.
/// An uncertain network result retains the exact request for an idempotent retry.
@MainActor
final class ProductionPush: NSObject, ObservableObject, UNUserNotificationCenterDelegate {
    static let shared = ProductionPush()
    static let bundleID = "com.jonathanjing.tongxing.dev"
    static let origin = URL(string: "https://ai-for-god-sermon-audio.web.app")!
    static var isProduction: Bool { Bundle.main.bundleIdentifier == bundleID }

    struct SubscriptionRequest: Codable, Equatable {
        let schemaVersion: Int
        let action: String
        let installationId: String
        let secret: String
        let seq: Int
        let deviceToken: String?
        let locale: String?
    }

    private struct SubscriptionResponse: Decodable {
        let ok: Bool
        let accepted: Bool
        let active: Bool
        let seq: Int
    }

    private struct SavedState: Codable {
        let installationId: String
        let secret: String
        var seq: Int = 0
        var pending: SubscriptionRequest?
        var deviceToken: String?
        var acknowledgedToken: String?
        var acknowledgedLocale: String?
        var active = false
        var lastAcknowledgedAt: Date?
    }

    private let defaults = UserDefaults.standard
    private let center = UNUserNotificationCenter.current()
    private let keychainAccount = "production-push-subscription-v1"
    private let enabledKey = "productionPushEnabled"
    private let localeKey = "productionPushLocale"
    private let offeredVersionKey = "productionPushOfferedVersion"
    private var syncing = false
    private var reconcileRequested = false
    @Published private(set) var enabled: Bool
    @Published private(set) var locale: String
    @Published private(set) var status = "通知默认关闭。"
    @Published private(set) var permissionStatus = "尚未申请系统通知权限。"
    @Published private(set) var pending: ProductionNotification?
    @Published var landingMessage: String?

    override private init() {
        enabled = defaults.bool(forKey: enabledKey)
        locale = defaults.string(forKey: localeKey) ?? "zh-Hans"
        super.init()
    }

    private var keychainQuery: [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: Self.bundleID,
         kSecAttrAccount as String: keychainAccount]
    }

    private func loadState() throws -> SavedState? {
        var query = keychainQuery
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        let code = SecItemCopyMatching(query as CFDictionary, &result)
        if code == errSecItemNotFound { return nil }
        guard code == errSecSuccess, let data = result as? Data else { throw PushStorageError.unavailable }
        return try JSONDecoder().decode(SavedState.self, from: data)
    }

    private func saveState(_ state: SavedState) throws {
        let data = try JSONEncoder().encode(state)
        let attributes: [String: Any] = [kSecValueData as String: data,
                                         kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly]
        let update = SecItemUpdate(keychainQuery as CFDictionary, attributes as CFDictionary)
        if update == errSecSuccess { return }
        guard update == errSecItemNotFound else { throw PushStorageError.unavailable }
        var insert = keychainQuery
        attributes.forEach { insert[$0.key] = $0.value }
        guard SecItemAdd(insert as CFDictionary, nil) == errSecSuccess else { throw PushStorageError.unavailable }
    }

    private func newState() throws -> SavedState {
        var bytes = [UInt8](repeating: 0, count: 32)
        guard SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes) == errSecSuccess else {
            throw PushStorageError.unavailable
        }
        let secret = Data(bytes).base64EncodedString().replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
        let state = SavedState(installationId: UUID().uuidString, secret: secret)
        try saveState(state)
        return state
    }

    private enum PushStorageError: Error { case unavailable }

    func installDelegate() {
        guard Self.isProduction else { return }
        center.delegate = self
    }

    func shouldOfferAfterUpdate() -> Bool {
        guard Self.isProduction, !enabled,
              !ProcessInfo.processInfo.arguments.contains("--ui-testing") else { return false }
        let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? ""
        guard !version.isEmpty, defaults.string(forKey: offeredVersionKey) != version else { return false }
        defaults.set(version, forKey: offeredVersionKey)
        return true
    }

    func refreshPermissionAndRegistration() async {
        guard Self.isProduction else { return }
        let settings = await center.notificationSettings()
        switch settings.authorizationStatus {
        case .authorized: permissionStatus = "系统通知已允许。"
        case .denied: permissionStatus = "系统通知已关闭。可在系统设置中更改。"
        case .notDetermined: permissionStatus = "尚未申请系统通知权限。"
        case .provisional, .ephemeral: permissionStatus = "系统仅允许临时或静默通知。"
        @unknown default: permissionStatus = "无法确认系统通知权限。"
        }
        if enabled && settings.authorizationStatus == .authorized {
            UIApplication.shared.registerForRemoteNotifications()
        } else {
            await reconcile()
        }
    }

    func enable() async {
        guard Self.isProduction else { return }
        do {
            let allowed = try await center.requestAuthorization(options: [.alert, .sound, .badge])
            guard allowed else {
                status = "系统通知未获允许；没有订阅。"
                await refreshPermissionAndRegistration()
                return
            }
            _ = try loadState() ?? newState()
            enabled = true
            defaults.set(true, forKey: enabledKey)
            status = "正在登记通知；完成前不会加入发送名单。"
            await refreshPermissionAndRegistration()
        } catch {
            status = "无法开启通知，请稍后重试。"
        }
    }

    func disable() async {
        guard Self.isProduction else { return }
        enabled = false
        defaults.set(false, forKey: enabledKey)
        pending = nil
        status = "已关闭本机通知；正在撤回服务器订阅。"
        UIApplication.shared.unregisterForRemoteNotifications()
        await reconcile()
    }

    func setLocale(_ value: String) async {
        guard Self.isProduction, ["zh-Hans", "en", "ko", "es", "vi"].contains(value) else { return }
        locale = value
        defaults.set(value, forKey: localeKey)
        pending = nil
        if enabled { await reconcile() }
    }

    func didRegister(_ data: Data) {
        guard Self.isProduction, enabled, !data.isEmpty else { return }
        do {
            var state = try loadState() ?? newState()
            state.deviceToken = data.map { String(format: "%02x", $0) }.joined()
            try saveState(state)
            Task { await reconcile() }
        } catch { status = "无法安全保存推送登记，请重试。" }
    }

    func didFailToRegister() {
        guard Self.isProduction else { return }
        status = "Apple 推送登记失败；请检查网络后重试。"
    }

    private func post(_ request: SubscriptionRequest) async throws -> SubscriptionResponse {
        var urlRequest = URLRequest(url: Self.origin.appendingPathComponent("api/push/subscription"))
        urlRequest.httpMethod = "POST"
        urlRequest.timeoutInterval = 15
        urlRequest.setValue("application/json", forHTTPHeaderField: "Content-Type")
        urlRequest.httpBody = try JSONEncoder().encode(request)
        let (data, response) = try await URLSession.shared.data(for: urlRequest)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200,
              data.count <= 4_096 else { throw PushStorageError.unavailable }
        let result = try JSONDecoder().decode(SubscriptionResponse.self, from: data)
        guard result.ok, result.accepted, result.seq == request.seq,
              result.active == (request.action == "upsert") else { throw PushStorageError.unavailable }
        return result
    }

    private func nextRequest(_ state: inout SavedState, action: String) throws -> SubscriptionRequest {
        state.seq += 1
        let request = SubscriptionRequest(schemaVersion: 1, action: action,
                                          installationId: state.installationId, secret: state.secret,
                                          seq: state.seq,
                                          deviceToken: action == "upsert" ? state.deviceToken : nil,
                                          locale: action == "upsert" ? locale : nil)
        state.pending = request
        try saveState(state) // Freeze exact bytes before the network request.
        return request
    }

    private func reconcile() async {
        guard Self.isProduction else { return }
        if syncing {
            reconcileRequested = true
            return
        }
        syncing = true
        defer {
            syncing = false
            if reconcileRequested {
                reconcileRequested = false
                Task { await reconcile() }
            }
        }
        do {
            guard var state = try loadState() else { return }
            // A pending request may have reached the server. Retry it unchanged.
            for _ in 0..<3 {
                let settings = await center.notificationSettings()
                let wantsActive = enabled && settings.authorizationStatus == .authorized && state.deviceToken != nil
                let needsRefresh = state.lastAcknowledgedAt.map { Date().timeIntervalSince($0) > 7 * 24 * 3600 } ?? true
                let action: String?
                if state.pending != nil { action = nil }
                else if wantsActive && (!state.active || state.acknowledgedToken != state.deviceToken ||
                                        state.acknowledgedLocale != locale || needsRefresh) { action = "upsert" }
                else if !wantsActive && state.active { action = "delete" }
                else { return }
                let request = try state.pending ?? nextRequest(&state, action: action!)
                _ = try await post(request)
                // APNs may register a newer token while this request is in flight.
                // Preserve it so the next pass replaces the acknowledged token.
                state = try loadState() ?? state
                state.active = request.action == "upsert"
                state.acknowledgedToken = state.active ? request.deviceToken : nil
                state.acknowledgedLocale = state.active ? request.locale : nil
                state.lastAcknowledgedAt = Date()
                state.pending = nil
                if !state.active { state.deviceToken = nil }
                try saveState(state)
                status = state.active ? "本机已订阅每周内容通知。" : "已撤回服务器订阅。"
            }
        } catch {
            status = enabled ? "订阅尚未确认；联网后会重试。" : "退订尚未确认；联网后会继续重试。"
        }
    }

    private func decode(_ userInfo: [AnyHashable: Any]) -> ProductionNotification? {
        guard let object = userInfo["tongxing"], JSONSerialization.isValidJSONObject(object),
              let data = try? JSONSerialization.data(withJSONObject: object),
              let notice = try? JSONDecoder().decode(ProductionNotification.self, from: data),
              (try? notice.validate()) != nil else { return nil }
        return notice
    }

    func openPending(in model: AppModel) {
        guard let notice = pending, let catalog = model.multilingualCatalog else { return }
        pending = nil
        do {
            let productionOrigin = model.mediaOrigin == Self.origin
            let page = try notice.matchedPage(in: catalog, subscriptionLocale: locale,
                                              enabled: enabled, productionOrigin: productionOrigin)
            guard model.independentPages.contains(where: { $0.id == page.id }) else {
                throw ProductionNotificationError.staleRelease
            }
            model.selectPublishedPage(page)
            model.selectPublishedContentLanguage(notice.locale)
            NotificationCenter.default.post(name: .productionNotificationOpened, object: nil)
        } catch {
            landingMessage = "通知对应的内容或订阅已变化；请刷新页面。"
        }
    }

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                            withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        Task { @MainActor in
            let notice = decode(notification.request.content.userInfo)
            completionHandler(enabled && notice?.locale == locale ? [.banner, .list, .sound] : [])
        }
    }

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
                                            withCompletionHandler completionHandler: @escaping () -> Void) {
        Task { @MainActor in
            if enabled && response.actionIdentifier == UNNotificationDefaultActionIdentifier,
               let notice = decode(response.notification.request.content.userInfo), notice.locale == locale {
                pending = notice
            }
            completionHandler()
        }
    }
}

struct ProductionPushSettingsView: View {
    @ObservedObject private var push = ProductionPush.shared
    @ObservedObject private var localization = AppLocalization.shared
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        Form {
            Section {
                Text(localization.text("选择开启后，同行会按你选的内容语言发送每周新内容通知。默认关闭，可随时退出。"))
                    .font(.footnote)
                Text(localization.text("开启时会上传 Apple 推送令牌、随机安装标识和所选语言。关闭时尝试撤回订阅；离线时会在下次联网后重试。有效登记最长 60 天，登记与发送记录最多保留 365 天。"))
                    .font(.footnote)
                    .accessibilityIdentifier("production-push-privacy")
                Picker(localization.text("通知内容语言"), selection: Binding(get: { push.locale }, set: { value in Task { await push.setLocale(value) } })) {
                    Text("中文").tag("zh-Hans")
                    Text("English").tag("en")
                    Text("한국어").tag("ko")
                    Text("Español").tag("es")
                    Text("Tiếng Việt").tag("vi")
                }.accessibilityIdentifier("production-push-locale")
                if push.enabled {
                    Button(localization.text("关闭每周通知"), role: .destructive) { Task { await push.disable() } }
                        .accessibilityIdentifier("production-push-disable")
                } else {
                    Button(localization.text("开启每周通知")) { Task { await push.enable() } }
                        .accessibilityIdentifier("production-push-enable")
                }
            }
            Section(localization.text("订阅状态")) {
                Text(localization.text(push.permissionStatus))
                Text(localization.text(push.status)).accessibilityIdentifier("production-push-status")
                Link(localization.text("打开系统通知设置"), destination: URL(string: UIApplication.openSettingsURLString)!)
            }
        }
        .navigationTitle(localization.text("每周通知"))
        .task { await push.refreshPermissionAndRegistration() }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active { Task { await push.refreshPermissionAndRegistration() } }
        }
    }
}
#endif
