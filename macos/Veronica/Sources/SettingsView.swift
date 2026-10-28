import SwiftUI

private struct PresetEditorSelection: Identifiable {
    let id = UUID()
    let preset: SettingsPreset?
    let recipe: ProcessingRecipe
    let suggestedName: String
    var makeDefault = false
}

struct SettingsView: View {
    @EnvironmentObject private var model: AppModel
    @State private var editorSelection: PresetEditorSelection?
    @State private var pendingPresetRemoval: SettingsPreset?
    @State private var errorMessage: String?
    @State private var defaultSelection = ""
    @State private var selectedTab = "defaults"

    private var presets: [SettingsPreset] { model.snapshot?.settingsPresets ?? [] }
    private var defaultPreset: SettingsPreset? { presets.first { $0.id == model.snapshot?.defaultPresetID } }
    private var busy: Bool { !model.hasLiveSnapshot || model.isAnalyzing || model.isRunningAnnual || model.isSavingSettings || model.isSavingFileDate }

    var body: some View {
        VStack(spacing: 0) {
            if let errorMessage {
                HStack {
                    Text(errorMessage).font(.callout).foregroundStyle(.red)
                    Spacer()
                    Button { self.errorMessage = nil } label: { Image(systemName: "xmark").frame(width: 28, height: 28) }
                        .buttonStyle(VeronicaPlainButtonStyle()).accessibilityLabel("Dismiss error")
                }.padding(14)
            }
            TabView(selection: $selectedTab) {
                defaultsContent.tabItem { Label("Defaults", systemImage: "slider.horizontal.3") }.tag("defaults")
                presetsContent.tabItem { Label("Presets", systemImage: "square.stack") }.tag("presets")
                supportContent.tabItem { Label("Support", systemImage: "questionmark.circle") }.tag("support")
            }.padding(16)
        }
        .background(VeronicaTheme.canvas).tint(VeronicaTheme.accent)
        .onAppear { defaultSelection = model.snapshot?.defaultPresetID ?? "" }
        .onChange(of: model.snapshot?.defaultPresetID) { defaultSelection = $0 ?? "" }
        .sheet(item: $editorSelection) { selection in
            PresetEditorView(preset: selection.preset, initialRecipe: selection.recipe,
                             suggestedName: selection.suggestedName, makeDefaultOnSave: selection.makeDefault)
                .environmentObject(model)
        }
        .confirmationDialog("Delete this preset?", isPresented: Binding(
            get: { pendingPresetRemoval != nil }, set: { if !$0 { pendingPresetRemoval = nil } }
        )) {
            Button("Delete preset", role: .destructive) {
                guard let preset = pendingPresetRemoval else { return }
                pendingPresetRemoval = nil
                Task {
                    do { try await model.deletePreset(presetID: preset.id) }
                    catch { errorMessage = error.localizedDescription }
                }
            }
            Button("Cancel", role: .cancel) { pendingPresetRemoval = nil }
        } message: {
            Text("Folders keep their current settings. If this is your default, new folders will use Balanced instead.")
        }
    }

    private var defaultsContent: some View {
        Form {
            Section {
                VStack(alignment: .leading, spacing: 8) {
                    Text("A good start for every new folder").font(.title3.weight(.semibold))
                    Text("Pick the settings Veronica starts with. You can always customize a folder afterward.")
                        .foregroundStyle(.secondary)
                }.padding(.vertical, 8)
                RecipeChoiceMenu(title: "Start new folders with", selection: Binding(get: { defaultSelection }, set: setDefault),
                                 choices: presets.map { ($0.id, $0.name) })
                .disabled(busy || presets.isEmpty).accessibilityIdentifier("veronica.defaultPreset")
            }
            if let preset = defaultPreset {
                Section("Current default") {
                    summaryRow("Photos", enabled: preset.recipe.mediaProcessing.images,
                               detail: "\(preset.recipe.optimizationSettings.imageMaxMegapixels.formatted()) MP · \(preset.recipe.optimizationSettings.imageOutputFormat.uppercased())")
                    summaryRow("Video", enabled: preset.recipe.mediaProcessing.videos,
                               detail: "Up to \(preset.recipe.optimizationSettings.videoMaxEdge) px")
                    summaryRow("Audio", enabled: preset.recipe.mediaProcessing.audio, detail: "MP3 · 128 kbps")
                    HStack { Text("File dates"); Spacer(); Text(preset.recipe.dateScope.summary).foregroundStyle(.secondary) }
                    Button("Customize these defaults…") { edit(preset, makeDefault: true) }
                        .disabled(busy).accessibilityIdentifier("veronica.customizeDefaults")
                }
            }
            Section {
                Label("Existing folders keep their own settings.", systemImage: "folder.badge.gearshape")
                    .font(.callout).foregroundStyle(.secondary)
                if model.isSavingSettings { ProgressView("Saving…").controlSize(.small) }
                if model.isAnalyzing || model.isRunningAnnual {
                    Text("You can change defaults when the current scan or cleanup finishes.").font(.caption).foregroundStyle(.secondary)
                }
            }
        }.formStyle(.grouped)
    }

