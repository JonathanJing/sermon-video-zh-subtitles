#if DEBUG
import Foundation
import SwiftUI
import TongxingCore
import TongxingInfrastructure

/// Each preview gets private URLSession transport and temporary state.
@MainActor
final class CanvasFixture: ObservableObject {
    enum Scenario: Equatable { case ready, published, loading, unavailable }
    let model: AppModel
    private let scenario: Scenario
    private let support: URL
    private let session: URLSession
    private var started = false
    @Published private(set) var error: String?

    init(_ scenario: Scenario = .ready) {
        self.scenario = scenario
        let id = UUID().uuidString
        support = FileManager.default.temporaryDirectory
            .appendingPathComponent("Tongxing-Canvas-\(id)", isDirectory: true)
        let configuration = URLSessionConfiguration.ephemeral
        switch scenario {
        case .ready: configuration.protocolClasses = [CanvasContentProtocol.self]
        case .published: configuration.protocolClasses = [CanvasPublishedProtocol.self]
        case .loading: configuration.protocolClasses = [CanvasLoadingProtocol.self]
        case .unavailable: configuration.protocolClasses = [CanvasUnavailableProtocol.self]
        }
        configuration.urlCache = nil
        session = URLSession(configuration: configuration)
        let defaults = UserDefaults(suiteName: "Tongxing-Canvas-\(id)")!
        model = AppModel(supportDirectory: support, contentOrigin: UITestContent.origin,
                         session: session, statisticsDefaults: defaults)
    }

    func start() async {
        guard !started else { return }
        started = true
        do {
            if scenario == .ready || scenario == .published {
                let catalog = try WeeklyCatalog.decode(UITestContent.responses["/weekly.json"]!)
                let library = OfflineLibrary(directory: support.appendingPathComponent("Audio"),
                                             baseURL: UITestContent.origin, session: session)
                for week in catalog.weeks {
                    for track in week.tracks { _ = try await library.download(track: track) }
                }
            }
            await model.start()
        } catch {
            self.error = String(describing: error)
        }
    }

    deinit {
        session.invalidateAndCancel()
        try? FileManager.default.removeItem(at: support)
    }
}

private class CanvasContentProtocol: UITestContentProtocol {
    override var isOffline: Bool { false }
    override var usesDualScript: Bool { false }
}
private final class CanvasPublishedProtocol: CanvasContentProtocol {
    override var usesDualScript: Bool { true }
}
private final class CanvasUnavailableProtocol: CanvasContentProtocol {
    override var isOffline: Bool { true }
}
private final class CanvasLoadingProtocol: CanvasContentProtocol {
    override func startLoading() {}
}

@MainActor
struct ComponentPreview: View {
    enum Surface { case page, dock, more }
    @StateObject private var fixture: CanvasFixture
    private let surface: Surface
    private let placement: PlaybackDockPlacement
    private let preparing: Bool
    private let capture: Bool

    init(_ scenario: CanvasFixture.Scenario = .ready, surface: Surface = .page,
         placement: PlaybackDockPlacement = .bottom, preparing: Bool = false,
         capture: Bool = false) {
        _fixture = StateObject(wrappedValue: CanvasFixture(scenario))
        self.surface = surface
        self.placement = placement
        self.preparing = preparing
        self.capture = capture
    }

    @ViewBuilder var body: some View {
        if capture {
            previewContent.designProbe(
                scene: "listening", requestedDevice: "iPhone 18 Pro",
                fingerprint: PreviewSourceFingerprint_73bbf1f9150d088c3b359b696673d973598ee215727fb105af891a913f82948e.value
            )
        } else {
            previewContent
        }
    }

    private var previewContent: some View {
        Group {
            switch surface {
            case .page:
                ContentView(model: fixture.model)
            case .dock:
                PlaybackDock(playback: fixture.model.playback, isPreparing: preparing,
                             alignmentModel: fixture.model, precision: {}, current: {}, placement: placement)
            case .more:
                PlaybackMoreControls(playback: fixture.model.playback, isPreparing: preparing,
                                     alignmentModel: fixture.model, precision: {}, current: {}, onClose: {})
            }
        }
        .tint(Brand.accent)
        .background(Brand.background)
        .overlay(alignment: .top) {
            if let error = fixture.error { Text(verbatim: error).foregroundStyle(.red) }
        }
        .task { await fixture.start() }
    }
}

#Preview("01 · Listening / light") {
    ComponentPreview().preferredColorScheme(.light)
}
#Preview("02 · Listening / dark") {
    ComponentPreview().preferredColorScheme(.dark)
}
#Preview("03 · Largest text") {
    ComponentPreview().dynamicTypeSize(.accessibility5)
}
#Preview("04 · Published reader / Korean") {
    ComponentPreview(.published)
}
#Preview("05 · Loading") {
    ComponentPreview(.loading)
}
#Preview("06 · No connection") {
    ComponentPreview(.unavailable)
}
#Preview("07 · Dock / ready", traits: .sizeThatFitsLayout) {
    ComponentPreview(surface: .dock)
}
#Preview("08 · Dock / preparing", traits: .sizeThatFitsLayout) {
    ComponentPreview(surface: .dock, preparing: true)
}
#Preview("09 · Dock / trailing", traits: .sizeThatFitsLayout) {
    ComponentPreview(surface: .dock, placement: .trailing)
}
#Preview("10 · More / largest text", traits: .sizeThatFitsLayout) {
    ComponentPreview(surface: .more).dynamicTypeSize(.accessibility5)
}

/// This deprecated-provider capture is intentionally separate from daily #Preview
/// variants so its simulator target is explicit and its build identity is inspectable.
@available(*, deprecated, message: "Device-specific screenshot capture; keep #Preview for normal iteration")
struct IPhone18ProListeningCapturePreview: PreviewProvider {
    static var previews: some View {
        ComponentPreview(capture: true)
            .previewDevice(PreviewDevice(rawValue: "iPhone 18 Pro"))
            .previewDisplayName("Capture · iPhone 18 Pro · Listening")
    }
}
#endif
