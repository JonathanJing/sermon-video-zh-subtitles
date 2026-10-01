import Foundation

/// The full reading manuscript retains source-video times; captions retain the
/// separately approved spoken-script times. English is joined only by source IDs.
public struct PublishedTranscriptCue: Sendable, Equatable, Identifiable {
    public let id: String
    public let text: String
    public let start: Double
    public let end: Double
    public let english: String?
}

public struct VerifiedPublishedTranscript: Sendable, Equatable {
    public let pageID: String
    public let locale: String
    public let sourceIdentitySha256: String
    public let title: String?
    public let series: String?
    public let speaker: String?
    public let durationSeconds: Double
    public let fullText: [PublishedTranscriptCue]
    public let captions: [PublishedTranscriptCue]

    /// Call after verifying the two asset byte hashes against the catalog-bound
    /// release. Optional English failures leave the verified target text usable.
    public static func decode(content: Data, captions: Data, englishReference: Data? = nil,
                              package: TargetLanguageReleasePackage, page: MultilingualPage) throws -> Self {
        try package.validate()
        guard package.schemaVersion == TargetLanguageReleasePackage.dualScriptSchemaVersion,
              package.pageId == page.id, let target = page.targets[package.targetLocale],
              package.contentStatus == target.contentStatus, package.audioStatus == target.audioStatus else {
            throw CatalogError.invalid("文稿与发布语言不符")
        }
        let source = try JSONDecoder().decode(FullContent.self, from: content)
        let spoken = try JSONDecoder().decode(CaptionContent.self, from: captions)
        guard source.schemaVersion == "sermon-full-video-text-content-v1",
              source.pageId == page.id, source.sourceLocale == "en", source.targetLocale == package.targetLocale,
              source.status == "human_reviewed", source.englishSourcePackageJsonSha256 == page.sourceIdentitySha256,
              source.targetLanguageCandidateJsonSha256 == package.targetLanguageCandidateJsonSha256,
              Validation.sha256(source.sourceMediaSha256),
              page.sourceMediaSha256.map({ $0 == source.sourceMediaSha256 }) ?? true,
              source.durationSeconds.isFinite, source.durationSeconds > 0,
              source.durationSeconds <= 24 * 60 * 60, !source.title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw CatalogError.invalid("完整文稿来源绑定无效")
        }
        try validateCues(source.cues, duration: source.durationSeconds, requiresSourceUnits: true)
        try validateCues(spoken.cues, duration: source.durationSeconds, requiresSourceUnits: false)
        guard source.cues.count == spoken.cues.count,
              Set(source.cues.map(\.textGroupId)) == Set(spoken.cues.map(\.textGroupId)) else {
            throw CatalogError.invalid("口播字幕与全文组不符")
        }
        let english = englishReference.flatMap {
            try? EnglishReference.validated($0, source: source, package: package, page: page)
        } ?? [:]
        func convert(_ cue: RawCue) -> PublishedTranscriptCue {
            .init(id: cue.textGroupId, text: cue.text, start: cue.start, end: cue.end,
                  english: english[cue.textGroupId])
        }
        return .init(pageID: page.id, locale: package.targetLocale,
                     sourceIdentitySha256: page.sourceIdentitySha256, title: source.title,
                     series: source.series, speaker: source.speaker,
                     durationSeconds: source.durationSeconds, fullText: source.cues.map(convert),
                     captions: spoken.cues.map(convert))
    }
}

private struct RawCue: Decodable {
    let textGroupId: String
    let sourceUnitIds: [String]?
    let text: String
    let start: Double
    let end: Double
}

private struct FullContent: Decodable {
    let schemaVersion: String
    let pageId: String
    let sourceLocale: String
    let targetLocale: String
    let status: String
    let englishSourcePackageJsonSha256: String
    let targetLanguageCandidateJsonSha256: String
    let sourceMediaSha256: String
    let durationSeconds: Double
    let title: String
    let series: String?
    let speaker: String?
    let cues: [RawCue]
}

private struct CaptionContent: Decodable { let cues: [RawCue] }

private func validateCues(_ cues: [RawCue], duration: Double, requiresSourceUnits: Bool) throws {
    guard !cues.isEmpty, cues.count <= 10_000 else { throw CatalogError.invalid("字幕数量无效") }
    var ids = Set<String>()
    var previousEnd: Double = 0
    for cue in cues {
        guard cue.start.isFinite, cue.end.isFinite, cue.start >= previousEnd,
              cue.start < cue.end, cue.end <= duration + 0.001,
              !cue.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, cue.text.count <= 50_000,
              Validation.identifier(cue.textGroupId), ids.insert(cue.textGroupId).inserted else {
            throw CatalogError.invalid("字幕时间或单元无效")
        }
        if requiresSourceUnits {
            guard let units = cue.sourceUnitIds, !units.isEmpty,
                  units.allSatisfy(Validation.identifier), Set(units).count == units.count else {
                throw CatalogError.invalid("全文英文来源单元无效")
            }
        }
        previousEnd = cue.end
    }
}

private struct EnglishReference: Decodable {
    struct Target: Decodable {
        struct Block: Decodable {
            let textGroupId: String
            let sourceUnitIds: [String]
            let english: String
        }
        let contentSha256: String
        let captionsSha256: String
        let releasePackageJsonSha256: String
        let blocks: [Block]
    }
    let schemaVersion: String
    let pageId: String
    let sourceIdentitySha256: String
    let sourceMediaSha256: String
    let reviewState: String
    let targets: [String: Target]

    static func validated(_ data: Data, source: FullContent, package: TargetLanguageReleasePackage,
                          page: MultilingualPage) throws -> [String: String] {
        let reference = try JSONDecoder().decode(Self.self, from: data)
        guard reference.schemaVersion == "sermon-published-english-reference-v1", reference.pageId == page.id,
              reference.sourceIdentitySha256 == page.sourceIdentitySha256,
              reference.sourceMediaSha256 == source.sourceMediaSha256, reference.reviewState == "human_approved",
              let target = reference.targets[package.targetLocale],
              target.releasePackageJsonSha256 == page.targets[package.targetLocale]?.releasePackageJsonSha256,
              target.contentSha256 == package.assets.first(where: { $0.role == .content })?.sha256,
              target.captionsSha256 == package.assets.first(where: { $0.role == .captions })?.sha256,
              target.blocks.count == source.cues.count else { throw CatalogError.invalid("英文对照发布绑定无效") }
        var result: [String: String] = [:]
        for (block, cue) in zip(target.blocks, source.cues) {
            guard block.textGroupId == cue.textGroupId, block.sourceUnitIds == cue.sourceUnitIds,
                  result[block.textGroupId] == nil,
                  !block.english.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                  block.english.count <= 50_000 else { throw CatalogError.invalid("英文对照单元不符") }
            result[block.textGroupId] = block.english
        }
        return result
    }
}
