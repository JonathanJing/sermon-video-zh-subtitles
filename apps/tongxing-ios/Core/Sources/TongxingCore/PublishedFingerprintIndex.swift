import Foundation

/// The current published web contract. It is intentionally separate from the
/// legacy native algorithm, despite both contracts naming spectral-landmarks-v1.
public struct PublishedFingerprintBinding: Codable, Sendable, Equatable {
    public let schemaVersion: String
    public let pageId: String
    public let sourceSha256: String
    public let trackSha256: String
    public let sourceStartSeconds: Double
    public let sourceEndSeconds: Double
    public let algorithmVersion: String
    public let captureSeconds: Double
    public let indexSha256: String
    public let indexUrl: String

    public func validate() throws {
        guard schemaVersion == "sermon-audio-fingerprint-binding-v1",
              algorithmVersion == "spectral-landmarks-v1", Validation.identifier(pageId),
              Validation.sha256(sourceSha256), Validation.sha256(trackSha256), Validation.sha256(indexSha256),
              sourceStartSeconds.isFinite, sourceStartSeconds >= 0, sourceEndSeconds.isFinite,
              (7...14_400).contains(sourceEndSeconds - sourceStartSeconds), captureSeconds == 10,
              indexUrl == "/fingerprints/\(indexSha256.prefix(16))-landmarks.json"
        else { throw CatalogError.invalid("已发布声音指纹绑定无效") }
    }

    public func validate(week: SermonWeek, track: SermonTrack) throws {
        try validate()
        // Editorial approval can advance without changing the source-bound audio.
        let supportedReviewState = (track.scope == "full_candidate" && week.humanApproval == .bool(false))
            || (track.scope == "full_reviewed" && week.humanApproval == .bool(true))
        guard supportedReviewState, pageId == week.id, sourceSha256 == week.sourceSha256,
              sourceStartSeconds == week.sourceStartSeconds, sourceEndSeconds == week.sourceEndSeconds,
              trackSha256 == track.sha256,
              track.subtitleTiming == "source_video_aligned_candidate",
              abs(track.durationSeconds - (sourceEndSeconds - sourceStartSeconds)) <= 0.1,
              week.videoSynchronization == "candidate_aligned",
              case .object(let evidence) = week.candidateEvidence,
              evidence["syncMp3Sha256"] == .string(trackSha256)
        else { throw CatalogError.invalid("已发布声音指纹与当前来源、窗口或音轨不符") }
    }

    public func indexURL(relativeTo baseURL: URL) throws -> URL {
        try validate()
        guard Validation.httpsURL(baseURL.absoluteString),
              var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false)
        else { throw CatalogError.invalid("指纹地址无效") }
        components.path = indexUrl; components.query = nil; components.fragment = nil
        guard let url = components.url else { throw CatalogError.invalid("指纹地址无效") }
        return url
    }
}

public struct PublishedFingerprintIndex: Sendable {
    public let durationSeconds: Double
    let lookup: [UInt32: [Int]]
    private let document: Document

    private struct Document: Decodable, Sendable {
        struct Window: Decodable, Sendable { let startSeconds: Double; let endSeconds: Double }
        let schemaVersion: String
        let algorithmVersion: String
        let sampleRate: Int
        let hopSize: Int
        let fftSize: Int
        let sourceSha256: String
        let trackSha256: String
        let pageId: String
        let sourceStartSeconds: Double
        let sourceEndSeconds: Double
        let window: Window
        let durationSeconds: Double
        let landmarkCount: Int
        let postings: [String: [Int]]
    }

    public static func decode(_ data: Data) throws -> Self {
        try Task.checkCancellation()
        guard !data.isEmpty, data.count <= 8 * 1024 * 1024 else { throw FingerprintError.invalidIndex("文件大小超出范围") }
        let doc = try JSONDecoder().decode(Document.self, from: data)
        guard doc.schemaVersion == "sermon-landmark-index-v1", doc.algorithmVersion == "spectral-landmarks-v1",
              doc.sampleRate == 8000, doc.hopSize == 256, doc.fftSize == 1024,
              Validation.identifier(doc.pageId), Validation.sha256(doc.sourceSha256), Validation.sha256(doc.trackSha256),
              doc.sourceStartSeconds.isFinite, doc.sourceStartSeconds >= 0, doc.sourceEndSeconds.isFinite,
              doc.durationSeconds.isFinite, (7...14_400).contains(doc.durationSeconds),
              doc.durationSeconds == doc.sourceEndSeconds - doc.sourceStartSeconds,
              doc.window.startSeconds == doc.sourceStartSeconds, doc.window.endSeconds == doc.sourceEndSeconds,
              doc.landmarkCount > 0, doc.landmarkCount <= Int(ceil(doc.durationSeconds)) * 14 * 8
        else { throw FingerprintError.invalidIndex("版本、算法或来源不符") }
        var lookup: [UInt32: [Int]] = [:]
        var count = 0
        for (iteration, entry) in doc.postings.enumerated() {
            if iteration % 4096 == 0 { try Task.checkCancellation() }
            let (key, times) = entry
            guard let hash = UInt32(key), String(hash) == key, hash < (1 << 22), !times.isEmpty,
                  times.allSatisfy({ $0 >= 0 && Double($0) * 0.032 < doc.durationSeconds }),
                  zip(times, times.dropFirst()).allSatisfy({ $0 <= $1 })
            else { throw FingerprintError.invalidIndex("索引数值、顺序或时间无效") }
            count += times.count
            guard count <= doc.landmarkCount else { throw FingerprintError.invalidIndex("索引长度不符") }
            lookup[hash] = times
        }
        guard count == doc.landmarkCount else { throw FingerprintError.invalidIndex("索引长度不符") }
        return Self(durationSeconds: doc.durationSeconds, lookup: lookup, document: doc)
    }

    public func validate(binding: PublishedFingerprintBinding) throws {
        try binding.validate()
        guard document.pageId == binding.pageId, document.sourceSha256 == binding.sourceSha256,
              document.trackSha256 == binding.trackSha256, document.algorithmVersion == binding.algorithmVersion,
              document.sourceStartSeconds == binding.sourceStartSeconds,
              document.sourceEndSeconds == binding.sourceEndSeconds
        else { throw FingerprintError.invalidIndex("指纹与已发布绑定不符") }
    }
}
