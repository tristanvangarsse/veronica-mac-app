import AppKit
import SwiftUI

struct FolderSettingsView: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.dismiss) private var dismiss
    let folder: FolderSettings
    @State private var draft: ProcessingRecipe
    @State private var savedRecipe: ProcessingRecipe
    @State private var selectedPresetID: String
    @State private var editorRevision = 0
    @State private var isWorking = false
    @State private var errorMessage: String?
    @State private var statusMessage: String?
    @State private var showingDiscard = false
    @State private var showingSavePreset = false
    @State private var presetName = ""

    init(folder: FolderSettings) {
        self.folder = folder
        _draft = State(initialValue: folder.recipe)
        _savedRecipe = State(initialValue: folder.recipe)
        _selectedPresetID = State(initialValue: folder.presetID ?? "")
    }
    private var presets: [SettingsPreset] { model.snapshot?.settingsPresets ?? [] }
    private var hasChanges: Bool { draft != savedRecipe }
    private var busy: Bool { !model.hasLiveSnapshot || isWorking || model.isSavingSettings || model.isAnalyzing || model.isRunningAnnual || model.isSavingFileDate }

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 12) {
                Image(systemName: "folder.fill").font(.title2).foregroundStyle(VeronicaTheme.accent)
                VStack(alignment: .leading, spacing: 4) {
                    Text(URL(fileURLWithPath: folder.folder).lastPathComponent).font(.title3.weight(.semibold))
                    Text("Settings for this folder and its subfolders").font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                if hasChanges { Text("Unsaved changes").font(.caption).foregroundStyle(VeronicaTheme.accent) }
            }.padding(20)
            Divider()
            RecipeEditorView(recipe: $draft).id(editorRevision).disabled(busy)
            Divider()
            HStack(spacing: 14) {
                Menu("Presets") {
                    ForEach(presets) { preset in
                        Button("Use \(preset.name)") { selectPreset(preset.id) }
                    }
                    Divider()
                    Button("Save as preset…") { presetName = ""; showingSavePreset = true }
                        .disabled(draft.validationMessage != nil)
                }
                .fixedSize().disabled(busy)
                .accessibilityIdentifier("veronica.folderPresetsMenu")
                VStack(alignment: .leading, spacing: 3) {
                    if let message = errorMessage ?? draft.validationMessage {
                        Text(message).font(.caption).foregroundStyle(.red)
                    } else {
                        Text(statusMessage ?? (hasChanges ? "Save to apply these changes to this folder." : "Other folders keep their own settings."))
                            .font(.caption).foregroundStyle(.secondary)
                    }
                    if isWorking { ProgressView().controlSize(.small) }
                }.frame(maxWidth: .infinity, alignment: .leading)
                Button(hasChanges ? "Cancel" : "Done", action: requestClose)
                    .keyboardShortcut(.cancelAction).disabled(isWorking || model.isSavingSettings)
                Button("Save changes", action: saveChanges)
                    .buttonStyle(VeronicaPrimaryButtonStyle()).keyboardShortcut("s", modifiers: .command)
                    .disabled(!hasChanges || busy || draft.validationMessage != nil)
                    .accessibilityIdentifier("veronica.saveFolderSettings")
            }.padding(18)
        }
        .frame(width: VeronicaWindowMetrics.settingsSheetSize.width, height: VeronicaWindowMetrics.settingsSheetSize.height)
        .background(VeronicaTheme.canvas).tint(VeronicaTheme.accent)
        .interactiveDismissDisabled(hasChanges || isWorking || model.isSavingSettings)
        .onChange(of: draft) { value in
            if let preset = presets.first(where: { $0.id == selectedPresetID }), preset.recipe != value {
                selectedPresetID = ""
            }
            statusMessage = nil
        }
        .confirmationDialog("Discard unsaved changes?", isPresented: $showingDiscard) {
            Button("Discard changes", role: .destructive) { dismiss() }
            Button("Keep editing", role: .cancel) {}
        }
        .alert("Save a reusable preset", isPresented: $showingSavePreset) {
            TextField("Preset name", text: $presetName)
            Button("Cancel", role: .cancel) {}
            Button("Save preset", action: savePreset)
                .disabled(presetName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        } message: {
            Text("Give these settings a name so you can use them for other folders too.")
        }
    }

    private func selectPreset(_ id: String) {
        guard !busy else { return }
        NSApp.keyWindow?.makeFirstResponder(nil)
        selectedPresetID = id
        guard let preset = presets.first(where: { $0.id == id }) else { return }
        draft = preset.recipe
        editorRevision += 1
        errorMessage = nil
        statusMessage = nil
    }
    private func requestClose() {
        if hasChanges { showingDiscard = true } else { dismiss() }
    }
    private func saveChanges() {
        guard !busy, draft.validationMessage == nil else { return }
        NSApp.keyWindow?.makeFirstResponder(nil)
        let recipe = draft
        let preset = presets.first { $0.id == selectedPresetID && $0.recipe == recipe }
        isWorking = true; errorMessage = nil
        Task {
            defer { isWorking = false }
            do {
                if let preset { try await model.applyPreset(folder: folder.folder, presetID: preset.id) }
                else { try await model.saveFolderSettings(folder: folder.folder, recipe: recipe) }
                guard let stored = model.snapshot?.folderSettings?.first(where: { $0.folder == folder.folder }), stored.recipe == recipe else {
                    throw EngineRunnerError.operationUnavailable("Your changes could not be confirmed. Try saving again.")
                }
                savedRecipe = stored.recipe
                dismiss()
            } catch { errorMessage = error.localizedDescription }
        }
    }
    private func savePreset() {
        let name = presetName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !busy, !name.isEmpty, draft.validationMessage == nil else { return }
        isWorking = true; errorMessage = nil
        Task {
            defer { isWorking = false }
            do {
                let saved = try await model.savePreset(name: name, recipe: draft)
                selectedPresetID = saved.id
                statusMessage = hasChanges ? "Preset saved. Save changes to use it for this folder."
                    : "Preset saved. This folder already uses these settings."
            } catch { errorMessage = error.localizedDescription }
        }
    }
}

