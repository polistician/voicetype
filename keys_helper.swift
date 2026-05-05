// keys_helper.swift — JSON-over-stdio for macOS Keychain.
//
// Protocol: read one JSON line from stdin, write one JSON line to stdout.
// Commands:
//   {"action":"set","account":"deepl","value":"<key>"}     -> {"ok":true}
//   {"action":"get","account":"deepl"}                     -> {"ok":true,"value":"<key>"}  or {"ok":false}
//   {"action":"delete","account":"deepl"}                  -> {"ok":true}
//   {"action":"list"}                                      -> {"ok":true,"accounts":["deepl",...]}
//
// All entries live under the service identifier:
//   com.polistician.voicetype.keys

import Foundation
import Security

let SERVICE = "com.polistician.voicetype.keys"

struct Request: Codable {
    let action: String
    let account: String?
    let value: String?
}

struct Response: Codable {
    var ok: Bool
    var value: String?
    var accounts: [String]?
    var error: String?
}

func emit(_ resp: Response) {
    let enc = JSONEncoder()
    if let data = try? enc.encode(resp), let line = String(data: data, encoding: .utf8) {
        print(line)
        fflush(stdout)
    }
}

func keychainSet(account: String, value: String) -> Response {
    let data = value.data(using: .utf8)!
    let query: [String: Any] = [
        kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: SERVICE,
        kSecAttrAccount as String: account
    ]
    SecItemDelete(query as CFDictionary)
    var add = query
    add[kSecValueData as String] = data
    let status = SecItemAdd(add as CFDictionary, nil)
    if status == errSecSuccess { return Response(ok: true) }
    return Response(ok: false, error: "SecItemAdd status \(status)")
}

func keychainGet(account: String) -> Response {
    let query: [String: Any] = [
        kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: SERVICE,
        kSecAttrAccount as String: account,
        kSecReturnData as String: true,
        kSecMatchLimit as String: kSecMatchLimitOne
    ]
    var result: AnyObject?
    let status = SecItemCopyMatching(query as CFDictionary, &result)
    if status == errSecSuccess, let data = result as? Data, let s = String(data: data, encoding: .utf8) {
        return Response(ok: true, value: s)
    }
    if status == errSecItemNotFound { return Response(ok: false, error: "not found") }
    return Response(ok: false, error: "SecItemCopyMatching status \(status)")
}

func keychainDelete(account: String) -> Response {
    let query: [String: Any] = [
        kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: SERVICE,
        kSecAttrAccount as String: account
    ]
    let status = SecItemDelete(query as CFDictionary)
    if status == errSecSuccess || status == errSecItemNotFound { return Response(ok: true) }
    return Response(ok: false, error: "SecItemDelete status \(status)")
}

func keychainList() -> Response {
    let query: [String: Any] = [
        kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: SERVICE,
        kSecReturnAttributes as String: true,
        kSecMatchLimit as String: kSecMatchLimitAll
    ]
    var result: AnyObject?
    let status = SecItemCopyMatching(query as CFDictionary, &result)
    if status == errSecItemNotFound { return Response(ok: true, accounts: []) }
    if status != errSecSuccess { return Response(ok: false, error: "SecItemCopyMatching status \(status)") }
    let items = (result as? [[String: Any]]) ?? []
    let accounts = items.compactMap { $0[kSecAttrAccount as String] as? String }
    return Response(ok: true, accounts: accounts)
}

while let line = readLine() {
    guard let data = line.data(using: .utf8),
          let req = try? JSONDecoder().decode(Request.self, from: data) else {
        emit(Response(ok: false, error: "invalid JSON"))
        continue
    }
    switch req.action {
    case "set":
        guard let a = req.account, let v = req.value else { emit(Response(ok: false, error: "missing account/value")); break }
        emit(keychainSet(account: a, value: v))
    case "get":
        guard let a = req.account else { emit(Response(ok: false, error: "missing account")); break }
        emit(keychainGet(account: a))
    case "delete":
        guard let a = req.account else { emit(Response(ok: false, error: "missing account")); break }
        emit(keychainDelete(account: a))
    case "list":
        emit(keychainList())
    default:
        emit(Response(ok: false, error: "unknown action: \(req.action)"))
    }
}
