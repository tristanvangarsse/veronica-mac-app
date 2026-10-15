import AppKit
import Foundation
import SwiftUI

@MainActor
final class AppModel: ObservableObject {
    @Published var snapshot: UISnapshot?
    @Published var isLoading = false

    // A cached snapshot may be displayed immediately at launch, but only a
    // snapshot fetched successfully during this app session is considered
    // live enough to authorize maintenance.
    @Published private(set) var hasLiveSnapshot = false

    @Published var isRunningAnnual = false
    @Published var isAnalyzing = false
    @Published var analysisCompleted = false
    @Published var analysisActivity = ""
    @Published var errorMessage: String?
    @Published var activityLines: [String] = []
    @Published var events: [EngineEvent] = []
    @Published var developerMode = DiagnosticsCenter.shared.developerMode
    @Published var notificationsEnabled = NotificationManager.shared.isEnabled
    @Published var notificationStatus = NotificationManager.shared.statusLabel

    // Immediate UI state for the media-processing toggles.
    // The engine remains the durable source of truth; refresh() reconciles these.
    @Published var processImages = true
    @Published var processVideos = true
    @Published var processAudio = true
    @Published var imageExtensions = Set(MediaProcessingPolicy.allImageExtensions)
    @Published var videoExtensions = Set(MediaProcessingPolicy.allVideoExtensions)
    @Published var audioExtensions = Set(MediaProcessingPolicy.allAudioExtensions)
    @Published var isUpdatingMediaProcessing = false

    // Media switches are intentionally optimistic. Multiple quick changes are
    // coalesced and persisted serially so a slow engine write never drops a
    // later click.
    private var mediaProcessingSaveRequested = false

    private let snapshotCacheURL: URL
    private let notifications = NotificationManager.shared

    init() {
        let fm = FileManager.default
        let appSupport = fm.urls(
            for: .applicationSupportDirectory,
            in: .userDomainMask
        ).first ?? fm.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support", isDirectory: true)

#if DEBUG
        let directory: URL
        if let stateDir = ProcessInfo.processInfo.environment["VERONICA_STATE_DIR"],
           !stateDir.isEmpty {
            directory = URL(fileURLWithPath: stateDir, isDirectory: true)
        } else {
            directory = appSupport
                .appendingPathComponent("Veronica", isDirectory: true)
        }
#else
        let directory = appSupport
            .appendingPathComponent("Veronica", isDirectory: true)
#endif

        snapshotCacheURL = directory
            .appendingPathComponent("ui-snapshot-cache.json")

        loadCachedSnapshot()
    }

    func prepareNotifications() async {
        await notifications.prepare()
        syncNotificationState()
    }

    func setNotificationsEnabled(_ enabled: Bool) {
        notificationsEnabled = enabled
        Task { @MainActor in
            await notifications.setEnabled(enabled)
            syncNotificationState()
        }
    }

    func requestNotificationPermission() {
        Task { @MainActor in
            await notifications.requestAuthorizationIfNeeded()
            syncNotificationState()
        }
    }

    func sendTestNotification() {
        Task { @MainActor in
            await notifications.notify(
                title: "Veronica notifications are working",
                body: "You will see messages when analysis or optimization finishes.",
                identifier: "settings-test-\(UUID().uuidString)"
            )
            syncNotificationState()
        }
    }

    func openNotificationSettings() {
        if let url = URL(string: "x-apple.systempreferences:com.apple.Notifications-Settings.extension") {
            NSWorkspace.shared.open(url)
        }
    }

    private func syncNotificationState() {
        notificationsEnabled = notifications.isEnabled
        notificationStatus = notifications.statusLabel
    }

