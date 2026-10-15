import SwiftUI
import AppKit
import QuickLookThumbnailing

enum VeronicaWindowMetrics {
    static let width: CGFloat = 1040
    static let height: CGFloat = 700
    static let contentMaxWidth: CGFloat = 940

    static let historySheetSize = CGSize(width: 900, height: 600)
    static let settingsSheetSize = CGSize(width: 860, height: 640)
    static let reviewSheetSize = CGSize(width: 900, height: 620)
}

private struct WindowChromeConfigurator: NSViewRepresentable {
    func makeNSView(context: Context) -> NSView {
        let view = NSView()

        DispatchQueue.main.async {
            configure(view.window)
        }

        return view
    }

    func updateNSView(_ nsView: NSView, context: Context) {
        DispatchQueue.main.async {
            configure(nsView.window)
        }
    }

    private func configure(_ window: NSWindow?) {
        guard let window else { return }

        // Follow the user's system appearance. SwiftUI and AppKit controls
        // inherit the current light/dark appearance from the window.
        window.backgroundColor = .windowBackgroundColor
        window.titleVisibility = .hidden
        window.titlebarAppearsTransparent = true
        window.toolbarStyle = .unified
        window.collectionBehavior.remove([.fullScreenPrimary, .fullScreenAuxiliary])
        window.collectionBehavior.insert(.fullScreenNone)
        window.setContentSize(
            NSSize(
                width: VeronicaWindowMetrics.width,
                height: VeronicaWindowMetrics.height
            )
        )
        window.minSize = NSSize(
            width: VeronicaWindowMetrics.width,
            height: VeronicaWindowMetrics.height
        )
        window.maxSize = NSSize(
            width: VeronicaWindowMetrics.width,
            height: VeronicaWindowMetrics.height
        )
        window.styleMask.remove(.resizable)
        window.standardWindowButton(.zoomButton)?.isEnabled = false
        window.standardWindowButton(.zoomButton)?.isHidden = true
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

    static let subtleFill = Color(nsColor: .controlBackgroundColor)
    static let strongerFill = Color(nsColor: .underPageBackgroundColor)
    static let panelFill = Color(nsColor: .textBackgroundColor)
    static let border = Color(nsColor: .separatorColor)
    static let secondaryInk = Color(nsColor: .secondaryLabelColor)
    static let tertiaryInk = Color(nsColor: .tertiaryLabelColor)
    static let accentFill = accent.opacity(0.085)
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

private enum AppSection: String, CaseIterable, Identifiable {
    case dashboard = "Dashboard"
    case activity = "Activity"
    case review = "Review"
    case history = "History"
    case settings = "Settings"

    var id: String { rawValue }

    var systemImage: String {
        switch self {
        case .dashboard:
            return "gauge.with.dots.needle.67percent"
        case .activity:
            return "waveform.path.ecg"
        case .review:
            return "exclamationmark.bubble"
        case .history:
            return "clock.arrow.circlepath"
        case .settings:
            return "gearshape"
        }
    }
}

private struct MediaThumbnail: View {
    let url: URL

    @State private var image: NSImage?

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 12)
                .fill(VeronicaTheme.accent.opacity(0.07))

            if let image {
                Image(nsImage: image)
                    .resizable()
                    .scaledToFill()
                    .frame(width: 90, height: 72)
                    .clipped()
                    .clipShape(RoundedRectangle(cornerRadius: 12))
            } else {
                Image(systemName: "photo.on.rectangle.angled")
                    .font(.system(size: 25))
                    .foregroundStyle(VeronicaTheme.accent.opacity(0.7))
            }
        }
        .frame(width: 90, height: 72)
        .task(id: url) {
            let request = QLThumbnailGenerator.Request(
                fileAt: url,
                size: CGSize(width: 180, height: 144),
                scale: NSScreen.main?.backingScaleFactor ?? 2,
                representationTypes: .thumbnail
            )

            do {
                let result = try await QLThumbnailGenerator.shared
                    .generateBestRepresentation(for: request)
                image = result.nsImage
            } catch {
                image = nil
            }
        }
    }
}

struct ContentView: View {
    @EnvironmentObject var model: AppModel
    @State private var showingHistory = false
    @State private var showingSettings = false
    @State private var showingReview = false
    @State private var confirmOptimize = false
    @State private var isDropTargeted = false

