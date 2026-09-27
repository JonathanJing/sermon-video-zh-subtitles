import Foundation

public enum LanguageCapability: String, Codable, CaseIterable, Sendable {
    case text, captions, audio, download, alignment
}

public struct MultilingualCatalog: Codable, Sendable, Equatable {
    public static let supportedSchemaVersion = "sermon-multilingual-catalog-v2"
    public static let dualScriptSchemaVersion = "sermon-multilingual-catalog-v3"
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
        guard [Self.supportedSchemaVersion, Self.dualScriptSchemaVersion].contains(schemaVersion) else {
            throw CatalogError.invalid("不支持的多语言目录版本")
        }
        guard !pages.isEmpty, pages.count <= 104 else { throw CatalogError.invalid("多语言目录页数无效") }
        guard Set(pages.map(\.id)).count == pages.count else { throw CatalogError.invalid("多语言页面 ID 重复") }
        guard pages.contains(where: { $0.id == defaultPageId }) else { throw CatalogError.invalid("默认多语言页面不存在") }
        for page in pages { try page.validate(catalogSchemaVersion: schemaVersion) }
    }
}

public struct MultilingualPage: Codable, Sendable, Equatable, Identifiable {
    public let id: String
    public let title: String?
    public let date: String
    public let sourceLocale: String
    public let sourceIdentitySha256: String
    public let sourceMediaSha256: String?
    public let defaultTargetLocale: String
    public let targets: [String: PageTarget]

