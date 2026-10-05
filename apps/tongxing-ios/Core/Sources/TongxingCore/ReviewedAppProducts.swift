import Foundation

/// Identity of the approved recording and window. Paths and reviewer details
/// remain private; these fields are the published immutable binding.
public struct ReviewedReleaseSourceIdentity: Codable, Sendable, Equatable {
    public struct Window: Codable, Sendable, Equatable {
        public let startSeconds: Double
        public let endSeconds: Double
        public let approvalReceiptSha256: String
    }
    public let sourceId: String
    public let sourceUrlHash: String
    public let mediaSha256: String
    public let durationSeconds: Double
    public let window: Window

    public func validate() throws {
        guard !sourceId.isEmpty, Validation.sha256(sourceUrlHash), Validation.sha256(mediaSha256),
              durationSeconds.isFinite, durationSeconds > 0,
              window.startSeconds.isFinite, window.endSeconds.isFinite,
              window.startSeconds >= 0, window.endSeconds > window.startSeconds,
              window.endSeconds <= durationSeconds, Validation.sha256(window.approvalReceiptSha256)
        else { throw CatalogError.invalid("四产物来源窗口无效") }
    }
}

public struct ReviewedAppProducts: Codable, Sendable, Equatable {
    public let sourcePackageSha256: String
    public let textCandidateSha256: String
    public let audioPackageSha256: String
    public let outlineArtifactSha256: String
    public let meditationArtifactSha256: String
    public let outlineReviewSha256: String
    public let meditationReviewSha256: String
    public let metadataApprovalSha256: String
    public let contentSha256: String
    public let candidateSha256: String

    public func validate() throws {
        guard [sourcePackageSha256, textCandidateSha256, audioPackageSha256,
               outlineArtifactSha256, meditationArtifactSha256, outlineReviewSha256,
               meditationReviewSha256, metadataApprovalSha256, contentSha256,
               candidateSha256].allSatisfy(Validation.sha256)
        else { throw CatalogError.invalid("四产物哈希绑定无效") }
    }
}
