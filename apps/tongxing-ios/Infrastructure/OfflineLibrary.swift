import CryptoKit
import Foundation
import TongxingCore

/// Verified, content-addressed foreground downloads. Track references are separate
/// from shared audio bytes, so deleting one track preserves another track's copy.
public actor OfflineLibrary {
    private struct Reference: Codable {
        let version: Int
        let trackID: String
        let sha256: String
    }

    private struct Transfer {
        let id: UUID
        let task: Task<URL, Error>
        var waiters: [UUID: String]
    }

    private let directory: URL
    private let baseURL: URL
    private let session: URLSession
    private let maxAudioBytes: Int64
    private var transfers: [String: Transfer] = [:]
    private var removalVersions: [String: Int] = [:]

    public init(directory: URL, baseURL: URL, session: URLSession = .shared,
                maxAudioBytes: Int64 = 512 * 1_024 * 1_024) {
        self.directory = directory
        self.baseURL = baseURL
        self.session = session
        self.maxAudioBytes = maxAudioBytes
    }

    /// A URL is returned only after verifying the entire file against this track's
    /// published SHA-256. A damaged reference/file throws instead of appearing ready.
    public func offlineFile(for track: SermonTrack) throws -> URL? {
        let hash = try validatedHash(for: track)
        let reference = referenceURL(for: track, hash: hash)
        guard FileManager.default.fileExists(atPath: reference.path) else { return nil }
        let metadata = try reference.resourceValues(forKeys: [.fileSizeKey])
        guard let size = metadata.fileSize, size < 4_096 else {
            throw ContentStorageError.invalidDownloadReference
        }
        let record = try JSONDecoder().decode(Reference.self, from: Data(contentsOf: reference))
        guard record.version == 1, record.trackID == track.id, record.sha256 == hash else {
            throw ContentStorageError.invalidDownloadReference
        }
        let file = blobURL(hash)
        guard FileManager.default.fileExists(atPath: file.path) else {
            throw ContentStorageError.invalidDownloadReference
        }
        try Self.verify(file, expectedHash: hash, maximumBytes: maxAudioBytes)
        return file
    }

    /// Same-hash concurrent requests share one transfer. Cancelling one waiter
    /// preserves the transfer for other waiters; the final cancellation stops it.
    public func download(track: SermonTrack) async throws -> URL {
        try Task.checkCancellation()
        let hash = try validatedHash(for: track)
        try ContentOrigin.validateHTTPS(baseURL)
        let source = try track.mediaURL(relativeTo: baseURL)
        guard ContentOrigin.isSame(baseURL, source) else { throw ContentStorageError.invalidURL }
        try prepareDirectories()
        let key = referenceKey(trackID: track.id, hash: hash)
        let removalVersion = removalVersions[key, default: 0]
        let existing = blobURL(hash)
        if FileManager.default.fileExists(atPath: existing.path),
           (try? Self.verify(existing, expectedHash: hash, maximumBytes: maxAudioBytes)) != nil {
            try Task.checkCancellation()
            try saveReference(track: track, hash: hash)
            return existing
        }

        let waiter = UUID()
        if var transfer = transfers[hash] {
            transfer.waiters[waiter] = key
            transfers[hash] = transfer
        } else {
            let temporary = temporaryDirectory.appendingPathComponent("\(UUID().uuidString).part")
            let destination = blobURL(hash)
            let session = session
            let maximumBytes = maxAudioBytes
            let task = Task.detached {
                defer { try? FileManager.default.removeItem(at: temporary) }
                let transfer = HTTPFileTransfer(session: session, url: source,
                    temporaryURL: temporary, maximumBytes: maximumBytes)
                let receipt = try await transfer.run()
                try Task.checkCancellation()
                guard receipt.sha256 == hash else { throw ContentStorageError.checksumMismatch }
                // Verify the persisted bytes as well as the network stream, then
                // promote only the complete file on the same filesystem.
                try Self.verify(temporary, expectedHash: hash, maximumBytes: maximumBytes)
                try Task.checkCancellation()
                if FileManager.default.fileExists(atPath: destination.path) {
                    if (try? Self.verify(destination, expectedHash: hash, maximumBytes: maximumBytes)) != nil {
                        return destination
                    }
                    _ = try FileManager.default.replaceItemAt(destination, withItemAt: temporary)
                } else {
                    try FileManager.default.moveItem(at: temporary, to: destination)
                }
                return destination
            }
            transfers[hash] = Transfer(id: UUID(), task: task, waiters: [waiter: key])
        }
        guard let transfer = transfers[hash] else { throw CancellationError() }
        do {
            let result = try await withTaskCancellationHandler {
                try await transfer.task.value
            } onCancel: {
                Task { await self.releaseWaiter(waiter, hash: hash, transferID: transfer.id) }
            }
            try Task.checkCancellation()
            guard removalVersions[key, default: 0] == removalVersion else { throw CancellationError() }
            try saveReference(track: track, hash: hash)
            releaseWaiter(waiter, hash: hash, transferID: transfer.id)
            return result
        } catch {
            releaseWaiter(waiter, hash: hash, transferID: transfer.id)
            throw error
        }
    }

    /// Call only for an explicit user request to delete this track's download.
    public func removeDownload(for track: SermonTrack) throws {
        let hash = try validatedHash(for: track)
        let key = referenceKey(trackID: track.id, hash: hash)
        removalVersions[key, default: 0] += 1
        if let transfer = transfers[hash] {
            for (waiter, waiterKey) in transfer.waiters where waiterKey == key {
                releaseWaiter(waiter, hash: hash, transferID: transfer.id)
            }
        }
        let reference = referenceURL(for: track, hash: hash)
        if FileManager.default.fileExists(atPath: reference.path) {
            try FileManager.default.removeItem(at: reference)
        }
        // Another registered track or active download may still own these bytes.
        if try transfers[hash] == nil && !hasReference(to: hash) {
            let blob = blobURL(hash)
            if FileManager.default.fileExists(atPath: blob.path) {
                try FileManager.default.removeItem(at: blob)
            }
        }
    }

    private func releaseWaiter(_ waiter: UUID, hash: String, transferID: UUID) {
        guard var transfer = transfers[hash], transfer.id == transferID else { return }
        transfer.waiters.removeValue(forKey: waiter)
        if transfer.waiters.isEmpty {
            transfer.task.cancel()
            transfers.removeValue(forKey: hash)
        } else {
            transfers[hash] = transfer
        }
    }

    private var temporaryDirectory: URL { directory.appendingPathComponent("tmp", isDirectory: true) }
    private var blobDirectory: URL { directory.appendingPathComponent("audio", isDirectory: true) }
    private var referenceDirectory: URL { directory.appendingPathComponent("tracks", isDirectory: true) }

    private func prepareDirectories() throws {
        for folder in [directory, temporaryDirectory, blobDirectory, referenceDirectory] {
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            var folder = folder
            var values = URLResourceValues()
            values.isExcludedFromBackup = true
            try folder.setResourceValues(values)
        }
    }

    private func blobURL(_ hash: String) -> URL { blobDirectory.appendingPathComponent("\(hash).mp3") }

    private func referenceKey(trackID: String, hash: String) -> String {
        SHA256.hash(data: Data("\(trackID)\u{0}\(hash)".utf8)).map { String(format: "%02x", $0) }.joined()
    }

    private func referenceURL(for track: SermonTrack, hash: String) -> URL {
        referenceDirectory.appendingPathComponent(referenceKey(trackID: track.id, hash: hash) + ".json")
    }

    private func saveReference(track: SermonTrack, hash: String) throws {
        let reference = Reference(version: 1, trackID: track.id, sha256: hash)
        try JSONEncoder().encode(reference).write(to: referenceURL(for: track, hash: hash), options: .atomic)
    }

    private func hasReference(to hash: String) throws -> Bool {
        guard FileManager.default.fileExists(atPath: referenceDirectory.path) else { return false }
        for file in try FileManager.default.contentsOfDirectory(at: referenceDirectory,
                includingPropertiesForKeys: [.fileSizeKey]) where file.pathExtension == "json" {
            let size = try file.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
            // A malformed reference must not trigger deletion of potentially used
            // bytes. Repair is explicit, and offlineFile still rejects it.
            guard size < 4_096,
                  let record = try? JSONDecoder().decode(Reference.self, from: Data(contentsOf: file)) else {
                return true
            }
            if record.sha256 == hash { return true }
        }
        return false
    }

    private func validatedHash(for track: SermonTrack) throws -> String {
        try track.validate()
        let hash = track.sha256.lowercased()
        guard hash.count == 64, hash.utf8.allSatisfy({ (48...57).contains($0) || (97...102).contains($0) }) else {
            throw ContentStorageError.checksumMismatch
        }
        return hash
    }

    private static func verify(_ file: URL, expectedHash: String, maximumBytes: Int64) throws {
        let values = try file.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey])
        guard values.isRegularFile == true, values.isSymbolicLink != true else {
            throw ContentStorageError.invalidDownloadReference
        }
        guard let size = values.fileSize, size > 0 else { throw ContentStorageError.emptyFile }
        guard size <= maximumBytes else { throw ContentStorageError.tooLarge(limit: maximumBytes) }
        let handle = try FileHandle(forReadingFrom: file)
        defer { try? handle.close() }
        var digest = SHA256()
        var count: Int64 = 0
        while let data = try handle.read(upToCount: 256 * 1_024), !data.isEmpty {
            count += Int64(data.count)
            guard count <= maximumBytes else { throw ContentStorageError.tooLarge(limit: maximumBytes) }
            digest.update(data: data)
        }
        let actualHash = digest.finalize().map { String(format: "%02x", $0) }.joined()
        guard actualHash == expectedHash else { throw ContentStorageError.checksumMismatch }
    }
}
