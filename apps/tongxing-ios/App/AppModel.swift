import Combine
import Foundation
import TongxingCore
import TongxingInfrastructure

@MainActor
final class AppModel: ObservableObject {
    static let contentOrigin = URL(string: "https://ai-for-god-sermon-audio.web.app")!

    let playback: PlaybackController
    @Published private(set) var catalog: WeeklyCatalog?
    @Published private(set) var selectedWeek: SermonWeek?
    @Published private(set) var selectedTrack: SermonTrack?
    @Published private(set) var isLoading = false
    @Published private(set) var isPreparing = false
    @Published private(set) var errorMessage: String?
    @Published private(set) var catalogNotice: String?
    @Published private(set) var downloadStates: [String: DownloadState] = [:]
    @Published private(set) var usingOfflineAudio = false
    @Published var display: ListeningDisplay = .current

    enum ListeningDisplay: String, CaseIterable { case current = "现场收听", transcript = "字幕全文" }
    enum DownloadState: Equatable {
        case absent, checking, downloading, ready, failed(String)
    }

    private var repository: CatalogRepository?
    private var offlineLibrary: OfflineLibrary?
    private let mediaOrigin: URL
    private var started = false
    private var preparation = UUID()
    private var downloadTasks: [String: Task<Void, Never>] = [:]

    init(supportDirectory: URL? = nil, contentOrigin: URL? = nil, session: URLSession = .shared) {
        let support = supportDirectory ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
            .appendingPathComponent("Tongxing", isDirectory: true)
        mediaOrigin = contentOrigin ?? Self.contentOrigin
        playback = PlaybackController(historyURL: support.appendingPathComponent("playback-history-v1.json"))
        repository = CatalogRepository(
                catalogURL: mediaOrigin.appendingPathComponent("weekly.json"),
                cacheDirectory: support.appendingPathComponent("Catalog", isDirectory: true),
                session: session
            )
        offlineLibrary = OfflineLibrary(
                directory: support.appendingPathComponent("Audio", isDirectory: true),
                baseURL: mediaOrigin,
                session: session
            )
    }

    var weeks: [SermonWeek] { catalog?.weeks ?? [] }
    var selectionKey: String? {
        guard let week = selectedWeek, let track = selectedTrack else { return nil }
        return track.identity(weekID: week.id).key
    }
    var currentDownload: DownloadState { selectionKey.flatMap { downloadStates[$0] } ?? .absent }

    func start() async {
        guard !started else { return }
        started = true
        await refresh()
    }

    func refresh() async {
        guard !isLoading, let repository else { return }
        isLoading = true
        defer { isLoading = false }
        do {
            let result = try await repository.load()
            catalog = result.catalog
            catalogNotice = result.warning
            if result.source == .cache {
                catalogNotice = "当前使用上次保存的证道目录。\(result.warning ?? "连接网络后可刷新。")"
            }
            errorMessage = nil
            let next = result.catalog.weeks.first { $0.id == selectedWeek?.id } ?? result.catalog.defaultWeek
            let track = next.tracks.first { $0.id == selectedTrack?.id } ?? next.tracks.first
            await select(week: next, track: track)
        } catch {
            errorMessage = "暂时无法读取证道目录。请连接网络后重试。"
        }
    }

    func select(week: SermonWeek, track: SermonTrack? = nil, force: Bool = false) async {
        let nextTrack = track ?? week.tracks.first
        let unchanged = selectedWeek?.id == week.id && selectedTrack?.id == nextTrack?.id
            && selectedTrack?.sha256 == nextTrack?.sha256
            && selectedWeek?.sourceId == week.sourceId && selectedWeek?.sourceUrl == week.sourceUrl
        if unchanged && !force {
            selectedWeek = week
            selectedTrack = nextTrack
            if let nextTrack { playback.updateMetadata(week: week, track: nextTrack) }
            return
        }
        playback.clear()
        preparation = UUID()
        let token = preparation
        isPreparing = true
        defer { if preparation == token { isPreparing = false } }
        selectedWeek = week
        selectedTrack = nextTrack
        usingOfflineAudio = false
        display = .current
        guard let track = nextTrack else { return }
        let key = track.identity(weekID: week.id).key
        var local: URL?
        do {
            local = try await offlineLibrary?.offlineFile(for: track)
            guard preparation == token else { return }
            downloadStates[key] = local == nil ? (downloadTasks[key] == nil ? .absent : .downloading) : .ready
        } catch {
            guard preparation == token else { return }
            downloadStates[key] = .failed("离线文件需要重新下载。")
        }
        guard preparation == token else { return }
        do {
            let url = try local ?? track.mediaURL(relativeTo: mediaOrigin)
            usingOfflineAudio = local != nil
            playback.load(week: week, track: track, url: url)
        } catch { errorMessage = "这条音频的地址无效，未开始播放。" }
    }

    func retryAudio() async {
        guard let week = selectedWeek else { return }
        await select(week: week, track: selectedTrack, force: true)
    }

    func downloadSelected() {
        guard let week = selectedWeek, let track = selectedTrack, let library = offlineLibrary else { return }
        let key = track.identity(weekID: week.id).key
        guard downloadTasks[key] == nil else { return }
        downloadStates[key] = .downloading
        downloadTasks[key] = Task { [weak self] in
            do {
                _ = try await library.download(track: track)
                try Task.checkCancellation()
                guard let self else { return }
                self.downloadStates[key] = .ready
                self.downloadTasks[key] = nil
                // Switch automatically only before listening starts. A completed
                // download must never reset or interrupt an active audio source.
                if self.selectionKey == key && !self.playback.hasUserInteraction
                    && self.playback.resumePosition == nil, let currentWeek = self.selectedWeek,
                    let currentTrack = self.selectedTrack {
                    await self.select(week: currentWeek, track: currentTrack, force: true)
                }
            } catch is CancellationError {
                self?.downloadStates[key] = .absent
                self?.downloadTasks[key] = nil
            } catch {
                self?.downloadStates[key] = .failed(error.localizedDescription)
                self?.downloadTasks[key] = nil
            }
        }
    }

    func cancelDownload() {
        guard let key = selectionKey else { return }
        downloadTasks[key]?.cancel()
    }

    var currentCue: SubtitleCue? { selectedTrack?.cue(at: playback.position) }
}
