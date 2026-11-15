import CryptoKit
import Foundation
import TongxingCore
import XCTest
@testable import Tongxing

/// Synthetic hosted checks for a published page whose verified audio downloads
/// slowly. They prove the dock/progress state and the refresh restart; they do
/// not establish real cellular timing, device acceptance or venue readiness.
@MainActor
final class PublishedAudioPreparationTests: XCTestCase {
    func testSlowPublishedAudioMountsTheDockAndReportsByteProgress() async throws {
        let fixture = try Fixture()
        defer { fixture.dispose() }
        let model = fixture.model

        await model.refresh()
        XCTAssertEqual(model.selectedPageID, fixture.pageID)

        try await waitUntil { model.isPreparingPublishedAudio && self.received(model) > 0 }
        XCTAssertTrue(model.showsPlaybackDock, "The controls must stay visible while audio downloads")
        XCTAssertTrue(model.isPreparingPlaybackAudio)
        let fraction = try XCTUnwrap(model.publishedAudioProgress?.fraction)
        XCTAssertGreaterThan(fraction, 0)
        XCTAssertLessThan(fraction, 1)
        XCTAssertEqual(model.publishedAudioProgress?.expectedBytes, Int64(fixture.audio.count))

        try await waitUntil(timeout: 20) {
            model.selectedAudioLocale == "zh-Hans" && model.playback.isReady
        }
        XCTAssertNil(model.publishedAudioError)
        XCTAssertTrue(model.showsPlaybackDock)
        XCTAssertFalse(model.isPreparingPlaybackAudio)
    }

    func testRefreshThatCannotReloadTheCatalogRestartsPreparation() async throws {
        let fixture = try Fixture()
        defer { fixture.dispose() }
        let model = fixture.model

        await model.refresh()
        try await waitUntil { model.isPreparingPublishedAudio && self.received(model) > 0 }

        // The refresh cancels the running transfer. With no workable catalog
        // cache and failing catalog endpoints, refreshMultilingualCatalog throws,
        // so only refresh()'s own restart can finish the page.
        try fixture.corruptCatalogCache()
        SlowPublishedContentProtocol.failCatalogNetwork()
        await model.refresh()

        XCTAssertNil(model.selectedAudioLocale, "The cancelled preparation must not claim audio")
        XCTAssertNil(model.publishedAudioError, "A cancelled preparation is not a failure")
        try await waitUntil { model.isPreparingPublishedAudio }
        try await waitUntil(timeout: 20) {
            model.selectedAudioLocale == "zh-Hans" && model.playback.isReady
        }
        XCTAssertNil(model.publishedAudioError)
    }

    func testForegroundRestartLeavesAFailedPreparationForItsRetryButton() async throws {
        let fixture = try Fixture()
        defer { fixture.dispose() }
        let model = fixture.model
        SlowPublishedContentProtocol.failAudio()
        defer { SlowPublishedContentProtocol.failAudio(false) }

        await model.refresh()
        try await waitUntil(timeout: 20) { model.publishedAudioError != nil }
        let attempts = SlowPublishedContentProtocol.audioRequestCount

        model.restartStalledPublishedAudioPreparation()
        try await Task.sleep(nanoseconds: 400_000_000)
        XCTAssertEqual(SlowPublishedContentProtocol.audioRequestCount, attempts,
                       "A known failure must not be retried silently on every foreground return")
        XCTAssertNotNil(model.publishedAudioError)
    }

    private func received(_ model: AppModel) -> Int64 {
        model.publishedAudioProgress?.receivedBytes ?? 0
    }

    private func waitUntil(timeout: TimeInterval = 10, _ predicate: @MainActor () -> Bool) async throws {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if predicate() { return }
            try await Task.sleep(nanoseconds: 20_000_000)
        }
        throw Fixture.TestError.timeout
    }
}

@MainActor
private final class Fixture {
    enum TestError: Error { case timeout }

    let support: URL
    let defaults: UserDefaults
    let suite: String
    let session: URLSession
    let model: AppModel
    let pageID = "published-preparation"
    let audio: Data

