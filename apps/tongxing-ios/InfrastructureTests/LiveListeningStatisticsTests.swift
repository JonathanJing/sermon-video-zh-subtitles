import Foundation
import Testing
@testable import TongxingInfrastructure

/// Explicit production contract probe. It sends temporary synthetic counters,
/// retracts both routes, and does not establish real-device playback acceptance.
struct LiveListeningStatisticsTests {
    @Test(.enabled(if: ProcessInfo.processInfo.environment["TONGXING_LISTENING_LIVE_SMOKE"] == "1"))
    func productionListeningRoutesAcceptNativeClientAndWithdraw() async throws {
        let path = try #require(ProcessInfo.processInfo.environment["TONGXING_LISTENING_CATALOG_PATH"])
        let catalog = try JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: path))) as! [String: Any]
        let row = try #require((catalog["sources"] as? [[String: Any]])?.first { $0["week"] as? String == "2026-09-27" && $0["audioLocale"] as? String == "zh-Hans" })
        let source = ListeningSource(week: row["week"] as! String, trackId: row["trackId"] as! String,
                                     audioSha256: row["audioSha256"] as! String)
        let suite = "tongxing-live-statistics-probe-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        let observer = LiveStatisticsObserver()
        LiveStatisticsProtocol.observer = observer
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [LiveStatisticsProtocol.self]
        let session = URLSession(configuration: config)
        defer { session.finishTasksAndInvalidate() }
        let statistics = ListeningStatistics(origin: URL(string: "https://ai-for-god-sermon-audio.web.app")!,
                                              appVersion: "ios42-native-live-probe", defaults: defaults, session: session)
        await statistics.interfaceVisit(source: source, locale: "en")
        await statistics.setEnabled(true)
        await statistics.sample(source: source, position: 0, duration: 1891.677333, playing: true,
                                uptime: ProcessInfo.processInfo.systemUptime, interfaceLocale: "en", contentLocale: "zh-Hans")
        let began = ProcessInfo.processInfo.systemUptime
        for _ in 0..<33 {
            let now = ProcessInfo.processInfo.systemUptime
            await statistics.sample(source: source, position: now - began, duration: 1891.677333, playing: true,
                                    uptime: now, interfaceLocale: "en", contentLocale: "zh-Hans")
            try await Task.sleep(nanoseconds: 1_000_000_000)
        }
        await statistics.flush()
        await statistics.setEnabled(false)
        let responses = observer.snapshot()
        #expect(responses.filter { $0.path == "/api/session" }.count == 2)
        #expect(responses.filter { $0.path == "/api/interface-usage" }.count == 2)
        #expect(responses.filter { $0.path == "/api/listening" }.count >= 3)
        #expect(responses.allSatisfy { $0.status == 200 && !$0.failed })
        print("Native temporary probe: \(responses.count) HTTP responses; interface/listening upserts and withdrawals all 200: \(responses.allSatisfy { $0.status == 200 && !$0.failed })")
    }
}

private final class LiveStatisticsObserver: @unchecked Sendable {
    struct Response { let path: String; let status: Int; let failed: Bool }
    private let lock = NSLock()
    private var responses: [Response] = []
    func record(path: String, response: URLResponse?, error: Error?) {
        lock.lock(); defer { lock.unlock() }
        responses.append(Response(path: path, status: (response as? HTTPURLResponse)?.statusCode ?? 0, failed: error != nil))
    }
    func snapshot() -> [Response] { lock.lock(); defer { lock.unlock() }; return responses }
}

private final class LiveStatisticsProtocol: URLProtocol {
    nonisolated(unsafe) static var observer: LiveStatisticsObserver?
    private var forwarded: URLSessionDataTask?
    override class func canInit(with request: URLRequest) -> Bool { request.url?.host == "ai-for-god-sermon-audio.web.app" }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        var forwardedRequest = request
        if forwardedRequest.httpBody == nil, let stream = request.httpBodyStream {
            stream.open(); defer { stream.close() }
            var data = Data(), buffer = [UInt8](repeating: 0, count: 4096)
            while stream.hasBytesAvailable {
                let n = stream.read(&buffer, maxLength: buffer.count)
                if n <= 0 { break }; data.append(buffer, count: n)
            }
            forwardedRequest.httpBody = data
        }
        forwarded = URLSession.shared.dataTask(with: forwardedRequest) { [weak self] data, response, error in
            guard let self else { return }
            Self.observer?.record(path: self.request.url?.path ?? "", response: response, error: error)
            if let error { self.client?.urlProtocol(self, didFailWithError: error); return }
            if let response { self.client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed) }
            if let data { self.client?.urlProtocol(self, didLoad: data) }
            self.client?.urlProtocolDidFinishLoading(self)
        }
        forwarded?.resume()
    }
    override func stopLoading() { forwarded?.cancel() }
}
