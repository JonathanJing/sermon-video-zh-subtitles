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

    @Test func multilingualCatalogAndReleaseAreHashBoundAndSurviveOfflineReload() async throws {
        let fixture = try multilingualFixture()
        StubURLProtocol.install(host: baseURL.host!) { request in
            switch request.url?.path {
            case "/multilingual-v2.json": return .init(chunks: [fixture.catalog])
            case "/releases/page-1/ko.json": return .init(chunks: [fixture.release])
            case "/pages/page-1/ko/index.html": return .init(chunks: [fixture.page])
            default: return .init(status: 404, chunks: [Data("missing".utf8)])
            }
        }
        let repository = MultilingualCatalogRepository(
            origin: baseURL, cacheDirectory: directory.appendingPathComponent("multilingual"), session: session
        )
        let online = try await repository.loadCatalog()
        #expect(online.source == .network)
        let page = online.catalog.defaultPage
        let package = try await repository.loadRelease(page: page, locale: "ko")
        #expect(try package.pageURL(relativeTo: baseURL).path == "/pages/page-1/ko/index.html")
        stub(.init(chunks: [Data("modified page".utf8)]))
        do { _ = try await repository.loadPage(for: package); Issue.record("Modified network page must fail") }
        catch { #expect(error as? ContentStorageError == .checksumMismatch) }
        stub(.init(chunks: [fixture.page]))
        #expect(try await repository.loadPage(for: package).html.contains("한국어"))

        stub(.init(chunks: [], error: URLError(.notConnectedToInternet)))
        let offline = try await repository.loadCatalog()
        #expect(offline.source == .cache)
        #expect(try await repository.loadRelease(page: offline.catalog.defaultPage, locale: "ko") == package)
        #expect(try await repository.loadPage(for: package).html.contains("한국어"))

        let pageHash = package.assets.first { $0.role == .page }!.sha256
        let cachedPage = directory.appendingPathComponent("multilingual/Pages/\(pageHash).html")
        try Data("tampered".utf8).write(to: cachedPage)
        do { _ = try await repository.loadPage(for: package); Issue.record("Tampered page must fail") }
        catch { #expect(error as? ContentStorageError == .checksumMismatch) }
    }

    @Test func damagedPreferredCatalogCacheFallsBackAndPreservesNetworkError() async throws {
        let legacy = try multilingualFixture()
        StubURLProtocol.install(host: baseURL.host!) { request in
            request.url?.path == "/multilingual-v2.json"
                ? .init(chunks: [legacy.catalog]) : .init(status: 404, chunks: [])
        }
        let cache = directory.appendingPathComponent("multilingual-cache-fallback")
        let repository = MultilingualCatalogRepository(origin: baseURL, cacheDirectory: cache, session: session)
        #expect(try await repository.loadCatalog().source == .network)

        stub(.init(chunks: [], error: URLError(.notConnectedToInternet)))
        let preferred = cache.appendingPathComponent("multilingual-v3.json")
        for invalid in [Data("{".utf8), legacy.catalog] {
            try invalid.write(to: preferred)
            let fallback = try await repository.loadCatalog()
            #expect(fallback.source == .cache)
            #expect(fallback.catalog.schemaVersion == MultilingualCatalog.supportedSchemaVersion)
        }

        try Data("{".utf8).write(to: cache.appendingPathComponent("multilingual-v2.json"))
        do {
            _ = try await repository.loadCatalog()
            Issue.record("When both caches are invalid, the original network error must be returned")
        } catch {
            #expect((error as? URLError)?.code == .notConnectedToInternet)
        }
    }

    @Test func productionCatalogV3LoadsV2ReleaseAndVerifiedPage() async throws {
        let fixture = try multilingualFixture()
        var releaseValue = try #require(JSONSerialization.jsonObject(with: fixture.release) as? [String: Any])
        releaseValue["schemaVersion"] = TargetLanguageReleasePackage.productionSchemaVersion
        releaseValue["spokenTargetLanguageCandidateJsonSha256"] = String(repeating: "a", count: 64)
        releaseValue["assets"] = [
            ["role": "page", "path": "/pages/page-1/ko/index.html",
             "sha256": SHA256.hash(data: fixture.page).map { String(format: "%02x", $0) }.joined()],
            ["role": "content", "path": "/content/page-1/ko.json", "sha256": String(repeating: "a", count: 64)],
            ["role": "captions", "path": "/captions/page-1/ko.json", "sha256": String(repeating: "b", count: 64)],
        ]
        let release = try JSONSerialization.data(withJSONObject: releaseValue, options: [.sortedKeys])
        let releaseHash = SHA256.hash(data: release).map { String(format: "%02x", $0) }.joined()
        var catalogValue = try #require(JSONSerialization.jsonObject(with: fixture.catalog) as? [String: Any])
        catalogValue["schemaVersion"] = MultilingualCatalog.productionSchemaVersion
        var pages = catalogValue["pages"] as! [[String: Any]]
        var pageValue = pages[0]
        pageValue["title"] = "正式页面"
        var targets = pageValue["targets"] as! [String: Any]
        var korean = targets["ko"] as! [String: Any]
        korean["releasePackageUrl"] = "/releases-v2/page-1/ko.json"
        korean["releasePackageJsonSha256"] = releaseHash
        targets["ko"] = korean
        pageValue["targets"] = targets
        pages[0] = pageValue
        catalogValue["pages"] = pages
        let catalog = try JSONSerialization.data(withJSONObject: catalogValue, options: [.sortedKeys])
        let production = URL(string: "https://ai-for-god-sermon-audio.web.app")!
        StubURLProtocol.install(host: production.host!) { request in
            switch request.url?.path {
            case "/multilingual-v3.json": return .init(chunks: [catalog])
            case "/releases-v2/page-1/ko.json": return .init(chunks: [release])
            case "/pages/page-1/ko/index.html": return .init(chunks: [fixture.page])
            default: return .init(status: 404, chunks: [Data("missing".utf8)])
            }
        }
        defer { StubURLProtocol.remove(host: production.host!) }
        let repository = MultilingualCatalogRepository(origin: production,
            cacheDirectory: directory.appendingPathComponent("production-v3"), session: session)
        let loaded = try await repository.loadCatalog()
        #expect(loaded.catalog.defaultPage.title == "正式页面")
        let package = try await repository.loadRelease(page: loaded.catalog.defaultPage, locale: "ko")
        #expect(package.schemaVersion == TargetLanguageReleasePackage.productionSchemaVersion)
        #expect(try await repository.loadPage(for: package).html.contains("한국어"))
    }

    @Test func reviewedLocaleAudioIsDownloadedByHashAndCachedBytesAreRechecked() async throws {
        let audio = Data("synthetic reviewed audio bytes".utf8)
        let fixture = try multilingualFixture(audio: audio)
        StubURLProtocol.install(host: baseURL.host!) { request in
            switch request.url?.path {
            case "/multilingual-v2.json": return .init(chunks: [fixture.catalog])
            case "/releases/page-1/ko.json": return .init(chunks: [fixture.release])
            case "/media/page-1/ko.wav": return .init(chunks: [audio])
            default: return .init(status: 404, chunks: [Data("missing".utf8)])
            }
        }
        let repository = MultilingualCatalogRepository(
            origin: baseURL, cacheDirectory: directory.appendingPathComponent("multilingual-audio"), session: session)
        let page = try await repository.loadCatalog().catalog.defaultPage
        let package = try await repository.loadRelease(page: page, locale: "ko")
        let verified = try await repository.loadAudio(for: package, page: page)
        #expect(verified.locale == "ko")
        #expect(verified.pageID == "page-1")
        #expect(try Data(contentsOf: verified.localURL) == audio)
        #expect(try verified.localURL.deletingLastPathComponent()
            .resourceValues(forKeys: [.isExcludedFromBackupKey]).isExcludedFromBackup == true)

        stub(.init(chunks: [], error: URLError(.notConnectedToInternet)))
        #expect(try await repository.loadAudio(for: package, page: page).localURL == verified.localURL)
        try Data("tampered".utf8).write(to: verified.localURL)
        do { _ = try await repository.loadAudio(for: package, page: page); Issue.record("Bad cache must not play offline") }
        catch { #expect(error is URLError) }
    }

    @Test func dualScriptCatalogTakesPriorityAndUsesStaticPageAndCanonicalAudio() async throws {
        let audio = Data("approved synthetic dual-script audio".utf8)
        let legacy = try multilingualFixture(audio: audio)
        var release = try #require(JSONSerialization.jsonObject(with: legacy.release) as? [String: Any])
        release["schemaVersion"] = TargetLanguageReleasePackage.dualScriptSchemaVersion
        release["spokenTargetLanguageCandidateJsonSha256"] = String(repeating: "b", count: 64)
        let page = Data("<html><head><style>body{color:black}</style></head><body>已批准完整韩语文稿</body></html>".utf8)
        let pageHash = SHA256.hash(data: page).map { String(format: "%02x", $0) }.joined()
        let audioHash = SHA256.hash(data: audio).map { String(format: "%02x", $0) }.joined()
        release["assets"] = [
            ["role": "page", "path": "/pages/page-1/ko/index.html", "sha256": pageHash],
            ["role": "content", "path": "/content/page-1/ko.json", "sha256": String(repeating: "a", count: 64)],
            ["role": "captions", "path": "/captions/page-1/ko.json", "sha256": String(repeating: "b", count: 64)],
            ["role": "audio", "path": "/media/page-1/ko.mp3", "sha256": audioHash],
        ]
        let releaseData = try JSONSerialization.data(withJSONObject: release, options: [.sortedKeys])
        let releaseHash = SHA256.hash(data: releaseData).map { String(format: "%02x", $0) }.joined()
        var catalog = try #require(JSONSerialization.jsonObject(with: legacy.catalog) as? [String: Any])
        catalog["schemaVersion"] = MultilingualCatalog.dualScriptSchemaVersion
        var pages = catalog["pages"] as! [[String: Any]], first = pages[0]
        first["title"] = "本周证道"
        var targets = first["targets"] as! [String: Any], korean = targets["ko"] as! [String: Any]
        korean["releasePackageUrl"] = "/releases-v2/page-1/ko.json"
        korean["releasePackageJsonSha256"] = releaseHash
        targets["ko"] = korean; first["targets"] = targets; pages[0] = first; catalog["pages"] = pages
        let catalogData = try JSONSerialization.data(withJSONObject: catalog, options: [.sortedKeys])
        StubURLProtocol.install(host: baseURL.host!) { request in
            switch request.url?.path {
            case "/multilingual-v3.json": return .init(chunks: [catalogData])
            case "/multilingual-v2.json": return .init(chunks: [legacy.catalog])
            case "/releases-v2/page-1/ko.json": return .init(chunks: [releaseData])
            case "/pages/page-1/ko/index.html": return .init(chunks: [page])
            case "/media/page-1/ko.mp3": return .init(chunks: [audio])
            default: return .init(status: 404, chunks: [Data("missing".utf8)])
            }
        }
        let repository = MultilingualCatalogRepository(origin: baseURL,
            cacheDirectory: directory.appendingPathComponent("dual-script"), session: session)
        let loaded = try await repository.loadCatalog()
        #expect(loaded.catalog.schemaVersion == MultilingualCatalog.dualScriptSchemaVersion)
        #expect(loaded.catalog.defaultPage.title == "本周证道")
        let selected = try await repository.loadRelease(page: loaded.catalog.defaultPage, locale: "ko")
        #expect(selected.spokenTargetLanguageCandidateJsonSha256 == String(repeating: "b", count: 64))
        #expect(try await repository.loadPage(for: selected).html.contains("已批准完整韩语文稿"))
        #expect(try await repository.loadAudio(for: selected, page: loaded.catalog.defaultPage).sha256 == audioHash)

        StubURLProtocol.install(host: baseURL.host!) { request in
            request.url?.path == "/multilingual-v2.json"
                ? .init(chunks: [legacy.catalog]) : .init(status: 404, chunks: [Data("missing".utf8)])
        }
        let fallback = try await repository.loadCatalog()
        #expect(fallback.catalog.schemaVersion == MultilingualCatalog.supportedSchemaVersion)
        #expect(fallback.source == .network)
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

    @Test func publishedTranscriptSeparatesSpokenTimesAndJoinsApprovedEnglish() async throws {
        let fixture = try publishedTranscriptFixture()
        installTranscriptFixture(fixture)
        let repository = MultilingualCatalogRepository(origin: baseURL, cacheDirectory: directory, session: session)
        let result = try await repository.loadPublishedTranscript(for: fixture.package, page: fixture.page)
        #expect(result.title == "한국어 전체 원고")
        #expect(result.fullText[0].text == "전체 원고")
        #expect(result.captions[0].text == "짧은 원고")
        #expect(result.fullText[0].start == 0)
        #expect(result.captions[0].start == 1)
        #expect(result.fullText[0].english == "Approved English.")
        #expect(result.captions[0].english == "Approved English.")
        stub(.init(chunks: [], error: URLError(.notConnectedToInternet)))
        let offline = try await repository.loadPublishedTranscript(for: fixture.package, page: fixture.page)
        #expect(offline.fullText[0].text == result.fullText[0].text)
        #expect(offline.captions[0].text == result.captions[0].text)
        #expect(offline.fullText[0].english == nil)
    }

    @Test func publishedTranscriptRejectsTamperedNetworkAndOfflineBytes() async throws {
        let fixture = try publishedTranscriptFixture()
        installTranscriptFixture(fixture, alteredContent: Data("{}".utf8))
        let repository = MultilingualCatalogRepository(origin: baseURL, cacheDirectory: directory, session: session)
        do { _ = try await repository.loadPublishedTranscript(for: fixture.package, page: fixture.page)
            Issue.record("Unverified text must not display")
        } catch { #expect(error as? ContentStorageError == .checksumMismatch) }
        installTranscriptFixture(fixture)
        _ = try await repository.loadPublishedTranscript(for: fixture.package, page: fixture.page)
        let hash = fixture.package.assets.first { $0.role == .captions }!.sha256
        try Data("{}".utf8).write(to: directory.appendingPathComponent("Transcripts/\(hash).json"))
        stub(.init(chunks: [], error: URLError(.notConnectedToInternet)))
        do { _ = try await repository.loadPublishedTranscript(for: fixture.package, page: fixture.page)
            Issue.record("Unverified cached captions must not display")
        } catch { #expect(error as? ContentStorageError == .checksumMismatch) }
    }

    @Test func optionalEnglishRejectsChangedSourceGroupAndReleaseWithoutHidingText() async throws {
        let fixture = try publishedTranscriptFixture()
        for mutation in ["group", "units", "release", "source", "content"] {
            var sidecar = try #require(JSONSerialization.jsonObject(with: fixture.english) as? [String: Any])
            var targets = sidecar["targets"] as! [String: [String: Any]]
            var target = targets["ko"]!
            var blocks = target["blocks"] as! [[String: Any]]
            switch mutation {
            case "group": blocks[0]["textGroupId"] = "wrong"
            case "units": blocks[0]["sourceUnitIds"] = ["source-wrong"]
            case "release": target["releasePackageJsonSha256"] = String(repeating: "e", count: 64)
            case "content": target["contentSha256"] = String(repeating: "e", count: 64)
            default: sidecar["sourceIdentitySha256"] = String(repeating: "e", count: 64)
            }
            target["blocks"] = blocks; targets["ko"] = target; sidecar["targets"] = targets
            let data = try JSONSerialization.data(withJSONObject: sidecar)
            installTranscriptFixture(fixture, alteredEnglish: data)
            let repository = MultilingualCatalogRepository(origin: baseURL, cacheDirectory: directory, session: session)
            let result = try await repository.loadPublishedTranscript(for: fixture.package, page: fixture.page)
            #expect(result.fullText[0].text == "전체 원고")
            #expect(result.fullText[0].english == nil)
            #expect(result.captions[0].english == nil)
        }
        installTranscriptFixture(fixture, alteredEnglish: Data("broken".utf8))
        let repository = MultilingualCatalogRepository(origin: baseURL, cacheDirectory: directory, session: session)
        #expect(try await repository.loadPublishedTranscript(for: fixture.package, page: fixture.page).fullText[0].english == nil)
    }

    @Test func spokenGroupMismatchCannotBecomeFullTextSubtitles() async throws {
        let fixture = try publishedTranscriptFixture()
        let mismatched = Data("{\"cues\":[{\"textGroupId\":\"wrong\",\"text\":\"spoken\",\"start\":1,\"end\":2}]}".utf8)
        do {
            _ = try VerifiedPublishedTranscript.decode(content: fixture.content, captions: mismatched,
                package: fixture.package, page: fixture.page)
            Issue.record("Wrong spoken group must fail even when the cue timings fit")
        } catch { #expect(error is CatalogError) }
    }

    private struct TranscriptFixture {
        let release: Data
        let package: TargetLanguageReleasePackage
        let page: MultilingualPage
        let content: Data
        let captions: Data
        let english: Data
    }

    private func installTranscriptFixture(_ fixture: TranscriptFixture, alteredContent: Data? = nil,
                                          alteredEnglish: Data? = nil) {
        StubURLProtocol.install(host: baseURL.host!) { request in
            switch request.url?.path {
            case "/releases-v2/page-1/ko.json": return .init(chunks: [fixture.release])
            case "/content/page-1/ko.json": return .init(chunks: [alteredContent ?? fixture.content])
            case "/captions/page-1/ko.json": return .init(chunks: [fixture.captions])
            case "/english-reference/page-1.json": return .init(chunks: [alteredEnglish ?? fixture.english])
            default: return .init(status: 404, chunks: [])
            }
        }
    }

    private func publishedTranscriptFixture() throws -> TranscriptFixture {
        let hashA = String(repeating: "a", count: 64)
        func json(_ value: [String: Any]) throws -> Data { try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]) }
        func hash(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }
        let content = try json([
            "schemaVersion": "sermon-full-video-text-content-v1", "pageId": "page-1", "sourceLocale": "en",
            "targetLocale": "ko", "status": "human_reviewed", "englishSourcePackageJsonSha256": hashA,
            "targetLanguageCandidateJsonSha256": hashA, "sourceMediaSha256": hashA,
            "durationSeconds": 10, "title": "한국어 전체 원고",
            "cues": [["textGroupId": "group-1", "sourceUnitIds": ["source-1"], "text": "전체 원고", "start": 0, "end": 2]],
        ])
        let captions = try json(["cues": [["textGroupId": "group-1", "text": "짧은 원고", "start": 1, "end": 3]]])
        let legacy = try multilingualFixture(audio: Data("audio".utf8))
        var releaseValue = try #require(JSONSerialization.jsonObject(with: legacy.release) as? [String: Any])
        releaseValue["schemaVersion"] = TargetLanguageReleasePackage.dualScriptSchemaVersion
        releaseValue["spokenTargetLanguageCandidateJsonSha256"] = hashA
        releaseValue["assets"] = [
            ["role": "page", "path": "/pages/page-1/ko/index.html", "sha256": hashA],
            ["role": "content", "path": "/content/page-1/ko.json", "sha256": hash(content)],
            ["role": "captions", "path": "/captions/page-1/ko.json", "sha256": hash(captions)],
            ["role": "audio", "path": "/media/page-1/ko.mp3", "sha256": hashA],
        ]
        let release = try json(releaseValue)
        let page = try JSONDecoder().decode(MultilingualPage.self, from: json([
            "id": "page-1", "title": "Sermon", "date": "2026-09-27", "sourceLocale": "en",
            "sourceIdentitySha256": hashA, "sourceMediaSha256": hashA, "defaultTargetLocale": "ko",
            "targets": ["ko": ["releasePackageUrl": "/releases-v2/page-1/ko.json", "releasePackageJsonSha256": hash(release),
                "contentStatus": "human_reviewed", "audioStatus": "human_reviewed", "capabilities": ["text", "captions", "audio"]]],
        ]))
        let english = try json([
            "schemaVersion": "sermon-published-english-reference-v1", "pageId": "page-1", "sourceIdentitySha256": hashA,
            "sourceMediaSha256": hashA, "reviewState": "human_approved", "targets": ["ko": [
                "releasePackageJsonSha256": hash(release), "contentSha256": hash(content), "captionsSha256": hash(captions),
                "blocks": [["textGroupId": "group-1", "sourceUnitIds": ["source-1"], "english": "Approved English."]],
            ]],
        ])
        return .init(release: release, package: try TargetLanguageReleasePackage.decode(release), page: page,
                     content: content, captions: captions, english: english)
    }

    private func track(id: String = "full", data: Data) -> SermonTrack {
        SermonTrack(id: id, label: "测试音轨", voiceLabel: "测试声音", audioUrl: "/media/test.mp3",
                    file: "test.mp3", sha256: SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined(),
                    durationSeconds: 10, cues: [SubtitleCue(start: 0, end: 5, text: "测试字幕")],
                    subtitleTiming: "candidate", scope: "full")
    }

    private func multilingualFixture(audio: Data? = nil) throws -> (catalog: Data, release: Data, page: Data) {
        let hashA = String(repeating: "a", count: 64)
        let page = Data("<html><head></head><body>한국어 검증 페이지</body></html>".utf8)
        let pageHash = SHA256.hash(data: page).map { String(format: "%02x", $0) }.joined()
        let audioHash = audio.map { SHA256.hash(data: $0).map { String(format: "%02x", $0) }.joined() }
        let releaseValue: [String: Any] = [
            "schemaVersion": "sermon-target-language-release-package-v1",
            "packageId": "page-1-ko", "pageId": "page-1", "sourceLocale": "en", "targetLocale": "ko",
            "targetLanguageCandidateJsonSha256": hashA, "targetLanguageAudioPackageJsonSha256": audio == nil ? NSNull() : hashA as Any,
            "status": "published_http_verified", "contentStatus": "human_reviewed",
            "audioStatus": audio == nil ? "unavailable" : "human_reviewed",
            "interfaceLocale": "ko", "contentLocale": "ko", "audioLocale": audio == nil ? NSNull() : "ko" as Any,
            "assets": [["role": "page", "path": "/pages/page-1/ko/index.html", "sha256": pageHash]]
                + (audioHash.map { [["role": "audio", "path": "/media/page-1/ko.wav", "sha256": $0]] } ?? []),
            "httpVerification": ["status": "pass", "evidenceSha256": hashA],
            "deviceAcceptance": ["status": "not_run", "evidenceSha256": NSNull()],
            "venueAcceptance": ["status": "not_run", "evidenceSha256": NSNull()], "issues": [],
        ]
        let release = try JSONSerialization.data(withJSONObject: releaseValue, options: [.sortedKeys])
        let releaseHash = SHA256.hash(data: release).map { String(format: "%02x", $0) }.joined()
        let catalogValue: [String: Any] = [
            "schemaVersion": "sermon-multilingual-catalog-v2", "generatedAt": "2026-09-21T00:00:00Z",
            "defaultPageId": "page-1", "pages": [[
                "id": "page-1", "date": "2026-09-21", "sourceLocale": "en", "sourceIdentitySha256": hashA,
                "defaultTargetLocale": "ko", "targets": ["ko": [
                    "releasePackageUrl": "/releases/page-1/ko.json", "releasePackageJsonSha256": releaseHash,
                    "contentStatus": "human_reviewed", "audioStatus": audio == nil ? "unavailable" : "human_reviewed",
                    "capabilities": audio == nil ? ["text"] : ["text", "audio"],
                ]],
            ]],
        ]
        return (try JSONSerialization.data(withJSONObject: catalogValue, options: [.sortedKeys]), release, page)
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
