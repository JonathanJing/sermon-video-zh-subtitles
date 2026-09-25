import Foundation
import Testing
@testable import TongxingCore

struct MultilingualCatalogTests {
    private let hashA = String(repeating: "a", count: 64)
    private let hashB = String(repeating: "b", count: 64)

    private func catalogData(change: (inout [String: Any]) -> Void = { _ in }) throws -> Data {
        var value: [String: Any] = [
            "schemaVersion": "sermon-multilingual-catalog-v2",
            "generatedAt": "2026-09-21T00:00:00Z",
            "defaultPageId": "page-1",
            "pages": [[
                "id": "page-1", "date": "2026-09-21", "sourceLocale": "en",
                "sourceIdentitySha256": hashA, "defaultTargetLocale": "zh-Hans",
                "targets": [
                    "zh-Hans": [
                        "releasePackageUrl": "/releases/page-1/zh-Hans.json",
                        "releasePackageJsonSha256": hashB, "contentStatus": "human_reviewed",
                        "audioStatus": "human_reviewed", "capabilities": ["text", "captions", "audio", "download"],
                    ],
                    "ko": [
                        "releasePackageUrl": "/releases/page-1/ko.json",
                        "releasePackageJsonSha256": hashA, "contentStatus": "human_reviewed",
                        "audioStatus": "unavailable", "capabilities": ["text"],
                    ],
                ],
            ]],
        ]
        change(&value)
        return try JSONSerialization.data(withJSONObject: value)
    }

    private func releaseData(locale: String = "ko", audioAvailable: Bool = false) throws -> Data {
        let value: [String: Any] = [
            "schemaVersion": "sermon-target-language-release-package-v1",
            "packageId": "page-1-\(locale)", "pageId": "page-1", "sourceLocale": "en",
            "targetLocale": locale, "targetLanguageCandidateJsonSha256": hashA,
            "targetLanguageAudioPackageJsonSha256": audioAvailable ? hashB : NSNull(),
            "status": "published_http_verified", "contentStatus": "human_reviewed",
            "audioStatus": audioAvailable ? "human_reviewed" : "unavailable",
            "interfaceLocale": locale, "contentLocale": locale,
            "audioLocale": audioAvailable ? locale : NSNull(),
            "assets": [
                ["role": "page", "path": "/pages/page-1/\(locale)/index.html", "sha256": hashA],
            ] + (audioAvailable ? [["role": "audio", "path": "/media/\(locale).mp3", "sha256": hashB]] : []),
            "httpVerification": ["status": "pass", "evidenceSha256": hashB],
            "deviceAcceptance": ["status": "not_run", "evidenceSha256": NSNull()],
            "venueAcceptance": ["status": "not_run", "evidenceSha256": NSNull()],
            "issues": [],
        ]
        return try JSONSerialization.data(withJSONObject: value)
    }

