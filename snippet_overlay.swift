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
    @Published var editingSnippet: SnippetItem? = nil
    @Published var showingEditor: Bool = false
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
                EditorView().environmentObject(state)
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
                    emit([
                        "type": "CREATE",
                        "name": "From clipboard",
                        "body": state.draftBody,
                        "description": "",
                        "tags": "",
                    ])
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

        let content = NSHostingView(rootView: OverlayView().environmentObject(state))
        panel.contentView = content

        // Escape key dismiss
        NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            if event.keyCode == 53 { // Esc
                self?.panel.orderOut(nil)
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