struct PresetEditorView: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.dismiss) private var dismiss
    let preset: SettingsPreset?
    let makeDefaultOnSave: Bool
    @State private var name: String
    @State private var draft: ProcessingRecipe
    @State private var savedID: String?
    private let originalName: String
    private let originalRecipe: ProcessingRecipe
    @State private var isWorking = false
    @State private var errorMessage: String?
    @State private var showingDiscard = false

    init(preset: SettingsPreset?, initialRecipe: ProcessingRecipe, suggestedName: String = "", makeDefaultOnSave: Bool = false) {
        self.preset = preset
        self.makeDefaultOnSave = makeDefaultOnSave
        let initialName = (preset?.builtIn == false ? preset?.name : nil) ?? suggestedName
        _name = State(initialValue: initialName)
        _draft = State(initialValue: initialRecipe)
        _savedID = State(initialValue: preset?.builtIn == false ? preset?.id : nil)
        originalName = initialName
        originalRecipe = initialRecipe
    }
    private var hasChanges: Bool { name != originalName || draft != originalRecipe }
    private var busy: Bool { !model.hasLiveSnapshot || isWorking || model.isSavingSettings || model.isAnalyzing || model.isRunningAnnual || model.isSavingFileDate }
    private var duplicateName: Bool {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        return model.snapshot?.settingsPresets?.contains { $0.id != savedID && $0.name.caseInsensitiveCompare(trimmed) == .orderedSame } == true
    }

    var body: some View {
        VStack(spacing: 0) {
            VStack(alignment: .leading, spacing: 12) {
                Text(savedID == nil ? "Create a preset" : "Edit preset").font(.title3.weight(.semibold))
                TextField("Preset name", text: $name).textFieldStyle(.roundedBorder)
                    .accessibilityIdentifier("veronica.presetName").disabled(busy)
                Text(makeDefaultOnSave ? "These settings will be used for new folders. Existing folders keep their settings."
                     : "Save a reusable set of settings. Existing folders keep their own copy.")
                    .font(.caption).foregroundStyle(.secondary)
            }.padding(20)
            Divider()
            RecipeEditorView(recipe: $draft).disabled(busy)
            Divider()
            HStack(spacing: 14) {
                if let message = errorMessage ?? draft.validationMessage ?? (duplicateName ? "A preset with this name already exists. Choose another name." : nil) {
                    Text(message).font(.caption).foregroundStyle(.red).frame(maxWidth: .infinity, alignment: .leading)
                } else { Spacer() }
                if isWorking { ProgressView().controlSize(.small) }
                Button("Cancel") { if hasChanges { showingDiscard = true } else { dismiss() } }
                    .keyboardShortcut(.cancelAction).disabled(isWorking || model.isSavingSettings)
                Button(makeDefaultOnSave ? "Save as default" : "Save preset", action: save)
                    .buttonStyle(VeronicaPrimaryButtonStyle()).keyboardShortcut("s", modifiers: .command)
                    .disabled(busy || draft.validationMessage != nil || duplicateName || name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    .accessibilityIdentifier("veronica.savePreset")
            }.padding(18)
        }
        .frame(width: VeronicaWindowMetrics.settingsSheetSize.width, height: VeronicaWindowMetrics.settingsSheetSize.height)
        .background(VeronicaTheme.canvas).tint(VeronicaTheme.accent)
        .interactiveDismissDisabled(hasChanges || isWorking || model.isSavingSettings)
        .confirmationDialog("Discard unsaved preset changes?", isPresented: $showingDiscard) {
            Button("Discard changes", role: .destructive) { dismiss() }
            Button("Keep editing", role: .cancel) {}
        }
    }
    private func save() {
        guard !busy, draft.validationMessage == nil, !duplicateName else { return }
        NSApp.keyWindow?.makeFirstResponder(nil)
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        isWorking = true; errorMessage = nil
        Task {
            defer { isWorking = false }
            do {
                let saved = try await model.savePreset(name: trimmed, recipe: draft, presetID: savedID)
                savedID = saved.id
                if makeDefaultOnSave { try await model.setDefaultPreset(presetID: saved.id) }
                dismiss()
            } catch { errorMessage = error.localizedDescription }
        }
    }
}
