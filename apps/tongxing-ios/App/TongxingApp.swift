import SwiftUI

@main
struct TongxingApp: App {
    @Environment(\.scenePhase) private var scenePhase
    // App-scoped on purpose: Tongxing owns a single audio session, so every
    // window (including Duo inner-display multi-window) mirrors the same
    // playback state. Do not move this into the WindowGroup content —
    // per-window models would create competing PlaybackControllers over one
    // audio session.
    @StateObject private var model: AppModel = {
        #if DEBUG
        if let fixtureModel = UITestLaunch.makeModel() { return fixtureModel }
        #endif
        return AppModel()
    }()

    var body: some Scene {
        WindowGroup {
            ContentView(model: model)
                .tint(Brand.accent)
                .onChange(of: scenePhase) { _, phase in
                    if phase == .background { model.suspendAlignment() }
                    model.playback.setStatisticsForeground(phase == .active)
                }
                #if DEBUG
                .modifier(UITestTextSize())
                #endif
                .task {
                    #if DEBUG
                    // Hosted tests provide their own local media and history.
                    // Keep the app host from also fetching the live catalog.
                    guard ProcessInfo.processInfo.environment["TONGXING_TEST_HOST"] != "1"
                        || UITestLaunch.isEnabled else { return }
                    #endif
                    await model.start()
                }
                #if os(macOS)
                .modifier(DevelopmentPreviewAppearance())
                #endif
        }
        #if os(macOS)
        .defaultSize(width: developmentWindowWidth, height: developmentWindowHeight)
        .windowStyle(.hiddenTitleBar)
        #endif
    }

    #if os(macOS)
    private var developmentWindowWidth: CGFloat {
        CGFloat((Bundle.main.object(forInfoDictionaryKey: "TongxingPreviewWidth") as? NSNumber)?.doubleValue ?? 390)
    }
    private var developmentWindowHeight: CGFloat {
        CGFloat((Bundle.main.object(forInfoDictionaryKey: "TongxingPreviewHeight") as? NSNumber)?.doubleValue ?? 844)
    }
    #endif
}

#if os(macOS)
// Preview-only launch options let us inspect appearance without changing the
// user's macOS settings. They aren't part of the iPhone interface.
private struct DevelopmentPreviewAppearance: ViewModifier {
    @Environment(\.dynamicTypeSize) private var inheritedSize
    @Environment(\.verticalSizeClass) private var inheritedVerticalSizeClass
    private let arguments = ProcessInfo.processInfo.arguments
        + (Bundle.main.object(forInfoDictionaryKey: "TongxingPreviewOptions") as? [String] ?? [])

    func body(content: Content) -> some View {
        content
            .preferredColorScheme(arguments.contains("--dark") ? .dark : arguments.contains("--light") ? .light : nil)
            .dynamicTypeSize(arguments.contains("--large-type") ? .accessibility3 : inheritedSize)
            .environment(\.verticalSizeClass, arguments.contains("--compact-height") ? .compact : inheritedVerticalSizeClass)
    }
}
#endif
