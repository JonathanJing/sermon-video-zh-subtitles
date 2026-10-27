#if DEBUG || TONGXING_GUIDE_PREVIEW
import SwiftUI
import TongxingCore

/// The guide is independent of the sermon release package and is only shown
/// for an explicitly mapped sermon and supported language.
struct WeeklyGuidePreview: View {
    @ObservedObject var model: AppModel
    @ObservedObject var playback: PlaybackController
    @Environment(\.dismiss) private var dismiss
    @Environment(\.dynamicTypeSize) private var typeSize
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var showingMore = false
    @State private var moreFrame: CGRect = .null
    @AccessibilityFocusState private var focusedSection: String?

    private var guide: WeeklyGuide? {
        #if DEBUG
        if UITestLaunch.isEnabled && ProcessInfo.processInfo.arguments.contains("--ui-testing-study-guide"),
           model.selectedPageID == "ui-test-week" {
            return WeeklyGuide(id: "ui-test-week", week: 7, title: "测试讲道", scripture: "测试经文",
                sections: [.init(id: "group", title: "生活小组", subtitle: "测试目录", symbol: "person.2",
                                 body: "测试用讨论内容，不代表教会手册。")])
        }
        #endif
        return WeeklyGuideRepository.load(pageID: model.selectedPageID, locale: model.selectedContentLocale)
    }

    var body: some View {
        GeometryReader { geometry in
        let controlRegion = dockRegion(in: geometry)
        NavigationStack {
            ToolbarVerticalEdgeReader { verticalEdge in
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: 24) {
                        if let guide {
                            VStack(alignment: .leading, spacing: 8) {
                                Text("中文机器翻译 · 未经人工审校").font(.caption).foregroundStyle(.secondary)
                                Text("第 \(guide.week) 周 · \(guide.title)").font(.largeTitle.bold())
                                Text(guide.scripture).font(.title3).foregroundStyle(.secondary)
                                Text("根据 Mariners Church《Revelation Series Guide》翻译；非教会官方中文译本。原稿部分经文仅标注章节范围。")
                                    .font(.footnote).foregroundStyle(.secondary)
                                Link("查看教会原手册", destination: URL(string: "https://www.flipsnack.com/57AF6AEEFB5/revelation-series-guide")!)
                                    .font(.footnote)
                            }
                            VStack(spacing: 0) {
                                ForEach(guide.sections) { section in
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
                                    if section.id != guide.sections.last?.id { Divider().padding(.leading, 72) }
                                }
                            }
                            .background(Brand.surface, in: RoundedRectangle(cornerRadius: 20))
                            ForEach(guide.sections) { section in
                                VStack(alignment: .leading, spacing: 12) {
                                    Text(section.title).font(.title2.bold()).accessibilityAddTraits(.isHeader)
                                        .accessibilityFocused($focusedSection, equals: section.id)
                                    Text(section.body).font(.body).lineSpacing(6)
                                        .fixedSize(horizontal: false, vertical: true)
                                }
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .id(section.id)
                                .accessibilityIdentifier("guide-content-\(section.id)")
                            }
                        } else {
                            ContentUnavailableView("本周研读手册尚不可用", systemImage: "book.closed",
                                description: Text("当前讲道或内容语言暂无对应手册。"))
                                .accessibilityIdentifier("guide-unavailable")
                        }
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

#endif
