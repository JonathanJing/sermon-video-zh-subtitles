import CryptoKit
import Foundation
import TongxingCore

public struct ReviewedStudyArtifact: Decodable, Sendable {
    public struct Section: Decodable, Sendable {
        public let title: String
        public let body: String
        public let sourceUnitIds: [String]
    }
    let schemaVersion: String
    let kind: String
    let pageId: String
    let locale: String
    let sourcePackageSha256: String
    let textCandidateSha256: String
    let producerIdentity: String
    public let sections: [Section]

    static func decode(_ data: Data, kind: String, package: TargetLanguageReleasePackage) throws -> Self {
        let artifact = try JSONDecoder().decode(Self.self, from: data)
        guard let products = package.fourProducts,
              artifact.schemaVersion == "sermon-study-artifact-v1", artifact.kind == kind,
              artifact.pageId == package.pageId, artifact.locale == package.targetLocale,
              artifact.sourcePackageSha256 == products.sourcePackageSha256,
              artifact.textCandidateSha256 == products.textCandidateSha256,
              !artifact.producerIdentity.isEmpty,
              !artifact.sections.isEmpty, artifact.sections.count <= 1_000,
              artifact.sections.allSatisfy({ !$0.title.isEmpty && $0.title.count <= 2_000 &&
                  !$0.body.isEmpty && $0.body.count <= 80_000 && !$0.sourceUnitIds.isEmpty &&
                  $0.sourceUnitIds.count <= 2_000 && Set($0.sourceUnitIds).count == $0.sourceUnitIds.count &&
                  $0.sourceUnitIds.allSatisfy({ !$0.isEmpty && $0.count <= 300 }) }),
              try canonicalSHA(data) == (kind == "outline" ? products.outlineArtifactSha256 : products.meditationArtifactSha256)
        else { throw ContentStorageError.invalidResponse }
        return artifact
    }

    var htmlItems: String {
        sections.map { "<li><strong>\(Self.escape($0.title))</strong><p>\(Self.escape($0.body))</p></li>" }.joined()
    }

    func isDisplayed(in html: String) -> Bool {
        html.contains("id=\"study-\(kind)\"") && sections.allSatisfy {
            html.contains(Self.escape($0.title)) && html.contains(Self.escape($0.body))
        }
    }

    static func escape(_ value: String) -> String {
        value.replacingOccurrences(of: "&", with: "&amp;").replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;").replacingOccurrences(of: "\"", with: "&quot;")
            .replacingOccurrences(of: "'", with: "&#x27;")
    }
}

public struct ReviewedStudyResources: Sendable {
    struct Manifest: Decodable {
        let schemaVersion: String
        let pageId: String
        let locale: String
        let sourceIdentity: ReviewedReleaseSourceIdentity
        let fourProducts: ReviewedAppProducts
    }
    public let outline: ReviewedStudyArtifact
    public let meditation: ReviewedStudyArtifact

    static func validateManifest(_ data: Data, package: TargetLanguageReleasePackage) throws {
        let manifest = try JSONDecoder().decode(Manifest.self, from: data)
        guard manifest.schemaVersion == "sermon-public-app-products-v1",
              manifest.pageId == package.pageId, manifest.locale == package.targetLocale,
              manifest.sourceIdentity == package.sourceIdentity,
              manifest.fourProducts == package.fourProducts
        else { throw ContentStorageError.invalidResponse }
        let p = manifest.fourProducts
        let products: [String: Any] = ["source": p.sourcePackageSha256, "products": [
            "text": p.textCandidateSha256, "audio": p.audioPackageSha256,
            "outline": ["status": "human_reviewed", "artifactSha256": p.outlineArtifactSha256, "reviewSha256": p.outlineReviewSha256],
            "meditation": ["status": "human_reviewed", "artifactSha256": p.meditationArtifactSha256, "reviewSha256": p.meditationReviewSha256]]]
        let productHash = try canonicalSHA(JSONSerialization.data(withJSONObject: products))
        let candidate: [String: Any] = ["products": productHash, "metadataApproval": p.metadataApprovalSha256,
                                       "contentSha256": p.contentSha256]
        guard try canonicalSHA(JSONSerialization.data(withJSONObject: candidate)) == p.candidateSha256,
              package.assets.first(where: { $0.role == .content })?.sha256 == p.contentSha256 else {
            throw ContentStorageError.invalidResponse
        }
    }
}

private func canonicalSHA(_ data: Data) throws -> String {
    let value = try JSONSerialization.jsonObject(with: data)
    let canonical = try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys, .withoutEscapingSlashes])
    return SHA256.hash(data: canonical).map { String(format: "%02x", $0) }.joined()
}
