import SwiftUI
import UIKit
import XCTest
@testable import Tongxing

#if DEBUG
/// Opt-in hosted view rendering, independent of Xcode Canvas/MCP caches.
/// Attachments are exported by scripts/preview.py; default test runs skip this.
@MainActor
final class SwiftUIPreviewTests: XCTestCase {
    private struct Request: Decodable {
        let files: [String]
        let variants: [String]
        let interfaceLocale: String
        let voiceDemoCatalogPath: String?
    }

    func testRenderRequestedViews() async throws {
        guard let encoded = ProcessInfo.processInfo.environment["TONGXING_PREVIEW_REQUEST"],
              !encoded.isEmpty, !encoded.hasPrefix("$(") else {
            throw XCTSkip("Opt-in view rendering: use make preview FILES=App/ContentView.swift")
        }
        let data = try XCTUnwrap(Data(base64Encoded: encoded), "Invalid preview request encoding")
        let request = try JSONDecoder().decode(Request.self, from: data)
        let supportedFiles = Set(["ContentView.swift", "PlaybackDock.swift", "DesignSystem.swift", "EnglishLocateSheet.swift", "VoiceDemoSection.swift"])
        let supportedVariants = Set(["light", "dark", "dark-large"])
        try XCTUnwrap(request.files.first, "Select at least one registered view fixture")
        try XCTUnwrap(request.variants.first, "Select at least one appearance variant")
        XCTAssertTrue(Set(request.files).isSubset(of: supportedFiles), "Unregistered view fixture")
        XCTAssertTrue(Set(request.variants).isSubset(of: supportedVariants), "Unknown appearance variant")
        guard Set(request.files).isSubset(of: supportedFiles),
              Set(request.variants).isSubset(of: supportedVariants) else { return }
        let language = try XCTUnwrap(request.interfaceLocale == "zh-Hans" ? .simplifiedChinese
            : request.interfaceLocale == "en" ? AppLanguage.english : nil, "Unknown interface locale")
        let localization = AppLocalization.shared
        let originalLanguage = localization.preference
        localization.setPreference(language)
        defer { localization.setPreference(originalLanguage) }

        let run = UUID().uuidString
        let support = FileManager.default.temporaryDirectory.appendingPathComponent("Tongxing-Preview-\(run)")
        let suite = "Tongxing-Preview-\(run)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        let model = UITestLaunch.makeFixtureModel(supportDirectory: support,
            statisticsDefaults: defaults, nativePublishedPage: true)
        defer {
            model.playback.pause()
            model.mediaSession.invalidateAndCancel()
            defaults.removePersistentDomain(forName: suite)
            try? FileManager.default.removeItem(at: support)
        }
        await model.start()
        try await waitForReady(model)
        await model.loadSelectedPublishedTranscript()
        XCTAssertEqual(model.selectedPageID, "ui-test-full-video")
        XCTAssertEqual(model.selectedContentLocale, "zh-Hans")
        XCTAssertNotNil(model.publishedTranscript, "Preview must show loaded captions, not a spinner")
        guard model.publishedTranscript != nil else { return }

