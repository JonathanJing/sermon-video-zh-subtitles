import CryptoKit
import Foundation
import ImageIO
import TongxingCore

public struct WeeklyAnnouncementLoadResult: Sendable {
    public enum Source: String, Sendable { case network, cache }
    public let catalog: WeeklyAnnouncementCatalog
    public let source: Source
}

public struct VerifiedWeeklyPoster: Sendable {
    public let data: Data
    public let localURL: URL
}

public actor WeeklyAnnouncementRepository {
    private let origin: URL
    private let cacheDirectory: URL
    private let session: URLSession
    private let maximumSidecarBytes: Int64 = 512 * 1024

    public init(origin: URL, cacheDirectory: URL, session: URLSession = .shared) {
        self.origin = origin; self.cacheDirectory = cacheDirectory; self.session = session
    }

    public func load(catalog: MultilingualCatalog) async throws -> WeeklyAnnouncementLoadResult {
        try ContentOrigin.validateHTTPS(origin)
        try FileManager.default.createDirectory(at: cacheDirectory, withIntermediateDirectories: true)
        let cache = cacheDirectory.appendingPathComponent("weekly-announcements-v1.json")
        do {
            let data = try await download(origin.appendingPathComponent("weekly-announcements-v1.json"), limit: maximumSidecarBytes)
            let decoded = try WeeklyAnnouncementCatalog.decode(data)
            try Task.checkCancellation()
            try data.write(to: cache, options: .atomic)
            return .init(catalog: admitted(decoded, catalog: catalog), source: .network)
        } catch {
            if Task.isCancelled || error is CancellationError { throw CancellationError() }
            // A missing sidecar means this server has intentionally disabled the feature.
            if error as? ContentStorageError == .httpStatus(404) {
                try? FileManager.default.removeItem(at: cache)
                throw error
            }
            let decoded = try WeeklyAnnouncementCatalog.decode(readBounded(cache, limit: maximumSidecarBytes))
            return .init(catalog: admitted(decoded, catalog: catalog), source: .cache)
        }
    }

    public func poster(for announcement: WeeklyAnnouncement) async throws -> VerifiedWeeklyPoster {
        try ContentOrigin.validateHTTPS(origin)
        try announcement.validate()
        let reference = announcement.poster
        let remote = URL(string: reference.url, relativeTo: origin)!.absoluteURL
        guard ContentOrigin.isSame(origin, remote) else { throw ContentStorageError.invalidURL }
        try FileManager.default.createDirectory(at: cacheDirectory, withIntermediateDirectories: true)
        let cache = cacheDirectory.appendingPathComponent(reference.sha256 + ".poster")
        if let data = try? readBounded(cache, limit: reference.bytes), (try? verify(data, reference: reference)) != nil {
            try Task.checkCancellation()
            return .init(data: data, localURL: cache)
        }
        let data = try await download(remote, limit: reference.bytes)
        try verify(data, reference: reference)
        try Task.checkCancellation()
        try data.write(to: cache, options: .atomic)
        return .init(data: data, localURL: cache)
    }

    private func admitted(_ sidecar: WeeklyAnnouncementCatalog, catalog: MultilingualCatalog) -> WeeklyAnnouncementCatalog {
        .init(announcements: sidecar.announcements.filter { (try? $0.matchedPage(in: catalog)) != nil })
    }

    private func verify(_ data: Data, reference: WeeklyPoster) throws {
        guard data.count == reference.bytes,
              SHA256.hash(data: data).map({ String(format: "%02x", $0) }).joined() == reference.sha256 else {
            throw ContentStorageError.checksumMismatch
        }
        guard let image = CGImageSourceCreateWithData(data as CFData, nil), CGImageSourceGetCount(image) == 1,
              let properties = CGImageSourceCopyPropertiesAtIndex(image, 0, nil) as? [CFString: Any],
              (properties[kCGImagePropertyPixelWidth] as? Int) == reference.width,
              (properties[kCGImagePropertyPixelHeight] as? Int) == reference.height else {
            throw ContentStorageError.invalidResponse
        }
    }

    private func download(_ url: URL, limit: Int64) async throws -> Data {
        guard ContentOrigin.isSame(origin, url) else { throw ContentStorageError.invalidURL }
        let temporary = cacheDirectory.appendingPathComponent("poster-transfer-\(UUID().uuidString).part")
        defer { try? FileManager.default.removeItem(at: temporary) }
        _ = try await HTTPFileTransfer(session: session, url: url, temporaryURL: temporary, maximumBytes: limit).run()
        try Task.checkCancellation()
        return try readBounded(temporary, limit: limit)
    }

    private func readBounded(_ url: URL, limit: Int64) throws -> Data {
        let size = try url.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
        guard size > 0, size <= limit else { throw ContentStorageError.tooLarge(limit: limit) }
        return try Data(contentsOf: url)
    }
}
