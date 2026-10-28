import SwiftUI
import AppKit

private extension ToolbarContent {
    @ToolbarContentBuilder
    func withoutSharedBackground() -> some ToolbarContent {
        if #available(macOS 26.0, *) {
            sharedBackgroundVisibility(.hidden)
        } else {
            self
        }
    }
}

enum VeronicaWindowMetrics {
    static let width: CGFloat = 640
    static let height: CGFloat = 600
    static let contentMaxWidth: CGFloat = 940
    static let detailsSheetSize = CGSize(width: 900, height: 600)
    static let settingsSheetSize = CGSize(width: 860, height: 640)
    static let reviewSheetSize = CGSize(width: 900, height: 620)

    static func size(reviewing: Bool) -> CGSize {
        let available = NSScreen.main?.visibleFrame.size ?? CGSize(width: 1440, height: 900)
        return CGSize(width: min(reviewing ? 1120 : width, available.width - 60),
                      height: min(reviewing ? 740 : height, available.height - 70))
    }
}

private struct WindowChromeConfigurator: NSViewRepresentable {
    let reviewing: Bool
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    func makeNSView(context: Context) -> NSView {
        let view = NSView()
        DispatchQueue.main.async { configure(view.window) }
        return view
    }

    func updateNSView(_ view: NSView, context: Context) {
        DispatchQueue.main.async { configure(view.window) }
    }

    private func configure(_ window: NSWindow?) {
        guard let window else { return }
        window.backgroundColor = .windowBackgroundColor
        window.titleVisibility = .hidden
        window.titlebarAppearsTransparent = true
        window.toolbarStyle = .unifiedCompact
        window.collectionBehavior.remove([.fullScreenPrimary, .fullScreenAuxiliary])
        window.collectionBehavior.insert(.fullScreenNone)
        window.standardWindowButton(.zoomButton)?.isHidden = true
        let size = VeronicaWindowMetrics.size(reviewing: reviewing)
        let content = window.contentRect(forFrameRect: window.frame)
        let needsResize = abs(content.width - size.width) > 1 || abs(content.height - size.height) > 1
        var frame = window.frameRect(forContentRect: NSRect(origin: .zero, size: size))
        frame.origin = needsResize
            ? NSPoint(x: window.frame.midX - frame.width / 2, y: window.frame.maxY - frame.height)
            : window.frame.origin
        if let visible = window.screen?.visibleFrame {
            frame.origin.x = max(visible.minX, min(frame.minX, visible.maxX - frame.width))
            frame.origin.y = max(visible.minY, min(frame.minY, visible.maxY - frame.height))
        }
        frame = window.constrainFrameRect(frame, to: window.screen)
        guard needsResize || frame.origin != window.frame.origin else { return }
        window.setFrame(frame, display: true, animate: window.isVisible && !reduceMotion)
    }
}

enum VeronicaTheme {
    // Brand palette:
    // Adaptive system surfaces / semantic ink / Indigo Bloom accent
    static let canvas = Color(nsColor: .windowBackgroundColor)
    static let ink = Color(nsColor: .labelColor)
    static let accent = Color(
        red: 129.0 / 255.0,
        green: 60.0 / 255.0,
        blue: 176.0 / 255.0
    )

    static let actionGreen = Color(red: 0.22, green: 0.78, blue: 0.36)
    static let actionInk = Color(red: 0.025, green: 0.20, blue: 0.08)

    static let subtleFill = Color(nsColor: .controlBackgroundColor)
    static let strongerFill = Color(nsColor: .underPageBackgroundColor)
    static let panelFill = Color(nsColor: .textBackgroundColor)
    static let border = Color(nsColor: .separatorColor)
    static let secondaryInk = Color(nsColor: .secondaryLabelColor)
    static let tertiaryInk = Color(nsColor: .tertiaryLabelColor)
    static let accentFill = accent.opacity(0.085)
}

