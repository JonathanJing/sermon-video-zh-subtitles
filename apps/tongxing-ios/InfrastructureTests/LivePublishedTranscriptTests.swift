import Foundation
import Testing
import TongxingCore
@testable import TongxingInfrastructure

/// Real production JSON readback only. This does not prove device playback or
/// microphone/venue acceptance, and never downloads the full video or audio.
@Suite(.enabled(if: ProcessInfo.processInfo.environment["TONGXING_LIVE_TRANSCRIPT_SMOKE"] == "1"))
struct LivePublishedTranscriptTests {
    @Test func currentThreeLocaleFullTextCaptionsAndEnglishAreBoundToPublishedRelease() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let repository = MultilingualCatalogRepository(
            origin: URL(string: "https://ai-for-god-sermon-audio.web.app")!, cacheDirectory: root)
        let catalog = try await repository.loadCatalog().catalog
        let page = try #require(catalog.pages.first { $0.id == "2026-09-27-weekend-sermon-drive-530" })
        for locale in ["zh-Hans", "ko", "es"] {
            let release = try await repository.loadRelease(page: page, locale: locale)
            let transcript = try await repository.loadPublishedTranscript(for: release, page: page)
            let expectedCount = locale == "zh-Hans" ? 419 : 420
            #expect(transcript.pageID == page.id)
            #expect(transcript.locale == locale)
            #expect(transcript.durationSeconds == 1891.677333)
            #expect(transcript.fullText.count == expectedCount)
            #expect(transcript.captions.count == expectedCount)
            #expect(transcript.fullText.allSatisfy { $0.english?.isEmpty == false })
            #expect(transcript.captions.allSatisfy { $0.english?.isEmpty == false })
            #expect(transcript.fullText.map(\.text) != transcript.captions.map(\.text))
            #expect(transcript.fullText.map(\.start) != transcript.captions.map(\.start))
            #expect(transcript.fullText.first?.english == "Amen.")
        }
    }
}
