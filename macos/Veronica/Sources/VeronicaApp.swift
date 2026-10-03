import SwiftUI

@main
struct VeronicaApp: App {
    @StateObject private var model = AppModel()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(model)
                .frame(minWidth: 860, minHeight: 600)
                .task {
                    DiagnosticsCenter.shared.log("INFO", "App", "Veronica launched")
                    await model.refresh()
                }
        }
        .windowToolbarStyle(.unified)
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
