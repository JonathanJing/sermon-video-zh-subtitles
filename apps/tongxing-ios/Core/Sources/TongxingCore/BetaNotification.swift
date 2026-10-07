import Foundation

/// A notification points to a frozen release, never an arbitrary external URL.
public struct BetaNotification: Codable, Equatable, Sendable {
    public static let schema = "tongxing-beta-notification-v1"
    public static let environment = "beta-dev"
    public let schemaVersion: String
    public let environment: String
    public let pageID: String
    public let locale: String
    public let releaseSHA256: String

    public init(pageID: String, locale: String, releaseSHA256: String) {
        schemaVersion = Self.schema
        environment = Self.environment
        self.pageID = pageID
        self.locale = locale
        self.releaseSHA256 = releaseSHA256
    }

    public func validate() throws {
        guard schemaVersion == Self.schema, environment == Self.environment,
              Validation.identifier(pageID), ["zh-Hans", "en", "ko", "es", "vi"].contains(locale),
              Validation.sha256(releaseSHA256) else { throw BetaNotificationError.invalidBinding }
    }

    public func matchedPage(in catalog: MultilingualCatalog, subscriptionLocale: String,
                            enabled: Bool, betaChannel: Bool) throws -> MultilingualPage {
        try validate()
        guard enabled, betaChannel, locale == subscriptionLocale else { throw BetaNotificationError.notSubscribed }
        // The native dual-script reader is the first notification landing path.
        guard catalog.schemaVersion == MultilingualCatalog.dualScriptSchemaVersion,
              let page = catalog.pages.first(where: { $0.id == pageID }),
              let target = page.targets[locale], target.contentStatus == "human_reviewed",
              target.releasePackageJsonSha256 == releaseSHA256 else { throw BetaNotificationError.staleRelease }
        return page
    }

    public func deduplicationKey(recipient: UUID) -> String {
        [environment, pageID, locale, releaseSHA256, recipient.uuidString].joined(separator: ":")
    }

    /// Generic copy avoids borrowing a Chinese catalog title for another language.
    public var title: String {
        switch locale {
        case "en": "[Beta test] New content is available"
        case "ko": "[Beta 테스트] 새로운 콘텐츠가 준비되었습니다"
        case "es": "[Prueba Beta] Hay contenido nuevo"
        case "vi": "[Thử nghiệm Beta] Có nội dung mới"
        default: "[Beta 测试] 新内容已上架"
        }
    }

    public func body(date: String, audioAvailable: Bool) -> String {
        switch locale {
        case "en": "\(date) · Open Tongxing Beta to \(audioAvailable ? "read and listen." : "read. Audio is unavailable.")"
        case "ko": "\(date) · 동행 Beta에서 \(audioAvailable ? "읽고 들어 보세요." : "읽어 보세요. 오디오는 제공되지 않습니다.")"
        case "es": "\(date) · Abre Tongxing Beta para \(audioAvailable ? "leer y escuchar." : "leer. El audio no está disponible.")"
        case "vi": "\(date) · Mở Tongxing Beta để \(audioAvailable ? "đọc và nghe." : "đọc. Chưa có âm thanh.")"
        default: "\(date) · 打开同行 Beta \(audioAvailable ? "查看并试听。" : "阅读文字。此语言暂无音频。")"
        }
    }
}

public enum BetaNotificationError: Error, Equatable {
    case invalidBinding, notSubscribed, staleRelease, alreadyScheduled
}
