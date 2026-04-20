// snippet_overlay.swift
// Snippet overlay + mini picker helper. Reads JSON events on stdin,
// emits JSON events on stdout. Window is a floating panel that never
// steals focus on paste (so Cmd+V targets the previously-frontmost app).

import Cocoa
import SwiftUI

// MARK: - Protocol types

struct OverlayMessage: Codable {
    let type: String
    var mode: String?
    var query: String?
    var draft_body: String?
    var items: [SnippetItem]?
    var candidates: [PickerCandidate]?
    var text: String?
    // Draft fields for OPEN_EDITOR (autogen-filled on save flow)
    var name: String?
    var description: String?
    var tags: String?
    var body: String?
}

struct SnippetItem: Codable, Identifiable {
    let id: Int
    let name: String
    let description: String
    let body: String
    let tags: String
    let used_count: Int
}

struct PickerCandidate: Codable, Identifiable {
    let id: Int
    let name: String
    let score: Double
}

// MARK: - Shared state

final class OverlayState: ObservableObject {
    @Published var snippets: [SnippetItem] = []
    @Published var visible: Bool = false
    @Published var mode: String = "list"
    @Published var query: String = ""
    @Published var draftBody: String = ""
    @Published var draftName: String = ""
    @Published var draftDesc: String = ""
    @Published var draftTags: String = ""
    @Published var editingSnippet: SnippetItem? = nil
    @Published var showingEditor: Bool = false
    @Published var pickerCandidates: [PickerCandidate] = []
}

// MARK: - stdin reader

func startStdinReader(state: OverlayState, panel: NSPanel) {
    Thread {
        while let line = readLine() {
            guard let data = line.data(using: .utf8),
                  let msg = try? JSONDecoder().decode(OverlayMessage.self, from: data) else {
                continue
            }
            DispatchQueue.main.async {
                switch msg.type {
                case "OPEN":
                    state.mode = msg.mode ?? "list"
                    state.query = msg.query ?? ""
                    state.draftBody = msg.draft_body ?? ""
                    panel.orderFrontRegardless()
                    panel.makeKey()
                case "HIDE":
                    panel.orderOut(nil)
                case "SNIPPETS":
                    state.snippets = msg.items ?? []
                case "SEARCH":
                    state.query = msg.query ?? ""
                case "PICKER":
                    state.pickerCandidates = msg.candidates ?? []
                    state.mode = "picker"
                    panel.orderFrontRegardless()
                    panel.makeKey()
                case "SHOW_HELP":
                    state.mode = "help"
                    panel.orderFrontRegardless()
                    panel.makeKey()
                case "OPEN_EDITOR":
                    // Autogen-prefilled editor for save-from-clipboard flow
                    state.draftName = msg.name ?? ""
                    state.draftDesc = msg.description ?? ""
                    state.draftTags = msg.tags ?? ""
                    state.draftBody = msg.body ?? ""
                    state.editingSnippet = nil
                    state.mode = "list"  // panel shows list underneath editor
                    panel.orderFrontRegardless()
                    panel.makeKey()
                    state.showingEditor = true
                default:
                    break
                }
            }
        }
    }.start()
}

// MARK: - Emit helpers

func emit(_ obj: [String: Any]) {
    guard let data = try? JSONSerialization.data(withJSONObject: obj) else { return }
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write("\n".data(using: .utf8)!)
}

// MARK: - Overlay UI

struct OverlayView: View {
    @EnvironmentObject var state: OverlayState
    @State private var selectedID: Int? = nil
    @State private var localQuery: String = ""