        let voiceDemoCatalog = try request.voiceDemoCatalogPath.map {
            try VoiceDemoCatalog.validatedClips(Data(contentsOf: URL(fileURLWithPath: $0)))
        }
        for file in request.files {
            for variant in request.variants {
                let image = try await render(view: fixture(file, model: model, voiceDemoCatalog: voiceDemoCatalog), variant: variant)
                let attachment = XCTAttachment(image: image)
                attachment.name = "preview-\(file.dropLast(6))-\(variant).png"
                attachment.lifetime = .keepAlways
                add(attachment)
            }
        }
    }

    // A SwiftUI source file can contain multiple views or require dependencies.
    // Register a factory here instead of guessing how to initialize arbitrary code.
    private func fixture(_ file: String, model: AppModel, voiceDemoCatalog: VoiceDemoCatalog? = nil) -> AnyView {
        switch file {
        case "ContentView.swift":
            return AnyView(ContentView(model: model))
        case "VoiceDemoSection.swift":
            return AnyView(NavigationStack {
                Form { Section { VoiceDemoSection(model: model, fixture: voiceDemoCatalog ?? (try? UITestLaunch.voiceDemoFixture())) } }
                    .navigationTitle("多语种音色试听")
            })
        case "EnglishLocateSheet.swift":
            return AnyView(EnglishLocateSheet(model: model, onLocated: {}))
        case "PlaybackDock.swift":
            return AnyView(ZStack {
                Brand.background.ignoresSafeArea()
                VStack(spacing: 20) {
                    Text("PlaybackDock").font(.title2)
                    Text("合成静音音轨 · 暂停就绪").foregroundStyle(.secondary)
                    PlaybackDock(playback: model.playback, alignmentModel: model)
                    PlaybackMoreControls(playback: model.playback, isPreparing: false,
                        alignmentModel: model, locate: {}, precision: {}, current: {}, onClose: {})
                }
            })
        default:
            return AnyView(ZStack {
                Brand.background.ignoresSafeArea()
                VStack(alignment: .leading, spacing: 24) {
                    Text("Tongxing · DesignSystem").font(.title2.bold())
                    Text("语义背景、内容表面与品牌强调色").foregroundStyle(.secondary)
                    Text("内容表面 · Content surface")
                        .padding(20).frame(maxWidth: .infinity, alignment: .leading)
                        .background(Brand.surface, in: RoundedRectangle(cornerRadius: 24))
                    HStack {
                        Image(systemName: "play.fill")
                        Text("主要操作 · Primary action")
                    }
                    .foregroundStyle(Brand.accent)
                    .padding(20).frame(maxWidth: .infinity)
                    .listeningGlassSurface()
                }.padding(24)
            })
        }
    }

    private func waitForReady(_ model: AppModel) async throws {
        let deadline = Date().addingTimeInterval(10)
        while !model.playback.isReady || model.isPreparingPublishedAudio {
            guard Date() < deadline else {
                XCTFail("Synthetic published audio did not become ready: \(model.publishedAudioError ?? model.playback.message)")
                throw PreviewError.audioNotReady
            }
            try await Task.sleep(for: .milliseconds(30))
        }
    }

    private enum PreviewError: Error { case audioNotReady, drawFailed }

    private func render(view: AnyView, variant: String) async throws -> UIImage {
        let scene = try XCTUnwrap(UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
            .first { $0.activationState == .foregroundActive }, "Hosted test needs an active iOS window scene")
        let previousWindow = scene.windows.first { $0.isKeyWindow }
        let dark = variant != "light"
        let large = variant == "dark-large"
        let host = UIHostingController(rootView: view
            .tint(Brand.accent)
            .environment(\.locale, AppLocalization.shared.locale)
            .environment(\.dynamicTypeSize, large ? .accessibility3 : .large)
            .transaction { $0.disablesAnimations = true }
            .preferredColorScheme(dark ? .dark : .light))
        host.traitOverrides.preferredContentSizeCategory = large
            ? UIContentSizeCategory.accessibilityExtraLarge : UIContentSizeCategory.large
        let window = UIWindow(windowScene: scene)
        window.frame = scene.coordinateSpace.bounds
        window.overrideUserInterfaceStyle = dark ? .dark : .light
        window.rootViewController = host
        window.makeKeyAndVisible()
        defer {
            window.isHidden = true
            window.rootViewController = nil
            previousWindow?.makeKey()
        }
        window.layoutIfNeeded()
        // Let SwiftUI tasks/layout and system material settle on the MainActor.
        try await Task.sleep(for: .milliseconds(350))
        window.layoutIfNeeded()
        let format = UIGraphicsImageRendererFormat()
        format.scale = scene.screen.scale
        format.opaque = true
        var complete = false
        let image = UIGraphicsImageRenderer(bounds: window.bounds, format: format).image { _ in
            complete = window.drawHierarchy(in: window.bounds, afterScreenUpdates: true)
        }
        guard complete else {
            XCTFail("UIKit could not capture the complete hosted view")
            throw PreviewError.drawFailed
        }
        XCTAssertGreaterThan(image.size.width, 0)
        XCTAssertGreaterThan(image.size.height, 0)
        return image
    }
}
#endif
