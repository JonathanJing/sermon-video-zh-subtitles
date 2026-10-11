#if DEBUG
import CryptoKit
import Dispatch
import Foundation
import SwiftUI
import TongxingCore

/// Explicit UI-test launch only. No global URLProtocol registration, production
/// state writes, preloaded downloads, or AVPlayer substitutions are involved.
enum UITestLaunch {
    static var isEnabled: Bool { ProcessInfo.processInfo.arguments.contains("--ui-testing") }

    static func liveActivitySmokeEnabled(arguments: [String] = ProcessInfo.processInfo.arguments) -> Bool {
        arguments.contains("--ui-testing") && arguments.contains("--ui-testing-live-activity")
    }

    @MainActor static func makeModel() -> AppModel? {
        guard isEnabled else { return nil }
        guard let value = ProcessInfo.processInfo.environment["TONGXING_UI_TEST_RUN_ID"],
              let runID = UUID(uuidString: value) else {
            preconditionFailure("UI tests must provide an isolated TONGXING_UI_TEST_RUN_ID UUID")
        }
        let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
            .appendingPathComponent("Tongxing-UITests", isDirectory: true)
            .appendingPathComponent(runID.uuidString, isDirectory: true)
        return makeFixtureModel(supportDirectory: support,
            statisticsDefaults: UserDefaults(suiteName: "Tongxing-UITests-\(runID.uuidString)")!,
            nativePublishedPage: ProcessInfo.processInfo.arguments.contains("--ui-testing-notification"))
    }

    static func voiceDemoFixture() throws -> VoiceDemoCatalog {
        try VoiceDemoCatalog.validatedClips(UITestContent.responses["/voice-demos/speaker-clips-v2/preview-catalog.json"]!)
    }

    /// Explicit system-UI smoke only: synthetic media, no microphone or network.
    /// Unlike ordinary UI tests, this launch opts into real ActivityKit.
    @MainActor static func runLiveActivitySmoke(in model: AppModel) async {
        guard liveActivitySmokeEnabled(),
              let week = model.weeks.first else { return }
        await model.select(week: week)
        model.downloadSelected()
        do {
            for _ in 0..<100 {
                if model.playback.isReady && model.usingOfflineAudio { break }
                try await Task.sleep(for: .milliseconds(100))
            }
            guard model.playback.isReady else { return }
            for phase in [ListeningAlignmentPhase.preparing, .listening, .matching, .aligned] {
                model.playback.setAlignmentPhase(phase)
                try await Task.sleep(for: .seconds(phase == .preparing ? 1 : 6))
            }
            try await Task.sleep(for: .seconds(4))
            model.playback.setAlignmentPhase(.preparing)
            model.playback.setAlignmentPhase(.listening)
            try await Task.sleep(for: .seconds(6))
            model.playback.setAlignmentPhase(.matching)
            try await Task.sleep(for: .seconds(6))
            model.playback.setAlignmentPhase(.unmatched)
            try await Task.sleep(for: .seconds(6))
            model.playback.setAlignmentPhase(nil)
        } catch { model.playback.setAlignmentPhase(nil) }
    }

    /// Hosted render tests share the synthetic catalog/audio transport, while
    /// keeping all downloads, preferences and playback history in private state.
    @MainActor static func makeFixtureModel(supportDirectory: URL, statisticsDefaults: UserDefaults,
                                            nativePublishedPage: Bool = false, headingLanguages: Bool = false) -> AppModel {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = headingLanguages ? [HeadingLanguageContentProtocol.self]
            : nativePublishedPage ? [NativePreviewContentProtocol.self] : [UITestContentProtocol.self]
        configuration.urlCache = nil
        return AppModel(supportDirectory: supportDirectory, contentOrigin: UITestContent.origin,
                        session: URLSession(configuration: configuration),
                        statisticsDefaults: statisticsDefaults,
                        alignmentCapture: ProcessInfo.processInfo.arguments.contains("--ui-testing-alignment-failure")
                            ? UITestFailedCapture() : nil)
    }
}

