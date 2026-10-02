import SwiftUI
import TongxingCore

/// Local English lookup uses only verified reference text and existing caption anchors.
/// It does not infer word-level timing or create another playback state.
struct EnglishLocateSheet: View {
    @ObservedObject var model: AppModel
    @ObservedObject private var playback: PlaybackController
    @ObservedObject private var localization = AppLocalization.shared
    @Environment(\.dismiss) private var dismiss
    @State private var query = ""
    @State private var locating = false
    @State private var seekFailed = false
    @FocusState private var searchFocused: Bool
    let onLocated: () -> Void

    init(model: AppModel, onLocated: @escaping () -> Void) {
        self.model = model
        self.playback = model.playback
        self.onLocated = onLocated
    }

    private struct Row: Identifiable {
        let id: String
        let english: String?
        let translated: String
        let start: Double
        let end: Double
        let audioStart: Double?
    }

    @State private var rows: [Row] = []

    private func rebuildRows() {
        rows = makeRows()
    }

    private func makeRows() -> [Row] {
        if let transcript = model.publishedTranscript {
            let captions = model.publishedCaptionsByID
            return transcript.fullText.map { cue in
                let caption = captions[cue.id]
                return Row(id: cue.id, english: cue.english, translated: cue.text,
                           start: caption?.start ?? cue.start, end: caption?.end ?? cue.end,
                           audioStart: caption?.start)
            }
        }
        guard let bilingual = model.bilingualRows else { return [] }
        return bilingual.rows.enumerated().map { index, row in
            Row(id: "legacy-\(index)", english: row.english, translated: row.cue.text,
                start: row.cue.start, end: row.cue.end, audioStart: row.cue.start)
        }
    }

    private var search: String { query.trimmingCharacters(in: .whitespacesAndNewlines) }
    private var results: [Row] {
        guard !search.isEmpty else { return rows }
        return rows.filter { $0.english?.range(of: search, options: [.caseInsensitive, .diacriticInsensitive]) != nil }
    }
    private var currentID: String? {
        rows.first { $0.start <= playback.position && playback.position < $0.end }?.id
            ?? rows.last { $0.start <= playback.position }?.id ?? rows.first?.id
    }
    private var canLocate: Bool { playback.isReady && !model.isPreparing && !model.isPreparingPublishedAudio }
    private var selectionKey: String {
        model.publishedTranscriptSelectionKey ?? model.selectedTrack?.id ?? ""
    }

    var body: some View {
        let current = currentID
        NavigationStack {
            VStack(spacing: 0) {
                TextField(localization.text("搜索刚听到的英文"), text: $query)
                    .textFieldStyle(.roundedBorder).autocorrectionDisabled()
                    .focused($searchFocused).submitLabel(.search)
                    .onSubmit { searchFocused = false }
                    .accessibilityIdentifier("english-locate-search")
                    .padding(.horizontal, 20).padding(.top, 12)
                ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 16) {
                        Text(localization.text("搜索刚听到的英文，再定位到段落开头。"))
                            .font(.subheadline).foregroundStyle(.secondary)
                        if seekFailed {
                            Text(localization.text("定位未完成，已保留上次确认的位置。"))
                                .font(.footnote).foregroundStyle(.secondary)
                        }
                        if !canLocate {
                            Label(localization.text("当前音频尚不可定位，可以先阅读和搜索。"), systemImage: "info.circle")
                                .font(.footnote).foregroundStyle(.secondary)
                                .accessibilityIdentifier("english-locate-unavailable")
                        }
                        if model.isLoadingPublishedTranscript {
                            ProgressView(localization.text("正在读取本周证道…"))
                        } else if let error = model.publishedTranscriptError {
                            Text(localization.text(error)).font(.footnote)
                            Button(localization.text("重新加载")) { Task { await model.loadSelectedPublishedTranscript() } }
                        } else if results.isEmpty {
                            Text(localization.text(rows.contains { $0.english != nil }
                                ? "没有找到这句英文，试试更短的关键词。" : "英文原文暂缺，保留中文显示。"))
                                .foregroundStyle(.secondary).accessibilityIdentifier("english-locate-empty")
                        }
                        ForEach(results) { row in
                            rowView(row, currentID: current).id(row.id)
                        }
                    }.padding(20).frame(maxWidth: 720).frame(maxWidth: .infinity)
                }
                .task(id: "\(selectionKey):\(rows.count)") {
                    // Scroll once on opening/reloading, never follow playback while reading.
                    await Task.yield()
                    if search.isEmpty, let currentID { proxy.scrollTo(currentID, anchor: .top) }
                }
            }
            }
            .background(Brand.background)
            .navigationTitle(localization.text("按英文找位置"))
            #if os(iOS)
            .navigationBarTitleDisplayMode(.inline)
            #endif
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button(localization.text("关闭")) { dismiss() }
                        .accessibilityIdentifier("english-locate-close")
                }
            }
        }
        .onChange(of: model.transcriptRowsRevision, initial: true) { _, _ in rebuildRows() }
        .environment(\.locale, localization.locale)
        .accessibilityIdentifier("english-locate-sheet")
    }

    private func rowView(_ row: Row, currentID: String?) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text(PlaybackTime.format(row.start)).font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                if row.id == currentID {
                    Text(localization.text("当前字幕")).font(.caption).foregroundStyle(Brand.accent)
                }
            }
            if let english = row.english {
                highlighted(english).font(.title3).lineSpacing(5)
                    .environment(\.locale, Locale(identifier: "en"))
                    .textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("locate-english-\(row.id)")
            }
            sourceText(row.translated, language: model.selectedWeek == nil ? model.selectedContentLocale : "zh-Hans").font(.body).foregroundStyle(.secondary)
                .textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
            if let start = row.audioStart {
                Button {
                    guard canLocate else { return }
                    locating = true
                    seekFailed = false
                    playback.jump(to: start) { succeeded in
                        locating = false
                        if succeeded { onLocated(); dismiss() }
                        else { seekFailed = true }
                    }
                } label: {
                    Label(localization.text("定位到这段"), systemImage: "arrow.right.to.line")
                        .frame(minHeight: 44)
                }.buttonStyle(.bordered).disabled(!canLocate || locating)
                    .accessibilityIdentifier("locate-segment-\(row.id)")
            } else {
                Text(localization.text("这段没有可用的音频时间，暂时只能阅读。"))
                    .font(.footnote).foregroundStyle(.secondary)
            }
        }.padding(16).frame(maxWidth: .infinity, alignment: .leading)
            .background(Brand.surface, in: RoundedRectangle(cornerRadius: 20))
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("locate-row-\(row.id)")
    }

    private func highlighted(_ text: String) -> Text {
        guard !search.isEmpty else { return sourceText(text, language: "en") }
        var output = AttributedString(text)
        output.languageIdentifier = "en"
        var remaining = text.startIndex..<text.endIndex
        while let match = text.range(of: search, options: [.caseInsensitive, .diacriticInsensitive], range: remaining) {
            if let range = Range(match, in: output) {
                output[range].font = .title3.bold()
                output[range].foregroundColor = Brand.accent
            }
            remaining = match.upperBound..<text.endIndex
        }
        return Text(output)
    }
}
