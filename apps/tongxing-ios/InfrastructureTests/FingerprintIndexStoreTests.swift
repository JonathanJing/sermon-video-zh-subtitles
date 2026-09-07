import CryptoKit
import Foundation
import Testing
import TongxingCore
@testable import TongxingInfrastructure

@Suite(.timeLimit(.minutes(1)))
final class FingerprintIndexStoreTests {
    private let directory: URL
    private let baseURL: URL
    private let session: URLSession

    init() throws {
        directory = FileManager.default.temporaryDirectory.appendingPathComponent("fingerprint-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        baseURL = URL(string: "https://\(UUID().uuidString.lowercased()).example.test")!
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [FingerprintURLProtocol.self]
        session = URLSession(configuration: configuration)
    }

    deinit {
        session.invalidateAndCancel(); FingerprintURLProtocol.remove(host: baseURL.host!)
        try? FileManager.default.removeItem(at: directory)
    }

    private struct Fixture {
        let data: Data
        let alignment: SermonAudioAlignment
        let week: SermonWeek
        let track: SermonTrack
    }

    private func fixture(indexSource: String = "synthetic-fingerprint", humanApproval: Bool = false) throws -> Fixture {
        let reference = String(repeating: "b", count: 64), trackHash = String(repeating: "c", count: 64)
        let algorithm = try JSONSerialization.jsonObject(with: JSONEncoder().encode(FingerprintAlgorithm.supported))
        let data = try JSONSerialization.data(withJSONObject: [
            "schemaVersion": "sermon-audio-fingerprint-v1", "algorithm": algorithm, "durationSeconds": 12,
            "landmarkCount": 0, "pairCount": 0, "encoding": "u32le-pairs-base64", "postings": "",
            "method": "spectral-landmarks-v1", "source": ["sourceId": indexSource, "referenceAudioSha256": reference,
                "sourceVideoOffsetSeconds": 1200, "timeOrigin": "approved_sermon_clip_start", "timeline": "source_clip", "reviewState": "candidate"],
        ])
        let digest = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
        let alignment = SermonAudioAlignment(fingerprintUrl: "/alignment/\(digest)-fingerprint.json", fingerprintSha256: digest,
            sourceId: "synthetic-fingerprint", referenceAudioSha256: reference, referenceDurationSeconds: 12,
            sourceVideoOffsetSeconds: 1200, trackSha256: trackHash)
        let track = SermonTrack(id: "track", label: "测试", voiceLabel: "测试", audioUrl: "/media/test.mp3", file: "test.mp3",
            sha256: trackHash, durationSeconds: 12, cues: [SubtitleCue(start: 0, end: 12, text: "合成存储测试。")],
            subtitleTiming: "source_video_aligned_candidate", scope: "full_candidate", alignment: alignment)
        let week = SermonWeek(id: "week", date: "2026-09-07", sourceId: "synthetic-fingerprint", sourceUrl: "https://example.org/synthetic",
            title: "测试", speaker: "测试", scripture: "", tracks: [track], videoSynchronization: "candidate_aligned",
            humanApproval: .bool(humanApproval), candidateEvidence: .object(["syncMp3Sha256": .string(trackHash)]))
        return Fixture(data: data, alignment: alignment, week: week, track: track)
    }

    private func store() -> FingerprintIndexStore { FingerprintIndexStore(directory: directory, baseURL: baseURL, session: session) }
    private func cache(_ f: Fixture) -> URL { directory.appendingPathComponent(f.alignment.fingerprintSha256 + "-fingerprint.json") }
    private func install(_ response: FingerprintResponse, calls: FingerprintCounter? = nil) {
        FingerprintURLProtocol.install(host: baseURL.host!) { _ in calls?.increment(); return response }
    }
    private func noPartialFiles() throws {
        #expect(try FileManager.default.contentsOfDirectory(atPath: directory.path).filter { $0.hasSuffix(".part") }.isEmpty)
    }

    @Test func validatedIndexPersistsExactBytesAndLoadsOfflineWithNoSecondRequest() async throws {
        let f = try fixture(), calls = FingerprintCounter()
        install(.init(chunks: [f.data]), calls: calls)
        let store = store()
        let first = try await store.load(alignment: f.alignment, week: f.week, track: f.track)
        #expect(first.source.sourceId == "synthetic-fingerprint")
        #expect(try Data(contentsOf: cache(f)) == f.data)
        install(.init(chunks: [], error: URLError(.notConnectedToInternet)), calls: calls)
        let second = try await store.load(alignment: f.alignment, week: f.week, track: f.track)
        #expect(second.durationSeconds == 12); #expect(calls.value == 1)
        try noPartialFiles()
    }

    @Test func badHashAndWrongSourceNeverBecomeCachedIndexes() async throws {
        let good = try fixture()
        install(.init(chunks: [Data("wrong bytes".utf8)]))
        do { _ = try await store().load(alignment: good.alignment, week: good.week, track: good.track); Issue.record("Bad hash admitted") }
        catch { #expect(error as? ContentStorageError == .checksumMismatch) }
        #expect(!FileManager.default.fileExists(atPath: cache(good).path))
        let wrongSource = try fixture(indexSource: "other-source")
        install(.init(chunks: [wrongSource.data]))
        do { _ = try await store().load(alignment: wrongSource.alignment, week: wrongSource.week, track: wrongSource.track); Issue.record("Wrong source admitted") }
        catch { #expect(error is FingerprintError) }
        #expect(!FileManager.default.fileExists(atPath: cache(wrongSource).path)); try noPartialFiles()
    }

    @Test func damagedEntryCanBeReplacedWithoutTouchingOtherIndexes() async throws {
        let f = try fixture(), unrelated = directory.appendingPathComponent("unrelated-fingerprint.json")
        try Data("damaged".utf8).write(to: cache(f)); try Data("keep".utf8).write(to: unrelated)
        install(.init(chunks: [f.data]))
        _ = try await store().load(alignment: f.alignment, week: f.week, track: f.track)
        #expect(try Data(contentsOf: cache(f)) == f.data)
        #expect(try Data(contentsOf: unrelated) == Data("keep".utf8)); try noPartialFiles()
    }

    @Test func oversizedInterruptedAndForeignResponsesRemainOutsideCache() async throws {
        let f = try fixture()
        let responses = [FingerprintResponse(chunks: [f.data], declaredLength: 8 * 1024 * 1024 + 1),
            FingerprintResponse(chunks: [Data(f.data.prefix(12))], error: URLError(.networkConnectionLost)),
            FingerprintResponse(chunks: [f.data], responseURL: URL(string: "https://other.example.test/index.json")!)]
        for response in responses {
            install(response)
            do { _ = try await store().load(alignment: f.alignment, week: f.week, track: f.track); Issue.record("Invalid response admitted") }
            catch {}
            #expect(!FileManager.default.fileExists(atPath: cache(f).path)); try noPartialFiles()
        }
    }

    @Test func cancellationCleansTemporaryIndexWithoutWaitingForDelayedBody() async throws {
        let f = try fixture(), calls = FingerprintCounter()
        install(.init(chunks: [f.data], delay: 0.2), calls: calls)
        let store = store()
        let loading = Task { try await store.load(alignment: f.alignment, week: f.week, track: f.track) }
        for _ in 0..<100 where calls.value == 0 { try await Task.sleep(nanoseconds: 5_000_000) }
        #expect(calls.value == 1); loading.cancel()
        do { _ = try await loading.value; Issue.record("Cancelled index returned") }
        catch { #expect(error is CancellationError) }
        #expect(!FileManager.default.fileExists(atPath: cache(f).path)); try noPartialFiles()
    }

    @Test func invalidCandidateReviewAndOriginFailBeforeAnyNetworkRequest() async throws {
        let invalid = try fixture(humanApproval: true), calls = FingerprintCounter()
        install(.init(chunks: [invalid.data]), calls: calls)
        do { _ = try await store().load(alignment: invalid.alignment, week: invalid.week, track: invalid.track); Issue.record("Changed review accepted") }
        catch { #expect(error is CatalogError) }
        let valid = try fixture(), insecure = FingerprintIndexStore(directory: directory, baseURL: URL(string: "http://example.test")!, session: session)
        do { _ = try await insecure.load(alignment: valid.alignment, week: valid.week, track: valid.track); Issue.record("Insecure origin accepted") }
        catch { #expect(error as? ContentStorageError == .invalidURL) }
        #expect(calls.value == 0); try noPartialFiles()
    }
}

private final class FingerprintCounter: @unchecked Sendable {
    private let lock = NSLock(); private var count = 0
    func increment() { lock.lock(); count += 1; lock.unlock() }
    var value: Int { lock.lock(); defer { lock.unlock() }; return count }
}

private struct FingerprintResponse {
    let chunks: [Data]
    var error: Error? = nil
    var responseURL: URL? = nil
    var declaredLength: Int? = nil
    var delay: Double = 0
}

private final class FingerprintURLProtocol: URLProtocol {
    private static let lock = NSLock()
    private static var handlers: [String: (URLRequest) -> FingerprintResponse] = [:]
    private let callbacks = DispatchQueue(label: "tongxing.fingerprint.transport.\(UUID().uuidString)")
    private var stopped = false
    static func install(host: String, handler: @escaping (URLRequest) -> FingerprintResponse) { lock.lock(); handlers[host] = handler; lock.unlock() }
    static func remove(host: String) { lock.lock(); handlers.removeValue(forKey: host); lock.unlock() }
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        Self.lock.lock(); let handler = Self.handlers[request.url!.host!]; Self.lock.unlock()
        guard let handler else { client?.urlProtocol(self, didFailWithError: URLError(.unsupportedURL)); return }
        let response = handler(request)
        callbacks.async { self.send(response, index: -1) }
    }
    private func send(_ response: FingerprintResponse, index: Int) {
        guard !stopped else { return }
        if index == -1 {
            let headers = response.declaredLength.map { ["Content-Length": String($0)] }
            let http = HTTPURLResponse(url: response.responseURL ?? request.url!, statusCode: 200, httpVersion: "HTTP/1.1", headerFields: headers)!
            client?.urlProtocol(self, didReceive: http, cacheStoragePolicy: .notAllowed)
        } else if index < response.chunks.count {
            client?.urlProtocol(self, didLoad: response.chunks[index])
        } else {
            if let error = response.error { client?.urlProtocol(self, didFailWithError: error) }
            else { client?.urlProtocolDidFinishLoading(self) }
            return
        }
        callbacks.asyncAfter(deadline: .now() + response.delay) { self.send(response, index: index + 1) }
    }
    override func stopLoading() { callbacks.async { self.stopped = true } }
}
