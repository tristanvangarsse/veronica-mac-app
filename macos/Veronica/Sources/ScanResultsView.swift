import AppKit
import QuickLookThumbnailing
import SwiftUI

struct ScanResultsView: View {
    @EnvironmentObject private var model: AppModel
    let onCleanup: () -> Void
    let canCleanup: Bool
    @State private var page: ScanResultsPage?
    @State private var category = "all"
    @State private var search = ""
    @State private var offset = 0
    @State private var selectedID: String?
    @State private var loading = false
    @State private var errorMessage: String?
    @State private var pendingDecision: ReviewItem?
    @State private var recordingDecision = false
    @State private var editingDate: ScanResultItem?
    @State private var dateSavedMessage: String?
    @State private var dateFocusRoot: String?
    @State private var dateFocusRelpath: String?

    private let categories = [
        ("all", "All files", "square.stack"),
        ("changes", "Ready to optimize", "sparkles"),
        ("review", "Need a decision", "questionmark.circle"),
        ("unchanged", "Unchanged", "checkmark.shield")
    ]
    private var selection: ScanResultItem? { page?.items.first { $0.id == selectedID } }
    private var requestID: String { "\(model.snapshot?.latestPlan?.planId ?? "")|\(category)|\(search)|\(offset)|\(dateFocusRoot ?? "")|\(dateFocusRelpath ?? "")" }

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 18) {
                Text("Review results").font(.title2.weight(.semibold))
                Spacer()
                TextField("Search files", text: $search)
                    .textFieldStyle(.roundedBorder).frame(width: 230)
                    .accessibilityIdentifier("veronica.searchResults")
            }.padding(20)
            Divider()
            HStack(spacing: 0) {
                sidebar
                Divider()
                fileList.frame(width: 360)
                Divider()
                details.frame(width: VeronicaWindowMetrics.size(reviewing: true).width - 562)
                    .frame(maxHeight: .infinity)
            }
            Divider()
            HStack(spacing: 12) {
                if loading { ProgressView().controlSize(.small) }
                Text(page.map { "\($0.counts["all", default: 0].formatted()) files in your scan" } ?? "Loading scan results…")
                    .font(.caption).foregroundStyle(.secondary)
                Spacer()
                Text("Savings are measured after conversion.").font(.caption).foregroundStyle(.secondary)
                Button("Smart cleanup", action: onCleanup)
                    .buttonStyle(VeronicaPrimaryButtonStyle())
                    .disabled(!canCleanup || loading || page == nil || recordingDecision)
                    .accessibilityIdentifier("veronica.reviewSmartCleanup")
            }.padding(16)
        }
        .sheet(item: $editingDate) { item in
            FileDateEditor(item: item) { relpath in
                selectedID = item.root + "|" + relpath
                category = "all"
                search = ""
                dateSavedMessage = "Date saved. This file’s scan result has been updated."
                offset = 0
                dateFocusRoot = item.root
                dateFocusRelpath = relpath
            }
            .environmentObject(model)
        }
        .task(id: requestID) {
            do {
                try await Task.sleep(nanoseconds: 250_000_000)
                await loadPage()
            } catch { }
        }
        .onChange(of: selectedID) { _ in dateSavedMessage = nil }
        .onChange(of: category) { _ in offset = 0 }
        .onChange(of: search) { _ in offset = 0 }
        .confirmationDialog("Review this file", isPresented: Binding(
            get: { pendingDecision != nil }, set: { if !$0 { pendingDecision = nil } }
        )) {
            if let item = pendingDecision {
                Button("Keep unchanged") { record(item, process: false) }
                if item.canProcessNormally {
                    Button("Apply normal rules and scan again") { record(item, process: true) }
                }
            }
            Button("Cancel", role: .cancel) { pendingDecision = nil }
        } message: {
            Text(pendingDecision?.explanation ?? "")
        }
    }

    private var sidebar: some View {
        VStack(alignment: .leading, spacing: 7) {
            Text("YOUR SCAN").font(.caption2.weight(.semibold)).foregroundStyle(.secondary).padding(.bottom, 10)
            ForEach(categories, id: \.0) { value, title, icon in
                Button { category = value } label: {
                    HStack(spacing: 8) {
                        Image(systemName: icon).frame(width: 18)
                        Text(title).lineLimit(2)
                        Spacer(minLength: 4)
                        Text(page?.counts[value].map { $0.formatted() } ?? "—").monospacedDigit()
                    }
                    .font(.callout).padding(.horizontal, 10).padding(.vertical, 11)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(category == value ? VeronicaTheme.accentFill : .clear, in: RoundedRectangle(cornerRadius: 11))
                    .foregroundStyle(category == value ? VeronicaTheme.accent : VeronicaTheme.ink)
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("veronica.filter.\(value)")
            }
            Spacer()
            Label("Replaced originals go to Trash.", systemImage: "trash")
                .font(.caption).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(16).frame(width: 200)
        .background(VeronicaTheme.subtleFill.opacity(0.5))
    }

    private var fileList: some View {
        VStack(spacing: 0) {
            if let errorMessage {
                VStack(spacing: 12) {
                    Image(systemName: "exclamationmark.triangle").font(.title)
                    Text(errorMessage).font(.callout).multilineTextAlignment(.center)
                    Button("Try again") { Task { await loadPage() } }
                }.padding(24).frame(maxHeight: .infinity)
            } else if let page, page.items.isEmpty {
                Text(search.isEmpty ? "No files in this group." : "No files match your search.")
                    .foregroundStyle(.secondary).frame(maxHeight: .infinity).padding(24)
            } else {
                List(selection: $selectedID) {
                    ForEach(page?.items ?? []) { item in
                        VStack(alignment: .leading, spacing: 5) {
                            Text(item.filename).font(.callout.weight(.medium)).lineLimit(1).truncationMode(.middle)
                            HStack {
                                Text(item.actionTitle).lineLimit(1)
                                Spacer()
                                Text(ByteCountFormatter.string(fromByteCount: item.sourceSize, countStyle: .file))
                            }.font(.caption).foregroundStyle(.secondary)
                            Text(URL(fileURLWithPath: item.root).lastPathComponent + "/" + item.relpath)
                                .font(.caption2).foregroundStyle(.tertiary).lineLimit(1).truncationMode(.middle)
                        }
                        .padding(.vertical, 7).tag(item.id)
                    }
                }
                .listStyle(.inset).scrollContentBackground(.hidden)
                .accessibilityIdentifier("veronica.resultFiles")
                .disabled(loading)
            }
            if let page, page.total > page.limit {
                Divider()
                HStack {
                    Button { offset = max(0, offset - page.limit) } label: { Image(systemName: "chevron.left") }
                        .disabled(offset == 0 || loading)
                        .accessibilityLabel("Previous files")
                    Spacer()
                    Text("\(offset + 1)–\(min(offset + page.items.count, page.total)) of \(page.total.formatted())")
                        .font(.caption).monospacedDigit()
                    Spacer()
                    Button { offset += page.limit } label: { Image(systemName: "chevron.right") }
                        .disabled(offset + page.limit >= page.total || loading)
                        .accessibilityLabel("Next files")
                }.padding(12)
            }
        }.frame(maxHeight: .infinity)
    }

    @ViewBuilder private var details: some View {
        if let item = selection {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    ResultThumbnail(url: item.fileURL)
                    VStack(alignment: .leading, spacing: 6) {
                        Text(item.filename).font(.title3.weight(.semibold)).textSelection(.enabled)
                        Text(item.fileURL.path).font(.caption).foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
                        Text(ByteCountFormatter.string(fromByteCount: item.sourceSize, countStyle: .file))
                            .font(.callout).foregroundStyle(.secondary)
                    }
                    VStack(alignment: .leading, spacing: 10) {
                        Label(item.actionTitle, systemImage: item.category == "review" ? "questionmark.circle" : item.category == "changes" ? "sparkles" : "checkmark.shield")
                            .font(.headline).foregroundStyle(VeronicaTheme.accent)
                        Text(item.detail).font(.callout).lineSpacing(4).textSelection(.enabled)
                    }
                    .padding(18).frame(maxWidth: .infinity, alignment: .leading)
                    .background(VeronicaTheme.accentFill, in: RoundedRectangle(cornerRadius: 18))
                    VStack(alignment: .leading, spacing: 10) {
                        Label("File date", systemImage: "calendar").font(.headline)
                        Text(item.embeddedDate ?? "No embedded date")
                            .font(.callout).foregroundStyle(.secondary)
                        if item.canEditDate == true {
                            Button(item.embeddedDate == nil ? "Add date…" : "Edit date…") {
                                dateSavedMessage = nil
                                editingDate = item
                            }
                            .disabled(recordingDecision || !model.hasLiveSnapshot || model.isSavingFileDate)
                            .accessibilityIdentifier("veronica.editFileDate")
                        } else {
                            Text(item.dateEditingUnavailableReason)
                                .font(.caption).foregroundStyle(.secondary)
                        }
                        if let dateSavedMessage {
                            Text(dateSavedMessage).font(.caption).foregroundStyle(VeronicaTheme.accent)
                        }
                    }
                    .padding(18).frame(maxWidth: .infinity, alignment: .leading)
                    .background(VeronicaTheme.subtleFill, in: RoundedRectangle(cornerRadius: 18))
                    HStack {
                        Button("Preview") { ReviewQuickLookController.shared.show(item.fileURL) }
                        Button("Show in Finder") { NSWorkspace.shared.activateFileViewerSelecting([item.fileURL]) }
                    }
                    if let review = model.snapshot?.unresolvedReviews.first(where: { $0.id == item.id }) {
                        VStack(alignment: .leading, spacing: 10) {
                            Text(review.explanation).font(.callout).foregroundStyle(.secondary)
                            Button("Review this decision…") { pendingDecision = review }
                                .disabled(recordingDecision || !model.hasLiveSnapshot)
                        }
                    }
                }.padding(24)
            }
        } else {
            VStack(spacing: 12) {
                Image(systemName: "doc.text.magnifyingglass").font(.system(size: 38, weight: .light)).foregroundStyle(VeronicaTheme.accent)
                Text("Every change, explained.").font(.headline)
                Text("Choose a file to see what Veronica plans to do.").foregroundStyle(.secondary).multilineTextAlignment(.center)
            }.padding(30)
        }
    }

    @MainActor private func loadPage() async {
        guard let id = model.snapshot?.latestPlan?.planId else { return }
        loading = true
        errorMessage = nil
        let request = requestID
        defer { if request == requestID { loading = false } }
        do {
            let result = try await EngineRunner.shared.scanResults(scanID: id, offset: offset, category: category, search: search, focusRoot: dateFocusRoot, focusRelpath: dateFocusRelpath)
            guard !Task.isCancelled, request == requestID else { return }
            page = result
            if dateFocusRelpath != nil {
                offset = result.offset
                dateFocusRoot = nil
                dateFocusRelpath = nil
            }
            if !result.items.contains(where: { $0.id == selectedID }) { selectedID = result.items.first?.id }
        } catch {
            guard !Task.isCancelled, request == requestID else { return }
            page = nil
            selectedID = nil
            errorMessage = error.localizedDescription
        }
    }

    private func record(_ item: ReviewItem, process: Bool) {
        pendingDecision = nil
        recordingDecision = true
        Task { @MainActor in
            defer { recordingDecision = false }
            if process {
                await model.processNormally(item)
                if model.errorMessage == nil { await model.analyzeLibrary() }
            } else {
                await model.keepAsIs(item)
                await loadPage()
            }
        }
    }
}

