import Foundation
import Testing
@testable import TongxingInfrastructure

@Suite(.serialized)
struct ListeningStatisticsTests {
    @Test func countsContinuousPlaybackButNotSeeksPausesOrStalls() {
        var a = ListeningAccumulator()
        a.sample(position: 10, uptime: 1, playing: true, duration: 100)
        a.sample(position: 11, uptime: 2, playing: true, duration: 100)
        a.sample(position: 70, uptime: 3, playing: true, duration: 100) // seek
        a.sample(position: 71, uptime: 4, playing: false, duration: 100)
        a.sample(position: 71, uptime: 20, playing: true, duration: 100)
        a.sample(position: 71, uptime: 21, playing: true, duration: 100) // stalled
        a.sample(position: 72, uptime: 22, playing: true, duration: 100)
        a.sample(position: 80, uptime: 200, playing: true, duration: 100) // suspended sampling
        #expect(a.listenedSeconds == 2)
        #expect(a.ranges == [[10, 11], [71, 72]])
    }
    @Test func replayCountsTimeButMergesCoverage() {
        var a = ListeningAccumulator()
        for _ in 0..<2 {
            a.resetBaseline()
            a.sample(position: 0, uptime: 0, playing: true, duration: 10)
            a.sample(position: 1, uptime: 1, playing: true, duration: 10)
            a.sample(position: 2, uptime: 2, playing: true, duration: 10)
        }
        a.sample(position: 1.5, uptime: 1.5, playing: true, duration: 10) // late callback ignored
        #expect(a.listenedSeconds == 4)
        #expect(a.ranges == [[0, 2]])
    }
    @Test func coverageBoundDoesNotFillUnheardGaps() {
        var a = ListeningAccumulator()
        for i in 0..<300 {
            a.resetBaseline()
            a.sample(position: Double(i * 3), uptime: 0, playing: true, duration: 1000)
            a.sample(position: Double(i * 3 + 1), uptime: 1, playing: true, duration: 1000)
        }
        #expect(a.ranges.count == 256)
        #expect(a.ranges.allSatisfy { $0[1] - $0[0] == 1 })
    }
    @Test func delayedBackgroundSampleCountsOnlyMediaProgress() {
        var a = ListeningAccumulator()
        a.sample(position: 10, uptime: 0, playing: true, duration: 100)
        a.sample(position: 70, uptime: 60, playing: true, duration: 100)
        #expect(a.listenedSeconds == 60)
        #expect(a.ranges == [[10, 70]])
    }
    @Test func interfaceVisitWithoutPlaybackAndLanguageSwitchUseSeparateSessions() async {
        let harness = ListeningHarness(); defer { harness.cleanup() }
        let statistics = harness.make()
        await statistics.setEnabled(true)
        await statistics.interfaceVisit(source: harness.source, locale: "en")
        await statistics.interfaceVisit(source: harness.source, locale: "en")
        await statistics.interfaceVisit(source: harness.source, locale: "ko")
        let events = ListeningProtocol.requests.filter { $0.path == "/api/interface-usage" }
        #expect(events.count == 2)
        #expect(ListeningProtocol.requests.filter { $0.path == "/api/listening" }.isEmpty)
        #expect(events.first?.body["clientId"] as? String == events.last?.body["clientId"] as? String)
        await statistics.setEnabled(false)
        #expect(ListeningProtocol.requests.filter { $0.path == "/api/interface-usage" && $0.body["action"] as? String == "delete" }.count == 2)
    }
    @Test func reportingDayAndPublishedIdentity() {
        let date = ISO8601DateFormatter().date(from: "2026-09-28T06:59:59Z")!
        #expect(ListeningAccumulator.reportingDay(date) == "2026-09-27")
        #expect(ListeningAccumulator.reportingDay(date.addingTimeInterval(1)) == "2026-09-28")
        let source = ListeningSource.published(pageID: "2026-09-27-weekend-sermon-drive-530", locale: "ko", sha256: String(repeating: "a", count: 64))
        #expect(source.week == "2026-09-27")
        #expect(source.trackId == "2026-09-27-weekend-sermon-drive-530-ko-aaaaaaaaaaaa")
    }
    @Test func optInSamplesAfterTokenAndRetractsEveryLanguage() async throws {
        let harness = ListeningHarness()
        defer { harness.cleanup() }
        let statistics = harness.make()
        await harness.sample(statistics, position: 0, second: 0)
        #expect(ListeningProtocol.requests.isEmpty) // default off
        await statistics.interfaceVisit(source: harness.source, locale: "en")
        await statistics.setEnabled(true)
        #expect(ListeningProtocol.requests.filter { $0.path == "/api/interface-usage" }.count == 1)
        await harness.sample(statistics, position: 0, second: 0) // token only
        await harness.sample(statistics, position: 40, second: 1) // baseline only
        await harness.sample(statistics, position: 41, second: 2)
        await statistics.flush()
        let uploads = ListeningProtocol.requests.filter { $0.path == "/api/listening" && $0.body["action"] as? String == "upsert" }
        #expect(uploads.last?.body["listenedSeconds"] as? Double == 1)
        #expect(uploads.last?.body["interfaceLocale"] as? String == "en")
        await harness.sample(statistics, position: 0, second: 3, locale: "ko")
        await harness.sample(statistics, position: 1, second: 4, locale: "ko")
        await harness.sample(statistics, position: 2, second: 5, locale: "ko")
        await statistics.setEnabled(false)
        let deletes = ListeningProtocol.requests.filter { $0.body["action"] as? String == "delete" }
        #expect(deletes.filter { $0.path == "/api/listening" }.count == 2)
        #expect(deletes.filter { $0.path == "/api/interface-usage" }.count == 1)
        let count = ListeningProtocol.requests.count
        await harness.sample(statistics, position: 3, second: 6)
        #expect(ListeningProtocol.requests.count == count)
    }
    @Test func failedUploadRetriesCumulativeAndDayRotatesIdentity() async throws {
        let harness = ListeningHarness(); defer { harness.cleanup() }
        let statistics = harness.make()
        await statistics.setEnabled(true)
        await harness.sample(statistics, position: 0, second: 0)
        await harness.sample(statistics, position: 0, second: 1)
        ListeningProtocol.failNextListening = true
        await harness.sample(statistics, position: 1, second: 2)
        await harness.sample(statistics, position: 2, second: 3)
        await harness.sample(statistics, position: 2, second: 33)
        let uploads = ListeningProtocol.requests.filter { $0.path == "/api/listening" }
        #expect(uploads.count == 2)
        #expect((uploads.last?.body["listenedSeconds"] as? Double) == 2)
        await harness.sample(statistics, position: 5, second: 86_400)
        await harness.sample(statistics, position: 6, second: 86_401)
        await harness.sample(statistics, position: 7, second: 86_402)
        let next = ListeningProtocol.requests.filter { $0.path == "/api/listening" }.last!
        #expect(next.body["clientId"] as? String != uploads.last?.body["clientId"] as? String)
        #expect(next.body["day"] as? String != uploads.last?.body["day"] as? String)
    }

