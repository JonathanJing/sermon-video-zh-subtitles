import CryptoKit
import Foundation
import TongxingCore
import Testing
@testable import TongxingInfrastructure

@Suite(.timeLimit(.minutes(1)))
final class StorageTests {
    private var directory: URL!
    private var baseURL: URL!
    private var session: URLSession!

    init() throws {
        directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        baseURL = URL(string: "https://\(UUID().uuidString.lowercased()).example.test")!
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [StubURLProtocol.self]
        session = URLSession(configuration: configuration)
    }

    deinit {
        session.invalidateAndCancel()
        StubURLProtocol.remove(host: baseURL.host!)
        try? FileManager.default.removeItem(at: directory)
    }

    @Test func testCatalogPreservesExactValidatedJSONAndReportsCacheFallback() async throws {
        let published = try catalogData()
        stub(.init(chunks: [published]))
        let repository = catalogRepository()
        let online = try await repository.load()
        #expect(online.source == .network)
        #expect(online.warning == nil)
        let saved = directory.appendingPathComponent("catalog/weekly.json")
        #expect(try Data(contentsOf: saved) == published)

        stub(.init(chunks: [], error: URLError(.notConnectedToInternet)))
        let offline = try await repository.load()
        #expect(offline.source == .cache)
        #expect(offline.warning != nil)
        #expect(offline.catalog == online.catalog)
    }

    @Test func testInvalidNetworkCatalogDoesNotOverwriteKnownGoodCache() async throws {
        let good = try catalogData()
        stub(.init(chunks: [good]))
        let repository = catalogRepository()
        _ = try await repository.load()
        stub(.init(chunks: [Data("{\"schemaVersion\":\"future\"}".utf8)]))
        let fallback = try await repository.load()
        #expect(fallback.source == .cache)
        #expect(try Data(contentsOf: directory.appendingPathComponent("catalog/weekly.json")) == good)

        try Data("broken cache".utf8).write(to: directory.appendingPathComponent("catalog/weekly.json"))
        do { _ = try await repository.load(); Issue.record("Corrupt cache must fail") } catch {}
    }

