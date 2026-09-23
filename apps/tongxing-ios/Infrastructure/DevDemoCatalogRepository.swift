import Foundation

/// Development POC metadata has no asset hashes or human approval. Keep it
/// separate from the verified Layer 4 release types and never admit it through
/// MultilingualCatalogRepository.
public struct DevDemoCatalog: Decodable, Sendable {
    public let schemaVersion: String
    public let environment: String
    public let poc: Bool
    public let defaultPageId: String
    public let pages: [DevDemoPage]

    public func page(id: String) -> DevDemoPage? { pages.first { $0.id == id } }

    fileprivate func validate() throws {
        guard schemaVersion == "sermon-multilingual-demo-catalog-v1",
              environment == "development", poc,
              !pages.isEmpty, pages.count <= 20,
              Set(pages.map(\.id)).count == pages.count,
              page(id: defaultPageId) != nil else { throw ContentStorageError.invalidResponse }
        for page in pages {
            guard !page.id.isEmpty, page.id.count <= 128,
                  page.id.allSatisfy({ $0.isASCII && ($0.isLetter || $0.isNumber || $0 == "-") }),
                  !page.targets.isEmpty, page.targets.count <= 16,
                  page.targets[page.defaultTargetLocale] != nil
            else { throw ContentStorageError.invalidResponse }
            for (locale, target) in page.targets {
                guard Self.allowedLocales.contains(locale),
                      target.releasePackageUrl == "/releases/\(page.id)/\(locale).json",
                      !target.contentStatus.isEmpty, !target.audioStatus.isEmpty
                else { throw ContentStorageError.invalidResponse }
            }
        }
    }

    private static let allowedLocales: Set<String> = ["en", "zh-Hans", "ko", "es", "vi"]
}

public struct DevDemoPage: Decodable, Sendable {
    public let id: String
    public let defaultTargetLocale: String
    public let targets: [String: DevDemoTarget]
}

public struct DevDemoTarget: Decodable, Sendable {
    public let releasePackageUrl: String
    public let contentStatus: String
    public let audioStatus: String
    public let machineScreening: String?
}

private struct DevDemoRelease: Decodable {
    let schemaVersion: String
    let environment: String
    let poc: Bool
    let productionEligible: Bool
    let humanApproval: Bool
    let pageId: String
    let targetLocale: String
    let contentStatus: String
    let audioStatus: String
    let pageUrl: String
}

public actor DevDemoCatalogRepository {
    private let origin: URL
    private let session: URLSession
    private let maximumBytes: Int64 = 2 * 1_024 * 1_024

    public init(origin: URL, session: URLSession = .shared) {
        self.origin = origin
        self.session = session
    }

    public func loadCatalog() async throws -> DevDemoCatalog {
        let data = try await load(path: "/multilingual.json")
        let catalog = try JSONDecoder().decode(DevDemoCatalog.self, from: data)
        try catalog.validate()
        return catalog
    }

    /// A demo route is deliberately returned as a URL, not VerifiedLanguagePage.
    /// Its HTML and referenced assets have no canonical release hash.
    public func pageURL(page: DevDemoPage, locale: String) async throws -> URL {
        guard let target = page.targets[locale] else { throw ContentStorageError.invalidDownloadReference }
        let data = try await load(path: target.releasePackageUrl)
        let release = try JSONDecoder().decode(DevDemoRelease.self, from: data)
        let expectedSchema = locale == "en" ? "sermon-source-language-demo-package-v1" :
            "sermon-target-language-demo-package-v1"
        guard release.schemaVersion == expectedSchema, release.environment == "development",
              release.poc, !release.productionEligible, !release.humanApproval,
              release.pageId == page.id, release.targetLocale == locale,
              release.contentStatus == target.contentStatus,
              release.audioStatus == target.audioStatus,
              release.pageUrl == "/pages/\(page.id)/\(locale)"
        else { throw ContentStorageError.invalidResponse }
        return try sameOriginURL(path: release.pageUrl)
    }

    private func load(path: String) async throws -> Data {
        let url = try sameOriginURL(path: path)
        let temporary = FileManager.default.temporaryDirectory
            .appendingPathComponent("tongxing-dev-demo-\(UUID().uuidString).part")
        defer { try? FileManager.default.removeItem(at: temporary) }
        let transfer = HTTPFileTransfer(session: session, url: url, temporaryURL: temporary,
                                        maximumBytes: maximumBytes)
        _ = try await transfer.run()
        return try Data(contentsOf: temporary)
    }

    private func sameOriginURL(path: String) throws -> URL {
        guard origin.scheme == "https", origin.user == nil, origin.password == nil,
              origin.query == nil, origin.fragment == nil,
              path.hasPrefix("/"), !path.hasPrefix("//"),
              !path.contains(".."), !path.contains("?"), !path.contains("#"),
              let url = URL(string: path, relativeTo: origin)?.absoluteURL,
              ContentOrigin.isSame(origin, url)
        else { throw ContentStorageError.invalidURL }
        return url
    }
}
