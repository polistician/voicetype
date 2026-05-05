// onboarding.swift
//
// 4-screen first-launch onboarding for VoiceType. JSON-over-stdio.
// Reads commands on stdin. Emits events on stdout.
//
// Screens:
//   1. Welcome         — keycap, headline, Continue
//   2. Permissions     — mic + accessibility status + deeplinks
//   3. Tutorial        — live dictation into NSTextField
//   4. Optional key    — DeepL API key (SecureField + Verify + Save + Skip)

import Cocoa
import SwiftUI
import AVFoundation

// MARK: - Protocol types

struct OBInMessage: Codable {
    let type: String
    var mic: Bool?
    var accessibility: Bool?
    var text: String?
    var ok: Bool?
    var error: String?
}

struct OBOutEvent: Codable {
    let type: String
    var pane: String?
    var account: String?
    var value: String?
}

func obEmit(_ event: OBOutEvent) {
    let enc = JSONEncoder()
    if let data = try? enc.encode(event), let line = String(data: data, encoding: .utf8) {
        FileHandle.standardOutput.write((line + "\n").data(using: .utf8)!)
    }
}

// MARK: - State

class OnboardingState: ObservableObject {
    @Published var currentScreen: Int = 1  // 1-4

    // Screen 2 – permissions
    @Published var micOK: Bool = false
    @Published var accessOK: Bool = false

    // Screen 3 – tutorial
    @Published var tutorialText: String = ""
    @Published var tutorialDone: Bool = false

    // Screen 4 – key
    @Published var keyValue: String = ""
    @Published var revealKey: Bool = false
    @Published var keyStatus: String = ""  // "", "verifying", "verified", "error"
    @Published var keyError: String = ""

    // Permission check via Swift APIs (no Python round-trip needed)
    func refreshPermissions() {
        let micStatus = AVCaptureDevice.authorizationStatus(for: .audio)
        micOK = (micStatus == .authorized)
        accessOK = AXIsProcessTrusted()
    }

    func handle(_ msg: OBInMessage) {
        switch msg.type {
        case "open":
            // handled at AppDelegate level — bringToFront
            break
        case "perm_status":
            if let m = msg.mic { micOK = m }
            if let a = msg.accessibility { accessOK = a }
        case "tutorial_paste_landed":
            if let t = msg.text, !t.isEmpty {
                tutorialText = t
                tutorialDone = true
            }
        case "key_verify_result":
            if msg.ok == true {
                keyStatus = "verified"
                keyError = ""
            } else {
                keyStatus = "error"
                keyError = msg.error ?? "verification failed"
            }
        default:
            break
        }
    }
}

// MARK: - Progress dots header

struct ProgressDotsView: View {
    let currentScreen: Int
    let total: Int = 4

    var body: some View {
        HStack(spacing: 6) {
            ForEach(1...total, id: \.self) { i in
                Circle()
                    .fill(i == currentScreen ? Color.accentColor : Color.secondary.opacity(0.35))
                    .frame(width: 7, height: 7)
                    .animation(.easeInOut(duration: 0.2), value: currentScreen)
            }
        }
    }
}

// MARK: - Screen 1: Welcome

struct WelcomeView: View {
    var onContinue: () -> Void

    var body: some View {
        VStack(spacing: 28) {
            Spacer()
            Text("⌥C")
                .font(.system(size: 72, weight: .light, design: .rounded))
                .foregroundColor(.accentColor)
            VStack(spacing: 10) {
                Text("Welcome to VoiceType")
                    .font(.system(size: 26, weight: .bold))
                Text("hold ⌥ C, speak, the text appears.")
                    .font(.system(size: 15))
                    .foregroundColor(.secondary)
                    .multilineTextAlignment(.center)
            }
            Spacer()
            Button(action: onContinue) {
                Text("Continue")
                    .frame(minWidth: 120)
            }
            .keyboardShortcut(.defaultAction)
            .controlSize(.large)
            .buttonStyle(.borderedProminent)
        }
        .padding(.horizontal, 48)
        .padding(.vertical, 32)
    }
}

// MARK: - Screen 2: Permissions