    public func validate(catalogSchemaVersion: String = MultilingualCatalog.supportedSchemaVersion) throws {
        guard Validation.identifier(id), Validation.isoDate(date), sourceLocale == "en",
              Validation.sha256(sourceIdentitySha256), Validation.locale(defaultTargetLocale),
              sourceMediaSha256.map(Validation.sha256) ?? true,
              !targets.isEmpty, targets.count <= 16, targets[defaultTargetLocale] != nil
        else { throw CatalogError.invalid("多语言页面来源、日期或默认语言无效") }
        if catalogSchemaVersion == MultilingualCatalog.dualScriptSchemaVersion {
            guard let title, !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                  title.count <= 180 else { throw CatalogError.invalid("双稿页面缺少有效标题") }
        }
        for (locale, target) in targets {
            guard Validation.locale(locale) else { throw CatalogError.invalid("目标语言代码无效") }
            try target.validate(pageID: id, locale: locale, catalogSchemaVersion: catalogSchemaVersion)
            if let binding = target.audioFingerprint {
                guard sourceMediaSha256 == binding.sourceSha256 else {
                    throw CatalogError.invalid("多语言页面声音指纹来源不符")
                }
            }
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
    public let audioFingerprint: PublishedFingerprintBinding?

    public func validate(pageID: String, locale: String,
                         catalogSchemaVersion: String = MultilingualCatalog.supportedSchemaVersion) throws {
        let directory = catalogSchemaVersion == MultilingualCatalog.dualScriptSchemaVersion ? "releases-v2" : "releases"
        let expected = "/\(directory)/\(pageID)/\(locale).json"
        guard releasePackageUrl == expected, Validation.sha256(releasePackageJsonSha256),
              contentStatus == "human_reviewed", ["unavailable", "human_reviewed"].contains(audioStatus),
              capabilities.contains(.text), Set(capabilities.map(\.rawValue)).count == capabilities.count,
              (audioStatus == "human_reviewed") == capabilities.contains(.audio),
              (audioFingerprint != nil) == capabilities.contains(.alignment)
        else { throw CatalogError.invalid("目标语言发布引用或能力无效") }
        if let audioFingerprint {
            try audioFingerprint.validate()
            guard audioFingerprint.pageId == pageID, audioStatus == "human_reviewed" else {
                throw CatalogError.invalid("目标语言声音指纹与页面不符")
            }
        }
    }

    public func packageURL(relativeTo baseURL: URL) throws -> URL {
        try secureURL(path: releasePackageUrl, baseURL: baseURL)
    }
}

public struct TargetLanguageReleasePackage: Codable, Sendable, Equatable {
    public static let supportedSchemaVersion = "sermon-target-language-release-package-v1"
    public static let dualScriptSchemaVersion = "sermon-target-language-release-package-v2"
    public let schemaVersion: String
    public let packageId: String
    public let pageId: String
    public let sourceLocale: String
    public let targetLocale: String
    public let targetLanguageCandidateJsonSha256: String
    public let spokenTargetLanguageCandidateJsonSha256: String?
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

    public static func decode(_ data: Data, allowDevCandidate: Bool = false) throws -> Self {
        let value = try JSONDecoder().decode(Self.self, from: data)
        try value.validate(allowDevCandidate: allowDevCandidate)
        return value
    }

    public func validate(allowDevCandidate: Bool = false) throws {
        guard [Self.supportedSchemaVersion, Self.dualScriptSchemaVersion].contains(schemaVersion),
              Validation.identifier(packageId),
              Validation.identifier(pageId), sourceLocale == "en", Validation.locale(targetLocale),
              Validation.sha256(targetLanguageCandidateJsonSha256),
              contentStatus == "human_reviewed", interfaceLocale == targetLocale,
              contentLocale == targetLocale, issues.isEmpty,
              !assets.isEmpty
        else { throw CatalogError.invalid("目标语言发布包状态或绑定无效") }
        if schemaVersion == Self.dualScriptSchemaVersion {
            guard spokenTargetLanguageCandidateJsonSha256.map(Validation.sha256) == true else {
                throw CatalogError.invalid("双稿发布包缺少短口播候选绑定")
            }
            let required = [
                ReleaseAsset.Role.page: "/pages/\(pageId)/\(targetLocale)/index.html",
                .content: "/content/\(pageId)/\(targetLocale).json",
                .captions: "/captions/\(pageId)/\(targetLocale).json",
            ]
            for (role, path) in required {
                guard assets.filter({ $0.role == role }).map(\.path) == [path] else {
                    throw CatalogError.invalid("双稿发布资产路径与语言不符")
                }
            }
            if audioStatus == "human_reviewed" {
                guard assets.filter({ $0.role == .audio }).map(\.path) == ["/media/\(pageId)/\(targetLocale).mp3"] else {
                    throw CatalogError.invalid("双稿音轨路径与语言不符")
                }
            }
        } else if spokenTargetLanguageCandidateJsonSha256 != nil {
            throw CatalogError.invalid("单稿发布包包含短口播绑定")
        }
        let published = status == "published_http_verified" && httpVerification.status == "pass"
        let devCandidate = allowDevCandidate && schemaVersion == Self.supportedSchemaVersion
            && status == "candidate" && httpVerification.status == "not_run"
        guard published || devCandidate else { throw CatalogError.invalid("目标语言发布包尚未通过所需发布状态") }
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
        if published {
            guard assets.contains(where: { $0.role == .page }) else { throw CatalogError.invalid("发布包缺少语言页面") }
        } else {
            guard assets.contains(where: { $0.role == .content &&
                $0.path == "/content/\(pageId)/\(targetLocale).json" })
            else { throw CatalogError.invalid("Dev 候选包缺少语言内容") }
        }
    }

    public func pageURL(relativeTo baseURL: URL) throws -> URL {
        guard let page = assets.first(where: { $0.role == .page }) else { throw CatalogError.invalid("发布包缺少语言页面") }
        return try secureURL(path: page.path, baseURL: baseURL)
    }

    public func contentURL(relativeTo baseURL: URL) throws -> URL {
        guard status == "candidate", let content = assets.first(where: { $0.role == .content }),
              content.path == "/content/\(pageId)/\(targetLocale).json"
        else { throw CatalogError.invalid("Dev 候选包缺少语言内容") }
        return try secureURL(path: content.path, baseURL: baseURL)
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