    private func loadCachedSnapshot() {
        do {
            let data = try Data(contentsOf: snapshotCacheURL)
            let cached = try JSONDecoder().decode(UISnapshot.self, from: data)

            snapshot = cached
            syncMediaProcessingState(cached.mediaProcessing)

            DiagnosticsCenter.shared.log(
                "INFO",
                "App",
                "Loaded cached UI snapshot"
            )
        } catch {
            // A missing, outdated, or corrupt cache is equivalent to having no
            // cache. The normal live refresh will populate state shortly.
            snapshot = nil
        }
    }

    private func cacheSnapshot(_ snapshot: UISnapshot) {
        do {
            let directory = snapshotCacheURL.deletingLastPathComponent()

            try FileManager.default.createDirectory(
                at: directory,
                withIntermediateDirectories: true
            )

            let encoder = JSONEncoder()
            let data = try encoder.encode(snapshot)

            try data.write(
                to: snapshotCacheURL,
                options: .atomic
            )
        } catch {
            DiagnosticsCenter.shared.log(
                "ERROR",
                "App",
                "Could not cache UI snapshot: \(error.localizedDescription)"
            )
        }
    }

    @discardableResult
    private func requireLiveSnapshot() -> Bool {
        guard hasLiveSnapshot else {
            errorMessage = "Veronica is still refreshing its live state. Wait a moment, then try again."
            return false
        }

        return true
    }

    var sortedEnabledImageExtensions: [String] {
        MediaProcessingPolicy.allImageExtensions.filter { imageExtensions.contains($0) }
    }

    var sortedEnabledVideoExtensions: [String] {
        MediaProcessingPolicy.allVideoExtensions.filter { videoExtensions.contains($0) }
    }

    var sortedEnabledAudioExtensions: [String] {
        MediaProcessingPolicy.allAudioExtensions.filter { audioExtensions.contains($0) }
    }

    private func syncMediaProcessingState(_ policy: MediaProcessingPolicy) {
        imageExtensions = Set(policy.imageExtensions)
        videoExtensions = Set(policy.videoExtensions)
        audioExtensions = Set(policy.audioExtensions)
        processImages = !imageExtensions.isEmpty
        processVideos = !videoExtensions.isEmpty
        processAudio = !audioExtensions.isEmpty
    }

    func refresh() async {
        DiagnosticsCenter.shared.log("INFO", "App", "Refreshing UI snapshot")
        isLoading = true
        hasLiveSnapshot = false

        defer {
            isLoading = false
        }

        do {
            let refreshed = try await EngineRunner.shared.snapshot()

            snapshot = refreshed
            hasLiveSnapshot = true

            syncMediaProcessingState(refreshed.mediaProcessing)

            cacheSnapshot(refreshed)

            let missing = refreshed.preflight.missingRequirements
            if missing.isEmpty {
                errorMessage = nil
            } else {
                errorMessage = "Veronica is missing required dependencies: \(missing.joined(separator: ", ")). Install them, then refresh or relaunch Veronica. Maintenance will remain disabled until they are available."
            }
        } catch {
            errorMessage = error.localizedDescription
            DiagnosticsCenter.shared.log(
                "ERROR",
                "App",
                "Snapshot refresh failed: \(error.localizedDescription)"
            )
        }
    }

