import Foundation
import XCTest
@testable import Tongxing

final class AppDeepLinkTests: XCTestCase {
    private let host = "ai-for-god-sermon-audio.web.app"
    private let schemes: Set<String> = ["tongxing", "tongxing-beta"]

    private func url(_ value: String) -> URL { URL(string: value)! }

    func testQueryLinkFromPoster() {
        let link = AppDeepLink.parse(url("https://\(host)/?week=if-i-had-more-time-jesus-wins&contentLang=zh-Hans&lang=zh"),
                                     allowedHost: host, allowedSchemes: schemes)
        XCTAssertEqual(link, AppDeepLink(pageID: "if-i-had-more-time-jesus-wins", locale: "zh-Hans", source: .universalLink))
    }

    func testPathLink() {
        let link = AppDeepLink.parse(url("https://\(host)/pages/if-i-had-more-time-jesus-wins/ko/"),
                                     allowedHost: host, allowedSchemes: schemes)
        XCTAssertEqual(link, AppDeepLink(pageID: "if-i-had-more-time-jesus-wins", locale: "ko", source: .universalLink))
    }

    func testPathWithoutLocaleUsesDefault() {
        let link = AppDeepLink.parse(url("https://\(host)/pages/if-i-had-more-time-jesus-wins"),
                                     allowedHost: host, allowedSchemes: schemes)
        XCTAssertEqual(link, AppDeepLink(pageID: "if-i-had-more-time-jesus-wins", locale: nil, source: .universalLink))
    }

    func testCustomScheme() {
        let link = AppDeepLink.parse(url("tongxing://page/if-i-had-more-time-jesus-wins?contentLang=es"),
                                     allowedHost: host, allowedSchemes: schemes)
        XCTAssertEqual(link, AppDeepLink(pageID: "if-i-had-more-time-jesus-wins", locale: "es", source: .customScheme))
    }

    func testRejectsForeignHost() {
        XCTAssertNil(AppDeepLink.parse(url("https://evil.example/?week=if-i-had-more-time-jesus-wins"),
                                       allowedHost: host, allowedSchemes: schemes))
    }

    func testRejectsUnsafePageID() {
        XCTAssertNil(AppDeepLink.parse(url("https://\(host)/?week=../other-page"),
                                       allowedHost: host, allowedSchemes: schemes))
    }

    func testRejectsUnknownLocaleButKeepsPage() {
        let link = AppDeepLink.parse(url("https://\(host)/?week=page&contentLang=fr"),
                                     allowedHost: host, allowedSchemes: schemes)
        XCTAssertEqual(link, AppDeepLink(pageID: "page", locale: nil, source: .universalLink))
    }
}

/// Model routing checks use only synthetic catalog data and a private URLSession.
/// They do not exercise iOS Universal Link delivery or real-device behavior.
@MainActor
final class AppDeepLinkModelTests: XCTestCase {
    private let defaultPage = "synthetic-default-page"
    private let targetPage = "synthetic-target-page"

    func testLinkDuringStartupSurvivesDelayedInitialCatalogLoad() async throws {
        let fixture = try RoutingFixture(holdWeekly: true)
        defer { fixture.dispose() }
        let startTask = Task { await fixture.model.start() }
        await fulfillment(of: [fixture.weeklyRequested], timeout: 10)

        let linkStarted = expectation(description: "deep-link task started")
        let linkTask = Task {
            linkStarted.fulfill()
            await fixture.model.openDeepLink(fixture.link(pageID: targetPage, locale: "ko"))
        }
        await fulfillment(of: [linkStarted], timeout: 10)

        // The former implementation starts a second catalog load while weekly
        // is held. Give it a chance to finish so the initial load then reproduces
        // the overwrite. A corrected implementation may instead wait for start.
        let deadline = Date().addingTimeInterval(1)
        while fixture.model.selectedPageID != targetPage && Date() < deadline {
            try await Task.sleep(nanoseconds: 10_000_000)
        }
        RoutingProtocol.releaseWeekly()
        await startTask.value
        await linkTask.value
        XCTAssertEqual(fixture.model.selectedPageID, targetPage)
        XCTAssertEqual(fixture.model.selectedContentLocale, "ko")
    }

    func testWarmLinkSelectsRequestedPageAndLocale() async throws {
        let fixture = try RoutingFixture()
        defer { fixture.dispose() }
        await fixture.model.start()
        XCTAssertEqual(fixture.model.selectedPageID, defaultPage)
        await fixture.model.openDeepLink(fixture.link(pageID: targetPage, locale: "ko"))
        XCTAssertEqual(fixture.model.selectedPageID, targetPage)
        XCTAssertEqual(fixture.model.selectedContentLocale, "ko")
    }

