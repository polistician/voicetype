// vocabulary_window.swift — VoiceType Vocabulary panel
//
// Brand-congruent visual treatment per polistician's design bar:
//   - Restrained dark background, single amber accent
//   - SF Mono for the words themselves (a list of strings; mono is native)
//   - Generous spacing; no row borders, hover lightens
//   - One panel, no tabs, no Settings chrome
//
// Wire protocol (line-oriented JSON over stdin/stdout, same as the rest of
// the Swift helpers — see overlay_bridge.py, settings_window.swift):
//
//   Python → Swift
//     {"type":"open"}
//     {"type":"close"}
//     {"type":"vocab_state",
//      "words":[{"canonical":"X","alias":null|"y","usage_count":N,
//                "status":"new"|"seen"|"active"|"archived"}, ...],
//      "suggestions":[{"raw":"polystition","suggested":"Polistician","count":4}, ...]}
//
//   Swift → Python
//     {"type":"refresh"}                                  // ask for fresh state
//     {"type":"add","canonical":"...","alias":""}
//     {"type":"add_many","words":["..."]}
//     {"type":"paste_dump","text":"..."}                  // python extracts proper nouns
//     {"type":"update","old":"...","new":"...","alias":""}
//     {"type":"remove","canonical":"..."}
//     {"type":"dismiss_suggestion","raw":"..."}
//     {"type":"accept_suggestion","raw":"...","canonical":"..."}
//     {"type":"window_closed"}

import Cocoa
import SwiftUI


// MARK: - Wire model

struct VocabWord: Codable, Identifiable, Equatable {
    var id: String { canonical }
    var canonical: String
    var alias: String?
    var usage_count: Int
    var status: String
}

struct VocabSuggestion: Codable, Identifiable, Equatable {
    var id: String { raw }
    var raw: String
    var suggested: String
    var count: Int
}

struct VocabState: Codable {
    var words: [VocabWord]
    var suggestions: [VocabSuggestion]
}


// MARK: - Brand palette

enum Palette {
    // Deep restrained black, slight warmth so it doesn't read as cold/grey.
    static let bg          = Color(red: 0.043, green: 0.043, blue: 0.047)
    static let panel       = Color(red: 0.078, green: 0.078, blue: 0.086)
    static let rowHover    = Color(red: 0.118, green: 0.118, blue: 0.129)
    static let separator   = Color(red: 0.196, green: 0.196, blue: 0.216)
    // Warm off-white that matches the marketing site copy color.
    static let text        = Color(red: 0.945, green: 0.910, blue: 0.847)
    static let textMuted   = Color(red: 0.580, green: 0.553, blue: 0.510)
    static let textDim     = Color(red: 0.380, green: 0.365, blue: 0.337)
    // The single accent — matches the ⌥ C keycap on the marketing site.
    static let amber       = Color(red: 0.961, green: 0.651, blue: 0.137)
    static let amberSoft   = Color(red: 0.961, green: 0.651, blue: 0.137, opacity: 0.18)
    static let danger      = Color(red: 0.870, green: 0.290, blue: 0.290)
}


// MARK: - State

@MainActor
final class VocabModel: ObservableObject {
    @Published var words: [VocabWord] = []
    @Published var suggestions: [VocabSuggestion] = []
    @Published var search: String = ""

    /// Apply a fresh snapshot from Python. Animates additions and removals
    /// so the UI doesn't snap discontinuously.
    func apply(_ state: VocabState) {
        withAnimation(.spring(response: 0.4, dampingFraction: 0.85)) {
            self.words = state.words
            self.suggestions = state.suggestions
        }
    }

    var filtered: [VocabWord] {
        if search.isEmpty { return words }
        let needle = search.lowercased()
        return words.filter { w in
            w.canonical.lowercased().contains(needle)
                || (w.alias?.lowercased().contains(needle) ?? false)
        }
    }
}


// MARK: - I/O

