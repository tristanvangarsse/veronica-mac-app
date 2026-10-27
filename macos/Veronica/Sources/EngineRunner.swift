import Foundation
import AppKit
import Darwin

struct EngineResult {
    let exitCode: Int32
    let stdout: String
    let stderr: String
}

enum EngineRunnerError: LocalizedError {
    case engineMissing
    case pythonMissing
    case invalidOutput(String)
    case operationUnavailable(String)

    var errorDescription: String? {
        switch self {
        case .engineMissing: return "Veronica's bundled media engine could not be found."
        case .pythonMissing: return "Veronica's Python runtime could not be found. Development builds can also use an installed Python 3."
        case .operationUnavailable(let message): return message
        case .invalidOutput(let text): return "The Veronica engine returned invalid data: \(text)"
        }
    }
}

private final class StreamAccumulator: @unchecked Sendable {
    private let lock = NSLock()
    private var stdoutData = Data()
    private var stderrData = Data()
    private var overflow = false

    func append(_ data: Data, isError: Bool) {
        guard !data.isEmpty else { return }
        lock.lock()
        defer { lock.unlock() }
        if isError {
            stderrData.append(data)
            if stderrData.count > 262_144 { stderrData.removeFirst(stderrData.count - 262_144) }
        } else {
            let remaining = max(0, 16 * 1024 * 1024 - stdoutData.count)
            stdoutData.append(data.prefix(remaining))
            if data.count > remaining { overflow = true }
        }
    }

    func strings() -> (stdout: String, stderr: String, overflow: Bool) {
        lock.lock()
        defer { lock.unlock() }
        return (
            String(data: stdoutData, encoding: .utf8) ?? "",
            String(data: stderrData, encoding: .utf8) ?? "",
            overflow
        )
    }
}

private final class EngineProcessControl: @unchecked Sendable {
    private let lock = NSLock()
    private let process: Process
    private var cancelled = false
    private var observer: NSObjectProtocol?

    init(_ process: Process) {
        self.process = process
        observer = NotificationCenter.default.addObserver(forName: NSApplication.willTerminateNotification, object: nil, queue: nil) { [weak self] _ in self?.cancel() }
    }
    deinit { if let observer { NotificationCenter.default.removeObserver(observer) } }
    func didStart() {
        lock.lock()
        let stop = cancelled
        lock.unlock()
        if stop { cancel() }
    }
    func cancel() {
        lock.lock()
        cancelled = true
        lock.unlock()
        guard process.isRunning else { return }
        let pid = process.processIdentifier
        if getpgid(pid) == pid { kill(-pid, SIGTERM) } else { process.terminate() }
        DispatchQueue.global().asyncAfter(deadline: .now() + 3) { [self] in
            guard process.isRunning else { return }
            if getpgid(pid) == pid { kill(-pid, SIGKILL) } else { kill(pid, SIGKILL) }
        }
    }
}

final class EngineRunner {
    static let shared = EngineRunner()

    let preferencesDirectory: URL = {
#if DEBUG
        if let override = ProcessInfo.processInfo.environment["VERONICA_STATE_DIR"], !override.isEmpty {
            return URL(fileURLWithPath: override, isDirectory: true)
        }
#endif
        return FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/Veronica", isDirectory: true)
    }()
    private let sessionIdentifier = UUID().uuidString
    var sessionDirectory: URL { preferencesDirectory
        .appendingPathComponent("Sessions.noindex", isDirectory: true)
        .appendingPathComponent(sessionIdentifier, isDirectory: true) }
    private let sessionLock = NSLock()
    private var sessionLease: Int32 = -1
    private var controls: [ObjectIdentifier: EngineProcessControl] = [:]
    private let controlsLock = NSLock()
    @MainActor private var launchPrepared = false
    private var endingSession = false

