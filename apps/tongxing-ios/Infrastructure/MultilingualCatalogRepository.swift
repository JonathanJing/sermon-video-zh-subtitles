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

public actor MultilingualCatalogRepository {
    private let origin: URL
    private let cacheDirectory: URL
    private let session: URLSession
    private let maximumCatalogBytes: Int64
    private let maximumPackageBytes: Int64
    private let maximumPageBytes: Int64 = 4 * 1_024 * 1_024

    public init(origin: URL, cacheDirectory: URL, session: URLSession = .shared,
                maximumCatalogBytes: Int64 = 2 * 1_024 * 1_024,
                maximumPackageBytes: Int64 = 1 * 1_024 * 1_024) {
        self.origin = origin
        self.cacheDirectory = cacheDirectory
        self.session = session
        self.maximumCatalogBytes = maximumCatalogBytes
        self.maximumPackageBytes = maximumPackageBytes
    }

    public func loadCatalog() async throws -> MultilingualCatalogLoadResult {
        let url = origin.appendingPathComponent("multilingual.json")
        guard url.path == "/multilingual.json", url.query == nil else { throw ContentStorageError.invalidURL }
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

    /// Render only the page bytes named by the verified release package. A
    /// cached page is reusable only while its hash still matches that package.
    public func loadPage(for package: TargetLanguageReleasePackage) async throws -> VerifiedLanguagePage {
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

    private var catalogCacheURL: URL { cacheDirectory.appendingPathComponent("multilingual.json") }

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
        let package = try TargetLanguageReleasePackage.decode(data)
        guard package.pageId == page.id, package.targetLocale == locale,
              let target = page.targets[locale],
              package.contentStatus == target.contentStatus, package.audioStatus == target.audioStatus
        else { throw ContentStorageError.invalidDownloadReference }
        let pageURL = try package.pageURL(relativeTo: origin)
        guard ContentOrigin.isSame(origin, pageURL) else { throw ContentStorageError.invalidURL }
        return package
    }
}
