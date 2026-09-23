import Foundation

public enum LanguageCapability: String, Codable, CaseIterable, Sendable {
    case text, captions, audio, download, alignment
}

public struct MultilingualCatalog: Codable, Sendable, Equatable {
    public static let supportedSchemaVersion = "sermon-multilingual-catalog-v2"
    public let schemaVersion: String
    public let generatedAt: String
    public let defaultPageId: String
    public let pages: [MultilingualPage]

    public var defaultPage: MultilingualPage { pages.first { $0.id == defaultPageId }! }

    public static func decode(_ data: Data) throws -> Self {
        let value = try JSONDecoder().decode(Self.self, from: data)
        try value.validate()
        return value
    }

    public func validate() throws {
        guard schemaVersion == Self.supportedSchemaVersion else { throw CatalogError.invalid("不支持的多语言目录版本") }
        guard !pages.isEmpty, pages.count <= 104 else { throw CatalogError.invalid("多语言目录页数无效") }
        guard Set(pages.map(\.id)).count == pages.count else { throw CatalogError.invalid("多语言页面 ID 重复") }
        guard pages.contains(where: { $0.id == defaultPageId }) else { throw CatalogError.invalid("默认多语言页面不存在") }
        for page in pages { try page.validate() }
    }
}

public struct MultilingualPage: Codable, Sendable, Equatable, Identifiable {
    public let id: String
    public let date: String
    public let sourceLocale: String
    public let sourceIdentitySha256: String
    public let defaultTargetLocale: String
    public let targets: [String: PageTarget]

    public func validate() throws {
        guard Validation.identifier(id), Validation.isoDate(date), sourceLocale == "en",
              Validation.sha256(sourceIdentitySha256), Validation.locale(defaultTargetLocale),
              !targets.isEmpty, targets.count <= 16, targets[defaultTargetLocale] != nil
        else { throw CatalogError.invalid("多语言页面来源、日期或默认语言无效") }
        for (locale, target) in targets {
            guard Validation.locale(locale) else { throw CatalogError.invalid("目标语言代码无效") }
            try target.validate(pageID: id, locale: locale)
        }
    }

    public var publishedTargets: [(locale: String, target: PageTarget)] {
        targets.filter { $0.value.contentStatus == "human_reviewed" }
            .sorted { $0.key.localizedStandardCompare($1.key) == .orderedAscending }
            .map { (locale: $0.key, target: $0.value) }
    }
}

public struct PageTarget: Codable, Sendable, Equatable {
    public let releasePackageUrl: String
    public let releasePackageJsonSha256: String
    public let contentStatus: String
    public let audioStatus: String
    public let capabilities: [LanguageCapability]

    public func validate(pageID: String, locale: String) throws {
        let expected = "/releases/\(pageID)/\(locale).json"
        guard releasePackageUrl == expected, Validation.sha256(releasePackageJsonSha256),
              contentStatus == "human_reviewed", ["unavailable", "human_reviewed"].contains(audioStatus),
              capabilities.contains(.text), Set(capabilities.map(\.rawValue)).count == capabilities.count,
              (audioStatus == "human_reviewed") == capabilities.contains(.audio)
        else { throw CatalogError.invalid("目标语言发布引用或能力无效") }
    }

    public func packageURL(relativeTo baseURL: URL) throws -> URL {
        try secureURL(path: releasePackageUrl, baseURL: baseURL)
    }
}

public struct TargetLanguageReleasePackage: Codable, Sendable, Equatable {
    public static let supportedSchemaVersion = "sermon-target-language-release-package-v1"
    public let schemaVersion: String
    public let packageId: String
    public let pageId: String
    public let sourceLocale: String
    public let targetLocale: String
    public let targetLanguageCandidateJsonSha256: String
    public let targetLanguageAudioPackageJsonSha256: String?
    public let status: String
    public let contentStatus: String
    public let audioStatus: String
    public let interfaceLocale: String
    public let contentLocale: String
    public let audioLocale: String?
    public let assets: [ReleaseAsset]
    public let httpVerification: ReleaseAcceptance
    public let deviceAcceptance: ReleaseAcceptance
    public let venueAcceptance: ReleaseAcceptance
    public let issues: [JSONValue]

    public static func decode(_ data: Data) throws -> Self {
        let value = try JSONDecoder().decode(Self.self, from: data)
        try value.validate()
        return value
    }

    public func validate() throws {
        guard schemaVersion == Self.supportedSchemaVersion, Validation.identifier(packageId),
              Validation.identifier(pageId), sourceLocale == "en", Validation.locale(targetLocale),
              Validation.sha256(targetLanguageCandidateJsonSha256), status == "published_http_verified",
              contentStatus == "human_reviewed", interfaceLocale == targetLocale,
              contentLocale == targetLocale, httpVerification.status == "pass", issues.isEmpty,
              !assets.isEmpty
        else { throw CatalogError.invalid("目标语言发布包状态或绑定无效") }
        let assetKeys = assets.map { "\($0.role.rawValue):\($0.path)" }
        guard Set(assetKeys).count == assetKeys.count else { throw CatalogError.invalid("发布资产重复") }
        for asset in assets { try asset.validate() }
        if audioStatus == "unavailable" {
            guard targetLanguageAudioPackageJsonSha256.map(Validation.sha256) ?? true, audioLocale == nil,
                  !assets.contains(where: { $0.role == .audio })
            else { throw CatalogError.invalid("无音频语言暴露了音频资产") }
        } else {
            guard audioStatus == "human_reviewed", audioLocale == targetLocale,
                  targetLanguageAudioPackageJsonSha256.map(Validation.sha256) == true,
                  assets.contains(where: { $0.role == .audio })
            else { throw CatalogError.invalid("音频语言或审核状态无效") }
        }
        guard assets.contains(where: { $0.role == .page }) else { throw CatalogError.invalid("发布包缺少语言页面") }
    }

    public func pageURL(relativeTo baseURL: URL) throws -> URL {
        guard let page = assets.first(where: { $0.role == .page }) else { throw CatalogError.invalid("发布包缺少语言页面") }
        return try secureURL(path: page.path, baseURL: baseURL)
    }
}

public struct ReleaseAsset: Codable, Sendable, Equatable {
    public enum Role: String, Codable, Sendable { case catalog, content, audio, captions, download, page, other }
    public let role: Role
    public let path: String
    public let sha256: String

    fileprivate func validate() throws {
        guard Validation.sha256(sha256), path.hasPrefix("/"), !path.hasPrefix("//"),
              !path.split(separator: "/").contains(".."), URLComponents(string: path)?.scheme == nil
        else { throw CatalogError.invalid("发布资产路径或哈希无效") }
    }
}

public struct ReleaseAcceptance: Codable, Sendable, Equatable {
    public let status: String
    public let evidenceSha256: String?
}

private func secureURL(path: String, baseURL: URL) throws -> URL {
    guard Validation.httpsURL(baseURL.absoluteString), path.hasPrefix("/"), !path.hasPrefix("//"),
          !path.split(separator: "/").contains(".."), var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false)
    else { throw CatalogError.invalid("发布地址无效") }
    components.path = path
    components.query = nil
    components.fragment = nil
    guard let result = components.url, result.host == baseURL.host else { throw CatalogError.invalid("发布地址无效") }
    return result
}

extension Validation {
    static func locale(_ value: String) -> Bool {
        value.range(of: "^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$", options: .regularExpression) != nil
    }
}