    private var hasFolders: Bool {
        !(model.snapshot?.scanFolders.isEmpty ?? true)
    }

    private var hasResults: Bool {
        model.analysisCompleted || model.snapshot?.latestPlan != nil
    }

    private var canOptimize: Bool {
        model.hasLiveSnapshot
        && model.analysisCompleted
        && !model.isAnalyzing
        && !model.isRunningAnnual
        && model.snapshot?.archiveAvailable == true
        && model.snapshot?.preflight.requiredToolsReady == true
        && (model.snapshot?.latestPlan?.remainingExecutableCount
            ?? model.snapshot?.latestPlan?.executableCount
            ?? 0) > 0
    }

    var body: some View {
        VStack(spacing: 0) {
            topBar

            Rectangle()
                .fill(VeronicaTheme.border.opacity(0.65))
                .frame(height: 1)

            VStack(spacing: 0) {
                if model.isRunningAnnual {
                    optimizingContent
                } else if model.isAnalyzing {
                    analyzingContent
                } else if hasResults {
                    resultsContent
                } else {
                    welcomeContent
                }
            }
            .frame(maxWidth: VeronicaWindowMetrics.contentMaxWidth)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
            .padding(.horizontal, 32)
            .padding(.vertical, 14)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .onDrop(of: ["public.file-url"], isTargeted: $isDropTargeted) { providers in
            guard model.hasLiveSnapshot,
                  !model.isAnalyzing,
                  !model.isRunningAnnual,
                  !providers.isEmpty else {
                return false
            }

            let group = DispatchGroup()
            let lock = NSLock()
            var droppedURLs: [URL] = []

            for provider in providers {
                guard provider.hasItemConformingToTypeIdentifier("public.file-url") else {
                    continue
                }

                group.enter()
                provider.loadItem(
                    forTypeIdentifier: "public.file-url",
                    options: nil
                ) { item, _ in
                    var url: URL?

                    if let data = item as? Data {
                        url = URL(dataRepresentation: data, relativeTo: nil)
                    } else if let value = item as? URL {
                        url = value
                    } else if let value = item as? String {
                        url = URL(string: value)
                    }

                    if let url {
                        lock.lock()
                        droppedURLs.append(url)
                        lock.unlock()
                    }

                    group.leave()
                }
            }

            group.notify(queue: .main) {
                Task { @MainActor in
                    await model.addScanFolderURLs(droppedURLs)
                }
            }

            return true
        }
        .background(VeronicaTheme.canvas)
        .tint(VeronicaTheme.accent)
        .background {
            WindowChromeConfigurator()
                .frame(width: 0, height: 0)
        }
        .sheet(isPresented: $showingHistory) {
            secondarySheet("History", size: VeronicaWindowMetrics.historySheetSize) {
                HistoryView()
            }
        }
        .sheet(isPresented: $showingSettings) {
            secondarySheet("Settings", size: VeronicaWindowMetrics.settingsSheetSize) {
                SettingsView()
            }
        }
        .sheet(isPresented: $showingReview) {
            secondarySheet("Review Details", size: VeronicaWindowMetrics.reviewSheetSize) {
                ReviewView()
            }
        }
        .confirmationDialog(
            "Optimize this library?",
            isPresented: $confirmOptimize
        ) {
            Button("Optimize Library") {
                Task { await model.runAnnual() }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Veronica will independently verify replacements before committing them. Originals are preserved in quarantine for rollback. Files requiring review are not automatically processed.")
        }
        .overlay(alignment: .bottom) {
            if let error = model.errorMessage {
                HStack(spacing: 12) {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .foregroundStyle(.orange)
                    Text(error)
                        .font(.callout)
                    Spacer()
                    Button("Dismiss") { model.errorMessage = nil }
                }
                .padding(16)
                .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 14))
                .padding(20)
            }
        }
    }

    private var topBar: some View {
        HStack(spacing: 12) {
            VeronicaAppIconView(size: 24)

            Text("Veronica")
                .font(.system(size: 16, weight: .semibold))

            Spacer()

            if model.isLoading && !model.isAnalyzing && !model.isRunningAnnual {
                ProgressView()
                    .controlSize(.small)
            }

            Button {
                showingHistory = true
            } label: {
                Label("History", systemImage: "clock.arrow.circlepath")
            }
            .accessibilityIdentifier("veronica.openHistory")
            .buttonStyle(.plain)
            .foregroundStyle(.secondary)

            Button {
                showingSettings = true
            } label: {
                Label("Settings", systemImage: "gearshape")
            }
            .accessibilityIdentifier("veronica.openSettings")
            .buttonStyle(.plain)
            .foregroundStyle(.secondary)
        }
        .padding(.horizontal, 32)
        .padding(.vertical, 14)
    }

