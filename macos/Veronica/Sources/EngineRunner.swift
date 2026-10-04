import Foundation

struct EngineResult {
    let exitCode: Int32
    let stdout: String
    let stderr: String
}

enum EngineRunnerError: LocalizedError {
    case engineMissing
    case pythonMissing
    case invalidOutput(String)

    var errorDescription: String? {
        switch self {
        case .engineMissing: return "Veronica's bundled media engine could not be found."
        case .pythonMissing: return "Veronica's Python runtime could not be found. Development builds can also use an installed Python 3."
        case .invalidOutput(let text): return "The Veronica engine returned invalid data: \(text)"
        }
    }
}

private final class StreamAccumulator: @unchecked Sendable {
    private let lock = NSLock()
    private var stdoutData = Data()
    private var stderrData = Data()

    func append(_ data: Data, isError: Bool) {
        guard !data.isEmpty else { return }
        lock.lock()
        defer { lock.unlock() }
        if isError { stderrData.append(data) } else { stdoutData.append(data) }
    }

    func strings() -> (stdout: String, stderr: String) {
        lock.lock()
        defer { lock.unlock() }
        return (
            String(data: stdoutData, encoding: .utf8) ?? "",
            String(data: stderrData, encoding: .utf8) ?? ""
        )
    }
}

final class EngineRunner {
    static let shared = EngineRunner()

    private func resourceURL(_ components: String...) -> URL? {
        guard let resources = Bundle.main.resourceURL else { return nil }
        return components.reduce(resources) { $0.appendingPathComponent($1) }
    }

    private func standaloneEngineURL() -> URL? {
#if DEBUG
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

        let developmentCandidates = ["/usr/bin/python3", "/opt/homebrew/bin/python3", "/usr/local/bin/python3"]
        for path in developmentCandidates where FileManager.default.isExecutableFile(atPath: path) {
            return URL(fileURLWithPath: path)
        }
        throw EngineRunnerError.pythonMissing
    }

    private func environment() -> [String: String] {
        var env = ProcessInfo.processInfo.environment
        var pathParts: [String] = []
        if let tools = resourceURL("Tools", "bin"), FileManager.default.fileExists(atPath: tools.path) {
            pathParts.append(tools.path)
        }
        if let runtime = resourceURL("Runtime", "bin"), FileManager.default.fileExists(atPath: runtime.path) {
            pathParts.append(runtime.path)
        }

        // Finder/Xcode-launched GUI apps do not inherit the interactive shell PATH.
        // Development builds therefore add conventional Homebrew/local prefixes.
        // Release builds still prefer Veronica's bundled tools above.
        for path in ["/opt/homebrew/bin", "/usr/local/bin"] where FileManager.default.fileExists(atPath: path) {
            pathParts.append(path)
        }

        if let existing = env["PATH"], !existing.isEmpty { pathParts.append(existing) }
        env["PATH"] = pathParts.joined(separator: ":")
        env["PYTHONUNBUFFERED"] = "1"
        return env
    }

    func run(_ arguments: [String], onOutput: (@Sendable (String) -> Void)? = nil) async throws -> EngineResult {
        DiagnosticsCenter.shared.log("INFO", "Engine", "Starting command: \(arguments.first ?? "unknown")")
        let process = Process()
        if let executable = standaloneEngineURL() {
            process.executableURL = executable
            process.arguments = arguments
            process.currentDirectoryURL = executable.deletingLastPathComponent()
        } else {
            let engine = try engineScriptURL()
            process.executableURL = try pythonURL()
            process.arguments = [engine.path] + arguments
            process.currentDirectoryURL = engine.deletingLastPathComponent()
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

        return try await withCheckedThrowingContinuation { continuation in
            process.terminationHandler = { process in
                out.fileHandleForReading.readabilityHandler = nil
                err.fileHandleForReading.readabilityHandler = nil
                let outTail = out.fileHandleForReading.readDataToEndOfFile()
                let errTail = err.fileHandleForReading.readDataToEndOfFile()
                accumulator.append(outTail, isError: false)
                accumulator.append(errTail, isError: true)
                let collected = accumulator.strings()
                if let text = String(data: outTail + errTail, encoding: .utf8), !text.isEmpty { onOutput?(text) }
                DiagnosticsCenter.shared.log(process.terminationStatus == 0 ? "INFO" : "ERROR", "Engine", "Command \(arguments.first ?? "unknown") exited \(process.terminationStatus)")
                if DiagnosticsCenter.shared.developerMode && !collected.stderr.isEmpty { DiagnosticsCenter.shared.log("DEBUG", "Engine stderr", collected.stderr) }
                continuation.resume(returning: EngineResult(exitCode: process.terminationStatus, stdout: collected.stdout, stderr: collected.stderr))
            }
            do { try process.run() }
            catch {
                DiagnosticsCenter.shared.log("ERROR", "Engine", "Failed to launch command \(arguments.first ?? "unknown"): \(error.localizedDescription)")
                continuation.resume(throwing: error)
            }
        }
    }

    func snapshot() async throws -> UISnapshot {
        let result = try await run(["ui-snapshot"])
        guard result.exitCode == 0 else { throw EngineRunnerError.invalidOutput(result.stderr) }
        guard let data = result.stdout.data(using: .utf8) else { throw EngineRunnerError.invalidOutput(result.stdout) }
        return try JSONDecoder().decode(UISnapshot.self, from: data)
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

    func configureMediaProcessing(
        images: Bool,
        videos: Bool,
        audio: Bool
    ) async throws {
        let result = try await run([
            "configure-media-types",
            "--images", images ? "true" : "false",
            "--videos", videos ? "true" : "false",
            "--audio", audio ? "true" : "false"
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
}
