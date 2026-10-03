import SwiftUI
import AppKit


private struct WindowChromeConfigurator: NSViewRepresentable {
    func makeNSView(context: Context) -> NSView {
        let view = NSView()

        DispatchQueue.main.async {
            configure(view.window)
        }

        return view
    }

    func updateNSView(_ nsView: NSView, context: Context) {
        DispatchQueue.main.async {
            configure(nsView.window)
        }
    }

    private func configure(_ window: NSWindow?) {
        guard let window else { return }

        // Follow the user's system appearance. SwiftUI and AppKit controls
        // inherit the current light/dark appearance from the window.
        window.backgroundColor = .windowBackgroundColor
        window.titleVisibility = .hidden
        window.titlebarAppearsTransparent = true
        window.toolbarStyle = .unified
    }
}


enum VeronicaTheme {
    // Brand palette:
    // Adaptive system surfaces / semantic ink / Indigo Bloom accent
    static let canvas = Color(nsColor: .windowBackgroundColor)
    static let ink = Color(nsColor: .labelColor)
    static let accent = Color(
        red: 129.0 / 255.0,
        green: 60.0 / 255.0,
        blue: 176.0 / 255.0
    )

    static let subtleFill = Color(nsColor: .controlBackgroundColor)
    static let strongerFill = Color(nsColor: .underPageBackgroundColor)
    static let border = Color(nsColor: .separatorColor)
    static let secondaryInk = Color(nsColor: .secondaryLabelColor)
    static let tertiaryInk = Color(nsColor: .tertiaryLabelColor)
    static let accentFill = accent.opacity(0.085)
}

struct VeronicaGroupBoxStyle: GroupBoxStyle {
    let fill: Color

    init(fill: Color = VeronicaTheme.subtleFill) {
        self.fill = fill
    }

    func makeBody(configuration: Configuration) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            configuration.label
                .font(.headline)
                .foregroundStyle(VeronicaTheme.ink)

            configuration.content
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(18)
        .background(
            fill,
            in: RoundedRectangle(cornerRadius: 14, style: .continuous)
        )
        .overlay {
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .stroke(VeronicaTheme.border, lineWidth: 1)
        }
    }
}

private enum AppSection: String, CaseIterable, Identifiable {
    case dashboard = "Dashboard"
    case activity = "Activity"
    case review = "Review"
    case history = "History"
    case settings = "Settings"

    var id: String { rawValue }

    var systemImage: String {
        switch self {
        case .dashboard:
            return "gauge.with.dots.needle.67percent"
        case .activity:
            return "waveform.path.ecg"
        case .review:
            return "exclamationmark.bubble"
        case .history:
            return "clock.arrow.circlepath"
        case .settings:
            return "gearshape"
        }
    }
}

struct ContentView: View {
    @EnvironmentObject var model: AppModel
    @State private var selectedSection: AppSection

    init() {
        let arguments = ProcessInfo.processInfo.arguments
        var initialSelection: AppSection = .dashboard

        if let index = arguments.firstIndex(of: "--ui-section"),
           arguments.indices.contains(index + 1) {
            let requested = arguments[index + 1].lowercased()

            if let section = AppSection.allCases.first(
                where: { $0.rawValue.lowercased() == requested }
            ) {
                initialSelection = section
            }
        }

        _selectedSection = State(initialValue: initialSelection)
    }

    var body: some View {
        Group {
            if model.isLoading && model.snapshot == nil {
                ProgressView("Starting Veronica…")
                    .frame(maxWidth: .infinity, maxHeight: .infinity)

            } else if let snapshot = model.snapshot, !snapshot.configured {
                SetupView()

            } else {
                mainInterface
            }
        }
        .tint(VeronicaTheme.accent)
        .foregroundStyle(VeronicaTheme.ink)
        .background(VeronicaTheme.canvas)
        .background {
            WindowChromeConfigurator()
                .frame(width: 0, height: 0)
        }
        .overlay(alignment: .bottom) {
            if let error = model.errorMessage {
                HStack(spacing: 9) {
                    Image(systemName: "exclamationmark.triangle.fill")

                    Text(error)

                    Spacer()

                    Button("Dismiss") {
                        model.errorMessage = nil
                    }
                    .buttonStyle(.link)
                }
                .font(.callout)
                .padding(12)
                .background(
                    .regularMaterial,
                    in: RoundedRectangle(cornerRadius: 12)
                )
                .shadow(radius: 6, y: 2)
                .padding()
            }
        }
    }

