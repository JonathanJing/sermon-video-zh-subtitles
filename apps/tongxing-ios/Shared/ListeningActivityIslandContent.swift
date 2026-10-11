#if os(iOS)
import SwiftUI

/// Shared production content for the system widget and native state previews.
/// The system still owns Dynamic Island region placement and presentation.
struct ListeningActivityIslandDetails: View {
    let state: ListeningActivityAttributes.ContentState
    let isStale: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            if state.alignmentPhase != nil {
                Text(verbatim: state.statusText(isStale: isStale))
                    .font(.headline).foregroundStyle(.green)
            }
            Text(verbatim: state.title)
                .font(state.alignmentPhase == nil ? .headline : .caption).lineLimit(2)
            HStack {
                Text(verbatim: state.speaker).lineLimit(1)
                Spacer(minLength: 8)
                Text(verbatim: state.statusText(isStale: isStale))
            }
            .font(.caption)
            .foregroundStyle(.secondary)
        }
        .padding(.top, 4)
    }
}

struct ListeningActivitySymbol: View {
    let state: ListeningActivityAttributes.ContentState
    let isStale: Bool

    var body: some View {
        Image(systemName: isStale ? "arrow.clockwise" : state.alignmentPhase?.symbolName ?? (state.isWaiting ? "hourglass" : state.isPlaying ? "headphones" : "pause.fill"))
            .foregroundStyle(.green)
            .accessibilityLabel(state.statusText(isStale: isStale))
    }
}

struct ListeningActivityElapsed: View {
    let state: ListeningActivityAttributes.ContentState
    let isStale: Bool

    var body: some View {
        if state.isPlaying && !state.isWaiting && !isStale {
            Text(timerInterval: state.timerInterval, countsDown: false)
                .monospacedDigit()
                .multilineTextAlignment(.trailing)
        } else {
            Text(verbatim: ListeningActivityAttributes.ContentState.timeLabel(state.position))
                .monospacedDigit()
        }
    }
}
#endif
