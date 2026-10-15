import SwiftUI

struct SettingsView: View {
    @EnvironmentObject var model: AppModel
    @State private var pendingRemoval: String?
    @State private var jpegQualityDraft: Double?
    @State private var imageOutputFormatDraft: String?
    @State private var imageMegapixelsText = ""
    @State private var videoMaxEdgeDraft: Int?
    @State private var audioThresholdText = ""
    @State private var videoMetadataCleanupDraft: Bool?

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

    private func seedOptimizationDrafts(from settings: OptimizationSettings) {
        if imageOutputFormatDraft == nil {
            imageOutputFormatDraft = settings.imageOutputFormat
        }

        if imageMegapixelsText.isEmpty {
            imageMegapixelsText = "\(Int(settings.imageMaxMegapixels.rounded()))"
        }

        if jpegQualityDraft == nil {
            jpegQualityDraft = Double(settings.jpegQuality)
        }

        if videoMaxEdgeDraft == nil {
            videoMaxEdgeDraft = settings.videoMaxEdge
        }

        if audioThresholdText.isEmpty {
            audioThresholdText = "\(settings.audioMinSizeMB)"
        }

        if videoMetadataCleanupDraft == nil {
            videoMetadataCleanupDraft = settings.videoAllowCameraMetadataDrop
        }
    }

    private var recipeMatchesRecommended: Bool {
        let recommended = OptimizationSettings.recommended
        guard let settings = model.snapshot?.optimizationSettings else { return true }

        return (imageOutputFormatDraft ?? settings.imageOutputFormat) == recommended.imageOutputFormat
            && Int((jpegQualityDraft ?? Double(settings.jpegQuality)).rounded()) == recommended.jpegQuality
            && (videoMaxEdgeDraft ?? settings.videoMaxEdge) == recommended.videoMaxEdge
            && (Int(imageMegapixelsText) ?? -1) == Int(recommended.imageMaxMegapixels.rounded())
            && (Int(audioThresholdText) ?? -1) == recommended.audioMinSizeMB
            && (videoMetadataCleanupDraft ?? settings.videoAllowCameraMetadataDrop) == recommended.videoAllowCameraMetadataDrop
    }

    private func restoreRecommendedRecipe() {
        let recommended = OptimizationSettings.recommended
        imageOutputFormatDraft = recommended.imageOutputFormat
        imageMegapixelsText = "\(Int(recommended.imageMaxMegapixels.rounded()))"
        jpegQualityDraft = Double(recommended.jpegQuality)
        videoMaxEdgeDraft = recommended.videoMaxEdge
        audioThresholdText = "\(recommended.audioMinSizeMB)"
        videoMetadataCleanupDraft = recommended.videoAllowCameraMetadataDrop

        Task {
            await model.restoreRecommendedOptimizationSettings()
        }
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
                        VStack(alignment: .leading, spacing: 16) {
                            Text("Choose exactly which file extensions Veronica may optimize. Disabled extensions are still inventoried, but Veronica will not change them.")
                                .font(.caption)
                                .foregroundStyle(.secondary)

                            MediaExtensionGroup(
                                title: "Images",
                                extensions: MediaProcessingPolicy.allImageExtensions,
                                enabled: model.imageExtensions
                            ) { next in
                                Task {
                                    await model.updateMediaProcessing(imageExtensions: next)
                                }
                            }

                            MediaExtensionGroup(
                                title: "Videos",
                                extensions: MediaProcessingPolicy.allVideoExtensions,
                                enabled: model.videoExtensions
                            ) { next in
                                Task {
                                    await model.updateMediaProcessing(videoExtensions: next)
                                }
                            }

                            MediaExtensionGroup(
                                title: "Audio",
                                extensions: MediaProcessingPolicy.allAudioExtensions,
                                enabled: model.audioExtensions
                            ) { next in
                                Task {
                                    await model.updateMediaProcessing(audioExtensions: next)
                                }
                            }

                            Label(
                                "Turning off every extension in a category disables that category.",
                                systemImage: "info.circle"
                            )
                            .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        .padding(.vertical, 4)
                        .disabled(model.isRunningAnnual)
                    }
                }