enum Bridge {
    /// Single-line JSON event to Python. Stdout, flushed.
    static func send(_ payload: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: payload, options: []),
              let line = String(data: data, encoding: .utf8) else { return }
        FileHandle.standardOutput.write(Data((line + "\n").utf8))
    }
}


// MARK: - Window controller

final class VocabWindowController: NSWindowController, NSWindowDelegate {
    let model = VocabModel()

    init() {
        let panel = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 640, height: 720),
            styleMask: [.titled, .closable, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        panel.titlebarAppearsTransparent = true
        panel.titleVisibility = .hidden
        panel.isMovableByWindowBackground = true
        panel.backgroundColor = NSColor(Palette.bg)
        panel.appearance = NSAppearance(named: .darkAqua)
        panel.center()
        panel.title = "Vocabulary"
        panel.isReleasedWhenClosed = false
        // Floating but not always-on-top: comes forward on open, then behaves
        // like a normal window.
        panel.level = .normal

        super.init(window: panel)
        panel.delegate = self
        let root = NSHostingView(rootView: VocabRootView(model: model))
        root.frame = panel.contentView!.bounds
        root.autoresizingMask = [.width, .height]
        panel.contentView?.addSubview(root)
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) not supported") }

    func bringToFront() {
        guard let window = window else { return }
        if !window.isVisible {
            // Ask Python to push a fresh snapshot before we show — keeps the
            // open animation crisp.
            Bridge.send(["type": "refresh"])
        }
        NSApp.activate(ignoringOtherApps: true)
        window.makeKeyAndOrderFront(nil)
    }

    func windowWillClose(_ notification: Notification) {
        Bridge.send(["type": "window_closed"])
    }
}


// MARK: - Views

struct VocabRootView: View {
    @ObservedObject var model: VocabModel
    @State private var showingAdd = false
    @State private var showingPasteDump = false

    var body: some View {
        ZStack {
            Palette.bg.ignoresSafeArea()
            VStack(spacing: 0) {
                header
                searchAndAdd
                Divider()
                    .background(Palette.separator)
                    .padding(.horizontal, 28)
                wordList
                if !model.suggestions.isEmpty {
                    suggestionsSection
                }
            }
            .padding(.top, 28)
        }
        .frame(minWidth: 560, minHeight: 600)
        .sheet(isPresented: $showingPasteDump) {
            PasteDumpSheet(isPresented: $showingPasteDump)
        }
    }

    private var header: some View {
        HStack(alignment: .firstTextBaseline) {
            Text("Vocabulary")
                .font(.system(size: 28, weight: .semibold, design: .default))
                .foregroundColor(Palette.text)
                .tracking(-0.2)
            Spacer()
            Text("\(model.words.filter { $0.status != "archived" }.count) words")
                .font(.system(size: 13, weight: .medium, design: .monospaced))
                .foregroundColor(Palette.amber)
        }
        .padding(.horizontal, 28)
        .padding(.bottom, 18)
    }

