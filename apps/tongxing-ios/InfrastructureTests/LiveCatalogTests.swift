import Foundation
import Testing
import TongxingCore
@testable import TongxingInfrastructure

/// Explicit public-network smoke; synthetic transport tests remain deterministic.
/// This verifies storage, not decoding/playback on an iPhone or venue readiness.
@Test(.enabled(if: ProcessInfo.processInfo.environment["TONGXING_LIVE_SMOKE"] == "1"),
      .timeLimit(.minutes(2)))
func publishedCatalogAndAudioSurviveOfflineReload() async throws {
    let base = URL(string: "https://ai-for-god-sermon-audio.web.app")!
    let root = FileManager.default.temporaryDirectory.appendingPathComponent("tongxing-live-\(UUID().uuidString)")
    defer { try? FileManager.default.removeItem(at: root) }
    let cache = root.appendingPathComponent("catalog")
    let audio = root.appendingPathComponent("offline")
    let repository = CatalogRepository(catalogURL: base.appendingPathComponent("weekly.json"), cacheDirectory: cache)
    let result = try await repository.load()
    #expect(result.source == .network)
    let track = try #require(result.catalog.weeks.flatMap(\.tracks).min { $0.durationSeconds < $1.durationSeconds })
    let library = OfflineLibrary(directory: audio, baseURL: base)
    let downloaded = try await library.download(track: track)
    let byteCount = try downloaded.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
    #expect(byteCount > 0)

    let configuration = URLSessionConfiguration.ephemeral
    configuration.protocolClasses = [UnavailableNetworkProtocol.self]
    let offlineSession = URLSession(configuration: configuration)
    defer { offlineSession.invalidateAndCancel() }
    let restartedRepository = CatalogRepository(catalogURL: base.appendingPathComponent("weekly.json"),
        cacheDirectory: cache, session: offlineSession)
    let restoredCatalog = try await restartedRepository.load()
    #expect(restoredCatalog.source == .cache)
    #expect(restoredCatalog.catalog == result.catalog)
    let restartedLibrary = OfflineLibrary(directory: audio, baseURL: base, session: offlineSession)
    let restoredAudio = try await restartedLibrary.offlineFile(for: track)
    #expect(restoredAudio == downloaded)
    print("Live storage smoke: \(track.audioUrl), \(byteCount) bytes, SHA-256 \(track.sha256); catalog network -> cache, audio verified after repository restart.")
    try await restartedLibrary.removeDownload(for: track)
    #expect(try await restartedLibrary.offlineFile(for: track) == nil)
}

private final class UnavailableNetworkProtocol: URLProtocol {
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() { client?.urlProtocol(self, didFailWithError: URLError(.notConnectedToInternet)) }
    override func stopLoading() {}
}
