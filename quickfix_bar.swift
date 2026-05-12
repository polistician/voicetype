// quickfix_bar.swift — VoiceType Quick Fix floating bar
//
// ⌥⇧V triggers Python → sends {"type":"open","text":"<last transcript>"}
// to this helper. A borderless floating panel slides down from the top of
// the screen, shows the transcript as clickable word chips. The user clicks
// a wrong word, types the right spelling, presses ↵.
//
// On commit the helper emits:
//   {"type":"fix","wrong":"polystition","correct":"Polistician"}
// Python then:
//   1. Adds Polistician to vocabulary.json
//   2. Adds {"polystition":"Polistician"} to corrections.json
//
// Esc dismisses without saving.
//
// Wire protocol
//
//   Python → Swift
//     {"type":"open","text":"the full last transcript"}
//     {"type":"close"}
//
//   Swift → Python
//     {"type":"fix","wrong":"polystition","correct":"Polistician"}
//     {"type":"closed"}
//
// Visual: same palette as vocabulary_window — dark, amber accent, SF Mono
// for the transcript words.

import Cocoa
import SwiftUI


// MARK: - Palette (duplicated from vocabulary_window for binary independence)

enum QFPalette {
    static let bg          = Color(red: 0.043, green: 0.043, blue: 0.047)
    static let panel       = Color(red: 0.078, green: 0.078, blue: 0.086)
    static let panelHover  = Color(red: 0.137, green: 0.137, blue: 0.149)
    static let separator   = Color(red: 0.196, green: 0.196, blue: 0.216)
    static let text        = Color(red: 0.945, green: 0.910, blue: 0.847)
    static let textMuted   = Color(red: 0.580, green: 0.553, blue: 0.510)
    static let textDim     = Color(red: 0.380, green: 0.365, blue: 0.337)
    static let amber       = Color(red: 0.961, green: 0.651, blue: 0.137)
    static let amberSoft   = Color(red: 0.961, green: 0.651, blue: 0.137, opacity: 0.18)
}


@MainActor
final class QFModel: ObservableObject {
    @Published var words: [String] = []
    /// Index into ``words`` currently being edited; -1 = none.
    @Published var editingIndex: Int = -1
    @Published var editedText: String = ""

    func load(_ transcript: String) {
        // Preserve original tokenization (whitespace split, punctuation attached
        // — matches what Whisper produced).
        words = transcript.split(separator: " ", omittingEmptySubsequences: true)
            .map(String.init)
        editingIndex = -1
        editedText = ""
    }

    func startEditing(_ idx: Int) {
        guard idx >= 0, idx < words.count else { return }
        editingIndex = idx
        // Strip trailing punctuation from the seed (less to fix), preserve
        // the original word for the "wrong" lookup.
        editedText = words[idx].trimmingCharacters(in: .punctuationCharacters)
    }

    func cancelEditing() {
        editingIndex = -1
        editedText = ""
    }

    func commitEdit() -> (wrong: String, correct: String)? {
        guard editingIndex >= 0, editingIndex < words.count else { return nil }
        let newText = editedText.trimmingCharacters(in: .whitespaces)
        guard !newText.isEmpty else { return nil }
        let original = words[editingIndex]
        let originalCore = original.trimmingCharacters(in: .punctuationCharacters)
        if originalCore.isEmpty || newText == originalCore { return nil }
        // Replace just the alphabetic core in the original token, preserving
        // any trailing punctuation (commas, periods).
        if let range = original.range(of: originalCore) {
            words[editingIndex] = original.replacingCharacters(in: range, with: newText)
        } else {
            words[editingIndex] = newText
        }
        editingIndex = -1
        editedText = ""
        return (wrong: originalCore, correct: newText)
    }
}


enum QFBridge {
    static func send(_ payload: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: payload),
              let line = String(data: data, encoding: .utf8) else { return }
        FileHandle.standardOutput.write(Data((line + "\n").utf8))
    }
}


final class QFWindowController: NSWindowController, NSWindowDelegate {
    let model = QFModel()