    private var searchAndAdd: some View {
        HStack(spacing: 10) {
            // Search field
            HStack(spacing: 8) {
                Image(systemName: "magnifyingglass")
                    .foregroundColor(Palette.textDim)
                    .font(.system(size: 12, weight: .medium))
                TextField("Search\u{2026}", text: $model.search)
                    .textFieldStyle(.plain)
                    .foregroundColor(Palette.text)
                    .font(.system(size: 13, design: .monospaced))
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 9)
            .background(Palette.panel)
            .cornerRadius(8)

            // Add menu — single tap word, or paste dump
            Menu {
                Button("Add a word\u{2026}") { showingAdd = true }
                Button("Paste a block of text\u{2026}") { showingPasteDump = true }
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: "plus")
                        .font(.system(size: 11, weight: .bold))
                    Text("Add")
                        .font(.system(size: 13, weight: .semibold))
                }
                .foregroundColor(Palette.bg)
                .padding(.horizontal, 14)
                .padding(.vertical, 9)
                .background(Palette.amber)
                .cornerRadius(8)
            }
            .menuStyle(.borderlessButton)
            .menuIndicator(.hidden)
            .fixedSize()
        }
        .padding(.horizontal, 28)
        .padding(.bottom, 14)
        .sheet(isPresented: $showingAdd) {
            AddWordSheet(isPresented: $showingAdd)
        }
    }

    private var wordList: some View {
        ScrollView {
            LazyVStack(spacing: 0) {
                if model.words.isEmpty && model.suggestions.isEmpty {
                    EmptyStateView()
                        .padding(.top, 80)
                } else if model.filtered.isEmpty && !model.search.isEmpty {
                    Text("No matches for \u{201C}\(model.search)\u{201D}")
                        .font(.system(size: 13, design: .monospaced))
                        .foregroundColor(Palette.textMuted)
                        .padding(.top, 40)
                } else {
                    ForEach(model.filtered) { word in
                        WordRow(word: word)
                    }
                }
                Spacer(minLength: 20)
            }
            .padding(.horizontal, 16)
            .padding(.top, 6)
        }
    }

    private var suggestionsSection: some View {
        VStack(alignment: .leading, spacing: 0) {
            Rectangle()
                .fill(Palette.separator)
                .frame(height: 1)
                .padding(.horizontal, 28)
                .padding(.bottom, 16)
            VStack(alignment: .leading, spacing: 6) {
                HStack(spacing: 8) {
                    Image(systemName: "lightbulb")
                        .font(.system(size: 13, weight: .medium))
                        .foregroundColor(Palette.amber)
                    Text("Words the app wasn\u{2019}t sure about")
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundColor(Palette.text)
                }
                Text("Confirm a spelling to add to your vocabulary.")
                    .font(.system(size: 12))
                    .foregroundColor(Palette.textMuted)
            }
            .padding(.horizontal, 28)
            .padding(.bottom, 14)

            ScrollView {
                LazyVStack(spacing: 0) {
                    ForEach(model.suggestions) { s in
                        SuggestionRow(suggestion: s)
                    }
                }
                .padding(.horizontal, 16)
            }
            .frame(maxHeight: 220)
        }
        .padding(.bottom, 18)
        .background(Palette.panel.opacity(0.6))
    }
}


// MARK: - Row views

struct WordRow: View {
    let word: VocabWord
    @State private var hovered = false
    @State private var editing = false
    @State private var editedCanonical = ""
    @State private var editedAlias = ""

    var body: some View {
        HStack(alignment: .center, spacing: 14) {
            if editing {
                editingRow
            } else {
                displayRow
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 11)
        .background(hovered ? Palette.rowHover : Color.clear)
        .cornerRadius(6)
        .onHover { hovered = $0 }
        .contentShape(Rectangle())
        .onTapGesture {
            editedCanonical = word.canonical
            editedAlias = word.alias ?? ""
            editing = true
        }
    }

    private var displayRow: some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Text(word.canonical)
                .font(.system(size: 14, weight: .regular, design: .monospaced))
                .foregroundColor(Palette.text)
            if let a = word.alias, !a.isEmpty {
                HStack(spacing: 4) {
                    Image(systemName: "arrow.right")
                        .font(.system(size: 9, weight: .medium))
                        .foregroundColor(Palette.textDim)
                    Text("\u{201C}\(a)\u{201D}")
                        .font(.system(size: 12, design: .monospaced))
                        .foregroundColor(Palette.textMuted)
                        .italic()
                }
            }
            Spacer()
            statusPill
            if hovered {
                Button(action: removeWord) {
                    Image(systemName: "xmark")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundColor(Palette.textMuted)
                        .frame(width: 22, height: 22)
                        .background(Color.clear)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .help("Remove from vocabulary")
            }
        }
    }

