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
    /// Optional study fields come from the same verified content bytes. They are
    /// exposed only for human-reviewed content; no legacy week is joined by date.
    public let scripture: String?
    public let summary: String?
    public let outline: [OutlineSection]
    public let questions: [String]
    /// Duration of the source-video timeline used by the full reading text.
    public let durationSeconds: Double
    /// Duration of the target-language audio timeline used by spoken captions.
    public let audioDurationSeconds: Double
    public let contentStatus: String
    /// Release audio status; `machine_checked` audio was admitted by a waiver, not a human listening review.
    public let audioStatus: String
    public let releaseStatus: String
    /// The verified v4 release's same-locale disclosure; nil for human-only releases.
    public let disclosure: MachineCheckedDisclosure?
    public let fullText: [PublishedTranscriptCue]
    public let captions: [PublishedTranscriptCue]

    /// At least one product of this release is machine-checked; never a human approval.
    public var isMachineChecked: Bool { contentStatus == "machine_checked" || audioStatus == "machine_checked" }

    /// Call after verifying the two asset byte hashes against the catalog-bound
    /// release. Optional English failures leave the verified target text usable.
    public static func decode(content: Data, captions: Data, englishReference: Data? = nil,
                              package: TargetLanguageReleasePackage, page: MultilingualPage,
                              allowDevCandidate: Bool = false) throws -> Self {
        try package.validate(allowDevCandidate: allowDevCandidate)
        guard [TargetLanguageReleasePackage.dualScriptSchemaVersion, TargetLanguageReleasePackage.fourProductSchemaVersion,
               TargetLanguageReleasePackage.machineCheckedSchemaVersion].contains(package.schemaVersion),
              package.pageId == page.id, let target = page.targets[package.targetLocale],
              package.contentStatus == target.contentStatus, package.audioStatus == target.audioStatus else {
            throw CatalogError.invalid("文稿与发布语言不符")
        }
        let source = try JSONDecoder().decode(FullContent.self, from: content)
        let spoken = try JSONDecoder().decode(CaptionContent.self, from: captions)
        let candidate = allowDevCandidate && package.status == "candidate" &&
            package.schemaVersion != TargetLanguageReleasePackage.fourProductSchemaVersion &&
            package.schemaVersion != TargetLanguageReleasePackage.machineCheckedSchemaVersion
        // Content v3 is read only through a v4 release, whose content status it must equal.
        let machineCheckedRelease = package.schemaVersion == TargetLanguageReleasePackage.machineCheckedSchemaVersion
        let validContentSchema = candidate
            ? (source.schemaVersion == "sermon-formal-dev-content-v1" ||
               (package.contentStatus == "machine_reviewed" && source.schemaVersion == "sermon-dev-podcast-candidate-content-v2"))
            : (["sermon-full-video-text-content-v1", "sermon-full-video-text-content-v2"].contains(source.schemaVersion)
               || (machineCheckedRelease && source.schemaVersion == PublishedContentReview.machineCheckedSchemaVersion))
        let validContentStatus = source.status == package.contentStatus
            && (source.status == "human_reviewed" || source.schemaVersion == PublishedContentReview.machineCheckedSchemaVersion)
        guard validContentSchema,
              source.pageId == page.id, source.sourceLocale == "en",
              (candidate ? source.locale : source.targetLocale) == package.targetLocale,
              (candidate ? source.contentStatus == package.contentStatus && source.audioStatus == package.audioStatus &&
                  source.targetLanguageAudioPackageJsonSha256 == package.targetLanguageAudioPackageJsonSha256 &&
                  source.date == page.date : validContentStatus),
              source.englishSourcePackageJsonSha256 == page.sourceIdentitySha256,
              source.targetLanguageCandidateJsonSha256 == package.targetLanguageCandidateJsonSha256,
              (candidate ? true : source.sourceMediaSha256.map(Validation.sha256) == true),
              (candidate ? true : page.sourceMediaSha256.map({ $0 == source.sourceMediaSha256 }) ?? true),
              source.durationSeconds.isFinite, source.durationSeconds > 0,
              source.durationSeconds <= 24 * 60 * 60, !source.title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw CatalogError.invalid("完整文稿来源绑定无效")
        }
        guard source.schemaVersion != "sermon-full-video-text-content-v2" || source.audioDurationSeconds != nil else {
            throw CatalogError.invalid("新版文稿缺少音轨时长")
        }
        if source.schemaVersion == PublishedContentReview.machineCheckedSchemaVersion {
            // v3 adds the formal-only review statement and, when machine-checked,
            // the same-locale disclosure. Simulation content stays on v2.
            let review = try PublishedContentReview.decode(content)
            // Machine-checked text repeats the release disclosure it was published under.
            guard review.pageId == page.id, review.targetLocale == package.targetLocale,
                  review.status == package.contentStatus,
                  review.status != "machine_checked" || review.disclosure == package.disclosure,
                  page.simulationOnly != true, target.simulationOnly != true else {
                throw CatalogError.invalid("机器质检文稿与发布包不符")
            }
        }
        if source.schemaVersion == "sermon-full-video-text-content-v2" {
            guard source.reviewMode == "formal" || source.reviewMode == "simulation" else {
                throw CatalogError.invalid("新版文稿审核模式无效")
            }
            if source.reviewMode == "simulation" {
                guard allowDevCandidate, page.simulationOnly == true, page.diagnosticOnly == true,
                      target.simulationOnly == true, target.diagnosticOnly == true else {
                    throw CatalogError.invalid("模拟审核文稿仅允许显式开发测试页面")
                }
            } else {
                guard page.simulationOnly != true, target.simulationOnly != true else {
                    throw CatalogError.invalid("模拟测试页面不能声明正式审核文稿")
                }
            }
        }
        let audioDuration = source.audioDurationSeconds ?? source.durationSeconds
        guard audioDuration.isFinite, audioDuration > 0, audioDuration <= 24 * 60 * 60 else {
            throw CatalogError.invalid("音轨时长无效")
        }
        if candidate {
            guard spoken.schemaVersion == "sermon-target-language-captions-v1", spoken.pageId == page.id,
                  spoken.locale == package.targetLocale,
                  spoken.audioPackageJsonSha256 == package.targetLanguageAudioPackageJsonSha256,
                  spoken.timingBasis == "concatenated target audio; natural unit durations; no source-video synchronization" else {
                throw CatalogError.invalid("Dev 候选字幕音轨绑定无效")
            }
        }
        try validateCues(source.cues, duration: source.durationSeconds, requiresSourceUnits: true)
        try validateCues(spoken.cues, duration: audioDuration, requiresSourceUnits: false)
        guard source.cues.count == spoken.cues.count,
              Set(source.cues.map(\.textGroupId)) == Set(spoken.cues.map(\.textGroupId)) else {
            throw CatalogError.invalid("口播字幕与全文组不符")
        }
        let english = (candidate ? nil : englishReference).flatMap {
            try? EnglishReference.validated($0, source: source, package: package, page: page)
        } ?? [:]
        func convert(_ cue: RawCue) -> PublishedTranscriptCue {
            .init(id: cue.textGroupId, text: cue.text, start: cue.start, end: cue.end,
                  english: english[cue.textGroupId])
        }
        let reviewed = package.contentStatus == "human_reviewed"
        func nonempty(_ value: String?) -> String? {
            guard let value, !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
            return value
        }
        let outline = reviewed ? (source.outline ?? []).compactMap { item -> OutlineSection? in
            let points = item.points.filter { nonempty($0) != nil }
            guard let title = nonempty(item.title) else { return nil }
            return OutlineSection(title: title, points: points)
        } : []
        return .init(pageID: page.id, locale: package.targetLocale,
                     sourceIdentitySha256: page.sourceIdentitySha256, title: source.title,
                     series: source.series, speaker: source.speaker,
                     scripture: source.scripture,
                     summary: reviewed ? nonempty(source.summary) : nil, outline: outline,
                     questions: reviewed ? (source.questions ?? []).filter { nonempty($0) != nil } : [],
                     durationSeconds: source.durationSeconds, audioDurationSeconds: audioDuration, contentStatus: package.contentStatus,
                     audioStatus: package.audioStatus, releaseStatus: package.status, disclosure: package.disclosure,
                     fullText: source.cues.map(convert),
                     captions: spoken.cues.map(convert))
    }
}

