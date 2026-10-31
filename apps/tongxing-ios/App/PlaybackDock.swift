import SwiftUI
import TongxingCore

enum PlaybackDockPlacement {
    case bottom
    case trailing
}

struct PlaybackDock: View {
    @ObservedObject private var localization = AppLocalization.shared
    @ObservedObject var playback: PlaybackController
    @Environment(\.colorScheme) private var scheme
    @Environment(\.dynamicTypeSize) private var typeSize
    var isPreparing = false
    var alignmentModel: AppModel? = nil
    var locate: (() -> Void)? = nil
    var precision: (() -> Void)? = nil
    var current: (() -> Void)? = nil
    var onTimeTap: (() -> Void)? = nil
    var placement: PlaybackDockPlacement = .bottom
    var inSystemBar = false
    /// The host owns the open state so it can close the panel when a sheet or
    /// an alignment failure takes over. The content is the shared
    /// `PlaybackMoreControls`; the dock only anchors the system popover.
    var isMorePresented: Binding<Bool>? = nil
    var moreContent: (() -> AnyView)? = nil
    /// When the dock lives inside a system toolbar item, a popover anchored
    /// here is placed against the bar instead of the button. The host then
    /// presents `moreContent` itself, anchored to this button frame.
    var defersMorePresentation = false
    var onMoreButtonFrame: ((CGRect) -> Void)? = nil

    var body: some View {
        Group {
            if placement == .trailing {
                dockSurface.frame(width: 80)
            } else {
                dockSurface.frame(maxWidth: 440).frame(maxWidth: .infinity)
            }
        }
    }

    private var dockSurface: some View {
        Group {
            if placement == .trailing {
                if inSystemBar { verticalControls }
                else { verticalControls.padding(6).listeningGlassSurface() }
            } else {
                horizontalControls
                    .padding(.horizontal, 8).padding(.vertical, 6)
                    .listeningGlassSurface()
            }
        }
        .contentShape(Rectangle())
        .padding(.horizontal, inSystemBar ? 0 : placement == .trailing ? 6 : 12)
        .padding(.vertical, inSystemBar ? 0 : 8)
    }

    @ViewBuilder private var horizontalControls: some View {
        if typeSize.isAccessibilitySize {
            compactControls
        } else {
            ViewThatFits(in: .horizontal) {
                HStack(spacing: 3) {
                    timeAndStatus
                    transportControls
                }
                compactControls
            }
            .buttonStyle(.plain)
        }
    }

    private var compactControls: some View {
        HStack(spacing: 3) { transportControls }
            .buttonStyle(.plain)
    }

    @ViewBuilder private var transportControls: some View {
        nudgeButton(-1)
        playButton
        nudgeButton(1)
        if hasMoreControls { moreButton }
    }

    private var verticalControls: some View {
        VStack(spacing: 4) {
            if !typeSize.isAccessibilitySize { timeAndStatus }
            nudgeButton(-1)
            playButton
            nudgeButton(1)
            if hasMoreControls { moreButton }
        }
        .buttonStyle(.plain)
    }

    private var hasMoreControls: Bool {
        isMorePresented != nil && moreContent != nil
            && (alignmentModel != nil || precision != nil || current != nil || playback.undoPosition != nil)
    }

    /// The more panel is a system popover anchored to this button. On iPhone
    /// `.presentationCompactAdaptation(.popover)` keeps it a popover instead of
    /// a sheet, so UIKit positions it, points the arrow at the button, keeps it
    /// on screen and dismisses it on an outside tap.
    private var moreButton: some View {
        Button {
            isMorePresented?.wrappedValue = true
        } label: {
            Image(systemName: "magnifyingglass")
                .font(.system(size: 20, weight: .medium))
                .frame(width: 48, height: 52)
                .contentShape(Rectangle())
        }
        .accessibilityLabel(localization.text("定位"))
        .accessibilityIdentifier("playback-more")
        .background {
            if defersMorePresentation {
                WindowFrameReader { onMoreButtonFrame?($0) }
            }
        }
        .modifier(MorePopoverAnchor(isPresented: isMorePresented ?? .constant(false),
                                    deferred: defersMorePresentation,
                                    content: moreContent,
                                    arrowEdge: placement == .trailing ? .trailing : .bottom,
                                    onDisappear: { isMorePresented?.wrappedValue = false }))
    }