    private var presetsContent: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 5) {
                    Text("Saved presets").font(.title3.weight(.semibold))
                    Text("Customize a built-in preset or create your own.").foregroundStyle(.secondary)
                }
                Spacer()
                Button("New preset…") {
                    editorSelection = PresetEditorSelection(preset: nil, recipe: defaultPreset?.recipe ?? .recommended, suggestedName: availableName("My preset"))
                }.disabled(busy).accessibilityIdentifier("veronica.newPreset")
            }.padding(.horizontal, 12).padding(.top, 10)
            ScrollView {
                VStack(spacing: 10) {
                    ForEach(presets) { preset in
                        HStack(spacing: 14) {
                            Image(systemName: "slider.horizontal.3").font(.title3).foregroundStyle(VeronicaTheme.accent)
                            VStack(alignment: .leading, spacing: 5) {
                                HStack(spacing: 8) {
                                    Text(preset.name).font(.headline)
                                    if preset.id == model.snapshot?.defaultPresetID {
                                        Text("Default").font(.caption).foregroundStyle(VeronicaTheme.accent)
                                    }
                                }
                                Text(preset.recipe.displaySummary).font(.caption).foregroundStyle(.secondary)
                                    .fixedSize(horizontal: false, vertical: true)
                                if preset.builtIn { Text("Built-in · customize to create your own copy").font(.caption2).foregroundStyle(.secondary) }
                            }
                            Spacer(minLength: 6)
                            Button(preset.builtIn ? "Customize…" : "Edit…") { edit(preset) }
                                .accessibilityIdentifier("veronica.editPreset.\(preset.id)")
                            Menu {
                                Button("Use for new folders") { setDefault(preset.id) }
                                Button("Duplicate…") {
                                    editorSelection = PresetEditorSelection(preset: nil, recipe: preset.recipe, suggestedName: availableName("\(preset.name) Copy"))
                                }
                                if !preset.builtIn {
                                    Button("Delete…", role: .destructive) { pendingPresetRemoval = preset }
                                }
                            } label: { Image(systemName: "ellipsis") }
                            .menuStyle(.borderlessButton).fixedSize().accessibilityLabel("Options for \(preset.name)")
                        }
                        .padding(16).frame(maxWidth: .infinity, alignment: .leading)
                        .background(VeronicaTheme.subtleFill, in: RoundedRectangle(cornerRadius: 14))
                        .overlay(RoundedRectangle(cornerRadius: 14).strokeBorder(VeronicaTheme.border.opacity(0.5)))
                        .disabled(busy)
                    }
                }.padding(12)
            }
        }
    }

    private var supportContent: some View {
        Form {
            Section("Veronica") {
                HStack { Text("Version"); Spacer(); Text(model.snapshot?.version ?? "—").foregroundStyle(.secondary) }
                Label(model.snapshot?.preflight.requiredToolsReady == true ? "Ready to scan and optimize" : "Some components need attention",
                      systemImage: model.snapshot?.preflight.requiredToolsReady == true ? "checkmark.circle" : "exclamationmark.triangle")
                Button("Check again") { Task { await model.refresh() } }.disabled(model.isLoading)
                if let missing = model.snapshot?.preflight.missingRequirements, !missing.isEmpty {
                    Text("Missing: \(missing.joined(separator: ", "))").font(.caption).foregroundStyle(.secondary)
                }
            }
            Section("Change logs") {
                Text("Each Smart cleanup gets its own dated log, with all folders and completed changes together. Manual date edits have separate logs. Logs remain after you quit Veronica.")
                    .font(.callout).foregroundStyle(.secondary)
                Button("Show change logs") { model.revealChangeLogs() }
                    .accessibilityIdentifier("veronica.showChangeLogs")
            }
            Section("Help with a problem") {
                Text("Export a report to help investigate a problem. Media filenames are omitted from the report.")
                    .font(.callout).foregroundStyle(.secondary)
                HStack {
                    Button("Export report…") { model.exportDiagnostics() }
                    Button("Copy report") { model.copyDiagnosticReport() }
                }
                SettingsDisclosure("Advanced") {
                    Toggle("Detailed local logging", isOn: Binding(get: { model.developerMode }, set: { model.setDeveloperMode($0) }))
                    Button("Show diagnostic log in Finder") { model.revealLogFile() }
                    Button("Show Veronica data in Finder") { model.revealStateDirectory() }
                    if let preflight = model.snapshot?.preflight {
                        Text("Python \(preflight.pythonVersion ?? "") · Pillow \(preflight.pillow.version ?? "")")
                            .font(.caption).foregroundStyle(.secondary)
                        ForEach(["ffmpeg", "ffprobe", "HandBrakeCLI"], id: \.self) { tool in
                            HStack {
                                Text(tool)
                                Spacer()
                                Text(preflight.tools[tool]?.available == true ? "Available" : "Missing").foregroundStyle(.secondary)
                            }
                        }
                    }
                }
            }
        }.formStyle(.grouped)
    }

    private func summaryRow(_ title: String, enabled: Bool, detail: String) -> some View {
        HStack { Text(title); Spacer(); Text(enabled ? detail : "Leave unchanged").foregroundStyle(.secondary) }
    }
    private func availableName(_ base: String) -> String {
        let names = Set(presets.map { $0.name.lowercased() })
        var name = base; var count = 2
        while names.contains(name.lowercased()) { name = "\(base) \(count)"; count += 1 }
        return name
    }
    private func edit(_ preset: SettingsPreset, makeDefault: Bool = false) {
        editorSelection = PresetEditorSelection(preset: preset, recipe: preset.recipe,
            suggestedName: preset.builtIn ? availableName("\(preset.name) Custom") : preset.name,
            makeDefault: makeDefault)
    }
    private func setDefault(_ id: String) {
        guard !busy, !id.isEmpty else { return }
        defaultSelection = id
        Task {
            do { try await model.setDefaultPreset(presetID: id) }
            catch { defaultSelection = model.snapshot?.defaultPresetID ?? ""; errorMessage = error.localizedDescription }
        }
    }
}
