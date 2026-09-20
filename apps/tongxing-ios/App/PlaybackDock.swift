import SwiftUI
import TongxingCore

struct PlaybackDock: View {
    @ObservedObject private var localization = AppLocalization.shared
    @ObservedObject var playback: PlaybackController
    @Environment(\.colorScheme) private var scheme
    @Environment(\.dynamicTypeSize) private var typeSize
    @Environment(\.verticalSizeClass) private var verticalSizeClass
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var isCollapsed = false
    var isPreparing = false
    var alignmentModel: AppModel? = nil
    var precision: (() -> Void)? = nil
    var current: (() -> Void)? = nil

    var body: some View {
        Group {
            if isCollapsed {
                miniPlayButton
                    .padding(6)
                    .listeningGlassSurface()
            } else {
                Group {
                    if verticalSizeClass == .compact { compactControls }
                    else { fullControls }
                }
                .padding(.horizontal, 18)
                .padding(.top, verticalSizeClass == .compact ? 10 : 14)
                .padding(.bottom, 8)
                .listeningGlassSurface()
                .frame(maxWidth: verticalSizeClass == .compact ? 880 : 660)
            }
        }
        .contentShape(Rectangle())
        .simultaneousGesture(dockGesture)
        .padding(.horizontal, 12).padding(.vertical, 8)
        .frame(maxWidth: .infinity)
    }

