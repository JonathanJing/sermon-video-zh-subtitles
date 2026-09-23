#if DEBUG
import CryptoKit
import Foundation
import SwiftUI
import TongxingCore

/// Explicit UI-test launch only. No global URLProtocol registration, production
/// state writes, preloaded downloads, or AVPlayer substitutions are involved.
enum UITestLaunch {
    static var isEnabled: Bool { ProcessInfo.processInfo.arguments.contains("--ui-testing") }

    @MainActor static func makeModel() -> AppModel? {
        guard isEnabled else { return nil }
        guard let value = ProcessInfo.processInfo.environment["TONGXING_UI_TEST_RUN_ID"],
              let runID = UUID(uuidString: value) else {
            preconditionFailure("UI tests must provide an isolated TONGXING_UI_TEST_RUN_ID UUID")
        }
        let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
            .appendingPathComponent("Tongxing-UITests", isDirectory: true)
            .appendingPathComponent(runID.uuidString, isDirectory: true)
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [UITestContentProtocol.self]
        configuration.urlCache = nil
        return AppModel(supportDirectory: support, contentOrigin: UITestContent.origin,
                        session: URLSession(configuration: configuration))
    }
}

struct UITestTextSize: ViewModifier {
    @Environment(\.dynamicTypeSize) private var inheritedSize

    func body(content: Content) -> some View {
        content.environment(\.dynamicTypeSize,
            UITestLaunch.isEnabled && ProcessInfo.processInfo.arguments.contains("--ui-testing-large-text")
                ? .accessibility3 : inheritedSize)
    }
}

private enum UITestContent {
    static let origin = URL(string: "https://tongxing-ui-fixture.example.test")!

    // One independently decodable silent MPEG-2.5 Layer III frame: 8 kHz,
    // 8 kbps, 576 samples, no bit reservoir. Generated from FFmpeg anullsrc
    // with libmp3lame -reservoir 0 -write_xing 0 -id3v2_version 0.
    // Repeating it produces valid MP3 bytes without a checked-in media asset.
    private static let silentFrame = Data(base64Encoded:
        "/+MYxAAAAANIAAAAAExBTUU0LjAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")!