    func updateMediaProcessing(
        images: Bool? = nil,
        videos: Bool? = nil,
        audio: Bool? = nil,
        imageExtensions: Set<String>? = nil,
        videoExtensions: Set<String>? = nil,
        audioExtensions: Set<String>? = nil
    ) async {
        guard requireLiveSnapshot() else { return }

        // Update the visible controls immediately.
        if let images {
            processImages = images
        }
        if let videos {
            processVideos = videos
        }
        if let audio {
            processAudio = audio
        }
        if let imageExtensions {
            self.imageExtensions = imageExtensions
            processImages = !imageExtensions.isEmpty
        }
        if let videoExtensions {
            self.videoExtensions = videoExtensions
            processVideos = !videoExtensions.isEmpty
        }
        if let audioExtensions {
            self.audioExtensions = audioExtensions
            processAudio = !audioExtensions.isEmpty
        }

        mediaProcessingSaveRequested = true

        // If a persistence loop is already running, it will pick up the
        // current values before it finishes. Do not discard this click.
        guard !isUpdatingMediaProcessing else { return }

        isUpdatingMediaProcessing = true
        defer { isUpdatingMediaProcessing = false }

        while mediaProcessingSaveRequested {
            // Clear the request and briefly debounce. Any clicks arriving
            // during this pause update the published values above.
            mediaProcessingSaveRequested = false
            try? await Task.sleep(nanoseconds: 300_000_000)

            // The values below are the newest combined state. Clear the flag
            // again so only changes that arrive during the engine command
            // cause another pass through the loop.
            mediaProcessingSaveRequested = false

            let targetImages = processImages
            let targetVideos = processVideos
            let targetAudio = processAudio
            let targetImageExtensions = sortedEnabledImageExtensions
            let targetVideoExtensions = sortedEnabledVideoExtensions
            let targetAudioExtensions = sortedEnabledAudioExtensions

            do {
                try await EngineRunner.shared.configureMediaProcessing(
                    images: targetImages,
                    videos: targetVideos,
                    audio: targetAudio,
                    imageExtensions: targetImageExtensions,
                    videoExtensions: targetVideoExtensions,
                    audioExtensions: targetAudioExtensions
                )

                DiagnosticsCenter.shared.log(
                    "INFO",
                    "App",
                    "Saved media processing settings: image_extensions=\(targetImageExtensions), video_extensions=\(targetVideoExtensions), audio_extensions=\(targetAudioExtensions)"
                )
            } catch {
                mediaProcessingSaveRequested = false

                errorMessage = error.localizedDescription
                DiagnosticsCenter.shared.log(
                    "ERROR",
                    "App",
                    "Could not update media processing settings: \(error.localizedDescription)"
                )

                // Persistence failed, so reload the durable engine state.
                await refresh()
                return
            }
        }
    }

