import Foundation
import Testing
import TongxingCore
@testable import TongxingInfrastructure

/// Real production JSON readback only. This does not prove device playback or
/// microphone/venue acceptance, and never downloads the full video or audio.
@Suite(.enabled(if: ProcessInfo.processInfo.environment["TONGXING_LIVE_SMOKE"] == "1"))
struct LivePublishedTranscriptTests {
    @Test func currentMixedSourceChineseFullTextAndCaptionsIncludeEditionEnglish() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let repository = MultilingualCatalogRepository(
            origin: URL(string: "https://ai-for-god-sermon-audio.web.app")!, cacheDirectory: root)
        let loaded = try await repository.loadCatalog()
        if let error = loaded.mixedSourceCatalogError { print("v5 fallback reason: \(error)") }
        let catalog = loaded.catalog
        #expect(catalog.schemaVersion == MultilingualCatalog.mixedSourceSchemaVersion)
        let page = try #require(catalog.pages.first { $0.id == "resi-20261018-15030286" })
        let target = try #require(page.targets["zh-Hans"])
        let source = try target.sourceBinding(in: page)
        #expect(source.familyPageId == "resi-20261018-15030286")
        #expect(source.editionId == "resi-20261018-broadcast")
        let release = try await repository.loadRelease(page: page, locale: "zh-Hans")
        #expect(release.pageId == source.editionId)
        let transcript = try await repository.loadPublishedTranscript(for: release, page: page)
        #expect(transcript.pageID == page.id)
        #expect(transcript.editionID == source.editionId)
        #expect(transcript.locale == "zh-Hans")
        #expect(transcript.fullText.count == 416)
        #expect(transcript.captions.count == 416)
        #expect(transcript.fullText.allSatisfy { $0.english?.isEmpty == false })
        #expect(transcript.captions.allSatisfy { $0.english?.isEmpty == false })
        #expect(transcript.fullText.first?.english?.isEmpty == false)
        #expect(transcript.captions.first?.english?.isEmpty == false)
    }
}
