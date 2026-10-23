import Foundation

/// A production push can open only the same published release it announced.
public struct ProductionNotification: Codable, Equatable, Sendable {
    public static let schema = "tongxing-production-notification-v1"
    public static let environment = "production"
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
              Validation.sha256(releaseSHA256) else { throw ProductionNotificationError.invalidBinding }
    }

    public func matchedPage(in catalog: MultilingualCatalog, subscriptionLocale: String,
                            enabled: Bool, productionOrigin: Bool) throws -> MultilingualPage {
        try validate()
        guard enabled, productionOrigin, locale == subscriptionLocale else {
            throw ProductionNotificationError.notSubscribed
        }
        guard catalog.isDualScript,
              let page = catalog.pages.first(where: { $0.id == pageID }),
              page.diagnosticOnly != true, page.simulationOnly != true,
              let target = page.targets[locale], target.isPublishedContent,
              target.diagnosticOnly != true, target.simulationOnly != true,
              target.releasePackageJsonSha256 == releaseSHA256 else {
            throw ProductionNotificationError.staleRelease
        }
        return page
    }
}

public enum ProductionNotificationError: Error, Equatable {
    case invalidBinding, notSubscribed, staleRelease
}