    init() throws {
        // One silent MPEG-2.5 Layer III frame (8 kHz mono, 8 kbps, 72 bytes)
        // repeated 112 times: about eight seconds, playable synthetic audio.
        let frame = try XCTUnwrap(Data(base64Encoded:
            "/+MYxMQAAANIAAAAAFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVMQU1FNC4wVVVVVVVVVVVVVVVV"))
        XCTAssertEqual(frame.count, 72)
        var audio = Data()
        for _ in 0..<112 { audio.append(frame) }
        self.audio = audio

        func json(_ value: [String: Any]) throws -> Data {
            try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
        }
        func hash(_ data: Data) -> String {
            SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
        }
        let pageIdentifier = "published-preparation"
        let candidateHash = String(repeating: "a", count: 64)
        let mediaHash = String(repeating: "b", count: 64)
        let html = Data("<html><body><h1>\(pageIdentifier)</h1></body></html>".utf8)
        let cueBytes = try json(["cues": []])
        let audioHash = hash(audio)
        let release = try json([
            "schemaVersion": "sermon-target-language-release-package-v2",
            "packageId": "\(pageIdentifier)-zh-Hans", "pageId": pageIdentifier, "sourceLocale": "en", "targetLocale": "zh-Hans",
            "targetLanguageCandidateJsonSha256": candidateHash,
            "spokenTargetLanguageCandidateJsonSha256": candidateHash,
            "targetLanguageAudioPackageJsonSha256": candidateHash,
            "status": "published_http_verified", "contentStatus": "human_reviewed", "audioStatus": "human_reviewed",
            "interfaceLocale": "zh-Hans", "contentLocale": "zh-Hans", "audioLocale": "zh-Hans",
            "assets": [
                ["role": "page", "path": "/pages/\(pageIdentifier)/zh-Hans/index.html", "sha256": hash(html)],
                ["role": "content", "path": "/content/\(pageIdentifier)/zh-Hans.json", "sha256": hash(cueBytes)],
                ["role": "captions", "path": "/captions/\(pageIdentifier)/zh-Hans.json", "sha256": hash(cueBytes)],
                ["role": "audio", "path": "/media/\(pageIdentifier)/zh-Hans.mp3", "sha256": audioHash]
            ],
            "httpVerification": ["status": "pass", "evidenceSha256": candidateHash],
            "deviceAcceptance": ["status": "not_run", "evidenceSha256": NSNull()],
            "venueAcceptance": ["status": "not_run", "evidenceSha256": NSNull()],
            "issues": []
        ])
        let catalog = try json([
            "schemaVersion": MultilingualCatalog.dualScriptSchemaVersion,
            "generatedAt": "2026-11-01T00:00:00Z", "defaultPageId": pageIdentifier,
            "pages": [["id": pageIdentifier, "title": "Synthetic published preparation page",
                       "date": "2026-11-01", "sourceLocale": "en",
                       "sourceIdentitySha256": candidateHash, "sourceMediaSha256": mediaHash,
                       "defaultTargetLocale": "zh-Hans",
                       "targets": ["zh-Hans": [
                           "releasePackageUrl": "/releases-v2/\(pageIdentifier)/zh-Hans.json",
                           "releasePackageJsonSha256": hash(release),
                           "contentStatus": "human_reviewed", "audioStatus": "human_reviewed",
                           "capabilities": ["text", "captions", "audio"]
                       ]]]]
        ])
        _ = try MultilingualCatalog.decode(catalog)

        SlowPublishedContentProtocol.install(catalog: catalog, release: release, audio: audio)

        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [SlowPublishedContentProtocol.self]
        configuration.urlCache = nil
        session = URLSession(configuration: configuration)
        suite = "Tongxing-PublishedPreparation-\(UUID().uuidString)"
        support = FileManager.default.temporaryDirectory.appendingPathComponent(suite)
        defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        model = AppModel(supportDirectory: support,
                         contentOrigin: URL(string: "https://published-preparation.example.test")!,
                         session: session, statisticsDefaults: defaults,
                         applicationBundleIdentifier: "com.jonathanjing.tongxing")
    }

    /// Make the cached multilingual catalog unreadable, as a damaged cache would
    /// be, so the next refresh cannot quietly reload from disk.
    func corruptCatalogCache() throws {
        let cache = support.appendingPathComponent("MultilingualCatalog", isDirectory: true)
            .appendingPathComponent("multilingual-v3.json")
        try Data("corrupted catalog".utf8).write(to: cache, options: .atomic)
    }

    func dispose() {
        model.playback.clear()
        session.invalidateAndCancel()
        defaults.removePersistentDomain(forName: suite)
        try? FileManager.default.removeItem(at: support)
        SlowPublishedContentProtocol.reset()
    }
}

/// Serves one verified published release over a deliberately slow audio transfer.
/// Catalog endpoints can be switched to failure to reproduce a refresh that
/// cannot reload the catalog after it cancelled the preparation.
private final class SlowPublishedContentProtocol: URLProtocol {
    private static let stateLock = NSLock()
    private static var catalog: Data?
    private static var release: Data?
    private static var audio: Data?
    private static var catalogFails = false
    private static var audioFails = false
    private static var audioRequests = 0