    @ViewBuilder private var timeAndStatus: some View {
        if let onTimeTap {
            Button(action: onTimeTap) {
                progressText.frame(minWidth: 44, minHeight: 44).contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityHint(localization.text("回到当前句"))
        } else {
            progressText
        }
    }

    private var progressText: some View {
        HStack(spacing: 1) {
            Text(PlaybackTime.format(playback.position))
                .fontWeight(.semibold)
            if placement == .bottom && !typeSize.isAccessibilitySize {
                Text("/" + PlaybackTime.format(playback.duration))
            }
        }
        .font(.caption2.monospacedDigit())
        .foregroundStyle(.secondary)
        .fixedSize()
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(localization.text("播放进度"))
        .accessibilityValue(localization.text("{time}，总长 {duration}。{status}", [
            "time": PlaybackTime.format(playback.position),
            "duration": PlaybackTime.format(playback.duration),
            "status": statusLabel
        ]))
        .accessibilityIdentifier("playback-progress")
    }

    private func nudgeButton(_ seconds: Double) -> some View {
        Button { playback.nudge(seconds) } label: {
            Image(systemName: seconds < 0 ? "gobackward" : "goforward")
                .font(.system(size: 20, weight: .medium))
                .frame(width: 44, height: 52)
                .contentShape(Rectangle())
        }
        .disabled(!playback.isReady || isPreparing)
        .accessibilityLabel(localization.text(seconds < 0 ? "中文抢先，后退1秒" : "中文落后，前进1秒"))
        .accessibilityHint(localization.text("调整中文音频的位置"))
        .accessibilityIdentifier(seconds < 0 ? "nudge-backward" : "nudge-forward")
    }

    @ViewBuilder private var playButton: some View {
        if let alignmentModel {
            AlignmentObservedContent(model: alignmentModel) { isAligning in
                transportPlayButton(isAligning: isAligning)
            }
        } else {
            transportPlayButton(isAligning: false)
        }
    }

    private func transportPlayButton(isAligning: Bool) -> some View {
        Button {
            if playback.isReady && !isPreparing { playback.toggle() }
        } label: {
            ZStack(alignment: .topTrailing) {
                Image(systemName: playback.isPlaying || playback.isWaiting ? "pause.fill" : "play.fill")
                    .font(.system(size: 20, weight: .semibold))
                    .contentTransition(.identity)
                    .frame(width: inSystemBar ? 44 : 56, height: inSystemBar ? 44 : 56)
                    .foregroundStyle(Brand.prominentLabel(scheme))
                    .background(Brand.accent, in: Circle())
                    .opacity(playback.isReady && !isPreparing ? 1 : 0.5)
                if isAligning {
                    ProgressView()
                        .controlSize(.mini)
                        .accessibilityIdentifier("playback-alignment-progress")
                        .padding(5)
                        .background(.ultraThinMaterial, in: Circle())
                        .accessibilityHidden(true)
                }
            }
        }
        .buttonStyle(.plain)
        .disabled(!playback.isReady || isPreparing)
        .accessibilityLabel(playLabel)
        .accessibilityValue(localization.text("{time}，总长 {duration}。{status}", [
            "time": PlaybackTime.format(playback.position),
            "duration": PlaybackTime.format(playback.duration),
            "status": isAligning
                ? localization.text("正在对齐。{status}", ["status": statusLabel]) : statusLabel
        ]))
        .accessibilityIdentifier("playback-toggle")
    }

    private var statusLabel: String { localization.text(isPreparing ? "正在准备音频…" : playback.message) }

    private var playLabel: String {
        if playback.isPlaying || playback.isWaiting { return localization.text("暂停播放") }
        return localization.text(playback.resumePosition == nil ? "开始播放" : "继续收听")
    }
}

/// Observes the supplied model directly; the optional dock API remains usable
/// in hosts without alignment without inventing another playback state source.
private struct AlignmentObservedContent<Content: View>: View {
    @ObservedObject var model: AppModel
    @ViewBuilder var content: (Bool) -> Content
    var body: some View { content(model.alignmentBusy) }
}

struct PlaybackMoreControls: View {
    @ObservedObject private var localization = AppLocalization.shared
    @ObservedObject var playback: PlaybackController
    var isPreparing: Bool
    var alignmentModel: AppModel?
    var locate: (() -> Void)? = nil
    var precision: (() -> Void)?
    var current: (() -> Void)?
    /// Closes the popover before an action opens a sheet or scrolls. The
    /// popover itself needs no close button: tapping outside dismisses it.
    var onClose: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if let alignmentModel {
                AlignmentControls(model: alignmentModel, compact: true, locate: locate == nil ? nil : openLocate)
            }
            if locate != nil {
                Button(action: openLocate) {
                    Label(localization.text("按英文找位置"), systemImage: "text.magnifyingglass")
                        .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain).foregroundStyle(Brand.accent)
                .accessibilityIdentifier("locate-english-action")
            }
            if current != nil || precision != nil || playback.undoPosition != nil {
                utilityActions
            }
        }
        .padding(12)
        .frame(minWidth: 260, idealWidth: 300, maxWidth: 320)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("playback-more-panel")
        .accessibilityAction(.escape, onClose)
    }

    private func openLocate() {
        onClose()
        if let locate { DispatchQueue.main.async(execute: locate) }
    }

    private var utilityActions: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 8) {
                if let current { currentButton(current) }
                if let previous = playback.undoPosition { undoButton(previous) }
                Spacer(minLength: 0)
                if let precision { precisionButton(precision) }
            }
            VStack(alignment: .leading, spacing: 0) {
                if let current { currentButton(current) }
                if let previous = playback.undoPosition { undoButton(previous) }
                if let precision { precisionButton(precision) }
            }
        }
        .font(.footnote.weight(.medium))
        .buttonStyle(.plain)
        .foregroundStyle(.primary)
    }

    private func currentButton(_ action: @escaping () -> Void) -> some View {
        Button {
            onClose()
            action()
        } label: {
            Label(localization.text("当前句"), systemImage: "text.bubble")
                .frame(minWidth: 44, minHeight: 44).contentShape(Rectangle())
        }
        .accessibilityLabel(localization.text("回到当前句"))
        .accessibilityIdentifier("current-cue")
    }

    private func precisionButton(_ action: @escaping () -> Void) -> some View {
        Button {
            onClose()
            DispatchQueue.main.async(execute: action)
        } label: {
            Label(localization.text("定位 / 精调"), systemImage: "slider.horizontal.3")
                .frame(minWidth: 44, minHeight: 44).contentShape(Rectangle())
        }
        .disabled(!playback.isReady || isPreparing)
        .accessibilityIdentifier("precision-controls")
    }

    private func undoButton(_ previous: Double) -> some View {
        Button {
            onClose()
            playback.undo()
        } label: {
            Label(localization.text("撤销"), systemImage: "arrow.uturn.backward")
                .frame(minWidth: 44, minHeight: 44).contentShape(Rectangle())
        }
        .accessibilityLabel(localization.text("撤销跳转，返回 {time}", ["time": PlaybackTime.format(previous)]))
        .accessibilityIdentifier("undo-seek")
        .disabled(!playback.isReady || isPreparing)
    }
}