    private var editingRow: some View {
        HStack(spacing: 8) {
            TextField("Word", text: $editedCanonical, onCommit: commitEdit)
                .textFieldStyle(.plain)
                .font(.system(size: 14, design: .monospaced))
                .foregroundColor(Palette.text)
                .padding(.horizontal, 8)
                .padding(.vertical, 5)
                .background(Palette.bg)
                .cornerRadius(4)
            Text("→")
                .foregroundColor(Palette.textDim)
            TextField("Spoken form (optional)", text: $editedAlias,
                      onCommit: commitEdit)
                .textFieldStyle(.plain)
                .font(.system(size: 12, design: .monospaced))
                .foregroundColor(Palette.textMuted)
                .padding(.horizontal, 8)
                .padding(.vertical, 5)
                .background(Palette.bg)
                .cornerRadius(4)
            Button("Save") { commitEdit() }
                .buttonStyle(AmberFilledButtonStyle())
            Button("Cancel") { editing = false }
                .buttonStyle(GhostButtonStyle())
        }
    }

    private var statusPill: some View {
        Group {
            switch word.status {
            case "active":
                pill("\(word.usage_count)× active", color: Palette.amber)
            case "seen":
                pill("seen \(word.usage_count)×", color: Palette.textMuted)
            case "new":
                pill("new", color: Palette.textMuted)
            case "archived":
                pill("archived", color: Palette.textDim)
            default:
                EmptyView()
            }
        }
    }

    private func pill(_ text: String, color: Color) -> some View {
        Text(text)
            .font(.system(size: 10, weight: .medium, design: .monospaced))
            .foregroundColor(color)
            .padding(.horizontal, 7)
            .padding(.vertical, 2)
            .background(color.opacity(0.12))
            .cornerRadius(3)
    }

    private func commitEdit() {
        let newC = editedCanonical.trimmingCharacters(in: .whitespaces)
        if !newC.isEmpty {
            Bridge.send([
                "type": "update", "old": word.canonical,
                "new": newC, "alias": editedAlias.trimmingCharacters(in: .whitespaces),
            ])
        }
        editing = false
    }

    private func removeWord() {
        Bridge.send(["type": "remove", "canonical": word.canonical])
    }
}


struct SuggestionRow: View {
    let suggestion: VocabSuggestion
    @State private var hovered = false
    @State private var editedCanonical: String = ""

    var body: some View {
        HStack(spacing: 12) {
            // Heard form (mono, dim — "what Whisper produced")
            Text("\u{201C}\(suggestion.raw)\u{201D}")
                .font(.system(size: 12, design: .monospaced))
                .foregroundColor(Palette.textMuted)
                .frame(width: 130, alignment: .leading)
                .lineLimit(1)

            Image(systemName: "arrow.right")
                .font(.system(size: 10, weight: .medium))
                .foregroundColor(Palette.textDim)

            // Editable canonical (user's expected spelling)
            TextField("", text: $editedCanonical,
                      onCommit: { accept() })
                .textFieldStyle(.plain)
                .font(.system(size: 13, weight: .medium, design: .monospaced))
                .foregroundColor(Palette.text)
                .padding(.horizontal, 8)
                .padding(.vertical, 5)
                .background(Palette.bg)
                .cornerRadius(4)

            Text("\(suggestion.count)×")
                .font(.system(size: 11, design: .monospaced))
                .foregroundColor(Palette.textDim)
                .frame(width: 28, alignment: .trailing)

            Button(action: accept) {
                HStack(spacing: 4) {
                    Image(systemName: "checkmark")
                        .font(.system(size: 10, weight: .bold))
                    Text("Add")
                        .font(.system(size: 11, weight: .semibold))
                }
                .foregroundColor(Palette.amber)
                .padding(.horizontal, 10)
                .padding(.vertical, 5)
                .overlay(
                    RoundedRectangle(cornerRadius: 4)
                        .stroke(Palette.amber, lineWidth: 1)
                )
            }
            .buttonStyle(.plain)
            .keyboardShortcut(.return, modifiers: [])

            Button(action: dismiss) {
                Image(systemName: "xmark")
                    .font(.system(size: 11, weight: .medium))
                    .foregroundColor(Palette.textMuted)
                    .frame(width: 22, height: 22)
            }
            .buttonStyle(.plain)
            .help("Ignore this suggestion")
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 9)
        .background(hovered ? Palette.rowHover : Color.clear)
        .cornerRadius(6)
        .onHover { hovered = $0 }
        .onAppear { editedCanonical = suggestion.suggested }
    }

