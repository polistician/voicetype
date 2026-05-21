// hotkey_helper.swift
// Registers Option+C (dictate) and Option+T (translate clipboard) global hotkeys.
// Accepts "PASTE:<text>" on stdin to paste text into frontmost app.

import Cocoa
import Carbon

class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        // Verify we actually have permission to post events
        let canPost = CGPreflightPostEventAccess()
        let isTrusted = AXIsProcessTrusted()
        fputs("PERMISSIONS: AXTrusted=\(isTrusted) CGPostAccess=\(canPost)\n", stdout)
        fputs("AX_TRUSTED: \(isTrusted)\n", stdout)
        fflush(stdout)

        if !canPost {
            fputs("WARNING: Cannot post events. Remove and re-add VoxType.app in Accessibility preferences.\n", stdout)
            fflush(stdout)
        }

        // Start stdin reader for paste / undo commands
        let stdinThread = Thread {
            while let line = readLine() {
                if line.hasPrefix("PASTE:") {
                    let text = String(line.dropFirst(6))
                    DispatchQueue.main.async {
                        self.pasteText(text)
                    }
                } else if line == "UNDO" {
                    DispatchQueue.main.async {
                        self.synthesizeCmdZ()
                    }
                }
            }
        }
        stdinThread.start()

        // Register Option+C hotkey (kVK_ANSI_C = 8) — dictate
        var dictateKeyRef: EventHotKeyRef?
        let dictateKeyID = EventHotKeyID(signature: OSType(0x564F5854), id: 1)

        let status1 = RegisterEventHotKey(
            UInt32(kVK_ANSI_C),
            UInt32(optionKey),
            dictateKeyID,
            GetApplicationEventTarget(),
            0,
            &dictateKeyRef
        )

        if status1 != noErr {
            fputs("WARNING: Option+C dictate hotkey failed to register (status: \(status1))\n", stderr)
        }

        // ALSO register Control+Option+C — fallback for German QWERTZ layouts
        // where ⌥C is a dead-key composition (produces ç) and macOS consumes
        // the event at the layout level before Carbon hotkey delivery. Adding
        // Control breaks the dead-key path. Both hotkeys fire the same handler.
        var dictateAltRef: EventHotKeyRef?
        let dictateAltID = EventHotKeyID(signature: OSType(0x564F5854), id: 4)
        let status1b = RegisterEventHotKey(
            UInt32(kVK_ANSI_C),
            UInt32(optionKey | controlKey),
            dictateAltID,
            GetApplicationEventTarget(),
            0,
            &dictateAltRef
        )
        if status1b != noErr {
            fputs("WARNING: Control+Option+C alternate hotkey failed (status: \(status1b))\n", stderr)
        }

        if status1 != noErr && status1b != noErr {
            fputs("ERROR: Both ⌥C and ⌃⌥C dictate hotkeys failed to register\n", stderr)
            exit(1)
        }

        // Register Option+T hotkey (kVK_ANSI_T = 17) — translate clipboard
        var translateKeyRef: EventHotKeyRef?
        let translateKeyID = EventHotKeyID(signature: OSType(0x564F5854), id: 2)

        let status2 = RegisterEventHotKey(
            UInt32(kVK_ANSI_T),
            UInt32(optionKey),
            translateKeyID,
            GetApplicationEventTarget(),
            0,
            &translateKeyRef
        )

        if status2 != noErr {
            fputs("WARNING: Option+T translate hotkey failed (status: \(status2))\n", stderr)
        }

        // ALSO register Control+Option+T (QWERTZ fallback)
        var translateAltRef: EventHotKeyRef?
        let translateAltID = EventHotKeyID(signature: OSType(0x564F5854), id: 5)
        let _ = RegisterEventHotKey(
            UInt32(kVK_ANSI_T),
            UInt32(optionKey | controlKey),
            translateAltID,
            GetApplicationEventTarget(),
            0,
            &translateAltRef
        )

        // Register Option+Shift+S hotkey (kVK_ANSI_S = 1) — open snippet overlay
        var overlayKeyRef: EventHotKeyRef?
        let overlayKeyID = EventHotKeyID(signature: OSType(0x564F5854), id: 3)

        let status3 = RegisterEventHotKey(
            UInt32(kVK_ANSI_S),
            UInt32(optionKey | shiftKey),
            overlayKeyID,
            GetApplicationEventTarget(),
            0,
            &overlayKeyRef
        )

        if status3 != noErr {
            fputs("ERROR: Could not register Option+Shift+S hotkey (status: \(status3))\n", stderr)
            exit(1)
        }

        // Register Option+Shift+V (kVK_ANSI_V = 9) — Quick Fix bar.
        // Captures the last transcript inline for one-touch vocab + correction.
        var quickFixKeyRef: EventHotKeyRef?
        let quickFixKeyID = EventHotKeyID(signature: OSType(0x564F5854), id: 6)
        let status4 = RegisterEventHotKey(
            UInt32(kVK_ANSI_V),
            UInt32(optionKey | shiftKey),
            quickFixKeyID,
            GetApplicationEventTarget(),
            0,
            &quickFixKeyRef
        )
        if status4 != noErr {
            fputs("WARNING: Option+Shift+V Quick Fix hotkey failed (status: \(status4))\n", stderr)
        }

        // Register Option+Shift+C (kVK_ANSI_C = 8) — Command Mode (hold to dictate
        // an editing instruction against the last paste). Held key, so we listen
        // for both press AND release like the dictate hotkey.
        var cmdModeKeyRef: EventHotKeyRef?
        let cmdModeKeyID = EventHotKeyID(signature: OSType(0x564F5854), id: 7)
        let status5 = RegisterEventHotKey(
            UInt32(kVK_ANSI_C),
            UInt32(optionKey | shiftKey),
            cmdModeKeyID,
            GetApplicationEventTarget(),
            0,
            &cmdModeKeyRef
        )
        if status5 != noErr {
            fputs("WARNING: Option+Shift+C Command Mode hotkey failed (status: \(status5))\n", stderr)
        }

        fputs("READY\n", stdout)
        fflush(stdout)

        var eventSpec = [
            EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed)),
            EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyReleased))
        ]

        InstallEventHandler(
            GetApplicationEventTarget(),
            { (_, event, _) -> OSStatus in
                var hotKeyID = EventHotKeyID()
                GetEventParameter(event, EventParamName(kEventParamDirectObject),
                                EventParamType(typeEventHotKeyID), nil,
                                MemoryLayout<EventHotKeyID>.size, nil, &hotKeyID)

                let kind = GetEventKind(event)

                if hotKeyID.id == 1 || hotKeyID.id == 4 {
                    // Option+C OR Control+Option+C — dictate (QWERTZ-safe alt)
                    if kind == UInt32(kEventHotKeyPressed) {
                        fputs("START\n", stdout)
                        fflush(stdout)
                    } else if kind == UInt32(kEventHotKeyReleased) {
                        fputs("STOP\n", stdout)
                        fflush(stdout)
                    }
                } else if hotKeyID.id == 2 || hotKeyID.id == 5 {
                    // Option+T OR Control+Option+T — translate (fire on press only)
                    if kind == UInt32(kEventHotKeyPressed) {
                        fputs("TRANSLATE\n", stdout)
                        fflush(stdout)
                    }
                } else if hotKeyID.id == 3 {
                    // Option+Shift+S — open snippet overlay (fire on press only)
                    if kind == UInt32(kEventHotKeyPressed) {
                        fputs("OPEN_OVERLAY\n", stdout)
                        fflush(stdout)
                    }
                } else if hotKeyID.id == 6 {
                    // Option+Shift+V — open Quick Fix bar (fire on press only)
                    if kind == UInt32(kEventHotKeyPressed) {
                        fputs("OPEN_QUICK_FIX\n", stdout)
                        fflush(stdout)
                    }
                } else if hotKeyID.id == 7 {
                    // Option+Shift+C — Command Mode (hold to dictate an edit)
                    if kind == UInt32(kEventHotKeyPressed) {
                        fputs("COMMAND_MODE_START\n", stdout)
                        fflush(stdout)
                    } else if kind == UInt32(kEventHotKeyReleased) {
                        fputs("COMMAND_MODE_STOP\n", stdout)
                        fflush(stdout)
                    }
                }
                return noErr
            },
            eventSpec.count,
            &eventSpec,
            nil,
            nil
        )
    }

    func pasteText(_ text: String) {
        // Step 1: Set clipboard
        let pasteboard = NSPasteboard.general
        pasteboard.clearContents()
        pasteboard.setString(text, forType: .string)

        // Step 2: Wait 100ms (same as FreeFlow)
        usleep(100000)

        // Step 3: Simulate Cmd+V via CGEvent using .cgSessionEventTap (same as FreeFlow)
        let source = CGEventSource(stateID: .combinedSessionState)
        let vKeyCode: CGKeyCode = 9

        let keyDown = CGEvent(keyboardEventSource: source, virtualKey: vKeyCode, keyDown: true)
        keyDown?.flags = .maskCommand
        keyDown?.post(tap: .cgSessionEventTap)

        usleep(30000) // 30ms between key down and up

        let keyUp = CGEvent(keyboardEventSource: source, virtualKey: vKeyCode, keyDown: false)
        keyUp?.flags = .maskCommand
        keyUp?.post(tap: .cgSessionEventTap)

        fputs("PASTED\n", stdout)
        fflush(stdout)
    }

    func synthesizeCmdZ() {
        // Cmd+Z — used by Tier-1 voice command "undo that". Uses the same
        // cgSessionEventTap pattern as paste() so target apps see a real
        // keystroke, not a "synthesized" event filtered by some apps.
        let source = CGEventSource(stateID: .combinedSessionState)
        let zKeyCode: CGKeyCode = 6  // kVK_ANSI_Z

        let keyDown = CGEvent(keyboardEventSource: source, virtualKey: zKeyCode, keyDown: true)
        keyDown?.flags = .maskCommand
        keyDown?.post(tap: .cgSessionEventTap)

        usleep(30000)

        let keyUp = CGEvent(keyboardEventSource: source, virtualKey: zKeyCode, keyDown: false)
        keyUp?.flags = .maskCommand
        keyUp?.post(tap: .cgSessionEventTap)

        fputs("UNDONE\n", stdout)
        fflush(stdout)
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let delegate = AppDelegate()
app.delegate = delegate
app.run()
