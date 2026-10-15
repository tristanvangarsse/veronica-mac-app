import AppKit
import SwiftUI

@main
struct VeronicaApp: App {
    @StateObject private var model = AppModel()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(model)
                .frame(
                    width: VeronicaWindowMetrics.width,
                    height: VeronicaWindowMetrics.height
                )
                .background(AppIconConfigurator())
                .task {
                    DiagnosticsCenter.shared.log("INFO", "App", "Veronica launched")
                    await model.prepareNotifications()
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
        .windowToolbarStyle(.unified)
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
                Button("Reveal Log in Finder") { model.revealLogFile() }
                Toggle("Developer Mode", isOn: Binding(get: { model.developerMode }, set: { model.setDeveloperMode($0) }))
            }
        }
    }
}

private struct AppIconConfigurator: NSViewRepresentable {
    func makeNSView(context: Context) -> NSView {
        let view = NSView()
        DispatchQueue.main.async {
            if let icon = NSImage(named: "VeronicaIcon") {
                NSApp.applicationIconImage = icon
            }
        }
        return view
    }

    func updateNSView(_ nsView: NSView, context: Context) {}
}
