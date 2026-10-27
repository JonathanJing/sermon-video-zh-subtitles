#if DEBUG
import SwiftUI
import TongxingCore

/// Synthetic, explicitly opt-in UI fixture. No church text, published identity,
/// or access permission is inferred from this preview.
struct WeeklyGuidePreview: View {
    @ObservedObject var model: AppModel
    @ObservedObject var playback: PlaybackController
    @Environment(\.dismiss) private var dismiss
    @Environment(\.dynamicTypeSize) private var typeSize
    @State private var showingMore = false
    @State private var moreFrame: CGRect = .null
    @State private var showingWeeks = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @AccessibilityFocusState private var focusedSection: String?

    private let sections: [GuidePreviewSection] = [
        .init(id: "scripture", title: "经文", subtitle: "阅读本周经文", symbol: "book", body: "示意内容：这里展示本周经文。实际经文与译本须经许可及核对。"),
        .init(id: "background", title: "理解本周", subtitle: "背景与图解", symbol: "text.book.closed", body: "示意内容：这里展示手册提供的背景和图解。"),
        .init(id: "notes", title: "讲道笔记", subtitle: "阅读手册中的讲道笔记", symbol: "pencil", body: "示意内容：这里展示手册中的讲道笔记。"),
        .init(id: "group", title: "生活小组", subtitle: "一起阅读与讨论", symbol: "person.2", body: "示意问题：请分享你在本周学习中的一个观察。")
    ]

    var body: some View {
        GeometryReader { geometry in
        let controlRegion = dockRegion(in: geometry)
        NavigationStack {
            ToolbarVerticalEdgeReader { verticalEdge in
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: 24) {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("合成预览 · 非教会手册").font(.caption).foregroundStyle(.secondary)
                            Text("第 7 周 · 示例讲道").font(.largeTitle.bold())
                            Text("示例经文范围").font(.title3).foregroundStyle(.secondary)
                        }
                        VStack(spacing: 0) {
                            ForEach(sections) { section in
                                Button {
                                    withAnimation(reduceMotion ? nil : .easeInOut) {
                                        proxy.scrollTo(section.id, anchor: .top)
                                    }
                                    focusedSection = section.id
                                } label: {
                                    HStack(spacing: 14) {
                                        Image(systemName: section.symbol)
                                            .font(.title3).foregroundStyle(Brand.accent)
                                            .frame(width: 42, height: 42)
                                            .background(Brand.accent.opacity(0.10), in: Circle())
                                        VStack(alignment: .leading, spacing: 4) {
                                            Text(section.title).font(.headline).foregroundStyle(Brand.accent)
                                            Text(section.subtitle).font(.subheadline).foregroundStyle(.secondary)
                                        }
                                        Spacer(minLength: 8)
                                        Image(systemName: "chevron.right").foregroundStyle(.secondary)
                                    }
                                    .padding(.horizontal, 16).padding(.vertical, 12)
                                    .frame(minHeight: 60).contentShape(Rectangle())
                                }
                                .buttonStyle(.plain)
                                .accessibilityIdentifier("guide-section-\(section.id)")
                                if section.id != sections.last?.id { Divider().padding(.leading, 72) }
                            }
                        }
                        .background(Brand.surface, in: RoundedRectangle(cornerRadius: 20))
                        ForEach(sections) { section in
                            VStack(alignment: .leading, spacing: 12) {
                                Text(section.title).font(.title2.bold()).accessibilityAddTraits(.isHeader)
                                    .accessibilityFocused($focusedSection, equals: section.id)
                                if section.id == "group" {
                                    Text("祷告 · 靠近 · 向下看 · 向外看 · 向内看")
                                        .font(.subheadline).foregroundStyle(.secondary)
                                }
                                Text(section.body).font(.body).lineSpacing(6)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .id(section.id)
                            .accessibilityIdentifier("guide-content-\(section.id)")
                        }
                        Text("测试样本，不包含教会原文或正式译文。")
                            .font(.footnote).foregroundStyle(.secondary)
                        Button("返回证道") { dismiss() }
                            .buttonStyle(.bordered)
                            .frame(minHeight: 44)
                            .accessibilityIdentifier("guide-close-bottom")
                    }
                    .padding(20).frame(maxWidth: 680, alignment: .leading)
                    .frame(maxWidth: .infinity)
                }
                .accessibilityIdentifier("guide-scroll")
                .background(Brand.background)
            }
            .navigationTitle(typeSize.isAccessibilitySize ? "手册" : "本周研读手册")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("返回证道") { dismiss() }.accessibilityIdentifier("guide-close")
                }
                ToolbarItem(placement: .primaryAction) {
                    Button("全部周次") { showingWeeks = true }.accessibilityIdentifier("guide-weeks")
                }
                #if os(iOS) && canImport(SwiftUI, _version: 8.0.85)
                if #available(iOS 27.1, macOS 27.1, *), verticalEdge != nil {
                    ToolbarItem(placement: .primaryAction) {
                        guideDock(placement: .trailing, inSystemBar: true)
                    }
                    .axisBehavior(.verticalPreferred)
                    .visibilityPriority(.high)
                }
                #endif
            }
            .sheet(isPresented: $showingWeeks) {
                NavigationStack {
                    List { Text("第 7 周 · 示例讲道"); Text("仅供界面测试，尚无正式手册目录。") }
                        .navigationTitle("全部周次")
                        .toolbar { Button("完成") { showingWeeks = false } }
                }
                .presentationDetents([.medium, .large])
            }
            .listeningPlayerDock(atTrailingEdge: false, inSystemBar: verticalEdge != nil) {
                if verticalEdge == nil {
                    HStack(spacing: 0) {
                        Color.clear.frame(width: controlRegion.minX, height: 0)
                        guideDock(placement: .bottom).frame(width: controlRegion.width)
                        Spacer(minLength: 0)
                    }
                }
            }
            }
        }
        .overlay {
            PlaybackMorePanelOverlay(isPresented: $showingMore, buttonFrame: moreFrame, placement: morePlacement) { width in
                PlaybackMoreControls(playback: playback, isPreparing: false, alignmentModel: model,
                                     onClose: { showingMore = false }, width: width)
            }
        }
        }
    }

    private func dockRegion(in geometry: GeometryProxy) -> CGRect {
        let bounds = CGRect(origin: .zero, size: geometry.size)
        #if os(iOS) && canImport(SwiftUI, _version: 8.0.85)
        if #available(iOS 27.1, macOS 27.1, *) {
            let divisions = geometry.reservedRegions(kind: .division).filter(\.isActive).map(\.frame)
            return PlaybackControlRegion.resolve(in: bounds, excluding: divisions)
        }
        #endif
        return bounds
    }

    @State private var morePlacement: PlaybackDockPlacement = .bottom
    private func guideDock(placement: PlaybackDockPlacement, inSystemBar: Bool = false) -> some View {
        PlaybackDock(playback: playback, alignmentModel: model, placement: placement, inSystemBar: inSystemBar,
            onMoreTap: { morePlacement = placement; showingMore = true },
            onMoreDismiss: { showingMore = false }, onMoreFrameChange: { moreFrame = $0 })
    }
}

private struct GuidePreviewSection: Identifiable {
    let id: String
    let title: String
    let subtitle: String
    let symbol: String
    let body: String
}
#endif
