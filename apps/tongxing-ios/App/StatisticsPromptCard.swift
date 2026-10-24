import SwiftUI

/// Inline one-time request to share anonymous statistics. It never blocks
/// listening, and both answers have equal weight; the Privacy switch stays
/// the place to change the choice later.
struct StatisticsPromptCard: View {
    @ObservedObject var playback: PlaybackController
    @ObservedObject private var localization = AppLocalization.shared

    var body: some View {
        if playback.statisticsPromptVisible {
            VStack(alignment: .leading, spacing: 10) {
                Text(localization.text("帮助改进同行？")).font(.headline)
                Text(localization.text("开启匿名使用统计后，我们能知道哪些语言和讲道有人在听。只上传界面语言、收听语言和收听时长；不含姓名、邮箱或广告标识，不跨日追踪。可随时在“隐私与支持”中关闭。"))
                    .font(.subheadline)
                    .fixedSize(horizontal: false, vertical: true)
                HStack(spacing: 12) {
                    Button(localization.text("开启统计")) { playback.setStatisticsEnabled(true) }
                        .accessibilityIdentifier("statistics-prompt-enable")
                    Button(localization.text("暂不")) { playback.declineStatisticsPrompt() }
                        .accessibilityIdentifier("statistics-prompt-decline")
                }
                .buttonStyle(.bordered)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(12).background(Brand.accent.opacity(0.10), in: RoundedRectangle(cornerRadius: 20))
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("statistics-prompt")
        }
    }
}