    var filtered: [SnippetItem] {
        if localQuery.isEmpty { return state.snippets }
        let q = localQuery.lowercased()
        return state.snippets.filter {
            $0.name.lowercased().contains(q)
            || $0.description.lowercased().contains(q)
            || $0.tags.lowercased().contains(q)
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            // Invisible keyboard shortcut handlers
            Button("") {
                state.editingSnippet = nil
                state.showingEditor = true
            }
            .keyboardShortcut("n", modifiers: .command)
            .frame(width: 0, height: 0)
            .opacity(0)

            Button("") {
                if let id = selectedID, let s = state.snippets.first(where: { $0.id == id }) {
                    state.editingSnippet = s
                    state.showingEditor = true
                }
            }
            .keyboardShortcut("e", modifiers: .command)
            .frame(width: 0, height: 0)
            .opacity(0)

            Button("") {
                if let id = selectedID {
                    emit(["type": "DELETE", "id": id])
                }
            }
            .keyboardShortcut(.delete, modifiers: .command)
            .frame(width: 0, height: 0)
            .opacity(0)

            searchField
            captureStrip
            Divider()
            snippetList
            footer
        }
        .padding(14)
        .frame(width: 540, height: 420)
        .background(VisualEffectView(material: .hudWindow, blending: .behindWindow))
        .sheet(isPresented: $state.showingEditor) {
            if let s = state.editingSnippet {
                EditorView(name: s.name, bodyText: s.body, description: s.description, tags: s.tags, editingID: s.id)
                    .environmentObject(state)
            } else {
                // New snippet — use autogen drafts if present (from OPEN_EDITOR)
                EditorView(
                    name: state.draftName,
                    bodyText: state.draftBody,
                    description: state.draftDesc,
                    tags: state.draftTags
                ).environmentObject(state)
            }
        }
        .onChange(of: state.query) { _, newValue in
            localQuery = newValue
        }
    }

    private var searchField: some View {
        TextField("Search snippets…", text: $localQuery, onCommit: {
            if let id = filtered.first?.id {
                emit(["type": "PASTE", "id": id])
                NSApp.windows.first?.orderOut(nil)
            }
        })
        .textFieldStyle(PlainTextFieldStyle())
        .font(.system(size: 14))
        .padding(10)
        .background(Color.black.opacity(0.25))
        .cornerRadius(6)
    }

    @ViewBuilder private var captureStrip: some View {
        if !state.draftBody.isEmpty {
            HStack {
                Image(systemName: "doc.on.clipboard")
                Text("Clipboard: ")
                    .foregroundColor(.secondary)
                Text(state.draftBody.prefix(60) + (state.draftBody.count > 60 ? "…" : ""))
                    .lineLimit(1)
                Spacer()
                Button("⌘S save") {
                    // Route through Python so autogen fills name/desc/tags
                    // and the editor opens for the user to review.
                    emit(["type": "SAVE_FROM_CLIPBOARD"])
                }
                .buttonStyle(LinkButtonStyle())
            }
            .font(.system(size: 11))
            .padding(8)
            .background(Color.blue.opacity(0.15))
            .cornerRadius(6)
        }
    }

    private var snippetList: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 2) {
                ForEach(filtered) { s in
                    SnippetRow(snippet: s, selected: s.id == selectedID)
                        .onTapGesture(count: 2) {
                            emit(["type": "PASTE", "id": s.id])
                            NSApp.windows.first?.orderOut(nil)
                        }
                        .onTapGesture { selectedID = s.id }
                }
            }
        }
    }

    private var footer: some View {
        HStack {
            Text("↑↓ navigate · ⏎ paste · ⌘N new · ⌘E edit · ⌘⌫ delete")
                .font(.system(size: 10))
                .foregroundColor(.secondary)
            Spacer()
            Text("\(filtered.count) of \(state.snippets.count)")
                .font(.system(size: 10))
                .foregroundColor(.secondary)
        }
    }
}

struct EditorView: View {
    @EnvironmentObject var state: OverlayState
    @State var name: String = ""
    @State var bodyText: String = ""
    @State var description: String = ""
    @State var tags: String = ""
    var editingID: Int? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            TextField("Name", text: $name).padding(8).background(Color.black.opacity(0.2)).cornerRadius(4)
            TextField("Description (helps voice match)", text: $description).padding(8).background(Color.black.opacity(0.2)).cornerRadius(4)
            TextField("Tags (comma separated)", text: $tags).padding(8).background(Color.black.opacity(0.2)).cornerRadius(4)
            TextEditor(text: $bodyText).frame(minHeight: 120).padding(6).background(Color.black.opacity(0.2)).cornerRadius(4)
            HStack {
                Button("Cancel") { state.showingEditor = false }
                Spacer()
                if let id = editingID {
                    Button("Delete", role: .destructive) {
                        emit(["type": "DELETE", "id": id])
                        state.showingEditor = false
                    }
                }
                Button("Save") {
                    if let id = editingID {
                        emit(["type": "UPDATE", "id": id, "name": name, "body": bodyText, "description": description, "tags": tags])
                    } else {
                        emit(["type": "CREATE", "name": name, "body": bodyText, "description": description, "tags": tags])
                    }
                    state.showingEditor = false
                }
                .keyboardShortcut(.defaultAction)
            }
        }
        .padding(14)
        .frame(width: 500, height: 360)
    }
}

