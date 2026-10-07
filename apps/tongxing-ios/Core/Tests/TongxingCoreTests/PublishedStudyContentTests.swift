import Foundation
import Testing
@testable import TongxingCore

struct PublishedStudyContentTests {
    private func decode(locale: String = "zh-Hans", fields: [String: Any] = [:]) throws -> VerifiedPublishedTranscript {
        let url = try #require(Bundle.module.url(forResource: "dev-candidate-catalog-readback", withExtension: "json", subdirectory: "Fixtures"))
        let fixture = try #require(JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
        func bytes(_ object: Any) throws -> Data { try JSONSerialization.data(withJSONObject: object) }
        let catalog = try MultilingualCatalog.decode(bytes(fixture["catalog"]!), allowDevCandidates: true)
        let page = catalog.pages[1]
        let releases = try #require(fixture["releases"] as? [String: [String: Any]])
        let package = try TargetLanguageReleasePackage.decode(bytes(releases[locale]!), allowDevCandidate: true)
        let cue: [String: Any] = ["textGroupId": "synthetic-1", "sourceUnitIds": ["source-1"], "start": 0, "end": 9, "text": "Synthetic text"]
        var content: [String: Any] = [
            "schemaVersion": locale == "zh-Hans" ? "sermon-formal-dev-content-v1" : "sermon-dev-podcast-candidate-content-v2",
            "pageId": page.id, "sourceLocale": "en", "locale": locale, "contentStatus": package.contentStatus,
            "audioStatus": package.audioStatus, "date": page.date,
            "englishSourcePackageJsonSha256": page.sourceIdentitySha256,
            "targetLanguageCandidateJsonSha256": package.targetLanguageCandidateJsonSha256,
            "targetLanguageAudioPackageJsonSha256": package.targetLanguageAudioPackageJsonSha256!,
            "durationSeconds": 10, "title": "Synthetic title", "cues": [cue],
        ]
        content.merge(fields) { _, new in new }
        let captions: [String: Any] = ["schemaVersion": "sermon-target-language-captions-v1", "pageId": page.id,
            "locale": locale, "audioPackageJsonSha256": package.targetLanguageAudioPackageJsonSha256!,
            "timingBasis": "concatenated target audio; natural unit durations; no source-video synchronization", "cues": [cue]]
        return try VerifiedPublishedTranscript.decode(content: bytes(content), captions: bytes(captions), package: package, page: page, allowDevCandidate: true)
    }

    @Test func reviewedStudyFieldsPreserveBothPublishedOutlineRepresentations() throws {
        let result = try decode(fields: ["summary": "Reviewed summary", "scripture": "Revelation 4",
            "outline": ["Published point", ["title": "Dev section", "body": "Reviewed body"],
                        ["title": "Legacy section", "points": ["Reviewed point"]]], "questions": ["Reviewed question"]])
        #expect(result.summary == "Reviewed summary")
        #expect(result.scripture == "Revelation 4")
        #expect(result.outline == [.init(title: "Published point", points: []), .init(title: "Dev section", points: ["Reviewed body"]), .init(title: "Legacy section", points: ["Reviewed point"])])
        #expect(result.questions == ["Reviewed question"])
        #expect(result.contentStatus == "human_reviewed")
    }

    @Test func partialAndOldContentDoNotCreateOrRetainStudyFields() throws {
        let partial = try decode(fields: ["summary": " ", "outline": [], "questions": ["", "Question"]])
        #expect(partial.summary == nil)
        #expect(partial.outline.isEmpty)
        #expect(partial.questions == ["Question"])
        let old = try decode()
        #expect(old.summary == nil && old.scripture == nil)
        #expect(old.outline.isEmpty && old.questions.isEmpty)
    }

    @Test func reviewedStudyFieldsKeepIndependentSourceAndAudioClocks() throws {
        let result = try decode(fields: ["audioDurationSeconds": 12,
            "summary": "Reviewed summary", "outline": ["Reviewed point"],
            "questions": ["Reviewed question"]])
        #expect(result.durationSeconds == 10)
        #expect(result.audioDurationSeconds == 12)
        #expect(result.summary == "Reviewed summary")
        #expect(result.outline == [.init(title: "Reviewed point", points: [])])
        #expect(result.questions == ["Reviewed question"])
    }

    @Test func machineReviewedCandidateDoesNotExposeStudyMaterialAsReviewed() throws {
        let result = try decode(locale: "ko", fields: ["summary": "Unreviewed foreign language summary", "outline": ["Unreviewed point"], "questions": ["Unreviewed question"]])
        #expect(result.contentStatus == "machine_reviewed")
        #expect(result.summary == nil && result.outline.isEmpty && result.questions.isEmpty)
        #expect(!result.fullText.isEmpty)
    }

    @Test func invalidSourceCannotSupplyStudyContent() throws {
        #expect(throws: (any Error).self) {
            try decode(fields: ["englishSourcePackageJsonSha256": String(repeating: "a", count: 64), "summary": "Wrong source"])
        }
    }

    @Test func legacyQuestionsSurviveCatalogCacheRoundTrip() throws {
        let catalog = try WeeklyCatalog.decode(CatalogTests().fixture())
        let week = catalog.defaultWeek
        let reviewed = SermonWeek(id: week.id, date: week.date, sourceId: week.sourceId, sourceUrl: week.sourceUrl,
            title: week.title, speaker: week.speaker, scripture: week.scripture, tracks: week.tracks,
            summary: "Legacy summary", outline: [.init(title: "Section", points: ["Point"])], questions: ["Question"], contentReview: "Published review statement")
        let cached = try WeeklyCatalog.decode(JSONEncoder().encode(WeeklyCatalog(defaultWeekId: reviewed.id, weeks: [reviewed])))
        #expect(cached.defaultWeek.questions == ["Question"])
        #expect(cached.defaultWeek.contentReview == "Published review statement")
    }
}