                GroupBox("Optimization recipe") {
                    if let settings = model.snapshot?.optimizationSettings {
                        let imageOutputFormat = imageOutputFormatDraft ?? settings.imageOutputFormat
                        let jpegQuality = jpegQualityDraft ?? Double(settings.jpegQuality)
                        let videoMaxEdge = videoMaxEdgeDraft ?? settings.videoMaxEdge
                        let videoMetadataCleanup = videoMetadataCleanupDraft ?? settings.videoAllowCameraMetadataDrop

                        VStack(alignment: .leading, spacing: 16) {
                            HStack(alignment: .firstTextBaseline, spacing: 16) {
                                Text("Choose how Veronica creates smaller files. Changes apply to the next analysis and never rewrite existing committed history.")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)

                                Spacer()

                                Button("Restore Recommended Recipe") {
                                    restoreRecommendedRecipe()
                                }
                                .disabled(model.isRunningAnnual || recipeMatchesRecommended)
                            }

                            LabeledContent("Image export") {
                                Picker(
                                    "Image export",
                                    selection: Binding(
                                        get: { imageOutputFormat },
                                        set: { value in
                                            imageOutputFormatDraft = value
                                            Task {
                                                await model.updateOptimizationSettings(
                                                    imageFormat: value
                                                )
                                            }
                                        }
                                    )
                                ) {
                                    Text("JPEG").tag("jpeg")
                                    Text("PNG").tag("png")
                                }
                                .pickerStyle(.segmented)
                                .frame(width: 190)
                            }

                            Text("JPEG is the default for smaller photo-style images. PNG is preserved automatically for images with transparency.")
                                .font(.caption)
                                .foregroundStyle(.secondary)

                            LabeledContent("Image size target") {
                                SettingsNumericField(
                                    text: $imageMegapixelsText,
                                    range: 1...60,
                                    suffix: "MP max"
                                ) { value in
                                    imageMegapixelsText = "\(value)"
                                    Task {
                                        await model.updateOptimizationSettings(
                                            imageMaxMegapixels: Double(value)
                                        )
                                    }
                                }
                            }

                            LabeledContent("JPEG quality") {
                                HStack(spacing: 12) {
                                    Slider(
                                        value: Binding(
                                            get: { jpegQuality },
                                            set: { value in
                                                jpegQualityDraft = value
                                            }
                                        ),
                                        in: 30...95,
                                        step: 1,
                                        onEditingChanged: { editing in
                                            guard !editing else { return }
                                            let nextValue = Int((jpegQualityDraft ?? Double(settings.jpegQuality)).rounded())
                                            jpegQualityDraft = Double(nextValue)
                                            guard nextValue != settings.jpegQuality else { return }

                                            Task {
                                                await model.updateOptimizationSettings(
                                                    jpegQuality: nextValue
                                                )
                                            }
                                        }
                                    )
                                    .frame(width: 190)

                                    Text("\(Int(jpegQuality.rounded()))")
                                        .monospacedDigit()
                                        .frame(width: 44, alignment: .trailing)
                                }
                            }

                            LabeledContent("Video size target") {
                                Picker(
                                    "Video size target",
                                    selection: Binding(
                                        get: { videoMaxEdge },
                                        set: { value in
                                            videoMaxEdgeDraft = value
                                            Task {
                                                await model.updateOptimizationSettings(
                                                    videoMaxEdge: value
                                                )
                                            }
                                        }
                                    )
                                ) {
                                    Text("720p").tag(1280)
                                    Text("1080p").tag(1920)
                                    Text("4K").tag(3840)
                                }
                                .pickerStyle(.segmented)
                                .frame(width: 280)
                            }

                            Toggle(
                                "Streamline auxiliary video metadata cleanup",
                                isOn: Binding(
                                    get: { videoMetadataCleanup },
                                    set: { value in
                                        videoMetadataCleanupDraft = value
                                        Task {
                                            await model.updateOptimizationSettings(
                                                videoAllowCameraMetadataDrop: value
                                            )
                                        }
                                    }
                                )
                            )

                            Text("When enabled, Veronica may drop auxiliary data tracks during video optimization while preserving video, audio, subtitles, attachments, chapters, timing, color, and geometry checks.")
                                .font(.caption)
                                .foregroundStyle(.secondary)

                            LabeledContent("Audio threshold") {
                                SettingsNumericField(
                                    text: $audioThresholdText,
                                    range: 1...500,
                                    suffix: "MB",
                                    prefix: "over"
                                ) { value in
                                    audioThresholdText = "\(value)"
                                    Task {
                                        await model.updateOptimizationSettings(
                                            audioMinSizeMB: value
                                        )
                                    }
                                }
                            }

                            Label(
                                "After changing the recipe, run Analyze Library again to preview the new plan.",
                                systemImage: "arrow.clockwise"
                            )
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        }
                        .padding(.vertical, 4)
                        .disabled(model.isRunningAnnual)
                        .onAppear {
                            seedOptimizationDrafts(from: settings)
                        }
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
                                .frame(width: 280)
                            }

