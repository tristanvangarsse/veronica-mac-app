import AppKit
import Foundation
import SwiftUI

@MainActor
final class AppModel: ObservableObject {
    @Published var snapshot: UISnapshot?
    @Published var isLoading = false

    // File lists and scan decisions exist only for this launch.
    @Published private(set) var hasLiveSnapshot = false

    @Published var isRunningAnnual = false
    @Published var isAnalyzing = false
    @Published private(set) var isCancellingAnalysis = false
    @Published private(set) var analysisCancelled = false
    @Published private(set) var isSavingSettings = false
    @Published private(set) var isSavingFileDate = false
    @Published var analysisCompleted = false
    @Published private(set) var cleanupCompleted = false
    @Published private(set) var cleanupOutcome: CleanupOutcome?
    @Published var analysisActivity = ""
    @Published private(set) var analysisProgress: AnalysisProgress?
    @Published var errorMessage: String?
    @Published private(set) var maintenanceFailure: String?
    @Published var activityLines: [String] = []
    @Published var events: [EngineEvent] = []
    @Published var developerMode = DiagnosticsCenter.shared.developerMode

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
    private var analysisTask: Task<Void, Error>?

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
            try await EngineRunner.shared.prepareForLaunch()
            let refreshed = try await EngineRunner.shared.snapshot()

            snapshot = refreshed
            hasLiveSnapshot = true

            syncMediaProcessingState(refreshed.mediaProcessing)