struct PermissionsView: View {
    @ObservedObject var state: OnboardingState
    var onBack: () -> Void
    var onContinue: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            Text("Permissions")
                .font(.system(size: 22, weight: .bold))
            Text("VoiceType needs two permissions to work.")
                .font(.system(size: 14))
                .foregroundColor(.secondary)
            VStack(spacing: 10) {
                PermRowView(
                    label: "Microphone",
                    detail: "To hear your voice",
                    ok: state.micOK,
                    settingsAction: {
                        obEmit(OBOutEvent(type: "open_pref_pane", pane: "microphone"))
                    }
                )
                PermRowView(
                    label: "Accessibility",
                    detail: "To paste text into apps",
                    ok: state.accessOK,
                    settingsAction: {
                        obEmit(OBOutEvent(type: "open_pref_pane", pane: "accessibility"))
                    }
                )
            }
            Text("Click \"Open System Settings\", grant the permission, then return here. The status updates automatically.")
                .font(.system(size: 12))
                .foregroundColor(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            Spacer()
            HStack {
                Button("Back", action: onBack).buttonStyle(.bordered)
                Spacer()
                Button(action: onContinue) {
                    Text("Continue")
                        .frame(minWidth: 100)
                }
                .keyboardShortcut(.defaultAction)
                .buttonStyle(.borderedProminent)
                .disabled(!state.micOK || !state.accessOK)
            }
        }
        .padding(.horizontal, 48)
        .padding(.vertical, 32)
        .onAppear { state.refreshPermissions() }
    }
}

struct PermRowView: View {
    let label: String
    let detail: String
    let ok: Bool
    var settingsAction: () -> Void

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: ok ? "checkmark.circle.fill" : "xmark.circle.fill")
                .foregroundColor(ok ? .green : .secondary)
                .font(.system(size: 20))
            VStack(alignment: .leading, spacing: 2) {
                Text(label).font(.system(size: 13, weight: .semibold))
                Text(detail).font(.system(size: 11)).foregroundColor(.secondary)
            }
            Spacer()
            if !ok {
                Button("Open System Settings") { settingsAction() }
                    .buttonStyle(.bordered)
                    .controlSize(.small)
            } else {
                Text("Granted").font(.system(size: 11)).foregroundColor(.green)
            }
        }
        .padding(12)
        .background(Color(NSColor.controlBackgroundColor))
        .cornerRadius(8)
    }
}

// MARK: - Screen 3: Tutorial (live NSTextField wrapper)

struct TutorialView: View {
    @ObservedObject var state: OnboardingState
    var onBack: () -> Void
    var onContinue: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            Text("Try it out")
                .font(.system(size: 22, weight: .bold))
            if !state.tutorialDone {
                Text("Hold ⌥ C and say “hello from VoiceType”.\nWatch the text appear below.")
                    .font(.system(size: 14))
                    .foregroundColor(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            } else {
                HStack(spacing: 6) {
                    Image(systemName: "checkmark.circle.fill").foregroundColor(.green)
                    Text("You got it — it works!")
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundColor(.green)
                }
            }
            TutorialTextField(text: $state.tutorialText, done: $state.tutorialDone)
                .frame(height: 90)
            if state.tutorialDone {
                Text("“\(state.tutorialText)”")
                    .font(.system(size: 12, design: .monospaced))
                    .foregroundColor(.secondary)
                    .lineLimit(3)
                    .truncationMode(.tail)
            }
            Spacer()
            HStack {
                Button("Back", action: onBack).buttonStyle(.bordered)
                Spacer()
                if state.tutorialDone {
                    Button(action: onContinue) {
                        Text("You’re set →")
                            .frame(minWidth: 120)
                    }
                    .keyboardShortcut(.defaultAction)
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
                } else {
                    Button("Skip for now", action: onContinue)
                        .buttonStyle(.bordered)
                }
            }
        }
        .padding(.horizontal, 48)
        .padding(.vertical, 32)
        .onAppear {
            obEmit(OBOutEvent(type: "start_tutorial"))
        }
    }
}

// NSTextField wrapper that fires on any text change, including programmatic paste
struct TutorialTextField: NSViewRepresentable {
    @Binding var text: String
    @Binding var done: Bool

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    func makeNSView(context: Context) -> NSScrollView {
        let tv = NSTextView()
        tv.isEditable = true
        tv.isSelectable = true
        tv.font = NSFont.monospacedSystemFont(ofSize: 13, weight: .regular)
        tv.string = ""
        tv.textColor = NSColor.labelColor
        tv.backgroundColor = NSColor.textBackgroundColor
        tv.drawsBackground = true
        tv.delegate = context.coordinator

        // Also observe NSText.didChangeNotification for programmatic changes
        NotificationCenter.default.addObserver(
            context.coordinator,
            selector: #selector(Coordinator.textDidChange(_:)),
            name: NSText.didChangeNotification,
            object: tv
        )

        let scroll = NSScrollView()
        scroll.documentView = tv
        scroll.hasVerticalScroller = true
        scroll.autohidesScrollers = true
        scroll.borderType = .bezelBorder
        scroll.wantsLayer = true
        scroll.layer?.cornerRadius = 6
        return scroll
    }