/// Review statement of full reading content v3. `machine_checked` means a bound
/// machine quality waiver admitted the full text; it is never a human approval,
/// so the content must carry its same-locale disclosure, and human-reviewed
/// content must not. Read only through a v4 release with the same content status.
public struct PublishedContentReview: Decodable, Sendable, Equatable {
    public static let machineCheckedSchemaVersion = "sermon-full-video-text-content-v3"
    public let schemaVersion: String
    public let pageId: String
    public let targetLocale: String
    public let sourceLocale: String
    public let status: String
    public let durationSeconds: Double
    public let audioDurationSeconds: Double
    public let reviewMode: String
    public let disclosure: MachineCheckedDisclosure?
    public let cueCount: Int

    private enum CodingKeys: String, CodingKey {
        case schemaVersion, pageId, targetLocale, sourceLocale, status, durationSeconds
        case audioDurationSeconds, reviewMode, disclosure, cues
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        schemaVersion = try c.decode(String.self, forKey: .schemaVersion)
        pageId = try c.decode(String.self, forKey: .pageId)
        targetLocale = try c.decode(String.self, forKey: .targetLocale)
        sourceLocale = try c.decode(String.self, forKey: .sourceLocale)
        status = try c.decode(String.self, forKey: .status)
        durationSeconds = try c.decode(Double.self, forKey: .durationSeconds)
        audioDurationSeconds = try c.decode(Double.self, forKey: .audioDurationSeconds)
        reviewMode = try c.decode(String.self, forKey: .reviewMode)
        // A present key must be a complete disclosure; explicit null is not absence.
        disclosure = c.contains(.disclosure)
            ? try c.decode(MachineCheckedDisclosure.self, forKey: .disclosure) : nil
        cueCount = try c.decode([JSONValue].self, forKey: .cues).count
    }

