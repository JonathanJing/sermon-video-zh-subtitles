import CryptoKit
import Foundation
import TongxingCore
import XCTest
@testable import Tongxing

/// Synthetic hosted checks cover app state; they do not establish real-device push delivery.
@MainActor
final class WeeklyUpdateModelTests: XCTestCase {
    func testOpeningSameUnchangedReleasePreservesPreparedPlaybackAndPosition() async throws {
        let fixture = try Fixture()
        defer { fixture.dispose() }
        let (catalog, page) = try await fixture.preparePublishedPage()
        fixture.model.playback.jump(to: 7)
        try await eventually { abs(fixture.model.playback.position - 7) < 0.1 }
        let locale = fixture.model.selectedAudioLocale
        fixture.model.openWeeklyUpdate(page, catalog: catalog)
        XCTAssertTrue(fixture.model.playback.isReady)
        XCTAssertEqual(fixture.model.selectedAudioLocale, locale)
        XCTAssertEqual(fixture.model.selectedPageID, page.id)
        XCTAssertEqual(fixture.model.playback.position, 7, accuracy: 0.1)
    }

    func testOpeningSamePageWithChangedReleaseInvalidatesOldPreparedAudio() async throws {
        let fixture = try Fixture()
        defer { fixture.dispose() }
        let (catalog, page) = try await fixture.preparePublishedPage()
        fixture.model.playback.play()
        try await eventually { fixture.model.playback.isPlaying }
        let locale = fixture.model.selectedContentLocale
        var value = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(catalog)) as? [String: Any])
        var pages = try XCTUnwrap(value["pages"] as? [[String: Any]])
        let index = try XCTUnwrap(pages.firstIndex { $0["id"] as? String == page.id })
        var targets = try XCTUnwrap(pages[index]["targets"] as? [String: [String: Any]])
        targets[locale]?["releasePackageJsonSha256"] = String(repeating: "d", count: 64)
        pages[index]["targets"] = targets
        value["pages"] = pages
        let revised = try MultilingualCatalog.decode(JSONSerialization.data(withJSONObject: value))
        let next = try XCTUnwrap(revised.pages.first { $0.id == page.id })
        fixture.model.openWeeklyUpdate(next, catalog: revised)
        // Synchronous invalidation must happen before a replacement download can run.
        XCTAssertFalse(fixture.model.playback.isReady)
        XCTAssertFalse(fixture.model.playback.isPlaying)
        XCTAssertNil(fixture.model.selectedAudioLocale)
        XCTAssertEqual(fixture.model.selectedPageID, page.id)
        XCTAssertEqual(fixture.model.multilingualCatalog, revised)
    }

    func testDefaultAndNotificationAnnouncementStatesRemainIndependentAndMergeReceipts() async throws {
        let fixture = try Fixture()
        defer { fixture.dispose() }
        let (original, originalPage) = try await fixture.preparePublishedPage()
        fixture.model.playback.play()
        try await eventually { fixture.model.playback.isPlaying }
        XCTAssertFalse(fixture.model.weeklyUpdates === fixture.model.notificationWeeklyUpdates)
        var value = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(original)) as? [String: Any])
        var pages = try XCTUnwrap(value["pages"] as? [[String: Any]])
        var second = try XCTUnwrap(pages.first { $0["id"] as? String == originalPage.id })
        second["id"] = "targeted-notification-page"
        var secondTargets = try XCTUnwrap(second["targets"] as? [String: [String: Any]])
        for locale in secondTargets.keys {
            secondTargets[locale]?["releasePackageUrl"] = "/releases-v2/targeted-notification-page/\(locale).json"
        }
        second["targets"] = secondTargets
        pages.append(second)
        value["pages"] = pages
        let catalog = try MultilingualCatalog.decode(JSONSerialization.data(withJSONObject: value))
        let locale = fixture.model.selectedContentLocale
        let png = Data(base64Encoded: "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a3ioAAAAASUVORK5CYII=")!
        let hash = SHA256.hash(data: png).map { String(format: "%02x", $0) }.joined()
        func announcement(_ page: MultilingualPage) throws -> WeeklyAnnouncement {
            let target = try XCTUnwrap(page.targets[locale])
            return .init(id: page.id, pageID: page.id, locale: locale,
                releaseSHA256: target.releasePackageJsonSha256, sourceIdentitySHA256: page.sourceIdentitySha256,
                title: page.title ?? "Synthetic weekly poster", publishedAt: "2026-10-07T00:00:00Z",
                poster: .init(url: "/posters/fixture.png", sha256: hash, bytes: Int64(png.count), width: 1, height: 1))
        }
        let targeted = try XCTUnwrap(catalog.pages.first { $0.id == "targeted-notification-page" })
        let sidecar = try JSONEncoder().encode(WeeklyAnnouncementCatalog(announcements: [try announcement(catalog.defaultPage), try announcement(targeted)]))
        WeeklyModelPosterProtocol.responses = ["/weekly-announcements-v1.json": sidecar, "/posters/fixture.png": png]
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [WeeklyModelPosterProtocol.self]
        let session = URLSession(configuration: config)
        defer { session.invalidateAndCancel(); WeeklyModelPosterProtocol.responses = [:] }
        let generic = WeeklyUpdates(origin: fixture.model.mediaOrigin, support: fixture.directory, session: session)
        let notification = WeeklyUpdates(origin: fixture.model.mediaOrigin, support: fixture.directory, session: session)
        await notification.load(catalog: catalog, locale: locale, pageID: targeted.id)
        await generic.load(catalog: catalog, locale: locale)
        XCTAssertEqual(notification.announcement?.pageID, targeted.id)
        XCTAssertEqual(generic.announcement?.pageID, catalog.defaultPageId)
        XCTAssertNotNil(notification.posterData)
        XCTAssertTrue(fixture.model.playback.isReady, "Discovery must leave prepared playback intact")
        XCTAssertTrue(fixture.model.playback.isPlaying, "Discovery must preserve active playback")
        XCTAssertEqual(fixture.model.selectedPageID, originalPage.id)
        notification.markSeen()
        generic.markSeen()
        let reopened = WeeklyUpdates(origin: fixture.model.mediaOrigin, support: fixture.directory, session: session)
        await reopened.load(catalog: catalog, locale: locale, pageID: targeted.id)
        XCTAssertFalse(reopened.isNew, "The generic receipt write must preserve the targeted receipt")
        await reopened.load(catalog: catalog, locale: locale)
        XCTAssertFalse(reopened.isNew)
    }

    private func eventually(_ predicate: @MainActor () -> Bool) async throws {
        let deadline = Date().addingTimeInterval(30)
        while !predicate() {
            guard Date() < deadline else { throw TestError.timeout }
            try await Task.sleep(nanoseconds: 20_000_000)
        }
    }
    private enum TestError: Error { case timeout }

    @MainActor
    private final class Fixture {
        let directory: URL
        let defaults: UserDefaults
        let suite: String
        let model: AppModel
        init() throws {
            suite = "WeeklyUpdateModel-\(UUID().uuidString)"
            directory = FileManager.default.temporaryDirectory.appendingPathComponent(suite)
            defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
            model = UITestLaunch.makeFixtureModel(supportDirectory: directory, statisticsDefaults: defaults, nativePublishedPage: true)
        }
        func preparePublishedPage() async throws -> (MultilingualCatalog, MultilingualPage) {
            await model.start()
            let catalog = try XCTUnwrap(model.multilingualCatalog)
            let page = try XCTUnwrap(model.independentPages.first)
            model.selectPublishedPage(page)
            let deadline = Date().addingTimeInterval(30)
            while !model.playback.isReady || model.selectedAudioLocale == nil {
                guard Date() < deadline else { throw TestError.timeout }
                try await Task.sleep(nanoseconds: 20_000_000)
            }
            return (catalog, page)
        }
        func dispose() {
            model.playback.clear()
            model.mediaSession.invalidateAndCancel()
            defaults.removePersistentDomain(forName: suite)
            try? FileManager.default.removeItem(at: directory)
        }
    }
}

private final class WeeklyModelPosterProtocol: URLProtocol {
    static var responses: [String: Data] = [:]
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        guard let url = request.url, let data = Self.responses[url.path] else {
            client?.urlProtocol(self, didFailWithError: URLError(.notConnectedToInternet)); return
        }
        let response = HTTPURLResponse(url: url, statusCode: 200, httpVersion: nil, headerFields: ["Content-Length": String(data.count)])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: data)
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}
