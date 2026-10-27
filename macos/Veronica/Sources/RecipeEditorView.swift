import SwiftUI

extension ProcessingRecipe {
    var displaySummary: String {
        var parts: [String] = []
        if mediaProcessing.images {
            let megapixels = imageMegapixelLabel(optimizationSettings.imageMaxMegapixels)
            parts.append(optimizationSettings.imageOutputFormat == "png"
                ? "Images · PNG · \(megapixels) MP"
                : "Images · JPEG \(optimizationSettings.jpegQuality) · \(megapixels) MP")
        }
        if mediaProcessing.videos { parts.append("Video") }
        if mediaProcessing.audio { parts.append("Audio") }
        if parts.isEmpty { parts.append("No media types enabled") }
        parts.append(dateScope.mode == "older_than_two_years" ? "Older than 2 years" : dateScope.summary)
        return parts.joined(separator: " · ")
    }

    var validationMessage: String? {
        let settings = optimizationSettings
        guard settings.imageMaxMegapixels.isFinite, (1...60).contains(settings.imageMaxMegapixels) else {
            return "Choose an image size between 1 and 60 megapixels."
        }
        guard (30...95).contains(settings.jpegQuality) else { return "Choose a JPEG quality between 30 and 95." }
        guard (480...7680).contains(settings.videoMaxEdge) else { return "Choose a video dimension between 480 and 7680 pixels." }
        guard settings.minimumSavingPercent.isFinite, (0...90).contains(settings.minimumSavingPercent),
              settings.minimumSavingMB.isFinite, (0...1024).contains(settings.minimumSavingMB) else {
            return "Choose a saving between 0 and 90 percent, and between 0 and 1024 MB."
        }
        guard FilenameDateStyle.isValid(filenamePolicy.dateFormat) else {
            return "Use YYYY (or YY), MM and DD once each. Use dashes, dots, underscores or spaces, and end with a separator."
        }
        guard FilenameDateStyle.example(filenamePolicy.dateFormat).utf8.count - "photo.jpg".utf8.count + 6 <= filenamePolicy.maxBytes else {
            return "Shorten the date style or increase the filename length."
        }
        guard (1...500).contains(settings.audioMinSizeMB) else { return "Choose an audio threshold between 1 and 500 MB." }
        guard (32...255).contains(filenamePolicy.maxBytes) else { return "Choose a filename limit between 32 and 255 bytes." }
        for name in mediaProcessing.excludedDirectoryNames {
            if name.isEmpty || name == "." || name == ".." || name.contains("/") || name.contains("\\")
                || name.unicodeScalars.contains(where: CharacterSet.controlCharacters.contains) {
                return "Skipped subfolders must be folder names, without slashes, paths, or control characters."
            }
        }
        if dateScope.mode == "within" || dateScope.mode == "outside" {
            guard let start = dateScope.start, let end = dateScope.end, start <= end else {
                return "The start date must be on or before the end date."
            }
        }
        return nil
    }
}

private func imageMegapixelLabel(_ value: Double) -> String {
    value.formatted(.number.precision(.fractionLength(0...1)))
}

private enum RecipePane: String, CaseIterable, Identifiable {
    case images = "Photos", video = "Video", audio = "Audio", organization = "Files & dates"
    var id: String { rawValue }
    var icon: String {
        switch self { case .images: return "photo"; case .video: return "video"; case .audio: return "waveform"; case .organization: return "folder" }
    }
}

struct RecipeEditorView: View {
    @Binding var recipe: ProcessingRecipe
    @State private var pane: RecipePane = .images
    @State private var customVideoResolution = false
    @State private var customDateStyle = false
    private let standardVideoEdges = [854, 1280, 1920, 3840]
    @State private var rememberedImages: [String] = []
    @State private var rememberedVideos: [String] = []
    @State private var rememberedAudio: [String] = []