    init() {
        let screenWidth = NSScreen.main?.frame.width ?? 1440
        let width = min(900.0, screenWidth - 80)
        let panel = NSPanel(
            contentRect: NSRect(x: 0, y: 0, width: width, height: 132),
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )
        panel.isFloatingPanel = true
        panel.level = .floating
        panel.titleVisibility = .hidden
        panel.titlebarAppearsTransparent = true
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = true
        panel.isMovableByWindowBackground = true
        panel.appearance = NSAppearance(named: .darkAqua)
        panel.hidesOnDeactivate = false
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        super.init(window: panel)
        panel.delegate = self
        let root = NSHostingView(rootView:
            QFRootView(model: model, dismiss: { [weak self] in self?.dismiss() }))
        root.frame = panel.contentView!.bounds
        root.autoresizingMask = [.width, .height]
        panel.contentView?.addSubview(root)
    }

    required init?(coder: NSCoder) { fatalError() }

    func open(with transcript: String) {
        model.load(transcript)
        guard let window = window, let screen = NSScreen.main else { return }
        // Position: horizontally centered, vertically ~25% from top of screen
        let frame = screen.visibleFrame
        let x = frame.midX - window.frame.width / 2
        let y = frame.maxY - window.frame.height - 80
        window.setFrameOrigin(NSPoint(x: x, y: y))
        NSApp.activate(ignoringOtherApps: true)
        window.makeKeyAndOrderFront(nil)
    }

    func dismiss() {
        window?.orderOut(nil)
        QFBridge.send(["type": "closed"])
    }
}


struct QFRootView: View {
    @ObservedObject var model: QFModel
    var dismiss: () -> Void

    var body: some View {
        ZStack {
            // Rounded backplate
            RoundedRectangle(cornerRadius: 14)
                .fill(QFPalette.bg)
                .overlay(
                    RoundedRectangle(cornerRadius: 14)
                        .stroke(QFPalette.separator, lineWidth: 0.5)
                )
            VStack(alignment: .leading, spacing: 12) {
                header
                wordsFlow
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 16)
        }
        .padding(8)   // outer shadow margin
    }

    private var header: some View {
        HStack(spacing: 10) {
            Image(systemName: "wand.and.stars")
                .font(.system(size: 12, weight: .medium))
                .foregroundColor(QFPalette.amber)
            Text("Quick Fix")
                .font(.system(size: 13, weight: .semibold))
                .foregroundColor(QFPalette.text)
            Text("click a word to teach VoiceType the right spelling")
                .font(.system(size: 11))
                .foregroundColor(QFPalette.textMuted)
            Spacer()
            Text("Esc")
                .font(.system(size: 10, weight: .medium, design: .monospaced))
                .foregroundColor(QFPalette.textDim)
                .padding(.horizontal, 6)
                .padding(.vertical, 2)
                .overlay(
                    RoundedRectangle(cornerRadius: 3)
                        .stroke(QFPalette.textDim, lineWidth: 0.5)
                )
        }
    }

    private var wordsFlow: some View {
        WrapLayout(spacing: 6, lineSpacing: 8) {
            ForEach(Array(model.words.enumerated()), id: \.offset) { idx, word in
                if idx == model.editingIndex {
                    WordEditor(model: model, dismiss: dismiss)
                } else {
                    WordChip(word: word, onClick: { model.startEditing(idx) })
                }
            }
        }
    }
}


struct WordChip: View {
    let word: String
    let onClick: () -> Void
    @State private var hovered = false

    var body: some View {
        Button(action: onClick) {
            Text(word)
                .font(.system(size: 14, weight: .regular, design: .monospaced))
                .foregroundColor(QFPalette.text)
                .padding(.horizontal, 8)
                .padding(.vertical, 4)
                .background(hovered ? QFPalette.amberSoft : QFPalette.panel)
                .cornerRadius(4)
                .overlay(
                    RoundedRectangle(cornerRadius: 4)
                        .stroke(hovered ? QFPalette.amber : Color.clear, lineWidth: 1)
                )
        }
        .buttonStyle(.plain)
        .onHover { hovered = $0 }
    }
}


struct WordEditor: View {
    @ObservedObject var model: QFModel
    var dismiss: () -> Void
    @FocusState private var focused: Bool