            let missing = refreshed.preflight.missingRequirements
            if missing.isEmpty {
                errorMessage = nil
            } else {
                errorMessage = "Veronica could not load some built-in components. Reinstall the complete Veronica app, then reopen it. Your files have not been changed."
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

    private func performSettingsUpdate(
        invalidatesAnalysis: Bool,
        operation: () async throws -> Void
    ) async throws {
        guard hasLiveSnapshot else {
            throw EngineRunnerError.operationUnavailable("Wait for Veronica to finish refreshing, then try again.")
        }
        guard !isAnalyzing && !isRunningAnnual && !isSavingSettings && !isSavingFileDate else {
            throw EngineRunnerError.operationUnavailable("Wait for the current operation to finish before changing settings.")
        }
        isSavingSettings = true
        defer { isSavingSettings = false }
        do {
            try await operation()
            if invalidatesAnalysis {
                analysisCompleted = false
                analysisActivity = "Folder settings changed. Analyze again before optimizing."
            }
            await refresh()
            guard hasLiveSnapshot else {
                throw EngineRunnerError.operationUnavailable("Settings were saved, but Veronica could not reload them. Refresh before continuing.")
            }
        } catch {
            errorMessage = error.localizedDescription
            throw error
        }
    }

    func saveFolderSettings(folder: String, recipe: ProcessingRecipe) async throws {
        try await performSettingsUpdate(invalidatesAnalysis: true) {
            try await EngineRunner.shared.saveFolderSettings(folder: folder, recipe: recipe)
        }
    }

    func applyPreset(folder: String, presetID: String) async throws {
        try await performSettingsUpdate(invalidatesAnalysis: true) {
            try await EngineRunner.shared.applyPreset(folder: folder, presetID: presetID)
        }
    }

    @discardableResult
    func savePreset(name: String, recipe: ProcessingRecipe, presetID: String? = nil) async throws -> SettingsPreset {
        var saved: SettingsPreset?
        try await performSettingsUpdate(invalidatesAnalysis: false) {
            saved = try await EngineRunner.shared.savePreset(name: name, recipe: recipe, presetID: presetID)
        }
        guard let saved else { throw EngineRunnerError.operationUnavailable("The preset could not be saved. Try again.") }
        return saved
    }

    func deletePreset(presetID: String) async throws {
        try await performSettingsUpdate(invalidatesAnalysis: false) {
            try await EngineRunner.shared.deletePreset(presetID: presetID)
        }
    }

    func setDefaultPreset(presetID: String) async throws {
        try await performSettingsUpdate(invalidatesAnalysis: false) {
            try await EngineRunner.shared.setDefaultPreset(presetID: presetID)
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
        do {
            try await EngineRunner.shared.restoreManualDefaults()
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
        guard !isAnalyzing && !isRunningAnnual && !isSavingSettings && !isSavingFileDate else {
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
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func removeScanFolder(_ path: String) async {
        guard requireLiveSnapshot() else { return }
        guard !isAnalyzing && !isRunningAnnual && !isSavingSettings && !isSavingFileDate else { return }

        do {
            try await EngineRunner.shared.removeScanFolder(path)
            analysisCompleted = false
            await refresh()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func analyzeLibrary() async {
        guard requireLiveSnapshot() else { return }
        guard !isAnalyzing && !isRunningAnnual && !isSavingSettings && !isSavingFileDate else { return }

        guard snapshot?.configured == true,
              snapshot?.archiveAvailable == true else {
            let message = "Choose an available folder before analyzing."
            errorMessage = message
            return
        }

        isAnalyzing = true
        cleanupOutcome = nil
        isCancellingAnalysis = false
        analysisCancelled = false
        analysisCompleted = false
        cleanupCompleted = false
        analysisActivity = "Preparing analysis…"
        analysisProgress = nil
        errorMessage = nil

        let progressURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("veronica-analysis-\(UUID().uuidString).jsonl")
        let pollTask = Task { [weak self] in
            while !Task.isCancelled {
                self?.loadAnalysisProgress(from: progressURL)
                try? await Task.sleep(nanoseconds: 250_000_000)
            }
        }

        defer {
            pollTask.cancel()
            try? FileManager.default.removeItem(at: progressURL)
            isAnalyzing = false
            isCancellingAnalysis = false
            analysisTask = nil
            analysisProgress = nil
        }

        do {
            let task = Task {
                try await EngineRunner.shared.analyzeAll(eventsURL: progressURL) { chunk in
                    Task { @MainActor in
                        guard self.isAnalyzing && !self.isCancellingAnalysis else { return }
                        let lines = chunk.split(separator: "\n", omittingEmptySubsequences: true)
                        if let last = lines.last {
                            self.analysisActivity = String(last)
                        }
                    }
                }
            }
            analysisTask = task
            try await withTaskCancellationHandler(operation: {
                try await task.value
            }, onCancel: { task.cancel() })
            try Task.checkCancellation()
            guard !isCancellingAnalysis else { throw CancellationError() }
            await refresh()
            guard !isCancellingAnalysis else { throw CancellationError() }
            guard hasLiveSnapshot else {
                analysisActivity = "Analysis completed, but results could not be loaded"
                return
            }
            analysisCompleted = true
            analysisActivity = "Analysis complete"
            if (snapshot?.pendingStagedOutputs ?? 0) == 0 {
                maintenanceFailure = nil
            }
        } catch {
            if error is CancellationError || isCancellingAnalysis {
                analysisCancelled = true
                analysisActivity = "Scan cancelled"
                await refresh()
            } else {
                errorMessage = error.localizedDescription
                analysisActivity = "Analysis could not be completed"
            }
        }
    }

    func cancelAnalysis() {
        guard isAnalyzing && !isCancellingAnalysis else { return }
        isCancellingAnalysis = true
        analysisActivity = "Cancelling scan…"
        analysisTask?.cancel()
    }

    private func loadAnalysisProgress(from url: URL) {
        guard let text = try? String(contentsOf: url, encoding: .utf8) else { return }
        // The writer may still be appending its final line. Use the newest
        // complete record so a partial write never resets visible progress.
        for line in text.split(separator: "\n").reversed() {
            if let progress = try? JSONDecoder().decode(AnalysisProgress.self, from: Data(line.utf8)) {
                analysisProgress = progress
                return
            }
        }
    }

    func runAnnual() async {
        guard requireLiveSnapshot() else { return }
        guard !isSavingSettings && !isSavingFileDate && !isAnalyzing && analysisCompleted else { return }

        guard !isRunningAnnual else { return }

        guard (snapshot?.pendingStagedOutputs ?? 0) == 0 else {
            maintenanceFailure = "Verified replacements from the previous run are still staged. Inspect the run details before starting another optimization."
            return
        }

        guard snapshot?.configured == true else {
            let message = "Add at least one folder before running maintenance."
            errorMessage = message
            return
        }
        guard snapshot?.archiveAvailable == true else {
            let message = "One or more configured folders are currently unavailable."
            errorMessage = message
            return
        }

        guard snapshot?.preflight.requiredToolsReady == true else {
            let message = "Veronica is missing one or more required media tools. Open Settings to see what is unavailable."
            errorMessage = message
            return
        }

        isRunningAnnual = true
        let beforeCleanup = snapshot
        cleanupOutcome = nil
        cleanupCompleted = false
        activityLines = []
        events = []
        errorMessage = nil
        maintenanceFailure = nil

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
            try await EngineRunner.shared.moveCompletedOriginalsToTrash()
            if result.exitCode != 0 {
                maintenanceFailure = "Cleanup stopped. Some files may already be optimized; their originals are in the Mac Trash. Open cleanup details for the reason."
            }
            await refresh()
            cleanupCompleted = result.exitCode == 0 && hasLiveSnapshot
        } catch {
            maintenanceFailure = error.localizedDescription
            await refresh()
        }
        cleanupOutcome = CleanupOutcome(
            completed: cleanupCompleted,
            optimized: max(0, (snapshot?.optimizedOutputs ?? 0) - (beforeCleanup?.optimizedOutputs ?? 0)),
            renamed: max(0, (snapshot?.renamedOutputs ?? 0) - (beforeCleanup?.renamedOutputs ?? 0)),
            savedBytes: max(0, (snapshot?.totalSavingBytes ?? 0) - (beforeCleanup?.totalSavingBytes ?? 0)),
            unreadable: events.filter { $0.event == "stage_item" && $0.status == "SOURCE_UNREADABLE" }.count,
            kept: events.filter { $0.event == "stage_item" && $0.status == "KEEP_ORIGINAL" }.count
        )
    }

    func dismissError() {
        errorMessage = nil
        maintenanceFailure = nil
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

    func saveFileDate(_ item: ScanResultItem, date: String) async throws -> String {
        guard hasLiveSnapshot, !isAnalyzing, !isRunningAnnual, !isSavingSettings, !isSavingFileDate,
              item.canEditDate == true, let plan = item.planPath else {
            throw EngineRunnerError.operationUnavailable("Wait for the current operation to finish, then open this file again.")
        }
        isSavingFileDate = true
        defer { isSavingFileDate = false }
        let result = try await EngineRunner.shared.run([
            "set-file-date", "--state-dir", item.stateDir, "--plan", plan,
            "--relpath", item.relpath, "--date", date, "--yes"
        ])
        guard result.exitCode == 0 else {
            throw EngineRunnerError.operationUnavailable(result.stderr.isEmpty ? result.stdout : result.stderr)
        }
        let response = try JSONSerialization.jsonObject(with: Data(result.stdout.utf8)) as? [String: Any]
        cleanupCompleted = false
        cleanupOutcome = nil
        do {
            try await EngineRunner.shared.moveCompletedOriginalsToTrash()
        } catch {
            await refresh()
            throw EngineRunnerError.operationUnavailable("The date was saved. Veronica has kept the original safely, but could not move it to Trash: \(error.localizedDescription)")
        }
        await refresh()
        return response?["relpath"] as? String ?? item.relpath
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

    func revealChangeLogs() {
        let directory = EngineRunner.shared.preferencesDirectory.appendingPathComponent("Change Logs", isDirectory: true)
        do {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true,
                                                    attributes: [.posixPermissions: 0o700])
            NSWorkspace.shared.open(directory)
        } catch { errorMessage = "The change log folder could not be opened: \(error.localizedDescription)" }
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
