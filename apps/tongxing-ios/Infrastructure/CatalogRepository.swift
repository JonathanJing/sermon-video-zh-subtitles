import Foundation
import TongxingCore

public struct CatalogLoadResult: Sendable {
    public enum Source: String, Sendable { case network, cache }
    public let catalog: WeeklyCatalog
    public let source: Source
    public let warning: String?
}

public actor CatalogRepository {
    private let catalogURL: URL
    private let cacheDirectory: URL
    private let session: URLSession
    private let maximumBytes: Int64

    public init(catalogURL: URL, cacheDirectory: URL, session: URLSession = .shared,
                maximumBytes: Int64 = 5 * 1_024 * 1_024) {
        self.catalogURL = catalogURL
        self.cacheDirectory = cacheDirectory
        self.session = session
        self.maximumBytes = maximumBytes
    }

    public func load() async throws -> CatalogLoadResult {
        try ContentOrigin.validateHTTPS(catalogURL)
        guard catalogURL.path == "/weekly.json", catalogURL.query == nil else {
            throw ContentStorageError.invalidURL
        }
        try FileManager.default.createDirectory(at: cacheDirectory, withIntermediateDirectories: true)
        let temporary = cacheDirectory.appendingPathComponent("catalog-\(UUID().uuidString).part")
        defer { try? FileManager.default.removeItem(at: temporary) }
        do {
            let transfer = HTTPFileTransfer(session: session, url: catalogURL,
                                            temporaryURL: temporary, maximumBytes: maximumBytes)
            _ = try await transfer.run()
            try Task.checkCancellation()
            let data = try Data(contentsOf: temporary)
            let catalog = try validatedCatalog(data)
            // Save the exact published JSON only after all catalog/media checks.
            try data.write(to: cacheURL, options: .atomic)
            return CatalogLoadResult(catalog: catalog, source: .network, warning: nil)
        } catch {
            if Task.isCancelled || error is CancellationError { throw CancellationError() }
            let originalError = error
            guard FileManager.default.fileExists(atPath: cacheURL.path) else { throw originalError }
            let data = try readBoundedCache()
            let catalog = try validatedCatalog(data)
            return CatalogLoadResult(catalog: catalog, source: .cache,
                warning: "暂时无法更新目录，正在使用此前保存的内容。")
        }
    }

    private var cacheURL: URL { cacheDirectory.appendingPathComponent("weekly.json") }

    private func readBoundedCache() throws -> Data {
        let size = try cacheURL.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
        guard size <= maximumBytes else { throw ContentStorageError.tooLarge(limit: maximumBytes) }
        return try Data(contentsOf: cacheURL)
    }

    private func validatedCatalog(_ data: Data) throws -> WeeklyCatalog {
        let catalog = try WeeklyCatalog.decode(data)
        for week in catalog.weeks {
            for track in week.tracks {
                let mediaURL = try track.mediaURL(relativeTo: catalogURL)
                guard ContentOrigin.isSame(catalogURL, mediaURL) else { throw ContentStorageError.invalidURL }
            }
        }
        return catalog
    }
}
