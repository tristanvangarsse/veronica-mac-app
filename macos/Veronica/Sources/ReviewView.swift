import AppKit
import QuickLookThumbnailing
import QuickLookUI
import SwiftUI

struct ReviewView: View {
    @EnvironmentObject var model: AppModel
    @AppStorage("veronica.review.keepAsIsConfirmationSeen") private var keepAsIsConfirmationSeen = false
    @AppStorage("veronica.review.processNormallyConfirmationSeen") private var processNormallyConfirmationSeen = false
    @State private var pendingKeep: ReviewItem?
    @State private var pendingProcess: ReviewItem?

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            VStack(alignment: .leading, spacing: 3) {
                Text("Review")
                    .font(.largeTitle.bold())

                Text("These files are still safe where they are. Veronica is asking because optimizing them could change quality, timing, tracks, or date-based organization.")
                    .foregroundStyle(.secondary)
            }

            if let items = model.snapshot?.unresolvedReviews, !items.isEmpty {
                List {
                    ForEach(items) { item in
                        ReviewItemRow(
                            item: item,
                            previewURL: reviewURL(for: item),
                            onReveal: { model.revealReview(item) },
                            onKeep: { keepAsIs(item) },
                            onProcess: { processNormally(item) }
                        )
                    }
                }
                .listStyle(.inset)
                .scrollContentBackground(.hidden)
                .background(VeronicaTheme.canvas)
            } else {
                SectionEmptyStateView(
                    title: "Nothing needs review",
                    systemImage: "checkmark.circle",
                    message: "Every item in the latest plan is either complete, deliberately preserved, or safely skippable."
                )
            }
        }
        .frame(maxWidth: 1100, alignment: .leading)
        .padding(.horizontal, 32)
        .padding(.vertical, 26)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(VeronicaTheme.canvas)
        .confirmationDialog(
            "Keep this original unchanged?",
            isPresented: Binding(
                get: { pendingKeep != nil },
                set: { if !$0 { pendingKeep = nil } }
            )
        ) {
            Button("Keep As Is") {
                if let item = pendingKeep {
                    keepAsIsConfirmationSeen = true
                    Task { await model.keepAsIs(item) }
                }
                pendingKeep = nil
            }

            Button("Cancel", role: .cancel) {
                pendingKeep = nil
            }
        } message: {
            Text("This records a guarded review decision in Veronica's database. The media file itself is not modified, and the decision is reused only while the source identity and review reason still match.")
        }
        .confirmationDialog(
            "Let Veronica process this file normally?",
            isPresented: Binding(
                get: { pendingProcess != nil },
                set: { if !$0 { pendingProcess = nil } }
            )
        ) {
            Button("Process Normally") {
                if let item = pendingProcess {
                    processNormallyConfirmationSeen = true
                    Task { await model.processNormally(item) }
                }
                pendingProcess = nil
            }

            Button("Cancel", role: .cancel) {
                pendingProcess = nil
            }
        } message: {
            Text("This approves this specific review reason for this exact unchanged file. Veronica will still apply its normal conversion rules and all other safety checks. It does not force compression.")
        }
    }

    private func reviewURL(for item: ReviewItem) -> URL? {
        URL(fileURLWithPath: item.root).appendingPathComponent(item.relpath)
    }

    private func keepAsIs(_ item: ReviewItem) {
        if keepAsIsConfirmationSeen {
            Task { await model.keepAsIs(item) }
        } else {
            pendingKeep = item
        }
    }

    private func processNormally(_ item: ReviewItem) {
        if processNormallyConfirmationSeen {
            Task { await model.processNormally(item) }
        } else {
            pendingProcess = item
        }
    }
}

private struct ReviewItemRow: View {
    let item: ReviewItem
    let previewURL: URL?
    let onReveal: () -> Void
    let onKeep: () -> Void
    let onProcess: () -> Void

    private var filename: String {
        URL(fileURLWithPath: item.relpath).lastPathComponent
    }

    private var formattedSize: String {
        ByteCountFormatter.string(fromByteCount: item.sourceSize, countStyle: .file)
    }

    var body: some View {
        HStack(alignment: .top, spacing: 16) {
            thumbnail
            details
            Spacer()
            actions
        }
        .padding(.vertical, 8)
    }

    @ViewBuilder
    private var thumbnail: some View {
        if let url = previewURL {
            Button {
                ReviewQuickLookController.shared.show(url)
            } label: {
                ReviewThumbnail(url: url)
            }
            .buttonStyle(.plain)
            .help("Preview")
        }
    }

    private var details: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text("\(item.category): \(item.title)")
                .font(.headline)
            Text(filename)
                .font(.subheadline)
                .textSelection(.enabled)
            Text(item.root)
                .font(.caption2)
                .lineLimit(1)
                .truncationMode(.middle)
            Text(item.explanation)
                .font(.caption)
            Text(item.recommendedAction)
                .font(.caption)
            Text(formattedSize)
                .font(.caption2)
        }
    }

    private var actions: some View {
        VStack(alignment: .trailing, spacing: 8) {
            Button("Preview") {
                if let url = previewURL {
                    ReviewQuickLookController.shared.show(url)
                }
            }
            .buttonStyle(.link)

            Button("Show in Finder", action: onReveal)
                .buttonStyle(.link)

            if item.canProcessNormally {
                Button("Process Normally", action: onProcess)
                    .buttonStyle(.borderedProminent)
                    .help("Approve this review and let Veronica apply its normal policy.")
            }

            Button("Keep As Is", action: onKeep)
                .buttonStyle(.bordered)
        }
    }
}

private struct ReviewThumbnail: View {
    let url: URL

    @State private var image: NSImage?

    var body: some View {
        Group {
            if let image {
                Image(nsImage: image)
                    .resizable()
                    .scaledToFill()
            } else {
                ZStack {
                    RoundedRectangle(cornerRadius: 8)
                        .fill(.quaternary)

                    Image(systemName: "photo.on.rectangle")
                        .font(.title2)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .frame(width: 128, height: 84)
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .overlay {
            RoundedRectangle(cornerRadius: 8)
                .stroke(.separator.opacity(0.5), lineWidth: 1)
        }
        .task(id: url) {
            await loadThumbnail()
        }
    }

    @MainActor
    private func loadThumbnail() async {
        let scale = NSScreen.main?.backingScaleFactor ?? 2
        let request = QLThumbnailGenerator.Request(
            fileAt: url,
            size: CGSize(width: 256, height: 168),
            scale: scale,
            representationTypes: .thumbnail
        )

        do {
            let representation = try await QLThumbnailGenerator.shared
                .generateBestRepresentation(for: request)
            image = representation.nsImage
        } catch {
            image = NSWorkspace.shared.icon(forFile: url.path)
        }
    }
}

final class ReviewQuickLookController: NSObject, QLPreviewPanelDataSource {
    static let shared = ReviewQuickLookController()

    private var previewURL: URL?

    func show(_ url: URL) {
        previewURL = url

        guard let panel = QLPreviewPanel.shared() else {
            NSWorkspace.shared.open(url)
            return
        }

        panel.dataSource = self
        panel.reloadData()
        panel.makeKeyAndOrderFront(nil)
    }

    func numberOfPreviewItems(in panel: QLPreviewPanel!) -> Int {
        previewURL == nil ? 0 : 1
    }

    func previewPanel(_ panel: QLPreviewPanel!, previewItemAt index: Int) -> QLPreviewItem! {
        previewURL as NSURL?
    }
}