    private func accept() {
        let c = editedCanonical.trimmingCharacters(in: .whitespaces)
        guard !c.isEmpty else { return }
        Bridge.send(["type": "accept_suggestion",
                     "raw": suggestion.raw, "canonical": c])
    }

    private func dismiss() {
        Bridge.send(["type": "dismiss_suggestion", "raw": suggestion.raw])
    }
}


// MARK: - Sheets

struct AddWordSheet: View {
    @Binding var isPresented: Bool
    @State private var canonical = ""
    @State private var alias = ""

    var body: some View {
        ZStack {
            Palette.bg.ignoresSafeArea()
            VStack(alignment: .leading, spacing: 18) {
                Text("Add a word to your vocabulary")
                    .font(.system(size: 18, weight: .semibold))
                    .foregroundColor(Palette.text)
                Text("Whisper will bias toward this word on every dictation.")
                    .font(.system(size: 12))
                    .foregroundColor(Palette.textMuted)

                VStack(alignment: .leading, spacing: 6) {
                    Text("Canonical spelling")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundColor(Palette.textMuted)
                    TextField("Polistician", text: $canonical)
                        .textFieldStyle(.plain)
                        .font(.system(size: 14, design: .monospaced))
                        .foregroundColor(Palette.text)
                        .padding(10)
                        .background(Palette.panel)
                        .cornerRadius(6)
                }
                VStack(alignment: .leading, spacing: 6) {
                    Text("If you say it differently (optional)")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundColor(Palette.textMuted)
                    TextField("habla daily", text: $alias)
                        .textFieldStyle(.plain)
                        .font(.system(size: 13, design: .monospaced))
                        .foregroundColor(Palette.text)
                        .padding(10)
                        .background(Palette.panel)
                        .cornerRadius(6)
                }
                HStack {
                    Spacer()
                    Button("Cancel") { isPresented = false }
                        .buttonStyle(GhostButtonStyle())
                        .keyboardShortcut(.escape)
                    Button("Save") {
                        Bridge.send(["type": "add",
                                     "canonical": canonical.trimmingCharacters(in: .whitespaces),
                                     "alias": alias.trimmingCharacters(in: .whitespaces)])
                        isPresented = false
                    }
                    .buttonStyle(AmberFilledButtonStyle())
                    .keyboardShortcut(.return)
                    .disabled(canonical.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
            .padding(28)
            .frame(width: 480)
        }
    }
}

struct PasteDumpSheet: View {
    @Binding var isPresented: Bool
    @State private var text = ""

    var body: some View {
        ZStack {
            Palette.bg.ignoresSafeArea()
            VStack(alignment: .leading, spacing: 18) {
                Text("Paste a block of text")
                    .font(.system(size: 18, weight: .semibold))
                    .foregroundColor(Palette.text)
                Text("Paste a README, a glossary, a brand list \u{2014} anything. "
                     + "The app pulls proper nouns and capitalized terms for you to confirm.")
                    .font(.system(size: 12))
                    .foregroundColor(Palette.textMuted)
                    .fixedSize(horizontal: false, vertical: true)

                TextEditor(text: $text)
                    .font(.system(size: 13, design: .monospaced))
                    .foregroundColor(Palette.text)
                    .colorMultiply(Palette.text)
                    .scrollContentBackground(.hidden)
                    .padding(8)
                    .background(Palette.panel)
                    .cornerRadius(6)
                    .frame(minHeight: 220)

                HStack {
                    Spacer()
                    Button("Cancel") { isPresented = false }
                        .buttonStyle(GhostButtonStyle())
                        .keyboardShortcut(.escape)
                    Button("Extract \u{0026} Add") {
                        Bridge.send(["type": "paste_dump", "text": text])
                        isPresented = false
                    }
                    .buttonStyle(AmberFilledButtonStyle())
                    .disabled(text.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
            .padding(28)
            .frame(width: 560, height: 480)
        }
    }
}


// MARK: - Empty state

struct EmptyStateView: View {
    var body: some View {
        VStack(spacing: 14) {
            Image(systemName: "text.cursor")
                .font(.system(size: 36, weight: .regular))
                .foregroundColor(Palette.textDim)
            Text("Your vocabulary is empty")
                .font(.system(size: 16, weight: .medium))
                .foregroundColor(Palette.textMuted)
            Text("Add the niche words you actually use \u{2014} project names, jargon, brand terms. \nWhisper biases toward them on every dictation.")
                .font(.system(size: 12))
                .foregroundColor(Palette.textDim)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.horizontal, 60)
        }
    }
}


// MARK: - Button styles

struct AmberFilledButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 13, weight: .semibold))
            .foregroundColor(Palette.bg)
            .padding(.horizontal, 14)
            .padding(.vertical, 8)
            .background(
                Palette.amber.opacity(configuration.isPressed ? 0.8 : 1.0)
            )
            .cornerRadius(6)
    }
}

struct GhostButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 13, weight: .medium))
            .foregroundColor(Palette.textMuted)
            .padding(.horizontal, 14)
            .padding(.vertical, 8)
            .background(Palette.panel.opacity(configuration.isPressed ? 0.8 : 0.5))
            .cornerRadius(6)
    }
}


