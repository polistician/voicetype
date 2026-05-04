// paste_helper.swift
// Sets clipboard from stdin, then simulates paste into the focused app.
// Uses Cmd+V normally, but Cmd+Shift+V for VS Code (terminal paste).

import Cocoa
import Foundation

// Set clipboard from stdin
let input = FileHandle.standardInput.readDataToEndOfFile()
guard let text = String(data: input, encoding: .utf8), !text.isEmpty else { exit(0) }

let pasteboard = NSPasteboard.general
pasteboard.clearContents()
pasteboard.setString(text, forType: .string)

// Small delay for clipboard to settle
usleep(50000)  // 50ms

let source = CGEventSource(stateID: .hidSystemState)
let vKeyCode: CGKeyCode = 9

// Check if VS Code or Cursor is frontmost
let frontApp = NSWorkspace.shared.frontmostApplication?.bundleIdentifier ?? ""
let isTerminalApp = frontApp.contains("com.microsoft.VSCode") ||
                    frontApp.contains("com.todesktop.") ||  // Cursor
                    frontApp.contains("com.apple.Terminal") ||
                    frontApp.contains("com.googlecode.iterm2")

if isTerminalApp {
    // For VS Code/Cursor terminals: try both Cmd+V and Cmd+Shift+V
    // First Cmd+V (works in editor panes)
    let keyDown = CGEvent(keyboardEventSource: source, virtualKey: vKeyCode, keyDown: true)
    keyDown?.flags = .maskCommand
    keyDown?.post(tap: .cghidEventTap)

    let keyUp = CGEvent(keyboardEventSource: source, virtualKey: vKeyCode, keyDown: false)
    keyUp?.flags = .maskCommand
    keyUp?.post(tap: .cghidEventTap)
} else {
    // Standard Cmd+V for other apps
    let keyDown = CGEvent(keyboardEventSource: source, virtualKey: vKeyCode, keyDown: true)
    keyDown?.flags = .maskCommand
    keyDown?.post(tap: .cghidEventTap)

    let keyUp = CGEvent(keyboardEventSource: source, virtualKey: vKeyCode, keyDown: false)
    keyUp?.flags = .maskCommand
    keyUp?.post(tap: .cghidEventTap)
}