/// Synthetic capture failure only in the explicitly isolated DEBUG UI fixture.
@MainActor
private final class UITestFailedCapture: MicrophoneCapturing {
    func capture(seconds: Double) async throws -> CapturedAudio {
        if !ProcessInfo.processInfo.arguments.contains("--ui-testing-alignment-failure-immediate") {
            try await Task.sleep(for: .milliseconds(250))
        }
        throw AudioAlignmentError.invalidCapture
    }
    func beginContinuousCapture(maxSeconds: Double) async throws -> any ContinuousCaptureSessionProtocol {
        if !ProcessInfo.processInfo.arguments.contains("--ui-testing-alignment-failure-immediate") {
            try await Task.sleep(for: .milliseconds(250))
        }
        throw AudioAlignmentError.invalidCapture
    }
    func cancel() {}
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
        let fixtureVideo = Data(base64Encoded: "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")!
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
                summary: "合成测试说明，用于验证大纲与默想页面。",
                outline: [OutlineSection(title: "测试大纲", points: ["测试要点"])],
                questions: ["这是用于测试的默想问题。"],
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
            "defaultPageId": ProcessInfo.processInfo.arguments.contains("--ui-testing-current-page-default")
                ? "ui-test-clip" : "ui-test-week", "pages": [[
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
                "sha256": hash(firstAudio), "bytes": firstAudio.count,
                "text": "Synthetic English reference.",
                "transcriptStatus": "machine_screening_only",
                "sourceUrl": "https://example.test/sermon/\(index)",
            ]
            let samples: [[String: Any]] = ["zh-Hans", "ko", "es", "vi"].map { locale in
                ["path": "\(demoPrefix)/\(speaker)/\(locale).mp3",
                 "sha256": hash(secondAudio), "bytes": secondAudio.count,
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
        var result: [String: Data] = ["/weekly.json": try! JSONEncoder().encode(catalog),
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
        for speaker in demoSpeakers {
            let original = speaker["original"] as! [String: Any]
            result[original["path"] as! String] = firstAudio
            for sample in speaker["samples"] as! [[String: Any]] { result[sample["path"] as! String] = secondAudio }
        }
        let clipPrefix = "/voice-demos/speaker-clips-v2"
        let english = "Synthetic English reference."
        let textHash = hash(Data(english.utf8))
        let clips: [[String: Any]] = (0..<6).map { index in
            let id = "speaker_\(index)"
            let clipID = "\(id)-fixture-v2"
            func asset(_ name: String, locale: String? = nil) -> [String: Any] {
                var value: [String: Any] = ["path": "\(clipPrefix)/\(id)/\(name).mp3",
                    "sha256": hash(firstAudio), "bytes": firstAudio.count, "durationSeconds": 36,
                    "sourceClipId": clipID, "englishTextSha256": textHash,
                    "text": locale == nil ? english : "Synthetic \(locale!) sample."]
                if let locale { value["locale"] = locale; value["humanListeningStatus"] = "pending" }
                else { value["locale"] = "en"; value["transcriptStatus"] = "machine_screening_only" }
                result[value["path"] as! String] = firstAudio
                return value
            }
            // Silent black video: synthetic UI fixture, not a sermon excerpt.
            let video: [String: Any] = ["path": "\(clipPrefix)/\(id)/source.mp4", "sha256": hash(fixtureVideo),
                "bytes": fixtureVideo.count, "durationSeconds": 36, "sourceClipId": clipID]
            result[video["path"] as! String] = fixtureVideo
            return ["speakerId": id, "displayName": "Synthetic speaker \(index)", "clipId": clipID,
                "source": ["url": "https://example.test/sermon/\(index)", "startSeconds": 100,
                    "endSeconds": 136, "englishTextSha256": textHash], "original": asset("en-original"),
                "video": video, "samples": ["zh-Hans", "ko", "es"].map { asset($0, locale: $0) }]
        }
        let clipCatalog = try! JSONSerialization.data(withJSONObject: [
                "schemaVersion": "sermon-speaker-clip-demo-catalog-v2", "status": "audition_demo",
                "sourceScope": "source_clip_translation_audition_not_sermon_release",
                "humanListeningStatus": "pending", "speakerCount": 6, "sampleCount": 18, "speakers": clips], options: [.sortedKeys])
        result["\(clipPrefix)/preview-catalog.json"] = clipCatalog
        if ProcessInfo.processInfo.arguments.contains("--ui-testing-voice-clips") { result["\(clipPrefix)/catalog.json"] = clipCatalog }
        return result
    }()

    static let dualScriptResponses = nativePublishedResponses(locale: "ko",
        fullText: "전체 원고입니다.", caption: "짧은 자막입니다.")
    static let previewResponses = nativePublishedResponses(locale: "zh-Hans",
        fullText: "这是用于检查页面布局的合成完整文稿。", caption: "这是用于预览的合成字幕。")

    /// Multi-locale timing/search fixture is opt-in and cannot affect the
    /// existing preview or catalog-routing samples.
    static let locateResponses: [String: Data] = {
        let pageID = "ui-test-locate-flow"
        let audio = responses["/media/fixture-first.mp3"]!
        let sourceHash = String(repeating: "a", count: 64)
        let spokenHash = String(repeating: "b", count: 64)
        let locales = ["zh-Hans", "ko"]
        let english = [
            "First synthetic source sentence for the opening.",
            "Listen for the lighthouse beside the harbor.",
            "Third synthetic source sentence for the ending."
        ]
        let captions = [
            "zh-Hans": ["中文第一句：开始收听。", "中文第二句：灯塔在港口旁。", "中文第三句：继续收听。"],
            "ko": ["한국어 첫 번째 문장: 듣기를 시작합니다.", "한국어 두 번째 문장: 등대는 항구 옆에 있습니다.", "한국어 세 번째 문장: 계속 듣습니다."]
        ]
        func hash(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }
        func encoded(_ value: [String: Any]) -> Data {
            try! JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
        }
        var result: [String: Data] = [:]
        var targets: [String: Any] = [:]
        var englishTargets: [String: Any] = [:]
        for locale in locales {
            let html = Data("<html><body><h1>测试英文定位证道</h1></body></html>".utf8)
            let sentences: [String] = captions[locale]!
            let rows: [[String: Any]] = (0..<3).map { (index: Int) -> [String: Any] in
                let start = Double(index * 12)
                let end = start + 12.0
                let row: [String: Any] = [
                    "textGroupId": "g\(index + 1)", "sourceUnitIds": ["u\(index + 1)"],
                    "start": start, "end": end, "text": sentences[index]
                ]
                return row
            }
            let contentValue: [String: Any] = [
                "schemaVersion": "sermon-full-video-text-content-v1", "pageId": pageID,
                "sourceLocale": "en", "targetLocale": locale, "status": "human_reviewed",
                "englishSourcePackageJsonSha256": sourceHash, "sourceMediaSha256": sourceHash,
                "targetLanguageCandidateJsonSha256": sourceHash,
                "durationSeconds": 36.0, "title": "测试英文定位证道", "cues": rows
            ]
            let content = encoded(contentValue)
            let captionData = encoded(["cues": rows])
            let assets: [[String: String]] = [
                ["role": "page", "path": "/pages/\(pageID)/\(locale)/index.html", "sha256": hash(html)],
                ["role": "content", "path": "/content/\(pageID)/\(locale).json", "sha256": hash(content)],
                ["role": "captions", "path": "/captions/\(pageID)/\(locale).json", "sha256": hash(captionData)],
                ["role": "audio", "path": "/media/\(pageID)/\(locale).mp3", "sha256": hash(audio)]
            ]
            let releaseValue: [String: Any] = [
                "schemaVersion": "sermon-target-language-release-package-v2",
                "packageId": "\(pageID)-\(locale)", "pageId": pageID,
                "sourceLocale": "en", "targetLocale": locale,
                "targetLanguageCandidateJsonSha256": sourceHash,
                "spokenTargetLanguageCandidateJsonSha256": spokenHash,
                "targetLanguageAudioPackageJsonSha256": spokenHash,
                "status": "published_http_verified", "contentStatus": "human_reviewed",
                "audioStatus": "human_reviewed", "interfaceLocale": locale,
                "contentLocale": locale, "audioLocale": locale,
                "assets": assets,
                "httpVerification": ["status": "pass", "evidenceSha256": sourceHash],
                "deviceAcceptance": ["status": "not_run", "evidenceSha256": NSNull()],
                "venueAcceptance": ["status": "not_run", "evidenceSha256": NSNull()], "issues": []
            ]
            let release = encoded(releaseValue)
            targets[locale] = [
                "releasePackageUrl": "/releases-v2/\(pageID)/\(locale).json",
                "releasePackageJsonSha256": hash(release),
                "contentStatus": "human_reviewed", "audioStatus": "human_reviewed",
                "capabilities": ["text", "captions", "audio"]
            ]
            englishTargets[locale] = [
                "contentSha256": hash(content), "captionsSha256": hash(captionData),
                "releasePackageJsonSha256": hash(release),
                "blocks": (0..<3).map { index -> [String: Any] in
                    ["textGroupId": "g\(index + 1)", "sourceUnitIds": ["u\(index + 1)"], "english": english[index]]
                }
            ]
            result["/releases-v2/\(pageID)/\(locale).json"] = release
            result["/pages/\(pageID)/\(locale)/index.html"] = html
            result["/content/\(pageID)/\(locale).json"] = content
            result["/captions/\(pageID)/\(locale).json"] = captionData
            result["/media/\(pageID)/\(locale).mp3"] = audio
        }
        result["/english-reference/\(pageID).json"] = encoded([
            "schemaVersion": "sermon-published-english-reference-v1", "pageId": pageID,
            "sourceIdentitySha256": sourceHash, "sourceMediaSha256": sourceHash,
            "reviewState": "human_approved", "targets": englishTargets
        ])
        result["/multilingual-v3.json"] = encoded([
            "schemaVersion": "sermon-multilingual-catalog-v3", "generatedAt": "2026-09-27T00:00:00Z",
            "defaultPageId": pageID,
            "pages": [["id": pageID, "title": "测试英文定位证道", "date": "2026-09-27",
                       "sourceLocale": "en", "sourceIdentitySha256": sourceHash,
                       "defaultTargetLocale": "zh-Hans", "targets": targets]]
        ])
        return result
    }()

    /// Explicit synthetic announcement fixture, isolated from published content.
    static let weeklyUpdateResponses: [String: Data] = {
        var result = locateResponses
        let catalog = try! JSONDecoder().decode(MultilingualCatalog.self, from: result["/multilingual-v3.json"]!)
        let page = catalog.defaultPage
        #if os(iOS)
        let width = 240, height = 320
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        let image = UIGraphicsImageRenderer(size: CGSize(width: 240, height: 320), format: format).pngData { context in
            UIColor.systemTeal.setFill()
            context.fill(CGRect(x: 0, y: 0, width: 240, height: 320))
            NSString(string: "UI TEST\nWEEKLY POSTER").draw(in: CGRect(x: 24, y: 90, width: 200, height: 150),
                withAttributes: [.font: UIFont.boldSystemFont(ofSize: 24), .foregroundColor: UIColor.white])
        }
        #else
        let width = 1, height = 1
        let image = Data(base64Encoded: "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a3ioAAAAASUVORK5CYII=")!
        #endif
        let hash = SHA256.hash(data: image).map { String(format: "%02x", $0) }.joined()
        let poster = WeeklyPoster(url: "/posters/ui-test.png", sha256: hash, bytes: Int64(image.count), width: width, height: height)
        let items = page.targets.map { locale, target in
            WeeklyAnnouncement(id: "ui-test-\(locale)", pageID: page.id, locale: locale,
                releaseSHA256: target.releasePackageJsonSha256, sourceIdentitySHA256: page.sourceIdentitySha256,
                title: "本周海报 · 合成交互测试", publishedAt: "2026-10-04T00:00:00Z", poster: poster)
        }
        result["/weekly-announcements-v1.json"] = try! JSONEncoder().encode(WeeklyAnnouncementCatalog(announcements: items))
        if !ProcessInfo.processInfo.arguments.contains("--ui-testing-poster-missing") {
            result["/posters/ui-test.png"] = image
        }
        return result
    }()

    static let alignmentFailureResponses: [String: Data] = {
        var result = locateResponses
        var catalog = try! JSONSerialization.jsonObject(with: result["/multilingual-v3.json"]!) as! [String: Any]
        var pages = catalog["pages"] as! [[String: Any]]
        var page = pages[0]
        var targets = page["targets"] as! [String: [String: Any]]
        let sourceHash = String(repeating: "a", count: 64)
        let trackHash = SHA256.hash(data: result["/media/ui-test-locate-flow/zh-Hans.mp3"]!).map { String(format: "%02x", $0) }.joined()
        let index = try! JSONSerialization.data(withJSONObject: [
            "schemaVersion": "sermon-landmark-index-v1", "algorithmVersion": "spectral-landmarks-v1",
            "sampleRate": 8000, "hopSize": 256, "fftSize": 1024,
            "sourceSha256": sourceHash, "trackSha256": trackHash, "pageId": "ui-test-locate-flow",
            "sourceStartSeconds": 0, "sourceEndSeconds": 36,
            "window": ["startSeconds": 0, "endSeconds": 36], "durationSeconds": 36,
            "landmarkCount": 1, "postings": ["1": [0]]
        ], options: [.sortedKeys])
        let indexHash = SHA256.hash(data: index).map { String(format: "%02x", $0) }.joined()
        let indexPath = "/fingerprints/\(indexHash.prefix(16))-landmarks.json"
        targets["zh-Hans"]!["audioFingerprint"] = [
            "schemaVersion": "sermon-audio-fingerprint-binding-v1", "pageId": "ui-test-locate-flow",
            "sourceSha256": sourceHash, "trackSha256": trackHash,
            "sourceStartSeconds": 0, "sourceEndSeconds": 36,
            "algorithmVersion": "spectral-landmarks-v1", "captureSeconds": 10,
            "indexSha256": indexHash, "indexUrl": indexPath
        ]
        targets["zh-Hans"]!["capabilities"] = ["text", "captions", "audio", "alignment"]
        page["sourceMediaSha256"] = sourceHash; page["targets"] = targets
        pages[0] = page; catalog["pages"] = pages
        result["/multilingual-v3.json"] = try! JSONSerialization.data(withJSONObject: catalog, options: [.sortedKeys])
        result[indexPath] = index
        return result
    }()

    private static func nativePublishedResponses(locale: String, fullText: String, caption: String,
                                                 pageID: String = "ui-test-full-video", title: String = "测试完整视频证道") -> [String: Data] {
        let audio = responses["/media/ui-test-clip/es.mp3"]!
        let html = Data("<html><head><style>body{font-size:20px}</style></head><body><h1>\(fullText)</h1></body></html>".utf8)
        func hash(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }
        let displayHash = String(repeating: "a", count: 64)
        let spokenHash = String(repeating: "b", count: 64)
        let content = try! JSONSerialization.data(withJSONObject: [
            "schemaVersion": "sermon-full-video-text-content-v1", "pageId": pageID,
            "sourceLocale": "en", "targetLocale": locale, "status": "human_reviewed",
            "englishSourcePackageJsonSha256": displayHash,
            "sourceMediaSha256": displayHash,
            "targetLanguageCandidateJsonSha256": displayHash,
            "durationSeconds": 20.0, "title": title,
            "series": "启示录：耶稣带来的安慰与盼望", "speaker": "Eric Geiger",
            "cues": [["textGroupId": "g1", "sourceUnitIds": ["u1"], "start": 0.0, "end": 10.0, "text": fullText]]
        ], options: [.sortedKeys])
        let captions = try! JSONSerialization.data(withJSONObject: [
            "cues": [["textGroupId": "g1", "start": 0.0, "end": 10.0, "text": caption]]
        ], options: [.sortedKeys])
        let release: [String: Any] = [
            "schemaVersion": "sermon-target-language-release-package-v2",
            "packageId": "\(pageID)-\(locale)", "pageId": pageID,
            "sourceLocale": "en", "targetLocale": locale,
            "targetLanguageCandidateJsonSha256": displayHash,
            "spokenTargetLanguageCandidateJsonSha256": spokenHash,
            "targetLanguageAudioPackageJsonSha256": spokenHash,
            "status": "published_http_verified", "contentStatus": "human_reviewed",
            "audioStatus": "human_reviewed", "interfaceLocale": locale,
            "contentLocale": locale, "audioLocale": locale,
            "assets": [
                ["role": "page", "path": "/pages/\(pageID)/\(locale)/index.html", "sha256": hash(html)],
                ["role": "content", "path": "/content/\(pageID)/\(locale).json", "sha256": hash(content)],
                ["role": "captions", "path": "/captions/\(pageID)/\(locale).json", "sha256": hash(captions)],
                ["role": "audio", "path": "/media/\(pageID)/\(locale).mp3", "sha256": hash(audio)],
            ],
            "httpVerification": ["status": "pass", "evidenceSha256": displayHash],
            "deviceAcceptance": ["status": "not_run", "evidenceSha256": NSNull()],
            "venueAcceptance": ["status": "not_run", "evidenceSha256": NSNull()],
            "issues": [],
        ]
        let releaseData = try! JSONSerialization.data(withJSONObject: release, options: [.sortedKeys])
        let english = try! JSONSerialization.data(withJSONObject: [
            "schemaVersion": "sermon-published-english-reference-v1", "pageId": pageID,
            "sourceIdentitySha256": displayHash, "sourceMediaSha256": displayHash,
            "reviewState": "human_approved",
            "targets": [locale: ["contentSha256": hash(content), "captionsSha256": hash(captions),
                "releasePackageJsonSha256": hash(releaseData),
                "blocks": [["textGroupId": "g1", "sourceUnitIds": ["u1"], "english": "This is the approved English source."]]]]
        ], options: [.sortedKeys])
        let catalog: [String: Any] = [
            "schemaVersion": "sermon-multilingual-catalog-v3", "generatedAt": "2026-09-27T00:00:00Z",
            "defaultPageId": pageID,
            "pages": [["id": pageID, "title": title, "date": "2026-09-27",
                       "sourceLocale": "en", "sourceIdentitySha256": displayHash,
                       "defaultTargetLocale": locale,
                       "targets": [locale: ["releasePackageUrl": "/releases-v2/\(pageID)/\(locale).json",
                                             "releasePackageJsonSha256": hash(releaseData),
                                             "contentStatus": "human_reviewed", "audioStatus": "human_reviewed",
                                             "capabilities": ["text", "captions", "audio"]]]]],
        ]
        let files: [String: Data] = [
            "/multilingual-v3.json": try! JSONSerialization.data(withJSONObject: catalog, options: [.sortedKeys]),
            "/releases-v2/\(pageID)/\(locale).json": releaseData,
            "/pages/\(pageID)/\(locale)/index.html": html,
            "/content/\(pageID)/\(locale).json": content,
            "/captions/\(pageID)/\(locale).json": captions,
            "/english-reference/\(pageID).json": english,
            "/media/\(pageID)/\(locale).mp3": audio,
        ]
        return ProcessInfo.processInfo.arguments.contains("--ui-testing-study-products") ? withStudyProducts(files, pageID: pageID, locale: locale) : files
    }
    static let headingLanguageResponses: [String: Data] = {
        let chinese = nativePublishedResponses(locale: "zh-Hans", fullText: "中文正文", caption: "中文字幕")
        let korean = nativePublishedResponses(locale: "ko", fullText: "한국어 본문", caption: "한국어 자막", title: "한국어 제목")
        var files = chinese.merging(korean) { first, _ in first }
        var catalog = try! JSONSerialization.jsonObject(with: chinese["/multilingual-v3.json"]!) as! [String: Any]
        let other = try! JSONSerialization.jsonObject(with: korean["/multilingual-v3.json"]!) as! [String: Any]
        var pages = catalog["pages"] as! [[String: Any]]
        let otherPage = (other["pages"] as! [[String: Any]])[0]
        let targets = pages[0]["targets"] as! [String: Any]
        pages[0]["targets"] = targets.merging(otherPage["targets"] as! [String: Any]) { first, _ in first }
        // Deliberately differ from verified content metadata to catch fallback.
        pages[0]["title"] = "Catalog fallback title"
        catalog["pages"] = pages
        files["/multilingual-v3.json"] = try! JSONSerialization.data(withJSONObject: catalog, options: [.sortedKeys])
        files.removeValue(forKey: "/english-reference/ui-test-full-video.json")
        return files
    }()

    /// Public display metadata with synthetic, hash-bound text/audio only.
    /// The category is exercised through the production picker, not drawn here.
    static let categoryResponses = makeCategoryResponses(remote: false)
    static let remoteCategoryResponses = makeCategoryResponses(remote: true)

    private static func makeCategoryResponses(remote: Bool) -> [String: Data] {
        let entries = remote ? [
            ("remote-archive", "2026-10-04", "正式版显示测试", "界面测试", "video"),
            ("remote-youtube", "2026-10-03", "YouTube 版显示测试", "界面测试", "video"),
            ("remote-podcast", "2026-10-02", "播客显示测试", "界面测试", "podcast"),
            ("remote-interview", "2026-10-01", "自定义类别显示测试", "界面测试", "video")
        ] : [
            ("resi-20261004-69ba7a66", "2026-10-04", "耶稣审判并保守", "Eric Geiger", "video"),
            ("if-i-had-more-time-jesus-is-worthy", "2026-10-02", "如果我有更多时间 · 耶稣配得", "Eric Geiger · Steve Bang Lee", "podcast"),
            ("2026-09-27-weekend-sermon-drive-530", "2026-09-27", "耶稣配得", "Eric Geiger", "video")
        ]
        var result: [String: Data] = [:]
        var pages: [[String: Any]] = []
        for (id, date, title, speaker, mediaType) in entries {
            var files = nativePublishedResponses(locale: "zh-Hans", fullText: "界面测试合成正文。", caption: "界面测试合成字幕。", pageID: id)
            let contentPath = "/content/\(id)/zh-Hans.json"
            var content = try! JSONSerialization.jsonObject(with: files[contentPath]!) as! [String: Any]
            content["title"] = title
            content["speaker"] = speaker
            files[contentPath] = try! JSONSerialization.data(withJSONObject: content, options: [.sortedKeys])
            // Rebind content and release hashes after changing fixture metadata.
            let releasePath = "/releases-v2/\(id)/zh-Hans.json"
            var release = try! JSONSerialization.jsonObject(with: files[releasePath]!) as! [String: Any]
            var assets = release["assets"] as! [[String: Any]]
            for index in assets.indices where assets[index]["role"] as? String == "content" {
                assets[index]["sha256"] = SHA256.hash(data: files[contentPath]!).map { String(format: "%02x", $0) }.joined()
            }
            release["assets"] = assets
            files[releasePath] = try! JSONSerialization.data(withJSONObject: release, options: [.sortedKeys])
            // This fixture tests picker metadata only; omit the optional English join.
            files.removeValue(forKey: "/english-reference/\(id).json")
            let catalog = try! JSONSerialization.jsonObject(with: files["/multilingual-v3.json"]!) as! [String: Any]
            var page = (catalog["pages"] as! [[String: Any]])[0]
            page["date"] = date; page["title"] = title; page["mediaType"] = mediaType
            if remote {
                let labels: [String: [String: String]] = [
                    "remote-archive": ["zh-Hans": "正式播放版", "en": "Archive edition"],
                    "remote-youtube": ["zh-Hans": "YouTube 版", "en": "YouTube edition"],
                    "remote-podcast": ["zh-Hans": "播客", "en": "Podcast"],
                    "remote-interview": ["zh-Hans": "专题访谈", "en": "Special interview"]
                ]
                page["displayCategory"] = ["schemaVersion": "sermon-page-display-category-v1", "labels": labels[id]!]
            }
            var targets = page["targets"] as! [String: [String: Any]]
            targets["zh-Hans"]!["releasePackageJsonSha256"] = SHA256.hash(data: files[releasePath]!).map { String(format: "%02x", $0) }.joined()
            page["targets"] = targets
            pages.append(page)
            files.removeValue(forKey: "/multilingual-v3.json")
            result.merge(files) { _, new in new }
        }
        result["/multilingual-v3.json"] = try! JSONSerialization.data(withJSONObject: [
            "schemaVersion": "sermon-multilingual-catalog-v3", "generatedAt": "2026-10-04T00:00:00Z",
            "defaultPageId": entries[0].0, "pages": pages
        ], options: [.sortedKeys])
        return result
    }

    private static func withStudyProducts(_ original: [String: Data], pageID: String, locale: String) -> [String: Data] {
        func encode(_ object: Any) -> Data { try! JSONSerialization.data(withJSONObject: object, options: [.sortedKeys, .withoutEscapingSlashes]) }
        func hash(_ bytes: Data) -> String { SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined() }
        var files = original
        let releasePath = "/releases-v2/\(pageID)/\(locale).json"
        var release = try! JSONSerialization.jsonObject(with: files[releasePath]!) as! [String: Any]
        let source = String(repeating: "a", count: 64)
        let text = release["targetLanguageCandidateJsonSha256"] as! String
        let audio = release["targetLanguageAudioPackageJsonSha256"] as! String
        let content = hash(files["/content/\(pageID)/\(locale).json"]!)
        func artifact(_ kind: String, title: String, body: String) -> [String: Any] {
            ["schemaVersion": "sermon-study-artifact-v1", "kind": kind, "pageId": pageID, "locale": locale,
             "sourcePackageSha256": source, "textCandidateSha256": text, "producerIdentity": "offline-ui-fixture",
             "sections": [["title": title, "body": body, "sourceUnitIds": ["u1"]]]]
        }
        let outline = artifact("outline", title: "검토된 개요", body: "본문 전체가 표시됩니다.")
        let meditation = artifact("meditation", title: "검토된 묵상", body: "예수님의 말씀을 묵상합니다.")
        let outlineHash = hash(encode(outline)), meditationHash = hash(encode(meditation))
        let identity: [String: Any] = ["sourceId": "offline-ui-fixture", "sourceUrlHash": source, "mediaSha256": source,
            "durationSeconds": 20, "window": ["startSeconds": 0, "endSeconds": 20, "approvalReceiptSha256": source]]
        let joined: [String: Any] = ["source": source, "products": ["text": text, "audio": audio,
            "outline": ["status": "human_reviewed", "artifactSha256": outlineHash, "reviewSha256": source],
            "meditation": ["status": "human_reviewed", "artifactSha256": meditationHash, "reviewSha256": source]]]
        let products: [String: Any] = ["sourcePackageSha256": source, "textCandidateSha256": text, "audioPackageSha256": audio,
            "outlineArtifactSha256": outlineHash, "meditationArtifactSha256": meditationHash,
            "outlineReviewSha256": source, "meditationReviewSha256": source, "metadataApprovalSha256": source,
            "contentSha256": content, "candidateSha256": hash(encode(["products": hash(encode(joined)), "metadataApproval": source, "contentSha256": content]))]
        let manifest: [String: Any] = ["schemaVersion": "sermon-public-app-products-v1", "pageId": pageID, "locale": locale,
                                      "sourceIdentity": identity, "fourProducts": products]
        let pagePath = "/pages/\(pageID)/\(locale)/index.html"
        let existingHTML = String(data: files[pagePath]!, encoding: .utf8)!
        let studyHTML = "<section id=\"study-outline\"><h2>설교 개요</h2><strong>검토된 개요</strong><p>본문 전체가 표시됩니다.</p></section><section id=\"study-meditation\"><h2>묵상</h2><strong>검토된 묵상</strong><p>예수님의 말씀을 묵상합니다.</p></section>"
        files[pagePath] = Data(existingHTML.replacingOccurrences(of: "</body>", with: studyHTML + "</body>").utf8)
        var assets = release["assets"] as! [[String: Any]]
        assets[0]["sha256"] = hash(files[pagePath]!)
        for (role, name, value) in [("outline", "outline", outline), ("meditation", "meditation", meditation), ("product_manifest", "products", manifest)] {
            let path = "/study/\(pageID)/\(locale)/\(name).json"
            files[path] = encode(value); assets.append(["role": role, "path": path, "sha256": hash(files[path]!)])
        }
        release["schemaVersion"] = "sermon-target-language-release-package-v3"
        release["englishSourcePackageJsonSha256"] = source; release["sourceIdentity"] = identity
        release["fourProducts"] = products; release["assets"] = assets; files[releasePath] = encode(release)
        var catalog = try! JSONSerialization.jsonObject(with: files["/multilingual-v3.json"]!) as! [String: Any]
        var pages = catalog["pages"] as! [[String: Any]], targets = pages[0]["targets"] as! [String: [String: Any]]
        pages[0]["sourceMediaSha256"] = source
        targets[locale]!["releasePackageJsonSha256"] = hash(files[releasePath]!)
        pages[0]["targets"] = targets; catalog["pages"] = pages; files["/multilingual-v3.json"] = encode(catalog)
        return files
    }

}

/// This transport belongs only to the explicitly constructed fixture session.
/// Offline launch reports a real URLSession error; the production repositories
/// must recover from their own previously written cache and verified audio.
private class UITestContentProtocol: URLProtocol {
    private let deliveryLock = NSRecursiveLock()
    private var delayedResponse: DispatchWorkItem?
    private var stopped = false

    class var offline: Bool { ProcessInfo.processInfo.arguments.contains("--ui-testing-offline") }
    class var dualScript: Bool { ProcessInfo.processInfo.arguments.contains("--ui-testing-dual-script") }
    class var nativeResponses: [String: Data]? {
        if ProcessInfo.processInfo.arguments.contains("--ui-testing-remote-categories") { return UITestContent.remoteCategoryResponses }
        if ProcessInfo.processInfo.arguments.contains("--ui-testing-source-categories") { return UITestContent.categoryResponses }
        if ProcessInfo.processInfo.arguments.contains("--ui-testing-weekly-update") { return UITestContent.weeklyUpdateResponses }
        if ProcessInfo.processInfo.arguments.contains("--ui-testing-alignment-failure") { return UITestContent.alignmentFailureResponses }
        if ProcessInfo.processInfo.arguments.contains("--ui-testing-locate-flow") { return UITestContent.locateResponses }
        return dualScript ? UITestContent.dualScriptResponses : nil
    }
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    private final class CategoryRequests: @unchecked Sendable {
        let lock = NSLock()
        var count = 0
        func isRefresh() -> Bool {
            lock.lock(); defer { lock.unlock() }
            count += 1
            return count > 1
        }
    }
    private static let categoryRequests = CategoryRequests()

    override func startLoading() {
        guard let url = request.url, url.scheme == "https", url.host == UITestContent.origin.host else {
            client?.urlProtocol(self, didFailWithError: URLError(.unsupportedURL))
            return
        }
        guard !Self.offline else {
            client?.urlProtocol(self, didFailWithError: URLError(.notConnectedToInternet))
            return
        }
        if var data = Self.nativeResponses?[url.path] {
            if url.path == "/multilingual-v3.json",
               ProcessInfo.processInfo.arguments.contains("--ui-testing-remote-categories"),
               ProcessInfo.processInfo.arguments.contains("--ui-testing-remote-category-refresh"),
               Self.categoryRequests.isRefresh() {
                var catalog = try! JSONSerialization.jsonObject(with: data) as! [String: Any]
                var pages = catalog["pages"] as! [[String: Any]]
                pages[0]["displayCategory"] = ["schemaVersion": "sermon-page-display-category-v1",
                    "labels": ["zh-Hans": "正式版 · 更新", "en": "Updated archive"]]
                catalog["pages"] = pages
                data = try! JSONSerialization.data(withJSONObject: catalog, options: [.sortedKeys])
            }
            if ProcessInfo.processInfo.arguments.contains("--ui-testing-delayed-transcript"),
               url.path == "/content/ui-test-locate-flow/ko.json" {
                // Delay only the transcript request, never the language release
                // or audio. The URLSession actor remains free to prepare audio.
                let work = DispatchWorkItem { [weak self] in
                    self?.deliverNativeResponse(data, at: url)
                }
                deliveryLock.lock()
                delayedResponse = work
                if stopped { work.cancel() }
                deliveryLock.unlock()
                DispatchQueue.global(qos: .userInitiated).asyncAfter(deadline: .now() + 8, execute: work)
            } else {
                deliverNativeResponse(data, at: url)
            }
            return
        }
        if url.path == "/multilingual-v3.json" || (url.path == "/voice-demos/speaker-clips-v2/catalog.json"
            && UITestContent.responses[url.path] == nil) {
            let response = HTTPURLResponse(url: url, statusCode: 404, httpVersion: "HTTP/1.1",
                headerFields: ["Content-Length": "1"])!
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: Data("0".utf8))
            client?.urlProtocolDidFinishLoading(self)
            return
        }
        guard let data = UITestContent.responses[url.path] else {
            client?.urlProtocol(self, didFailWithError: URLError(.fileDoesNotExist))
            return
        }
        let response = HTTPURLResponse(url: url, statusCode: 200, httpVersion: "HTTP/1.1",
            headerFields: ["Content-Length": String(data.count),
                           "Content-Type": url.path.hasSuffix(".json") ? "application/json" : url.path.hasSuffix(".mp4") ? "video/mp4" : "audio/mpeg"])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: data)
        client?.urlProtocolDidFinishLoading(self)
    }

    private func deliverNativeResponse(_ data: Data, at url: URL) {
        deliveryLock.lock()
        defer { deliveryLock.unlock() }
        guard !stopped, delayedResponse?.isCancelled != true else { return }
        delayedResponse = nil
        let response = HTTPURLResponse(url: url, statusCode: 200, httpVersion: "HTTP/1.1",
            headerFields: ["Content-Length": String(data.count),
                           "Content-Type": url.path.hasSuffix(".json") ? "application/json"
                               : url.path.hasSuffix(".mp3") ? "audio/mpeg" : "text/html"])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: data)
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {
        deliveryLock.lock()
        stopped = true
        delayedResponse?.cancel()
        delayedResponse = nil
        deliveryLock.unlock()
    }
}

private final class HeadingLanguageContentProtocol: UITestContentProtocol {
    override class var offline: Bool { false }
    override class var nativeResponses: [String: Data]? { UITestContent.headingLanguageResponses }
}

private final class NativePreviewContentProtocol: UITestContentProtocol {
    override class var offline: Bool { false }
    override class var nativeResponses: [String: Data]? { UITestContent.previewResponses }
}
#endif
