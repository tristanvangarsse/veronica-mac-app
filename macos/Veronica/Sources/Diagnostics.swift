import AppKit
import Foundation
import UniformTypeIdentifiers

final class DiagnosticsCenter: @unchecked Sendable {
    static let shared = DiagnosticsCenter()

    private let lock = NSLock()
    private let fm = FileManager.default
    private let developerModeKey = "VeronicaDeveloperMode"

    var developerMode: Bool {
        get { UserDefaults.standard.bool(forKey: developerModeKey) }
        set { UserDefaults.standard.set(newValue, forKey: developerModeKey) }
    }

    var stateDirectory: URL {
#if DEBUG
        if let stateDir = ProcessInfo.processInfo.environment["VERONICA_STATE_DIR"],
           !stateDir.isEmpty {
            return URL(fileURLWithPath: stateDir, isDirectory: true)
        }
#endif
        return fm.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/Veronica", isDirectory: true)
    }

    var logDirectory: URL { stateDirectory.appendingPathComponent("logs", isDirectory: true) }
    var logURL: URL { logDirectory.appendingPathComponent("veronica.log") }

    private init() {}

    func log(_ level: String, _ component: String, _ message: String) {
        lock.lock()
        defer { lock.unlock() }
        do {
            try fm.createDirectory(at: logDirectory, withIntermediateDirectories: true)
            rotateIfNeeded()
            let ts = ISO8601DateFormatter().string(from: Date())
            let line = "\(ts) [\(level)] [\(component)] \(message)\n"
            let data = Data(line.utf8)
            if !fm.fileExists(atPath: logURL.path) {
                try data.write(to: logURL, options: .atomic)
            } else {
                let handle = try FileHandle(forWritingTo: logURL)
                try handle.seekToEnd()
                try handle.write(contentsOf: data)
                try handle.close()
            }
        } catch {
            // Diagnostics must never interfere with Veronica's media workflow.
        }
    }

    private func rotateIfNeeded() {
        guard let attrs = try? fm.attributesOfItem(atPath: logURL.path),
              let size = attrs[.size] as? NSNumber,
              size.int64Value > 5 * 1024 * 1024,
              let data = try? Data(contentsOf: logURL) else { return }
        let keep = min(data.count, 1024 * 1024)
        let tail = data.suffix(keep)
        try? Data(tail).write(to: logURL, options: .atomic)
    }

    func recentLog(limit: Int = 250) -> String {
        lock.lock()
        defer { lock.unlock() }
        guard let text = try? String(contentsOf: logURL, encoding: .utf8) else { return "" }
        return text.split(separator: "\n", omittingEmptySubsequences: false).suffix(limit).joined(separator: "\n")
    }

    private func isInsideAppBundle(_ path: String?) -> Bool {
        guard let path, !path.isEmpty else { return false }

        let candidate = URL(fileURLWithPath: path).standardizedFileURL.path
        let bundle = Bundle.main.bundleURL.standardizedFileURL.path

        return candidate == bundle || candidate.hasPrefix(bundle + "/")
    }

    private func runtimeSource(for path: String?) -> String {
        guard let path, !path.isEmpty else { return "missing" }

        if isInsideAppBundle(path) {
            return "bundled"
        }

        if path == "/usr/bin/file" || path == "/usr/bin/xattr" {
            return "macOS system"
        }

        if path.hasPrefix("/opt/homebrew/") || path.hasPrefix("/usr/local/") {
            return "Homebrew/local dependency"
        }

        return "external"
    }

