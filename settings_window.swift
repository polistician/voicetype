// settings_window.swift
//
// SwiftUI Settings window for VoiceType. JSON-over-stdio.
// Reads commands on stdin. Emits events on stdout.

import Cocoa
import SwiftUI

// MARK: - Protocol types

struct InMessage: Codable {
    let type: String
    var account: String?
    var present: Bool?
    var ok: Bool?
    var error: String?
    var key: String?
    var boolValue: Bool?
    var stringValue: String?
    var value: String?
}

struct OutEvent: Codable {
    let type: String
    var account: String?
    var value: String?
    var key: String?
    var boolValue: Bool?
    var stringValue: String?
}

func emit(_ event: OutEvent) {
    let enc = JSONEncoder()
    if let data = try? enc.encode(event), let line = String(data: data, encoding: .utf8) {
        FileHandle.standardOutput.write((line + "\n").data(using: .utf8)!)
    }
}

// MARK: - State

class SettingsState: ObservableObject {
    @Published var deeplKey: String = ""
    @Published var deeplPresent: Bool = false
    @Published var deeplStatus: String = ""  // "verifying", "verified", "error: ...", ""
    @Published var deeplError: String = ""
    @Published var revealKey: Bool = false
    @Published var autoPaste: Bool = true

    // Cleanup backend (unified replacement for AI cleanup + LLM correction).
    // Allowed string values: "off" | "integrator" | "groq" | "local".
    @Published var cleanupBackend: String = "off"
    @Published var integratorConnected: Bool = false
    @Published var integratorEmail: String = ""
    @Published var integratorBusy: Bool = false
    @Published var integratorError: String = ""

    // Local (MLX Qwen 3) download state — populated by cleanup_backend_status/progress.
    @Published var localModelReady: Bool = false
    @Published var localDownloadBusy: Bool = false
    @Published var localDownloadError: String = ""

    // Command Mode (⌥⇧C) + Tier-1 voice-edit phrases.
    @Published var commandModeEnabled: Bool = true
    @Published var voiceEditAutoDetect: Bool = true

    func handle(_ msg: InMessage) {
        switch msg.type {
        case "key_status":
            if msg.account == "deepl" {
                self.deeplPresent = msg.present ?? false
                if self.deeplStatus.isEmpty {
                    self.deeplStatus = self.deeplPresent ? "saved" : "not set"
                }
            }
        case "verify_result":
            if msg.account == "deepl" {
                if msg.ok == true {
                    self.deeplStatus = "verified"
                    self.deeplError = ""
                } else {
                    self.deeplStatus = "verify_failed"
                    self.deeplError = msg.error ?? "verification failed"
                }
            }
        case "setting_status":
            if msg.key == "auto_paste", let v = msg.boolValue {
                self.autoPaste = v
            }
            if msg.key == "cleanup_backend", let s = msg.stringValue {
                self.cleanupBackend = s
            }
            if msg.key == "command_mode_enabled", let v = msg.boolValue {
                self.commandModeEnabled = v
            }
            if msg.key == "voice_edit_auto_detect_enabled", let v = msg.boolValue {
                self.voiceEditAutoDetect = v
            }
        case "cleanup_backend_status":
            let v = msg.value ?? ""
            switch v {
            case "downloading":
                self.localDownloadBusy = true
                self.localDownloadError = ""
                self.localModelReady = false
            case "ready":
                self.localDownloadBusy = false
                self.localDownloadError = ""
                self.localModelReady = true
            case "error":
                self.localDownloadBusy = false
                self.localDownloadError = msg.error ?? "download failed"
            default:
                break
            }
        case "key_value":
            if msg.account == "deepl", let v = msg.value {
                self.deeplKey = v
                self.deeplPresent = !v.isEmpty
                if self.deeplStatus.isEmpty || self.deeplStatus == "not set" {
                    self.deeplStatus = self.deeplPresent ? "saved" : "not set"
                }
            }
        case "integrator_status":
            self.integratorConnected = msg.boolValue ?? false
            let v = msg.value ?? ""
            if v == "connecting" {
                self.integratorBusy = true
                self.integratorError = ""
            } else if v.hasPrefix("error:") {
                self.integratorBusy = false
                self.integratorError = String(v.dropFirst("error:".count)).trimmingCharacters(in: .whitespaces)
            } else {
                self.integratorBusy = false
                self.integratorError = ""
                self.integratorEmail = v
            }
        default:
            break
        }
    }
}

// MARK: - View