    static func install(catalog: Data, release: Data, audio: Data) {
        stateLock.lock()
        Self.catalog = catalog; Self.release = release; Self.audio = audio
        catalogFails = false; audioFails = false; audioRequests = 0
        stateLock.unlock()
    }

    static func reset() {
        stateLock.lock()
        catalog = nil; release = nil; audio = nil
        catalogFails = false; audioFails = false; audioRequests = 0
        stateLock.unlock()
    }

    static func failCatalogNetwork() {
        stateLock.lock(); catalogFails = true; stateLock.unlock()
    }

    static func failAudio(_ value: Bool = true) {
        stateLock.lock(); audioFails = value; stateLock.unlock()
    }

    static var audioRequestCount: Int {
        stateLock.lock(); defer { stateLock.unlock() }; return audioRequests
    }

    private struct Snapshot {
        let catalog: Data?
        let release: Data?
        let audio: Data?
        let catalogFails: Bool
        let audioFails: Bool
    }

    private static func snapshot() -> Snapshot {
        stateLock.lock(); defer { stateLock.unlock() }
        return Snapshot(catalog: catalog, release: release, audio: audio,
                        catalogFails: catalogFails, audioFails: audioFails)
    }

    private let deliveryQueue = DispatchQueue(label: "tongxing.published-preparation.\(UUID().uuidString)")
    private let lock = NSLock()
    private var stopped = false

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        guard let url = request.url, url.path.hasPrefix("/") else {
            client?.urlProtocol(self, didFailWithError: URLError(.badURL))
            return
        }
        let snapshot = Self.snapshot()
        switch url.path {
        case "/multilingual-v5.json", "/multilingual-v4.json", "/multilingual-v3.json",
             "/multilingual-v2.json", "/weekly.json":
            guard !snapshot.catalogFails, let catalog = snapshot.catalog else {
                respond(status: 500, data: Data("catalog unavailable".utf8), at: url)
                return
            }
            // Only the v3 catalog is served; v4/v5 fail, and the app falls back.
            guard url.path == "/multilingual-v3.json" else {
                respond(status: 404, data: Data("missing".utf8), at: url)
                return
            }
            respond(status: 200, data: catalog, at: url)
        case let path where path.hasPrefix("/releases-v2/") && path.hasSuffix("/zh-Hans.json"):
            guard let release = snapshot.release else {
                respond(status: 404, data: Data("missing".utf8), at: url)
                return
            }
            respond(status: 200, data: release, at: url)
        case let path where path.hasPrefix("/media/") && path.hasSuffix(".mp3"):
            Self.stateLock.lock(); Self.audioRequests += 1; Self.stateLock.unlock()
            guard !snapshot.audioFails, let audio = snapshot.audio else {
                respond(status: 500, data: Data("audio unavailable".utf8), at: url)
                return
            }
            deliverSlowly(audio, at: url)
        default:
            respond(status: 404, data: Data("missing".utf8), at: url)
        }
    }

    override func stopLoading() {
        lock.lock(); stopped = true; lock.unlock()
    }

    private func respond(status: Int, data: Data, at url: URL) {
        guard let response = HTTPURLResponse(url: url, statusCode: status, httpVersion: "HTTP/1.1",
                                             headerFields: ["Content-Length": String(data.count)]) else { return }
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        if status == 200 { client?.urlProtocol(self, didLoad: data) }
        client?.urlProtocolDidFinishLoading(self)
    }

    /// Declares the full length, then sends four chunks with pauses so the app can
    /// show a determinate bar mid-transfer.
    private func deliverSlowly(_ data: Data, at url: URL) {
        guard let response = HTTPURLResponse(url: url, statusCode: 200, httpVersion: "HTTP/1.1",
                                             headerFields: ["Content-Length": String(data.count)]) else { return }
        let chunkSize = max(1, data.count / 4)
        let chunks = stride(from: 0, to: data.count, by: chunkSize).map {
            data.subdata(in: $0..<min($0 + chunkSize, data.count))
        }
        deliveryQueue.async { [weak self] in
            guard let self, self.isRunning else { return }
            self.client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            self.send(chunks, index: 0)
        }
    }

    private func send(_ chunks: [Data], index: Int) {
        guard isRunning else { return }
        if index == chunks.count {
            client?.urlProtocolDidFinishLoading(self)
            return
        }
        client?.urlProtocol(self, didLoad: chunks[index])
        deliveryQueue.asyncAfter(deadline: .now() + 0.8) { [weak self] in
            self?.send(chunks, index: index + 1)
        }
    }

    private var isRunning: Bool {
        lock.lock(); defer { lock.unlock() }; return !stopped
    }
}
