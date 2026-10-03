import CryptoKit
import Foundation
import Testing
import TongxingCore
@testable import TongxingInfrastructure

@Suite(.serialized)
struct DevCandidateReaderTests {
    private let devOrigin = URL(string: "https://ai-for-god-sermon-audio-dev.web.app")!
    private func readback() throws -> [String: Any] {
        let url = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Core/Tests/TongxingCoreTests/Fixtures/dev-candidate-catalog-readback.json")
        return try #require(JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
    }
    private func metadataFiles() throws -> [String: Data] {
        let fixture = try readback()
        var catalog = try #require(fixture["catalog"] as? [String: Any])
        let releases = try #require(fixture["releases"] as? [String: [String: Any]])
        var pages = catalog["pages"] as! [[String: Any]], targets = pages[1]["targets"] as! [String: [String: Any]]
        var files: [String: Data] = [:]
        for (locale, release) in releases {
            let bytes = try JSONSerialization.data(withJSONObject: release)
            let path = targets[locale]!["releasePackageUrl"] as! String
            files[path] = bytes
            targets[locale]!["releasePackageJsonSha256"] = SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined()
        }
        // A synthetic published Korean locale keeps Production usable while the
        // independently bound podcast candidates remain hidden.
        let formalID = pages[0]["id"] as! String
        var formalTargets = pages[0]["targets"] as! [String: [String: Any]]
        var formal = releases["zh-Hans"]!
        formal["pageId"] = formalID; formal["targetLocale"] = "ko"; formal["contentLocale"] = "ko"
        formal["audioLocale"] = "ko"; formal["interfaceLocale"] = "ko"
        formal["status"] = "published_http_verified"
        formal["httpVerification"] = ["status": "pass", "evidenceSha256": String(repeating: "a", count: 64)]
        formal["assets"] = (formal["assets"] as! [[String: Any]]).map { asset in
            var changed = asset
            let role = changed["role"] as! String
            changed["path"] = role == "page" ? "/pages/\(formalID)/ko/index.html" : "/\(role == "audio" ? "media" : role)/\(formalID)/ko.\(role == "audio" ? "mp3" : "json")"
            return changed
        }
        let formalBytes = try JSONSerialization.data(withJSONObject: formal)
        files[formalTargets["ko"]!["releasePackageUrl"] as! String] = formalBytes
        formalTargets["ko"]!["releasePackageJsonSha256"] = SHA256.hash(data: formalBytes).map { String(format: "%02x", $0) }.joined()
        pages[0]["targets"] = formalTargets
        pages[1]["targets"] = targets; catalog["pages"] = pages
        files["/multilingual-v3.json"] = try JSONSerialization.data(withJSONObject: catalog)
        return files
    }
    private func frozenFiles(root: URL) throws -> [String: Data] {
        var files: [String: Data] = [:]
        let enumerator = try #require(FileManager.default.enumerator(at: root, includingPropertiesForKeys: nil))
        for case let url as URL in enumerator where url.pathExtension == "json" {
            files[String(url.path.dropFirst(root.path.count))] = try Data(contentsOf: url)
        }
        return files
    }
    private func session(files: [String: Data]) -> URLSession {
        CandidateFixtureProtocol.files = files
        CandidateFixtureProtocol.stalledPaths = []
        CandidateFixtureProtocol.requestedPaths = []
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [CandidateFixtureProtocol.self]
        return URLSession(configuration: config)
    }

    @Test func repositoryRequiresExplicitDevOriginAndOptInForNetworkAndCache() async throws {
        let files = try metadataFiles(), session = session(files: files)
        defer { session.invalidateAndCancel() }
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let dev = MultilingualCatalogRepository(origin: devOrigin, cacheDirectory: root, session: session, allowDevCandidate: true)
        let catalog = try await dev.loadCatalog().catalog
        let page = catalog.pages[1]
        #expect(page.targets["ko"]?.contentStatus == "machine_reviewed")
        for locale in ["zh-Hans", "ko", "es"] {
            let release = try await dev.loadRelease(page: page, locale: locale)
            #expect(release.status == "candidate")
        }
        // The same frozen raw cache must be projected under the caller's current
        // configuration; a previous Dev load cannot promote it to Production.
        for (index, origin) in [devOrigin, URL(string: "https://production.example.test")!].enumerated() {
            let production = MultilingualCatalogRepository(origin: origin, cacheDirectory: root, session: session, allowDevCandidate: index == 1)
            let projected = try await production.loadCatalog().catalog
            #expect(projected.pages.count == 1)
            #expect(projected.defaultPage.targets.keys.sorted() == ["ko"])
            #expect(projected.defaultPage.defaultTargetLocale == "ko")
            do { _ = try await production.loadRelease(page: page, locale: "zh-Hans"); Issue.record("Production must reject candidate, including cached bytes") }
            catch { }
            let package = try await dev.loadRelease(page: page, locale: "zh-Hans")
            do { _ = try await production.loadPage(for: package); Issue.record("Page entry must recheck Production policy") }
            catch { }
            do { _ = try await production.loadAudio(for: package, page: page); Issue.record("Audio entry must recheck Production policy") }
            catch { }
        }
        CandidateFixtureProtocol.files = [:]
        let cached = try await dev.loadCatalog()
        #expect(cached.source == .cache)
        #expect(cached.catalog.pages[1].targets["es"]?.contentStatus == "machine_reviewed")
        let production = MultilingualCatalogRepository(origin: devOrigin, cacheDirectory: root, session: session)
        #expect(try await production.loadCatalog().catalog.pages.count == 1)
        let cachedFormal = root.appendingPathComponent("Releases/\(catalog.pages[0].id)/ko.json")
        try Data("tampered".utf8).write(to: cachedFormal)
        do { _ = try await production.loadCatalog(); Issue.record("Damaged or candidate-only caches must not be selectable") }
        catch { }
    }