    @Test func testCatalogRejectsNonHTTPSAndForeignResponse() async throws {
        let invalid = CatalogRepository(catalogURL: URL(string: "http://example.test/content/weekly.json")!,
            cacheDirectory: directory, session: session)
        do { _ = try await invalid.load(); Issue.record("HTTP must fail") }
        catch { #expect(error as? ContentStorageError == .invalidURL) }
        stub(.init(chunks: [try catalogData()], responseURL: URL(string: "https://foreign.example/content/weekly.json")!))
        do { _ = try await catalogRepository().load(); Issue.record("Foreign response must fail") }
        catch { #expect(error as? ContentStorageError == .invalidResponse) }
    }

    @Test func testVerifiedDownloadTamperDetectionAndRepair() async throws {
        let data = Data("complete MP3 test payload".utf8)
        let track = track(data: data)
        let library = library()
        stub(.init(chunks: [data]))
        let downloaded = try await library.download(track: track)
        #expect(try Data(contentsOf: downloaded) == data)
        let checked = try await library.offlineFile(for: track)
        #expect(checked == downloaded)
        try Data("tampered".utf8).write(to: downloaded)
        do { _ = try await library.offlineFile(for: track); Issue.record("Tampering must fail") }
        catch { #expect(error as? ContentStorageError == .checksumMismatch) }
        let repaired = try await library.download(track: track)
        #expect(try Data(contentsOf: repaired) == data)
        try assertTemporaryFilesEmpty()
    }

    @Test func testChecksumFailurePreservesPreviousCompleteAudio() async throws {
        let data = Data("previous complete track".utf8)
        let original = track(data: data)
        let library = library()
        stub(.init(chunks: [data]))
        let originalFile = try await library.download(track: original)
        let replacement = track(data: Data("expected new bytes".utf8))
        stub(.init(chunks: [Data("wrong bytes".utf8)]))
        do { _ = try await library.download(track: replacement); Issue.record("Wrong hash must fail") }
        catch { #expect(error as? ContentStorageError == .checksumMismatch) }
        #expect(try Data(contentsOf: originalFile) == data)
        let missing = try await library.offlineFile(for: replacement)
        #expect(missing == nil)
        try assertTemporaryFilesEmpty()
    }

    @Test func testResponseStatusAndSizeLimitsCannotBecomeDownloads() async throws {
        let data = Data(repeating: 65, count: 16)
        let track = track(data: data)
        let library = library(maximumBytes: 8)
        stub(.init(status: 404, chunks: [data]))
        do { _ = try await library.download(track: track); Issue.record("404 must fail") }
        catch { #expect(error as? ContentStorageError == .httpStatus(404)) }
        stub(.init(chunks: [data], declaredLength: 16))
        do { _ = try await library.download(track: track); Issue.record("Declared size must fail") }
        catch { #expect(error as? ContentStorageError == .tooLarge(limit: 8)) }
        stub(.init(chunks: [Data(data.prefix(8)), Data(data.suffix(8))]))
        do { _ = try await library.download(track: track); Issue.record("Streaming size must fail") }
        catch { #expect(error as? ContentStorageError == .tooLarge(limit: 8)) }
        let missing = try await library.offlineFile(for: track)
        #expect(missing == nil)
        try assertTemporaryFilesEmpty()
    }

    @Test func testInterruptedTransferIsNotAdmitted() async throws {
        let data = Data("full expected payload".utf8)
        stub(.init(chunks: [Data(data.prefix(4))], error: URLError(.networkConnectionLost)))
        let library = library()
        let track = track(data: data)
        do { _ = try await library.download(track: track); Issue.record("Interrupted transfer must fail") }
        catch { #expect((error as? URLError)?.code == .networkConnectionLost) }
        let missing = try await library.offlineFile(for: track)
        #expect(missing == nil)
        try assertTemporaryFilesEmpty()
    }

    @Test func testDeclaredLengthMismatchAndEmptyFileAreRejected() async throws {
        let data = Data("payload".utf8)
        let library = library()
        let track = track(data: data)
        stub(.init(chunks: [data], declaredLength: data.count + 1))
        do { _ = try await library.download(track: track); Issue.record("Truncated transfer must fail") }
        catch { #expect(error as? ContentStorageError == .truncated(expected: Int64(data.count + 1), actual: Int64(data.count))) }
        stub(.init(chunks: []))
        do { _ = try await library.download(track: track); Issue.record("Empty transfer must fail") }
        catch { #expect(error as? ContentStorageError == .emptyFile) }
        try assertTemporaryFilesEmpty()
    }

    @Test func testCrossOriginRedirectIsNotFollowed() async throws {
        let data = Data("payload".utf8)
        let foreign = URL(string: "https://\(UUID().uuidString.lowercased()).example.test/media/test.mp3")!
        let foreignCalls = Counter()
        StubURLProtocol.install(host: foreign.host!) { _ in
            foreignCalls.increment()
            return StubResponse(chunks: [data])
        }
        defer { StubURLProtocol.remove(host: foreign.host!) }
        stub(.init(chunks: [], redirectURL: foreign))
        do { _ = try await library().download(track: track(data: data)); Issue.record("Cross-origin redirect must fail") }
        catch { #expect(error as? ContentStorageError == .invalidURL) }
        #expect(foreignCalls.value == 0)
        try assertTemporaryFilesEmpty()
    }

    @Test func testConcurrentSameHashUsesOneTransferAndSingleTrackRemovalPreservesOther() async throws {
        let data = Data("shared complete audio".utf8)
        let calls = Counter()
        stub(.init(chunks: [data], delay: 0.15), calls: calls)
        let library = library()
        let first = track(id: "track_one", data: data)
        let second = track(id: "track_two", data: data)
        async let left = library.download(track: first)
        async let right = library.download(track: second)
        let (leftURL, rightURL) = try await (left, right)
        #expect(leftURL == rightURL)
        #expect(calls.value == 1)
        try await library.removeDownload(for: first)
        let removed = try await library.offlineFile(for: first)
        let retained = try await library.offlineFile(for: second)
        #expect(removed == nil)
        #expect(retained != nil)
        try await library.removeDownload(for: second)
        #expect(!(FileManager.default.fileExists(atPath: rightURL.path)))
    }

    @Test func testCancellingFinalWaiterCleansTemporaryFile() async throws {
        let data = Data(repeating: 65, count: 32)
        let began = Counter()
        stub(.init(chunks: [Data(data.prefix(16)), Data(data.suffix(16))], delay: 0.3), began: began)
        let library = library()
        let track = track(data: data)
        let task = Task { try await library.download(track: track) }
        try await waitFor(began)
        task.cancel()
        do { _ = try await task.value; Issue.record("Cancelled task must fail") } catch {}
        let missing = try await library.offlineFile(for: track)
        #expect(missing == nil)
        try assertTemporaryFilesEmpty()
    }

    @Test func testCancellingOneWaiterPreservesSharedDownloadForAnother() async throws {
        let data = Data("shared slow audio".utf8)
        let began = Counter()
        let calls = Counter()
        stub(.init(chunks: [data], delay: 0.3), calls: calls, began: began)
        let library = library()
        let first = track(id: "first", data: data)
        let second = track(id: "second", data: data)
        let taskOne = Task { try await library.download(track: first) }
        try await waitFor(began)
        let taskTwo = Task { try await library.download(track: second) }
        // Give the second waiter a chance to enter the actor before cancellation.
        try await Task.sleep(nanoseconds: 30_000_000)
        taskOne.cancel()
        do { _ = try await taskOne.value; Issue.record("Cancelled waiter must fail") } catch {}
        let file = try await taskTwo.value
        #expect(try Data(contentsOf: file) == data)
        #expect(calls.value == 1)
        let cancelled = try await library.offlineFile(for: first)
        #expect(cancelled == nil)
    }

    @Test func testDeleteDuringDownloadDoesNotRecreateTrackReference() async throws {
        let data = Data("slow audio".utf8)
        let began = Counter()
        stub(.init(chunks: [data], delay: 0.3), began: began)
        let library = library()
        let track = track(data: data)
        let task = Task { try await library.download(track: track) }
        try await waitFor(began)
        try await library.removeDownload(for: track)
        do { _ = try await task.value; Issue.record("Deleted transfer must fail") } catch {}
        let missing = try await library.offlineFile(for: track)
        #expect(missing == nil)
        try assertTemporaryFilesEmpty()
    }

    private func track(id: String = "full", data: Data) -> SermonTrack {
        SermonTrack(id: id, label: "测试音轨", voiceLabel: "测试声音", audioUrl: "/media/test.mp3",
                    file: "test.mp3", sha256: SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined(),
                    durationSeconds: 10, cues: [SubtitleCue(start: 0, end: 5, text: "测试字幕")],
                    subtitleTiming: "candidate", scope: "full")
    }

    private func catalogData() throws -> Data {
        let week = SermonWeek(id: "2026-09-05", date: "2026-09-05", sourceId: "source123",
            sourceUrl: "https://www.youtube.com/watch?v=source123", title: "测试证道", speaker: "讲员",
            scripture: "诗篇", tracks: [track(data: Data("audio".utf8))])
        let catalog = try WeeklyCatalog(defaultWeekId: week.id, weeks: [week])
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        return try encoder.encode(catalog)
    }

    private func catalogRepository() -> CatalogRepository {
        CatalogRepository(catalogURL: baseURL.appendingPathComponent("weekly.json"),
                          cacheDirectory: directory.appendingPathComponent("catalog"), session: session)
    }

    private func library(maximumBytes: Int64 = 1_024) -> OfflineLibrary {
        OfflineLibrary(directory: directory.appendingPathComponent("offline"), baseURL: baseURL,
                       session: session, maxAudioBytes: maximumBytes)
    }

    private func assertTemporaryFilesEmpty() throws {
        let path = directory.appendingPathComponent("offline/tmp")
        if FileManager.default.fileExists(atPath: path.path) {
            #expect(try FileManager.default.contentsOfDirectory(atPath: path.path).isEmpty)
        }
    }

    private func waitFor(_ signal: Counter) async throws {
        for _ in 0..<200 {
            if signal.value > 0 { return }
            try await Task.sleep(nanoseconds: 10_000_000)
        }
        throw URLError(.timedOut)
    }

    private func stub(_ response: StubResponse, calls: Counter? = nil, began: Counter? = nil) {
        StubURLProtocol.install(host: baseURL.host!) { _ in
            calls?.increment()
            began?.increment()
            return response
        }
    }
}

private final class Counter: @unchecked Sendable {
    private let lock = NSLock()
    private var count = 0
    var value: Int { lock.lock(); defer { lock.unlock() }; return count }
    func increment() { lock.lock(); count += 1; lock.unlock() }
}

private struct StubResponse {
    var status = 200
    var chunks: [Data]
    var declaredLength: Int? = nil
    var error: Error? = nil
    var responseURL: URL? = nil
    var delay: TimeInterval = 0
    var redirectURL: URL? = nil
}

private final class StubURLProtocol: URLProtocol {
    private static let lock = NSLock()
    private static var handlers: [String: (URLRequest) -> StubResponse] = [:]
    private let callbackQueue = DispatchQueue(label: "tongxing.test.transport.\(UUID().uuidString)")
    private var stopped = false

    static func install(host: String, handler: @escaping (URLRequest) -> StubResponse) {
        lock.lock(); handlers[host] = handler; lock.unlock()
    }
    static func remove(host: String) { lock.lock(); handlers.removeValue(forKey: host); lock.unlock() }
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        Self.lock.lock()
        let handler = Self.handlers[request.url!.host!]
        Self.lock.unlock()
        guard let handler else {
            client?.urlProtocol(self, didFailWithError: URLError(.unsupportedURL)); return
        }
        let response = handler(request)
        callbackQueue.async { self.send(response, index: -1) }
    }

    private func send(_ response: StubResponse, index: Int) {
        guard !stopped else { return }
        if index == -1 {
            if let redirect = response.redirectURL {
                let http = HTTPURLResponse(url: request.url!, statusCode: 302,
                    httpVersion: "HTTP/1.1", headerFields: ["Location": redirect.absoluteString])!
                client?.urlProtocol(self, wasRedirectedTo: URLRequest(url: redirect), redirectResponse: http)
                return
            }
            var headers: [String: String] = [:]
            if let length = response.declaredLength { headers["Content-Length"] = String(length) }
            let http = HTTPURLResponse(url: response.responseURL ?? request.url!, statusCode: response.status,
                                       httpVersion: "HTTP/1.1", headerFields: headers)!
            client?.urlProtocol(self, didReceive: http, cacheStoragePolicy: .notAllowed)
        } else if index < response.chunks.count {
            client?.urlProtocol(self, didLoad: response.chunks[index])
        } else {
            if let error = response.error { client?.urlProtocol(self, didFailWithError: error) }
            else { client?.urlProtocolDidFinishLoading(self) }
            return
        }
        callbackQueue.asyncAfter(deadline: .now() + response.delay) { self.send(response, index: index + 1) }
    }

    override func stopLoading() { callbackQueue.async { self.stopped = true } }
}