    @Test func alignmentAttemptRecordKeepsOnlyWhitelistedConsistentFields() {
        let at = Date(timeIntervalSince1970: 1_760_204_679.4)
        let miss = AlignmentAttemptRecord(at: at, outcome: .noMatch, stage: .matchedAudio, reason: "low_confidence",
                                          errorCode: "Native text", rms: 0.004, matchFraction: 0.05, captureSeconds: 15.002, totalSeconds: 19.349)
        #expect(miss.atMilliseconds == 1_760_204_679_000)
        #expect(miss.reason == "low_confidence" && miss.errorCode == nil && miss.level == "low")
        #expect(miss.fractionBand == "0_045_to_0_055" && miss.captureSeconds == 15 && miss.totalMilliseconds == 19_300)
        let json = miss.json
        #expect(Set(json.keys) == ["at", "outcome", "stage", "reason", "errorCode", "level", "fractionBand", "captureSeconds", "totalMs", "shadow"])
        #expect(json["shadow"] is NSNull && json["errorCode"] is NSNull)
        let denied = AlignmentAttemptRecord(at: at, outcome: .permissionDenied, stage: .indexReady, reason: "matched",
                                            errorCode: "MIC_PERMISSION", rms: 0.5, matchFraction: 0.2, captureSeconds: 10)
        #expect(denied.reason == nil && denied.level == nil && denied.fractionBand == nil && denied.captureSeconds == nil)
        #expect(denied.errorCode == "MIC_PERMISSION")
        #expect(AlignmentAttemptRecord(at: at, outcome: .applied, stage: .recording).outcome == .cancelled)
        #expect(AlignmentAttemptRecord(at: at, outcome: .noMatch, stage: .recording).outcome == .error)
        #expect(AlignmentAttemptRecord(at: at, outcome: .applied, stage: .matchedAudio, reason: "matched", captureSeconds: 11).captureSeconds == nil)
    }
    @Test func alignmentAttemptsAppendRetryRollOverAndRetract() async {
        let harness = ListeningHarness(); defer { harness.cleanup() }
        let statistics = harness.make()
        let attempt = AlignmentAttemptRecord(at: harness.date, outcome: .applied, stage: .matchedAudio, reason: "matched", captureSeconds: 10, totalSeconds: 12)
        await statistics.recordAlignment(attempt, source: harness.source, interfaceLocale: "en", contentLocale: "zh-Hans", date: harness.date)
        #expect(ListeningProtocol.requests.isEmpty, "disabled statistics never mint or upload")
        await statistics.setEnabled(true)
        let before = ListeningProtocol.requests.count
        await statistics.recordAlignment(attempt, source: harness.source, interfaceLocale: "en", contentLocale: "zh-Hans", date: harness.date)
        ListeningProtocol.failNextAlignment = true
        await statistics.recordAlignment(attempt, source: harness.source, interfaceLocale: "en", contentLocale: "zh-Hans", date: harness.date)
        await statistics.recordAlignment(attempt, source: harness.source, interfaceLocale: "en", contentLocale: "zh-Hans", date: harness.date)
        var uploads = ListeningProtocol.requests.dropFirst(before).filter { $0.path == "/api/alignment-usage" }
        #expect(uploads.map { ($0.body["attempts"] as? [[String: Any]])?.count ?? -1 } == [1, 2, 3])
        #expect(uploads.map { $0.body["seq"] as? Int ?? -1 } == [1, 2, 3])
        #expect(uploads.last?.body["platform"] as? String == "ios" && uploads.last?.body["contentLocale"] as? String == "zh-Hans")
        #expect(ListeningProtocol.requests.dropFirst(before).filter { $0.path == "/api/session" }.count == 1)
        for _ in 0..<38 {
            await statistics.recordAlignment(attempt, source: harness.source, interfaceLocale: "en", contentLocale: "zh-Hans", date: harness.date)
        }
        uploads = ListeningProtocol.requests.dropFirst(before).filter { $0.path == "/api/alignment-usage" }
        #expect(uploads.compactMap { ($0.body["attempts"] as? [[String: Any]])?.count }.max() == 40)
        #expect(uploads.last.flatMap { ($0.body["attempts"] as? [[String: Any]])?.count } == 1, "the 41st press opens a new credential")
        #expect(ListeningProtocol.requests.dropFirst(before).filter { $0.path == "/api/session" }.count == 2)
        await statistics.setEnabled(false)
        let deletes = ListeningProtocol.requests.filter { $0.path == "/api/alignment-usage" && $0.body["action"] as? String == "delete" }
        #expect(deletes.count == 2)
    }
}

