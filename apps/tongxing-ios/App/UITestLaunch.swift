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
                    SubtitleCue(start: 0, end: 12, text: "\(label)：第一句，用于验证选轨。"),
                    SubtitleCue(start: 12, end: 24, text: "\(label)：第二句，用于验证时间定位。"),
                    SubtitleCue(start: 24, end: duration, text: "\(label)：第三句，用于验证继续收听。")
                ], subtitleTiming: "synthetic-ui-test-fixture", scope: "full_candidate")
        }
        let catalog = try! WeeklyCatalog(defaultWeekId: "ui-test-week", weeks: [
            SermonWeek(id: "ui-test-week", date: "2026-09-06", sourceId: "ui-test-source",
                sourceUrl: "https://example.test/synthetic-ui-test", title: "界面测试证道",
                speaker: "静音夹具", scripture: "自动化验证",
                tracks: [track(id: "fixture-first", label: "甲音轨", data: firstAudio, duration: 36),
                         track(id: "fixture-second", label: "乙音轨", data: secondAudio, duration: 48.024)],
                contentReview: "合成测试数据，无真实证道内容或审核声明。",
                audioNotice: "仅用于界面自动化的本地静音夹具，不是证道内容。")
        ])
        return ["/weekly.json": try! JSONEncoder().encode(catalog),
                "/media/fixture-first.mp3": firstAudio,
                "/media/fixture-second.mp3": secondAudio]
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
                           "Content-Type": url.path == "/weekly.json" ? "application/json" : "audio/mpeg"])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: data)
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}
#endif
