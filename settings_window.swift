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
}

struct OutEvent: Codable {
    let type: String
    var account: String?
    var value: String?
    var key: String?
    var boolValue: Bool?
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

            Spacer()
        }
        .padding(20)
        .frame(width: 480, height: 430)
        .background(Color(NSColor.windowBackgroundColor))
    }
}

// MARK: - Window controller

class SettingsWindowController: NSWindowController {
    let state: SettingsState

    init(state: SettingsState) {
        self.state = state
        let view = NSHostingView(rootView: SettingsView(state: state))
        let win = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 480, height: 430),
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
        case "close":
            controller.window?.orderOut(nil)
        case "key_status", "verify_result", "setting_status":
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
