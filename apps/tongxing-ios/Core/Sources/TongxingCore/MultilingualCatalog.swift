import Foundation

public enum LanguageCapability: String, Codable, CaseIterable, Sendable {
    case text, captions, audio, download, alignment
}

public struct MultilingualCatalog: Codable, Sendable, Equatable {
    public static let supportedSchemaVersion = "sermon-multilingual-catalog-v2"
    public static let dualScriptSchemaVersion = "sermon-multilingual-catalog-v3"
    public static let productionSchemaVersion = dualScriptSchemaVersion
    public let schemaVersion: String
    public let generatedAt: String
    public let defaultPageId: String
    public let pages: [MultilingualPage]

    public var defaultPage: MultilingualPage { pages.first { $0.id == defaultPageId }! }

    public static func decode(_ data: Data, allowDevCandidates: Bool = false) throws -> Self {
        let value = try JSONDecoder().decode(Self.self, from: data)
        // Validate the entire wire catalog before projecting the visible locales.
        // A machine-reviewed locale never becomes a published target.
        try value.validate(allowDevCandidates: true)
        if allowDevCandidates { return value }
        let pages = value.pages.compactMap { page -> MultilingualPage? in
            guard page.diagnosticOnly != true, page.simulationOnly != true else { return nil }
            let targets = page.targets.filter { $0.value.contentStatus == "human_reviewed" && $0.value.diagnosticOnly != true && $0.value.simulationOnly != true }
            guard !targets.isEmpty else { return nil }
            let locale = targets[page.defaultTargetLocale] != nil ? page.defaultTargetLocale : targets.keys.sorted().first!
            return MultilingualPage(id: page.id, title: page.title, date: page.date,
                sourceLocale: page.sourceLocale, sourceIdentitySha256: page.sourceIdentitySha256,
                sourceMediaSha256: page.sourceMediaSha256, mediaType: page.mediaType, displayCategory: page.displayCategory, defaultTargetLocale: locale, targets: targets,
                diagnosticOnly: page.diagnosticOnly, simulationOnly: page.simulationOnly)
        }
        let projected = Self(schemaVersion: value.schemaVersion, generatedAt: value.generatedAt,
            defaultPageId: pages.contains { $0.id == value.defaultPageId } ? value.defaultPageId : (pages.first?.id ?? ""),
            pages: pages)
        try projected.validate()
        return projected
    }

    /// Retain independently verified human locales after the repository checks
    /// immutable release bytes and publication status. This creates no approval.
    public func retainingHumanLocales(_ localesByPage: [String: Set<String>]) throws -> Self {
        let selected = pages.compactMap { page -> MultilingualPage? in
            guard page.diagnosticOnly != true, page.simulationOnly != true else { return nil }
            let targets = page.targets.filter { locale, target in
                localesByPage[page.id]?.contains(locale) == true && target.contentStatus == "human_reviewed"
                    && target.diagnosticOnly != true && target.simulationOnly != true
            }
            guard !targets.isEmpty else { return nil }
            let locale = targets[page.defaultTargetLocale] != nil ? page.defaultTargetLocale : targets.keys.sorted().first!
            return MultilingualPage(id: page.id, title: page.title, date: page.date,
                sourceLocale: page.sourceLocale, sourceIdentitySha256: page.sourceIdentitySha256,
                sourceMediaSha256: page.sourceMediaSha256, mediaType: page.mediaType, displayCategory: page.displayCategory, defaultTargetLocale: locale, targets: targets,
                diagnosticOnly: page.diagnosticOnly, simulationOnly: page.simulationOnly)
        }
        let result = Self(schemaVersion: schemaVersion, generatedAt: generatedAt,
            defaultPageId: selected.contains { $0.id == defaultPageId } ? defaultPageId : (selected.first?.id ?? ""), pages: selected)
        try result.validate()
        return result
    }

    public func validate(allowDevCandidates: Bool = false) throws {
        guard [Self.supportedSchemaVersion, Self.dualScriptSchemaVersion].contains(schemaVersion) else {
            throw CatalogError.invalid("不支持的多语言目录版本")
        }
        guard !pages.isEmpty, pages.count <= 104 else { throw CatalogError.invalid("多语言目录页数无效") }
        guard Set(pages.map(\.id)).count == pages.count else { throw CatalogError.invalid("多语言页面 ID 重复") }
        guard pages.contains(where: { $0.id == defaultPageId }) else { throw CatalogError.invalid("默认多语言页面不存在") }
        for page in pages { try page.validate(catalogSchemaVersion: schemaVersion, allowDevCandidates: allowDevCandidates) }
    }
}

public struct MultilingualPage: Codable, Sendable, Equatable, Identifiable {
    /// Source category only, not a statement of publication or review approval.
    /// Older catalogs retain confirmed archive IDs and explicit podcast type.
    public var displayEdition: String? { displayEdition(locale: "zh-Hans") }

