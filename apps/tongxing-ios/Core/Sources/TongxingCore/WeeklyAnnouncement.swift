import Foundation

/// Optional sidecar. It adds presentation assets without changing release or catalog schemas.
public struct WeeklyAnnouncementCatalog: Codable, Equatable, Sendable {
    public static let schema = "tongxing-weekly-announcements-v1"
    public let schemaVersion: String
    public let announcements: [WeeklyAnnouncement]

    public init(announcements: [WeeklyAnnouncement]) {
        schemaVersion = Self.schema
        self.announcements = announcements
    }

    public static func decode(_ data: Data) throws -> Self {
        let value = try JSONDecoder().decode(Self.self, from: data)
        guard value.schemaVersion == schema, value.announcements.count <= 520,
              Set(value.announcements.map(\.deduplicationKey)).count == value.announcements.count else {
            throw WeeklyAnnouncementError.invalidBinding
        }
        for item in value.announcements { try item.validate() }
        return value
    }

    public func matchedAnnouncement(pageID: String, locale: String, catalog: MultilingualCatalog) -> WeeklyAnnouncement? {
        announcements.first { $0.pageID == pageID && $0.locale == locale && (try? $0.matchedPage(in: catalog)) != nil }
    }
}

public struct WeeklyAnnouncement: Codable, Equatable, Sendable, Identifiable {
    public let id: String
    public let pageID: String
    public let locale: String
    public let releaseSHA256: String
    public let sourceIdentitySHA256: String
    public let title: String
    public let publishedAt: String
    public let poster: WeeklyPoster

    public init(id: String, pageID: String, locale: String, releaseSHA256: String,
                sourceIdentitySHA256: String, title: String, publishedAt: String, poster: WeeklyPoster) {
        self.id = id; self.pageID = pageID; self.locale = locale; self.releaseSHA256 = releaseSHA256
        self.sourceIdentitySHA256 = sourceIdentitySHA256; self.title = title
        self.publishedAt = publishedAt; self.poster = poster
    }

    /// A refreshed artwork or sidecar id does not repeatedly announce the same release.
    public var deduplicationKey: String { [pageID, locale, releaseSHA256].joined(separator: ":") }

    public func validate() throws {
        guard Validation.identifier(id), Validation.identifier(pageID), Validation.locale(locale),
              Validation.sha256(releaseSHA256), Validation.sha256(sourceIdentitySHA256),
              !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, title.count <= 240,
              ISO8601DateFormatter().date(from: publishedAt) != nil else { throw WeeklyAnnouncementError.invalidBinding }
        try poster.validate()
    }

    public func matchedPage(in catalog: MultilingualCatalog) throws -> MultilingualPage {
        try validate()
        guard let page = catalog.pages.first(where: { $0.id == pageID }),
              page.diagnosticOnly != true, page.simulationOnly != true,
              page.sourceIdentitySha256 == sourceIdentitySHA256,
              let target = page.targets[locale], target.isPublishedContent,
              target.diagnosticOnly != true, target.simulationOnly != true,
              target.releasePackageJsonSha256 == releaseSHA256 else { throw WeeklyAnnouncementError.staleRelease }
        return page
    }
}

public struct WeeklyPoster: Codable, Equatable, Sendable {
    public static let maximumBytes: Int64 = 8 * 1_024 * 1_024
    public let url: String
    public let sha256: String
    public let bytes: Int64
    public let width: Int
    public let height: Int

    public init(url: String, sha256: String, bytes: Int64, width: Int, height: Int) {
        self.url = url; self.sha256 = sha256; self.bytes = bytes; self.width = width; self.height = height
    }

    public func validate() throws {
        guard url.hasPrefix("/posters/"), !url.contains(".."), !url.contains("%"), !url.contains("\\"),
              let parts = URLComponents(string: url), parts.scheme == nil, parts.host == nil,
              parts.query == nil, parts.fragment == nil,
              ["png", "jpg", "jpeg"].contains(URL(fileURLWithPath: url).pathExtension.lowercased()),
              Validation.sha256(sha256), bytes > 0, bytes <= Self.maximumBytes,
              width > 0, height > 0, width <= 8192, height <= 8192,
              width * height <= 20_000_000 else { throw WeeklyAnnouncementError.invalidBinding }
    }
}

public enum WeeklyAnnouncementError: Error, Equatable { case invalidBinding, staleRelease }
