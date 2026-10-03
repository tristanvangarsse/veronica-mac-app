import SwiftUI

struct SettingsView: View {
    @EnvironmentObject var model: AppModel
    @State private var pendingRemoval: String?

    private static let dateFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter
    }()

    private func parsedDate(_ value: String?) -> Date {
        if let value, let date = Self.dateFormatter.date(from: value) {
            return date
        }
        return Date()
    }

    private func formattedDate(_ value: Date) -> String {
        Self.dateFormatter.string(from: value)
    }

    private var shouldStartAtBottomForUICapture: Bool {
        ProcessInfo.processInfo.arguments.contains("--ui-settings-bottom")
    }

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                VStack(alignment: .leading, spacing: 3) {
                    Text("Settings").font(.largeTitle.bold())
                    Text("Folders, Veronica data, runtime readiness, and diagnostics.").foregroundStyle(.secondary)
                }

                GroupBox("Folders to scan") {
                    VStack(alignment: .leading, spacing: 12) {
                        if let snapshot = model.snapshot, !snapshot.scanFolders.isEmpty {
                            ForEach(snapshot.scanFolders, id: \.self) { path in
                                HStack(spacing: 12) {
                                    Image(systemName: "folder")
                                        .foregroundStyle(.secondary)

                                    VStack(alignment: .leading, spacing: 3) {
                                        Text(path)
                                            .lineLimit(1)
                                            .truncationMode(.middle)
                                            .textSelection(.enabled)

                                        let unavailable = snapshot.unavailableScanFolders.contains(path)
                                        Text(unavailable ? "Unavailable" : "Available")
                                            .font(.caption)
                                            .foregroundStyle(unavailable ? Color.red : Color.secondary)
                                    }

                                    Spacer()

                                    Button {
                                        pendingRemoval = path
                                    } label: {
                                        Image(systemName: "minus")
                                    }
                                    .help("Remove folder")
                                    .disabled(model.isRunningAnnual)
                                }

                                if path != snapshot.scanFolders.last {
                                    Divider()
                                }
                            }
                        } else {
                            Text("No folders added.")
                                .foregroundStyle(.secondary)
                        }

                        HStack {
                            Button {
                                Task { await model.addScanFolders() }
                            } label: {
                                Label("Add Folders…", systemImage: "plus")
                            }
                            .disabled(model.isRunningAnnual)

                            Spacer()
                        }

                        Text("Veronica scans only the folders listed here. You can add as many folders as you need. Removing a folder does not delete its media.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    .padding(.vertical, 4)
                }
                GroupBox("Media to process") {
                    if model.snapshot?.mediaProcessing != nil {
                        VStack(alignment: .leading, spacing: 14) {
                            Toggle(
                                "Images",
                                isOn: Binding(
                                    get: { model.processImages },
                                    set: { value in
                                        Task {
                                            await model.updateMediaProcessing(images: value)
                                        }
                                    }
                                )
                            )

                            Toggle(
                                "Videos",
                                isOn: Binding(
                                    get: { model.processVideos },
                                    set: { value in
                                        Task {
                                            await model.updateMediaProcessing(videos: value)
                                        }
                                    }
                                )
                            )

                            Toggle(
                                "Audio",
                                isOn: Binding(
                                    get: { model.processAudio },
                                    set: { value in
                                        Task {
                                            await model.updateMediaProcessing(audio: value)
                                        }
                                    }
                                )
                            )

                            Text("Disabled media types are still inventoried for safety and history, but Veronica will not plan conversions for them.")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        .padding(.vertical, 4)
                        .disabled(model.isRunningAnnual)
                    }
                }

                GroupBox("Date scope") {
                    if let scope = model.snapshot?.dateScope {
                        VStack(alignment: .leading, spacing: 14) {
                            Picker(
                                "Apply maintenance to",
                                selection: Binding(
                                    get: { scope.mode },
                                    set: { mode in
                                        if mode == "all" {
                                            Task {
                                                await model.updateDateScope(mode: "all")
                                            }
                                        } else {
                                            let start = scope.start ?? formattedDate(Date())
                                            let end = scope.end ?? formattedDate(Date())
                                            Task {
                                                await model.updateDateScope(
                                                    mode: mode,
                                                    start: start,
                                                    end: end
                                                )
                                            }
                                        }
                                    }
                                )
                            ) {
                                Text("All dates")
                                    .tag("all")
                                Text("Only within range")
                                    .tag("within")
                                Text("Outside range")
                                    .tag("outside")
                            }
                            .pickerStyle(.segmented)
                            .frame(maxWidth: 560)

                            if scope.mode == "within" || scope.mode == "outside" {
                                VStack(alignment: .leading, spacing: 10) {
                                    HStack(spacing: 14) {
                                        Text("From")
                                            .frame(width: 74, alignment: .leading)

                                        DatePicker(
                                            "",
                                            selection: Binding(
                                                get: { parsedDate(scope.start) },
                                                set: { date in
                                                    Task {
                                                        await model.updateDateScope(
                                                            mode: scope.mode,
                                                            start: formattedDate(date),
                                                            end: scope.end ?? formattedDate(date)
                                                        )
                                                    }
                                                }
                                            ),
                                            displayedComponents: .date
                                        )
                                        .labelsHidden()
                                        .datePickerStyle(.field)
                                        .fixedSize()
                                        .frame(minWidth: 210, alignment: .leading)
                                    }

                                    HStack(spacing: 14) {
                                        Text("Through")
                                            .frame(width: 74, alignment: .leading)

                                        DatePicker(
                                            "",
                                            selection: Binding(
                                                get: { parsedDate(scope.end) },
                                                set: { date in
                                                    Task {
                                                        await model.updateDateScope(
                                                            mode: scope.mode,
                                                            start: scope.start ?? formattedDate(date),
                                                            end: formattedDate(date)
                                                        )
                                                    }
                                                }
                                            ),
                                            displayedComponents: .date
                                        )
                                        .labelsHidden()
                                        .datePickerStyle(.field)
                                        .fixedSize()
                                        .frame(minWidth: 210, alignment: .leading)
                                    }
                                }
                            }

                            Text(scope.summary)
                                .font(.caption)
                                .foregroundStyle(.secondary)

                            if scope.mode == "all" {
                                Text("Date filtering is disabled. Any otherwise eligible media date may be processed.")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            } else if scope.mode == "within" {
                                Text("Only media whose resolved date falls within this inclusive range is eligible.")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            } else {
                                Text("Only media whose resolved date falls before or after this inclusive range is eligible.")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                        .padding(.vertical, 4)
                        .disabled(model.isRunningAnnual)
                    }
                }

                GroupBox("File naming") {
                    if let naming = model.snapshot?.filenamePolicy {
                        VStack(alignment: .leading, spacing: 14) {
                            Toggle(
                                "Standardize media filenames",
                                isOn: Binding(
                                    get: { naming.enabled },
                                    set: { value in
                                        Task {
                                            await model.updateFilenamePolicy(enabled: value)
                                        }
                                    }
                                )
                            )

                            Text("When enabled, eligible media is named using its resolved Veronica date followed by the existing filename.")
                                .font(.caption)
                                .foregroundStyle(.secondary)

                            Divider()

                            LabeledContent("Format") {
                                Picker(
                                    "Format",
                                    selection: Binding(
                                        get: { naming.dateFormat },
                                        set: { value in
                                            Task {
                                                await model.updateFilenamePolicy(dateFormat: value)
                                            }
                                        }
                                    )
                                ) {
                                    Text("YYYY-MM-DD_filename.ext")
                                        .tag("YYYY-MM-DD_")
                                }
                                .labelsHidden()
                                .frame(width: 230)
                            }

                            LabeledContent("Maximum filename size") {
                                Stepper(
                                    value: Binding(
                                        get: { naming.maxBytes },
                                        set: { value in
                                            Task {
                                                await model.updateFilenamePolicy(maxBytes: value)
                                            }
                                        }
                                    ),
                                    in: 32...255,
                                    step: 1
                                ) {
                                    Text("\(naming.maxBytes) UTF-8 bytes")
                                        .monospacedDigit()
                                }
                            }

                            Text("The limit includes the date prefix and file extension. Veronica truncates only the original filename portion and never splits a UTF-8 character. The filesystem safety ceiling is 255 bytes.")
                                .font(.caption)
                                .foregroundStyle(.secondary)

                            LabeledContent("Example") {
                                Text("2023-01-01_Screenshot 1.jpg")
                                    .font(.system(.body, design: .monospaced))
                            }
                        }
                        .padding(.vertical, 4)
                        .disabled(model.isRunningAnnual)
                    }
                }

                GroupBox("Veronica data") {
                    VStack(alignment: .leading, spacing: 10) {
                        LabeledContent("Location") { Text(model.snapshot?.stateDir ?? "—").textSelection(.enabled) }
                        LabeledContent("Database") { Text(model.snapshot?.databaseExists == true ? "Ready" : "Created on first scan") }
                        Button("Reveal Veronica Data in Finder") { model.revealStateDirectory() }
                    }.padding(.vertical, 4)
                }

                GroupBox("Runtime & media tools") {
                    if let p = model.snapshot?.preflight {
                        VStack(alignment: .leading, spacing: 12) {
                            HStack {
                                VStack(alignment: .leading, spacing: 3) {
                                    Text(p.requiredToolsReady ? "Ready for maintenance" : "Dependencies required")
                                        .font(.headline)
                                    Text(p.requiredToolsReady
                                         ? "All required runtime components are available."
                                         : "Maintenance remains disabled until the missing requirements below are available.")
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }

                                Spacer()

                                Button("Refresh") {
                                    Task { await model.refresh() }
                                }
                                .disabled(model.isLoading)
                            }

                            if !p.missingRequirements.isEmpty {
                                VStack(alignment: .leading, spacing: 6) {
                                    Text("Missing: \(p.missingRequirements.joined(separator: ", "))")
                                        .font(.callout.weight(.medium))

                                    if p.tools["ffmpeg"]?.available != true || p.tools["ffprobe"]?.available != true {
                                        Text("brew install ffmpeg")
                                            .font(.system(.caption, design: .monospaced))
                                            .textSelection(.enabled)
                                    }

                                    if p.tools["HandBrakeCLI"]?.available != true {
                                        Text("brew install handbrake")
                                            .font(.system(.caption, design: .monospaced))
                                            .textSelection(.enabled)
                                    }

                                    if !p.pillow.available {
                                        Text("python3 -m pip install Pillow==11.3.0")
                                            .font(.system(.caption, design: .monospaced))
                                            .textSelection(.enabled)
                                    }

                                    if p.python.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                                        Text("Python 3 is required before Veronica can run its engine.")
                                            .font(.caption)
                                            .foregroundStyle(.secondary)
                                    }
                                }
                                .padding(10)
                                .background(.quaternary, in: RoundedRectangle(cornerRadius: 8))
                            }

                            Divider()

                            ToolRow(name: "Python / engine runtime", ready: !p.python.isEmpty, detail: p.pythonVersion)
                            ToolRow(name: "Pillow", ready: p.pillow.available, detail: p.pillow.version)

                            ForEach(["file", "ffprobe", "ffmpeg", "HandBrakeCLI", "xattr"], id: \.self) { name in
                                ToolRow(name: name, ready: p.tools[name]?.available == true, detail: p.tools[name]?.path)
                            }
                        }
                        .padding(.vertical, 4)
                    }
                }

                GroupBox("Diagnostics") {
                    VStack(alignment: .leading, spacing: 12) {
                        Toggle("Developer Mode", isOn: Binding(get: { model.developerMode }, set: { model.setDeveloperMode($0) }))
                        Text("Developer Mode keeps more detailed local engine diagnostics. It never changes media-processing policy.")
                            .font(.caption).foregroundStyle(.secondary)
                        HStack {
                            Button("Copy Debug Info") { model.copyDiagnosticReport() }
                            Button("Export Diagnostics…") { model.exportDiagnostics() }
                            Button("Reveal Log in Finder") { model.revealLogFile() }
                        }
                        Text("Exported diagnostics are privacy-sanitized: home/library paths are replaced and media filenames are omitted from the structured event summary.")
                            .font(.caption).foregroundStyle(.secondary)
                    }.padding(.vertical, 4)
                }

                GroupBox("About") {
                    LabeledContent("Veronica version") { Text(model.snapshot?.version ?? "0.13.2") }
                    Text("Veronica uses verified staging, per-file quarantine, rollback, and durable audit history.")
                        .font(.caption).foregroundStyle(.secondary).padding(.top, 4)
                }
                .id("settings-bottom")
            }
            .frame(maxWidth: 900, alignment: .leading)
            .padding(.horizontal, 32)
            .padding(.vertical, 26)
            .frame(maxWidth: .infinity, alignment: .leading)
            }
            .task {
                guard shouldStartAtBottomForUICapture else { return }

                // Wait for the initial engine snapshot to finish populating
                // Settings before jumping to the bottom capture anchor.
                while model.isLoading || model.snapshot == nil {
                    try? await Task.sleep(nanoseconds: 100_000_000)
                }

                try? await Task.sleep(nanoseconds: 300_000_000)

                withAnimation(nil) {
                    proxy.scrollTo("settings-bottom", anchor: .bottom)
                }
            }
        }
        .background(VeronicaTheme.canvas)
        .groupBoxStyle(VeronicaGroupBoxStyle(fill: VeronicaTheme.canvas))
        .confirmationDialog(
            "Remove this folder from Veronica?",
            isPresented: Binding(
                get: { pendingRemoval != nil },
                set: { if !$0 { pendingRemoval = nil } }
            )
        ) {
            Button("Remove Folder", role: .destructive) {
                if let path = pendingRemoval {
                    Task { await model.removeScanFolder(path) }
                }
                pendingRemoval = nil
            }

            Button("Cancel", role: .cancel) {
                pendingRemoval = nil
            }
        } message: {
            Text("Veronica will stop scanning this folder. Its media and Veronica history will not be deleted.")
        }
    }
}

private struct ToolRow: View {
    let name: String
    let ready: Bool
    let detail: String?
    var body: some View {
        HStack {
            Image(systemName: ready ? "checkmark.circle.fill" : "xmark.circle.fill")
                .foregroundStyle(ready ? Color.green : Color.red)
            Text(name)
            Spacer()
            if let detail, !detail.isEmpty {
                Text(detail).font(.caption).foregroundStyle(.secondary).lineLimit(1).truncationMode(.middle)
            }
        }
    }
}
