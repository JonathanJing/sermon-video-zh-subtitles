#if DEBUG || TONGXING_GUIDE_PREVIEW
import SwiftUI
import TongxingCore
import UIKit

/// The guide is independent of the sermon release package and is only shown
/// for an explicitly mapped sermon and supported language.
struct WeeklyGuidePreview: View {
    @ObservedObject var model: AppModel
    @ObservedObject var playback: PlaybackController
    var embedded = false
    @ObservedObject private var localization = AppLocalization.shared
    @Environment(\.dismiss) private var dismiss
    @Environment(\.dynamicTypeSize) private var typeSize
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var showingMore = false
    @AccessibilityFocusState private var focusedSection: String?
    @State private var remoteGuide: WeeklyGuide?
    @State private var remoteSelection: WeeklyGuideSelection?
    @State private var loadingSelection: WeeklyGuideSelection?
    @State private var expandedImage: WeeklyGuideExpandedImage?

    private var selection: WeeklyGuideSelection {
        let locale = model.selectedContentLocale
        if let week = model.selectedWeek {
            guard let legacy = WeeklyGuideRepository.legacyIdentity(week: week) else {
                return WeeklyGuideSelection(pageID: week.id, locale: locale)
            }
            return WeeklyGuideSelection(pageID: week.id, locale: locale, legacy: legacy)
        }
        guard let page = model.selectedMultilingualPage, page.id == model.selectedPageID,
              let target = page.targets[locale], let source = try? target.sourceBinding(in: page) else {
            return WeeklyGuideSelection(pageID: model.selectedPageID, locale: locale)
        }
        return WeeklyGuideSelection(pageID: page.id, locale: locale, editionId: source.editionId,
                                    sourceIdentitySha256: source.sourceIdentitySha256,
                                    releasePackageJsonSha256: target.releasePackageJsonSha256)
    }

    private var guide: WeeklyGuide? {
        #if DEBUG
        if UITestLaunch.isEnabled && ProcessInfo.processInfo.arguments.contains("--ui-testing-study-guide"),
           model.selectedPageID == "ui-test-week" {
            return WeeklyGuide(id: "ui-test-week", week: 7, title: "测试讲道", scripture: "测试经文",
                sections: [.init(id: "group", title: "生活小组", subtitle: "测试目录", symbol: "person.2",
                                 body: "测试用讨论内容，不代表教会手册。")])
        }
        #endif
        return WeeklyGuideRepository.matchingRemote(remoteGuide, resultFor: remoteSelection, current: selection)
    }

    private func refreshGuide(for requested: WeeklyGuideSelection) async {
        loadingSelection = requested
        remoteGuide = nil
        remoteSelection = nil
        let origin = model.mediaOrigin
        #if DEBUG
        if UITestLaunch.isEnabled && !ProcessInfo.processInfo.arguments.contains("--ui-testing-remote-guide") {
            remoteSelection = requested
            loadingSelection = nil
            return
        }
        #endif
        let result = await WeeklyGuideRepository.loadRemote(selection: requested, origin: origin)
        guard !Task.isCancelled, selection == requested else { return }
        remoteGuide = WeeklyGuideRepository.resolvedGuide(result, selection: requested, origin: origin,
                                                          ledger: WeeklyGuideDenyLedger()) {
            WeeklyGuideRepository.loadBundled(selection: requested, origin: origin)
        }
        remoteSelection = requested
        loadingSelection = nil
    }

    private var translationNotice: String {
        switch selection.locale {
        case "ko": return localization.text("韩语机器翻译 · 未经人工审校")
        case "es": return localization.text("西语机器翻译 · 未经人工审校")
        default: return localization.text("中文机器翻译 · 未经人工审校")
        }
    }

    var body: some View {
        Group {
            if embedded {
                guideReader.frame(maxHeight: .infinity, alignment: .top)
            } else {
                standaloneReader
            }
        }
        .task(id: selection) {
            await refreshGuide(for: selection)
        }
        .sheet(item: $expandedImage) { image in
            WeeklyGuideImageSheet(image: image, closeLabel: localization.text("关闭"),
                                  zoomInLabel: localization.text("放大图片"),
                                  zoomOutLabel: localization.text("缩小图片"))
        }
    }

