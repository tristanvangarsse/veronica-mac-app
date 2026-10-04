import SwiftUI

struct DashboardView: View {
    @EnvironmentObject var model: AppModel
    @State private var confirmRun = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                header

                if let s = model.snapshot {
                    StatusBanner(snapshot: s, running: model.isRunningAnnual, latestEvent: model.latestEvent)

                    HStack(spacing: 12) {
                        MetricCard(title: "Media files", value: s.activeAssets.formatted(), detail: "currently indexed")
                        MetricCard(title: "Changed safely", value: s.committedOutputs.formatted(), detail: "verified replacements")
                        MetricCard(title: "Space saved", value: ByteCountFormatter.string(fromByteCount: s.totalSavingBytes, countStyle: .file), detail: "across committed conversions")
                        MetricCard(title: "Needs review", value: String(s.unresolvedReviews.count), detail: s.unresolvedReviews.isEmpty ? "nothing waiting" : "requires your decision")
                    }

                    if model.isRunningAnnual {
                        LiveProgressCard(event: model.latestEvent, progress: model.currentProgress)
                    }

                    planCard(s)
                    recentCard(s)
                } else if model.isLoading {
                    coldStartSkeleton
                } else {
                    EmptyStateView(title: "Veronica couldn't read its state", systemImage: "exclamationmark.triangle", message: model.errorMessage ?? "Refresh to try again.")
                }
            }
            .frame(maxWidth: 1120, alignment: .leading)
            .padding(.horizontal, 32)
            .padding(.vertical, 26)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .background(VeronicaTheme.canvas)
        .groupBoxStyle(VeronicaGroupBoxStyle())
        .confirmationDialog("Run Veronica?", isPresented: $confirmRun) {
            Button("Run Veronica") { Task { await model.runAnnual() } }
            Button("Cancel", role: .cancel) { }
        } message: {
            if let scope = model.snapshot?.dateScope {
                Text("Veronica will scan your configured folders using this date scope: \(scope.summary). New review items or any verification anomaly will stop automation before unsafe work is committed.")
            } else {
                Text("Veronica will scan your configured folders and stop safely if anything needs review.")
            }
        }
    }

    private var header: some View {
        HStack(alignment: .center) {
            VStack(alignment: .leading, spacing: 4) {
                Text("Veronica")
                    .font(.system(size: 34, weight: .bold, design: .default))
                    .foregroundStyle(VeronicaTheme.ink)

                if let scope = model.snapshot?.dateScope {
                    Text("Date scope: \(scope.summary)")
                        .font(.callout)
                        .foregroundStyle(VeronicaTheme.secondaryInk)
                }
            }
            Spacer()

            if model.isLoading && !model.hasLiveSnapshot {
                HStack(spacing: 6) {
                    ProgressView()
                        .controlSize(.small)

                    Text(model.snapshot == nil ? "Loading…" : "Refreshing…")
                        .font(.caption)
                        .foregroundStyle(VeronicaTheme.secondaryInk)
                }
                .help(
                    model.snapshot == nil
                        ? "Loading Veronica's current state."
                        : "Verifying current folders, tools, and state."
                )
            }

            Button {
                confirmRun = true
            } label: {
                Label(
                    model.isRunningAnnual ? "Running…" : "Run Veronica",
                    systemImage: model.isRunningAnnual ? "hourglass" : "play.fill"
                )
            }
            .buttonStyle(.borderedProminent)
            .tint(VeronicaTheme.accent)
            .controlSize(.large)
            .disabled(
                !model.hasLiveSnapshot
                || model.isRunningAnnual
                || model.snapshot?.archiveAvailable != true
                || model.snapshot?.preflight.requiredToolsReady != true
            )
        }
    }

    private var coldStartSkeleton: some View {
        VStack(alignment: .leading, spacing: 22) {
            HStack(spacing: 14) {
                Circle()
                    .fill(VeronicaTheme.strongerFill)
                    .frame(width: 38, height: 38)

                VStack(alignment: .leading, spacing: 7) {
                    RoundedRectangle(cornerRadius: 3)
                        .fill(VeronicaTheme.strongerFill)
                        .frame(width: 170, height: 15)

                    RoundedRectangle(cornerRadius: 3)
                        .fill(VeronicaTheme.strongerFill)
                        .frame(width: 360, height: 11)
                }

                Spacer()
            }
            .padding(18)
            .background(
                VeronicaTheme.accentFill,
                in: RoundedRectangle(
                    cornerRadius: 14,
                    style: .continuous
                )
            )
            .overlay {
                RoundedRectangle(
                    cornerRadius: 14,
                    style: .continuous
                )
                .stroke(
                    VeronicaTheme.accent.opacity(0.10),
                    lineWidth: 1
                )
            }

            HStack(spacing: 12) {
                ForEach(0..<4, id: \.self) { _ in
                    ColdStartMetricCard()
                }
            }

            GroupBox("Latest maintenance plan") {
                VStack(alignment: .leading, spacing: 10) {
                    ForEach(0..<5, id: \.self) { index in
                        HStack(spacing: 28) {
                            RoundedRectangle(cornerRadius: 3)
                                .fill(VeronicaTheme.strongerFill)
                                .frame(
                                    width: index == 1 ? 88 : 110,
                                    height: 11
                                )

                            RoundedRectangle(cornerRadius: 3)
                                .fill(VeronicaTheme.strongerFill)
                                .frame(
                                    width: index == 1 ? 150 : 95,
                                    height: 11
                                )
                        }
                    }
                }
                .padding(.vertical, 4)
            }

            GroupBox("Recently changed") {
                VStack(spacing: 0) {
                    ForEach(0..<3, id: \.self) { index in
                        HStack(spacing: 12) {
                            RoundedRectangle(cornerRadius: 4)
                                .fill(VeronicaTheme.strongerFill)
                                .frame(width: 22, height: 18)

                            VStack(alignment: .leading, spacing: 6) {
                                RoundedRectangle(cornerRadius: 3)
                                    .fill(VeronicaTheme.strongerFill)
                                    .frame(width: 220, height: 11)

                                RoundedRectangle(cornerRadius: 3)
                                    .fill(VeronicaTheme.strongerFill)
                                    .frame(width: 150, height: 9)
                            }

                            Spacer()

                            RoundedRectangle(cornerRadius: 3)
                                .fill(VeronicaTheme.strongerFill)
                                .frame(width: 80, height: 10)
                        }
                        .padding(.vertical, 8)

                        if index < 2 {
                            Divider()
                        }
                    }
                }
            }
        }
        .accessibilityHidden(true)
    }

    @ViewBuilder
    private func planCard(_ s: UISnapshot) -> some View {
        GroupBox("Latest maintenance plan") {
            if let plan = s.latestPlan {
                Grid(alignment: .leading, horizontalSpacing: 28, verticalSpacing: 9) {
                    GridRow { Text("Run date").foregroundStyle(.secondary); Text(plan.runDate) }
                    GridRow {
                        Text("Date scope").foregroundStyle(.secondary)
                        Text(s.dateScope.summary)
                    }
                    GridRow { Text("Planned conversions").foregroundStyle(.secondary); Text(plan.executableCount.formatted()) }
                    GridRow {
                        Text("Still waiting").foregroundStyle(.secondary)
                        Text((plan.remainingExecutableCount ?? plan.executableCount).formatted())
                    }
                    GridRow { Text("Needs review").foregroundStyle(.secondary); Text(plan.unresolvedReviewCount.formatted()) }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.vertical, 4)
            } else {
                Text(s.databaseExists ? "No maintenance plan has been created yet." : "Ready for your first scan.").foregroundStyle(.secondary)
            }
        }
    }

    @ViewBuilder
    private func recentCard(_ s: UISnapshot) -> some View {
        GroupBox("Recently changed") {
            if s.recentChanges.isEmpty {
                Text("No committed changes yet.").foregroundStyle(.secondary)
            } else {
                VStack(spacing: 0) {
                    ForEach(s.recentChanges.prefix(8)) { change in
                        HStack(spacing: 12) {
                            Image(systemName: change.operation == "CONVERT_VIDEO" ? "film" : "photo")
                                .foregroundStyle(.secondary)
                                .frame(width: 22)
                            VStack(alignment: .leading, spacing: 3) {
                                Text(URL(fileURLWithPath: change.relpath).lastPathComponent).lineLimit(1)
                                Text("Saved \(ByteCountFormatter.string(fromByteCount: change.savingBytes, countStyle: .file)) • \(change.savingPercent, specifier: "%.1f")%")
                                    .font(.caption).foregroundStyle(.secondary)
                            }
                            Spacer()
                            Button("Show in Finder") { model.reveal(change.finalPath) }
                                .buttonStyle(.link)
                        }
                        .padding(.vertical, 8)
                        if change.id != s.recentChanges.prefix(8).last?.id { Divider() }
                    }
                }
            }
        }
    }
}

