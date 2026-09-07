#if os(iOS)
import ActivityKit
import SwiftUI
import WidgetKit

@main
struct ListeningActivityBundle: WidgetBundle {
    var body: some Widget { ListeningActivityWidget() }
}

struct ListeningActivityWidget: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: ListeningActivityAttributes.self) { context in
            ListeningActivityCard(state: context.state, isStale: context.isStale)
                .padding(16)
                .activityBackgroundTint(.black)
                .activitySystemActionForegroundColor(.white)
                .widgetURL(ListeningActivityAttributes.widgetURL)
        } dynamicIsland: { context in
            DynamicIsland {
                DynamicIslandExpandedRegion(.leading) {
                    ListeningActivitySymbol(state: context.state, isStale: context.isStale)
                        .font(.title3)
                }
                DynamicIslandExpandedRegion(.trailing) {
                    ListeningActivityElapsed(state: context.state, isStale: context.isStale)
                        .font(.headline.monospacedDigit())
                }
                DynamicIslandExpandedRegion(.bottom) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(verbatim: context.state.title)
                            .font(.headline).lineLimit(2)
                        HStack {
                            Text(verbatim: context.state.speaker).lineLimit(1)
                            Spacer(minLength: 8)
                            Text(verbatim: context.state.statusText(isStale: context.isStale))
                        }
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    }
                    .padding(.top, 4)
                }
            } compactLeading: {
                ListeningActivitySymbol(state: context.state, isStale: context.isStale)
            } compactTrailing: {
                ListeningActivityElapsed(state: context.state, isStale: context.isStale)
                    .font(.caption.monospacedDigit())
                    .frame(width: context.state.duration >= 3600 ? 62 : 48)
            } minimal: {
                ListeningActivitySymbol(state: context.state, isStale: context.isStale)
            }
            .widgetURL(ListeningActivityAttributes.widgetURL)
            .keylineTint(.green)
        }
    }
}

private struct ListeningActivityCard: View {
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
                Text(verbatim: state.statusText(isStale: isStale)).font(.caption)
                Spacer(minLength: 8)
                ListeningActivityElapsed(state: state, isStale: isStale)
                Text(verbatim: "/ \(ListeningActivityAttributes.ContentState.timeLabel(state.duration))")
                    .foregroundStyle(.secondary)
            }
            .font(.subheadline.monospacedDigit())
            if state.isPlaying && !isStale {
                ProgressView(timerInterval: state.timerInterval, countsDown: false)
                    .labelsHidden()
            } else {
                ProgressView(value: state.position, total: state.duration)
            }
        }
        .tint(.green)
        .foregroundStyle(.white)
    }
}

private struct ListeningActivitySymbol: View {
    let state: ListeningActivityAttributes.ContentState
    let isStale: Bool

    var body: some View {
        Image(systemName: isStale ? "arrow.clockwise" : state.isWaiting ? "hourglass" : state.isPlaying ? "headphones" : "pause.fill")
            .foregroundStyle(.green)
            .accessibilityLabel(state.statusText(isStale: isStale))
    }
}

private struct ListeningActivityElapsed: View {
    let state: ListeningActivityAttributes.ContentState
    let isStale: Bool

    var body: some View {
        if state.isPlaying && !isStale {
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
