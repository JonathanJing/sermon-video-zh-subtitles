#if os(iOS)
import SwiftUI
import UserNotifications
import TongxingCore

extension Notification.Name {
    static let betaNotificationOpened = Notification.Name("TongxingBetaNotificationOpened")
}

@MainActor
final class BetaNotificationController: NSObject, ObservableObject, UNUserNotificationCenterDelegate {
    static let shared = BetaNotificationController()
    static var isBeta: Bool { Bundle.main.bundleIdentifier == "com.jonathanjing.tongxing.beta" }
    static let requestPrefix = "tongxing-beta-preview-"
    static func allowedOrigin(_ origin: URL) -> Bool {
        #if DEBUG
        if UITestLaunch.isEnabled,
           ProcessInfo.processInfo.arguments.contains("--ui-testing-notification"),
           origin.absoluteString == "https://tongxing-ui-fixture.example.test" { return true }
        #endif
        return origin.scheme == "https" && origin.host == "ai-for-god-sermon-audio-dev.web.app"
    }
    private let center: UNUserNotificationCenter
    private let defaults: UserDefaults
    private let recipient: UUID
    private var preferenceRevision = UUID()
    @Published private(set) var enabled: Bool
    @Published private(set) var locale: String
    @Published private(set) var permissionStatus = "尚未申请系统通知权限。"
    @Published private(set) var status = ""
    @Published private(set) var pending: BetaNotification?
    @Published private(set) var lastOpened: String?
    @Published var landingMessage: String?
    @Published private(set) var busy = false

    override convenience init() {
        var defaults = UserDefaults.standard
        #if DEBUG
        if UITestLaunch.isEnabled,
           let runID = ProcessInfo.processInfo.environment["TONGXING_UI_TEST_RUN_ID"] {
            defaults = UserDefaults(suiteName: "Tongxing-Notification-UITests-\(runID)")!
        }
        #endif
        self.init(center: .current(), defaults: defaults)
    }

    init(center: UNUserNotificationCenter, defaults: UserDefaults) {
        self.center = center
        self.defaults = defaults
        enabled = defaults.bool(forKey: "betaNotificationEnabled")
        locale = defaults.string(forKey: "betaNotificationLocale") ?? "zh-Hans"
        recipient = defaults.string(forKey: "betaNotificationRecipient").flatMap(UUID.init(uuidString:)) ?? UUID()
        super.init()
        if Self.isBeta { defaults.set(recipient.uuidString, forKey: "betaNotificationRecipient") }
    }

    func installDelegate() {
        guard Self.isBeta else { return }
        center.delegate = self
    }

    func setEnabled(_ value: Bool) {
        guard Self.isBeta else { return }
        enabled = value
        preferenceRevision = UUID()
        defaults.set(value, forKey: "betaNotificationEnabled")
        if !value {
            pending = nil
            clearLocalRequests()
            status = "已退出本机通知测试；不会安排新通知。"
        }
    }

    func setLocale(_ value: String) {
        guard ["zh-Hans", "en", "ko", "es", "vi"].contains(value) else { return }
        locale = value
        preferenceRevision = UUID()
        defaults.set(value, forKey: "betaNotificationLocale")
        pending = nil
        clearLocalRequests()
        status = "已更改订阅内容语言；旧语言的本机测试通知已清除。"
    }

    func refreshPermission() async {
        let settings = await center.notificationSettings()
        switch settings.authorizationStatus {
        case .authorized: permissionStatus = "系统通知已允许。"
        case .denied: permissionStatus = "系统通知已拒绝；请到系统设置更改。"
        case .notDetermined: permissionStatus = "尚未申请系统通知权限。"
        case .provisional, .ephemeral: permissionStatus = "系统仅允许临时或静默通知。"
        @unknown default: permissionStatus = "系统通知权限状态未知。"
        }
    }

    func requestPermission() async {
        guard Self.isBeta, enabled, !busy else { return }
        busy = true
        defer { busy = false }
        do {
            _ = try await center.requestAuthorization(options: [.alert, .sound])
            await refreshPermission()
        } catch { status = "通知权限申请失败，请重试或检查系统设置。" }
    }