    private var welcomeContent: some View {
        VStack(spacing: 22) {
            ZStack {
                Circle()
                    .fill(VeronicaTheme.accent.opacity(0.045))
                    .frame(width: 168, height: 168)

                Circle()
                    .strokeBorder(
                        VeronicaTheme.accent.opacity(0.12),
                        lineWidth: 1
                    )
                    .frame(width: 134, height: 134)

                RoundedRectangle(cornerRadius: 28, style: .continuous)
                    .fill(VeronicaTheme.accent.opacity(0.10))
                    .frame(width: 96, height: 96)
                    .rotationEffect(.degrees(-8))

                Image(systemName: "photo.on.rectangle.angled")
                    .font(.system(size: 43, weight: .ultraLight))
                    .foregroundStyle(VeronicaTheme.accent)

                Image(systemName: "sparkle")
                    .font(.system(size: 20, weight: .medium))
                    .foregroundStyle(VeronicaTheme.accent)
                    .offset(x: 62, y: -52)

                Circle()
                    .fill(VeronicaTheme.accent.opacity(0.35))
                    .frame(width: 8, height: 8)
                    .offset(x: -70, y: 40)
            }
            .frame(height: 166)
            .accessibilityHidden(true)

            VStack(spacing: 12) {
                Text("Make room for more memories.")
                    .font(.system(size: 34, weight: .semibold))
                    .multilineTextAlignment(.center)
                    .foregroundStyle(VeronicaTheme.ink)

                Text("Beautifully simple media optimization. Discover ways to save space while keeping your originals protected.")
                    .font(.system(size: 16))
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: 510)
                    .fixedSize(horizontal: false, vertical: true)
            }

            VStack(spacing: 14) {
                ZStack {
                    RoundedRectangle(cornerRadius: 15, style: .continuous)
                        .fill(VeronicaTheme.accent.opacity(0.10))
                        .frame(width: 54, height: 54)

                    Image(systemName: "folder.badge.plus")
                        .font(.system(size: 25, weight: .light))
                        .foregroundStyle(VeronicaTheme.accent)
                }
                .accessibilityHidden(true)

                VStack(spacing: 7) {
                    Text(
                        isDropTargeted
                        ? "Drop your folder here"
                        : "Start with your media library"
                    )
                    .font(.system(size: 20, weight: .semibold))
                    .multilineTextAlignment(.center)

                    Text("Drag a folder here, or choose one to begin.")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                }

                Button {
                    Task { await model.addScanFolders() }
                } label: {
                    Label("Choose a Folder", systemImage: "folder")
                        .font(.system(size: 14, weight: .semibold))
                        .frame(minWidth: 175)
                        .padding(.vertical, 5)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .disabled(!model.hasLiveSnapshot)

                Text("Analysis starts automatically. Nothing changes without your approval.")
                    .font(.caption)
                    .foregroundStyle(.tertiary)
                    .multilineTextAlignment(.center)
            }
            .frame(maxWidth: .infinity)
            .padding(.horizontal, 26)
            .padding(.vertical, 24)
            .background(
                isDropTargeted
                    ? VeronicaTheme.accent.opacity(0.08)
                    : VeronicaTheme.subtleFill,
                in: RoundedRectangle(cornerRadius: 24, style: .continuous)
            )
            .overlay {
                RoundedRectangle(cornerRadius: 24, style: .continuous)
                    .strokeBorder(
                        isDropTargeted
                            ? VeronicaTheme.accent
                            : VeronicaTheme.border,
                        style: StrokeStyle(
                            lineWidth: isDropTargeted ? 2 : 1,
                            dash: [7, 5]
                        )
                    )
            }
            .animation(.easeInOut(duration: 0.18), value: isDropTargeted)

            ViewThatFits(in: .horizontal) {
                HStack(spacing: 25) {
                    reassurance("Originals protected", icon: "checkmark.shield")
                    reassurance("Carefully verified", icon: "checkmark.seal")
                    reassurance("You're in control", icon: "hand.raised")
                }

                VStack(spacing: 9) {
                    reassurance("Originals protected", icon: "checkmark.shield")
                    reassurance("Carefully verified", icon: "checkmark.seal")
                    reassurance("You're in control", icon: "hand.raised")
                }
            }
        }
        .frame(maxWidth: 760)
        .frame(maxWidth: .infinity)
    }