    func updateNSView(_ scrollView: NSScrollView, context: Context) {
        // Only push updates from state if the field is currently empty
        if let tv = scrollView.documentView as? NSTextView, tv.string.isEmpty && !text.isEmpty {
            tv.string = text
        }
    }

    class Coordinator: NSObject, NSTextViewDelegate {
        var parent: TutorialTextField

        init(_ parent: TutorialTextField) {
            self.parent = parent
        }

        @objc func textDidChange(_ notification: Notification) {
            guard let tv = notification.object as? NSTextView else { return }
            let s = tv.string
            DispatchQueue.main.async {
                self.parent.text = s
                if s.count > 3 && !self.parent.done {
                    self.parent.done = true
                }
            }
        }
    }
}

// MARK: - Screen 4: Optional API Key

struct OptionalKeyView: View {
    @ObservedObject var state: OnboardingState
    var onBack: () -> Void
    var onDone: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("Optional: DeepL Translation")
                .font(.system(size: 22, weight: .bold))
            Text("Add a free DeepL API key to translate while you dictate. You can skip this and add it later in Settings.")
                .font(.system(size: 14))
                .foregroundColor(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Text("DeepL API Key")
                        .font(.system(size: 13, weight: .semibold))
                    Spacer()
                    keyStatusView
                }
                HStack(spacing: 6) {
                    Group {
                        if state.revealKey {
                            TextField("Paste key here", text: $state.keyValue)
                        } else {
                            SecureField("Paste key here", text: $state.keyValue)
                        }
                    }
                    .textFieldStyle(.roundedBorder)
                    .font(.system(.body, design: .monospaced))
                    Button(state.revealKey ? "Hide" : "Reveal") {
                        state.revealKey.toggle()
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.small)
                }
                HStack(spacing: 8) {
                    Button("Verify") {
                        state.keyStatus = "verifying"
                        obEmit(OBOutEvent(type: "verify_key", account: "deepl", value: state.keyValue))
                    }
                    .disabled(state.keyValue.isEmpty || state.keyStatus == "verifying")
                    Button("Save") {
                        obEmit(OBOutEvent(type: "save_key", account: "deepl", value: state.keyValue))
                        state.keyStatus = "saved"
                    }
                    .disabled(state.keyValue.isEmpty || state.keyStatus != "verified")
                    .keyboardShortcut(.defaultAction)
                }
                if state.keyStatus == "error" && !state.keyError.isEmpty {
                    Text("× \(state.keyError)")
                        .font(.system(size: 11))
                        .foregroundColor(.red)
                }
                Text("Get a free DeepL key →")
                    .font(.system(size: 11))
                    .foregroundColor(Color(red: 0.302, green: 0.561, blue: 0.859))
                    .onTapGesture {
                        if let url = URL(string: "https://www.deepl.com/pro-api") {
                            NSWorkspace.shared.open(url)
                        }
                    }
            }
            .padding(14)
            .background(Color(NSColor.controlBackgroundColor))
            .cornerRadius(8)
            Spacer()
            HStack {
                Button("Back", action: onBack).buttonStyle(.bordered)
                Spacer()
                Button("Skip") {
                    obEmit(OBOutEvent(type: "skip_key"))
                    onDone()
                }
                .buttonStyle(.bordered)
                Button(action: onDone) {
                    Text("Done")
                        .frame(minWidth: 80)
                }
                .buttonStyle(.borderedProminent)
                .disabled(state.keyStatus != "saved" && state.keyStatus != "verified")
            }
        }
        .padding(.horizontal, 48)
        .padding(.vertical, 32)
    }

    @ViewBuilder
    var keyStatusView: some View {
        switch state.keyStatus {
        case "verifying":
            HStack(spacing: 4) {
                ProgressView().controlSize(.small)
                Text("verifying…").font(.system(size: 11)).foregroundColor(.secondary)
            }
        case "verified":
            Text("✓ verified").font(.system(size: 11)).foregroundColor(.green)
        case "saved":
            Text("✓ saved").font(.system(size: 11)).foregroundColor(.secondary)
        case "error":
            Text("× failed").font(.system(size: 11)).foregroundColor(.red)
        default:
            EmptyView()
        }
    }
}