private struct ResultThumbnail: View {
    let url: URL
    @State private var image: NSImage?
    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 20).fill(VeronicaTheme.subtleFill)
            if let image {
                Image(nsImage: image).resizable().scaledToFit().padding(12)
            } else {
                Image(systemName: "doc").font(.system(size: 48, weight: .light)).foregroundStyle(.secondary)
            }
        }
        .frame(height: 180)
        .task(id: url) {
            image = nil
            let requestedURL = url
            let request = QLThumbnailGenerator.Request(fileAt: url, size: CGSize(width: 600, height: 360),
                                                       scale: NSScreen.main?.backingScaleFactor ?? 2,
                                                       representationTypes: .thumbnail)
            do {
                let thumbnail = try await QLThumbnailGenerator.shared.generateBestRepresentation(for: request)
                guard !Task.isCancelled, requestedURL == url else { return }
                image = thumbnail.nsImage
            } catch { }
        }
    }
}

private struct FileDateEditor: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.dismiss) private var dismiss
    let item: ScanResultItem
    let onSaved: (String) -> Void
    @State private var date: Date
    @State private var saving = false
    @State private var errorMessage: String?

    init(item: ScanResultItem, onSaved: @escaping (String) -> Void) {
        self.item = item
        self.onSaved = onSaved
        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd"
        _date = State(initialValue: item.embeddedDate.flatMap { formatter.date(from: $0) } ?? Date())
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            Text(item.embeddedDate == nil ? "Add a file date" : "Edit file date")
                .font(.title2.weight(.semibold))
            Text(item.filename).font(.callout.weight(.medium)).lineLimit(2)
            DatePicker("Date", selection: $date, displayedComponents: .date)
                .datePickerStyle(.field)
                .accessibilityIdentifier("veronica.fileDate")
                .disabled(saving)
            Text("This date will be saved inside this file and used for its cleanup and filename rules. Its media content stays unchanged. The original goes to Trash.")
                .font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            if let errorMessage {
                Text(errorMessage).font(.callout).foregroundStyle(.red)
                    .textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
            }
            HStack {
                if saving {
                    ProgressView().controlSize(.small)
                    Text("Saving and checking this file…").font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Button("Cancel") { dismiss() }.keyboardShortcut(.cancelAction).disabled(saving)
                Button("Save date") { save() }
                    .buttonStyle(VeronicaPrimaryButtonStyle()).keyboardShortcut(.defaultAction).disabled(saving)
                    .accessibilityIdentifier("veronica.saveFileDate")
            }
        }
        .padding(28).frame(width: 460)
        .interactiveDismissDisabled(saving)
    }

    private func save() {
        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd"
        let value = formatter.string(from: date)
        saving = true
        errorMessage = nil
        Task { @MainActor in
            defer { saving = false }
            do {
                let relpath = try await model.saveFileDate(item, date: value)
                onSaved(relpath)
                dismiss()
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }
}