    static let responses: [String: Data] = {
        func audio(frameCount: Int) -> Data {
            var result = Data(capacity: silentFrame.count * frameCount)
            for _ in 0..<frameCount { result.append(silentFrame) }
            return result
        }
        let firstAudio = audio(frameCount: 500)
        let secondAudio = audio(frameCount: 667)
        func track(id: String, label: String, data: Data, duration: Double) -> SermonTrack {
            SermonTrack(id: id, label: label, voiceLabel: "自动化静音夹具",
                audioUrl: "/media/\(id).mp3", file: "\(id).mp3",
                sha256: SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined(),
                durationSeconds: duration,
                cues: [
                    SubtitleCue(start: 0, end: 12, text: "\(label)：第一句，用于验证选轨。", blockId: "0"),
                    SubtitleCue(start: 12, end: 24, text: "\(label)：第二句，用于验证时间定位。", blockId: "1"),
                    SubtitleCue(start: 24, end: duration, text: "\(label)：第三句，用于验证继续收听。", blockId: "2")
                ], subtitleTiming: "synthetic-ui-test-fixture", scope: "full_candidate")
        }
        let catalog = try! WeeklyCatalog(defaultWeekId: "ui-test-week", weeks: [
            SermonWeek(id: "ui-test-week", date: "2026-09-06", sourceId: "ui-test-source",
                sourceUrl: "https://example.test/synthetic-ui-test", title: "界面测试证道",
                speaker: "静音夹具", scripture: "自动化验证",
                tracks: [track(id: "fixture-first", label: "甲音轨", data: firstAudio, duration: 36),
                         track(id: "fixture-second", label: "乙音轨", data: secondAudio, duration: 48.024)],
                contentReview: "合成测试数据，无真实证道内容或审核声明。",
                audioNotice: "仅用于界面自动化的本地静音夹具，不是证道内容。",
                transcript: BilingualTranscript(blocks: [
                    .init(blockId: "0", english: "First synthetic source sentence for UI testing.", sourceTextOrigin: "synthetic-fixture", reviewState: "candidate"),
                    .init(blockId: "1", english: "Second synthetic source sentence for seek testing.", sourceTextOrigin: "synthetic-fixture", reviewState: "candidate"),
                    .init(blockId: "2", english: "Third synthetic source sentence for continued listening.", sourceTextOrigin: "synthetic-fixture", reviewState: "candidate")
                ])),
            SermonWeek(id: "ui-test-past-week", date: "2026-08-30", sourceId: "ui-test-past-source",
                sourceUrl: "https://example.test/synthetic-ui-past", title: "往期界面测试证道",
                speaker: "静音夹具", scripture: "自动化验证",
                tracks: [track(id: "fixture-first", label: "甲音轨", data: firstAudio, duration: 36)],
                contentReview: "合成测试数据，无真实证道内容或审核声明。")
        ])
        func pageHTML(locale: String) -> Data {
            let title = locale == "ko" ? "한국어 검증 페이지" : (locale == "en" ? "English verified page" : "中文验证页面")
            return Data("<html lang=\"\(locale)\"><body><h1>\(title)</h1><p>UI fixture only</p></body></html>".utf8)
        }
        func hash(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }
        func release(locale: String) -> Data {
            let candidateHash = String(repeating: "a", count: 64)
            let value: [String: Any] = [
                "schemaVersion": "sermon-target-language-release-package-v1",
                "packageId": "ui-test-week-\(locale)", "pageId": "ui-test-week", "sourceLocale": "en",
                "targetLocale": locale, "targetLanguageCandidateJsonSha256": candidateHash,
                "targetLanguageAudioPackageJsonSha256": NSNull(), "status": "published_http_verified",
                "contentStatus": "human_reviewed", "audioStatus": "unavailable",
                "interfaceLocale": locale, "contentLocale": locale, "audioLocale": NSNull(),
                "assets": [["role": "page", "path": "/pages/ui-test-week/\(locale)/index.html", "sha256": hash(pageHTML(locale: locale))]],
                "httpVerification": ["status": "pass", "evidenceSha256": candidateHash],
                "deviceAcceptance": ["status": "not_run", "evidenceSha256": NSNull()],
                "venueAcceptance": ["status": "not_run", "evidenceSha256": NSNull()], "issues": [],
            ]
            return try! JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
        }
        let chineseRelease = release(locale: "zh-Hans"), koreanRelease = release(locale: "ko")
        let englishRelease = release(locale: "en")
        let includeEnglish = ProcessInfo.processInfo.arguments.contains("--ui-testing-published-english")
        let sourceHash = String(repeating: "b", count: 64)
        var targets: [String: Any] = [
            "zh-Hans": ["releasePackageUrl": "/releases/ui-test-week/zh-Hans.json",
                        "releasePackageJsonSha256": hash(chineseRelease), "contentStatus": "human_reviewed",
                        "audioStatus": "unavailable", "capabilities": ["text"]],
            "ko": ["releasePackageUrl": "/releases/ui-test-week/ko.json",
                   "releasePackageJsonSha256": hash(koreanRelease), "contentStatus": "human_reviewed",
                   "audioStatus": "unavailable", "capabilities": ["text"]],
        ]
        if includeEnglish {
            targets["en"] = ["releasePackageUrl": "/releases/ui-test-week/en.json",
                             "releasePackageJsonSha256": hash(englishRelease), "contentStatus": "human_reviewed",
                             "audioStatus": "unavailable", "capabilities": ["text"]]
        }
        let multilingual: [String: Any] = [
            "schemaVersion": "sermon-multilingual-catalog-v2", "generatedAt": "2026-09-21T00:00:00Z",
            "defaultPageId": "ui-test-week", "pages": [[
                "id": "ui-test-week", "date": "2026-09-06", "sourceLocale": "en",
                "sourceIdentitySha256": sourceHash, "defaultTargetLocale": "zh-Hans", "targets": targets,
            ]],
        ]
        var responses = ["/weekly.json": try! JSONEncoder().encode(catalog),
                "/multilingual.json": try! JSONSerialization.data(withJSONObject: multilingual, options: [.sortedKeys]),
                "/releases/ui-test-week/zh-Hans.json": chineseRelease,
                "/releases/ui-test-week/ko.json": koreanRelease,
                "/pages/ui-test-week/zh-Hans/index.html": pageHTML(locale: "zh-Hans"),
                "/pages/ui-test-week/ko/index.html": pageHTML(locale: "ko"),
                "/media/fixture-first.mp3": firstAudio,
                "/media/fixture-second.mp3": secondAudio]
        if ProcessInfo.processInfo.arguments.contains("--ui-testing-dev-preview") {
            let demoTargets = ["en", "ko", "zh-Hans"].reduce(into: [String: Any]()) { result, locale in
                result[locale] = ["releasePackageUrl": "/releases/ui-test-week/\(locale).json",
                                  "contentStatus": "machine_review_pass_human_review_pending",
                                  "audioStatus": "candidate", "machineScreening": "pass"]
            }
            let demo: [String: Any] = [
                "schemaVersion": "sermon-multilingual-demo-catalog-v1", "environment": "development",
                "poc": true, "defaultPageId": "ui-test-week",
                "pages": [["id": "ui-test-week", "defaultTargetLocale": "zh-Hans", "targets": demoTargets]],
            ]
            responses["/multilingual.json"] = try! JSONSerialization.data(withJSONObject: demo)
            for locale in ["en", "ko", "zh-Hans"] {
                let release: [String: Any] = [
                    "schemaVersion": locale == "en" ? "sermon-source-language-demo-package-v1" :
                        "sermon-target-language-demo-package-v1",
                    "environment": "development", "poc": true, "productionEligible": false,
                    "humanApproval": false, "pageId": "ui-test-week", "targetLocale": locale,
                    "contentStatus": "machine_review_pass_human_review_pending", "audioStatus": "candidate",
                    "pageUrl": "/pages/ui-test-week/\(locale)",
                ]
                responses["/releases/ui-test-week/\(locale).json"] = try! JSONSerialization.data(withJSONObject: release)
            }
        }
        if includeEnglish {
            responses["/releases/ui-test-week/en.json"] = englishRelease
            responses["/pages/ui-test-week/en/index.html"] = pageHTML(locale: "en")
        }
        return responses
    }()
}

