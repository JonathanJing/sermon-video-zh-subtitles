import SwiftUI
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif

enum Brand {
    static let ink = Color(red: 0.09, green: 0.20, blue: 0.22)
    static let sage = Color(red: 0.68, green: 0.82, blue: 0.75)

    // Semantic surfaces and an adaptive accent keep the reading layer legible.
    // Only the floating controls use Liquid Glass.
    #if os(iOS)
    static let accent = Color(uiColor: UIColor { traits in
        traits.userInterfaceStyle == .dark
            ? UIColor(red: 0.60, green: 0.84, blue: 0.73, alpha: 1)
            : UIColor(red: 0.17, green: 0.39, blue: 0.32, alpha: 1)
    })
    static let background = Color(uiColor: .systemGroupedBackground)
    static let surface = Color(uiColor: .secondarySystemGroupedBackground)
    static let controlSurface = Color(uiColor: .secondarySystemBackground)
    #elseif os(macOS)
    static let accent = Color(nsColor: NSColor(name: nil) { appearance in
        appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
            ? NSColor(red: 0.60, green: 0.84, blue: 0.73, alpha: 1)
            : NSColor(red: 0.17, green: 0.39, blue: 0.32, alpha: 1)
    })
    static let background = Color(nsColor: .windowBackgroundColor)
    static let surface = Color(nsColor: .controlBackgroundColor)
    static let controlSurface = Color(nsColor: .windowBackgroundColor)
    #endif

    static func prominentLabel(_ scheme: ColorScheme) -> Color {
        scheme == .dark ? ink : .white
    }
}

extension View {
    // Older SDKs still compile the iOS 17 fallback; 26+ SDKs use the real system
    // material and register the bar for the scroll-edge legibility treatment.
    @ViewBuilder
    func listeningBottomBar<Bar: View>(@ViewBuilder content: () -> Bar) -> some View {
        #if compiler(>=6.2)
        if #available(iOS 26, macOS 26, *) {
            safeAreaBar(edge: .bottom, spacing: 0, content: content)
        } else {
            safeAreaInset(edge: .bottom, spacing: 0, content: content)
        }
        #else
        safeAreaInset(edge: .bottom, spacing: 0, content: content)
        #endif
    }

    func listeningGlassSurface() -> some View { modifier(ListeningGlassSurface()) }
}

private struct ListeningGlassSurface: ViewModifier {
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @Environment(\.colorSchemeContrast) private var contrast

    private let shape = RoundedRectangle(cornerRadius: 30, style: .continuous)

    func body(content: Content) -> some View {
        surface(content)
            .overlay {
                if contrast == .increased {
                    shape.strokeBorder(.primary.opacity(0.35), lineWidth: 1.5)
                }
            }
    }

    @ViewBuilder private func surface(_ content: Content) -> some View {
        if reduceTransparency {
            content.background(Brand.controlSurface, in: shape)
                .shadow(color: .black.opacity(0.12), radius: 12, y: 4)
        } else {
            #if compiler(>=6.2)
            if #available(iOS 26, macOS 26, *) {
                content.glassEffect(.regular, in: shape)
            } else {
                content.background(.regularMaterial, in: shape)
                    .shadow(color: .black.opacity(0.10), radius: 12, y: 4)
            }
            #else
            content.background(.regularMaterial, in: shape)
                .shadow(color: .black.opacity(0.10), radius: 12, y: 4)
            #endif
        }
    }
}