    private func ensureSessionLease() throws {
        sessionLock.lock()
        defer { sessionLock.unlock() }
        guard !endingSession else { throw CancellationError() }
        guard sessionLease < 0 else { return }
        let directory = sessionDirectory.standardizedFileURL
        guard directory.resolvingSymlinksInPath().path == directory.path else {
            throw EngineRunnerError.operationUnavailable("Veronica’s temporary folder could not be opened safely.")
        }
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true,
                                                attributes: [.posixPermissions: 0o700])
        let fd = open(directory.appendingPathComponent(".lease").path, O_CREAT | O_RDWR | O_NOFOLLOW, 0o600)
        guard fd >= 0 else { throw POSIXError(.EACCES) }
        guard flock(fd, LOCK_EX | LOCK_NB) == 0 else { close(fd); throw POSIXError(.EBUSY) }
        _ = fcntl(fd, F_SETFD, FD_CLOEXEC)
        sessionLease = fd
    }

    private func track(_ control: EngineProcessControl, add: Bool) {
        controlsLock.lock()
        defer { controlsLock.unlock() }
        if add { controls[ObjectIdentifier(control)] = control }
        else { controls.removeValue(forKey: ObjectIdentifier(control)) }
    }

    private func cancelCommands() -> Bool {
        controlsLock.lock()
        let running = Array(controls.values)
        controlsLock.unlock()
        running.forEach { $0.cancel() }
        return !running.isEmpty
    }

    @MainActor func prepareForLaunch() async throws {
        guard !launchPrepared else { return }
        let setup = try await run(["prepare-runtime", "--state-dir", preferencesDirectory.path])
        guard setup.exitCode == 0 else {
            throw EngineRunnerError.operationUnavailable("Veronica could not prepare its built-in components. Reinstall the complete Veronica app and try again. \(setup.stderr)")
        }
        try ensureSessionLease()
        let logs = try await run(["change-log-status", "--state-dir", preferencesDirectory.path])
        guard logs.exitCode == 0 else {
            throw EngineRunnerError.operationUnavailable("Veronica could not open its change logs. \(logs.stderr)")
        }
        let sessions = try FileManager.default.contentsOfDirectory(at: sessionDirectory.deletingLastPathComponent(),
                                                                  includingPropertiesForKeys: nil)
        for previous in sessions where previous != sessionDirectory && UUID(uuidString: previous.lastPathComponent) != nil {
            try await releaseSession(previous, active: false, discard: true)
        }
        let oldSnapshot = preferencesDirectory.appendingPathComponent("ui-snapshot-cache.json")
        if FileManager.default.fileExists(atPath: oldSnapshot.path) {
            try FileManager.default.removeItem(at: oldSnapshot)
        }
        launchPrepared = true
    }

    private struct SessionRelease: Decodable {
        let original_folders: [String]
        let busy: Bool
    }

    private func releaseSession(_ directory: URL, active: Bool, discard: Bool) async throws {
        var arguments = ["desktop-session", "--state-dir", preferencesDirectory.path,
                         "--session-dir", directory.path]
        if active { arguments.append("--active") }
        let result = try await run(arguments)
        guard result.exitCode == 0 else {
            throw EngineRunnerError.operationUnavailable("Temporary cleanup files were kept safely. \(result.stderr)")
        }
        let release = try JSONDecoder().decode(SessionRelease.self, from: Data(result.stdout.utf8))
        guard !release.busy else { return }
        for path in release.original_folders {
            let url = URL(fileURLWithPath: path).standardizedFileURL
            guard url.path.hasPrefix(directory.standardizedFileURL.path + "/folders/") else {
                throw EngineRunnerError.invalidOutput("Unexpected originals folder")
            }
            // Failure keeps the session intact; never fall back to deletion.
            var destination: NSURL?
            try FileManager.default.trashItem(at: url, resultingItemURL: &destination)
            guard let destination else {
                throw EngineRunnerError.operationUnavailable("Originals were moved to Trash, but their new location could not be recorded. Temporary records were kept.")
            }
            let logged = try await run(["record-trash", "--state-dir", preferencesDirectory.path,
                                        "--session-dir", directory.path, "--source", url.path,
                                        "--destination", (destination as URL).path])
            guard logged.exitCode == 0 else {
                throw EngineRunnerError.operationUnavailable("Originals are safe in Trash, but their move could not be added to the change log. Temporary records were kept. \(logged.stderr)")
            }
        }
        if discard {
            let result = try await run(arguments + ["--discard"])
            guard result.exitCode == 0 else {
                throw EngineRunnerError.operationUnavailable("Temporary cleanup files were kept safely. \(result.stderr)")
            }
        }
    }

    private func sessionIsEnding() -> Bool {
        sessionLock.lock()
        defer { sessionLock.unlock() }
        return endingSession
    }

    func moveCompletedOriginalsToTrash() async throws {
        guard !sessionIsEnding() else { return }
        try await releaseSession(sessionDirectory, active: true, discard: false)
    }

    private func beginEndingSession() {
        sessionLock.lock()
        endingSession = true
        sessionLock.unlock()
    }

    private func closeSessionLease() {
        sessionLock.lock()
        defer { sessionLock.unlock() }
        if sessionLease >= 0 { close(sessionLease); sessionLease = -1 }
    }

    func endSession() async {
        beginEndingSession()
        while cancelCommands() { try? await Task.sleep(nanoseconds: 100_000_000) }
        do { try await releaseSession(sessionDirectory, active: true, discard: true) }
        catch { DiagnosticsCenter.shared.log("ERROR", "Session", error.localizedDescription) }
        closeSessionLease()
    }

    private func resourceURL(_ components: String...) -> URL? {
        guard let resources = Bundle.main.resourceURL else { return nil }
        return components.reduce(resources) { $0.appendingPathComponent($1) }
    }

    private func standaloneEngineURL() -> URL? {
#if VERONICA_USE_SOURCE_ENGINE
        // Development Release builds can opt into the bundled Python source.
        // Production Release builds continue using the standalone executable.
        return nil
#elseif DEBUG
        // Development builds intentionally use the bundled Python source.
        //
        // The release engine is packaged separately and may have meaningful
        // startup overhead. Using the source engine here keeps development
        // launches and UI iteration effectively instantaneous while exercising
        // the same CLI contract as the packaged engine.
        return nil
#else
        let candidates = [
            resourceURL("VeronicaEngine", "veronica-engine"),
            resourceURL("veronica-engine")
        ].compactMap { $0 }
        return candidates.first { FileManager.default.isExecutableFile(atPath: $0.path) }
#endif
    }

    private func engineScriptURL() throws -> URL {
        if let url = Bundle.main.url(forResource: "veronica", withExtension: "py", subdirectory: "Engine") { return url }
        if let url = Bundle.main.url(forResource: "veronica", withExtension: "py") { return url }
        throw EngineRunnerError.engineMissing
    }

    private func pythonURL() throws -> URL {
        let bundled = [
            resourceURL("Runtime", "bin", "python3"),
            resourceURL("Runtime", "Python.framework", "Versions", "Current", "bin", "python3")
        ].compactMap { $0 }
        for url in bundled where FileManager.default.isExecutableFile(atPath: url.path) { return url }

#if DEBUG || VERONICA_USE_SOURCE_ENGINE
        let checkout = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let developmentCandidates = [checkout.appendingPathComponent(".venv/bin/python").path, "/opt/homebrew/bin/python3", "/usr/local/bin/python3"]
        for path in developmentCandidates where FileManager.default.isExecutableFile(atPath: path) {
            return URL(fileURLWithPath: path)
        }
#endif
        throw EngineRunnerError.pythonMissing
    }

    private func environment() -> [String: String] {
        let inherited = ProcessInfo.processInfo.environment
        let allowed = ["LANG", "LC_ALL", "LC_CTYPE", "TMPDIR"]
        var env = inherited.filter { allowed.contains($0.key) }
        var pathParts: [String] = []
        if let tools = resourceURL("Tools", "bin"), FileManager.default.fileExists(atPath: tools.path) {
            pathParts.append(tools.path)
        }
        if let runtime = resourceURL("Runtime", "bin"), FileManager.default.fileExists(atPath: runtime.path) {
            pathParts.append(runtime.path)
        }

        // Finder/Xcode-launched GUI apps do not inherit the interactive shell PATH.
        // Only development builds use conventional Homebrew/local prefixes.
#if DEBUG || VERONICA_USE_SOURCE_ENGINE
        for path in ["/opt/homebrew/bin", "/usr/local/bin"] where FileManager.default.fileExists(atPath: path) {
            pathParts.append(path)
        }
#endif

        pathParts.append("/usr/bin:/bin")
        env["PATH"] = pathParts.joined(separator: ":")
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["VERONICA_GUI_RUN"] = "1"
        return env
    }

    func run(_ arguments: [String], onOutput: (@Sendable (String) -> Void)? = nil) async throws -> EngineResult {
        var effectiveArguments = arguments

#if DEBUG
        if let stateDir = ProcessInfo.processInfo.environment["VERONICA_STATE_DIR"],
           !stateDir.isEmpty,
           !effectiveArguments.contains("--state-dir") {
            let commandsWithStateDir: Set<String> = [
                "analyze-all",
                "annual-all",
                "annual",
                "ui-snapshot",
                "scan-results",
                "folder-settings", "configure-folder", "presets", "save-preset",
                "delete-preset", "apply-preset", "set-default-preset",
                "configure-folders",
                "restore-manual-defaults",
                "configure-media-types",
                "configure-date-scope",
                "configure-filenames",
                "configure-optimization",
                "configure-library",
                "preflight",
                "status",
                "run-status",
                "resolve-review"
            ]

            if let command = effectiveArguments.first,
               commandsWithStateDir.contains(command) {
                effectiveArguments += ["--state-dir", stateDir]
            }
        }
#endif

        if let command = effectiveArguments.first,
           ["ui-snapshot", "analyze-all", "annual-all", "scan-results"].contains(command) {
            try ensureSessionLease()
            if !effectiveArguments.contains("--state-dir") {
                effectiveArguments += ["--state-dir", preferencesDirectory.path]
            }
            effectiveArguments += ["--session-dir", sessionDirectory.path]
        }

        DiagnosticsCenter.shared.log("INFO", "Engine", "Starting command: \(effectiveArguments.first ?? "unknown")")
        let process = Process()
        if let executable = standaloneEngineURL() {
            process.executableURL = executable
            process.arguments = effectiveArguments
            process.currentDirectoryURL = executable.deletingLastPathComponent()
        } else {
#if !DEBUG && !VERONICA_USE_SOURCE_ENGINE
            throw EngineRunnerError.engineMissing
#else
            let engine = try engineScriptURL()
            process.executableURL = try pythonURL()
            process.arguments = ["-I", "-B", engine.path] + effectiveArguments
            process.currentDirectoryURL = engine.deletingLastPathComponent()
#endif
        }
        process.environment = environment()

        let out = Pipe()
        let err = Pipe()
        process.standardOutput = out
        process.standardError = err
        let accumulator = StreamAccumulator()

        func install(_ handle: FileHandle, isError: Bool) {
            handle.readabilityHandler = { h in
                let chunk = h.availableData
                guard !chunk.isEmpty else { return }
                accumulator.append(chunk, isError: isError)
                if let text = String(data: chunk, encoding: .utf8), !text.isEmpty { onOutput?(text) }
            }
        }
        install(out.fileHandleForReading, isError: false)
        install(err.fileHandleForReading, isError: true)

        let control = EngineProcessControl(process)
        track(control, add: true)
        let command = effectiveArguments.first ?? ""
        let limit: TimeInterval = ["annual", "annual-all"].contains(command) ? 48 * 60 * 60 : (["analyze-all", "desktop-session"].contains(command) ? 4 * 60 * 60 : 120)
        let deadline = DispatchWorkItem { control.cancel() }
        return try await withTaskCancellationHandler(operation: {
          try await withCheckedThrowingContinuation { continuation in
            process.terminationHandler = { process in
                self.track(control, add: false)
                deadline.cancel()
                out.fileHandleForReading.readabilityHandler = nil
                err.fileHandleForReading.readabilityHandler = nil
                let outTail = out.fileHandleForReading.readDataToEndOfFile()
                let errTail = err.fileHandleForReading.readDataToEndOfFile()
                accumulator.append(outTail, isError: false)
                accumulator.append(errTail, isError: true)
                let collected = accumulator.strings()
                if let text = String(data: outTail + errTail, encoding: .utf8), !text.isEmpty { onOutput?(text) }
                DiagnosticsCenter.shared.log(process.terminationStatus == 0 ? "INFO" : "ERROR", "Engine", "Command \(command) exited \(process.terminationStatus)")
                if DiagnosticsCenter.shared.developerMode && !collected.stderr.isEmpty { DiagnosticsCenter.shared.log("DEBUG", "Engine stderr", collected.stderr) }
                continuation.resume(returning: EngineResult(exitCode: collected.overflow ? 75 : process.terminationStatus, stdout: collected.stdout, stderr: collected.overflow ? "The engine response exceeded its safety limit. Narrow the folder selection and try again." : collected.stderr))
            }
            do {
                try Task.checkCancellation()
                try process.run()
                control.didStart()
                DispatchQueue.global().asyncAfter(deadline: .now() + limit, execute: deadline)
            }
            catch {
                self.track(control, add: false)
                DiagnosticsCenter.shared.log("ERROR", "Engine", "Failed to launch command \(command): \(error.localizedDescription)")
                out.fileHandleForReading.readabilityHandler = nil
                err.fileHandleForReading.readabilityHandler = nil
                deadline.cancel()
                continuation.resume(throwing: error)
            }
          }
        }, onCancel: { control.cancel() })
    }

    func analyzeAll(
        eventsURL: URL,
        onOutput: (@Sendable (String) -> Void)? = nil
    ) async throws {
        let result = try await run(["analyze-all", "--events-jsonl", eventsURL.path], onOutput: onOutput)
        try Task.checkCancellation()
        guard result.exitCode == 0 else {
            throw EngineRunnerError.invalidOutput(
                result.stderr.isEmpty ? result.stdout : result.stderr
            )
        }
    }

    func snapshot() async throws -> UISnapshot {
        let result = try await run(["ui-snapshot"])
        guard result.exitCode == 0 else { throw EngineRunnerError.invalidOutput(result.stderr) }
        guard let data = result.stdout.data(using: .utf8) else { throw EngineRunnerError.invalidOutput(result.stdout) }
        return try JSONDecoder().decode(UISnapshot.self, from: data)
    }

    func scanResults(scanID: String, offset: Int, category: String, search: String, focusRoot: String? = nil, focusRelpath: String? = nil) async throws -> ScanResultsPage {
        var arguments = ["scan-results", "--scan-id", scanID, "--offset", String(offset),
                         "--limit", "100", "--category", category, "--search", search]
        if let focusRoot, let focusRelpath {
            arguments += ["--focus-root", focusRoot, "--focus-relpath", focusRelpath]
        }
        let result = try await run(arguments)
        guard result.exitCode == 0, let data = result.stdout.data(using: .utf8) else {
            throw EngineRunnerError.invalidOutput(result.stderr.isEmpty ? result.stdout : result.stderr)
        }
        return try JSONDecoder().decode(ScanResultsPage.self, from: data)
    }

    func addScanFolders(_ paths: [String]) async throws {
        guard !paths.isEmpty else { return }
        var arguments = ["configure-folders"]
        for path in paths {
            arguments += ["--add", path]
        }
        let result = try await run(arguments)
        guard result.exitCode == 0 else {
            throw EngineRunnerError.invalidOutput(
                result.stderr.isEmpty ? result.stdout : result.stderr
            )
        }
    }

    func removeScanFolder(_ path: String) async throws {
        let result = try await run(["configure-folders", "--remove", path])
        guard result.exitCode == 0 else {
            throw EngineRunnerError.invalidOutput(
                result.stderr.isEmpty ? result.stdout : result.stderr
            )
        }
    }

    private func recipeJSON(_ recipe: ProcessingRecipe) throws -> String {
        let data = try JSONEncoder().encode(recipe)
        guard let json = String(data: data, encoding: .utf8) else {
            throw EngineRunnerError.invalidOutput("Could not encode folder preferences.")
        }
        return json
    }

    private func performSettingsCommand(_ arguments: [String]) async throws -> EngineResult {
        let result = try await run(arguments)
        guard result.exitCode == 0 else {
            let message = result.stderr.isEmpty ? result.stdout : result.stderr
            throw EngineRunnerError.operationUnavailable(message.trimmingCharacters(in: .whitespacesAndNewlines))
        }
        return result
    }

    func folderSettings(folder: String) async throws -> FolderSettings {
        let result = try await performSettingsCommand(["folder-settings", "--folder", folder])
        return try JSONDecoder().decode(FolderSettings.self, from: Data(result.stdout.utf8))
    }

    func saveFolderSettings(folder: String, recipe: ProcessingRecipe) async throws {
        _ = try await performSettingsCommand([
            "configure-folder", "--folder", folder, "--recipe-json", try recipeJSON(recipe)
        ])
    }

    func applyPreset(folder: String, presetID: String) async throws {
        _ = try await performSettingsCommand(["apply-preset", "--folder", folder, "--preset-id", presetID])
    }

    func savePreset(name: String, recipe: ProcessingRecipe, presetID: String? = nil) async throws -> SettingsPreset {
        var arguments = ["save-preset", "--name", name, "--recipe-json", try recipeJSON(recipe)]
        if let presetID { arguments += ["--preset-id", presetID] }
        let result = try await performSettingsCommand(arguments)
        return try JSONDecoder().decode(SettingsPreset.self, from: Data(result.stdout.utf8))
    }

    func deletePreset(presetID: String) async throws {
        _ = try await performSettingsCommand(["delete-preset", "--preset-id", presetID])
    }

    func setDefaultPreset(presetID: String) async throws {
        _ = try await performSettingsCommand(["set-default-preset", "--preset-id", presetID])
    }

    func configureMediaProcessing(
        images: Bool,
        videos: Bool,
        audio: Bool,
        imageExtensions: [String],
        videoExtensions: [String],
        audioExtensions: [String]
    ) async throws {
        let result = try await run([
            "configure-media-types",
            "--images", images ? "true" : "false",
            "--videos", videos ? "true" : "false",
            "--audio", audio ? "true" : "false",
            "--image-extensions", imageExtensions.joined(separator: ","),
            "--video-extensions", videoExtensions.joined(separator: ","),
            "--audio-extensions", audioExtensions.joined(separator: ",")
        ])

        guard result.exitCode == 0 else {
            throw EngineRunnerError.invalidOutput(
                result.stderr.isEmpty ? result.stdout : result.stderr
            )
        }
    }

    func configureDateScope(
        mode: String,
        start: String?,
        end: String?
    ) async throws {
        var arguments = [
            "configure-date-scope",
            "--mode", mode
        ]

        if let start {
            arguments += ["--start", start]
        }

        if let end {
            arguments += ["--end", end]
        }

        let result = try await run(arguments)
        guard result.exitCode == 0 else {
            throw EngineRunnerError.invalidOutput(
                result.stderr.isEmpty ? result.stdout : result.stderr
            )
        }
    }

    func configureFilenames(
        enabled: Bool,
        dateFormat: String,
        maxBytes: Int
    ) async throws {
        let result = try await run([
            "configure-filenames",
            "--enabled", enabled ? "true" : "false",
            "--date-format", dateFormat,
            "--max-bytes", String(maxBytes)
        ])
        guard result.exitCode == 0 else {
            throw EngineRunnerError.invalidOutput(
                result.stderr.isEmpty ? result.stdout : result.stderr
            )
        }
    }

    func restoreManualDefaults() async throws {
        let result = try await run(["restore-manual-defaults"])
        guard result.exitCode == 0 else {
            throw EngineRunnerError.invalidOutput(result.stderr.isEmpty ? result.stdout : result.stderr)
        }
    }

    func configureOptimization(
        imageFormat: String,
        imageMaxMegapixels: Double,
        jpegQuality: Int,
        videoMaxEdge: Int,
        audioMinSizeMB: Int,
        videoAllowCameraMetadataDrop: Bool
    ) async throws {
        let result = try await run([
            "configure-optimization",
            "--image-format", imageFormat,
            "--image-max-megapixels", String(imageMaxMegapixels),
            "--jpeg-quality", String(jpegQuality),
            "--video-max-edge", String(videoMaxEdge),
            "--audio-min-size-mb", String(audioMinSizeMB),
            "--allow-camera-metadata-drop", videoAllowCameraMetadataDrop ? "true" : "false"
        ])
        guard result.exitCode == 0 else {
            throw EngineRunnerError.invalidOutput(
                result.stderr.isEmpty ? result.stdout : result.stderr
            )
        }
    }
}