/// This transport belongs only to the explicitly constructed fixture session.
/// Offline launch reports a real URLSession error; the production repositories
/// must recover from their own previously written cache and verified audio.
private final class UITestContentProtocol: URLProtocol {
    private static let requestLock = NSLock()
    private static var multilingualRequestCount = 0

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        guard let url = request.url, url.scheme == "https", url.host == UITestContent.origin.host else {
            client?.urlProtocol(self, didFailWithError: URLError(.unsupportedURL))
            return
        }
        guard !ProcessInfo.processInfo.arguments.contains("--ui-testing-offline") else {
            client?.urlProtocol(self, didFailWithError: URLError(.notConnectedToInternet))
            return
        }
        guard var data = UITestContent.responses[url.path] else {
            client?.urlProtocol(self, didFailWithError: URLError(.fileDoesNotExist))
            return
        }
        if url.path == "/multilingual.json",
           ProcessInfo.processInfo.arguments.contains("--ui-testing-revoke-korean-on-refresh") {
            Self.requestLock.lock()
            Self.multilingualRequestCount += 1
            let isRefresh = Self.multilingualRequestCount > 1
            Self.requestLock.unlock()
            if isRefresh,
               var document = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
               var pages = document["pages"] as? [[String: Any]], !pages.isEmpty,
               var targets = pages[0]["targets"] as? [String: Any] {
                targets.removeValue(forKey: "ko")
                pages[0]["targets"] = targets
                document["pages"] = pages
                data = (try? JSONSerialization.data(withJSONObject: document, options: [.sortedKeys])) ?? data
            }
        }
        if url.path.hasPrefix("/media/"),
           ProcessInfo.processInfo.arguments.contains("--ui-testing-delay-download") {
            Thread.sleep(forTimeInterval: 3)
        }
        let response = HTTPURLResponse(url: url, statusCode: 200, httpVersion: "HTTP/1.1",
            headerFields: ["Content-Length": String(data.count),
                           "Content-Type": url.path.hasSuffix(".json") ? "application/json" :
                               (url.path.hasSuffix(".html") ? "text/html; charset=utf-8" : "audio/mpeg")])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: data)
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}
#endif