                            LabeledContent("Maximum filename size") {
                                SettingsNumberStepper(
                                    value: naming.maxBytes,
                                    range: 32...255,
                                    suffix: "UTF-8 bytes"
                                ) { value in
                                    Task {
                                        await model.updateFilenamePolicy(maxBytes: value)
                                    }
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

                GroupBox("Notifications") {
                    VStack(alignment: .leading, spacing: 12) {
                        HStack(alignment: .firstTextBaseline) {
                            Toggle(
                                "Notify when analysis or optimization finishes",
                                isOn: Binding(
                                    get: { model.notificationsEnabled },
                                    set: { model.setNotificationsEnabled($0) }
                                )
                            )

                            Spacer()

                            Text(model.notificationStatus)
                                .font(.caption.weight(.semibold))
                                .foregroundStyle(
                                    model.notificationStatus == "Enabled"
                                        ? Color.green
                                        : VeronicaTheme.secondaryInk
                                )
                        }

                        Text(model.notificationStatus == "Signed build required"
                             ? "This local ad-hoc build cannot render native macOS notifications correctly. Use a signed Veronica build for system notifications with the app icon."
                             : "Veronica sends notifications only for meaningful outcomes: analysis complete, analysis stopped, optimization complete, or optimization stopped.")
                            .font(.caption)
                            .foregroundStyle(.secondary)

                        HStack {
                            Button("Allow Notifications") {
                                model.requestNotificationPermission()
                            }

                            Button("Send Test Notification") {
                                model.sendTestNotification()
                            }

                            Button("Open macOS Notification Settings") {
                                model.openNotificationSettings()
                            }
                        }
                        .disabled(!model.notificationsEnabled)
                    }
                    .padding(.vertical, 4)
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
                    LabeledContent("Veronica version") { Text(model.snapshot?.version ?? "0.13.5") }
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

private struct SettingsNumberStepper: View {
    let value: Int
    let range: ClosedRange<Int>
    let suffix: String
    var prefix: String = ""
    let onChange: (Int) -> Void

    var body: some View {
        HStack(spacing: 8) {
            Button {
                update(value - 1)
            } label: {
                Image(systemName: "minus")
                    .frame(width: 18, height: 18)
            }
            .buttonStyle(.bordered)
            .help("Decrease")
            .disabled(value <= range.lowerBound)

            Text(label)
                .font(.system(.body, design: .monospaced))
                .lineLimit(1)
                .frame(width: 150, alignment: .center)
                .padding(.horizontal, 10)
                .padding(.vertical, 5)
                .background(.quaternary, in: RoundedRectangle(cornerRadius: 6))

            Button {
                update(value + 1)
            } label: {
                Image(systemName: "plus")
                    .frame(width: 18, height: 18)
            }
            .buttonStyle(.bordered)
            .help("Increase")
            .disabled(value >= range.upperBound)
        }
        .fixedSize()
    }

    private var label: String {
        if prefix.isEmpty {
            return "\(value) \(suffix)"
        }

        return "\(prefix) \(value) \(suffix)"
    }

    private func update(_ nextValue: Int) {
        onChange(min(max(nextValue, range.lowerBound), range.upperBound))
    }
}

private struct MediaExtensionGroup: View {
    let title: String
    let extensions: [String]
    let enabled: Set<String>
    let onChange: (Set<String>) -> Void

    private var enabledCount: Int {
        extensions.filter { enabled.contains($0) }.count
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(title)
                        .font(.headline)

                    Text("\(enabledCount) of \(extensions.count) enabled")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                Spacer()

                Button(enabledCount == extensions.count ? "Turn All Off" : "Turn All On") {
                    onChange(enabledCount == extensions.count ? Set<String>() : Set(extensions))
                }
                .buttonStyle(.link)
            }

            LazyVGrid(
                columns: [
                    GridItem(.adaptive(minimum: 78), spacing: 8, alignment: .leading)
                ],
                alignment: .leading,
                spacing: 8
            ) {
                ForEach(extensions, id: \.self) { ext in
                    Toggle(ext.uppercased(), isOn: Binding(
                        get: { enabled.contains(ext) },
                        set: { isOn in
                            var next = enabled
                            if isOn {
                                next.insert(ext)
                            } else {
                                next.remove(ext)
                            }
                            onChange(next)
                        }
                    ))
                    .toggleStyle(.checkbox)
                    .font(.callout)
                }
            }
        }
        .padding(.vertical, 2)
    }
}

private struct SettingsNumericField: View {
    @Binding var text: String
    @FocusState private var isFocused: Bool

    let range: ClosedRange<Int>
    let suffix: String
    var prefix: String = ""
    let onCommit: (Int) -> Void

    var body: some View {
        HStack(spacing: 8) {
            if !prefix.isEmpty {
                Text(prefix)
                    .foregroundStyle(.secondary)
            }

            TextField("", text: $text)
                .textFieldStyle(.roundedBorder)
                .font(.system(.body, design: .monospaced))
                .frame(width: 72)
                .multilineTextAlignment(.trailing)
                .focused($isFocused)
                .onSubmit(commit)

            Text(suffix)
                .foregroundStyle(.secondary)
        }
        .fixedSize()
        .onChange(of: text) { newValue in
            let filtered = newValue.filter(\.isNumber)
            if filtered != newValue {
                text = filtered
            }
        }
        .onChange(of: isFocused) { focused in
            if !focused {
                commit()
            }
        }
    }

    private func commit() {
        let parsed = Int(text) ?? range.lowerBound
        let clamped = min(max(parsed, range.lowerBound), range.upperBound)
        text = "\(clamped)"
        onCommit(clamped)
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
