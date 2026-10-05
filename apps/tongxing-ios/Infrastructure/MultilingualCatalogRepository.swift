import CryptoKit
import Foundation
import TongxingCore

public struct MultilingualCatalogLoadResult: Sendable {
    public enum Source: String, Sendable { case network, cache }
    public let catalog: MultilingualCatalog
    public let source: Source
    public let warning: String?
}

public struct VerifiedLanguagePage: Sendable {
    public let html: String
    public let baseURL: URL
}

public struct VerifiedLanguageAudio: Sendable {
    public let localURL: URL
    public let pageID: String
    public let locale: String
    public let sourceIdentitySha256: String
    public let sha256: String
}

public actor MultilingualCatalogRepository {
    private let origin: URL
    private let cacheDirectory: URL
    private let session: URLSession
    private let allowDevCandidate: Bool
    private let maximumCatalogBytes: Int64
    private let maximumPackageBytes: Int64
    private let publicationCheckSeconds: Double
    private let maximumPageBytes: Int64 = 4 * 1_024 * 1_024
    private let maximumAudioBytes: Int64 = 512 * 1_024 * 1_024

    public init(origin: URL, cacheDirectory: URL, session: URLSession = .shared,
                maximumCatalogBytes: Int64 = 2 * 1_024 * 1_024,
                maximumPackageBytes: Int64 = 1 * 1_024 * 1_024,
                allowDevCandidate: Bool = false, publicationCheckSeconds: Double = 30) {
        self.origin = origin
        self.cacheDirectory = cacheDirectory
        self.session = session
        self.maximumCatalogBytes = maximumCatalogBytes
        self.maximumPackageBytes = maximumPackageBytes
        self.publicationCheckSeconds = publicationCheckSeconds.isFinite && publicationCheckSeconds > 0
            ? min(publicationCheckSeconds, 30) : 30
        self.allowDevCandidate = allowDevCandidate && origin.scheme == "https"
            && origin.host == "ai-for-god-sermon-audio-dev.web.app"
            && (origin.port == nil || origin.port == 443) && origin.user == nil && origin.password == nil
    }

    public func loadCatalog() async throws -> MultilingualCatalogLoadResult {
        try FileManager.default.createDirectory(at: cacheDirectory, withIntermediateDirectories: true)
        do {
            return try await loadNetworkCatalog(named: "multilingual-v3.json",
                                                schemaVersion: MultilingualCatalog.dualScriptSchemaVersion)
        } catch ContentStorageError.httpStatus(404) {
            // A missing v3 catalog means this site still serves the v1 release protocol.
            do {
                return try await loadNetworkCatalog(named: "multilingual-v2.json",
                                                    schemaVersion: MultilingualCatalog.supportedSchemaVersion)
            } catch {
                if Task.isCancelled || error is CancellationError { throw CancellationError() }
                return try await loadCachedCatalog(preferredNames: ["multilingual-v2.json", "multilingual-v3.json"],
                                             originalError: error)
            }
        } catch {
            if Task.isCancelled || error is CancellationError { throw CancellationError() }
            return try await loadCachedCatalog(preferredNames: ["multilingual-v3.json", "multilingual-v2.json"],
                                         originalError: error)
        }
    }

    private func loadNetworkCatalog(named name: String, schemaVersion: String) async throws -> MultilingualCatalogLoadResult {
        let url = origin.appendingPathComponent(name)
        guard url.path == "/\(name)", url.query == nil else { throw ContentStorageError.invalidURL }
        try ContentOrigin.validateHTTPS(url)
        let (data, _) = try await download(url: url, maximumBytes: maximumCatalogBytes)
        let catalog = try MultilingualCatalog.decode(data, allowDevCandidates: allowDevCandidate)
        guard catalog.schemaVersion == schemaVersion else { throw ContentStorageError.invalidResponse }
        try validatePackageURLs(catalog)
        let visible = try await publicationProjection(catalog, useNetwork: true)
        try data.write(to: catalogCacheURL(named: name), options: .atomic)
        return .init(catalog: visible, source: .network, warning: nil)
    }

    private func loadCachedCatalog(preferredNames: [String], originalError: Error) async throws -> MultilingualCatalogLoadResult {
        for name in preferredNames {
            try Task.checkCancellation()
            let path = catalogCacheURL(named: name)
            guard FileManager.default.fileExists(atPath: path.path) else { continue }
            do {
                let data = try readBounded(path, maximumBytes: maximumCatalogBytes)
                let catalog = try MultilingualCatalog.decode(data, allowDevCandidates: allowDevCandidate)
                let expected = name == "multilingual-v3.json"
                    ? MultilingualCatalog.dualScriptSchemaVersion : MultilingualCatalog.supportedSchemaVersion
                guard catalog.schemaVersion == expected else { throw ContentStorageError.invalidResponse }
                try validatePackageURLs(catalog)
                let visible = try await publicationProjection(catalog, useNetwork: false)
                return .init(catalog: visible, source: .cache,
                             warning: "暂时无法更新多语言目录，正在使用此前保存的语言列表。")
            } catch {
                if Task.isCancelled || error is CancellationError { throw CancellationError() }
                // A damaged preferred cache must not prevent a valid older catalog from loading.
            }
        }
        try Task.checkCancellation()
        throw originalError
    }

    // Catalog contentStatus alone cannot distinguish a human-reviewed candidate
    // from a published locale. Production therefore checks the hash-bound package
    // before exposing a locale in the chooser. Valid immutable caches avoid GETs.
    private func publicationProjection(_ catalog: MultilingualCatalog, useNetwork: Bool) async throws -> MultilingualCatalog {
        if allowDevCandidate { return catalog }
        var admitted: [String: Set<String>] = [:]
        if !useNetwork {
            for page in catalog.pages {
                for locale in page.targets.keys.sorted() {
                    try Task.checkCancellation()
                    if (try? cachedPackage(page: page, locale: locale)) != nil {
                        admitted[page.id, default: []].insert(locale)
                    }
                }
            }
        } else {
            var pending: [(page: MultilingualPage, locale: String)] = []
            for page in catalog.pages {
                for locale in page.targets.keys.sorted() {
                    try Task.checkCancellation()
                    if let visible = try? cachedReleaseVisibility(page: page, locale: locale) {
                        if visible { admitted[page.id, default: []].insert(locale) }
                    } else { pending.append((page, locale)) }
                }
            }
            if !pending.isEmpty {
                // Each locale reports independently, so a stalled sibling cannot
                // discard already verified locales at the catalog deadline.
                await withTaskGroup(of: (Int, Bool).self) { group in
                    group.addTask { [publicationCheckSeconds] in
                        try? await Task.sleep(nanoseconds: UInt64(publicationCheckSeconds * 1_000_000_000))
                        return (-1, false)
                    }
                    var next = 0, completed = 0, timedOut = false
                    func enqueue(_ index: Int) {
                        let item = pending[index]
                        group.addTask {
                            do {
                                _ = try await self.loadRelease(page: item.page, locale: item.locale)
                                return (index, !Task.isCancelled)
                            } catch { return (index, false) }
                        }
                    }
                    while next < min(4, pending.count) { enqueue(next); next += 1 }
                    for await (index, accepted) in group {
                        if index == -1 { timedOut = true; group.cancelAll(); continue }
                        completed += 1
                        if accepted { admitted[pending[index].page.id, default: []].insert(pending[index].locale) }
                        if completed == pending.count { group.cancelAll() }
                        if !timedOut && next < pending.count { enqueue(next); next += 1 }
                    }
                    group.cancelAll()
                }
            }
        }
        try Task.checkCancellation()
        return try catalog.retainingHumanLocales(admitted)
    }

    private func cachedPackage(page: MultilingualPage, locale: String) throws -> TargetLanguageReleasePackage {
        guard let target = page.targets[locale] else { throw ContentStorageError.invalidDownloadReference }
        let bytes = try readBounded(packageCacheURL(pageID: page.id, locale: locale), maximumBytes: maximumPackageBytes)
        guard SHA256.hash(data: bytes).map({ String(format: "%02x", $0) }).joined() == target.releasePackageJsonSha256 else {
            throw ContentStorageError.checksumMismatch
        }
        return try validatedPackage(bytes, page: page, locale: locale)
    }

    // A valid immutable candidate cache is a negative admission result. Reuse
    // its hash-bound status without fetching the same rejected bytes repeatedly.
    private func cachedReleaseVisibility(page: MultilingualPage, locale: String) throws -> Bool {
        guard let target = page.targets[locale] else { throw ContentStorageError.invalidDownloadReference }
        let bytes = try readBounded(packageCacheURL(pageID: page.id, locale: locale), maximumBytes: maximumPackageBytes)
        guard SHA256.hash(data: bytes).map({ String(format: "%02x", $0) }).joined() == target.releasePackageJsonSha256 else {
            throw ContentStorageError.checksumMismatch
        }
        if isBoundCandidate(bytes, page: page, locale: locale) { return false }
        _ = try validatedPackage(bytes, page: page, locale: locale)
        return true
    }

    private func isBoundCandidate(_ bytes: Data, page: MultilingualPage, locale: String) -> Bool {
        guard let package = try? TargetLanguageReleasePackage.decode(bytes, allowDevCandidate: true),
              package.status == "candidate", package.pageId == page.id, package.targetLocale == locale,
              let target = page.targets[locale], package.contentStatus == target.contentStatus,
              package.audioStatus == target.audioStatus else { return false }
        let expected = target.releasePackageUrl.hasPrefix("/releases-v2/")
            ? TargetLanguageReleasePackage.dualScriptSchemaVersion : TargetLanguageReleasePackage.supportedSchemaVersion
        return (package.schemaVersion == expected ||
            (expected == TargetLanguageReleasePackage.dualScriptSchemaVersion && package.schemaVersion == TargetLanguageReleasePackage.fourProductSchemaVersion)) &&
            (package.fourProducts == nil || (package.englishSourcePackageJsonSha256 == page.sourceIdentitySha256 &&
                package.sourceIdentity?.mediaSha256 == page.sourceMediaSha256))
    }

    public func loadRelease(page: MultilingualPage, locale: String) async throws -> TargetLanguageReleasePackage {
        guard allowDevCandidate || (page.diagnosticOnly != true && page.simulationOnly != true),
              let target = page.targets[locale],
              allowDevCandidate || (target.contentStatus == "human_reviewed" && target.diagnosticOnly != true && target.simulationOnly != true)
        else { throw ContentStorageError.invalidDownloadReference }
        try target.validate(pageID: page.id, locale: locale,
            catalogSchemaVersion: target.releasePackageUrl.hasPrefix("/releases-v2/")
                ? MultilingualCatalog.dualScriptSchemaVersion : MultilingualCatalog.supportedSchemaVersion,
            allowDevCandidates: allowDevCandidate)
        let url = try target.packageURL(relativeTo: origin)
        let cacheURL = packageCacheURL(pageID: page.id, locale: locale)
        do {
            let (data, receivedHash) = try await download(url: url, maximumBytes: maximumPackageBytes)
            guard receivedHash == target.releasePackageJsonSha256 else { throw ContentStorageError.checksumMismatch }
            let package: TargetLanguageReleasePackage
            do { package = try validatedPackage(data, page: page, locale: locale) }
            catch {
                if !allowDevCandidate && isBoundCandidate(data, page: page, locale: locale) {
                    try FileManager.default.createDirectory(at: cacheURL.deletingLastPathComponent(), withIntermediateDirectories: true)
                    try data.write(to: cacheURL, options: .atomic)
                }
                throw error
            }
            try FileManager.default.createDirectory(at: cacheURL.deletingLastPathComponent(), withIntermediateDirectories: true)
            try data.write(to: cacheURL, options: .atomic)
            return package
        } catch {
            if Task.isCancelled || error is CancellationError { throw CancellationError() }
            guard FileManager.default.fileExists(atPath: cacheURL.path) else { throw error }
            let data = try readBounded(cacheURL, maximumBytes: maximumPackageBytes)
            let package = try validatedPackage(data, page: page, locale: locale)
            let temporary = cacheDirectory.appendingPathComponent("hash-\(UUID().uuidString).part")
            defer { try? FileManager.default.removeItem(at: temporary) }
            try data.write(to: temporary)
            let receipt = try await hashLocalFile(temporary, maximumBytes: maximumPackageBytes)
            guard receipt == target.releasePackageJsonSha256 else { throw ContentStorageError.checksumMismatch }
            return package
        }
    }

    /// Only pages whose bytes match the verified release package may be shown.
    /// Recheck cached bytes before every offline use.
    public func loadPage(for package: TargetLanguageReleasePackage) async throws -> VerifiedLanguagePage {
        try package.validate(allowDevCandidate: allowDevCandidate)
        if package.status == "candidate" {
            guard allowDevCandidate else { throw ContentStorageError.invalidDownloadReference }
            if package.schemaVersion != TargetLanguageReleasePackage.fourProductSchemaVersion {
                return try await loadDevContentPage(for: package)
            }
        }
        guard let asset = package.assets.first(where: { $0.role == .page }) else {
            throw ContentStorageError.invalidDownloadReference
        }
        let url = try package.pageURL(relativeTo: origin)
        guard ContentOrigin.isSame(origin, url) else { throw ContentStorageError.invalidURL }
        let cacheURL = cacheDirectory.appendingPathComponent("Pages", isDirectory: true)
            .appendingPathComponent("\(asset.sha256).html")
        let data: Data
        do {
            let (downloaded, receivedHash) = try await download(url: url, maximumBytes: maximumPageBytes)
            guard receivedHash == asset.sha256 else { throw ContentStorageError.checksumMismatch }
            try FileManager.default.createDirectory(at: cacheURL.deletingLastPathComponent(), withIntermediateDirectories: true)
            try downloaded.write(to: cacheURL, options: .atomic)
            data = downloaded
        } catch {
            if Task.isCancelled || error is CancellationError { throw CancellationError() }
            guard FileManager.default.fileExists(atPath: cacheURL.path) else { throw error }
            let cached = try readBounded(cacheURL, maximumBytes: maximumPageBytes)
            guard SHA256.hash(data: cached).map({ String(format: "%02x", $0) }).joined() == asset.sha256 else {
                throw ContentStorageError.checksumMismatch
            }
            data = cached
        }
        guard let html = String(data: data, encoding: .utf8) else { throw ContentStorageError.invalidResponse }
        if [TargetLanguageReleasePackage.dualScriptSchemaVersion, TargetLanguageReleasePackage.fourProductSchemaVersion].contains(package.schemaVersion) {
            let lower = html.lowercased()
            guard lower.contains("<html"), lower.contains("<body"),
                  !["<script", "<link", "<iframe", "<video", "<audio"].contains(where: lower.contains) else {
                throw ContentStorageError.invalidResponse
            }
        }
        if let studies = try await loadStudies(for: package) {
            guard studies.outline.isDisplayed(in: html), studies.meditation.isDisplayed(in: html) else {
                throw ContentStorageError.invalidResponse
            }
        }
        return VerifiedLanguagePage(html: html, baseURL: url)
    }

    private func loadDevContentPage(for package: TargetLanguageReleasePackage) async throws -> VerifiedLanguagePage {
        guard let asset = package.assets.first(where: { $0.role == .content }) else {
            throw ContentStorageError.invalidDownloadReference
        }
        let url = try package.contentURL(relativeTo: origin)
        guard ContentOrigin.isSame(origin, url) else { throw ContentStorageError.invalidURL }
        let cacheURL = cacheDirectory.appendingPathComponent("Pages", isDirectory: true)
            .appendingPathComponent("\(asset.sha256).json")
        let data: Data
        do {
            let (downloaded, receivedHash) = try await download(url: url, maximumBytes: maximumPageBytes)
            guard receivedHash == asset.sha256 else { throw ContentStorageError.checksumMismatch }
            _ = try FormalDevContentPage.decode(downloaded, package: package)
            try FileManager.default.createDirectory(at: cacheURL.deletingLastPathComponent(), withIntermediateDirectories: true)
            try downloaded.write(to: cacheURL, options: .atomic)
            data = downloaded
        } catch {
            if Task.isCancelled || error is CancellationError { throw CancellationError() }
            guard FileManager.default.fileExists(atPath: cacheURL.path) else { throw error }
            let cached = try readBounded(cacheURL, maximumBytes: maximumPageBytes)
            guard SHA256.hash(data: cached).map({ String(format: "%02x", $0) }).joined() == asset.sha256 else {
                throw ContentStorageError.checksumMismatch
            }
            data = cached
        }
        let studies = try await loadStudies(for: package)
        return VerifiedLanguagePage(html: try FormalDevContentPage.decode(data, package: package).renderedHTML(studies: studies),
                                    baseURL: url)
    }

    public func loadStudies(for package: TargetLanguageReleasePackage) async throws -> ReviewedStudyResources? {
        try package.validate(allowDevCandidate: allowDevCandidate)
        guard package.schemaVersion == TargetLanguageReleasePackage.fourProductSchemaVersion else { return nil }
        var resources: [ReleaseAsset.Role: Data] = [:]
        for role in [ReleaseAsset.Role.outline, .meditation, .productManifest] {
            guard let asset = package.assets.first(where: { $0.role == role }),
                  let url = URL(string: asset.path, relativeTo: origin)?.absoluteURL,
                  ContentOrigin.isSame(origin, url) else { throw ContentStorageError.invalidDownloadReference }
            let cache = cacheDirectory.appendingPathComponent("Study", isDirectory: true)
                .appendingPathComponent("\(asset.sha256).json")
            let data: Data
            do {
                let (downloaded, hash) = try await download(url: url, maximumBytes: maximumPageBytes)
                guard hash == asset.sha256 else { throw ContentStorageError.checksumMismatch }
                data = downloaded
            } catch {
                if Task.isCancelled || error is CancellationError { throw CancellationError() }
                guard FileManager.default.fileExists(atPath: cache.path) else { throw error }
                data = try readBounded(cache, maximumBytes: maximumPageBytes)
                guard SHA256.hash(data: data).map({ String(format: "%02x", $0) }).joined() == asset.sha256 else {
                    throw ContentStorageError.checksumMismatch
                }
            }
            // Validate semantic identity before admitting bytes to the offline cache.
            if role == .productManifest { try ReviewedStudyResources.validateManifest(data, package: package) }
            else { _ = try ReviewedStudyArtifact.decode(data, kind: role.rawValue, package: package) }
            try FileManager.default.createDirectory(at: cache.deletingLastPathComponent(), withIntermediateDirectories: true)
            try data.write(to: cache, options: .atomic)
            resources[role] = data
        }
        guard let outline = resources[.outline], let meditation = resources[.meditation] else {
            throw ContentStorageError.invalidResponse
        }
        return ReviewedStudyResources(outline: try ReviewedStudyArtifact.decode(outline, kind: "outline", package: package),
            meditation: try ReviewedStudyArtifact.decode(meditation, kind: "meditation", package: package))
    }

    /// Download only the reviewed, same-locale audio declared by this page's
    /// verified release. Never hand AVPlayer network bytes or an unchecked cache.
    public func loadAudio(for package: TargetLanguageReleasePackage,
                          page: MultilingualPage) async throws -> VerifiedLanguageAudio {
        try package.validate(allowDevCandidate: allowDevCandidate)
        guard allowDevCandidate || (page.diagnosticOnly != true && page.simulationOnly != true) else {
            throw ContentStorageError.invalidDownloadReference
        }
        guard package.pageId == page.id, package.audioStatus == "human_reviewed",
              package.audioLocale == package.targetLocale,
              let target = page.targets[package.targetLocale], target.audioStatus == "human_reviewed",
              target.contentStatus == package.contentStatus,
              allowDevCandidate || (target.contentStatus == "human_reviewed" && target.diagnosticOnly != true && target.simulationOnly != true) else {
            throw ContentStorageError.invalidDownloadReference
        }
        let assets = package.assets.filter { $0.role == .audio }
        guard assets.count == 1, let asset = assets.first else { throw ContentStorageError.invalidDownloadReference }
        let filename = String(asset.path.dropFirst("/media/".count))
        let expectedPrefix = "\(page.id)/\(package.targetLocale)."
        guard asset.path.hasPrefix("/media/"), filename.hasPrefix(expectedPrefix),
              ["wav", "mp3", "m4a"].contains(String(filename.dropFirst(expectedPrefix.count))),
              let source = URL(string: asset.path, relativeTo: origin)?.absoluteURL,
              ContentOrigin.isSame(origin, source) else { throw ContentStorageError.invalidURL }
        let extensionName = (filename as NSString).pathExtension
        var audioCacheDirectory = cacheDirectory.appendingPathComponent("Audio", isDirectory: true)
        let cache = audioCacheDirectory.appendingPathComponent("\(asset.sha256).\(extensionName)")
        try FileManager.default.createDirectory(at: audioCacheDirectory, withIntermediateDirectories: true)
        var backupValues = URLResourceValues()
        backupValues.isExcludedFromBackup = true
        try audioCacheDirectory.setResourceValues(backupValues)
        if FileManager.default.fileExists(atPath: cache.path),
           (try? verifyAudioFile(cache, sha256: asset.sha256)) != nil {
            return .init(localURL: cache, pageID: page.id, locale: package.targetLocale,
                         sourceIdentitySha256: page.sourceIdentitySha256, sha256: asset.sha256)
        }
        let temporary = cacheDirectory.appendingPathComponent("Audio/\(UUID().uuidString).part")
        defer { try? FileManager.default.removeItem(at: temporary) }
        let receipt = try await HTTPFileTransfer(session: session, url: source, temporaryURL: temporary,
                                                  maximumBytes: maximumAudioBytes).run()
        guard receipt.sha256 == asset.sha256 else { throw ContentStorageError.checksumMismatch }
        try verifyAudioFile(temporary, sha256: asset.sha256)
        try Task.checkCancellation()
        if FileManager.default.fileExists(atPath: cache.path) {
            _ = try FileManager.default.replaceItemAt(cache, withItemAt: temporary)
        } else {
            try FileManager.default.moveItem(at: temporary, to: cache)
        }
        try verifyAudioFile(cache, sha256: asset.sha256)
        return .init(localURL: cache, pageID: page.id, locale: package.targetLocale,
                     sourceIdentitySha256: page.sourceIdentitySha256, sha256: asset.sha256)
    }

    /// Load both approved scripts without turning full reading text into spoken
    /// subtitles. Every cached asset is rehashed before use.
    public func loadPublishedTranscript(for package: TargetLanguageReleasePackage,
                                        page: MultilingualPage) async throws -> VerifiedPublishedTranscript {
        let verified = try await loadRelease(page: page, locale: package.targetLocale)
        guard verified == package, [TargetLanguageReleasePackage.dualScriptSchemaVersion, TargetLanguageReleasePackage.fourProductSchemaVersion].contains(package.schemaVersion),
              let content = package.assets.first(where: { $0.role == .content }),
              let captions = package.assets.first(where: { $0.role == .captions }) else {
            throw ContentStorageError.invalidDownloadReference
        }
        let contentData = try await loadTranscriptAsset(content)
        let captionData = try await loadTranscriptAsset(captions)
        let referenceURL = origin.appendingPathComponent("english-reference/\(page.id).json")
        var englishData: Data?
        do {
            englishData = try await download(url: referenceURL, maximumBytes: maximumPageBytes).0
        } catch {
            if Task.isCancelled || error is CancellationError { throw CancellationError() }
            // This supplementary reference has no catalog hash, so do not trust
            // an offline cache as approved English. Base approved scripts work.
        }
        return try VerifiedPublishedTranscript.decode(content: contentData, captions: captionData,
            englishReference: englishData, package: package, page: page, allowDevCandidate: allowDevCandidate)
    }

    private func loadTranscriptAsset(_ asset: ReleaseAsset) async throws -> Data {
        guard let url = URL(string: asset.path, relativeTo: origin)?.absoluteURL,
              ContentOrigin.isSame(origin, url) else { throw ContentStorageError.invalidURL }
        let cache = cacheDirectory.appendingPathComponent("Transcripts", isDirectory: true)
            .appendingPathComponent("\(asset.sha256).json")
        do {
            let (data, hash) = try await download(url: url, maximumBytes: maximumPageBytes)
            guard hash == asset.sha256 else { throw ContentStorageError.checksumMismatch }
            try FileManager.default.createDirectory(at: cache.deletingLastPathComponent(), withIntermediateDirectories: true)
            try data.write(to: cache, options: .atomic)
            return data
        } catch {
            if Task.isCancelled || error is CancellationError { throw CancellationError() }
            guard FileManager.default.fileExists(atPath: cache.path) else { throw error }
            let data = try readBounded(cache, maximumBytes: maximumPageBytes)
            guard SHA256.hash(data: data).map({ String(format: "%02x", $0) }).joined() == asset.sha256 else {
                throw ContentStorageError.checksumMismatch
            }
            return data
        }
    }

    private func verifyAudioFile(_ url: URL, sha256: String) throws {
        let size = try url.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
        guard size > 0, size <= maximumAudioBytes else { throw ContentStorageError.invalidDownloadReference }
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        var digest = SHA256()
        while let chunk = try handle.read(upToCount: 1_024 * 1_024), !chunk.isEmpty {
            digest.update(data: chunk)
        }
        guard digest.finalize().map({ String(format: "%02x", $0) }).joined() == sha256 else {
            throw ContentStorageError.checksumMismatch
        }
    }

    private func catalogCacheURL(named name: String) -> URL { cacheDirectory.appendingPathComponent(name) }

    private func packageCacheURL(pageID: String, locale: String) -> URL {
        cacheDirectory.appendingPathComponent("Releases", isDirectory: true)
            .appendingPathComponent(pageID, isDirectory: true).appendingPathComponent("\(locale).json")
    }

    private func download(url: URL, maximumBytes: Int64) async throws -> (Data, String) {
        let temporary = cacheDirectory.appendingPathComponent("transfer-\(UUID().uuidString).part")
        defer { try? FileManager.default.removeItem(at: temporary) }
        let transfer = HTTPFileTransfer(session: session, url: url, temporaryURL: temporary, maximumBytes: maximumBytes)
        let receipt = try await transfer.run()
        return (try Data(contentsOf: temporary), receipt.sha256)
    }

    private func hashLocalFile(_ url: URL, maximumBytes: Int64) async throws -> String {
        let scratch = cacheDirectory.appendingPathComponent("rehash-\(UUID().uuidString).part")
        defer { try? FileManager.default.removeItem(at: scratch) }
        let data = try readBounded(url, maximumBytes: maximumBytes)
        try data.write(to: scratch)
        // The cache was size-bounded above. Reuse CryptoKit through the transfer
        // receipt is unnecessary and would require a network request.
        return SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    private func readBounded(_ url: URL, maximumBytes: Int64) throws -> Data {
        let size = try url.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
        guard size <= maximumBytes else { throw ContentStorageError.tooLarge(limit: maximumBytes) }
        return try Data(contentsOf: url)
    }

    private func validatePackageURLs(_ catalog: MultilingualCatalog) throws {
        for page in catalog.pages {
            for target in page.targets.values {
                let url = try target.packageURL(relativeTo: origin)
                guard ContentOrigin.isSame(origin, url) else { throw ContentStorageError.invalidURL }
            }
        }
    }

    private func validatedPackage(_ data: Data, page: MultilingualPage, locale: String) throws -> TargetLanguageReleasePackage {
        let package = try TargetLanguageReleasePackage.decode(data, allowDevCandidate: allowDevCandidate)
        guard package.pageId == page.id, package.targetLocale == locale,
              let target = page.targets[locale],
              package.contentStatus == target.contentStatus, package.audioStatus == target.audioStatus
        else { throw ContentStorageError.invalidDownloadReference }
        let expectedSchema = target.releasePackageUrl.hasPrefix("/releases-v2/")
            ? TargetLanguageReleasePackage.dualScriptSchemaVersion : TargetLanguageReleasePackage.supportedSchemaVersion
        guard package.schemaVersion == expectedSchema ||
                (expectedSchema == TargetLanguageReleasePackage.dualScriptSchemaVersion &&
                 package.schemaVersion == TargetLanguageReleasePackage.fourProductSchemaVersion) else {
            throw ContentStorageError.invalidDownloadReference
        }
        if package.fourProducts != nil {
            guard package.englishSourcePackageJsonSha256 == page.sourceIdentitySha256,
                  package.sourceIdentity?.mediaSha256 == page.sourceMediaSha256 else {
                throw ContentStorageError.invalidDownloadReference
            }
        }
        let pageURL = try package.status == "candidate"
            ? package.contentURL(relativeTo: origin) : package.pageURL(relativeTo: origin)
        guard ContentOrigin.isSame(origin, pageURL) else { throw ContentStorageError.invalidURL }
        return package
    }
}