    private static let dateFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter
    }()

    var body: some View {
        HStack(spacing: 0) {
            VStack(spacing: 6) {
                ForEach(RecipePane.allCases) { item in
                    Button { pane = item } label: {
                        Label(item.rawValue, systemImage: item.icon)
                            .font(.callout.weight(pane == item ? .semibold : .regular))
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.horizontal, 12).padding(.vertical, 11)
                            .background(pane == item ? VeronicaTheme.accentFill : .clear, in: RoundedRectangle(cornerRadius: 10))
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(pane == item ? VeronicaTheme.accent : VeronicaTheme.ink)
                    .accessibilityIdentifier("veronica.recipe.pane.\(item.id)")
                }
                Spacer()
            }.padding(12).frame(width: 155)
            Divider()
            Form {
                switch pane {
                case .images: photoControls
                case .video: videoControls
                case .audio: audioControls
                case .organization: organizationControls
                }
            }
            .formStyle(.grouped)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .id(pane)
        }
        .tint(VeronicaTheme.accent)
    }

    @ViewBuilder private var photoControls: some View {
        Section {
            Toggle("Optimize photos", isOn: mediaEnabled("images"))
                .accessibilityIdentifier("veronica.recipe.imagesEnabled")
            Text(recipe.mediaProcessing.images
                 ? "Make photo files smaller using the settings below."
                 : "Photos will be left unchanged. Turn this on to choose photo settings.")
                .font(.caption).foregroundStyle(.secondary)
        }
        if recipe.mediaProcessing.images {
            Section("Size & quality") {
                RecipeChoiceMenu(title: "Save photos as", selection: $recipe.optimizationSettings.imageOutputFormat,
                                 choices: [("jpeg", "JPEG · smaller files"), ("png", "PNG · lossless compression")])
                    .accessibilityIdentifier("veronica.recipe.imageFormat")
                HStack {
                    Text("Maximum photo size")
                    Spacer()
                    RecipeDecimalField(title: "Maximum photo size", value: $recipe.optimizationSettings.imageMaxMegapixels)
                    Text("MP").foregroundStyle(.secondary)
                }
                Toggle("Also compress photos below this size", isOn: $recipe.optimizationSettings.recompressImagesBelowTarget)
                    .accessibilityIdentifier("veronica.recipe.recompressSmallPhotos")
                Text("Larger photos are resized to fit. Smaller photos keep their dimensions. Turn this off to leave smaller photos uncompressed. Transparency is always preserved.")
                    .font(.caption).foregroundStyle(.secondary)
                if recipe.optimizationSettings.imageOutputFormat == "jpeg" {
                    VStack(alignment: .leading, spacing: 8) {
                        HStack {
                            Text("JPEG quality")
                            Spacer()
                            RecipeIntegerField(title: "JPEG quality", value: $recipe.optimizationSettings.jpegQuality)
                        }
                        Slider(value: Binding(get: { Double(recipe.optimizationSettings.jpegQuality) },
                                              set: { recipe.optimizationSettings.jpegQuality = Int($0.rounded()) }), in: 30...95, step: 1)
                            .accessibilityLabel("JPEG quality slider")
                        HStack { Text("Smaller files"); Spacer(); Text("Higher quality") }
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
            }

        }
        Section {
            SettingsDisclosure("Photo formats") {
                RecipeExtensionGroup(title: "Photo formats", extensions: MediaProcessingPolicy.allImageExtensions,
                                     enabled: Set(recipe.mediaProcessing.imageExtensions)) { values in
                    recipe.mediaProcessing.imageExtensions = MediaProcessingPolicy.allImageExtensions.filter(values.contains)
                    recipe.mediaProcessing.images = !values.isEmpty
                }
            }
        }
    }

    @ViewBuilder private var videoControls: some View {
        Section {
            Toggle("Optimize videos", isOn: mediaEnabled("videos"))
                .accessibilityIdentifier("veronica.recipe.videosEnabled")
            Text(recipe.mediaProcessing.videos ? "Save videos as MP4 with H.264 video and AAC stereo sound."
                 : "Videos will be left unchanged. Turn this on to choose video settings.")
                .font(.caption).foregroundStyle(.secondary)
        }
        if recipe.mediaProcessing.videos {
            Section("Video quality") {
                RecipeChoiceMenu(title: "Maximum resolution", selection: Binding(
                    get: { customVideoResolution || !standardVideoEdges.contains(recipe.optimizationSettings.videoMaxEdge) ? 0 : recipe.optimizationSettings.videoMaxEdge },
                    set: { value in
                        customVideoResolution = value == 0
                        if value != 0 { recipe.optimizationSettings.videoMaxEdge = value }
                    }), choices: [(854, "480p"), (1280, "720p"), (1920, "1080p"), (3840, "4K"), (0, "Custom…")])
                    .accessibilityIdentifier("veronica.recipe.videoResolution")
                if customVideoResolution || !standardVideoEdges.contains(recipe.optimizationSettings.videoMaxEdge) {
                    HStack {
                        Text("Maximum dimension")
                        Spacer()
                        RecipeIntegerField(title: "Custom video dimension", value: $recipe.optimizationSettings.videoMaxEdge)
                            .accessibilityIdentifier("veronica.recipe.customVideoDimension")
                        Text("px").foregroundStyle(.secondary)
                    }
                    Text("The longest side of the video, from 480 to 7680 pixels.")
                        .font(.caption).foregroundStyle(.secondary)
                }
                Text("Smaller videos are never enlarged. Videos that might lose important content are held for review.")
                    .font(.caption).foregroundStyle(.secondary)
                Toggle("Remove supported camera metadata", isOn: $recipe.optimizationSettings.videoAllowCameraMetadataDrop)
                Text("Removes supported camera data tracks. Unknown tracks still need your review.")
                    .font(.caption).foregroundStyle(.secondary)
            }

        }
        Section {
            SettingsDisclosure("Video formats") {
                RecipeExtensionGroup(title: "Video formats", extensions: MediaProcessingPolicy.allVideoExtensions,
                                     enabled: Set(recipe.mediaProcessing.videoExtensions)) { values in
                    recipe.mediaProcessing.videoExtensions = MediaProcessingPolicy.allVideoExtensions.filter(values.contains)
                    recipe.mediaProcessing.videos = !values.isEmpty
                }
            }
        }
    }

    @ViewBuilder private var audioControls: some View {
        Section {
            Toggle("Optimize audio", isOn: mediaEnabled("audio"))
                .accessibilityIdentifier("veronica.recipe.audioEnabled")
            Text(recipe.mediaProcessing.audio ? "Convert eligible audio files to MP3 at 128 kbps."
                 : "Audio will be left unchanged. Turn this on to choose audio settings.")
                .font(.caption).foregroundStyle(.secondary)
        }
        if recipe.mediaProcessing.audio {
            Section("File size") {
                HStack {
                    Text("Only process files larger than")
                    Spacer()
                    RecipeIntegerField(title: "Audio size threshold", value: $recipe.optimizationSettings.audioMinSizeMB)
                    Text("MB").foregroundStyle(.secondary)
                }
                Text("Smaller audio files and files already near the target quality are left unchanged.")
                    .font(.caption).foregroundStyle(.secondary)
            }

        }
        Section {
            SettingsDisclosure("Audio formats") {
                RecipeExtensionGroup(title: "Audio formats", extensions: MediaProcessingPolicy.allAudioExtensions,
                                     enabled: Set(recipe.mediaProcessing.audioExtensions)) { values in
                    recipe.mediaProcessing.audioExtensions = MediaProcessingPolicy.allAudioExtensions.filter(values.contains)
                    recipe.mediaProcessing.audio = !values.isEmpty
                }
            }
        }
    }

    @ViewBuilder private var organizationControls: some View {
        Section("Which files to include") {
            RecipeChoiceMenu(title: "File dates", selection: Binding(get: { recipe.dateScope.mode }, set: changeDateMode),
                choices: [("older_than_two_years", "Older than 2 years"), ("all", "All dates"),
                          ("within", "Within a date range"), ("outside", "Outside a date range")]
                    + (recipe.dateScope.mode == "legacy" ? [("legacy", "Previous annual cutoff")] : []))
                .accessibilityIdentifier("veronica.recipe.dateScope")
            if ["within", "outside"].contains(recipe.dateScope.mode) {
                DatePicker("From", selection: dateBinding(start: true), displayedComponents: .date)
                DatePicker("Through", selection: dateBinding(start: false), displayedComponents: .date)
            }
            Text(recipe.dateScope.summary).font(.caption).foregroundStyle(.secondary)
            Text("Veronica uses the date embedded in each file. Files without a usable embedded date are left unchanged for review.")
                .font(.caption).foregroundStyle(.secondary)
        }
        Section("File names") {
            Toggle("Add the date to file names", isOn: $recipe.filenamePolicy.enabled)
                .accessibilityIdentifier("veronica.recipe.renameFiles")
            if recipe.filenamePolicy.enabled {
                RecipeChoiceMenu(title: "Date style", selection: Binding(
                    get: { customDateStyle || !FilenameDateStyle.choices.contains(where: { $0.0 == recipe.filenamePolicy.dateFormat }) ? "custom" : recipe.filenamePolicy.dateFormat },
                    set: { value in
                        customDateStyle = value == "custom"
                        if value != "custom" { recipe.filenamePolicy.dateFormat = value }
                    }), choices: FilenameDateStyle.choices + [("custom", "Custom…")])
                    .accessibilityIdentifier("veronica.recipe.filenameFormat")
                if customDateStyle || !FilenameDateStyle.choices.contains(where: { $0.0 == recipe.filenamePolicy.dateFormat }) {
                    TextField("Date pattern", text: $recipe.filenamePolicy.dateFormat)
                        .textFieldStyle(.roundedBorder).autocorrectionDisabled()
                        .accessibilityIdentifier("veronica.recipe.customDateStyle")
                    Text("Use YYYY (or YY), MM and DD. Separate with dashes, dots, underscores or spaces; end with a separator.")
                        .font(.caption).foregroundStyle(.secondary)
                }
                if FilenameDateStyle.isValid(recipe.filenamePolicy.dateFormat) {
                    Text("Example: \(FilenameDateStyle.example(recipe.filenamePolicy.dateFormat))")
                        .font(.callout.monospaced()).foregroundStyle(VeronicaTheme.accent)
                        .accessibilityIdentifier("veronica.recipe.filenameExample")
                }
                Text("Veronica uses the embedded date. Existing date prefixes are not added twice.")
                    .font(.caption).foregroundStyle(.secondary)
                SettingsDisclosure("Filename length") {
                    HStack {
                        Text("Maximum length")
                        Spacer()
                        RecipeIntegerField(title: "Maximum filename length", value: $recipe.filenamePolicy.maxBytes)
                        Text("bytes").foregroundStyle(.secondary)
                    }
                    Text("Includes the date, name and extension. Accented characters can use more than one byte.")
                        .font(.caption).foregroundStyle(.secondary)
                }
            } else {
                Text("Keep existing names, apart from extensions changed by conversion.").font(.caption).foregroundStyle(.secondary)
            }
        }
        Section("Before replacing an original") {
            HStack {
                Text("Save at least")
                Spacer()
                RecipeDecimalField(title: "Minimum saving percentage", value: $recipe.optimizationSettings.minimumSavingPercent)
                    .accessibilityIdentifier("veronica.recipe.minimumSavingPercent")
                Text("%").foregroundStyle(.secondary)
            }
            HStack {
                Text("Or save at least")
                Spacer()
                RecipeDecimalField(title: "Minimum saving in MB", value: $recipe.optimizationSettings.minimumSavingMB)
                    .accessibilityIdentifier("veronica.recipe.minimumSavingMB")
                Text("MB").foregroundStyle(.secondary)
            }
            Text("Keep the original unless the verified result is smaller and meets either saving target.")
                .font(.caption).foregroundStyle(.secondary)
        }
        Section {
            SettingsDisclosure("Skip subfolders by name") {
                RecipeExcludedFoldersField(names: $recipe.mediaProcessing.excludedDirectoryNames)
                Text("Separate names with commas. Matching subfolders are skipped wherever they appear. Clear this list to skip none.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
    }

    private func mediaEnabled(_ kind: String) -> Binding<Bool> {
        Binding(get: {
            switch kind { case "images": return recipe.mediaProcessing.images; case "videos": return recipe.mediaProcessing.videos; default: return recipe.mediaProcessing.audio }
        }, set: { enabled in
            switch kind {
            case "images":
                if !enabled { rememberedImages = recipe.mediaProcessing.imageExtensions }
                recipe.mediaProcessing.imageExtensions = enabled ? (rememberedImages.isEmpty ? MediaProcessingPolicy.recommended.imageExtensions : rememberedImages) : []
                recipe.mediaProcessing.images = enabled
            case "videos":
                if !enabled { rememberedVideos = recipe.mediaProcessing.videoExtensions }
                recipe.mediaProcessing.videoExtensions = enabled ? (rememberedVideos.isEmpty ? MediaProcessingPolicy.allVideoExtensions : rememberedVideos) : []
                recipe.mediaProcessing.videos = enabled
            default:
                if !enabled { rememberedAudio = recipe.mediaProcessing.audioExtensions }
                recipe.mediaProcessing.audioExtensions = enabled ? (rememberedAudio.isEmpty ? MediaProcessingPolicy.allAudioExtensions : rememberedAudio) : []
                recipe.mediaProcessing.audio = enabled
            }
        })
    }

    private func changeDateMode(_ mode: String) {
        recipe.dateScope.mode = mode
        recipe.dateScope.legacy = mode == "legacy"
        if mode == "within" || mode == "outside" {
            if recipe.dateScope.start == nil { recipe.dateScope.start = Self.dateFormatter.string(from: Date()) }
            if recipe.dateScope.end == nil { recipe.dateScope.end = Self.dateFormatter.string(from: Date()) }
        } else { recipe.dateScope.start = nil; recipe.dateScope.end = nil }
    }

    private func dateBinding(start: Bool) -> Binding<Date> {
        Binding(get: {
            let value = start ? recipe.dateScope.start : recipe.dateScope.end
            return value.flatMap(Self.dateFormatter.date(from:)) ?? Date()
        }, set: { date in
            if start { recipe.dateScope.start = Self.dateFormatter.string(from: date) }
            else { recipe.dateScope.end = Self.dateFormatter.string(from: date) }
        })
    }
}

// A menu makes the complete settings row clickable and keeps selection actions
// stable when custom choices add fields or a preset refreshes the draft.
struct RecipeChoiceMenu<Value: Hashable>: View {
    let title: String
    @Binding var selection: Value
    let choices: [(Value, String)]

    var body: some View {
        Menu {
            ForEach(choices, id: \.0) { value, label in
                Button { selection = value } label: {
                    if value == selection { Label(label, systemImage: "checkmark") }
                    else { Text(label) }
                }
            }
        } label: {
            HStack(spacing: 12) {
                Text(title).foregroundStyle(.primary)
                Spacer()
                Text(choices.first { $0.0 == selection }?.1 ?? "Custom…")
                    .foregroundStyle(.secondary)
                Image(systemName: "chevron.up.chevron.down").font(.caption2.weight(.semibold))
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading).contentShape(Rectangle())
        }
        .menuStyle(.borderlessButton).menuIndicator(.hidden)
        .accessibilityLabel(title)
        .accessibilityValue(choices.first { $0.0 == selection }?.1 ?? "Custom")
    }
}

// Make the entire row clickable, including its label and empty space.
struct SettingsDisclosure<Content: View>: View {
    let title: String
    let content: Content
    @State private var expanded = false

    init(_ title: String, @ViewBuilder content: () -> Content) {
        self.title = title
        self.content = content()
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Button { expanded.toggle() } label: {
                HStack(spacing: 7) {
                    Image(systemName: expanded ? "chevron.down" : "chevron.right")
                        .font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                    Text(title)
                    Spacer(minLength: 0)
                }
                .frame(maxWidth: .infinity, alignment: .leading).padding(.vertical, 5)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain).accessibilityLabel(title)
            .accessibilityValue(expanded ? "Expanded" : "Collapsed")
            if expanded { content }
        }.frame(maxWidth: .infinity, alignment: .leading)
    }
}

// Text bindings update the recipe while the user types. Invalid text remains
// visible and produces an out-of-range draft, so Save never uses an old value.
private struct RecipeIntegerField: View {
    let title: String
    @Binding var value: Int
    @State private var text: String
    @FocusState private var focused: Bool

    init(title: String, value: Binding<Int>) {
        self.title = title
        _value = value
        _text = State(initialValue: String(value.wrappedValue))
    }

    var body: some View {
        TextField(title, text: $text)
            .textFieldStyle(.roundedBorder).labelsHidden().frame(width: 76)
            .accessibilityLabel(title)
            .multilineTextAlignment(.trailing)
            .focused($focused)
            .onChange(of: text) { next in value = Int(next) ?? 0 }
            .onChange(of: value) { next in
                if (!focused || Int(text) != nil), Int(text) != next { text = String(next) }
            }
    }
}

private struct RecipeExcludedFoldersField: View {
    @Binding var names: [String]
    @State private var text: String
    @FocusState private var focused: Bool

    init(names: Binding<[String]>) {
        _names = names
        _text = State(initialValue: names.wrappedValue.joined(separator: ", "))
    }

    var body: some View {
        TextEditor(text: $text)
            .font(.body)
            .frame(height: 76)
            .padding(5)
            .background(VeronicaTheme.panelFill)
            .overlay(RoundedRectangle(cornerRadius: 6).stroke(VeronicaTheme.border))
            .focused($focused)
            .accessibilityLabel("Skipped subfolder names")
            .onChange(of: text) { next in names = Self.parse(next) }
            .onChange(of: names) { next in
                if !focused && Self.parse(text) != next { text = next.joined(separator: ", ") }
            }
    }

    private static func parse(_ text: String) -> [String] {
        text.components(separatedBy: CharacterSet.newlines.union(CharacterSet(charactersIn: ",")))
            .map { $0.trimmingCharacters(in: CharacterSet(charactersIn: " ")) }
            .filter { !$0.isEmpty }
    }
}

private struct RecipeDecimalField: View {
    let title: String
    @Binding var value: Double
    @State private var text: String
    @FocusState private var focused: Bool

    init(title: String, value: Binding<Double>) {
        self.title = title
        _value = value
        _text = State(initialValue: Self.label(value.wrappedValue))
    }

    var body: some View {
        TextField(title, text: $text)
            .textFieldStyle(.roundedBorder).labelsHidden().frame(width: 76)
            .accessibilityLabel(title)
            .multilineTextAlignment(.trailing)
            .focused($focused)
            // Zero is a valid saving target; invalid input must stay invalid.
            .onChange(of: text) { next in value = SettingsNumberInput.decimal(next) ?? .nan }
            .onChange(of: value) { next in
                guard next.isFinite else { return }
                if SettingsNumberInput.decimal(text) != next { text = Self.label(next) }
            }
    }

    private static func label(_ value: Double) -> String {
        guard value.isFinite else { return "" }
        return value == value.rounded() ? String(format: "%.0f", value) : String(value)
    }
}

private struct RecipeExtensionGroup: View {
    let title: String
    let extensions: [String]
    let enabled: Set<String>
    let onChange: (Set<String>) -> Void

    private var enabledCount: Int { extensions.filter(enabled.contains).count }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(title).font(.headline)
                    Text("\(enabledCount) of \(extensions.count) enabled").font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Button(enabledCount == extensions.count ? "Turn All Off" : "Turn All On") {
                    onChange(enabledCount == extensions.count ? [] : Set(extensions))
                }.buttonStyle(.link)
            }
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 78), spacing: 8, alignment: .leading)], alignment: .leading, spacing: 8) {
                ForEach(extensions, id: \.self) { ext in
                    Button {
                        var next = enabled
                        if next.contains(ext) { next.remove(ext) } else { next.insert(ext) }
                        onChange(next)
                    } label: {
                        Text(ext.trimmingCharacters(in: CharacterSet(charactersIn: ".")).uppercased())
                            .font(.callout.weight(.semibold))
                            .frame(maxWidth: .infinity).padding(.vertical, 9)
                            .background(enabled.contains(ext) ? VeronicaTheme.accent : VeronicaTheme.subtleFill,
                                        in: RoundedRectangle(cornerRadius: 9))
                            .foregroundStyle(enabled.contains(ext) ? Color.white : VeronicaTheme.secondaryInk)
                            .overlay(RoundedRectangle(cornerRadius: 9).strokeBorder(enabled.contains(ext) ? Color.clear : VeronicaTheme.border))
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(ext.uppercased() + " " + title.lowercased())
                    .accessibilityValue(enabled.contains(ext) ? "Enabled" : "Disabled")
                    .accessibilityIdentifier("veronica.recipe.format" + ext)
                }
            }
        }
        .padding(.vertical, 2)
    }
}
