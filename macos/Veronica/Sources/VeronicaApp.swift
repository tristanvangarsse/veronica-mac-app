import AppKit
import SwiftUI

@main
struct VeronicaApp: App {
    @NSApplicationDelegateAdaptor(VeronicaAppDelegate.self) private var appDelegate
    @StateObject private var model = AppModel()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(model)
                .task {
                    DiagnosticsCenter.shared.log("INFO", "App", "Veronica launched")
                    LegacyNotificationCleanup.clear()
                    await model.refresh()
#if DEBUG
                    let arguments = ProcessInfo.processInfo.arguments
                    if arguments.contains("--debug-run-analysis-on-launch") {
                        await model.analyzeLibrary()
                    }
                    if arguments.contains("--debug-run-optimization-on-launch") {
                        if !model.analysisCompleted {
                            await model.analyzeLibrary()
                        }
                        await model.runAnnual()
                    }
#endif
                }
        }
        .windowToolbarStyle(.unifiedCompact)
        .windowResizability(.contentSize)
        .commands {
            CommandGroup(after: .appInfo) {
                Button("Refresh") { Task { await model.refresh() } }
                    .keyboardShortcut("r")
            }
            CommandMenu("Diagnostics") {
                Button("Copy Diagnostic Report") { model.copyDiagnosticReport() }
                Button("Export Diagnostics…") { model.exportDiagnostics() }
                Divider()
                Button("Show Change Logs") { model.revealChangeLogs() }
                Button("Reveal Diagnostic Log in Finder") { model.revealLogFile() }
                Toggle("Developer Mode", isOn: Binding(get: { model.developerMode }, set: { model.setDeveloperMode($0) }))
            }
        }

        Settings {
            SettingsView()
                .environmentObject(model)
                .frame(width: VeronicaWindowMetrics.settingsSheetSize.width,
                       height: VeronicaWindowMetrics.settingsSheetSize.height)
                .tint(VeronicaTheme.accent)
        }
    }
}

private final class VeronicaAppDelegate: NSObject, NSApplicationDelegate {
    private var terminating = false

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard !terminating else { return .terminateLater }
        terminating = true
        Task { @MainActor in
            await EngineRunner.shared.endSession()
            sender.reply(toApplicationShouldTerminate: true)
        }
        return .terminateLater
    }
}