// MARK: - App entry

final class VocabAppDelegate: NSObject, NSApplicationDelegate {
    var controller: VocabWindowController?
    var stdinReader: DispatchSourceRead?

    func applicationDidFinishLaunching(_ notification: Notification) {
        controller = VocabWindowController()
        startStdinReader()
        // Don't auto-show; wait for the {"type":"open"} request from Python.
        // VoiceType's parent process opens the window when the user clicks
        // the menubar item.
    }

    private func startStdinReader() {
        let fd = FileHandle.standardInput.fileDescriptor
        let q = DispatchQueue(label: "vocab.stdin")
        let source = DispatchSource.makeReadSource(fileDescriptor: fd, queue: q)
        var buffer = Data()
        source.setEventHandler {
            let chunk = FileHandle.standardInput.availableData
            if chunk.isEmpty {
                // stdin closed → parent process gone → exit
                DispatchQueue.main.async { NSApp.terminate(nil) }
                return
            }
            buffer.append(chunk)
            while let nl = buffer.firstIndex(of: 0x0A) {
                let line = buffer.subdata(in: 0 ..< nl)
                buffer.removeSubrange(0 ... nl)
                guard !line.isEmpty,
                      let obj = try? JSONSerialization.jsonObject(with: line),
                      let dict = obj as? [String: Any],
                      let type = dict["type"] as? String else { continue }
                DispatchQueue.main.async { [weak self] in
                    self?.handle(type: type, payload: dict)
                }
            }
        }
        stdinReader = source
        source.resume()
    }

    @MainActor
    private func handle(type: String, payload: [String: Any]) {
        guard let controller = controller else { return }
        switch type {
        case "open":
            controller.bringToFront()
        case "close":
            controller.window?.orderOut(nil)
        case "vocab_state":
            guard let data = try? JSONSerialization.data(withJSONObject: payload),
                  let state = try? JSONDecoder().decode(VocabStateWire.self, from: data)
            else { return }
            controller.model.apply(VocabState(words: state.words,
                                              suggestions: state.suggestions))
        default:
            break
        }
    }
}

// Wire decoder shape — same as VocabState but tolerates the "type" key.
struct VocabStateWire: Codable {
    var words: [VocabWord]
    var suggestions: [VocabSuggestion]
}


// MARK: - main

@main
struct VocabApp {
    static func main() {
        let app = NSApplication.shared
        let delegate = VocabAppDelegate()
        app.delegate = delegate
        app.setActivationPolicy(.accessory)  // no Dock icon
        // Keep a strong reference; without it the delegate gets collected
        // when this scope returns even though app.run() blocks afterwards.
        objc_setAssociatedObject(app, "vt_delegate", delegate, .OBJC_ASSOCIATION_RETAIN)
        app.run()
    }
}