struct KeyRow: View {
    @ObservedObject var state: SettingsState
    let label: String
    let account: String

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(label)
                    .font(.system(size: 13, weight: .semibold))
                Spacer()
                statusView
            }
            HStack(spacing: 6) {
                Group {
                    if state.revealKey {
                        TextField("Paste key here", text: $state.deeplKey)
                    } else {
                        SecureField("Paste key here", text: $state.deeplKey)
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
            HStack {
                Button("Verify") {
                    state.deeplStatus = "verifying"
                    emit(OutEvent(type: "verify_key", account: account, value: state.deeplKey))
                }
                .disabled(state.deeplKey.isEmpty)
                Button("Save") {
                    emit(OutEvent(type: "set_key", account: account, value: state.deeplKey))
                    state.deeplStatus = "saved"
                    state.deeplPresent = true
                    state.deeplKey = ""  // clear field
                }
                .disabled(state.deeplKey.isEmpty || state.deeplStatus != "verified")
                .keyboardShortcut(.defaultAction)
                Spacer()
                Button("Remove") {
                    emit(OutEvent(type: "delete_key", account: account))
                    state.deeplPresent = false
                    state.deeplStatus = "not set"
                }
                .disabled(!state.deeplPresent)
            }
            HStack {
                Text("Get a free DeepL key \u{2192}")
                    .font(.system(size: 11))
                    .foregroundColor(Color(red: 0.302, green: 0.561, blue: 0.859))
                    .onTapGesture {
                        if let url = URL(string: "https://www.deepl.com/pro-api") {
                            NSWorkspace.shared.open(url)
                        }
                    }
                Spacer()
            }
        }
        .padding(14)
        .background(Color(NSColor.controlBackgroundColor))
        .cornerRadius(8)
    }

    @ViewBuilder
    var statusView: some View {
        switch state.deeplStatus {
        case "verifying":
            HStack(spacing: 4) {
                ProgressView().controlSize(.small)
                Text("verifying\u{2026}").font(.system(size: 11)).foregroundColor(.secondary)
            }
        case "verified":
            Text("\u{2713} verified").font(.system(size: 11)).foregroundColor(.green)
        case "saved":
            Text("\u{2713} saved").font(.system(size: 11)).foregroundColor(.secondary)
        case "verify_failed":
            Text("\u{00D7} \(state.deeplError)").font(.system(size: 11)).foregroundColor(.red)
        case "not set":
            Text("\u{00D7} not set").font(.system(size: 11)).foregroundColor(.secondary)
        default:
            Text(state.deeplPresent ? "\u{2713} saved" : "\u{00D7} not set")
                .font(.system(size: 11)).foregroundColor(.secondary)
        }
    }
}

struct SettingsView: View {
    @ObservedObject var state: SettingsState

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("VoiceType \u{2014} Settings")
                    .font(.system(size: 17, weight: .bold))
                Spacer()
            }
            Text("Keys")
                .font(.system(size: 11, weight: .semibold))
                .foregroundColor(.secondary)
                .textCase(.uppercase)
                .padding(.top, 4)
            KeyRow(state: state, label: "DeepL", account: "deepl")

            Text("Behavior")
                .font(.system(size: 11, weight: .semibold))
                .foregroundColor(.secondary)
                .textCase(.uppercase)
                .padding(.top, 12)
            HStack {
                Toggle("Auto-paste (synthesize \u{2318}V)", isOn: $state.autoPaste)
                    .onChange(of: state.autoPaste) { _, newValue in
                        emit(OutEvent(type: "set_setting", key: "auto_paste", boolValue: newValue))
                    }
                Spacer()
            }
            .padding(14)
            .background(Color(NSColor.controlBackgroundColor))
            .cornerRadius(8)

            Text("AI cleanup")
                .font(.system(size: 11, weight: .semibold))
                .foregroundColor(.secondary)
                .textCase(.uppercase)
                .padding(.top, 12)
            CleanupBackendRow(state: state)

            Text("Voice editing")
                .font(.system(size: 11, weight: .semibold))
                .foregroundColor(.secondary)
                .textCase(.uppercase)
                .padding(.top, 12)
            VoiceEditingRow(state: state)

            Spacer()
        }
        .padding(20)
        .frame(width: 480, height: 700)
        .background(Color(NSColor.windowBackgroundColor))
    }
}