struct SnippetRow: View {
    let snippet: SnippetItem
    let selected: Bool

    var body: some View {
        HStack {
            Text(snippet.name).fontWeight(.medium)
            Text(snippet.body.prefix(50) + (snippet.body.count > 50 ? "…" : ""))
                .foregroundColor(.secondary)
                .lineLimit(1)
                .font(.system(size: 11))
            Spacer()
            Text("\(snippet.used_count)×")
                .foregroundColor(.secondary)
                .font(.system(size: 10))
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(selected ? Color.accentColor.opacity(0.3) : Color.clear)
        .cornerRadius(4)
    }
}

struct PickerView: View {
    @EnvironmentObject var state: OverlayState

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("Did you mean:").font(.system(size: 11)).foregroundColor(.secondary)
            ForEach(Array(state.pickerCandidates.prefix(3).enumerated()), id: \.element.id) { idx, c in
                HStack {
                    Text("\(idx + 1).").monospacedDigit().frame(width: 16, alignment: .leading)
                    Text(c.name).fontWeight(.medium)
                    Spacer()
                    Text(String(format: "%.2f", c.score))
                        .foregroundColor(.secondary)
                        .font(.system(size: 10))
                }
                .padding(.vertical, 2)
            }
            Text("Press 1/2/3 · Esc to cancel").font(.system(size: 10)).foregroundColor(.secondary).padding(.top, 4)
        }
        .padding(12)
        .frame(width: 340)
        .background(VisualEffectView(material: .hudWindow, blending: .behindWindow))
    }
}

struct HelpView: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("VoxType Help")
                .font(.system(size: 16, weight: .semibold))

            Group {
                Text("Quick actions").font(.system(size: 11, weight: .semibold)).foregroundColor(.secondary)
                VStack(alignment: .leading, spacing: 4) {
                    helpRow("Option+C (hold)", "dictate — transcribe and paste")
                    helpRow("Option+T", "translate clipboard to selected language")
                    helpRow("Option+Shift+S", "open snippet manager")
                }

                Text("Voice commands (hold Option+C and say…)").font(.system(size: 11, weight: .semibold)).foregroundColor(.secondary).padding(.top, 4)
                VStack(alignment: .leading, spacing: 4) {
                    helpRow("\"snippet <description>\"", "paste snippet matching the description")
                    helpRow("\"open snippet overview\"", "open the manager")
                    helpRow("\"save snippet from clipboard\"", "create snippet from clipboard")
                    helpRow("\"show help\" / \"open help\"", "show this screen")
                }

                Text("Inside the snippet manager").font(.system(size: 11, weight: .semibold)).foregroundColor(.secondary).padding(.top, 4)
                VStack(alignment: .leading, spacing: 4) {
                    helpRow("↑ ↓ + ⏎", "navigate and paste")
                    helpRow("⌘N / ⌘E / ⌘⌫", "new / edit / delete snippet")
                    helpRow("Option+C (hold)", "dictate a search query")
                    helpRow("?", "show this help")
                    helpRow("Esc", "close")
                }
            }

            Divider().padding(.vertical, 2)

            Text("What this does").font(.system(size: 11, weight: .semibold)).foregroundColor(.secondary)
            Text("VoxType is a voice + keyboard input system. Dictate naturally, or issue voice commands like \"snippet deploy v3\" to paste by meaning — no need to remember exact names. The manager (⌥⇧S) lets you create, edit, and browse snippets; inside it, keyboard is precise and voice is semantic. Matches with high confidence paste directly; medium confidence shows a 3-option picker; low confidence opens the manager with your query pre-filled.")
                .font(.system(size: 11))
                .foregroundColor(.primary.opacity(0.85))
                .fixedSize(horizontal: false, vertical: true)

            Text("Esc to close").font(.system(size: 10)).foregroundColor(.secondary).padding(.top, 4)
        }
        .padding(16)
        .frame(width: 500)
        .background(VisualEffectView(material: .hudWindow, blending: .behindWindow))
    }

    private func helpRow(_ key: String, _ desc: String) -> some View {
        HStack(alignment: .firstTextBaseline) {
            Text(key)
                .font(.system(size: 11, design: .monospaced))
                .foregroundColor(.primary)
                .frame(width: 170, alignment: .leading)
            Text(desc)
                .font(.system(size: 11))
                .foregroundColor(.secondary)
        }
    }
}

