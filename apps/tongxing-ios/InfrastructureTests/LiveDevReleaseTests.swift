import Foundation
import Testing
import TongxingCore
@testable import TongxingInfrastructure

/// Opt-in verification against the actual Firebase Dev publication.
@Suite(.enabled(if: ProcessInfo.processInfo.environment["TONGXING_LIVE_DEV_SMOKE"] == "1"))
struct LiveDevReleaseTests {
    @Test func secondClipCatalogPagesAndAudioAreReadable() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let origin = URL(string: "https://ai-for-god-sermon-audio-dev.web.app")!
        let repository = MultilingualCatalogRepository(origin: origin, cacheDirectory: root,
                                                       allowDevCandidate: true)
        let catalog = try await repository.loadCatalog().catalog
        #expect(catalog.pages.count >= 2)
        let page = try #require(catalog.pages.first { $0.id == "2026-09-20-laodicea-clip" })
        #expect(Set(page.publishedTargets.map(\.locale)) == Set(["zh-Hans", "ko", "es"]))
        for locale in ["zh-Hans", "ko", "es"] {
            let release = try await repository.loadRelease(page: page, locale: locale)
            #expect(release.status == "candidate")
            let verifiedPage = try await repository.loadPage(for: release)
            #expect(verifiedPage.html.contains("<html"))
            #expect(verifiedPage.html.contains("Dev POC"))
            let audio = try await repository.loadAudio(for: release, page: page)
            #expect(audio.locale == locale)
            #expect(audio.sha256 == release.assets.first { $0.role == .audio }?.sha256)
        }
    }
}

struct FormalDevContentPageTests {
    @Test func reviewedContentEscapesMarkupAndRejectsWrongLocale() throws {
        let hash = String(repeating: "a", count: 64)
        let release: [String: Any] = [
            "schemaVersion": "sermon-target-language-release-package-v1", "packageId": "page-1-ko",
            "pageId": "page-1", "sourceLocale": "en", "targetLocale": "ko",
            "targetLanguageCandidateJsonSha256": hash,
            "targetLanguageAudioPackageJsonSha256": NSNull(), "status": "candidate",
            "contentStatus": "human_reviewed", "audioStatus": "unavailable",
            "interfaceLocale": "ko", "contentLocale": "ko", "audioLocale": NSNull(),
            "assets": [["role": "content", "path": "/content/page-1/ko.json", "sha256": hash]],
            "httpVerification": ["status": "not_run", "evidenceSha256": NSNull()],
            "deviceAcceptance": ["status": "not_run", "evidenceSha256": NSNull()],
            "venueAcceptance": ["status": "not_run", "evidenceSha256": NSNull()], "issues": [],
        ]
        let package = try TongxingCore.TargetLanguageReleasePackage.decode(
            JSONSerialization.data(withJSONObject: release), allowDevCandidate: true)
        var content: [String: Any] = [
            "schemaVersion": "sermon-formal-dev-content-v1", "pageId": "page-1",
            "sourceLocale": "en", "locale": "ko", "targetLanguageCandidateJsonSha256": hash,
            "targetLanguageAudioPackageJsonSha256": NSNull(), "contentStatus": "human_reviewed",
            "audioStatus": "unavailable", "series": "Series", "title": "<script>alert(1)</script>",
            "speaker": "Speaker", "scripture": "Rev 3:16", "summary": "<b>summary</b>",
            "date": "2026-09-24", "durationSeconds": 10.0,
            "outline": [["title": "1", "body": "<outline>"]],
            "cues": [["start": 0.0, "end": 9.0, "text": "<cue>"]],
        ]
        let page = try FormalDevContentPage.decode(JSONSerialization.data(withJSONObject: content), package: package)
        #expect(page.html.contains("&lt;script&gt;"))
        #expect(!page.html.contains("<script>"))
        #expect(page.html.contains("&lt;cue&gt;"))
        content["locale"] = "es"
        #expect(throws: (any Error).self) {
            try FormalDevContentPage.decode(JSONSerialization.data(withJSONObject: content), package: package)
        }
    }
}
