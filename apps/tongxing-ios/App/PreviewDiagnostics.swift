#if DEBUG
import Foundation
import SwiftUI

struct PreviewAnchorEntry {
    let id: String
    let label: String?
    let bounds: Anchor<CGRect>
}

struct PreviewAnchorPreferenceKey: PreferenceKey {
    static let defaultValue: [PreviewAnchorEntry] = []

    static func reduce(value: inout [PreviewAnchorEntry], nextValue: () -> [PreviewAnchorEntry]) {
        value.append(contentsOf: nextValue())
    }
}

private struct PreviewCaptureRecord: Codable, Equatable {
    let kind: String
    let id: String
    let label: String?
    /// Window-coordinate points: x, y, width, height.
    let frame: [Double]
}

private struct PreviewCaptureDocument: Codable, Equatable {
    let schema: String
    let scene: String
    let requestedDevice: String
    let sourceFingerprint: String
    let colorScheme: String
    let dynamicTypeSize: String
    let operatingSystem: String
    let records: [PreviewCaptureRecord]
}

extension View {
    /// Adds geometry metadata without changing the accessibility tree or hit testing.
    func designAnchor(_ id: String, label: String? = nil) -> some View {
        transformAnchorPreference(key: PreviewAnchorPreferenceKey.self, value: .bounds) { entries, anchor in
            entries.append(PreviewAnchorEntry(id: id, label: label, bounds: anchor))
        }
    }

    func designProbe(scene: String, requestedDevice: String, fingerprint: String) -> some View {
        modifier(PreviewCaptureProbe(scene: scene, requestedDevice: requestedDevice,
                                     fingerprint: fingerprint))
    }
}

private struct PreviewCaptureProbe: ViewModifier {
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    let scene: String
    let requestedDevice: String
    let fingerprint: String

    func body(content: Content) -> some View {
        content.overlayPreferenceValue(PreviewAnchorPreferenceKey.self) { entries in
            GeometryReader { proxy in
                let origin = proxy.frame(in: .global).origin
                let size = proxy.size
                let safeArea = proxy.safeAreaInsets
                let number = { (value: CGFloat) in
                    (Double(value) * 10).rounded() / 10
                }
                let screen = PreviewCaptureRecord(
                    kind: "screen", id: "__screen__",
                    label: "safeArea=\(safeArea.top),\(safeArea.leading),\(safeArea.bottom),\(safeArea.trailing)",
                    frame: [0, 0, number(size.width + safeArea.leading + safeArea.trailing),
                            number(size.height + safeArea.top + safeArea.bottom)]
                )
                let build = PreviewCaptureRecord(kind: "build", id: "__build__",
                                                 label: fingerprint, frame: [0, 0, 0, 0])
                let controls = entries.map { entry in
                    let rect = proxy[entry.bounds]
                    return PreviewCaptureRecord(
                        kind: "anchor", id: entry.id, label: entry.label,
                        frame: [number(rect.minX + origin.x), number(rect.minY + origin.y),
                                number(rect.width), number(rect.height)]
                    )
                }
                let document = PreviewCaptureDocument(
                    schema: "tongxing-preview-capture-v1", scene: scene,
                    requestedDevice: requestedDevice, sourceFingerprint: fingerprint,
                    colorScheme: colorScheme == .dark ? "dark" : "light",
                    dynamicTypeSize: String(describing: dynamicTypeSize),
                    operatingSystem: ProcessInfo.processInfo.operatingSystemVersionString,
                    records: [screen, build] + controls
                )
                Color.clear
                    .task(id: document) { write(document) }
                    .allowsHitTesting(false)
            }
        }
    }

    private func write(_ document: PreviewCaptureDocument) {
        let environment = ProcessInfo.processInfo.environment
        let base: URL
        if let override = environment["TONGXING_PREVIEW_CAPTURE_DIR"], !override.isEmpty {
            base = URL(fileURLWithPath: override, isDirectory: true)
        } else if let hostHome = environment["SIMULATOR_HOST_HOME"], !hostHome.isEmpty {
            base = URL(fileURLWithPath: hostHome, isDirectory: true)
                .appendingPathComponent("Library/Caches/Tongxing/PreviewCaptures", isDirectory: true)
        } else {
            base = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
                .appendingPathComponent("Tongxing/PreviewCaptures", isDirectory: true)
        }
        let appearance = document.colorScheme
        let textSize = document.dynamicTypeSize.replacingOccurrences(of: ".", with: "-")
        let name = "\(document.scene)-\(appearance)-\(textSize)-\(document.sourceFingerprint).json"
        let destination = base.appendingPathComponent(name)
        do {
            try FileManager.default.createDirectory(at: base, withIntermediateDirectories: true)
            let encoder = JSONEncoder()
            encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
            try encoder.encode(document).write(to: destination, options: .atomic)
            print("TONGXING_PREVIEW_CAPTURE_FILE=\(destination.path)")
        } catch {
            print("TONGXING_PREVIEW_CAPTURE_ERROR=\(error.localizedDescription)")
        }
    }
}
#endif