    func testMissingLinkPreservesExistingSelectionAndLocale() async throws {
        let fixture = try RoutingFixture()
        defer { fixture.dispose() }
        await fixture.model.start()
        await fixture.model.openDeepLink(fixture.link(pageID: targetPage, locale: "ko"))
        XCTAssertEqual(fixture.model.selectedPageID, targetPage)
        XCTAssertEqual(fixture.model.selectedContentLocale, "ko")
        await fixture.model.openDeepLink(fixture.link(pageID: "withdrawn-page", locale: "zh-Hans"))
        XCTAssertEqual(fixture.model.selectedPageID, targetPage)
        XCTAssertEqual(fixture.model.selectedContentLocale, "ko")
    }

    func testLinkDuringRefreshSurvivesDelayedCatalogResponse() async throws {
        let fixture = try RoutingFixture()
        defer { fixture.dispose() }
        await fixture.model.start()
        XCTAssertEqual(fixture.model.selectedPageID, defaultPage)

        let catalogRequested = expectation(description: "refresh catalog request held")
        RoutingProtocol.holdNextCatalog(requested: catalogRequested)
        let refreshTask = Task { await fixture.model.refresh() }
        await fulfillment(of: [catalogRequested], timeout: 10)
        let linkStarted = expectation(description: "link received during refresh")
        let linkTask = Task {
            linkStarted.fulfill()
            await fixture.model.openDeepLink(fixture.link(pageID: targetPage, locale: "ko"))
        }
        await fulfillment(of: [linkStarted], timeout: 10)
        RoutingProtocol.releaseCatalog()
        await refreshTask.value
        await linkTask.value
        XCTAssertEqual(fixture.model.selectedPageID, targetPage)
        XCTAssertEqual(fixture.model.selectedContentLocale, "ko")
    }

    func testManualSelectionSurvivesDelayedMissingLinkRefresh() async throws {
        let fixture = try RoutingFixture()
        defer { fixture.dispose() }
        await fixture.model.start()
        XCTAssertEqual(fixture.model.selectedPageID, defaultPage)

        let catalogRequested = expectation(description: "missing-link catalog request held")
        RoutingProtocol.holdNextCatalog(requested: catalogRequested)
        let linkTask = Task {
            await fixture.model.openDeepLink(fixture.link(pageID: "withdrawn-page", locale: "zh-Hans"))
        }
        await fulfillment(of: [catalogRequested], timeout: 10)
        let target = try XCTUnwrap(fixture.model.independentPages.first { $0.id == targetPage })
        fixture.model.selectPublishedPage(target)
        fixture.model.selectPublishedContentLanguage("ko")
        XCTAssertEqual(fixture.model.selectedPageID, targetPage)
        XCTAssertEqual(fixture.model.selectedContentLocale, "ko")
        RoutingProtocol.releaseCatalog()
        await linkTask.value
        XCTAssertEqual(fixture.model.selectedPageID, targetPage)
        XCTAssertEqual(fixture.model.selectedContentLocale, "ko")
    }
}

@MainActor
private final class RoutingFixture {
    let model: AppModel
    let weeklyRequested: XCTestExpectation
    private let directory: URL
    private let defaults: UserDefaults
    private let suite: String
    private let session: URLSession

    init(holdWeekly: Bool = false) throws {
        suite = "DeepLinkRouting-\(UUID().uuidString)"
        directory = FileManager.default.temporaryDirectory.appendingPathComponent(suite)
        defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        weeklyRequested = XCTestExpectation(description: "initial weekly request held")
        let fixtureRoot = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
        let weekly = try Data(contentsOf: fixtureRoot.appendingPathComponent("Core/Tests/TongxingCoreTests/Fixtures/catalog.synthetic.json"))
        let hash = String(repeating: "a", count: 64)
        func page(_ id: String) -> [String: Any] {
            func target(_ locale: String) -> [String: Any] {
                ["releasePackageUrl": "/releases-v2/\(id)/\(locale).json",
                 "releasePackageJsonSha256": hash, "contentStatus": "human_reviewed",
                 "audioStatus": "unavailable", "capabilities": ["text"]]
            }
            return ["id": id, "title": "Synthetic \(id)", "date": "2026-10-04", "sourceLocale": "en",
                    "sourceIdentitySha256": hash, "defaultTargetLocale": "zh-Hans",
                    "targets": ["zh-Hans": target("zh-Hans"), "ko": target("ko")]]
        }
        let catalog = try JSONSerialization.data(withJSONObject: [
            "schemaVersion": "sermon-multilingual-catalog-v3", "generatedAt": "2026-10-07T00:00:00Z",
            "defaultPageId": "synthetic-default-page",
            "pages": [page("synthetic-default-page"), page("synthetic-target-page")]
        ])
        RoutingProtocol.install(weekly: weekly, catalog: catalog,
                                holdWeekly: holdWeekly, requested: weeklyRequested)
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [RoutingProtocol.self]
        config.urlCache = nil
        session = URLSession(configuration: config)
        model = AppModel(supportDirectory: directory,
                         contentOrigin: URL(string: "https://ai-for-god-sermon-audio-dev.web.app")!,
                         session: session, statisticsDefaults: defaults,
                         applicationBundleIdentifier: "com.jonathanjing.tongxing.beta")
    }