    private var analyzingContent: some View {
        AnalysisExperienceView()
    }

    private var resultsContent: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .top, spacing: 22) {
                VStack(alignment: .leading, spacing: 9) {
                    Label("Dashboard", systemImage: "sparkles")
                        .font(.system(size: 12, weight: .bold))
                        .foregroundStyle(VeronicaTheme.accent)
                        .labelStyle(.titleAndIcon)

                    Text("Library overview")
                        .font(.system(size: 25, weight: .semibold))
                        .foregroundStyle(VeronicaTheme.ink)
                        .fixedSize(horizontal: false, vertical: true)

                    Text(
                        model.analysisCompleted
                            ? "Current analysis is ready. Review the plan, then choose what Veronica may change."
                            : "Previous results are available. Run a fresh analysis before making changes."
                    )
                    .font(.system(size: 15))
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                }

                Spacer(minLength: 20)

                VStack(alignment: .leading, spacing: 7) {
                    Label(
                        model.analysisCompleted
                            ? "Current analysis"
                            : "Previous analysis",
                        systemImage: model.analysisCompleted
                            ? "checkmark.circle.fill"
                            : "clock.arrow.circlepath"
                    )
                    .font(.callout.weight(.semibold))
                    .foregroundStyle(
                        model.analysisCompleted
                            ? Color.green
                            : VeronicaTheme.secondaryInk
                    )

                    Text(
                        model.analysisCompleted
                            ? "Optimization is available after your confirmation."
                            : "Refresh first so the plan matches your files."
                    )
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                }
                .frame(width: 250, alignment: .leading)
                .padding(10)
                .background(VeronicaTheme.panelFill, in: RoundedRectangle(cornerRadius: 8))
                .overlay {
                    RoundedRectangle(cornerRadius: 8)
                        .strokeBorder(VeronicaTheme.border.opacity(0.65))
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            if let snapshot = model.snapshot {
                HStack(spacing: 12) {
                    resultMetric(
                        "Media files",
                        value: snapshot.activeAssets.formatted(),
                        icon: "photo.on.rectangle"
                    )
                    resultMetric(
                        "Ready actions",
                        value: (snapshot.latestPlan?.remainingExecutableCount
                            ?? snapshot.latestPlan?.executableCount
                            ?? 0).formatted(),
                        icon: "sparkles"
                    )
                    resultMetric(
                        "Already saved",
                        value: ByteCountFormatter.string(
                            fromByteCount: snapshot.totalSavingBytes,
                            countStyle: .file
                        ),
                        icon: "externaldrive"
                    )
                }

                workflowGuide(snapshot: snapshot)
                resultsNextStepCard(snapshot: snapshot)

                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        VStack(alignment: .leading, spacing: 5) {
                            Label("Your folders", systemImage: "folder")
                                .font(.headline)
                                .foregroundStyle(VeronicaTheme.ink)
                            Text("\(snapshot.scanFolders.count) selected")
                                .font(.callout)
                                .foregroundStyle(.secondary)
                        }

                        Spacer()

                        Button("Add Folder") {
                            Task { await model.addScanFolders() }
                        }
                        .disabled(model.isRunningAnnual || model.isAnalyzing)
                    }

                    if snapshot.scanFolders.count > 3 {
                        ScrollView {
                            folderRows(snapshot: snapshot)
                                .padding(.trailing, 4)
                        }
                        .frame(maxHeight: 106)
                    } else {
                        folderRows(snapshot: snapshot)
                    }

                    if !snapshot.unavailableScanFolders.isEmpty {
                        Label {
                            Text("One or more folders no longer exist or cannot be accessed. Remove unavailable folders or add a valid folder to continue.")
                        } icon: {
                            Image(systemName: "exclamationmark.triangle.fill")
                        }
                        .font(.callout)
                        .foregroundStyle(.orange)
                    }
                }
                .padding(12)
                .background(VeronicaTheme.panelFill, in: RoundedRectangle(cornerRadius: 8))
                .overlay {
                    RoundedRectangle(cornerRadius: 8)
                        .strokeBorder(VeronicaTheme.border.opacity(0.65))
                }

                if !snapshot.unresolvedReviews.isEmpty {
                    Button {
                        showingReview = true
                    } label: {
                        HStack(spacing: 12) {
                            Image(systemName: "exclamationmark.circle")
                                .font(.title3)
                            VStack(alignment: .leading, spacing: 4) {
                                Text("A few files need your attention")
                                    .font(.callout.weight(.semibold))
                                Text("\(snapshot.unresolvedReviews.count) quality or track decision(s)")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                            Spacer()
                            Image(systemName: "chevron.right")
                        }
                        .padding(12)
                        .background(VeronicaTheme.accent.opacity(0.08), in: RoundedRectangle(cornerRadius: 14))
                    }
                    .buttonStyle(.plain)
                }

                let readyCount = snapshot.latestPlan?.remainingExecutableCount
                    ?? snapshot.latestPlan?.executableCount
                    ?? 0

                if model.analysisCompleted && !snapshot.archiveAvailable {
                    Label(
                        "A selected folder is unavailable. Reconnect it before optimizing.",
                        systemImage: "folder.badge.questionmark"
                    )
                    .font(.callout)
                    .foregroundStyle(.secondary)
                } else if model.analysisCompleted && !snapshot.preflight.requiredToolsReady {
                    Label(
                        "Some required media tools are unavailable. Open Settings to see what's missing.",
                        systemImage: "exclamationmark.triangle"
                    )
                    .font(.callout)
                    .foregroundStyle(.secondary)
                } else if model.analysisCompleted && readyCount == 0 {
                    Label(
                        "Analysis complete. No automatic changes are ready. Files needing attention can be reviewed separately.",
                        systemImage: "checkmark.circle"
                    )
                    .font(.callout)
                    .foregroundStyle(.secondary)
                }

            }
        }
    }

    private func folderRows(snapshot: UISnapshot) -> some View {
        VStack(spacing: 10) {
            ForEach(snapshot.scanFolders, id: \.self) { folder in
                folderRow(folder, snapshot: snapshot)
            }
        }
    }

    private var optimizingContent: some View {
        VStack(spacing: 24) {
            Image(systemName: "sparkles")
                .font(.system(size: 54, weight: .light))
                .foregroundStyle(VeronicaTheme.accent)

            Text("Optimizing your library")
                .font(.system(size: 34, weight: .semibold))
                .tracking(-1)

            Text("Each replacement is staged and verified before it is committed.")
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)

            if let progress = model.currentProgress {
                ProgressView(value: progress)
                    .frame(maxWidth: 520)
            } else {
                ProgressView()
                    .frame(maxWidth: 520)
            }

            if let event = model.latestEvent {
                VStack(spacing: 7) {
                    Text(event.title)
                        .fontWeight(.medium)
                    if let detail = event.detail {
                        Text(detail)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .lineLimit(2)
                    }
                }
                .frame(maxWidth: 540)
                .padding(22)
                .background(VeronicaTheme.subtleFill, in: RoundedRectangle(cornerRadius: 18))
            }

            Label("Verified originals remain recoverable", systemImage: "checkmark.shield")
                .foregroundStyle(.secondary)
                .font(.callout)
        }
        .frame(maxWidth: .infinity)
        .padding(.top, 90)
    }

    private func resultsNextStepCard(snapshot: UISnapshot) -> some View {
        let readyCount = snapshot.latestPlan?.remainingExecutableCount
            ?? snapshot.latestPlan?.executableCount
            ?? 0
        let reviewCount = snapshot.unresolvedReviews.count

        let title: String
        let description: String
        let icon: String

        if !model.analysisCompleted && !snapshot.archiveAvailable {
            title = "Reconnect your folders"
            description = "One or more folders are unavailable. Reconnect or remove them, then analyze again."
            icon = "folder.badge.questionmark"
        } else if !model.analysisCompleted {
            title = "Ready for a fresh look"
            description = "Analyze your library again to refresh these results before making changes."
            icon = "arrow.clockwise"
        } else if !snapshot.archiveAvailable {
            title = "Reconnect your folders"
            description = "One or more folders are unavailable. Reconnect them before continuing."
            icon = "folder.badge.questionmark"
        } else if !snapshot.preflight.requiredToolsReady {
            title = "A little setup is needed"
            description = "Some required media tools are unavailable. Check Settings before optimizing."
            icon = "wrench.and.screwdriver"
        } else if readyCount > 0 {
            title = "You're ready for the next step"
            description = "\(readyCount) media items are ready for optimization. Veronica will verify replacements before committing them."
            icon = "checkmark.shield"
        } else if reviewCount > 0 {
            title = "A few files need your decision"
            description = "\(reviewCount) item(s) may change quality, timing, tracks, or date organization if optimized."
            icon = "hand.raised"
        } else {
            title = "Your library is looking good"
            description = "There are no automatic optimizations ready right now."
            icon = "checkmark.seal"
        }

        return HStack(alignment: .top, spacing: 16) {
            Image(systemName: icon)
                .font(.system(size: 21, weight: .medium))
                .foregroundStyle(VeronicaTheme.accent)
                .frame(width: 38, height: 38)
                .background(
                    VeronicaTheme.accent.opacity(0.10),
                    in: RoundedRectangle(cornerRadius: 8)
                )

            VStack(alignment: .leading, spacing: 6) {
                Text(title)
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundStyle(VeronicaTheme.ink)

                Text(description)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)

                if !model.analysisCompleted {
                    Button {
                        Task { await model.analyzeLibrary() }
                    } label: {
                        Label("Analyze Library", systemImage: "magnifyingglass")
                            .font(.system(size: 14, weight: .semibold))
                            .padding(.horizontal, 8)
                            .padding(.vertical, 3)
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
                    .disabled(
                        !model.hasLiveSnapshot
                        || !snapshot.archiveAvailable
                        || model.isAnalyzing
                        || model.isRunningAnnual
                    )
                    .padding(.top, 3)
                } else if readyCount > 0 {
                    Button {
                        confirmOptimize = true
                    } label: {
                        Label("Optimize Library", systemImage: "sparkles")
                            .font(.system(size: 14, weight: .semibold))
                            .padding(.horizontal, 8)
                            .padding(.vertical, 3)
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
                    .disabled(!canOptimize)
                    .padding(.top, 3)
                } else {
                    Button {
                        Task { await model.analyzeLibrary() }
                    } label: {
                        Label("Analyze Again", systemImage: "arrow.clockwise")
                            .font(.system(size: 14, weight: .semibold))
                            .padding(.horizontal, 8)
                            .padding(.vertical, 3)
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.large)
                    .disabled(!model.hasLiveSnapshot)
                    .padding(.top, 3)
                }

                if model.analysisCompleted && readyCount > 0 && reviewCount > 0 {
                    Label(
                        "\(reviewCount) additional items need separate review",
                        systemImage: "info.circle"
                    )
                    .font(.caption)
                    .foregroundStyle(.secondary)
                }
            }

            Spacer(minLength: 0)
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            VeronicaTheme.accent.opacity(0.045),
            in: RoundedRectangle(cornerRadius: 8, style: .continuous)
        )
        .overlay {
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .strokeBorder(VeronicaTheme.accent.opacity(0.15))
        }
    }

    private func workflowGuide(snapshot: UISnapshot) -> some View {
        let readyCount = snapshot.latestPlan?.remainingExecutableCount
            ?? snapshot.latestPlan?.executableCount
            ?? 0

        return HStack(spacing: 0) {
            workflowStep(
                number: "1",
                title: "Choose folders",
                detail: snapshot.scanFolders.isEmpty
                    ? "Add the folders Veronica may scan."
                    : "\(snapshot.scanFolders.count) folder selected",
                isActive: snapshot.scanFolders.isEmpty
            )

            workflowConnector()

            workflowStep(
                number: "2",
                title: "Analyze",
                detail: model.analysisCompleted
                    ? "Current plan is ready."
                    : "Refresh the plan before changes.",
                isActive: !model.analysisCompleted
            )

            workflowConnector()

            workflowStep(
                number: "3",
                title: "Review",
                detail: snapshot.unresolvedReviews.isEmpty
                    ? "No manual review pending."
                    : "\(snapshot.unresolvedReviews.count) item(s) need review",
                isActive: !snapshot.unresolvedReviews.isEmpty
            )

            workflowConnector()

            workflowStep(
                number: "4",
                title: "Optimize",
                detail: readyCount == 0
                    ? "No ready actions pending."
                    : "\(readyCount) verified action(s) ready",
                isActive: model.analysisCompleted && readyCount > 0
            )
        }
        .padding(11)
        .background(VeronicaTheme.panelFill, in: RoundedRectangle(cornerRadius: 8))
        .overlay {
            RoundedRectangle(cornerRadius: 8)
                .strokeBorder(VeronicaTheme.border.opacity(0.65))
        }
    }

    private func workflowStep(
        number: String,
        title: String,
        detail: String,
        isActive: Bool
    ) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Text(number)
                    .font(.caption.weight(.bold))
                    .foregroundStyle(isActive ? Color.white : VeronicaTheme.secondaryInk)
                    .frame(width: 22, height: 22)
                    .background(
                        isActive
                            ? VeronicaTheme.accent
                            : VeronicaTheme.subtleFill,
                        in: Circle()
                    )

                Text(title)
                    .font(.callout.weight(.semibold))
            }

            Text(detail)
                .font(.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func workflowConnector() -> some View {
        Rectangle()
            .fill(VeronicaTheme.border.opacity(0.7))
            .frame(width: 18, height: 1)
            .padding(.horizontal, 8)
    }

    private func reassurance(_ title: String, icon: String) -> some View {
        Label(title, systemImage: icon)
            .font(.caption)
            .foregroundStyle(.secondary)
    }

    private func resultMetric(_ title: String, value: String, icon: String) -> some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack {
                Image(systemName: icon)
                    .foregroundStyle(VeronicaTheme.accent)
                    .font(.title3)

                Spacer()
            }

            Text(value)
                .font(.system(size: 23, weight: .semibold))
                .minimumScaleFactor(0.7)
                .lineLimit(1)

            Text(title)
                .font(.callout)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(13)
        .background(VeronicaTheme.panelFill, in: RoundedRectangle(cornerRadius: 8))
        .overlay {
            RoundedRectangle(cornerRadius: 8)
                .strokeBorder(VeronicaTheme.border.opacity(0.65))
        }
    }

    private func folderRow(_ folder: String, snapshot: UISnapshot) -> some View {
        HStack(spacing: 12) {
            Image(systemName: "folder.fill")
                .foregroundStyle(VeronicaTheme.accent)

            VStack(alignment: .leading, spacing: 3) {
                Text(URL(fileURLWithPath: folder).lastPathComponent)
                    .fontWeight(.medium)
                Text(folder)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }

            Spacer()

            if snapshot.unavailableScanFolders.contains(folder) {
                Label("Unavailable", systemImage: "exclamationmark.triangle.fill")
                    .font(.caption)
                    .foregroundStyle(.orange)
            } else {
                Image(systemName: "checkmark.circle.fill")
                    .foregroundStyle(.green)
            }

            Button {
                Task { await model.removeScanFolder(folder) }
            } label: {
                Image(systemName: "minus.circle")
            }
            .buttonStyle(.borderless)
            .help("Remove this folder from Veronica")
            .disabled(model.isAnalyzing || model.isRunningAnnual)
        }
    }

    private func secondarySheet<Content: View>(
        _ title: String,
        size: CGSize,
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(spacing: 0) {
            HStack {
                Text(title)
                    .font(.headline)
                Spacer()
                Button("Done") {
                    showingHistory = false
                    showingSettings = false
                    showingReview = false
                }
                .accessibilityIdentifier("veronica.closeSheet")
            }
            .padding(20)

            Divider()

            content()
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .frame(
            width: size.width,
            height: size.height
        )
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
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var isBreathing = false

    var body: some View {
        VStack(spacing: 30) {
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
            .frame(height: 190)
            .accessibilityHidden(true)

            VStack(spacing: 10) {
                Text("Getting to know your library")
                    .font(.system(size: 34, weight: .semibold))
                    .tracking(-1)
                    .multilineTextAlignment(.center)

                Text("Finding thoughtful ways to make more room for what matters.")
                    .font(.system(size: 15))
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: 440)
            }

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
                    Text("Discovering opportunities")
                        .font(.system(size: 15, weight: .semibold))

                    Text("Checking your media for safe ways to save space.")
                        .font(.system(size: 13))
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }

                Spacer(minLength: 8)

                ProgressView()
                    .controlSize(.small)
                    .accessibilityLabel("Analysis in progress")
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
        }
        .frame(maxWidth: .infinity)
        .padding(.top, 48)
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