    private var standaloneReader: some View {
        GeometryReader { geometry in
        let controlRegion = dockRegion(in: geometry)
        NavigationStack {
            ToolbarVerticalEdgeReader { verticalEdge in
            guideReader
            .navigationTitle(localization.text(typeSize.isAccessibilitySize || localization.language != .simplifiedChinese ? "手册" : "本周研读手册"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(localization.text("返回证道")) { dismiss() }.accessibilityIdentifier("guide-close")
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
        }
    }

    private var guideReader: some View {
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: 24) {
                        if let guide {
                            VStack(alignment: .leading, spacing: 8) {
                                Text(translationNotice).font(.caption).foregroundStyle(.secondary)
                                Text(localization.text("第 {week} 周 · {title}", ["week": String(guide.week), "title": guide.title])).font(embedded ? .title2.bold() : .largeTitle.bold())
                                Text(guide.scripture).font(.title3).foregroundStyle(.secondary)
                                Text(localization.text("根据 Mariners Church《Revelation Series Guide》翻译；非教会官方译本。部分经文在此仅标注章节范围。"))
                                    .font(.footnote).foregroundStyle(.secondary)
                                Link(localization.text("查看教会原手册"), destination: URL(string: "https://www.flipsnack.com/57AF6AEEFB5/revelation-series-guide")!)
                                    .font(.footnote)
                            }
                            if !embedded {
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
                            }
                            ForEach(guide.sections) { section in
                                VStack(alignment: .leading, spacing: 12) {
                                    Text(section.title).font(.title2.bold()).accessibilityAddTraits(.isHeader)
                                        .accessibilityFocused($focusedSection, equals: section.id)
                                    if let blocks = displayableBlocks(section) {
                                        ForEach(blocks.indices, id: \.self) { index in
                                            if !isRepeatedSectionHeading(blocks[index], at: index, section: section) {
                                                guideBlock(blocks[index])
                                            }
                                        }
                                    } else {
                                        guideParagraph(section.body)
                                    }
                                }
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .id(section.id)
                                .accessibilityIdentifier("guide-content-\(section.id)")
                            }
                        } else if remoteSelection != selection || loadingSelection == selection {
                            ProgressView(localization.text("正在加载研读手册…"))
                                .accessibilityIdentifier("guide-loading")
                        } else {
                            ContentUnavailableView(localization.text("本周研读手册尚不可用"), systemImage: "book.closed",
                                description: Text(localization.text("当前讲道或内容语言暂无对应手册。")))
                                .accessibilityIdentifier("guide-unavailable")
                        }
                        if !embedded {
                        Button(localization.text("返回证道")) { dismiss() }
                            .buttonStyle(.bordered)
                            .frame(minHeight: 44)
                            .accessibilityIdentifier("guide-close-bottom")
                        }
                    }
                    .padding(20).frame(maxWidth: 680, alignment: .leading)
                    .frame(maxWidth: .infinity)
                }
                .accessibilityIdentifier("guide-scroll")
                .background(Brand.background)
                .toolbar {
                    if embedded {
                        ToolbarItem(placement: .topBarLeading) {
                            embeddedHeader(proxy: proxy)
                        }
                    }
                }
            }
    }

    private func embeddedHeader(proxy: ScrollViewProxy) -> some View {
        Group {
            if let guide {
                Menu {
                    ForEach(guide.sections) { section in
                        Button(section.title) {
                            withAnimation(reduceMotion ? nil : .easeInOut) {
                                proxy.scrollTo(section.id, anchor: .top)
                            }
                            focusedSection = section.id
                        }
                        .accessibilityIdentifier("guide-section-\(section.id)")
                    }
                } label: {
                    HStack(spacing: 8) {
                        Image(systemName: "book")
                        Text(localization.text("本周研读手册"))
                    }
                    .font(.headline)
                    .fixedSize(horizontal: true, vertical: false)
                }
                .accessibilityLabel(localization.text("本周研读手册"))
                .accessibilityHint(localization.text("手册目录"))
                .accessibilityIdentifier("guide-chapter-menu")
            } else {
                HStack(spacing: 8) {
                    Image(systemName: "book")
                    Text(localization.text("本周研读手册"))
                }
                .font(.headline)
                .fixedSize(horizontal: true, vertical: false)
                .accessibilityAddTraits(.isHeader)
            }
        }
    }

    private func guideParagraph(_ text: String) -> some View {
        Text(text).font(.body).lineSpacing(6)
            .frame(maxWidth: .infinity, alignment: .leading)
            .fixedSize(horizontal: false, vertical: true)
    }

    private func displayableBlocks(_ section: WeeklyGuideSection) -> [WeeklyGuideBlock]? {
        guard let blocks = section.blocks else { return nil }
        for block in blocks {
            if case .image(let assetID, _, _) = block {
                guard let data = WeeklyGuideImageAssets.data(for: assetID), UIImage(data: data) != nil else {
                    return nil
                }
            }
        }
        return blocks
    }

    private func isRepeatedSectionHeading(_ block: WeeklyGuideBlock, at index: Int,
                                          section: WeeklyGuideSection) -> Bool {
        guard index == 0, case .paragraph(let text) = block else { return false }
        return text.trimmingCharacters(in: .whitespacesAndNewlines)
            == section.title.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    @ViewBuilder
    private func guideBlock(_ block: WeeklyGuideBlock) -> some View {
        switch block {
        case .paragraph(let text):
            guideParagraph(text)
        case .table(let title, let columns, let rows, let footnote):
            VStack(alignment: .leading, spacing: 12) {
                if !title.isEmpty {
                    Text(title).font(.headline).accessibilityAddTraits(.isHeader)
                }
                // Each source row remains one card so that narrow screens and
                // VoiceOver preserve the relationship between its cells.
                ForEach(rows.indices, id: \.self) { row in
                    VStack(alignment: .leading, spacing: 12) {
                        ForEach(columns.indices, id: \.self) { column in
                            VStack(alignment: .leading, spacing: 3) {
                                if !columns[column].trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                                    Text(columns[column]).font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                                }
                                Text(rows[row][column]).font(.body)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }
                    .padding(14)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Brand.surface, in: RoundedRectangle(cornerRadius: 14))
                    .accessibilityElement(children: .combine)
                }
                if let footnote, !footnote.isEmpty {
                    Text(footnote).font(.footnote).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        case .list(let title, let items):
            VStack(alignment: .leading, spacing: 8) {
                if !title.isEmpty {
                    Text(title).font(.headline).accessibilityAddTraits(.isHeader)
                }
                ForEach(items.indices, id: \.self) { index in
                    HStack(alignment: .top, spacing: 8) {
                        Text("•").accessibilityHidden(true)
                        guideParagraph(items[index])
                    }
                }
            }
        case .flow(let title, let items):
            VStack(alignment: .leading, spacing: 8) {
                if !title.isEmpty {
                    Text(title).font(.headline).accessibilityAddTraits(.isHeader)
                }
                ForEach(items.indices, id: \.self) { index in
                    if index > 0 {
                        Image(systemName: "arrow.down").foregroundStyle(.secondary)
                            .accessibilityHidden(true)
                    }
                    guideParagraph(items[index])
                }
            }
        case .image(let assetID, let alt, let caption):
            if let data = WeeklyGuideImageAssets.data(for: assetID), let image = UIImage(data: data) {
                VStack(alignment: .leading, spacing: 8) {
                    Button {
                        expandedImage = WeeklyGuideExpandedImage(id: assetID, image: image, alt: alt, caption: caption)
                    } label: {
                        Image(uiImage: image).resizable().scaledToFit()
                            .frame(maxWidth: .infinity)
                            .clipShape(RoundedRectangle(cornerRadius: 12))
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(Text(alt))
                    .accessibilityHint(Text(localization.text("点按可放大图片")))
                    .accessibilityIdentifier("guide-image-\(assetID)")
                    if !caption.isEmpty {
                        Text(caption).font(.footnote).foregroundStyle(.secondary)
                    }
                }
            }
        case .map(let title, let points, let caption, let attribution):
            VStack(alignment: .leading, spacing: 12) {
                Text(title).font(.headline).accessibilityAddTraits(.isHeader)
                // This is a local schematic: dots encode the validated
                // relative coordinates, not coastlines, routes or buildings.
                GeometryReader { geometry in
                    let minLat = points.map(\.latitude).min() ?? 0
                    let maxLat = points.map(\.latitude).max() ?? 1
                    let minLon = points.map(\.longitude).min() ?? 0
                    let maxLon = points.map(\.longitude).max() ?? 1
                    let usableWidth = max(1, geometry.size.width - 40)
                    let usableHeight = max(1, geometry.size.height - 40)
                    ZStack {
                        ForEach(points.indices, id: \.self) { index in
                            let point = points[index]
                            let x = 20 + usableWidth * CGFloat((point.longitude - minLon) / (maxLon - minLon))
                            let y = 20 + usableHeight * CGFloat((maxLat - point.latitude) / (maxLat - minLat))
                            ZStack {
                                Circle().fill(Brand.accent).frame(width: 26, height: 26)
                                Text("\(index + 1)").font(.caption2.bold()).foregroundStyle(.white)
                            }
                            .position(x: x, y: y)
                        }
                    }
                }
                .frame(height: 220)
                .background(Brand.surface, in: RoundedRectangle(cornerRadius: 14))
                .accessibilityHidden(true)
                ForEach(points.indices, id: \.self) { index in
                    Text("\(index + 1). \(points[index].name)")
                        .font(.body).fixedSize(horizontal: false, vertical: true)
                }
                Text(caption).font(.footnote).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                Text(attribution).font(.footnote).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                DisclosureGroup(localization.text("查看地图来源")) {
                    VStack(alignment: .leading, spacing: 12) {
                        ForEach(points.indices, id: \.self) { index in
                            VStack(alignment: .leading, spacing: 4) {
                                if let url = URL(string: points[index].sourceURL) {
                                    Link(points[index].name, destination: url).font(.footnote)
                                }
                                Text(points[index].credit).font(.footnote).foregroundStyle(.secondary)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.vertical, 8)
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

    private func guideDock(placement: PlaybackDockPlacement, inSystemBar: Bool = false) -> some View {
        PlaybackDock(playback: playback, alignmentModel: model, placement: placement, inSystemBar: inSystemBar,
            isMorePresented: $showingMore,
            moreContent: {
                AnyView(PlaybackMoreControls(playback: playback, isPreparing: false, alignmentModel: model,
                                             onClose: { showingMore = false }))
            })
    }
}

private struct WeeklyGuideExpandedImage: Identifiable {
    let id: String
    let image: UIImage
    let alt: String
    let caption: String
}

private struct WeeklyGuideImageSheet: View {
    let image: WeeklyGuideExpandedImage
    let closeLabel: String
    let zoomInLabel: String
    let zoomOutLabel: String
    @Environment(\.dismiss) private var dismiss
    @State private var scale: CGFloat = 1
    @GestureState private var magnification: CGFloat = 1

    var body: some View {
        NavigationStack {
            GeometryReader { geometry in
                ScrollView([.horizontal, .vertical]) {
                    Image(uiImage: image.image).resizable().scaledToFit()
                        .frame(width: max(1, geometry.size.width * min(4, max(1, scale * magnification))))
                        .accessibilityLabel(Text(image.alt))
                }
                .gesture(MagnificationGesture()
                    .updating($magnification) { value, state, _ in state = value }
                    .onEnded { value in scale = min(4, max(1, scale * value)) })
            }
            .background(Brand.background)
            .navigationTitle(image.caption)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(closeLabel) { dismiss() }
                }
                ToolbarItemGroup(placement: .primaryAction) {
                    Button { scale = max(1, scale / 1.5) } label: {
                        Image(systemName: "minus.magnifyingglass")
                    }
                    .accessibilityLabel(Text(zoomOutLabel))
                    .disabled(scale <= 1)
                    Button { scale = min(4, scale * 1.5) } label: {
                        Image(systemName: "plus.magnifyingglass")
                    }
                    .accessibilityLabel(Text(zoomInLabel))
                    .disabled(scale >= 4)
                }
            }
        }
    }
}

#endif
