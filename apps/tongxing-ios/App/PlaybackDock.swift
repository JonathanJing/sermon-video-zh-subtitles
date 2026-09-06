import SwiftUI
import TongxingCore

struct PlaybackDock: View {
    @ObservedObject var playback: PlaybackController
    @Environment(\.colorScheme) private var scheme
    @Environment(\.dynamicTypeSize) private var typeSize
    @Environment(\.verticalSizeClass) private var verticalSizeClass
    var isPreparing = false
    var precision: (() -> Void)? = nil
    var current: (() -> Void)? = nil

    var body: some View {
        Group {
            if verticalSizeClass == .compact { compactControls }
            else { fullControls }
        }
        .padding(.horizontal, 18)
        .padding(.top, verticalSizeClass == .compact ? 10 : 14)
        .padding(.bottom, 8)
        .listeningGlassSurface()
        .padding(.horizontal, 12).padding(.vertical, 8)
        .frame(maxWidth: verticalSizeClass == .compact ? 880 : 660)
        .frame(maxWidth: .infinity)
    }

    private var fullControls: some View {
        VStack(spacing: 10) {
            timeAndStatus
            Group {
                if typeSize.isAccessibilitySize {
                    VStack(spacing: 12) {
                        playButton
                        HStack(spacing: 16) { nudgeButton(-1); nudgeButton(1) }
                    }
                } else {
                    HStack(spacing: 12) {
                        nudgeButton(-1)
                        playButton
                        nudgeButton(1)
                    }
                }
            }.disabled(!playback.isReady || isPreparing)

            if precision != nil || current != nil || playback.undoPosition != nil {
                utilityActions
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
        }
    }

    private func compactNudge(_ seconds: Double) -> some View {
        Button { playback.nudge(seconds) } label: {
            Label("1 秒", systemImage: seconds < 0 ? "gobackward" : "goforward")
                .font(.body.weight(.medium)).fixedSize()
                .frame(maxWidth: .infinity, minHeight: 44)
                .contentShape(Rectangle())
        }
        .accessibilityLabel(seconds < 0 ? "中文抢先，后退1秒" : "中文落后，前进1秒")
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
            .accessibilityLabel("播放进度")
            .accessibilityValue("\(PlaybackTime.format(playback.position))，总长 \(PlaybackTime.format(playback.duration))。\(statusLabel)")
            .accessibilityIdentifier("playback-progress")
            if typeSize.isAccessibilitySize {
                Text(statusLabel).font(.caption).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private func nudgeButton(_ seconds: Double) -> some View {
        Button { playback.nudge(seconds) } label: {
            VStack(spacing: 5) {
                Image(systemName: seconds < 0 ? "gobackward" : "goforward")
                    .font(.system(size: 24, weight: .medium))
                    .accessibilityHidden(true)
                Text(seconds < 0 ? "后退 1 秒" : "前进 1 秒")
                    .font(.caption.weight(.medium))
                    .fixedSize(horizontal: false, vertical: true)
            }
            .frame(maxWidth: .infinity, minHeight: 58)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain).foregroundStyle(.primary)
        .accessibilityLabel(seconds < 0 ? "中文抢先，后退1秒" : "中文落后，前进1秒")
        .accessibilityHint("调整中文音频的位置")
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
        Button(action: action) { Label("当前句", systemImage: "text.line.first.and.arrowtriangle.forward")
                .frame(minWidth: 44, minHeight: 44).contentShape(Rectangle()) }
            .accessibilityLabel("回到当前句")
            .accessibilityIdentifier("current-cue")
    }

    private func precisionButton(_ action: @escaping () -> Void) -> some View {
        Button(action: action) { Label("定位 / 精调", systemImage: "slider.horizontal.3")
                .frame(minWidth: 44, minHeight: 44).contentShape(Rectangle()) }
            .disabled(!playback.isReady || isPreparing)
            .accessibilityIdentifier("precision-controls")
    }

    private func undoButton(_ previous: Double) -> some View {
        Button { playback.undo() } label: {
            Label("撤销", systemImage: "arrow.uturn.backward")
                .frame(minWidth: 44, minHeight: 44).contentShape(Rectangle())
        }
        .accessibilityLabel("撤销跳转，返回 \(PlaybackTime.format(previous))")
        .accessibilityIdentifier("undo-seek")
        .disabled(!playback.isReady || isPreparing)
    }

    private var statusLabel: String { isPreparing ? "正在准备音频…" : playback.message }
    private var shortPlayLabel: String {
        if playback.isPlaying || playback.isWaiting { return "暂停" }
        return playback.resumePosition == nil ? "播放" : "继续"
    }
    private var playLabel: String {
        if playback.isPlaying || playback.isWaiting { return "暂停播放" }
        return playback.resumePosition == nil ? "开始播放" : "继续收听"
    }
}
