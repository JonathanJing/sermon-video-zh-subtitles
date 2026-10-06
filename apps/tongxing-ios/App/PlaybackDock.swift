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
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var isCollapsed = false
    @State private var showingMore = false
    var isPreparing = false
    var alignmentModel: AppModel? = nil
    var locate: (() -> Void)? = nil
    var precision: (() -> Void)? = nil
    var current: (() -> Void)? = nil
    var onTimeTap: (() -> Void)? = nil
    var placement: PlaybackDockPlacement = .bottom
    var inSystemBar = false
    var onMoreTap: (() -> Void)? = nil
    var onMoreDismiss: (() -> Void)? = nil
    var onMoreFrameChange: ((CGRect) -> Void)? = nil

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
            if isCollapsed {
                if inSystemBar { playButton }
                else { playButton.padding(6).listeningCircularGlassSurface() }
            } else if placement == .trailing {
                if inSystemBar { verticalControls }
                else { verticalControls.padding(6).listeningGlassSurface() }
            } else {
                horizontalControls
                    .padding(.horizontal, 8).padding(.vertical, 6)
                    .listeningGlassSurface()
            }
        }
        .contentShape(Rectangle())
        .simultaneousGesture(dockGesture)
        .padding(.horizontal, inSystemBar ? 0 : placement == .trailing ? 6 : 12)
        .padding(.vertical, inSystemBar ? 0 : 8)
    }

    private var horizontalControls: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 3) {
                timeAndStatus
                nudgeButton(-1)
                playButton
                nudgeButton(1)
                if hasMoreControls { moreButton }
            }
            // Narrow widths (split view, compact windows): keep the essential
            // transport controls. Time/status stays available to VoiceOver via
            // the play button's accessibility value.
            HStack(spacing: 6) {
                nudgeButton(-1)
                playButton
                nudgeButton(1)
                if hasMoreControls { moreButton }
            }
        }
        .buttonStyle(.plain)
    }

    private var verticalControls: some View {
        VStack(spacing: 4) {
            timeAndStatus
            nudgeButton(-1)
            playButton
            nudgeButton(1)
            if hasMoreControls { moreButton }
        }
        .buttonStyle(.plain)
    }

    private var hasMoreControls: Bool {
        alignmentModel != nil || precision != nil || current != nil || playback.undoPosition != nil
    }

    private var moreButton: some View {
        Button {
            if let onMoreTap { onMoreTap() }
            else { showingMore = true }
        } label: {
            Image(systemName: "magnifyingglass")
                .font(.title3.weight(.medium))
                .frame(width: 48, height: 52)
                .contentShape(Rectangle())
        }
        .accessibilityLabel(localization.text("定位"))
        .accessibilityIdentifier("playback-more")
        .popover(isPresented: $showingMore, arrowEdge: placement == .trailing ? .trailing : .bottom) {
            PlaybackMoreControls(playback: playback, isPreparing: isPreparing,
                                 alignmentModel: alignmentModel, locate: locate, precision: precision,
                                 current: current, onClose: { showingMore = false })
                .presentationCompactAdaptation(.popover)
        }
        .onGeometryChange(for: CGRect.self, of: { $0.frame(in: .global) }) { frame in
            onMoreFrameChange?(frame)
        }
        .onDisappear {
            onMoreFrameChange?(.null)
            onMoreDismiss?()
        }
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
        .accessibilityAction(named: Text(localization.text("收起播放栏"))) { setCollapsed(true) }
    }

    private func nudgeButton(_ seconds: Double) -> some View {
        Button { playback.nudge(seconds) } label: {
            Image(systemName: seconds < 0 ? "gobackward" : "goforward")
                .font(.title3.weight(.medium))
                .frame(width: 44, height: 52)
                .contentShape(Rectangle())
        }
        .disabled(!playback.isReady || isPreparing)
        .accessibilityLabel(localization.text(seconds < 0 ? "中文抢先，后退1秒" : "中文落后，前进1秒"))
        .accessibilityHint(localization.text("调整中文音频的位置"))
        .accessibilityIdentifier(seconds < 0 ? "nudge-backward" : "nudge-forward")
    }

    private var playButton: some View {
        Button {
            if playback.isReady && !isPreparing { playback.toggle() }
        } label: {
            Image(systemName: playback.isPlaying || playback.isWaiting ? "pause.fill" : "play.fill")
                .font(.title3.weight(.semibold))
                .contentTransition(.identity)
                .frame(width: inSystemBar ? 44 : 56, height: inSystemBar ? 44 : 56)
                .foregroundStyle(Brand.prominentLabel(scheme))
                .background(Brand.accent, in: Circle())
                .opacity(playback.isReady && !isPreparing ? 1 : 0.5)
        }
        .buttonStyle(.plain)
        .disabled(!playback.isReady || isPreparing)
        .accessibilityLabel(playLabel)
        .accessibilityValue(statusLabel)
        .accessibilityIdentifier("playback-toggle")
        .accessibilityHint(localization.text(isCollapsed ? "向上轻扫展开播放栏" : "向下轻扫收起播放栏"))
        .accessibilityAction(named: Text(localization.text(isCollapsed ? "展开播放栏" : "收起播放栏"))) {
            setCollapsed(!isCollapsed)
        }
        .contextMenu {
            Button(localization.text(isCollapsed ? "展开播放栏" : "收起播放栏"),
                   systemImage: isCollapsed ? "chevron.up" : "chevron.down") {
                setCollapsed(!isCollapsed)
            }
        }
    }

    private var dockGesture: some Gesture {
        DragGesture(minimumDistance: 16)
            .onEnded { value in
                let movement = value.translation
                guard abs(movement.height) > 32,
                      abs(movement.height) > abs(movement.width) * 1.5 else { return }
                setCollapsed(movement.height > 0)
            }
    }

    private func setCollapsed(_ collapsed: Bool) {
        withAnimation(reduceMotion ? nil : .easeInOut(duration: 0.2)) {
            isCollapsed = collapsed
            if collapsed {
                showingMore = false
                onMoreDismiss?()
            }
        }
    }

    private var statusLabel: String { localization.text(isPreparing ? "正在准备音频…" : playback.message) }
    private var playLabel: String {
        if playback.isPlaying || playback.isWaiting { return localization.text("暂停播放") }
        return localization.text(playback.resumePosition == nil ? "开始播放" : "继续收听")
    }
}

struct PlaybackMoreControls: View {
    @ObservedObject private var localization = AppLocalization.shared
    @ObservedObject var playback: PlaybackController
    @AccessibilityFocusState private var closeFocused: Bool
    var isPreparing: Bool
    var alignmentModel: AppModel?
    var locate: (() -> Void)? = nil
    var precision: (() -> Void)?
    var current: (() -> Void)?
    var onClose: () -> Void
    var width: CGFloat = 320

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text(localization.text("定位")).font(.headline)
                Spacer()
                Button(action: onClose) {
                    Image(systemName: "xmark")
                        .font(.footnote.weight(.semibold))
                        .frame(width: 44, height: 44)
                }
                .accessibilityLabel(localization.text("关闭"))
                .accessibilityIdentifier("playback-more-close")
                .accessibilityFocused($closeFocused)
            }
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
        .frame(width: width)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("playback-more-panel")
        .accessibilityAddTraits(.isModal)
        .accessibilityAction(.escape, onClose)
        .task { closeFocused = true }
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
