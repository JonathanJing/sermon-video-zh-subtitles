import CryptoKit
import Foundation
import Testing
import TongxingCore
@testable import TongxingInfrastructure

@Suite(.serialized)
struct ReviewedStudyResourcesTests {
    private let a = String(repeating: "a", count: 64)
    private func bytes(_ value: Any) throws -> Data {
        try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys, .withoutEscapingSlashes])
    }
    private func hash(_ value: Any) throws -> String {
        SHA256.hash(data: try bytes(value)).map { String(format: "%02x", $0) }.joined()
    }
    private func fixture() throws -> (TargetLanguageReleasePackage, Data, Data, Data) {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
        let raw = try JSONSerialization.jsonObject(with: Data(contentsOf: root.appendingPathComponent("Core/Tests/TongxingCoreTests/Fixtures/dev-candidate-catalog-readback.json"))) as! [String: Any]
        var release = (raw["releases"] as! [String: [String: Any]])["zh-Hans"]!
        let page = release["pageId"] as! String
        let text = release["targetLanguageCandidateJsonSha256"] as! String
        let audio = release["targetLanguageAudioPackageJsonSha256"] as! String
        func study(_ kind: String) -> [String: Any] {
            ["schemaVersion": "sermon-study-artifact-v1", "kind": kind, "pageId": page, "locale": "zh-Hans",
             "sourcePackageSha256": a, "textCandidateSha256": text, "producerIdentity": "offline-fixture",
             "sections": [["title": "标题 & <测试>", "body": "完整正文，不能只显示标题。", "sourceUnitIds": ["unit-1"]]]]
        }
        let outline = study("outline"), meditation = study("meditation")
        let identity: [String: Any] = ["sourceId": "offline-source", "sourceUrlHash": a, "mediaSha256": a,
            "durationSeconds": 30, "window": ["startSeconds": 0, "endSeconds": 30, "approvalReceiptSha256": a]]
        let contentSHA = (release["assets"] as! [[String: Any]]).first { $0["role"] as? String == "content" }!["sha256"] as! String
        let joined: [String: Any] = ["source": a, "products": ["text": text, "audio": audio,
            "outline": ["status": "human_reviewed", "artifactSha256": try hash(outline), "reviewSha256": a],
            "meditation": ["status": "human_reviewed", "artifactSha256": try hash(meditation), "reviewSha256": a]]]
        let products: [String: Any] = ["sourcePackageSha256": a, "textCandidateSha256": text,
            "audioPackageSha256": audio, "outlineArtifactSha256": try hash(outline), "meditationArtifactSha256": try hash(meditation),
            "outlineReviewSha256": a, "meditationReviewSha256": a, "metadataApprovalSha256": a,
            "contentSha256": contentSHA, "candidateSha256": try hash(["products": try hash(joined), "metadataApproval": a, "contentSha256": contentSHA])]
        let manifest: [String: Any] = ["schemaVersion": "sermon-public-app-products-v1", "pageId": page,
            "locale": "zh-Hans", "sourceIdentity": identity, "fourProducts": products]
        release["schemaVersion"] = TargetLanguageReleasePackage.fourProductSchemaVersion
        release["contentStatus"] = "human_reviewed"; release["interfaceLocale"] = "zh-Hans"
        release["englishSourcePackageJsonSha256"] = a; release["sourceIdentity"] = identity; release["fourProducts"] = products
        var assets = release["assets"] as! [[String: Any]]
        for (role, name, value) in [("outline", "outline", outline), ("meditation", "meditation", meditation), ("product_manifest", "products", manifest)] {
            assets.append(["role": role, "path": "/study/\(page)/zh-Hans/\(name).json", "sha256": try hash(value)])
        }
        release["assets"] = assets
        return (try TargetLanguageReleasePackage.decode(bytes(release), allowDevCandidate: true), try bytes(outline), try bytes(meditation), try bytes(manifest))
    }

    @Test func validatedStudyRequiresCompleteDisplayedBodyAndEscapesHTML() throws {
        let (package, outlineData, meditationData, manifest) = try fixture()
        try ReviewedStudyResources.validateManifest(manifest, package: package)
        let outline = try ReviewedStudyArtifact.decode(outlineData, kind: "outline", package: package)
        _ = try ReviewedStudyArtifact.decode(meditationData, kind: "meditation", package: package)
        #expect(outline.htmlItems.contains("标题 &amp; &lt;测试&gt;"))
        #expect(!outline.isDisplayed(in: "<section id=\"study-outline\">标题 &amp; &lt;测试&gt;</section>"))
        #expect(outline.isDisplayed(in: "<section id=\"study-outline\">\(outline.htmlItems)</section>"))
    }

    @Test func tamperedTextLocaleKindAndCandidateCannotBeAdmitted() throws {
        let (package, outline, _, manifest) = try fixture()
        for (field, value) in [("locale", "ko"), ("kind", "meditation"), ("sourcePackageSha256", String(repeating: "b", count: 64)), ("textCandidateSha256", String(repeating: "b", count: 64))] {
            var artifact = try JSONSerialization.jsonObject(with: outline) as! [String: Any]
            artifact[field] = value
            #expect(throws: (any Error).self) { try ReviewedStudyArtifact.decode(bytes(artifact), kind: "outline", package: package) }
        }
        var modified = try JSONSerialization.jsonObject(with: manifest) as! [String: Any]
        var products = modified["fourProducts"] as! [String: Any]
        products["candidateSha256"] = a; modified["fourProducts"] = products
        #expect(throws: (any Error).self) { try ReviewedStudyResources.validateManifest(bytes(modified), package: package) }
    }
    @Test(.enabled(if: ProcessInfo.processInfo.environment["TONGXING_FOUR_PRODUCT_FIXTURE"] != nil))
    func realPythonBuilderOutputLoadsAndOfflineTamperIsRejected() async throws {
        let root = URL(fileURLWithPath: try #require(ProcessInfo.processInfo.environment["TONGXING_FOUR_PRODUCT_FIXTURE"]))
        var files: [String: Data] = [:]
        let enumerator = try #require(FileManager.default.enumerator(at: root, includingPropertiesForKeys: nil))
        for case let url as URL in enumerator where ["json", "html"].contains(url.pathExtension) {
            files[String(url.path.dropFirst(root.path.count))] = try Data(contentsOf: url)
        }
        FourProductFixtureProtocol.files = files
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [FourProductFixtureProtocol.self]
        let session = URLSession(configuration: configuration)
        defer { session.invalidateAndCancel(); FourProductFixtureProtocol.files = [:] }
        let cache = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: cache) }
        let repository = MultilingualCatalogRepository(origin: URL(string: "https://ai-for-god-sermon-audio-dev.web.app")!,
            cacheDirectory: cache, session: session, allowDevCandidate: true)
        let catalog = try await repository.loadCatalog().catalog
        let page = catalog.defaultPage
        let package = try await repository.loadRelease(page: page, locale: "ko")
        let transcript = try await repository.loadPublishedTranscript(for: package, page: page)
        #expect(!transcript.fullText.isEmpty)
        let studies = try #require(await repository.loadStudies(for: package))
        #expect(!studies.meditation.sections.isEmpty)
        let online = try await repository.loadPage(for: package)
        #expect(online.html.contains("id=\"study-meditation\""))
        #expect(online.html.contains("Second complete sentence &amp; last words."))
        FourProductFixtureProtocol.files = [:]
        let offline = try await repository.loadPage(for: package)
        #expect(offline.html == online.html)
        let studyAsset = try #require(package.assets.first { $0.role == .meditation })
        try Data("{}".utf8).write(to: cache.appendingPathComponent("Study/\(studyAsset.sha256).json"))
        await #expect(throws: (any Error).self) { try await repository.loadPage(for: package) }
    }

}

private final class FourProductFixtureProtocol: URLProtocol {
    private static let lock = NSLock()
    private static var stored: [String: Data] = [:]
    static var files: [String: Data] {
        get { lock.lock(); defer { lock.unlock() }; return stored }
        set { lock.lock(); defer { lock.unlock() }; stored = newValue }
    }
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        guard let url = request.url else { client?.urlProtocol(self, didFailWithError: URLError(.badURL)); return }
        let bytes = Self.files[url.path]
        let response = HTTPURLResponse(url: url, statusCode: bytes == nil ? 404 : 200, httpVersion: "HTTP/1.1", headerFields: nil)!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        if let bytes { client?.urlProtocol(self, didLoad: bytes) }
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}