    @Test func coldDeadlineRetainsAlreadyVerifiedSiblingAndWarmCacheNeedsNoPackageGet() async throws {
        let files = try metadataFiles(), session = session(files: files)
        defer { session.invalidateAndCancel(); CandidateFixtureProtocol.stalledPaths = [] }
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let formalID = "2026-09-27-weekend-sermon-drive-530"
        CandidateFixtureProtocol.stalledPaths = ["/releases-v2/\(formalID)/zh-Hans.json"]
        let repository = MultilingualCatalogRepository(origin: devOrigin, cacheDirectory: root, session: session, publicationCheckSeconds: 0.05)
        let partial = try await repository.loadCatalog()
        #expect(partial.catalog.defaultPage.id == formalID)
        #expect(partial.catalog.defaultPage.targets.keys.sorted() == ["ko"])
        // Serve a fresh catalog but no packages. The prior immutable verified
        // Korean release remains usable; unknown/candidate siblings stay hidden.
        CandidateFixtureProtocol.stalledPaths = []
        CandidateFixtureProtocol.files = ["/multilingual-v3.json": files["/multilingual-v3.json"]!]
        CandidateFixtureProtocol.requestedPaths = []
        #expect(try await repository.loadCatalog().catalog.defaultPage.targets.keys.sorted() == ["ko"])
        #expect(!CandidateFixtureProtocol.requestedPaths.contains("/releases-v2/\(formalID)/ko.json"))
        #expect(!CandidateFixtureProtocol.requestedPaths.contains("/releases-v2/if-i-had-more-time-jesus-is-worthy/zh-Hans.json"))
    }

    @Test(.enabled(if: ProcessInfo.processInfo.environment["TONGXING_DEV_CATALOG_FIXTURE_ROOT"] != nil))
    func frozenRealCandidateCatalogReleasePageAndTranscriptLoadOffline() async throws {
        let path = try #require(ProcessInfo.processInfo.environment["TONGXING_DEV_CATALOG_FIXTURE_ROOT"])
        let fixtureRoot = URL(fileURLWithPath: path)
        let session = session(files: try frozenFiles(root: fixtureRoot))
        defer { session.invalidateAndCancel() }
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let repository = MultilingualCatalogRepository(origin: devOrigin, cacheDirectory: root, session: session, allowDevCandidate: true)
        let catalog = try await repository.loadCatalog().catalog
        let production = MultilingualCatalogRepository(origin: devOrigin, cacheDirectory: root.appendingPathComponent("production"), session: session)
        let published = try await production.loadCatalog()
        #expect(published.catalog.pages.map(\.id) == ["2026-09-27-weekend-sermon-drive-530"])
        let page = try #require(catalog.pages.first { $0.id == "if-i-had-more-time-jesus-is-worthy" })
        for locale in ["zh-Hans", "ko", "es"] {
            let release = try await repository.loadRelease(page: page, locale: locale)
            let content = try await repository.loadPage(for: release)
            #expect(content.html.contains("Dev POC"))
            #expect(content.html.contains(locale == "zh-Hans" ? "Human reviewed content" : "Machine reviewed content; human review pending"))
            let transcript = try await repository.loadPublishedTranscript(for: release, page: page)
            #expect(transcript.contentStatus == release.contentStatus)
            #expect(transcript.releaseStatus == "candidate")
            #expect(transcript.fullText.count == 839 && transcript.captions.count == 839)
        }
        CandidateFixtureProtocol.files = [:]
        #expect(try await repository.loadCatalog().source == .cache)
        #expect(try await production.loadCatalog().catalog.pages.map(\.id) == ["2026-09-27-weekend-sermon-drive-530"])
        for locale in ["zh-Hans", "ko", "es"] {
            let release = try await repository.loadRelease(page: page, locale: locale)
            #expect(try await repository.loadPage(for: release).html.contains("Dev POC"))
            #expect(try await repository.loadPublishedTranscript(for: release, page: page).captions.count == 839)
        }
    }
}

private final class CandidateFixtureProtocol: URLProtocol {
    private static let lock = NSLock()
    private static var stored: [String: Data] = [:]
    private static var stalled: Set<String> = []
    private static var requests: [String] = []
    static var requestedPaths: [String] {
        get { lock.lock(); defer { lock.unlock() }; return requests }
        set { lock.lock(); defer { lock.unlock() }; requests = newValue }
    }
    private static func record(_ path: String) { lock.lock(); defer { lock.unlock() }; requests.append(path) }
    static var stalledPaths: Set<String> {
        get { lock.lock(); defer { lock.unlock() }; return stalled }
        set { lock.lock(); defer { lock.unlock() }; stalled = newValue }
    }
    static var files: [String: Data] {
        get { lock.lock(); defer { lock.unlock() }; return stored }
        set { lock.lock(); defer { lock.unlock() }; stored = newValue }
    }
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        guard let url = request.url else { client?.urlProtocol(self, didFailWithError: URLError(.badURL)); return }
        Self.record(url.path)
        if Self.stalledPaths.contains(url.path) { return }
        let bytes = Self.files[url.path]
        let response = HTTPURLResponse(url: url, statusCode: bytes == nil ? 404 : 200, httpVersion: "HTTP/1.1", headerFields: nil)!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        if let bytes { client?.urlProtocol(self, didLoad: bytes) }
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() { }
}