    public func displayEdition(locale: String) -> String? {
        guard diagnosticOnly != true, simulationOnly != true else { return nil }
        if let displayCategory { return displayCategory.label(locale: locale) }
        if mediaType == "podcast" { return "播客" }
        switch id {
        case "2026-09-27-weekend-sermon-drive-530", "resi-20261004-69ba7a66":
            return "正式播放版"
        default:
            return nil
        }
    }

    public let id: String
    public let title: String?
    public let date: String
    public let sourceLocale: String
    public let sourceIdentitySha256: String
    public let sourceMediaSha256: String?
    public let mediaType: String?
    public var displayCategory: PageDisplayCategory? = nil
    public let defaultTargetLocale: String
    public let targets: [String: PageTarget]
    public let diagnosticOnly: Bool?
    public let simulationOnly: Bool?

    public func validate(catalogSchemaVersion: String = MultilingualCatalog.supportedSchemaVersion,
                         allowDevCandidates: Bool = false) throws {
        guard allowDevCandidates || (diagnosticOnly != true && simulationOnly != true) else {
            throw CatalogError.invalid("开发页面需要明确的 Dev 上下文")
        }
        guard Validation.identifier(id), Validation.isoDate(date), sourceLocale == "en",
              Validation.sha256(sourceIdentitySha256), Validation.locale(defaultTargetLocale),
              sourceMediaSha256.map(Validation.sha256) ?? true,
              mediaType.map({ ["podcast", "video"].contains($0) }) ?? true,
              title.map({ !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }) ?? true,
              !targets.isEmpty, targets.count <= 16, targets[defaultTargetLocale] != nil
        else { throw CatalogError.invalid("多语言页面来源、日期或默认语言无效") }
        if catalogSchemaVersion == MultilingualCatalog.dualScriptSchemaVersion {
            guard let title, !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                  title.count <= 180 else { throw CatalogError.invalid("双稿页面缺少有效标题") }
        }
        try displayCategory?.validate()
        for (locale, target) in targets {
            guard Validation.locale(locale) else { throw CatalogError.invalid("目标语言代码无效") }
            try target.validate(pageID: id, locale: locale, catalogSchemaVersion: catalogSchemaVersion,
                                allowDevCandidates: allowDevCandidates)
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

/// Versioned catalog presentation metadata; independent of review and playback.
public struct PageDisplayCategory: Codable, Sendable, Equatable {
    public static let supportedSchemaVersion = "sermon-page-display-category-v1"
    public let schemaVersion: String
    public let labels: [String: String]

    public func validate() throws {
        guard schemaVersion == Self.supportedSchemaVersion,
              (1...16).contains(labels.count), labels["en"] != nil,
              labels.allSatisfy({ locale, label in
                  Validation.locale(locale) && (1...48).contains(label.unicodeScalars.count)
                      && !label.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                      && !label.unicodeScalars.contains(where: { $0.value < 32 || (127...159).contains($0.value) || [0x2028, 0x2029].contains($0.value) })
              }) else { throw CatalogError.invalid("页面类别显示元数据无效") }
    }

    /// Interface locale, never audio/content locale. English is required fallback.
    public func label(locale: String) -> String? {
        let requested = locale.replacingOccurrences(of: "_", with: "-")
        if let exact = labels[requested] { return exact }
        if ["zh-CN", "zh-SG", "zh-Hans"].contains(requested) || requested.hasPrefix("zh-Hans-") {
            for alias in ["zh-Hans", "zh-CN", "zh-SG", "zh"] {
                if let value = labels[alias] { return value }
            }
        }
        let base = requested.split(separator: "-").first.map(String.init) ?? requested
        return labels[base] ?? labels["en"]
    }
}

public struct PageTarget: Codable, Sendable, Equatable {
    public let releasePackageUrl: String
    public let releasePackageJsonSha256: String
    public let contentStatus: String
    public let audioStatus: String
    public let capabilities: [LanguageCapability]
    public let audioFingerprint: PublishedFingerprintBinding?
    public let diagnosticOnly: Bool?
    public let simulationOnly: Bool?

    public func validate(pageID: String, locale: String,
                         catalogSchemaVersion: String = MultilingualCatalog.supportedSchemaVersion,
                         allowDevCandidates: Bool = false) throws {
        guard allowDevCandidates || (diagnosticOnly != true && simulationOnly != true) else {
            throw CatalogError.invalid("开发语言需要明确的 Dev 上下文")
        }
        let directory = catalogSchemaVersion == MultilingualCatalog.dualScriptSchemaVersion ? "releases-v2" : "releases"
        let expected = "/\(directory)/\(pageID)/\(locale).json"
        guard releasePackageUrl == expected, Validation.sha256(releasePackageJsonSha256),
              (contentStatus == "human_reviewed" || (allowDevCandidates && contentStatus == "machine_reviewed")),
              ["unavailable", "human_reviewed"].contains(audioStatus),
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
    public static let fourProductSchemaVersion = "sermon-target-language-release-package-v3"
    public static let productionSchemaVersion = dualScriptSchemaVersion
    public let schemaVersion: String
    public let packageId: String
    public let pageId: String
    public let sourceLocale: String
    public let targetLocale: String
    public let targetLanguageCandidateJsonSha256: String
    public let spokenTargetLanguageCandidateJsonSha256: String?
    public let targetLanguageAudioPackageJsonSha256: String?
    public let audioHumanReviewReceiptJsonSha256: String?
    public let englishSourcePackageJsonSha256: String?
    public let sourceIdentity: ReviewedReleaseSourceIdentity?
    public let fourProducts: ReviewedAppProducts?
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
        let published = status == "published_http_verified" && httpVerification.status == "pass"
        let devCandidate = allowDevCandidate && status == "candidate" && httpVerification.status == "not_run"
        let machineCandidate = devCandidate && schemaVersion == Self.dualScriptSchemaVersion && contentStatus == "machine_reviewed"
        guard [Self.supportedSchemaVersion, Self.dualScriptSchemaVersion, Self.fourProductSchemaVersion].contains(schemaVersion),
              !packageId.isEmpty, // Opaque schema ID; producer suffix can exceed the page ID limit.
              Validation.identifier(pageId), sourceLocale == "en", Validation.locale(targetLocale),
              Validation.sha256(targetLanguageCandidateJsonSha256),
              (contentStatus == "human_reviewed" || machineCandidate),
              (interfaceLocale == targetLocale || (machineCandidate && interfaceLocale == "zh-Hans")),
              (!machineCandidate || audioHumanReviewReceiptJsonSha256.map(Validation.sha256) == true),
              contentLocale == targetLocale, issues.isEmpty,
              !assets.isEmpty
        else { throw CatalogError.invalid("目标语言发布包状态或绑定无效") }
        if schemaVersion == Self.dualScriptSchemaVersion || schemaVersion == Self.fourProductSchemaVersion {
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
                let audioPaths = assets.filter { $0.role == .audio }.map(\.path)
                let acceptedExtensions = devCandidate ? ["mp3", "wav", "m4a"] : ["mp3"]
                let acceptedAudioPaths = acceptedExtensions.map { "/media/\(pageId)/\(targetLocale).\($0)" }
                guard audioPaths.count == 1, acceptedAudioPaths.contains(audioPaths[0]) else {
                    throw CatalogError.invalid("双稿音轨路径与语言不符")
                }
            }
        } else if spokenTargetLanguageCandidateJsonSha256 != nil {
            throw CatalogError.invalid("单稿发布包包含短口播绑定")
        }
        if schemaVersion == Self.fourProductSchemaVersion {
            guard let sourceIdentity, let fourProducts,
                  englishSourcePackageJsonSha256 == fourProducts.sourcePackageSha256,
                  targetLanguageCandidateJsonSha256 == fourProducts.textCandidateSha256,
                  targetLanguageAudioPackageJsonSha256 == fourProducts.audioPackageSha256,
                  contentStatus == "human_reviewed"
            else { throw CatalogError.invalid("四产物发布缺少来源或文字音频绑定") }
            try sourceIdentity.validate()
            try fourProducts.validate()
            for (role, name) in [(ReleaseAsset.Role.outline, "outline"), (.meditation, "meditation"), (.productManifest, "products")] {
                guard assets.filter({ $0.role == role }).map(\.path) == ["/study/\(pageId)/\(targetLocale)/\(name).json"] else {
                    throw CatalogError.invalid("四产物学习资源缺失或路径错误")
                }
            }
        } else if fourProducts != nil || sourceIdentity != nil || englishSourcePackageJsonSha256 != nil ||
                    assets.contains(where: { [.outline, .meditation, .productManifest].contains($0.role) }) {
            throw CatalogError.invalid("旧版本发布包不能声明四产物资格")
        }
        guard published || devCandidate else { throw CatalogError.invalid("目标语言发布包尚未通过所需发布状态") }
        for acceptance in [httpVerification, deviceAcceptance, venueAcceptance] {
            try acceptance.validate()
        }
        if devCandidate {
            guard deviceAcceptance.status == "not_run", venueAcceptance.status == "not_run" else {
                throw CatalogError.invalid("Dev 候选不能声明设备或现场验收")
            }
        }
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
    public enum Role: String, Codable, Sendable {
        case catalog, content, audio, captions, download, page, other, outline, meditation
        case productManifest = "product_manifest"
    }
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

    fileprivate func validate() throws {
        guard ["not_run", "pass", "fail"].contains(status),
              status == "not_run" ? evidenceSha256 == nil : evidenceSha256.map(Validation.sha256) == true
        else { throw CatalogError.invalid("发布验收状态缺少匹配证据") }
    }
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
