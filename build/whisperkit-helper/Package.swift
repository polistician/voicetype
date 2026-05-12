// swift-tools-version: 5.10
//
// Package manifest for the WhisperKit subprocess helper.
// Architecture: see ../../docs/SPEC-v0.13-whisperkit.md § 5.
//
// The Python side (whisperkit_backend.py) spawns this binary at app start
// and talks to it over stdin/stdout JSON.

import PackageDescription

let package = Package(
    name: "whisperkit-helper",
    platforms: [
        .macOS(.v14),   // macOS Sonoma 14.0 — earliest stable with full ANE for Whisper
    ],
    products: [
        .executable(name: "whisperkit-helper", targets: ["whisperkit-helper"]),
    ],
    dependencies: [
        // WhisperKit is MIT-licensed and ships ANE-compiled CoreML Whisper models.
        // We pin to a recent stable; bump deliberately on release.
        .package(url: "https://github.com/argmaxinc/WhisperKit", from: "0.10.0"),
    ],
    targets: [
        .executableTarget(
            name: "whisperkit-helper",
            dependencies: [
                .product(name: "WhisperKit", package: "WhisperKit"),
            ],
            path: "Sources/whisperkit-helper",
            swiftSettings: [
                .enableExperimentalFeature("StrictConcurrency"),
            ]
        ),
    ]
)