    private var mainInterface: some View {
        VStack(spacing: 0) {
            HStack {
                Spacer()
                toolbarNavigation
                Spacer()
            }
            .padding(.vertical, 7)
            .padding(.horizontal, 72)
            .background(VeronicaTheme.canvas)

            Divider()
                .opacity(0.45)

            ZStack {
                VeronicaTheme.canvas
                    .ignoresSafeArea()

                switch selectedSection {
                case .dashboard:
                    DashboardView()

                case .activity:
                    ActivityView()

                case .review:
                    ReviewView()

                case .history:
                    HistoryView()

                case .settings:
                    SettingsView()
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var toolbarNavigation: some View {
        HStack(spacing: 5) {
            HStack(spacing: 7) {
                Image(systemName: "photo.on.rectangle.angled")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(VeronicaTheme.accent)

                Text("Veronica")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(VeronicaTheme.ink)
            }
            .padding(.trailing, 6)

            Divider()
                .frame(height: 20)
                .padding(.horizontal, 2)

            ForEach(AppSection.allCases) { section in
                Button {
                    selectedSection = section
                } label: {
                    HStack(spacing: 6) {
                        Image(systemName: section.systemImage)
                            .frame(width: 15)

                        Text(section.rawValue)

                        if section == .review,
                           let count = model.snapshot?.unresolvedReviews.count,
                           count > 0 {
                            Text(count.formatted())
                                .font(.caption2.bold())
                                .padding(.horizontal, 6)
                                .padding(.vertical, 1)
                                .background(
                                    selectedSection == section
                                        ? VeronicaTheme.accent.opacity(0.16)
                                        : VeronicaTheme.strongerFill,
                                    in: Capsule()
                                )
                        }
                    }
                    .font(.system(size: 13, weight: .medium))
                    .fixedSize(horizontal: true, vertical: false)
                    .foregroundStyle(
                        selectedSection == section
                            ? VeronicaTheme.accent
                            : VeronicaTheme.ink
                    )
                    .padding(.horizontal, 9)
                    .padding(.vertical, 5)
                    .contentShape(Rectangle())
                    .background(
                        selectedSection == section
                            ? VeronicaTheme.accent.opacity(0.11)
                            : Color.clear,
                        in: RoundedRectangle(
                            cornerRadius: 7,
                            style: .continuous
                        )
                    )
                }
                .buttonStyle(.plain)
                .help(section.rawValue)
            }
        }
    }
}

struct SectionEmptyStateView: View {
    let title: String
    let systemImage: String
    let message: String

    var body: some View {
        VStack(spacing: 12) {
            Image(systemName: systemImage)
                .font(.system(size: 36, weight: .medium))
                .foregroundStyle(VeronicaTheme.accent)

            Text(title)
                .font(.title2.bold())
                .foregroundStyle(VeronicaTheme.ink)

            Text(message)
                .foregroundStyle(VeronicaTheme.secondaryInk)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 560)
        }
        .frame(maxWidth: .infinity, alignment: .center)
        .padding(.top, 30)
        .padding(.horizontal, 40)

        Spacer(minLength: 0)
    }
}

struct EmptyStateView: View {
    let title: String
    let systemImage: String
    let message: String

    var body: some View {
        VStack(spacing: 12) {
            Image(systemName: systemImage)
                .font(.system(size: 36, weight: .medium))
                .foregroundStyle(VeronicaTheme.accent)

            Text(title)
                .font(.title2.bold())
                .foregroundStyle(VeronicaTheme.ink)

            Text(message)
                .foregroundStyle(VeronicaTheme.secondaryInk)
                .multilineTextAlignment(.center)
                .lineSpacing(2)
        }
        .frame(maxWidth: 620)
        .padding(.horizontal, 28)
        .padding(.vertical, 44)
        .frame(maxWidth: .infinity, alignment: .top)
    }
}