    func preview(page: MultilingualPage, catalog: MultilingualCatalog, displayTitle: String) async {
        guard Self.isBeta, enabled, !busy, let target = page.targets[locale] else { return }
        busy = true
        defer { busy = false }
        let revision = preferenceRevision
        do {
            let notice = BetaNotification(pageID: page.id, locale: locale, releaseSHA256: target.releasePackageJsonSha256)
            _ = try notice.matchedPage(in: catalog, subscriptionLocale: locale, enabled: enabled, betaChannel: Self.isBeta)
            let settings = await center.notificationSettings()
            guard enabled, preferenceRevision == revision,
                  settings.authorizationStatus == .authorized || settings.authorizationStatus == .provisional else {
                status = "请先允许系统通知，再安排测试。"
                return
            }
            let key = notice.deduplicationKey(recipient: recipient)
            var scheduled = defaults.stringArray(forKey: "betaNotificationScheduled") ?? []
            guard !scheduled.contains(key) else { throw BetaNotificationError.alreadyScheduled }
            let content = UNMutableNotificationContent()
            content.title = SermonHeading.displayTitle(displayTitle, pageID: page.id, date: page.date,
                                                       fallback: AppLocalization.shared.text("证道"))
            content.body = notice.body(date: page.date, audioAvailable: target.audioStatus == "human_reviewed")
            content.sound = settings.soundSetting == .enabled ? .default : nil
            content.userInfo = ["tongxing": try JSONSerialization.jsonObject(with: JSONEncoder().encode(notice))]
            // A plain text preview remains useful when a future poster cannot load.
            let request = UNNotificationRequest(identifier: Self.requestPrefix + revision.uuidString + ":" + key, content: content,
                                                trigger: UNTimeIntervalNotificationTrigger(timeInterval: 5, repeats: false))
            try await center.add(request)
            // A user may opt out while awaiting permission/settings/add.
            guard enabled, preferenceRevision == revision, locale == notice.locale else {
                center.removePendingNotificationRequests(withIdentifiers: [request.identifier])
                center.removeDeliveredNotifications(withIdentifiers: [request.identifier])
                return
            }
            scheduled.append(key)
            defaults.set(Array(scheduled.suffix(200)), forKey: "betaNotificationScheduled")
            status = "已安排本机测试通知，最早约 5 秒后触发；实际显示时间由系统决定。"
        } catch BetaNotificationError.alreadyScheduled {
            status = "此内容版本和语言已测试；可先清除本机测试记录再重试。"
        } catch { status = "无法安排测试：内容版本或语言不可用。" }
    }

    func clearTestHistory() {
        preferenceRevision = UUID()
        clearLocalRequests()
        defaults.removeObject(forKey: "betaNotificationScheduled")
        status = "本机测试记录已清除。"
    }

    private func clearLocalRequests() {
        Task {
            let pending = await center.pendingNotificationRequests()
            let currentPrefix = Self.requestPrefix + preferenceRevision.uuidString + ":"
            center.removePendingNotificationRequests(withIdentifiers: pending.map(\.identifier).filter { $0.hasPrefix(Self.requestPrefix) && !$0.hasPrefix(currentPrefix) })
            let delivered = await center.deliveredNotifications()
            let deliveredPrefix = Self.requestPrefix + preferenceRevision.uuidString + ":"
            center.removeDeliveredNotifications(withIdentifiers: delivered.map { $0.request.identifier }.filter { $0.hasPrefix(Self.requestPrefix) && !$0.hasPrefix(deliveredPrefix) })
        }
    }

    func openPending(in model: AppModel) {
        guard let notice = pending, let catalog = model.multilingualCatalog else { return }
        pending = nil
        do {
            guard Self.allowedOrigin(model.mediaOrigin) else { throw BetaNotificationError.invalidBinding }
            let page = try notice.matchedPage(in: catalog, subscriptionLocale: locale, enabled: enabled, betaChannel: Self.isBeta)
            guard model.independentPages.contains(where: { $0.id == page.id }) else { throw BetaNotificationError.staleRelease }
            model.selectPublishedPage(page)
            model.selectPublishedContentLanguage(notice.locale)
            lastOpened = "\(page.id) · \(notice.locale)"
            status = "已打开通知对应的 Beta 内容和语言；文字与音频仍通过原有发布包校验。"
            NotificationCenter.default.post(name: .betaNotificationOpened, object: nil)
        } catch { landingMessage = "通知版本已变化、语言未订阅或内容不可用。当前内容没有改变，请刷新目录后重新测试。" }
    }

    private func decode(_ info: [AnyHashable: Any]) -> BetaNotification? {
        guard let value = info["tongxing"], JSONSerialization.isValidJSONObject(value),
              let data = try? JSONSerialization.data(withJSONObject: value),
              let notice = try? JSONDecoder().decode(BetaNotification.self, from: data),
              (try? notice.validate()) != nil else { return nil }
        return notice
    }

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                            withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        Task { @MainActor in
            let notice = decode(notification.request.content.userInfo)
            let allowed = Self.isBeta && enabled && notice?.locale == locale
            completionHandler(allowed ? [.banner, .list, .sound] : [])
        }
    }

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
                                            withCompletionHandler completionHandler: @escaping () -> Void) {
        Task { @MainActor in
            if Self.isBeta, enabled, response.actionIdentifier == UNNotificationDefaultActionIdentifier {
                if let notice = decode(response.notification.request.content.userInfo), notice.locale == locale {
                    pending = notice
                } else { landingMessage = "此通知没有有效的 Beta 内容绑定。" }
            }
            completionHandler()
        }
    }
}