    func privacySafeReport(snapshot: UISnapshot?, errorMessage: String?, events: [EngineEvent]) -> String {
        var lines: [String] = []
        let info = Bundle.main.infoDictionary ?? [:]
        let appVersion = (info["CFBundleShortVersionString"] as? String) ?? snapshot?.version ?? "unknown"
        let build = (info["CFBundleVersion"] as? String) ?? "unknown"

        lines.append("Veronica Diagnostic Report")
        lines.append("Generated: \(ISO8601DateFormatter().string(from: Date()))")
        lines.append("App version: \(appVersion) (\(build))")
        lines.append("macOS: \(ProcessInfo.processInfo.operatingSystemVersionString)")
        #if arch(arm64)
        lines.append("Architecture: arm64")
        #elseif arch(x86_64)
        lines.append("Architecture: x86_64")
        #else
        lines.append("Architecture: unknown")
        #endif
        lines.append("Developer mode: \(developerMode ? "on" : "off")")
        lines.append("")

        if let snapshot {
            lines.append("State")
            lines.append("- Configured: \(snapshot.configured)")
            lines.append("- Database exists: \(snapshot.databaseExists)")
            lines.append("- Configured folders: \(snapshot.scanFolders.count)")
            lines.append("- All configured folders available: \(snapshot.archiveAvailable)")
            lines.append("- Unavailable folders: \(snapshot.unavailableScanFolders.count)")
            lines.append("- Active assets: \(snapshot.activeAssets)")
            lines.append("- Committed outputs: \(snapshot.committedOutputs)")
            lines.append("- Unresolved reviews: \(snapshot.unresolvedReviews.count)")
            lines.append("- Quarantine transactions: \(snapshot.quarantineDirectories)")
            lines.append("- Annual include-through: \(snapshot.annual.includeThrough)")
            if let plan = snapshot.latestPlan {
                lines.append("- Latest plan ID: \(plan.planId)")
                lines.append("- Remaining executable: \(plan.remainingExecutableCount ?? plan.executableCount)")
                lines.append("- Latest-plan unresolved reviews: \(plan.unresolvedReviewCount)")
            }
            if !snapshot.unresolvedReviews.isEmpty {
                let reasons = Dictionary(grouping: snapshot.unresolvedReviews, by: { $0.reason }).mapValues { $0.count }
                for key in reasons.keys.sorted() { lines.append("- Review reason \(key): \(reasons[key] ?? 0)") }
            }
            lines.append("")
            lines.append("Runtime")
            lines.append("- Python/runtime: \(snapshot.preflight.pythonVersion)")
            lines.append("- Engine executable: \(sanitize(snapshot.preflight.python, snapshot: snapshot))")
            lines.append("- Engine source: \(runtimeSource(for: snapshot.preflight.python))")
            lines.append("- Pillow: \(snapshot.preflight.pillow.available ? (snapshot.preflight.pillow.version ?? "available") : "missing")")

            lines.append("")
            lines.append("Tools")

            for tool in ["file", "ffprobe", "ffmpeg", "HandBrakeCLI", "xattr"] {
                let status = snapshot.preflight.tools[tool]
                let ready = status?.available == true
                let toolPath = status?.path

                if ready, let toolPath, !toolPath.isEmpty {
                    lines.append("- \(tool): available | \(sanitize(toolPath, snapshot: snapshot)) | \(runtimeSource(for: toolPath))")
                } else {
                    lines.append("- \(tool): missing")
                }
            }

            let missingRequirements = snapshot.preflight.missingRequirements

            lines.append("")
            lines.append("Dependency readiness")
            lines.append("- Ready for maintenance: \(missingRequirements.isEmpty ? "YES" : "NO")")
            if missingRequirements.isEmpty {
                lines.append("- Missing requirements: none")
            } else {
                lines.append("- Missing requirements: \(missingRequirements.joined(separator: ", "))")
            }
        } else {
            lines.append("State snapshot: unavailable")
        }

        if let errorMessage, !errorMessage.isEmpty {
            lines.append("")
            lines.append("Last app error")
            lines.append(sanitize(errorMessage, snapshot: snapshot))
        }

        if !events.isEmpty {
            lines.append("")
            lines.append("Recent structured events (filenames omitted)")
            for event in events.suffix(30) {
                var parts = [event.event]
                if let status = event.status { parts.append("status=\(status)") }
                if let error = event.error { parts.append("error=\(sanitize(error, snapshot: snapshot))") }
                if let index = event.index, let total = event.total { parts.append("progress=\(index)/\(total)") }
                lines.append("- " + parts.joined(separator: " "))
            }
        }
        return lines.joined(separator: "\n") + "\n"
    }

    func sanitizedRecentLog(snapshot: UISnapshot?) -> String {
        recentLog().split(separator: "\n", omittingEmptySubsequences: false)
            .map { sanitize(String($0), snapshot: snapshot) }
            .joined(separator: "\n")
    }

    private func sanitize(_ input: String, snapshot: UISnapshot?) -> String {
        var value = input
        let home = fm.homeDirectoryForCurrentUser.path
        value = value.replacingOccurrences(of: home, with: "<HOME>")
        if let snapshot {
            for (index, root) in snapshot.scanFolders.enumerated() where !root.isEmpty {
                value = value.replacingOccurrences(
                    of: root,
                    with: "<SCAN_FOLDER_\(index + 1)>"
                )
            }
        }
        if let state = snapshot?.stateDir, !state.isEmpty {
            value = value.replacingOccurrences(of: state, with: "<VERONICA_STATE>")
        }
        return value
    }

    func exportDiagnostics(to destination: URL, snapshot: UISnapshot?, errorMessage: String?, events: [EngineEvent]) throws {
        let tempRoot = fm.temporaryDirectory.appendingPathComponent("Veronica-Diagnostics-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempRoot, withIntermediateDirectories: true)
        defer { try? fm.removeItem(at: tempRoot) }

        let report = privacySafeReport(snapshot: snapshot, errorMessage: errorMessage, events: events)
        try report.write(to: tempRoot.appendingPathComponent("diagnostics.txt"), atomically: true, encoding: .utf8)
        try sanitizedRecentLog(snapshot: snapshot).write(to: tempRoot.appendingPathComponent("recent-log.txt"), atomically: true, encoding: .utf8)

        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/ditto")
        process.arguments = ["-c", "-k", "--sequesterRsrc", "--keepParent", tempRoot.path, destination.path]
        try process.run()
        process.waitUntilExit()
        if process.terminationStatus != 0 {
            throw NSError(domain: "Veronica.Diagnostics", code: Int(process.terminationStatus), userInfo: [NSLocalizedDescriptionKey: "Could not create the diagnostics ZIP."])
        }
    }
}
