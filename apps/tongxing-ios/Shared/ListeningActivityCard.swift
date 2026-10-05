#if os(iOS)
import SwiftUI

struct ListeningActivityCard: View {
    let state: ListeningActivityAttributes.ContentState
    let isStale: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .top, spacing: 10) {
                ListeningActivitySymbol(state: state, isStale: isStale)
                    .font(.title2)
                VStack(alignment: .leading, spacing: 3) {
                    Text(verbatim: state.title).font(.headline).lineLimit(2)
                    Text(verbatim: state.speaker).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                }
                Spacer(minLength: 0)
            }
            HStack {
                if state.alignmentPhase == nil && !isStale && hasSubtitle {
                    HStack(spacing: 5) {
                        Text(verbatim: state.subtitleSnapshotLabel)
                        Text(state.sampledAt, style: .time)
                    }
                    .font(.caption2)
                    .lineLimit(1)
                } else {
                    Text(verbatim: state.statusText(isStale: isStale)).font(.caption)
                }
                Spacer(minLength: 8)
                ListeningActivityElapsed(state: state, isStale: isStale)
                Text(verbatim: "/ \(ListeningActivityAttributes.ContentState.timeLabel(state.duration))")
                    .foregroundStyle(.secondary)
            }
            .font(.subheadline.monospacedDigit())
            // The system media card owns playback controls. This activity's
            // distinct Lock Screen content is the last submitted subtitle snapshot.
            if state.alignmentPhase == nil {
                if isStale {
                    if hasSubtitle {
                        Text(verbatim: state.subtitleStaleMessage)
                            .font(.caption).foregroundStyle(.secondary)
                    }
                } else if let chinese = state.chineseSubtitle, !chinese.isEmpty {
                    subtitle(chinese, label: "中文")
                }
                if !isStale, let english = state.englishSubtitle, !english.isEmpty {
                    subtitle(english, label: "EN")
                }
            }
            if state.isPlaying && !state.isWaiting && !isStale {
                ProgressView(timerInterval: state.timerInterval, countsDown: false)
                    .labelsHidden()
            } else {
                ProgressView(value: state.position, total: state.duration)
            }
        }
        .tint(.green)
        .foregroundStyle(.white)
    }

    private var hasSubtitle: Bool {
        state.chineseSubtitle?.isEmpty == false || state.englishSubtitle?.isEmpty == false
    }

    private func subtitle(_ text: String, label: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Text(verbatim: label).font(.caption2.bold()).foregroundStyle(.secondary)
            Text(verbatim: text).font(.subheadline).lineLimit(2)
        }
        .accessibilityElement(children: .combine)
    }

}

#endif