    func updateFilenamePolicy(
        enabled: Bool? = nil,
        dateFormat: String? = nil,
        maxBytes: Int? = nil
    ) async {
        guard requireLiveSnapshot() else { return }

        guard let current = snapshot?.filenamePolicy else { return }

        let nextEnabled = enabled ?? current.enabled
        let nextDateFormat = dateFormat ?? current.dateFormat
        let nextMaxBytes = maxBytes ?? current.maxBytes

        do {
            try await EngineRunner.shared.configureFilenames(
                enabled: nextEnabled,
                dateFormat: nextDateFormat,
                maxBytes: nextMaxBytes
            )
            await refresh()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func updateOptimizationSettings(
        imageFormat: String? = nil,
        imageMaxMegapixels: Double? = nil,
        jpegQuality: Int? = nil,
        videoMaxEdge: Int? = nil,
        audioMinSizeMB: Int? = nil,
        videoAllowCameraMetadataDrop: Bool? = nil
    ) async {
        guard requireLiveSnapshot() else { return }
        guard let current = snapshot?.optimizationSettings else { return }

        do {
            try await EngineRunner.shared.configureOptimization(
                imageFormat: imageFormat ?? current.imageOutputFormat,
                imageMaxMegapixels: imageMaxMegapixels ?? current.imageMaxMegapixels,
                jpegQuality: jpegQuality ?? current.jpegQuality,
                videoMaxEdge: videoMaxEdge ?? current.videoMaxEdge,
                audioMinSizeMB: audioMinSizeMB ?? current.audioMinSizeMB,
                videoAllowCameraMetadataDrop: videoAllowCameraMetadataDrop ?? current.videoAllowCameraMetadataDrop
            )
            analysisCompleted = false
            await refresh()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func restoreRecommendedOptimizationSettings() async {
        guard requireLiveSnapshot() else { return }
        let recommended = OptimizationSettings.recommended

        do {
            try await EngineRunner.shared.configureOptimization(
                imageFormat: recommended.imageOutputFormat,
                imageMaxMegapixels: recommended.imageMaxMegapixels,
                jpegQuality: recommended.jpegQuality,
                videoMaxEdge: recommended.videoMaxEdge,
                audioMinSizeMB: recommended.audioMinSizeMB,
                videoAllowCameraMetadataDrop: recommended.videoAllowCameraMetadataDrop
            )
            analysisCompleted = false
            await refresh()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func updateDateScope(
        mode: String,
        start: String? = nil,
        end: String? = nil
    ) async {
        guard requireLiveSnapshot() else { return }

        do {
            try await EngineRunner.shared.configureDateScope(
                mode: mode,
                start: start,
                end: end
            )
            await refresh()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func addScanFolders() async {
        guard requireLiveSnapshot() else { return }

        let panel = NSOpenPanel()
        panel.title = "Add Folders"
        panel.message = "Choose one or more folders Veronica should scan."
        panel.prompt = "Add"
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = true
        panel.canCreateDirectories = false

        if let current = snapshot?.scanFolders.first {
            panel.directoryURL = URL(fileURLWithPath: current)
        }

        guard panel.runModal() == .OK else { return }

        await addScanFolderURLs(panel.urls)
    }

    func addScanFolderURLs(_ urls: [URL]) async {
        guard requireLiveSnapshot() else { return }
        guard !isAnalyzing && !isRunningAnnual else {
            errorMessage = "Wait for the current operation to finish before adding folders."
            return
        }

        let folders = urls.filter { url in
            var isDirectory: ObjCBool = false
            return url.isFileURL
                && FileManager.default.fileExists(
                    atPath: url.path,
                    isDirectory: &isDirectory
                )
                && isDirectory.boolValue
        }

        guard folders.count == urls.count, !folders.isEmpty else {
            errorMessage = "Drop folders, not individual files."
            return
        }

        let paths = Array(Set(folders.map {
            $0.standardizedFileURL.resolvingSymlinksInPath().path
        })).sorted()

        do {
            try await EngineRunner.shared.addScanFolders(paths)
            analysisCompleted = false
            await refresh()

            if hasLiveSnapshot {
                await analyzeLibrary()
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func removeScanFolder(_ path: String) async {
        guard requireLiveSnapshot() else { return }

        do {
            try await EngineRunner.shared.removeScanFolder(path)
            analysisCompleted = false
            await refresh()

            if hasLiveSnapshot && snapshot?.configured == true {
                await analyzeLibrary()
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func analyzeLibrary() async {
        guard requireLiveSnapshot() else { return }
        guard !isAnalyzing && !isRunningAnnual else { return }

        guard snapshot?.configured == true,
              snapshot?.archiveAvailable == true else {
            let message = "Choose an available folder before analyzing."
            errorMessage = message
            await notifications.notify(
                title: "Veronica analysis stopped",
                body: message,
                identifier: "analysis-not-ready"
            )
            return
        }

        isAnalyzing = true
        analysisCompleted = false
        analysisActivity = "Preparing analysis…"
        errorMessage = nil

        defer { isAnalyzing = false }

        do {
            try await EngineRunner.shared.analyzeAll { chunk in
                Task { @MainActor in
                    let lines = chunk.split(
                        separator: "\n",
                        omittingEmptySubsequences: true
                    )
                    if let last = lines.last {
                        self.analysisActivity = String(last)
                    }
                }
            }
            await refresh()
            guard hasLiveSnapshot else {
                analysisActivity = "Analysis completed, but results could not be loaded"
                return
            }
            analysisCompleted = true
            analysisActivity = "Analysis complete"
            let readyCount = snapshot?.latestPlan?.remainingExecutableCount
                ?? snapshot?.latestPlan?.executableCount
                ?? 0
            let reviewCount = snapshot?.unresolvedReviews.count ?? 0
            await notifications.notify(
                title: "Veronica analysis complete",
                body: "\(readyCount) ready action(s), \(reviewCount) item(s) needing review.",
                identifier: "analysis-complete"
            )
        } catch {
            errorMessage = error.localizedDescription
            analysisActivity = "Analysis could not be completed"
            await notifications.notify(
                title: "Veronica analysis stopped",
                body: error.localizedDescription,
                identifier: "analysis-failed"
            )
        }
    }

    func runAnnual() async {
        guard requireLiveSnapshot() else { return }

        guard !isRunningAnnual else { return }

        guard snapshot?.configured == true else {
            let message = "Add at least one folder before running maintenance."
            errorMessage = message
            await notifications.notify(
                title: "Veronica optimization stopped",
                body: message,
                identifier: "maintenance-not-configured"
            )
            return
        }
        guard snapshot?.archiveAvailable == true else {
            let message = "One or more configured folders are currently unavailable."
            errorMessage = message
            await notifications.notify(
                title: "Veronica optimization stopped",
                body: message,
                identifier: "maintenance-folder-unavailable"
            )
            return
        }

        guard snapshot?.preflight.requiredToolsReady == true else {
            let message = "Veronica is missing one or more required media tools. Open Settings to see what is unavailable."
            errorMessage = message
            await notifications.notify(
                title: "Veronica optimization stopped",
                body: message,
                identifier: "maintenance-tools-unavailable"
            )
            return
        }

        isRunningAnnual = true
        activityLines = []
        events = []
        errorMessage = nil

        let eventURL = FileManager.default.temporaryDirectory.appendingPathComponent("veronica-events-\(UUID().uuidString).jsonl")
        let pollTask = Task { [weak self] in
            while !Task.isCancelled {
                self?.loadEvents(from: eventURL)
                try? await Task.sleep(nanoseconds: 250_000_000)
            }
        }

        defer {
            pollTask.cancel()
            loadEvents(from: eventURL)
            try? FileManager.default.removeItem(at: eventURL)
            isRunningAnnual = false
        }

        do {
            let result = try await EngineRunner.shared.run(["annual-all", "--yes", "--events-jsonl", eventURL.path]) { chunk in
                Task { @MainActor in
                    let newLines = chunk.split(separator: "\n", omittingEmptySubsequences: true).map(String.init)
                    self.activityLines.append(contentsOf: newLines)
                }
            }
            loadEvents(from: eventURL)
            if result.exitCode != 0 {
                errorMessage = "Maintenance stopped safely. Review the Activity and Review screens for details."
                await notifications.notify(
                    title: "Veronica stopped safely",
                    body: "Review Activity and Review Details before continuing.",
                    identifier: "maintenance-stopped"
                )
            } else {
                await refresh()
                let saved = snapshot.map {
                    ByteCountFormatter.string(
                        fromByteCount: $0.totalSavingBytes,
                        countStyle: .file
                    )
                } ?? "space"
                let reviewCount = snapshot?.unresolvedReviews.count ?? 0
                await notifications.notify(
                    title: "Veronica optimization complete",
                    body: "Saved \(saved). \(reviewCount) item(s) still need review.",
                    identifier: "maintenance-complete"
                )
                return
            }
            await refresh()
        } catch {
            errorMessage = error.localizedDescription
            await notifications.notify(
                title: "Veronica optimization stopped",
                body: error.localizedDescription,
                identifier: "maintenance-failed"
            )
        }
    }

    private func loadEvents(from url: URL) {
        guard let data = try? Data(contentsOf: url), !data.isEmpty,
              let text = String(data: data, encoding: .utf8) else { return }
        let decoder = JSONDecoder()
        let decoded = text.split(separator: "\n").compactMap { line -> EngineEvent? in
            guard let d = String(line).data(using: .utf8) else { return nil }
            return try? decoder.decode(EngineEvent.self, from: d)
        }
        if !decoded.isEmpty { events = decoded }
    }

    func keepAsIs(_ item: ReviewItem) async {
        guard requireLiveSnapshot() else { return }

        guard let plan = item.planPath else {
            errorMessage = "This review item is missing its immutable plan path."
            return
        }
        do {
            let result = try await EngineRunner.shared.run([
                "resolve-review",
                "--state-dir", item.stateDir,
                "--plan", plan,
                "--relpath", item.relpath,
                "--resolution", "KEEP_AS_IS",
                "--note", "Reviewed in Veronica.app; preserve original.",
                "--yes"
            ])
            guard result.exitCode == 0 else {
                errorMessage = result.stderr.isEmpty ? result.stdout : result.stderr
                return
            }
            await refresh()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func processNormally(_ item: ReviewItem) async {
        guard requireLiveSnapshot() else { return }

        guard item.canProcessNormally else {
            errorMessage = "This review issue cannot safely be bypassed."
            return
        }
        guard let plan = item.planPath else {
            errorMessage = "This review item is missing its immutable plan path."
            return
        }

        do {
            let result = try await EngineRunner.shared.run([
                "resolve-review",
                "--state-dir", item.stateDir,
                "--plan", plan,
                "--relpath", item.relpath,
                "--resolution", "PROCESS_NORMALLY",
                "--note", "Reviewed in Veronica.app; allow normal policy evaluation.",
                "--yes"
            ])

            guard result.exitCode == 0 else {
                errorMessage = result.stderr.isEmpty ? result.stdout : result.stderr
                return
            }

            await refresh()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func reveal(_ path: String?) {
        guard let path else { return }
        NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: path)])
    }

    func revealReview(_ item: ReviewItem) {
        reveal(URL(fileURLWithPath: item.root).appendingPathComponent(item.relpath).path)
    }

    func setDeveloperMode(_ enabled: Bool) {
        developerMode = enabled
        DiagnosticsCenter.shared.developerMode = enabled
        DiagnosticsCenter.shared.log("INFO", "Diagnostics", "Developer mode \(enabled ? "enabled" : "disabled")")
    }

    func copyDiagnosticReport() {
        let report = DiagnosticsCenter.shared.privacySafeReport(snapshot: snapshot, errorMessage: errorMessage, events: events)
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(report, forType: .string)
        DiagnosticsCenter.shared.log("INFO", "Diagnostics", "Copied privacy-safe diagnostic report")
    }

    func exportDiagnostics() {
        let panel = NSSavePanel()
        panel.title = "Export Veronica Diagnostics"
        panel.nameFieldStringValue = "Veronica-Diagnostics.zip"
        panel.allowedContentTypes = [.zip]
        guard panel.runModal() == .OK, let url = panel.url else { return }
        do {
            try DiagnosticsCenter.shared.exportDiagnostics(to: url, snapshot: snapshot, errorMessage: errorMessage, events: events)
            DiagnosticsCenter.shared.log("INFO", "Diagnostics", "Exported privacy-safe diagnostics ZIP")
        } catch {
            errorMessage = error.localizedDescription
            DiagnosticsCenter.shared.log("ERROR", "Diagnostics", "Export failed: \(error.localizedDescription)")
        }
    }

    func revealLogFile() {
        let url = DiagnosticsCenter.shared.logURL
        try? FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        if !FileManager.default.fileExists(atPath: url.path) {
            FileManager.default.createFile(atPath: url.path, contents: Data())
        }
        NSWorkspace.shared.activateFileViewerSelecting([url])
    }

    func revealStateDirectory() {
        reveal(snapshot?.stateDir)
    }

    var latestEvent: EngineEvent? { events.last }

    var currentProgress: Double? {
        guard let event = events.last(where: { $0.index != nil && $0.total != nil }),
              let index = event.index, let total = event.total, total > 0 else { return nil }
        return min(max(Double(index) / Double(total), 0), 1)
    }
}