struct VisualEffectView: NSViewRepresentable {
    let material: NSVisualEffectView.Material
    let blending: NSVisualEffectView.BlendingMode
    func makeNSView(context: Context) -> NSVisualEffectView {
        let v = NSVisualEffectView()
        v.material = material
        v.blendingMode = blending
        v.state = .active
        return v
    }
    func updateNSView(_ nsView: NSVisualEffectView, context: Context) {}
}

// MARK: - Root view (mode switcher)

struct RootView: View {
    @EnvironmentObject var state: OverlayState
    var body: some View {
        Group {
            if state.mode == "picker" {
                PickerView()
            } else if state.mode == "help" {
                HelpView()
            } else {
                OverlayView()
            }
        }
    }
}

// MARK: - App delegate

class AppDelegate: NSObject, NSApplicationDelegate {
    var panel: NSPanel!
    let state = OverlayState()

    func applicationDidFinishLaunching(_ notification: Notification) {
        let rect = NSRect(x: 0, y: 0, width: 540, height: 420)
        panel = NSPanel(
            contentRect: rect,
            styleMask: [.titled, .fullSizeContentView, .nonactivatingPanel, .hudWindow],
            backing: .buffered,
            defer: false
        )
        panel.level = .floating
        panel.isMovableByWindowBackground = true
        panel.titleVisibility = .hidden
        panel.titlebarAppearsTransparent = true
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.center()
        panel.hidesOnDeactivate = false
        panel.orderOut(nil)

        let content = NSHostingView(rootView: RootView().environmentObject(state))
        panel.contentView = content

        // Key handler: 1/2/3 in picker mode, Esc in any mode
        NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            guard let self = self else { return event }
            if self.state.mode == "picker" {
                // Number keys to select
                switch event.keyCode {
                case 18, 83: // 1 (top-row and numpad)
                    if let c = self.state.pickerCandidates.first {
                        emit(["type": "PASTE", "id": c.id])
                    }
                    self.panel.orderOut(nil)
                    self.state.mode = "list"  // reset for next open
                    return nil
                case 19, 84: // 2
                    if let c = self.state.pickerCandidates.dropFirst().first {
                        emit(["type": "PASTE", "id": c.id])
                    }
                    self.panel.orderOut(nil)
                    self.state.mode = "list"
                    return nil
                case 20, 85: // 3
                    if let c = self.state.pickerCandidates.dropFirst(2).first {
                        emit(["type": "PASTE", "id": c.id])
                    }
                    self.panel.orderOut(nil)
                    self.state.mode = "list"
                    return nil
                default: break
                }
            }
            // "?" key (shift + /) — show help from any mode
            if event.charactersIgnoringModifiers == "?" {
                self.state.mode = "help"
                self.panel.orderFrontRegardless()
                return nil
            }
            if event.keyCode == 53 { // Esc
                self.panel.orderOut(nil)
                self.state.mode = "list"
                emit(["type": "DISMISSED"])
                return nil
            }
            return event
        }

        startStdinReader(state: state, panel: panel)

        fputs("READY\n", stdout)
        fflush(stdout)
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let delegate = AppDelegate()
app.delegate = delegate
app.run()