    public static func decode(_ data: Data) throws -> Self {
        let value = try JSONDecoder().decode(Self.self, from: data)
        try value.validate()
        return value
    }

    public func validate() throws {
        guard schemaVersion == Self.machineCheckedSchemaVersion, !pageId.isEmpty, !targetLocale.isEmpty,
              sourceLocale == "en", ["human_reviewed", "machine_checked"].contains(status),
              durationSeconds.isFinite, durationSeconds > 0, durationSeconds <= 24 * 60 * 60,
              audioDurationSeconds.isFinite, audioDurationSeconds > 0, audioDurationSeconds <= 24 * 60 * 60,
              reviewMode == "formal", cueCount > 0
        else { throw CatalogError.invalid("文稿版本、审核状态或时长无效") }
        if status == "machine_checked" {
            guard let disclosure else { throw CatalogError.invalid("机器质检文稿缺少说明") }
            try disclosure.validate(locale: targetLocale)
        } else if disclosure != nil {
            throw CatalogError.invalid("人工审核文稿不能声明机器质检说明")
        }
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
    let targetLocale: String?
    let locale: String?
    let status: String?
    let contentStatus: String?
    let audioStatus: String?
    let date: String?
    let targetLanguageAudioPackageJsonSha256: String?
    let englishSourcePackageJsonSha256: String
    let targetLanguageCandidateJsonSha256: String
    let sourceMediaSha256: String?
    let durationSeconds: Double
    let audioDurationSeconds: Double?
    let reviewMode: String?
    let title: String
    let series: String?
    let speaker: String?
    let scripture: String?
    let summary: String?
    let outline: [PublishedStudyOutline]?
    let questions: [String]?
    let cues: [RawCue]

    private enum CodingKeys: String, CodingKey {
        case schemaVersion, pageId, sourceLocale, targetLocale, locale, status, contentStatus, audioStatus, date
        case targetLanguageAudioPackageJsonSha256, englishSourcePackageJsonSha256, targetLanguageCandidateJsonSha256
        case sourceMediaSha256, durationSeconds, audioDurationSeconds, reviewMode, title, series, speaker, cues
        case scripture, summary, outline, questions
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        schemaVersion = try c.decode(String.self, forKey: .schemaVersion)
        pageId = try c.decode(String.self, forKey: .pageId)
        sourceLocale = try c.decode(String.self, forKey: .sourceLocale)
        targetLocale = try c.decodeIfPresent(String.self, forKey: .targetLocale)
        locale = try c.decodeIfPresent(String.self, forKey: .locale)
        status = try c.decodeIfPresent(String.self, forKey: .status)
        contentStatus = try c.decodeIfPresent(String.self, forKey: .contentStatus)
        audioStatus = try c.decodeIfPresent(String.self, forKey: .audioStatus)
        date = try c.decodeIfPresent(String.self, forKey: .date)
        targetLanguageAudioPackageJsonSha256 = try c.decodeIfPresent(String.self, forKey: .targetLanguageAudioPackageJsonSha256)
        englishSourcePackageJsonSha256 = try c.decode(String.self, forKey: .englishSourcePackageJsonSha256)
        targetLanguageCandidateJsonSha256 = try c.decode(String.self, forKey: .targetLanguageCandidateJsonSha256)
        sourceMediaSha256 = try c.decodeIfPresent(String.self, forKey: .sourceMediaSha256)
        durationSeconds = try c.decode(Double.self, forKey: .durationSeconds)
        // Only an absent legacy field may fall back. Explicit null or a wrong
        // type must not silently remove a declared audio clock.
        audioDurationSeconds = c.contains(.audioDurationSeconds)
            ? try c.decode(Double.self, forKey: .audioDurationSeconds) : nil
        reviewMode = try c.decodeIfPresent(String.self, forKey: .reviewMode)
        title = try c.decode(String.self, forKey: .title)
        series = try c.decodeIfPresent(String.self, forKey: .series)
        speaker = try c.decodeIfPresent(String.self, forKey: .speaker)
        scripture = try c.decodeIfPresent(String.self, forKey: .scripture)
        summary = try c.decodeIfPresent(String.self, forKey: .summary)
        outline = try c.decodeIfPresent([PublishedStudyOutline].self, forKey: .outline)
        questions = try c.decodeIfPresent([String].self, forKey: .questions)
        cues = try c.decode([RawCue].self, forKey: .cues)
    }
}

/// Published full-video outlines use strings; Dev uses title/body objects and
/// legacy-compatible optional additions may use title/points objects.
private struct PublishedStudyOutline: Decodable {
    let title: String
    let points: [String]
    private enum CodingKeys: String, CodingKey { case title, body, points }
    init(from decoder: Decoder) throws {
        if let line = try? decoder.singleValueContainer().decode(String.self) {
            title = line; points = []
        } else {
            let values = try decoder.container(keyedBy: CodingKeys.self)
            title = try values.decode(String.self, forKey: .title)
            if let body = try values.decodeIfPresent(String.self, forKey: .body) { points = [body] }
            else { points = try values.decode([String].self, forKey: .points) }
        }
        guard title.count <= 8_000, points.count <= 100,
              points.allSatisfy({ $0.count <= 50_000 }) else {
            throw CatalogError.invalid("大纲内容范围无效")
        }
    }
}

private struct CaptionContent: Decodable {
    let schemaVersion: String?
    let pageId: String?
    let locale: String?
    let audioPackageJsonSha256: String?
    let timingBasis: String?
    let cues: [RawCue]
}

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
