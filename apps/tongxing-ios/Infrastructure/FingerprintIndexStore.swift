import CryptoKit
import Foundation
import TongxingCore

/// Same-origin, content-addressed reference indexes only. Captured microphone
/// samples never reach this store or its network requests.
public actor FingerprintIndexStore {
    private let directory: URL
    private let baseURL: URL
    private let session: URLSession
    private let maximumBytes: Int64 = 8 * 1024 * 1024

    public init(directory: URL, baseURL: URL, session: URLSession = .shared) {
        self.directory = directory; self.baseURL = baseURL; self.session = session
    }

    public func load(alignment: SermonAudioAlignment, week: SermonWeek, track: SermonTrack) async throws -> FingerprintIndex {
        try Task.checkCancellation()
        try alignment.validate(week: week, track: track)
        try ContentOrigin.validateHTTPS(baseURL)
        let url = try alignment.indexURL(relativeTo: baseURL)
        guard ContentOrigin.isSame(baseURL, url) else { throw ContentStorageError.invalidURL }
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let cached = directory.appendingPathComponent(alignment.fingerprintSha256 + "-fingerprint.json")
        if FileManager.default.fileExists(atPath: cached.path) {
            do { return try validateFile(cached, alignment: alignment) }
            catch {
                if Task.isCancelled || error is CancellationError { throw CancellationError() }
                // Remove only this invalid hash-addressed entry; other weeks stay
                // available, and a failed replacement never admits partial data.
                try? FileManager.default.removeItem(at: cached)
            }
        }
        let temporary = directory.appendingPathComponent("fingerprint-\(UUID().uuidString).part")
        defer { try? FileManager.default.removeItem(at: temporary) }
        let transfer = HTTPFileTransfer(session: session, url: url, temporaryURL: temporary, maximumBytes: maximumBytes)
        let receipt = try await transfer.run()
        try Task.checkCancellation()
        guard receipt.sha256 == alignment.fingerprintSha256 else { throw ContentStorageError.checksumMismatch }
        let index = try validateFile(temporary, alignment: alignment)
        try Task.checkCancellation()
        // Preserve the exact downloaded bytes so subsequent loads verify the
        // same published digest. Atomic replacement also handles concurrent loads.
        try Data(contentsOf: temporary).write(to: cached, options: .atomic)
        return index
    }

    public func loadPublished(binding: PublishedFingerprintBinding, week: SermonWeek, track: SermonTrack) async throws -> PublishedFingerprintIndex {
        try Task.checkCancellation()
        try binding.validate(week: week, track: track)
        return try await loadPublishedIndex(binding: binding)
    }

    public func loadPublished(binding: PublishedFingerprintBinding, page: MultilingualPage,
                              locale: String, trackSha256: String,
                              durationSeconds: Double) async throws -> PublishedFingerprintIndex {
        try Task.checkCancellation()
        try binding.validate(page: page, locale: locale, trackSha256: trackSha256,
                             durationSeconds: durationSeconds)
        return try await loadPublishedIndex(binding: binding)
    }

    private func loadPublishedIndex(binding: PublishedFingerprintBinding) async throws -> PublishedFingerprintIndex {
        try ContentOrigin.validateHTTPS(baseURL)
        let url = try binding.indexURL(relativeTo: baseURL)
        guard ContentOrigin.isSame(baseURL, url) else { throw ContentStorageError.invalidURL }
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let cached = directory.appendingPathComponent(binding.indexSha256 + "-landmarks.json")
        if FileManager.default.fileExists(atPath: cached.path) {
            do { return try validatePublishedFile(cached, binding: binding) }
            catch {
                if Task.isCancelled || error is CancellationError { throw CancellationError() }
                try? FileManager.default.removeItem(at: cached)
            }
        }
        let temporary = directory.appendingPathComponent("landmarks-\(UUID().uuidString).part")
        defer { try? FileManager.default.removeItem(at: temporary) }
        let receipt = try await HTTPFileTransfer(session: session, url: url, temporaryURL: temporary,
                                                 maximumBytes: maximumBytes).run()
        try Task.checkCancellation()
        guard receipt.sha256 == binding.indexSha256 else { throw ContentStorageError.checksumMismatch }
        let index = try validatePublishedFile(temporary, binding: binding)
        try Task.checkCancellation()
        try Data(contentsOf: temporary).write(to: cached, options: .atomic)
        return index
    }

    private func validatePublishedFile(_ url: URL, binding: PublishedFingerprintBinding) throws -> PublishedFingerprintIndex {
        try Task.checkCancellation()
        let size = try url.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
        guard size > 0 else { throw ContentStorageError.emptyFile }
        guard size <= maximumBytes else { throw ContentStorageError.tooLarge(limit: maximumBytes) }
        let bytes = try Data(contentsOf: url)
        guard bytes.count <= maximumBytes else { throw ContentStorageError.tooLarge(limit: maximumBytes) }
        let digest = SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined()
        guard digest == binding.indexSha256 else { throw ContentStorageError.checksumMismatch }
        let index = try PublishedFingerprintIndex.decode(bytes)
        try index.validate(binding: binding)
        try Task.checkCancellation()
        return index
    }

    private func validateFile(_ url: URL, alignment: SermonAudioAlignment) throws -> FingerprintIndex {
        try Task.checkCancellation()
        let size = try url.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
        guard size > 0 else { throw ContentStorageError.emptyFile }
        guard size <= maximumBytes else { throw ContentStorageError.tooLarge(limit: maximumBytes) }
        let bytes = try Data(contentsOf: url)
        guard bytes.count <= maximumBytes else { throw ContentStorageError.tooLarge(limit: maximumBytes) }
        let digest = SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined()
        guard digest == alignment.fingerprintSha256 else { throw ContentStorageError.checksumMismatch }
        let index = try FingerprintIndex.decode(bytes)
        try index.validate(alignment: alignment)
        try Task.checkCancellation()
        return index
    }
}