    var body: some View {
        HStack(spacing: 6) {
            TextField("", text: $model.editedText, onCommit: commit)
                .textFieldStyle(.plain)
                .font(.system(size: 14, weight: .medium, design: .monospaced))
                .foregroundColor(QFPalette.amber)
                .frame(minWidth: 80)
                .focused($focused)
                .onAppear { focused = true }
            Image(systemName: "return")
                .font(.system(size: 10, weight: .medium))
                .foregroundColor(QFPalette.textDim)
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 4)
        .background(QFPalette.amberSoft)
        .cornerRadius(4)
        .overlay(
            RoundedRectangle(cornerRadius: 4)
                .stroke(QFPalette.amber, lineWidth: 1)
        )
    }

    private func commit() {
        if let fix = model.commitEdit() {
            QFBridge.send(["type": "fix",
                           "wrong": fix.wrong,
                           "correct": fix.correct])
        }
    }
}


// MARK: - Wrap layout (flow lines of variable-width children)
// Avoids importing extra deps; SwiftUI's native HStack doesn't wrap.

struct WrapLayout: Layout {
    var spacing: CGFloat = 6
    var lineSpacing: CGFloat = 8

    func sizeThatFits(proposal: ProposedViewSize,
                      subviews: Subviews, cache: inout ()) -> CGSize {
        let width = proposal.width ?? 800
        return arrange(in: width, subviews: subviews).size
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize,
                       subviews: Subviews, cache: inout ()) {
        let result = arrange(in: bounds.width, subviews: subviews)
        for (i, p) in result.positions.enumerated() {
            subviews[i].place(at: CGPoint(x: bounds.minX + p.x,
                                          y: bounds.minY + p.y),
                              proposal: ProposedViewSize(result.sizes[i]))
        }
    }

    private func arrange(in width: CGFloat, subviews: Subviews)
        -> (positions: [CGPoint], sizes: [CGSize], size: CGSize)
    {
        var positions: [CGPoint] = []
        var sizes: [CGSize] = []
        var x: CGFloat = 0
        var y: CGFloat = 0
        var lineH: CGFloat = 0
        var maxX: CGFloat = 0
        for sub in subviews {
            let s = sub.sizeThatFits(.unspecified)
            sizes.append(s)
            if x + s.width > width && x > 0 {
                x = 0
                y += lineH + lineSpacing
                lineH = 0
            }
            positions.append(CGPoint(x: x, y: y))
            x += s.width + spacing
            lineH = max(lineH, s.height)
            maxX = max(maxX, x)
        }
        return (positions, sizes, CGSize(width: maxX, height: y + lineH))
    }
}


// MARK: - App entry

@MainActor
final class QFAppDelegate: NSObject, NSApplicationDelegate {
    var controller: QFWindowController?
    var stdinReader: DispatchSourceRead?

    func applicationDidFinishLaunching(_ notification: Notification) {
        controller = QFWindowController()
        startStdinReader()
        // Esc key — local monitor so the panel dismisses without consuming
        // global key events.
        NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] ev in
            if ev.keyCode == 53 {  // Esc
                self?.controller?.dismiss()
                return nil
            }
            return ev
        }
    }

    private func startStdinReader() {
        let fd = FileHandle.standardInput.fileDescriptor
        let source = DispatchSource.makeReadSource(fileDescriptor: fd,
                                                   queue: DispatchQueue(label: "qf.stdin"))
        var buffer = Data()
        source.setEventHandler {
            let chunk = FileHandle.standardInput.availableData
            if chunk.isEmpty {
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
            let text = (payload["text"] as? String) ?? ""
            controller.open(with: text)
        case "close":
            controller.dismiss()
        default:
            break
        }
    }
}


@main
struct QuickFixApp {
    static func main() {
        let app = NSApplication.shared
        let delegate = QFAppDelegate()
        app.delegate = delegate
        app.setActivationPolicy(.accessory)
        objc_setAssociatedObject(app, "qf_delegate", delegate, .OBJC_ASSOCIATION_RETAIN)
        app.run()
    }
}