    // Presentation state only: collapsing never changes playback or alignment.
    private func setCollapsed(_ collapsed: Bool) {
        withAnimation(reduceMotion ? nil : .easeInOut(duration: 0.2)) {
            isCollapsed = collapsed
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

    private var miniPlayButton: some View {
        Button {
            if playback.isReady && !isPreparing { playback.toggle() }
        } label: {
            Image(systemName: playback.isPlaying || playback.isWaiting ? "pause.fill" : "play.fill")
                .font(.title3.weight(.semibold))
                .contentTransition(.identity)
                .frame(width: 56, height: 56)
                .foregroundStyle(Brand.prominentLabel(scheme))
                .background(Brand.accent, in: Circle())
                .opacity(playback.isReady && !isPreparing ? 1 : 0.5)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(playLabel)
        .accessibilityValue(statusLabel)
        .accessibilityHint(localization.text("向上轻扫展开播放栏"))
        .accessibilityIdentifier("playback-toggle")
        // Keep the custom expand action reachable even while audio is preparing.
        .accessibilityAction(named: Text(localization.text("展开播放栏"))) { setCollapsed(false) }
        .contextMenu {
            Button(localization.text("展开播放栏"), systemImage: "chevron.up") { setCollapsed(false) }
        }
    }

    private var fullControls: some View {
        VStack(spacing: 10) {
            timeAndStatus
            HStack(spacing: 12) {
                if typeSize.isAccessibilitySize {
                    compactNudge(-1).labelStyle(.iconOnly).frame(width: 44)
                    playButton
                    compactNudge(1).labelStyle(.iconOnly).frame(width: 44)
                } else {
                    nudgeButton(-1)
                    playButton
                    nudgeButton(1)
                }
            }
            .buttonStyle(.plain).foregroundStyle(.primary)
            .disabled(!playback.isReady || isPreparing)

            if let alignmentModel {
                AlignmentControls(model: alignmentModel, compact: true)
            }
            if precision != nil || current != nil || playback.undoPosition != nil {
                if typeSize.isAccessibilitySize {
                    HStack(spacing: 16) {
                        if let current { currentButton(current) }
                        if let previous = playback.undoPosition { undoButton(previous) }
                        Spacer(minLength: 0)
                        if let precision { precisionButton(precision) }
                    }
                    .labelStyle(.iconOnly)
                    .font(.footnote.weight(.medium))
                    .buttonStyle(.plain).foregroundStyle(.primary)
                } else {
                    utilityActions
                }
            }
        }
    }

    private var compactControls: some View {
        VStack(spacing: 6) {
            timeAndStatus
            HStack(spacing: 12) {
                compactNudge(-1)
                playButton.frame(maxWidth: 150)
                compactNudge(1)
                Spacer(minLength: 0)
                if let current { currentButton(current).labelStyle(.iconOnly) }
                if let previous = playback.undoPosition { undoButton(previous).labelStyle(.iconOnly) }
                if let precision { precisionButton(precision).labelStyle(.iconOnly) }
            }
            .buttonStyle(.plain).foregroundStyle(.primary)
            .disabled(!playback.isReady || isPreparing)
            if let alignmentModel {
                AlignmentControls(model: alignmentModel, compact: true)
            }
        }
    }

    private func compactNudge(_ seconds: Double) -> some View {
        Button { playback.nudge(seconds) } label: {
            Label(localization.text("1 秒"), systemImage: seconds < 0 ? "gobackward" : "goforward")
                .font(.body.weight(.medium)).fixedSize()
                .frame(maxWidth: .infinity, minHeight: 44)
                .contentShape(Rectangle())
        }
        .accessibilityLabel(localization.text(seconds < 0 ? "中文抢先，后退1秒" : "中文落后，前进1秒"))
        .accessibilityIdentifier(seconds < 0 ? "nudge-backward" : "nudge-forward")
    }

    private var timeAndStatus: some View {
        VStack(spacing: 4) {
            HStack(alignment: .firstTextBaseline) {
                Text(PlaybackTime.format(playback.position))
                    .foregroundStyle(.primary).fontWeight(.semibold)
                Spacer(minLength: 10)
                if !typeSize.isAccessibilitySize {
                    Text(statusLabel).lineLimit(1)
                        .frame(maxWidth: .infinity)
                }
                Spacer(minLength: 10)
                Text(PlaybackTime.format(playback.duration))
            }
            .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(localization.text("播放进度"))
            .accessibilityValue(localization.text("{time}，总长 {duration}。{status}", ["time": PlaybackTime.format(playback.position), "duration": PlaybackTime.format(playback.duration), "status": statusLabel]))
            .accessibilityIdentifier("playback-progress")
            .accessibilityAction(named: Text(localization.text("收起播放栏"))) { setCollapsed(true) }
        }
    }

    private func nudgeButton(_ seconds: Double) -> some View {
        Button { playback.nudge(seconds) } label: {
            VStack(spacing: 5) {
                Image(systemName: seconds < 0 ? "gobackward" : "goforward")
                    .font(.system(size: 24, weight: .medium))
                    .accessibilityHidden(true)
                Text(localization.text(seconds < 0 ? "后退 1 秒" : "前进 1 秒"))
                    .font(.caption.weight(.medium))
                    .fixedSize(horizontal: false, vertical: true)
            }
            .frame(maxWidth: .infinity, minHeight: 58)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain).foregroundStyle(.primary)
        .accessibilityLabel(localization.text(seconds < 0 ? "中文抢先，后退1秒" : "中文落后，前进1秒"))
        .accessibilityHint(localization.text("调整中文音频的位置"))
        .accessibilityIdentifier(seconds < 0 ? "nudge-backward" : "nudge-forward")
    }

    private var playButton: some View {
        Button { playback.toggle() } label: {
            HStack(spacing: 9) {
                Image(systemName: playback.isPlaying || playback.isWaiting ? "pause.fill" : "play.fill")
                    .font(.title3.weight(.semibold))
                    .contentTransition(.identity)
                Text(shortPlayLabel).font(.headline)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .frame(maxWidth: .infinity, minHeight: 60)
            .padding(.horizontal, 8)
            .foregroundStyle(Brand.prominentLabel(scheme))
            .background(Brand.accent, in: Capsule())
            .contentShape(Capsule())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(playLabel)
        .accessibilityIdentifier("playback-toggle")
        .accessibilityHint(localization.text("向下轻扫收起播放栏"))
        .accessibilityAction(named: Text(localization.text("收起播放栏"))) { setCollapsed(true) }
    }

    private var utilityActions: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 12) {
                if let current { currentButton(current) }
                if let previous = playback.undoPosition { undoButton(previous) }
                Spacer(minLength: 0)
                if let precision { precisionButton(precision) }
            }
            VStack(spacing: 0) {
                HStack {
                    if let current { currentButton(current) }
                    Spacer()
                    if let precision { precisionButton(precision) }
                }
                if let previous = playback.undoPosition { undoButton(previous) }
            }
        }
        .font(.footnote.weight(.medium))
        .buttonStyle(.plain).foregroundStyle(.primary)
    }

    private func currentButton(_ action: @escaping () -> Void) -> some View {
        Button(action: action) { Label(localization.text("当前句"), systemImage: "text.line.first.and.arrowtriangle.forward")
                .frame(minWidth: 44, minHeight: 44).contentShape(Rectangle()) }
            .accessibilityLabel(localization.text("回到当前句"))
            .accessibilityIdentifier("current-cue")
    }

    private func precisionButton(_ action: @escaping () -> Void) -> some View {
        Button(action: action) { Label(localization.text("定位 / 精调"), systemImage: "slider.horizontal.3")
                .frame(minWidth: 44, minHeight: 44).contentShape(Rectangle()) }
            .disabled(!playback.isReady || isPreparing)
            .accessibilityIdentifier("precision-controls")
    }

    private func undoButton(_ previous: Double) -> some View {
        Button { playback.undo() } label: {
            Label(localization.text("撤销"), systemImage: "arrow.uturn.backward")
                .frame(minWidth: 44, minHeight: 44).contentShape(Rectangle())
        }
        .accessibilityLabel(localization.text("撤销跳转，返回 {time}", ["time": PlaybackTime.format(previous)]))
        .accessibilityIdentifier("undo-seek")
        .disabled(!playback.isReady || isPreparing)
    }

    private var statusLabel: String { localization.text(isPreparing ? "正在准备音频…" : playback.message) }
    private var shortPlayLabel: String {
        if playback.isPlaying || playback.isWaiting { return localization.text("暂停") }
        return localization.text(playback.resumePosition == nil ? "播放" : "继续")
    }
    private var playLabel: String {
        if playback.isPlaying || playback.isWaiting { return localization.text("暂停播放") }
        return localization.text(playback.resumePosition == nil ? "开始播放" : "继续收听")
    }
}