// MARK: - Root onboarding view

struct OnboardingView: View {
    @ObservedObject var state: OnboardingState
    var onComplete: () -> Void

    var body: some View {
        VStack(spacing: 0) {
            // Header: progress dots
            HStack {
                Spacer()
                ProgressDotsView(currentScreen: state.currentScreen)
                Spacer()
            }
            .padding(.top, 20)
            .padding(.bottom, 4)

            Divider()

            // Content
            Group {
                switch state.currentScreen {
                case 1:
                    WelcomeView(onContinue: { advance() })
                case 2:
                    PermissionsView(
                        state: state,
                        onBack: { retreat() },
                        onContinue: { advance() }
                    )
                case 3:
                    TutorialView(
                        state: state,
                        onBack: { retreat() },
                        onContinue: { advance() }
                    )
                case 4:
                    OptionalKeyView(
                        state: state,
                        onBack: { retreat() },
                        onDone: { finishOnboarding() }
                    )
                default:
                    EmptyView()
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .frame(width: 600, height: 440)
        .background(Color(NSColor.windowBackgroundColor))
    }

    private func advance() {
        withAnimation {
            if state.currentScreen < 4 {
                state.currentScreen += 1
            } else {
                finishOnboarding()
            }
        }
    }

    private func retreat() {
        withAnimation {
            if state.currentScreen > 1 {
                state.currentScreen -= 1
            }
        }
    }

    private func finishOnboarding() {
        obEmit(OBOutEvent(type: "onboarding_complete"))
    }
}

// MARK: - Window controller

class OnboardingWindowController: NSWindowController {
    let state: OnboardingState

    init(state: OnboardingState, onComplete: @escaping () -> Void) {
        self.state = state
        let view = NSHostingView(rootView: OnboardingView(state: state, onComplete: onComplete))
        let win = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 600, height: 440),
            styleMask: [.titled, .closable, .miniaturizable],
            backing: .buffered,
            defer: false
        )
        win.title = "Welcome to VoiceType"
        win.contentView = view
        win.center()
        win.isReleasedWhenClosed = false
        super.init(window: win)
    }

    required init?(coder: NSCoder) { fatalError() }

    func bringToFront() {
        NSApp.activate(ignoringOtherApps: true)
        showWindow(nil)
        window?.makeKeyAndOrderFront(nil)
    }
}

// MARK: - Permission polling timer

class PermPoller {
    private var timer: Timer?
    let state: OnboardingState

    init(state: OnboardingState) {
        self.state = state
    }

    func start() {
        timer = Timer.scheduledTimer(withTimeInterval: 2.0, repeats: true) { [weak self] _ in
            self?.state.refreshPermissions()
        }
        RunLoop.main.add(timer!, forMode: .common)
    }

    func stop() {
        timer?.invalidate()
        timer = nil
    }
}

// MARK: - App delegate

class OBAppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    var controller: OnboardingWindowController!
    let state = OnboardingState()
    var poller: PermPoller!

    func applicationDidFinishLaunching(_ notification: Notification) {
        controller = OnboardingWindowController(state: state) {
            // onComplete callback — just emit; Python writes the flag
        }
        controller.window?.delegate = self
        poller = PermPoller(state: state)
        poller.start()
        startStdinReader()
        controller.bringToFront()
    }

    func windowWillClose(_ notification: Notification) {
        // If user closes window via red X without completing, still emit completion
        // so Python writes the flag and stops showing onboarding on future restarts.
        obEmit(OBOutEvent(type: "onboarding_complete"))
        NSApp.terminate(nil)
    }

    func startStdinReader() {
        DispatchQueue.global(qos: .userInteractive).async {
            while let line = readLine() {
                guard !line.isEmpty else { continue }
                guard let data = line.data(using: .utf8),
                      let msg = try? JSONDecoder().decode(OBInMessage.self, from: data) else { continue }
                DispatchQueue.main.async {
                    self.handle(msg)
                }
            }
        }
    }

    func handle(_ msg: OBInMessage) {
        switch msg.type {
        case "open":
            controller.bringToFront()
        case "close":
            controller.window?.orderOut(nil)
        default:
            state.handle(msg)
        }
    }
}

// MARK: - Main

let app = NSApplication.shared
let delegate = OBAppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