struct CleanupBackendRow: View {
    @ObservedObject var state: SettingsState

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top) {
                Picker("Backend", selection: $state.cleanupBackend) {
                    Text("Off (raw transcript)").tag("off")
                    Text("Integrator \u{2014} ChatGPT (cloud)").tag("integrator")
                    Text("Integrator \u{2014} Groq (cloud, fast)").tag("groq")
                    Text("Local \u{2014} Qwen 3 0.6B (on-device)").tag("local")
                }
                .pickerStyle(.menu)
                .onChange(of: state.cleanupBackend) { _, newValue in
                    emit(OutEvent(type: "set_setting", key: "cleanup_backend", stringValue: newValue))
                }
                Spacer()
                statusBadge
            }
            Text("How VoiceType tightens raw Whisper output before pasting. Cloud paths send only the transcript text \u{2014} never audio. Local path is fully offline. Any backend falls back to raw text on failure.")
                .font(.system(size: 11))
                .foregroundColor(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            if state.cleanupBackend == "integrator" || state.cleanupBackend == "groq" {
                HStack(spacing: 8) {
                    if state.integratorConnected {
                        Button("Disconnect Integrator") {
                            emit(OutEvent(type: "integrator_disconnect"))
                        }
                        .buttonStyle(.bordered)
                        if !state.integratorEmail.isEmpty {
                            Text(state.integratorEmail)
                                .font(.system(size: 11))
                                .foregroundColor(.secondary)
                        }
                    } else {
                        Button(state.integratorBusy ? "Connecting\u{2026}" : "Connect Integrator") {
                            emit(OutEvent(type: "integrator_connect"))
                        }
                        .disabled(state.integratorBusy)
                        .buttonStyle(.borderedProminent)
                    }
                    Spacer()
                    Text("integrator.polistician.ai \u{2192}")
                        .font(.system(size: 11))
                        .foregroundColor(Color(red: 0.302, green: 0.561, blue: 0.859))
                        .onTapGesture {
                            if let url = URL(string: "https://integrator.polistician.ai") {
                                NSWorkspace.shared.open(url)
                            }
                        }
                }
                if state.cleanupBackend == "groq" && !state.integratorConnected {
                    Text("Groq routes through Integrator \u{2014} pair Integrator above, then paste your Groq API key at integrator.polistician.ai/console/connectors.html.")
                        .font(.system(size: 11))
                        .foregroundColor(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if !state.integratorError.isEmpty {
                    Text("\u{00D7} \(state.integratorError)")
                        .font(.system(size: 11))
                        .foregroundColor(.red)
                }
            } else if state.cleanupBackend == "local" {
                if state.localDownloadBusy {
                    HStack(spacing: 6) {
                        ProgressView().controlSize(.small)
                        Text("Downloading Qwen 3 0.6B (~400 MB)\u{2026}")
                            .font(.system(size: 11))
                            .foregroundColor(.secondary)
                    }
                } else if state.localModelReady {
                    Text("\u{2713} Model ready \u{2014} ~/.voicetype/models/cleanup/qwen3-0.6b-4bit/")
                        .font(.system(size: 11))
                        .foregroundColor(.green)
                } else {
                    Text("Model will download on first dictation.")
                        .font(.system(size: 11))
                        .foregroundColor(.secondary)
                }
                if !state.localDownloadError.isEmpty {
                    Text("\u{00D7} \(state.localDownloadError)")
                        .font(.system(size: 11))
                        .foregroundColor(.red)
                }
            }
        }
        .padding(14)
        .background(Color(NSColor.controlBackgroundColor))
        .cornerRadius(8)
    }

    @ViewBuilder
    var statusBadge: some View {
        if state.cleanupBackend == "off" {
            Text("off").font(.system(size: 11)).foregroundColor(.secondary)
        } else if (state.cleanupBackend == "integrator" || state.cleanupBackend == "groq") && state.integratorConnected {
            Text("\u{2713} ready").font(.system(size: 11)).foregroundColor(.green)
        } else if state.cleanupBackend == "local" && state.localModelReady {
            Text("\u{2713} ready").font(.system(size: 11)).foregroundColor(.green)
        } else if state.cleanupBackend == "local" && state.localDownloadBusy {
            Text("downloading\u{2026}").font(.system(size: 11)).foregroundColor(.secondary)
        } else {
            Text("\u{26A0} needs setup").font(.system(size: 11)).foregroundColor(.orange)
        }
    }
}