    @Test func catalogKeepsContentAndAudioCapabilitiesDistinct() throws {
        let catalog = try MultilingualCatalog.decode(catalogData())
        let page = catalog.defaultPage
        #expect(page.publishedTargets.map(\.locale) == ["ko", "zh-Hans"])
        #expect(page.targets["ko"]?.audioStatus == "unavailable")
        #expect(page.targets["ko"]?.capabilities == [.text])
        #expect(page.targets["zh-Hans"]?.capabilities.contains(.audio) == true)
        #expect(try page.targets["ko"]?.packageURL(relativeTo: URL(string: "https://example.org")!).path
                == "/releases/page-1/ko.json")
    }

    @Test func independentlyPublishedPagesKeepTheirOwnLocales() throws {
        let catalog = try MultilingualCatalog.decode(catalogData { root in
            var pages = root["pages"] as! [[String: Any]]
            pages.append([
                "id": "clip-2", "date": "2026-09-24", "sourceLocale": "en",
                "sourceIdentitySha256": hashB, "defaultTargetLocale": "es",
                "targets": ["es": [
                    "releasePackageUrl": "/releases/clip-2/es.json",
                    "releasePackageJsonSha256": hashA, "contentStatus": "human_reviewed",
                    "audioStatus": "unavailable", "capabilities": ["text"],
                ]],
            ])
            root["pages"] = pages
        })
        #expect(catalog.defaultPage.id == "page-1")
        #expect(catalog.pages.map(\.id) == ["page-1", "clip-2"])
        #expect(catalog.pages[0].publishedTargets.map(\.locale) == ["ko", "zh-Hans"])
        #expect(catalog.pages[1].publishedTargets.map(\.locale) == ["es"])
        #expect(try catalog.pages[1].targets["es"]?.packageURL(relativeTo: URL(string: "https://example.org")!).path
                == "/releases/clip-2/es.json")
    }

    @Test(.enabled(if: ProcessInfo.processInfo.environment["TONGXING_MULTILINGUAL_CATALOG_SMOKE_PATH"] != nil))
    func frozenPublishedCatalogDecodesInNativeClient() throws {
        guard let path = ProcessInfo.processInfo.environment["TONGXING_MULTILINGUAL_CATALOG_SMOKE_PATH"] else {
            return
        }
        let catalog = try MultilingualCatalog.decode(Data(contentsOf: URL(fileURLWithPath: path)))
        #expect(catalog.pages.contains { $0.id == catalog.defaultPageId })
        #expect(catalog.pages.allSatisfy { !$0.publishedTargets.isEmpty })
    }

    @Test func publishedPageFingerprintRequiresExactSourceAndTrack() throws {
        let catalog = try MultilingualCatalog.decode(catalogData { root in
            var pages = root["pages"] as! [[String: Any]], page = pages[0]
            page["sourceMediaSha256"] = hashA
            var targets = page["targets"] as! [String: Any]
            var chinese = targets["zh-Hans"] as! [String: Any]
            chinese["capabilities"] = ["text", "captions", "audio", "alignment"]
            chinese["audioFingerprint"] = [
                "schemaVersion": "sermon-audio-fingerprint-binding-v1", "pageId": "page-1",
                "sourceSha256": hashA, "trackSha256": hashB,
                "sourceStartSeconds": 0, "sourceEndSeconds": 138,
                "algorithmVersion": "spectral-landmarks-v1", "captureSeconds": 10,
                "indexSha256": hashA, "indexUrl": "/fingerprints/aaaaaaaaaaaaaaaa-landmarks.json",
            ] as [String: Any]
            targets["zh-Hans"] = chinese; page["targets"] = targets; pages[0] = page; root["pages"] = pages
        })
        let page = catalog.defaultPage
        let binding = try #require(page.targets["zh-Hans"]?.audioFingerprint)
        try binding.validate(page: page, locale: "zh-Hans", trackSha256: hashB, durationSeconds: 138.004)
        #expect(throws: (any Error).self) {
            try binding.validate(page: page, locale: "zh-Hans", trackSha256: hashA, durationSeconds: 138)
        }
        #expect(throws: (any Error).self) {
            try binding.validate(page: page, locale: "ko", trackSha256: hashB, durationSeconds: 138)
        }
    }

    @Test func catalogRejectsLocaleKeyPathAndCapabilityMismatches() throws {
        #expect(throws: (any Error).self) {
            try MultilingualCatalog.decode(catalogData { root in
                var pages = root["pages"] as! [[String: Any]], page = pages[0]
                var targets = page["targets"] as! [String: Any]
                var korean = targets["ko"] as! [String: Any]
                korean["releasePackageUrl"] = "/releases/page-1/zh-Hans.json"
                targets["ko"] = korean; page["targets"] = targets; pages[0] = page; root["pages"] = pages
            })
        }
        #expect(throws: (any Error).self) {
            try MultilingualCatalog.decode(catalogData { root in
                var pages = root["pages"] as! [[String: Any]], page = pages[0]
                var targets = page["targets"] as! [String: Any]
                var korean = targets["ko"] as! [String: Any]
                korean["capabilities"] = ["text", "audio"]
                targets["ko"] = korean; page["targets"] = targets; pages[0] = page; root["pages"] = pages
            })
        }
    }

    @Test func releasePackageRoutesOnlyToSameOriginPublishedPage() throws {
        let package = try TargetLanguageReleasePackage.decode(releaseData())
        let pageURL = try package.pageURL(relativeTo: URL(string: "https://dev.example")!)
        #expect(pageURL.absoluteString == "https://dev.example/pages/page-1/ko/index.html")
        #expect(throws: (any Error).self) {
            try TargetLanguageReleasePackage.decode(releaseData()).pageURL(relativeTo: URL(string: "http://dev.example")!)
        }
    }

    @Test func unavailableAudioCannotExposeAnAudioAsset() throws {
        var value = try #require(JSONSerialization.jsonObject(with: releaseData()) as? [String: Any])
        var assets = value["assets"] as! [[String: Any]]
        assets.append(["role": "audio", "path": "/media/ko.mp3", "sha256": hashB])
        value["assets"] = assets
        #expect(throws: (any Error).self) {
            try TargetLanguageReleasePackage.decode(JSONSerialization.data(withJSONObject: value))
        }
    }

    @Test func unavailableAudioMayBindSameLocaleLayer3Package() throws {
        var value = try #require(JSONSerialization.jsonObject(with: releaseData()) as? [String: Any])
        value["targetLanguageAudioPackageJsonSha256"] = hashB
        let package = try TargetLanguageReleasePackage.decode(JSONSerialization.data(withJSONObject: value))
        #expect(package.targetLanguageAudioPackageJsonSha256 == hashB)
        #expect(package.audioLocale == nil)
    }

    @Test func devContentCandidateNeedsExplicitOptInAndExactPath() throws {
        var value = try #require(JSONSerialization.jsonObject(with: releaseData()) as? [String: Any])
        value["status"] = "candidate"
        value["httpVerification"] = ["status": "not_run", "evidenceSha256": NSNull()]
        value["assets"] = [["role": "content", "path": "/content/page-1/ko.json", "sha256": hashA]]
        let data = try JSONSerialization.data(withJSONObject: value)
        #expect(throws: (any Error).self) { try TargetLanguageReleasePackage.decode(data) }
        let candidate = try TargetLanguageReleasePackage.decode(data, allowDevCandidate: true)
        #expect(try candidate.contentURL(relativeTo: URL(string: "https://dev.example")!).path
                == "/content/page-1/ko.json")
        value["assets"] = [["role": "content", "path": "/content/other/ko.json", "sha256": hashA]]
        #expect(throws: (any Error).self) {
            try TargetLanguageReleasePackage.decode(JSONSerialization.data(withJSONObject: value), allowDevCandidate: true)
        }
    }
}