private final class ListeningHarness {
    let name = UUID().uuidString
    let defaults: UserDefaults
    let source = ListeningSource(week: "2026-09-27", trackId: "example", audioSha256: String(repeating: "a", count: 64))
    let date = Date()
    init() { defaults = UserDefaults(suiteName: name)!; ListeningProtocol.requests = []; ListeningProtocol.failNextListening = false; ListeningProtocol.failNextAlignment = false }
    func cleanup() { defaults.removePersistentDomain(forName: name) }
    func make() -> ListeningStatistics {
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [ListeningProtocol.self]
        return ListeningStatistics(origin: URL(string: "https://example.test")!, appVersion: "1.0.0", defaults: defaults, session: URLSession(configuration: config))
    }
    func sample(_ statistics: ListeningStatistics, position: Double, second: Double, locale: String = "zh-Hans") async {
        let s = locale == "zh-Hans" ? source : ListeningSource(week: source.week, trackId: locale, audioSha256: source.audioSha256)
        await statistics.sample(source: s, position: position, duration: 100, playing: true,
                                uptime: second, interfaceLocale: "en", contentLocale: locale,
                                date: date.addingTimeInterval(second))
    }
}
private final class ListeningProtocol: URLProtocol {
    struct Request { let path: String; let body: [String: Any] }
    nonisolated(unsafe) static var requests: [Request] = []
    nonisolated(unsafe) static var failNextListening = false
    nonisolated(unsafe) static var failNextAlignment = false
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        var data = request.httpBody ?? Data()
        if let stream = request.httpBodyStream {
            stream.open(); defer { stream.close() }
            var buffer = [UInt8](repeating: 0, count: 4096)
            while stream.hasBytesAvailable { let n = stream.read(&buffer, maxLength: buffer.count); if n <= 0 { break }; data.append(buffer, count: n) }
        }
        let body = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
        let path = request.url!.path
        Self.requests.append(Request(path: path, body: body))
        if path == "/api/alignment-usage", Self.failNextAlignment {
            Self.failNextAlignment = false; client?.urlProtocol(self, didFailWithError: URLError(.timedOut)); return
        }
        if path == "/api/listening", Self.failNextListening {
            Self.failNextListening = false; client?.urlProtocol(self, didFailWithError: URLError(.timedOut)); return
        }
        let response: [String: Any] = path == "/api/session"
            ? ["token": UUID().uuidString, "expiresAt": ISO8601DateFormatter().string(from: Date().addingTimeInterval(200_000))]
            : ["accepted": true]
        client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: try! JSONSerialization.data(withJSONObject: response))
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}
