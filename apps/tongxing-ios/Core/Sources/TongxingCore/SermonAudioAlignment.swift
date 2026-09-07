import Foundation

/// A published candidate capability. Its presence does not upgrade subtitle or
/// acoustic review; it only permits matching the same reference recording at 1x.
public struct SermonAudioAlignment: Codable, Sendable, Equatable {
    public static let supportedSchemaVersion = "sermon-audio-alignment-v1"
    public static let supportedMethod = "spectral-landmarks-v1"
    public let schemaVersion: String
    public let method: String
    public let fingerprintUrl: String
    public let fingerprintSha256: String
    public let sourceId: String
    public let referenceAudioSha256: String
    public let referenceDurationSeconds: Double
    public let timeOrigin: String
    public let sourceVideoOffsetSeconds: Double
    public let trackSha256: String
    public let timeline: String
    public let reviewState: String

    public init(schemaVersion: String = supportedSchemaVersion, method: String = supportedMethod,
                fingerprintUrl: String, fingerprintSha256: String, sourceId: String,
                referenceAudioSha256: String, referenceDurationSeconds: Double,
                timeOrigin: String = "approved_sermon_clip_start", sourceVideoOffsetSeconds: Double,
                trackSha256: String, timeline: String = "source_clip", reviewState: String = "candidate") {
        self.schemaVersion = schemaVersion; self.method = method
        self.fingerprintUrl = fingerprintUrl; self.fingerprintSha256 = fingerprintSha256; self.sourceId = sourceId
        self.referenceAudioSha256 = referenceAudioSha256; self.referenceDurationSeconds = referenceDurationSeconds
        self.timeOrigin = timeOrigin; self.sourceVideoOffsetSeconds = sourceVideoOffsetSeconds
        self.trackSha256 = trackSha256; self.timeline = timeline; self.reviewState = reviewState
    }

    public func validate() throws {
        guard schemaVersion == Self.supportedSchemaVersion, method == Self.supportedMethod,
              Validation.sha256(fingerprintSha256), Validation.sha256(referenceAudioSha256), Validation.sha256(trackSha256),
              fingerprintUrl == "/alignment/\(fingerprintSha256)-fingerprint.json",
              Validation.identifier(sourceId), sourceId.utf8.count <= 128,
              timeOrigin == "approved_sermon_clip_start", timeline == "source_clip", reviewState == "candidate",
              sourceVideoOffsetSeconds.isFinite, sourceVideoOffsetSeconds >= 0,
              referenceDurationSeconds.isFinite, (5...14_400).contains(referenceDurationSeconds)
        else { throw CatalogError.invalid("声音定位能力或时间来源无效") }
    }

    public func validate(track: SermonTrack) throws {
        try validate()
        guard trackSha256 == track.sha256, track.durationSeconds.isFinite,
              abs(referenceDurationSeconds - track.durationSeconds) <= 0.2,
              track.subtitleTiming == "source_video_aligned_candidate", track.scope == "full_candidate"
        else { throw CatalogError.invalid("声音定位与当前音轨不一致") }
    }

    public func validate(week: SermonWeek, track: SermonTrack) throws {
        try validate(track: track)
        guard sourceId == week.sourceId, week.videoSynchronization == "candidate_aligned", week.humanApproval == .bool(false),
              case .object(let evidence) = week.candidateEvidence, evidence["syncMp3Sha256"] == .string(trackSha256)
        else { throw CatalogError.invalid("声音定位与当前周次来源不一致") }
    }

    public func indexURL(relativeTo baseURL: URL) throws -> URL {
        try validate()
        guard Validation.httpsURL(baseURL.absoluteString), var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false)
        else { throw CatalogError.invalid("指纹地址无效") }
        components.path = fingerprintUrl; components.query = nil; components.fragment = nil
        guard let url = components.url else { throw CatalogError.invalid("指纹地址无效") }
        return url
    }
}