struct VeronicaPrimaryButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var enabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.body.weight(.semibold))
            .foregroundStyle(enabled ? VeronicaTheme.actionInk : VeronicaTheme.secondaryInk)
            .padding(.horizontal, 16).padding(.vertical, 10)
            .background(enabled ? VeronicaTheme.actionGreen.opacity(configuration.isPressed ? 0.8 : 1) : VeronicaTheme.subtleFill,
                        in: RoundedRectangle(cornerRadius: 12))
            .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(enabled ? VeronicaTheme.actionInk.opacity(0.10) : VeronicaTheme.border.opacity(0.4)))
            .contentShape(RoundedRectangle(cornerRadius: 12))
    }
}

struct VeronicaPlainButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var enabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            // Include the label's frame, padding and spacer in mouse hit testing.
            .contentShape(Rectangle())
            .opacity(enabled ? (configuration.isPressed ? 0.72 : 1) : 0.45)
    }
}

struct VeronicaGroupBoxStyle: GroupBoxStyle {
    let fill: Color

    init(fill: Color = VeronicaTheme.subtleFill) {
        self.fill = fill
    }

    func makeBody(configuration: Configuration) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            configuration.label
                .font(.headline)
                .foregroundStyle(VeronicaTheme.ink)

            configuration.content
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(18)
        .background(
            fill,
            in: RoundedRectangle(cornerRadius: 14, style: .continuous)
        )
        .overlay {
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .stroke(VeronicaTheme.border, lineWidth: 1)
        }
    }
}

struct VeronicaAppIconView: View {
    let size: CGFloat

    var body: some View {
        Image("VeronicaIcon")
            .resizable()
            .scaledToFit()
            .frame(width: size, height: size)
            .clipShape(RoundedRectangle(cornerRadius: size * 0.22, style: .continuous))
            .accessibilityHidden(true)
    }
}



struct ContentView: View {
    @EnvironmentObject private var model: AppModel
    @State private var reviewing = false
    @State private var showingRunDetails = false
    @State private var folderSettingsSelection: FolderSettings?
    @State private var confirmCleanup = false
    @State private var isDropTargeted = false

    private var folders: [String] { model.snapshot?.scanFolders ?? [] }
    private var busy: Bool { model.isAnalyzing || model.isRunningAnnual || model.isSavingSettings || model.isSavingFileDate }
    private var readyCount: Int {
        model.snapshot?.latestPlan?.remainingExecutableCount ?? model.snapshot?.latestPlan?.executableCount ?? 0
    }
    private var reviewCount: Int { model.snapshot?.unresolvedReviews.count ?? 0 }
    private var canCleanup: Bool {
        model.hasLiveSnapshot && model.analysisCompleted && !busy && readyCount > 0
        && model.maintenanceFailure == nil && (model.snapshot?.pendingStagedOutputs ?? 0) == 0
        && model.snapshot?.archiveAvailable == true && model.snapshot?.preflight.requiredToolsReady == true
    }

