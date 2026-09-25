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
    private let maximumPageBytes: Int64 = 4 * 1_024 * 1_024
    private let maximumAudioBytes: Int64 = 512 * 1_024 * 1_024

    public init(origin: URL, cacheDirectory: URL, session: URLSession = .shared,
                maximumCatalogBytes: Int64 = 2 * 1_024 * 1_024,
                maximumPackageBytes: Int64 = 1 * 1_024 * 1_024,
                allowDevCandidate: Bool = false) {
        self.origin = origin
        self.cacheDirectory = cacheDirectory
        self.session = session
        self.maximumCatalogBytes = maximumCatalogBytes
        self.maximumPackageBytes = maximumPackageBytes
        self.allowDevCandidate = allowDevCandidate && origin.host == "ai-for-god-sermon-audio-dev.web.app"
    }

    public func loadCatalog() async throws -> MultilingualCatalogLoadResult {
        let url = origin.appendingPathComponent("multilingual-v2.json")
        guard url.path == "/multilingual-v2.json", url.query == nil else { throw ContentStorageError.invalidURL }
        try ContentOrigin.validateHTTPS(url)
        try FileManager.default.createDirectory(at: cacheDirectory, withIntermediateDirectories: true)
        do {
            let (data, _) = try await download(url: url, maximumBytes: maximumCatalogBytes)
            let catalog = try MultilingualCatalog.decode(data)
            try validatePackageURLs(catalog)
            try data.write(to: catalogCacheURL, options: .atomic)
            return .init(catalog: catalog, source: .network, warning: nil)
        } catch {
            if Task.isCancelled || error is CancellationError { throw CancellationError() }
            guard FileManager.default.fileExists(atPath: catalogCacheURL.path) else { throw error }
            let data = try readBounded(catalogCacheURL, maximumBytes: maximumCatalogBytes)
            let catalog = try MultilingualCatalog.decode(data)
            try validatePackageURLs(catalog)
            return .init(catalog: catalog, source: .cache,
                         warning: "暂时无法更新多语言目录，正在使用此前保存的语言列表。")
        }
    }

    public func loadRelease(page: MultilingualPage, locale: String) async throws -> TargetLanguageReleasePackage {
        guard let target = page.targets[locale] else { throw ContentStorageError.invalidDownloadReference }
        let url = try target.packageURL(relativeTo: origin)
        let cacheURL = packageCacheURL(pageID: page.id, locale: locale)
        do {
            let (data, receivedHash) = try await download(url: url, maximumBytes: maximumPackageBytes)
            guard receivedHash == target.releasePackageJsonSha256 else { throw ContentStorageError.checksumMismatch }
            let package = try validatedPackage(data, page: page, locale: locale)
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
        if package.status == "candidate" {
            guard allowDevCandidate else { throw ContentStorageError.invalidDownloadReference }
            return try await loadDevContentPage(for: package)
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
        return VerifiedLanguagePage(html: try FormalDevContentPage.decode(data, package: package).html,
                                    baseURL: url)
    }

    /// Download only the reviewed, same-locale audio declared by this page's
    /// verified release. Never hand AVPlayer network bytes or an unchecked cache.
    public func loadAudio(for package: TargetLanguageReleasePackage,
                          page: MultilingualPage) async throws -> VerifiedLanguageAudio {
        guard package.pageId == page.id, package.audioStatus == "human_reviewed",
              package.audioLocale == package.targetLocale,
              page.targets[package.targetLocale]?.audioStatus == "human_reviewed" else {
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

    private var catalogCacheURL: URL { cacheDirectory.appendingPathComponent("multilingual-v2.json") }

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
        let pageURL = try package.status == "candidate"
            ? package.contentURL(relativeTo: origin) : package.pageURL(relativeTo: origin)
        guard ContentOrigin.isSame(origin, pageURL) else { throw ContentStorageError.invalidURL }
        return package
    }
}
