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
        let spanishAudio = audio(frameCount: 550)
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
                ]))
        ])
        func page(pageID: String, locale: String) -> Data {
            Data("<html><head><title>\(pageID) \(locale)</title></head><body><h1>\(pageID) · \(locale)</h1></body></html>".utf8)
        }
        func release(pageID: String, locale: String, audio: Data? = nil) -> Data {
            let hash = String(repeating: "a", count: 64)
            let pageHash = SHA256.hash(data: page(pageID: pageID, locale: locale)).map { String(format: "%02x", $0) }.joined()
            let audioHash = audio.map { SHA256.hash(data: $0).map { String(format: "%02x", $0) }.joined() }
            let assets: [[String: Any]] = [["role": "page", "path": "/pages/\(pageID)/\(locale)/index.html", "sha256": pageHash]]
                + (audioHash.map { [["role": "audio", "path": "/media/\(pageID)/\(locale).mp3", "sha256": $0]] } ?? [])
            let value: [String: Any] = [
                "schemaVersion": "sermon-target-language-release-package-v1",
                "packageId": "\(pageID)-\(locale)", "pageId": pageID, "sourceLocale": "en",
                "targetLocale": locale, "targetLanguageCandidateJsonSha256": hash,
                "targetLanguageAudioPackageJsonSha256": audio == nil ? NSNull() : hash as Any,
                "status": "published_http_verified", "contentStatus": "human_reviewed",
                "audioStatus": audio == nil ? "unavailable" : "human_reviewed",
                "interfaceLocale": locale, "contentLocale": locale, "audioLocale": audio == nil ? NSNull() : locale as Any,
                "assets": assets,
                "httpVerification": ["status": "pass", "evidenceSha256": hash],
                "deviceAcceptance": ["status": "not_run", "evidenceSha256": NSNull()],
                "venueAcceptance": ["status": "not_run", "evidenceSha256": NSNull()], "issues": [],
            ]
            return try! JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
        }
        let chineseRelease = release(pageID: "ui-test-week", locale: "zh-Hans")
        let koreanRelease = release(pageID: "ui-test-week", locale: "ko")
        let spanishRelease = release(pageID: "ui-test-clip", locale: "es", audio: spanishAudio)
        func hash(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }
        let sourceHash = String(repeating: "b", count: 64)
        let multilingual: [String: Any] = [
            "schemaVersion": "sermon-multilingual-catalog-v2", "generatedAt": "2026-09-21T00:00:00Z",
            "defaultPageId": "ui-test-week", "pages": [[
                "id": "ui-test-week", "date": "2026-09-06", "sourceLocale": "en",
                "sourceIdentitySha256": sourceHash, "defaultTargetLocale": "zh-Hans", "targets": [
                    "zh-Hans": ["releasePackageUrl": "/releases/ui-test-week/zh-Hans.json",
                                "releasePackageJsonSha256": hash(chineseRelease), "contentStatus": "human_reviewed",
                                "audioStatus": "unavailable", "capabilities": ["text"]],
                    "ko": ["releasePackageUrl": "/releases/ui-test-week/ko.json",
                           "releasePackageJsonSha256": hash(koreanRelease), "contentStatus": "human_reviewed",
                           "audioStatus": "unavailable", "capabilities": ["text"]],
                ],
            ], [
                "id": "ui-test-clip", "date": "2026-09-24", "sourceLocale": "en",
                "sourceIdentitySha256": sourceHash, "defaultTargetLocale": "es", "targets": [
                    "es": ["releasePackageUrl": "/releases/ui-test-clip/es.json",
                           "releasePackageJsonSha256": hash(spanishRelease), "contentStatus": "human_reviewed",
                           "audioStatus": "human_reviewed", "capabilities": ["text", "audio"]],
                ],
            ]],
        ]
        let demoPrefix = "/voice-demos/2026-09-21-v2"
        let demoSpeakers: [[String: Any]] = (0..<6).map { index in
            let speaker = "speaker_\(index)"
            let original: [String: Any] = [
                "path": "\(demoPrefix)/\(speaker)/en-original.mp3",
                "sha256": String(repeating: "c", count: 64), "bytes": 100,
                "text": "Synthetic English reference.",
                "transcriptStatus": "machine_screening_only",
                "sourceUrl": "https://example.test/sermon/\(index)",
            ]
            let samples: [[String: Any]] = ["zh-Hans", "ko", "es", "vi"].map { locale in
                ["path": "\(demoPrefix)/\(speaker)/\(locale).mp3",
                 "sha256": String(repeating: "d", count: 64), "bytes": 100,
                 "locale": locale, "text": "Synthetic sample.",
                 "humanListeningStatus": "pending"]
            }
            return ["speakerId": speaker, "displayName": "Synthetic speaker \(index)",
                    "original": original, "samples": samples]
        }
        let demos = try! JSONSerialization.data(withJSONObject: [
            "schemaVersion": "sermon-multilingual-voice-demo-public-v1",
            "status": "audition_demo",
            "sourceScope": "voice_capability_audition_not_sermon_translation",
            "humanListeningStatus": "pending", "speakerCount": 6, "sampleCount": 24,
            "speakers": demoSpeakers,
        ], options: [.sortedKeys])
        return ["/weekly.json": try! JSONEncoder().encode(catalog),
                "/multilingual-v2.json": try! JSONSerialization.data(withJSONObject: multilingual, options: [.sortedKeys]),
                "\(demoPrefix)/catalog.json": demos,
                "/releases/ui-test-week/zh-Hans.json": chineseRelease,
                "/releases/ui-test-week/ko.json": koreanRelease,
                "/releases/ui-test-clip/es.json": spanishRelease,
                "/pages/ui-test-week/zh-Hans/index.html": page(pageID: "ui-test-week", locale: "zh-Hans"),
                "/pages/ui-test-week/ko/index.html": page(pageID: "ui-test-week", locale: "ko"),
                "/pages/ui-test-clip/es/index.html": page(pageID: "ui-test-clip", locale: "es"),
                "/media/fixture-first.mp3": firstAudio,
                "/media/fixture-second.mp3": secondAudio,
                "/media/ui-test-clip/es.mp3": spanishAudio]
    }()
}

/// This transport belongs only to the explicitly constructed fixture session.
/// Offline launch reports a real URLSession error; the production repositories
/// must recover from their own previously written cache and verified audio.
private final class UITestContentProtocol: URLProtocol {
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
        guard let data = UITestContent.responses[url.path] else {
            client?.urlProtocol(self, didFailWithError: URLError(.fileDoesNotExist))
            return
        }
        let response = HTTPURLResponse(url: url, statusCode: 200, httpVersion: "HTTP/1.1",
            headerFields: ["Content-Length": String(data.count),
                           "Content-Type": url.path.hasSuffix(".json") ? "application/json" : "audio/mpeg"])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: data)
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}
#endif