final class BetaNotificationAppDelegate: NSObject, UIApplicationDelegate {
    func application(_ application: UIApplication, didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
        BetaNotificationController.shared.installDelegate()
        return true
    }
}

struct BetaNotificationSettingsView: View {
    @ObservedObject var model: AppModel
    @ObservedObject private var localization = AppLocalization.shared
    @ObservedObject private var controller = BetaNotificationController.shared
    @Environment(\.scenePhase) private var scenePhase
    @State private var pageID = ""
    private var pages: [MultilingualPage] {
        guard model.multilingualCatalog?.schemaVersion == MultilingualCatalog.dualScriptSchemaVersion else { return [] }
        return model.independentPages.filter { $0.targets[controller.locale]?.contentStatus == "human_reviewed" }
    }
    private var page: MultilingualPage? { pages.first { $0.id == pageID } }
    private func normalizeSelection() {
        if !pages.contains(where: { $0.id == pageID }) { pageID = pages.first?.id ?? "" }
    }

    var body: some View {
        Form {
            Section {
                Toggle(localization.text("开启本机通知测试"), isOn: Binding(get: { controller.enabled }, set: { controller.setEnabled($0) }))
                    .accessibilityIdentifier("beta-notification-opt-in")
                Text(localization.text("默认关闭。只在本机安排通知，不会向其他设备发送。"))
                    .font(.footnote).foregroundStyle(.secondary)
                Picker(localization.text("订阅内容语言"), selection: Binding(get: { controller.locale }, set: { controller.setLocale($0); normalizeSelection() })) {
                    Text("中文").tag("zh-Hans")
                    Text("English").tag("en")
                    Text("한국어").tag("ko")
                    Text("Español").tag("es")
                    Text("Tiếng Việt").tag("vi")
                }.accessibilityIdentifier("beta-notification-language")
                Text(localization.text("通知内容语言与 App 界面语言分别选择。"))
                    .font(.footnote).foregroundStyle(.secondary)
            }
            Section(localization.text("系统通知权限")) {
                Text(localization.text(controller.permissionStatus)).accessibilityIdentifier("beta-notification-permission-status")
                if let opened = controller.lastOpened {
                    Text(opened).font(.caption).accessibilityIdentifier("beta-notification-last-opened")
                }
                Button(localization.text("允许系统通知")) { Task { await controller.requestPermission() } }
                    .disabled(!controller.enabled || controller.busy)
                    .accessibilityIdentifier("beta-notification-permission")
                Link(localization.text("打开系统通知设置"), destination: URL(string: UIApplication.openSettingsURLString)!)
            }
            Section(localization.text("本机预览")) {
                if !controller.status.isEmpty {
                    Text(localization.text(controller.status)).accessibilityIdentifier("beta-notification-status")
                }
                if let page, let target = page.targets[controller.locale] {
                    Picker(localization.text("测试内容"), selection: $pageID) {
                        ForEach(pages) { Text(model.heading(for: $0).title).tag($0.id) }
                    }
                    let notice = BetaNotification(pageID: page.id, locale: controller.locale, releaseSHA256: target.releasePackageJsonSha256)
                    Text(model.heading(for: page).title).font(.headline)
                    Text(notice.body(date: page.date, audioAvailable: target.audioStatus == "human_reviewed"))
                    Button(localization.text("安排本机测试通知（约 5 秒后）")) {
                        if let catalog = model.multilingualCatalog,
                           BetaNotificationController.allowedOrigin(model.mediaOrigin) {
                            Task { await controller.preview(page: page, catalog: catalog, displayTitle: model.heading(for: page).title) }
                        }
                    }.disabled(!controller.enabled || controller.busy)
                        .accessibilityIdentifier("beta-notification-preview")
                } else {
                    Text(localization.text("此语言暂没有可测试内容，请刷新或选择其他语言。"))
                        .accessibilityIdentifier("beta-notification-unavailable")
                }
                Button(localization.text("清除本机测试记录")) { controller.clearTestHistory() }
                    .accessibilityIdentifier("beta-notification-clear")
                Text(localization.text("当前仅支持本机测试，远端推送和海报附件将在后续 Beta 中验证。"))
                    .font(.footnote).foregroundStyle(.secondary)
            }
        }
        .navigationTitle(localization.text("Beta 通知测试"))
        .task { normalizeSelection(); await controller.refreshPermission() }
        .onChange(of: pages.map(\.id)) { _, _ in normalizeSelection() }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active { Task { await controller.refreshPermission() } }
        }
    }
}
#endif