struct StatusBanner: View {
    let snapshot: UISnapshot
    let running: Bool
    let latestEvent: EngineEvent?

    private var title: String {
        if running { return "Maintenance is running" }
        if !snapshot.unresolvedReviews.isEmpty { return "Your attention is needed" }
        if let remaining = snapshot.latestPlan?.remainingExecutableCount, remaining > 0 { return "Work is waiting" }
        return "Folders are up to date"
    }

    private var detail: String {
        if running { return latestEvent?.title ?? "Veronica is scanning and verifying your configured folders." }
        if !snapshot.unresolvedReviews.isEmpty { return "\(snapshot.unresolvedReviews.count) item(s) need review before automatic maintenance can continue." }
        if let remaining = snapshot.latestPlan?.remainingExecutableCount, remaining > 0 { return "\(remaining) planned conversion(s) have not reached a terminal disposition yet." }
        return "No executable work or unresolved review decisions are waiting in the latest plan."
    }

    private var icon: String {
        if running { return "arrow.triangle.2.circlepath" }
        if !snapshot.unresolvedReviews.isEmpty { return "exclamationmark.triangle.fill" }
        if let remaining = snapshot.latestPlan?.remainingExecutableCount, remaining > 0 { return "clock.fill" }
        return "checkmark.circle.fill"
    }

