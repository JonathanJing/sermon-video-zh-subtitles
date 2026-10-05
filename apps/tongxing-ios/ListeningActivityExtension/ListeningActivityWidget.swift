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
                    ListeningActivityIslandDetails(state: context.state, isStale: context.isStale)
                }
            } compactLeading: {
                ListeningActivitySymbol(state: context.state, isStale: context.isStale)
            } compactTrailing: {
                Group {
                    if let phase = context.state.alignmentPhase, !context.isStale {
                        Text(verbatim: phase.compactText(english: context.state.usesEnglish))
                    } else {
                        Text(verbatim: context.isStale ? "—" : context.state.compactStatusText)
                    }
                }
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

#endif