struct VoiceEditingRow: View {
    @ObservedObject var state: SettingsState

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Toggle("Command Mode (hold \u{2325}\u{21E7}C to dictate an edit)", isOn: $state.commandModeEnabled)
                    .onChange(of: state.commandModeEnabled) { _, newValue in
                        emit(OutEvent(type: "set_setting", key: "command_mode_enabled", boolValue: newValue))
                    }
                Spacer()
            }
            Text("Hold \u{2325}\u{21E7}C while speaking an instruction (e.g. \u{201C}make it more formal\u{201D}, \u{201C}turn this into bullets\u{201D}). The instruction is applied to the last paste via the configured cleanup backend.")
                .font(.system(size: 11))
                .foregroundColor(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            HStack {
                Toggle("Tier-1 voice phrases (\u{201C}scratch that\u{201D}, \u{201C}new line\u{201D}, \u{201C}new paragraph\u{201D}, \u{201C}undo that\u{201D})", isOn: $state.voiceEditAutoDetect)
                    .onChange(of: state.voiceEditAutoDetect) { _, newValue in
                        emit(OutEvent(type: "set_setting", key: "voice_edit_auto_detect_enabled", boolValue: newValue))
                    }
                Spacer()
            }
            Text("Auto-trigger on dictated commands without holding the Command Mode key. Disable if false-positives interfere with normal dictation.")
                .font(.system(size: 11))
                .foregroundColor(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(14)
        .background(Color(NSColor.controlBackgroundColor))
        .cornerRadius(8)
    }
}

// MARK: - Window controller

class SettingsWindowController: NSWindowController {
    let state: SettingsState

    init(state: SettingsState) {
        self.state = state
        let view = NSHostingView(rootView: SettingsView(state: state))
        let win = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 480, height: 700),
            styleMask: [.titled, .closable, .miniaturizable],
            backing: .buffered,
            defer: false
        )
        win.title = "VoiceType \u{2014} Settings"
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

// MARK: - App delegate (handle window close)

class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    var controller: SettingsWindowController!
    let state = SettingsState()

    func applicationDidFinishLaunching(_ notification: Notification) {
        installEditMenu()
        controller = SettingsWindowController(state: state)
        controller.window?.delegate = self
        // Ask Python for current key status
        emit(OutEvent(type: "refresh_status", account: "deepl"))
        startStdinReader()
    }

    private func installEditMenu() {
        let mainMenu = NSMenu()

        // App menu (required for menubar to render properly)
        let appMenuItem = NSMenuItem()
        mainMenu.addItem(appMenuItem)
        let appMenu = NSMenu()
        appMenu.addItem(NSMenuItem(title: "Quit",
                                   action: #selector(NSApplication.terminate(_:)),
                                   keyEquivalent: "q"))
        appMenuItem.submenu = appMenu

        // Edit menu — what we actually need
        let editMenuItem = NSMenuItem()
        mainMenu.addItem(editMenuItem)
        let editMenu = NSMenu(title: "Edit")
        editMenu.addItem(withTitle: "Undo",
                         action: Selector(("undo:")),
                         keyEquivalent: "z")
        editMenu.addItem(withTitle: "Redo",
                         action: Selector(("redo:")),
                         keyEquivalent: "Z")
        editMenu.addItem(NSMenuItem.separator())
        editMenu.addItem(withTitle: "Cut",
                         action: #selector(NSText.cut(_:)),
                         keyEquivalent: "x")
        editMenu.addItem(withTitle: "Copy",
                         action: #selector(NSText.copy(_:)),
                         keyEquivalent: "c")
        editMenu.addItem(withTitle: "Paste",
                         action: #selector(NSText.paste(_:)),
                         keyEquivalent: "v")
        editMenu.addItem(NSMenuItem.separator())
        editMenu.addItem(withTitle: "Select All",
                         action: #selector(NSText.selectAll(_:)),
                         keyEquivalent: "a")
        editMenuItem.submenu = editMenu

        NSApp.mainMenu = mainMenu
    }

    func windowWillClose(_ notification: Notification) {
        emit(OutEvent(type: "window_closed"))
    }

    func startStdinReader() {
        DispatchQueue.global(qos: .userInteractive).async {
            while let line = readLine() {
                guard !line.isEmpty else { continue }
                guard let data = line.data(using: .utf8),
                      let msg = try? JSONDecoder().decode(InMessage.self, from: data) else { continue }
                DispatchQueue.main.async {
                    self.handle(msg)
                }
            }
        }
    }

    func handle(_ msg: InMessage) {
        switch msg.type {
        case "open":
            controller.bringToFront()
            // Re-fetch saved keys + settings whenever window opens, not just on first launch.
            emit(OutEvent(type: "refresh_status", account: "deepl"))
        case "close":
            controller.window?.orderOut(nil)
        case "key_status", "verify_result", "setting_status", "key_value", "integrator_status", "cleanup_backend_status":
            state.handle(msg)
        default:
            break
        }
    }
}

// MARK: - Main

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