    var body: some View {
        HStack(spacing: 14) {
            ZStack {
                Circle()
                    .fill(VeronicaTheme.accent.opacity(0.12))
                    .frame(width: 38, height: 38)

                Image(systemName: icon)
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundStyle(VeronicaTheme.accent)
            }

            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(.headline)
                    .foregroundStyle(VeronicaTheme.ink)

                Text(detail)
                    .font(.callout)
                    .foregroundStyle(VeronicaTheme.secondaryInk)
            }

            Spacer()
        }
        .padding(18)
        .background(
            VeronicaTheme.accentFill,
            in: RoundedRectangle(cornerRadius: 14, style: .continuous)
        )
        .overlay {
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .stroke(VeronicaTheme.accent.opacity(0.14), lineWidth: 1)
        }
    }
}

struct LiveProgressCard: View {
    let event: EngineEvent?
    let progress: Double?

    var body: some View {
        GroupBox("Current activity") {
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    ProgressView()
                        .controlSize(.small)
                    Text(event?.title ?? "Working…").font(.headline)
                    Spacer()
                    if let event, let index = event.index, let total = event.total {
                        Text("\(index) of \(total)").foregroundStyle(.secondary).monospacedDigit()
                    }
                }
                if let detail = event?.detail { Text(detail).font(.callout).foregroundStyle(.secondary).lineLimit(2) }
                if let progress { ProgressView(value: progress) }
            }
            .padding(.vertical, 4)
        }
    }
}

struct MetricCard: View {
    let title: String
    let value: String
    let detail: String
    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            RoundedRectangle(cornerRadius: 2)
                .fill(VeronicaTheme.accent)
                .frame(width: 28, height: 3)

            Text(title)
                .font(.caption)
                .foregroundStyle(VeronicaTheme.secondaryInk)

            Text(value)
                .font(.title2.bold())
                .foregroundStyle(VeronicaTheme.ink)
                .monospacedDigit()

            Text(detail)
                .font(.caption)
                .foregroundStyle(VeronicaTheme.secondaryInk)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(18)
        .background(
            VeronicaTheme.subtleFill,
            in: RoundedRectangle(cornerRadius: 14, style: .continuous)
        )
        .overlay {
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .stroke(VeronicaTheme.border, lineWidth: 1)
        }
    }
}


private struct ColdStartMetricCard: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            RoundedRectangle(cornerRadius: 2)
                .fill(VeronicaTheme.accent.opacity(0.35))
                .frame(width: 28, height: 3)

            RoundedRectangle(cornerRadius: 3)
                .fill(VeronicaTheme.strongerFill)
                .frame(width: 74, height: 10)

            RoundedRectangle(cornerRadius: 4)
                .fill(VeronicaTheme.strongerFill)
                .frame(width: 82, height: 22)

            RoundedRectangle(cornerRadius: 3)
                .fill(VeronicaTheme.strongerFill)
                .frame(width: 112, height: 9)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(18)
        .background(
            VeronicaTheme.subtleFill,
            in: RoundedRectangle(
                cornerRadius: 14,
                style: .continuous
            )
        )
        .overlay {
            RoundedRectangle(
                cornerRadius: 14,
                style: .continuous
            )
            .stroke(
                VeronicaTheme.border,
                lineWidth: 1
            )
        }
    }
}
