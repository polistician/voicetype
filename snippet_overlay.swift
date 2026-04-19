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

// MARK: - Placeholder view (replaced in Task 11)

struct PlaceholderView: View {
    @EnvironmentObject var state: OverlayState
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("VoxType snippets — mode: \(state.mode)")
                .font(.headline)
            Text("\(state.snippets.count) snippets loaded")
                .foregroundColor(.secondary)
            Divider()
            ForEach(state.snippets.prefix(5)) { s in
                HStack {
                    Text(s.name).fontWeight(.medium)
                    Spacer()
                    Text("\(s.used_count)×").foregroundColor(.secondary)
                }
            }
        }
        .padding(16)
        .frame(minWidth: 480, minHeight: 200)
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

        let content = NSHostingView(rootView: PlaceholderView().environmentObject(state))
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