    func link(pageID: String, locale: String) -> URL {
        URL(string: "https://ai-for-god-sermon-audio-dev.web.app/?week=\(pageID)&contentLang=\(locale)")!
    }

    func dispose() {
        RoutingProtocol.releaseWeekly()
        RoutingProtocol.releaseCatalog()
        model.playback.clear()
        session.invalidateAndCancel()
        defaults.removePersistentDomain(forName: suite)
        try? FileManager.default.removeItem(at: directory)
        RoutingProtocol.reset()
    }
}

/// Controlled response delivery without blocking URLSession's worker thread.
private final class RoutingProtocol: URLProtocol {
    private static let lock = NSLock()
    private static var files: [String: Data] = [:]
    private static var holdWeekly = false
    private static var pendingWeekly: RoutingProtocol?
    private static var requested: XCTestExpectation?
    private static var holdCatalog = false
    private static var pendingCatalog: RoutingProtocol?
    private static var catalogRequested: XCTestExpectation?
    private let deliveryLock = NSRecursiveLock()
    private var stopped = false

    static func install(weekly: Data, catalog: Data, holdWeekly: Bool, requested: XCTestExpectation) {
        lock.lock(); defer { lock.unlock() }
        files = ["/weekly.json": weekly, "/multilingual-v3.json": catalog]
        self.holdWeekly = holdWeekly
        pendingWeekly = nil
        self.requested = requested
        holdCatalog = false
        pendingCatalog = nil
        catalogRequested = nil
    }

    static func holdNextCatalog(requested: XCTestExpectation) {
        lock.lock(); defer { lock.unlock() }
        holdCatalog = true
        pendingCatalog = nil
        catalogRequested = requested
    }

    static func releaseWeekly() {
        lock.lock()
        let pending = pendingWeekly
        let data = files["/weekly.json"]
        pendingWeekly = nil
        holdWeekly = false
        lock.unlock()
        if let pending, let data { pending.deliver(data: data, status: 200) }
    }

    static func releaseCatalog() {
        lock.lock()
        let pending = pendingCatalog
        let data = files["/multilingual-v3.json"]
        pendingCatalog = nil
        holdCatalog = false
        catalogRequested = nil
        lock.unlock()
        if let pending, let data { pending.deliver(data: data, status: 200) }
    }

    static func reset() {
        lock.lock(); defer { lock.unlock() }
        files = [:]; pendingWeekly = nil; requested = nil; holdWeekly = false
        pendingCatalog = nil; catalogRequested = nil; holdCatalog = false
    }

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        guard let url = request.url else {
            client?.urlProtocol(self, didFailWithError: URLError(.badURL)); return
        }
        Self.lock.lock()
        if url.path == "/weekly.json" && Self.holdWeekly {
            Self.pendingWeekly = self
            let signal = Self.requested
            Self.lock.unlock()
            signal?.fulfill()
            return
        }
        if url.path == "/multilingual-v3.json" && Self.holdCatalog {
            Self.holdCatalog = false
            Self.pendingCatalog = self
            let signal = Self.catalogRequested
            Self.lock.unlock()
            signal?.fulfill()
            return
        }
        let data = Self.files[url.path]
        Self.lock.unlock()
        deliver(data: data, status: data == nil ? 404 : 200)
    }

    private func deliver(data: Data?, status: Int) {
        deliveryLock.lock(); defer { deliveryLock.unlock() }
        guard !stopped, let url = request.url else { return }
        let response = HTTPURLResponse(url: url, statusCode: status, httpVersion: "HTTP/1.1",
                                       headerFields: ["Content-Length": String(data?.count ?? 0)])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        if let data { client?.urlProtocol(self, didLoad: data) }
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {
        deliveryLock.lock(); stopped = true; deliveryLock.unlock()
    }
}
