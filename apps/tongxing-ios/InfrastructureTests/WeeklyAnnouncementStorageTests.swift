import CryptoKit
import Foundation
import Testing
import TongxingCore
@testable import TongxingInfrastructure

@Suite(.serialized)
struct WeeklyAnnouncementStorageTests {
    let hash = String(repeating: "a", count: 64)
    let png = Data(base64Encoded: "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a3ioAAAAASUVORK5CYII=")!
    func fixture() throws -> (MultilingualCatalog, WeeklyAnnouncement) {
        let catalog = try MultilingualCatalog.decode(JSONSerialization.data(withJSONObject: [
            "schemaVersion": MultilingualCatalog.dualScriptSchemaVersion,
            "generatedAt": "2026-10-07T00:00:00Z", "defaultPageId": "week-1",
            "pages": [["id": "week-1", "title": "Test sermon", "date": "2026-10-04", "sourceLocale": "en", "sourceIdentitySha256": hash,
                "defaultTargetLocale": "zh-Hans", "targets": ["zh-Hans": ["releasePackageUrl": "/releases-v2/week-1/zh-Hans.json",
                "releasePackageJsonSha256": hash, "contentStatus": "human_reviewed", "audioStatus": "unavailable", "capabilities": ["text"]]]]]]))
        return (catalog, .init(id: "week-1", pageID: "week-1", locale: "zh-Hans", releaseSHA256: hash,
            sourceIdentitySHA256: hash, title: "本周证道", publishedAt: "2026-10-07T00:00:00Z",
            poster: .init(url: "/posters/week-1/zh-Hans.png", sha256: SHA256.hash(data: png).map { String(format: "%02x", $0) }.joined(), bytes: Int64(png.count), width: 1, height: 1)))
    }
    @Test func verifiedPosterAndSidecarSurviveOfflineButDamagedCacheDoesNot() async throws {
        let (catalog, announcement) = try fixture()
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory); PosterURLProtocol.response = nil }
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [PosterURLProtocol.self]
        let session = URLSession(configuration: config); defer { session.invalidateAndCancel() }
        let encoded = try JSONEncoder().encode(WeeklyAnnouncementCatalog(announcements: [announcement]))
        PosterURLProtocol.response = { url in url.path.hasSuffix("json") ? encoded : png }
        let repository = WeeklyAnnouncementRepository(origin: URL(string: "https://posters.example.test")!, cacheDirectory: directory, session: session)
        #expect(try await repository.load(catalog: catalog).source == .network)
        let image = try await repository.poster(for: announcement)
        #expect(image.data == png)
        PosterURLProtocol.response = nil
        #expect(try await repository.load(catalog: catalog).source == .cache)
        #expect(try await repository.poster(for: announcement).data == png)
        try Data("broken".utf8).write(to: image.localURL)
        do { _ = try await repository.poster(for: announcement); Issue.record("Damaged offline image must fail") } catch {}
    }
    @Test func rejectsWrongHashWrongDimensionsAndForeignRedirect() async throws {
        let (_, value) = try fixture()
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory); PosterURLProtocol.response = nil; PosterURLProtocol.foreign = false }
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [PosterURLProtocol.self]
        let session = URLSession(configuration: config); defer { session.invalidateAndCancel() }
        let repository = WeeklyAnnouncementRepository(origin: URL(string: "https://posters.example.test")!, cacheDirectory: directory, session: session)
        PosterURLProtocol.response = { _ in Data(repeating: 0, count: png.count) }
        do { _ = try await repository.poster(for: value); Issue.record("Wrong hash must fail") }
        catch { #expect(error as? ContentStorageError == .checksumMismatch) }
        PosterURLProtocol.response = { _ in png }
        let wrongDimensions = WeeklyAnnouncement(id: value.id, pageID: value.pageID, locale: value.locale, releaseSHA256: value.releaseSHA256,
            sourceIdentitySHA256: value.sourceIdentitySHA256, title: value.title, publishedAt: value.publishedAt,
            poster: .init(url: value.poster.url, sha256: value.poster.sha256, bytes: value.poster.bytes, width: 2, height: 1))
        do { _ = try await repository.poster(for: wrongDimensions); Issue.record("Wrong dimensions must fail") }
        catch { #expect(error as? ContentStorageError == .invalidResponse) }
        PosterURLProtocol.foreign = true
        do { _ = try await repository.poster(for: value); Issue.record("Foreign response must fail") }
        catch { #expect(error as? ContentStorageError == .invalidResponse) }
    }
}

private final class PosterURLProtocol: URLProtocol {
    static var response: ((URL) -> Data)?
    static var foreign = false
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        guard let data = Self.response?(request.url!) else {
            client?.urlProtocol(self, didFailWithError: URLError(.notConnectedToInternet)); return
        }
        let responseURL = Self.foreign ? URL(string: "https://foreign.test/poster.png")! : request.url!
        client?.urlProtocol(self, didReceive: HTTPURLResponse(url: responseURL, statusCode: 200, httpVersion: nil, headerFields: ["Content-Length": String(data.count)])!, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: data); client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}
