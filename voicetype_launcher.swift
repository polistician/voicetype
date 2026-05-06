// voicetype_launcher.swift
//
// AppTranslocation breakout for VoiceType.
//
// macOS runs ad-hoc-signed apps with the quarantine xattr from a randomized
// /private/var/folders/.../AppTranslocation/ path. Every launch is a different
// path, breaking permission grants on child binaries.
//
// This launcher is the bundle's Contents/MacOS/VoiceType entrypoint. On each
// launch:
//   1. Check if its own path starts with /private/var/folders/.../AppTranslocation/
//   2. If yes: remove quarantine xattr from /Applications/VoiceType.app, then
//      `open` that app (which now runs from the real path), then exit. The user
//      sees the app launch normally on the second run.
//   3. If no: execv the real Python entry at MacOS/VoiceType_main with the
//      same argv. Standard exec behavior — same process tree, same permissions.
//
// Build: swiftc -O voicetype_launcher.swift -o voicetype_launcher
// Bundled: PyInstaller renames its output binary to VoiceType_main and the
// launcher is copied to MacOS/VoiceType.

import Foundation
import Darwin

let TRANSLOCATION_PATTERN = "/AppTranslocation/"
let APP_PATH = "/Applications/VoiceType.app"
let QUARANTINE_XATTR = "com.apple.quarantine"

func selfPath() -> String {
    var size: UInt32 = 4096
    var buffer = [CChar](repeating: 0, count: Int(size))
    if _NSGetExecutablePath(&buffer, &size) == 0 {
        return String(cString: buffer)
    }
    return ""
}

func removeQuarantineRecursive(at path: String) {
    let url = URL(fileURLWithPath: path)
    let fm = FileManager.default
    guard let enumerator = fm.enumerator(at: url, includingPropertiesForKeys: nil) else {
        // Best-effort: try root only
        _ = path.withCString { removexattr($0, QUARANTINE_XATTR, XATTR_NOFOLLOW) }
        return
    }
    _ = path.withCString { removexattr($0, QUARANTINE_XATTR, XATTR_NOFOLLOW) }
    for case let fileURL as URL in enumerator {
        _ = fileURL.path.withCString { removexattr($0, QUARANTINE_XATTR, XATTR_NOFOLLOW) }
    }
}

func openInstalledApp() -> Bool {
    let task = Process()
    task.executableURL = URL(fileURLWithPath: "/usr/bin/open")
    task.arguments = [APP_PATH]
    do {
        try task.run()
        // Don't wait — let the new process launch independently.
        return true
    } catch {
        return false
    }
}

func spawnMainAndExit(argv: [String]) -> Never {
    let myPath = selfPath()
    let mainPath = (myPath as NSString).deletingLastPathComponent + "/VoiceType_main"

    // Build C-style argv (mainPath at [0], rest from CommandLine.arguments[1...])
    var cArgs: [UnsafeMutablePointer<CChar>?] = []
    cArgs.append(strdup(mainPath))
    for a in argv.dropFirst() {
        cArgs.append(strdup(a))
    }
    cArgs.append(nil)

    // Inherit env
    var cEnv: [UnsafeMutablePointer<CChar>?] = []
    for (k, v) in ProcessInfo.processInfo.environment {
        cEnv.append(strdup("\(k)=\(v)"))
    }
    cEnv.append(nil)

    var pid: pid_t = 0
    var attrs = posix_spawnattr_t(bitPattern: 0)
    posix_spawnattr_init(&attrs)
    // POSIX_SPAWN_SETSID: detach from launcher's session so child becomes top-level
    posix_spawnattr_setflags(&attrs, Int16(POSIX_SPAWN_SETSID))

    let result = posix_spawn(&pid, mainPath, nil, &attrs, &cArgs, &cEnv)
    posix_spawnattr_destroy(&attrs)

    if result != 0 {
        let err = String(cString: strerror(result))
        fputs("VoiceType launcher: posix_spawn \(mainPath) failed: \(err)\n", stderr)
        exit(127)
    }

    // Parent exits immediately — child reparents to launchd, becomes top-level
    exit(0)
}

let argv = CommandLine.arguments
let me = selfPath()

if me.contains(TRANSLOCATION_PATTERN) {
    // We are translocated. Remove quarantine on the installed app, then bounce.
    if FileManager.default.fileExists(atPath: APP_PATH) {
        removeQuarantineRecursive(at: APP_PATH)
        if openInstalledApp() {
            exit(0)
        }
        // open command failed — fall through to direct exec as best-effort
    }
    // Either the installed app is missing or open failed. Just run inline; the
    // user gets one broken-permissions launch but it doesn't crash the install.
}

spawnMainAndExit(argv: argv)