/// Attaches the popover unless the host defers presentation (system toolbar
/// hosts cannot anchor a popover to their own subview).
private struct MorePopoverAnchor: ViewModifier {
    let isPresented: Binding<Bool>
    let deferred: Bool
    let content: (() -> AnyView)?
    let arrowEdge: Edge
    let onDisappear: () -> Void

    func body(content base: Content) -> some View {
        if deferred {
            base.onDisappear(perform: onDisappear)
        } else {
            base
                .popover(isPresented: isPresented, attachmentAnchor: .rect(.bounds), arrowEdge: arrowEdge) {
                    content?()
                        .presentationCompactAdaptation(.popover)
                }
                .onDisappear(perform: onDisappear)
        }
    }
}

#if os(iOS)
/// Reports the hosted view's frame in window coordinates. A toolbar item's
/// `.frame(in: .global)` resolves against the bar, so anchoring a popover from
/// inside the bar drops it in the corner; this keeps real screen geometry.
private struct WindowFrameReader: UIViewRepresentable {
    var onChange: (CGRect) -> Void

    func makeUIView(context: Context) -> ReaderView {
        let view = ReaderView()
        view.onChange = onChange
        return view
    }

    func updateUIView(_ view: ReaderView, context: Context) {
        view.onChange = onChange
        view.report()
    }

    final class ReaderView: UIView {
        var onChange: ((CGRect) -> Void)?

        override func layoutSubviews() {
            super.layoutSubviews()
            report()
        }

        override func didMoveToWindow() {
            super.didMoveToWindow()
            report()
        }

        override var intrinsicContentSize: CGSize { .zero }

        private var reported: CGRect = .null

        func report() {
            guard window != nil else { return }
            let frame = convert(bounds, to: nil)
            guard frame != reported else { return }
            reported = frame
            onChange?(frame)
        }
    }
}
#endif