    var body: some View {
        VStack(spacing: 0) {
            if model.isRunningAnnual {
                cleanupContent
            } else if model.isAnalyzing {
                AnalysisExperienceView()
                    .padding(.horizontal, 32)
                    .frame(maxHeight: .infinity)
            } else if model.isLoading && !model.hasLiveSnapshot && model.snapshot == nil {
                VStack(spacing: 14) {
                    ProgressView()
                    Text("Getting Veronica ready…").font(.title3.weight(.semibold))
                    Text("Preparing the built-in tools. Everything you need comes with Veronica.")
                        .font(.callout).foregroundStyle(.secondary).multilineTextAlignment(.center)
                }.padding(32).frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if reviewing && model.analysisCompleted {
                ScanResultsView(onCleanup: { confirmCleanup = true }, canCleanup: canCleanup)
            } else if model.analysisCompleted {
                summaryContent
            } else {
                foldersContent
            }
            if !busy && !model.analysisCompleted,
               model.maintenanceFailure != nil || (model.snapshot?.pendingStagedOutputs ?? 0) > 0 {
                HStack(spacing: 10) {
                    Image(systemName: "exclamationmark.triangle").foregroundStyle(.orange)
                    Text("A previous cleanup needs attention.").font(.caption)
                    Spacer()
                    Button("Inspect details") { showingRunDetails = true }
                }.padding(14).background(VeronicaTheme.subtleFill)
            }
            if let message = model.errorMessage {
                HStack(alignment: .top, spacing: 10) {
                    Image(systemName: "exclamationmark.triangle")
                    Text(message).font(.caption).textSelection(.enabled)
                    Spacer(minLength: 4)
                    Button { model.dismissError() } label: { Image(systemName: "xmark").frame(width: 28, height: 28) }
                        .buttonStyle(VeronicaPlainButtonStyle()).accessibilityLabel("Dismiss message")
                }
                .foregroundStyle(.secondary)
                .padding(14)
                .background(VeronicaTheme.subtleFill)
            }
        }
        .frame(width: VeronicaWindowMetrics.size(reviewing: reviewing).width,
               height: VeronicaWindowMetrics.size(reviewing: reviewing).height)
        .background(VeronicaTheme.canvas)
        .tint(VeronicaTheme.accent)
        .background(WindowChromeConfigurator(reviewing: reviewing).frame(width: 0, height: 0))
        .toolbar {
            ToolbarItem(placement: .principal) {
                HStack(spacing: 7) {
                    VeronicaAppIconView(size: 22)
                    Text("Veronica").font(.system(size: 14, weight: .semibold))
                }.fixedSize()
            }
            .withoutSharedBackground()
            ToolbarItem(placement: .navigation) {
                if reviewing {
                    Button { reviewing = false } label: { Label("Summary", systemImage: "chevron.left") }
                        .accessibilityIdentifier("veronica.backToSummary")
                }
            }
        }

        .onChange(of: model.analysisCompleted) { complete in
            if !complete { reviewing = false }
        }
        .onChange(of: model.isRunningAnnual) { running in
            if !running { reviewing = false }
        }
        .onDrop(of: ["public.file-url"], isTargeted: $isDropTargeted, perform: acceptFolders)
        .sheet(item: $folderSettingsSelection) { folder in
            FolderSettingsView(folder: folder).environmentObject(model)
        }
        .sheet(isPresented: $showingRunDetails) {
            sheet("Cleanup details", size: VeronicaWindowMetrics.detailsSheetSize) {
                VStack(alignment: .leading) {
                    if let failure = model.maintenanceFailure { Text(failure).foregroundStyle(.orange).padding() }
                    ActivityView()
                }
            }
        }
        .confirmationDialog("Start Smart cleanup?", isPresented: $confirmCleanup) {
            Button("Smart cleanup") { Task { await model.runAnnual() } }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Veronica will process \(readyCount.formatted()) planned files using each folder’s settings. Files needing your decision are left unchanged. Replaced originals go to the Mac Trash; you can recover them until you empty it.")
        }
#if DEBUG
        .task {
            if ProcessInfo.processInfo.arguments.contains("--debug-open-folder-settings") {
                while !model.hasLiveSnapshot { try? await Task.sleep(nanoseconds: 50_000_000) }
                folderSettingsSelection = model.snapshot?.folderSettings?.first
            }
        }
#endif
    }

    private var foldersContent: some View {
        VStack(spacing: 20) {
            VStack(spacing: 8) {
                if folders.isEmpty {
                    Button { Task { await model.addScanFolders() } } label: {
                        Image(systemName: "folder.badge.plus")
                            .font(.system(size: 48, weight: .light))
                            .frame(width: 112, height: 100)
                            .background(VeronicaTheme.accentFill, in: RoundedRectangle(cornerRadius: 30))
                    }
                    .buttonStyle(VeronicaPlainButtonStyle()).foregroundStyle(VeronicaTheme.accent)
                    .disabled(!model.hasLiveSnapshot || busy)
                    .accessibilityLabel("Add a folder").accessibilityIdentifier("veronica.addFirstFolder")
                }
                Text(folders.isEmpty ? "Make room for more." : "Ready when you are.")
                    .font(.system(size: 29, weight: .semibold)).tracking(-0.7)
                Text(folders.isEmpty ? "Add the folders you’d like Veronica to optimize." : "Each folder has its own settings. Add as many as you need.")
                    .font(.callout).foregroundStyle(.secondary).multilineTextAlignment(.center)
            }
            .padding(.top, folders.isEmpty ? 20 : 4)

            if folders.isEmpty {
                Button("Add a folder…") { Task { await model.addScanFolders() } }
                    .buttonStyle(VeronicaPrimaryButtonStyle()).controlSize(.large)
                    .disabled(!model.hasLiveSnapshot || busy)
                Text("You can also drop folders here.").font(.caption).foregroundStyle(.secondary)
                Spacer(minLength: 0)
            } else {
                ScrollView {
                    LazyVStack(spacing: 9) {
                        ForEach(folders, id: \.self) { folder in folderRow(folder) }
                    }.padding(1)
                }
                .frame(maxHeight: .infinity)
                Button { Task { await model.addScanFolders() } } label: {
                    Label("Add another folder…", systemImage: "plus")
                        .padding(.horizontal, 10).padding(.vertical, 6)
                }
                .buttonStyle(VeronicaPlainButtonStyle()).foregroundStyle(VeronicaTheme.accent)
                .disabled(!model.hasLiveSnapshot || busy)
                .accessibilityIdentifier("veronica.addFolder")
            }

            VStack(spacing: 12) {
                Text("Just push the green button to find all optimizable files")
                    .font(.callout).foregroundStyle(.secondary).multilineTextAlignment(.center)
                Button { Task { await model.analyzeLibrary() } } label: {
                    Label("Scan folders", systemImage: "magnifyingglass")
                        .frame(minWidth: 170).padding(.vertical, 5)
                }
                .buttonStyle(VeronicaPrimaryButtonStyle()).controlSize(.large)
                .keyboardShortcut(.defaultAction)
                .disabled(folders.isEmpty || !model.hasLiveSnapshot || busy || model.snapshot?.archiveAvailable != true)
                .accessibilityIdentifier("veronica.scanFolders")
                Text(model.analysisCancelled ? "Scan cancelled. Your files were not changed." : "Scanning leaves your files unchanged.")
                    .font(.caption).foregroundStyle(.secondary)
                    .accessibilityIdentifier("veronica.scanStatus")
            }
        }
        .padding(.horizontal, 32).padding(.top, 18).padding(.bottom, 24)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(isDropTargeted ? VeronicaTheme.accentFill : Color.clear)
    }

    private func folderRow(_ path: String) -> some View {
        let settings = model.snapshot?.folderSettings?.first { $0.folder == path }
        let unavailable = model.snapshot?.unavailableScanFolders.contains(path) == true
        return HStack(spacing: 12) {
            Image(systemName: "folder.fill").font(.title2).foregroundStyle(VeronicaTheme.accent)
            VStack(alignment: .leading, spacing: 4) {
                Text(URL(fileURLWithPath: path).lastPathComponent).font(.callout.weight(.semibold))
                Text(unavailable ? "Folder unavailable" : settings?.recipe.displaySummary ?? path)
                    .font(.caption).foregroundStyle(.secondary).lineLimit(2)
            }
            .help(path)
            Spacer(minLength: 8)
            Button { folderSettingsSelection = settings } label: { Image(systemName: "slider.horizontal.3").frame(width: 28, height: 28) }
                .buttonStyle(VeronicaPlainButtonStyle()).disabled(busy || settings == nil || !model.hasLiveSnapshot)
                .accessibilityLabel("Settings for \(URL(fileURLWithPath: path).lastPathComponent)")
                .accessibilityIdentifier("veronica.folderSettings")
                .help("Folder settings")
            Button { Task { await model.removeScanFolder(path) } } label: { Image(systemName: "minus.circle").frame(width: 28, height: 28) }
                .buttonStyle(VeronicaPlainButtonStyle()).disabled(busy || !model.hasLiveSnapshot)
                .accessibilityLabel("Remove \(URL(fileURLWithPath: path).lastPathComponent)")
        }
        .padding(14)
        .background(VeronicaTheme.subtleFill, in: RoundedRectangle(cornerRadius: 16))
        .overlay(RoundedRectangle(cornerRadius: 16).strokeBorder(VeronicaTheme.border.opacity(0.55)))
    }

    private var summaryContent: some View {
        VStack(spacing: 22) {
            ZStack {
                RoundedRectangle(cornerRadius: 38).fill(VeronicaTheme.accentFill).frame(width: 124, height: 116)
                Image(systemName: readyCount > 0 ? "sparkles" : "checkmark.seal")
                    .font(.system(size: 46, weight: .light)).foregroundStyle(VeronicaTheme.accent)
            }
            .padding(.top, 12)
            VStack(spacing: 8) {
                Text(model.cleanupOutcome?.title ?? "Scan complete")
                    .font(.system(size: 30, weight: .semibold)).tracking(-0.7)
                Text(model.cleanupOutcome?.subtitle
                     ?? (model.cleanupCompleted ? "Your optimized files are ready in their folders."
                     : readyCount > 0 ? "A little more space is waiting." : "Your folders are looking good.")
                )
                    .foregroundStyle(.secondary)
            }
            HStack(spacing: 0) {
                if let outcome = model.cleanupOutcome {
                    metric("Files optimized", value: outcome.optimized)
                    Divider().frame(height: 48)
                    metric("Renamed", value: outcome.renamed)
                    Divider().frame(height: 48)
                    metric("Space saved", value: outcome.formattedSaving)
                } else {
                    metric("Files scanned", value: model.snapshot?.latestPlan?.itemCount ?? 0)
                    Divider().frame(height: 48)
                    metric("Ready to optimize", value: readyCount)
                    Divider().frame(height: 48)
                    metric("Need a decision", value: reviewCount)
                }
            }
            .padding(.vertical, 18)
            .background(VeronicaTheme.subtleFill, in: RoundedRectangle(cornerRadius: 20))
            Text(model.cleanupCompleted
                 ? "Replaced originals are in the Mac Trash. Empty Trash when you’re ready to free the space."
                 : "See every planned change before cleanup. Actual space savings are measured after conversion.")
                .font(.callout).foregroundStyle(.secondary).multilineTextAlignment(.center)
                .frame(maxWidth: 450)
            if model.maintenanceFailure != nil || (model.snapshot?.pendingStagedOutputs ?? 0) > 0 || (model.cleanupOutcome?.unreadable ?? 0) > 0 {
                Button("Inspect cleanup details") { showingRunDetails = true }
                    .foregroundStyle(.orange)
            }
            HStack(spacing: 12) {
                Button { reviewing = true } label: { Text("Review results").frame(minWidth: 140).padding(.vertical, 5) }
                    .buttonStyle(.bordered).controlSize(.large)
                    .accessibilityIdentifier("veronica.reviewResults")
                Button { confirmCleanup = true } label: { Text("Smart cleanup").frame(minWidth: 140).padding(.vertical, 5) }
                    .buttonStyle(VeronicaPrimaryButtonStyle()).controlSize(.large).disabled(!canCleanup)
                    .accessibilityIdentifier("veronica.smartCleanup")
            }
            Button { model.analysisCompleted = false; reviewing = false } label: {
                Text("Back to folders").padding(.horizontal, 10).padding(.vertical, 6)
            }
                .buttonStyle(VeronicaPlainButtonStyle()).font(.callout).foregroundStyle(.secondary)
                .accessibilityIdentifier("veronica.backToFolders")
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 32).padding(.top, 24)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func metric(_ title: String, value: Int) -> some View {
        metric(title, value: value.formatted())
    }

    private func metric(_ title: String, value: String) -> some View {
        VStack(spacing: 6) {
            Text(value).font(.system(size: 26, weight: .semibold)).monospacedDigit()
            Text(title).font(.caption).foregroundStyle(.secondary)
        }.frame(maxWidth: .infinity)
    }

    private var cleanupContent: some View {
        VStack(spacing: 22) {
            Image(systemName: "sparkles").font(.system(size: 50, weight: .light)).foregroundStyle(VeronicaTheme.accent)
            Text("Making room for more").font(.system(size: 29, weight: .semibold))
            Text("Veronica verifies every replacement before making a change.")
                .foregroundStyle(.secondary).multilineTextAlignment(.center)
            ProgressView(value: model.currentProgress).progressViewStyle(.linear)
            if let event = model.latestEvent {
                Text(event.title).fontWeight(.medium)
                if let detail = event.detail { Text(detail).font(.caption).foregroundStyle(.secondary).lineLimit(2) }
            }
            Text("Replaced originals go to the Mac Trash.").font(.caption).foregroundStyle(.secondary)
        }
        .padding(40).frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func sheet<Content: View>(_ title: String, size: CGSize, @ViewBuilder content: () -> Content) -> some View {
        VStack(spacing: 0) {
            HStack {
                Text(title).font(.headline)
                Spacer()
                Button("Done") { showingRunDetails = false }
                    .keyboardShortcut(.cancelAction)
            }.padding(20)
            Divider()
            content()
        }.frame(width: size.width, height: size.height)
    }

    private func acceptFolders(_ providers: [NSItemProvider]) -> Bool {
        guard model.hasLiveSnapshot, !busy, !providers.isEmpty else { return false }
        Task { @MainActor in
            var urls: [URL] = []
            for provider in providers {
                let url: URL? = await withCheckedContinuation { continuation in
                    provider.loadItem(forTypeIdentifier: "public.file-url", options: nil) { item, _ in
                        if let data = item as? Data { continuation.resume(returning: URL(dataRepresentation: data, relativeTo: nil)) }
                        else if let url = item as? URL { continuation.resume(returning: url) }
                        else { continuation.resume(returning: nil) }
                    }
                }
                if let url { urls.append(url) }
            }
            if !urls.isEmpty { await model.addScanFolderURLs(urls) }
        }
        return true
    }
}

struct SectionEmptyStateView: View {
    let title: String
    let systemImage: String
    let message: String

    var body: some View {
        VStack(spacing: 12) {
            Image(systemName: systemImage)
                .font(.system(size: 36, weight: .medium))
                .foregroundStyle(VeronicaTheme.accent)

            Text(title)
                .font(.title2.bold())
                .foregroundStyle(VeronicaTheme.ink)

            Text(message)
                .foregroundStyle(VeronicaTheme.secondaryInk)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 560)
        }
        .frame(maxWidth: .infinity, alignment: .center)
        .padding(.top, 30)
        .padding(.horizontal, 40)

        Spacer(minLength: 0)
    }
}

struct EmptyStateView: View {
    let title: String
    let systemImage: String
    let message: String

    var body: some View {
        VStack(spacing: 12) {
            Image(systemName: systemImage)
                .font(.system(size: 36, weight: .medium))
                .foregroundStyle(VeronicaTheme.accent)

            Text(title)
                .font(.title2.bold())
                .foregroundStyle(VeronicaTheme.ink)

            Text(message)
                .foregroundStyle(VeronicaTheme.secondaryInk)
                .multilineTextAlignment(.center)
                .lineSpacing(2)
        }
        .frame(maxWidth: 620)
        .padding(.horizontal, 28)
        .padding(.vertical, 44)
        .frame(maxWidth: .infinity, alignment: .top)
    }
}

// MARK: - Analysis Experience

private struct AnalysisExperienceView: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var isBreathing = false

    var body: some View {
        VStack(spacing: 24) {
            ZStack {
                Circle()
                    .fill(VeronicaTheme.accent.opacity(0.055))
                    .frame(width: 180, height: 180)
                    .scaleEffect(isBreathing ? 1.08 : 0.94)

                Circle()
                    .fill(VeronicaTheme.accent.opacity(0.09))
                    .frame(width: 140, height: 140)
                    .scaleEffect(isBreathing ? 0.96 : 1.05)

                Circle()
                    .fill(
                        LinearGradient(
                            colors: [
                                VeronicaTheme.accent.opacity(0.18),
                                VeronicaTheme.accent.opacity(0.08)
                            ],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                    .frame(width: 104, height: 104)

                VeronicaAppIconView(size: 82)
            }
            .frame(height: 130)
            .accessibilityHidden(true)

            VStack(spacing: 10) {
                Text("Getting to know your library")
                    .font(.system(size: 27, weight: .semibold))
                    .tracking(-1)
                    .multilineTextAlignment(.center)

                Text("Finding thoughtful ways to make more room for what matters.")
                    .font(.system(size: 15))
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: 440)
            }

            VStack(alignment: .leading, spacing: 16) {
                HStack(spacing: 16) {
                    ZStack {
                        RoundedRectangle(cornerRadius: 13)
                            .fill(VeronicaTheme.accent.opacity(0.1))
                            .frame(width: 48, height: 48)

                        Image(systemName: "magnifyingglass")
                            .font(.system(size: 21, weight: .medium))
                            .foregroundStyle(VeronicaTheme.accent)
                    }

                    VStack(alignment: .leading, spacing: 5) {
                        Text(model.analysisProgress?.title ?? "Preparing your scan")
                            .font(.system(size: 15, weight: .semibold))

                        if let progress = model.analysisProgress {
                            Text(URL(fileURLWithPath: progress.folder).lastPathComponent)
                                .font(.system(size: 13))
                                .foregroundStyle(.secondary)
                                .lineLimit(1)
                                .truncationMode(.middle)
                                .help(progress.folder)

                            if progress.folderCount > 1 {
                                Text("Folder \(progress.folderIndex) of \(progress.folderCount)")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }

                    Spacer(minLength: 0)
                }

                VStack(spacing: 8) {
                    Group {
                        if let fraction = model.analysisProgress?.fractionCompleted {
                            ProgressView(value: fraction)
                        } else {
                            ProgressView()
                        }
                    }
                    .progressViewStyle(.linear)
                    .accessibilityLabel("Folder scan progress")
                    .accessibilityIdentifier("veronica.scanProgress")

                    HStack {
                        if let progress = model.analysisProgress,
                           progress.phase == "scanning", let total = progress.totalFiles {
                            Text("\(progress.completedFiles.formatted()) of \(total.formatted()) files checked")
                        } else {
                            Text(model.analysisProgress?.phase == "planning"
                                 ? "Checking for safe ways to save space…"
                                 : "Finding the files in your folder…")
                        }

                        Spacer()

                        if let fraction = model.analysisProgress?.fractionCompleted {
                            Text(fraction, format: .percent.precision(.fractionLength(0)))
                        }
                    }
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .monospacedDigit()
                }
            }
            .padding(22)
            .frame(maxWidth: 570)
            .background(
                VeronicaTheme.subtleFill,
                in: RoundedRectangle(cornerRadius: 20, style: .continuous)
            )
            .overlay {
                RoundedRectangle(cornerRadius: 20, style: .continuous)
                    .strokeBorder(VeronicaTheme.border.opacity(0.65))
            }

            Label(
                "Your original files stay exactly as they are",
                systemImage: "lock.shield"
            )
            .font(.callout)
            .foregroundStyle(.secondary)

            Button(model.isCancellingAnalysis ? "Cancelling…" : "Cancel") {
                model.cancelAnalysis()
            }
            .buttonStyle(.bordered)
            .controlSize(.large)
            .keyboardShortcut(.cancelAction)
            .disabled(model.isCancellingAnalysis)
            .accessibilityIdentifier("veronica.cancelAnalysis")
            .accessibilityHint("Stop scanning and return to your folders.")
        }
        .frame(maxWidth: .infinity)
        .padding(.top, 10)
        .onAppear {
            guard !reduceMotion else { return }
            withAnimation(.easeInOut(duration: 2.4).repeatForever(autoreverses: true)) {
                isBreathing = true
            }
        }
        .onChange(of: reduceMotion) { enabled in
            if enabled {
                isBreathing = false
            } else {
                withAnimation(.easeInOut(duration: 2.4).repeatForever(autoreverses: true)) {
                    isBreathing = true
                }
            }
        }
    }
}
