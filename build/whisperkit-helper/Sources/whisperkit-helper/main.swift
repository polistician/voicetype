// whisperkit-helper — WhisperKit subprocess wrapper for VoiceType.
//
// Architecture: ../../../docs/SPEC-v0.13-whisperkit.md § 5
//
// Lifecycle:
//   - Spawned at VoiceType app start by whisperkit_backend.py
//   - Reads one JSON request per stdin line
//   - Emits one JSON event per stdout line
//   - Stays alive for the session; on EOF or fatal error it exits and the
//     Python side falls back to whisper.cpp.
//
// Wire protocol:
//   Requests  (Python → Swift):
//     {"op":"load",      "model_path": "<path-to-.mlmodelc>"}
//     {"op":"set_lang",  "code": "en"|"de"|...|"auto"}
//     {"op":"set_vocab", "words": ["..."]}
//     {"op":"detect",    "id": N, "audio_b64": "...", "sr": 16000}
//     {"op":"transcribe","id": N, "audio_b64": "...", "sr": 16000,
//                        "lang": "en"|"auto"|...,
//                        "prompt": "...",
//                        "beam_size": 0|>1,
//                        "no_speech_thold": 0.6,
//                        "logprob_thold": -1.0}
//     {"op":"unload"}
//     {"op":"ping"}    // health check
//
//   Events    (Swift → Python):
//     {"event":"ready"}                                     // emitted at startup
//     {"event":"loaded","model":"...","took_ms":N}
//     {"event":"detect_result","id":N,"code":"de","prob":0.91}
//     {"event":"transcribe_result","id":N,
//        "text":"...","segments":[{...}],
//        "avg_logprob":-0.31, "detected_lang":"en",
//        "took_ms": N}
//     {"event":"pong"}
//     {"event":"error","id":N?,"message":"..."}             // never raises — emits error
//
// Audio encoding: float32 PCM at 16 kHz mono, base64-encoded in audio_b64.

import Foundation
import WhisperKit
import CoreML

// MARK: - Wire model

struct Request: Decodable {
    let op: String
    let id: Int?
    let model_path: String?
    let code: String?
    let words: [String]?
    let audio_b64: String?
    let sr: Int?
    let lang: String?
    let prompt: String?
    let beam_size: Int?
    let no_speech_thold: Float?
    let logprob_thold: Float?
}

// MARK: - JSON I/O

let encoder: JSONEncoder = {
    let e = JSONEncoder()
    e.outputFormatting = []  // single-line; one event per stdout line
    return e
}()

let decoder = JSONDecoder()

// Emit a JSON object as one stdout line + flush. We assemble via
// JSONSerialization rather than Encodable because event payloads have
// heterogeneous types (segments contain strings + floats + ints).
func emit(_ payload: [String: Any]) {
    do {
        let data = try JSONSerialization.data(withJSONObject: payload, options: [])
        FileHandle.standardOutput.write(data)
        FileHandle.standardOutput.write("\n".data(using: .utf8)!)
    } catch {
        // Last-resort: a hand-rolled error event we know serializes
        let fallback = "{\"event\":\"error\",\"message\":\"emit failed\"}\n"
        FileHandle.standardOutput.write(fallback.data(using: .utf8)!)
    }
}

func emitError(_ id: Int?, _ msg: String) {
    var p: [String: Any] = ["event": "error", "message": msg]
    if let id = id { p["id"] = id }
    emit(p)
}

// MARK: - State

actor State {
    var whisper: WhisperKit?
    var vocab: [String] = []
    var pinnedLanguage: String = "auto"

    func load(modelPath: String) async throws -> (model: String, tookMs: Int) {
        let t0 = Date()
        // WhisperKit will scan `modelPath` for an `openai_whisper-*` folder
        // containing the .mlmodelc files. We pass the parent of the .mlmodelc
        // bundle directory if it's structured that way.
        let cfg = WhisperKitConfig(
            modelFolder: modelPath,
            verbose: false,
            logLevel: .error,
            prewarm: true,
            load: true,
            download: false   // VoiceType bundles the model — never reach out
        )
        whisper = try await WhisperKit(cfg)
        let tookMs = Int(Date().timeIntervalSince(t0) * 1000)
        return (model: cfg.model ?? "large-v3-turbo", tookMs: tookMs)
    }

    func setLanguage(_ code: String) {
        pinnedLanguage = code.lowercased()
    }

    func setVocab(_ words: [String]) {
        vocab = Array(words.prefix(50))
    }

    func detect(_ audio: [Float]) async throws -> (code: String, prob: Float) {
        guard let w = whisper else {
            throw NSError(domain: "whisperkit-helper", code: 1,
                          userInfo: [NSLocalizedDescriptionKey: "not loaded"])
        }
        // WhisperKit's public API has a typo: detectLangauge (not detectLanguage).
        // The audioArray variant takes [Float]; the spelled-correctly version
        // takes audioPath. Using the typo'd one is intentional.
        let result = try await w.detectLangauge(audioArray: audio)
        let prob = result.langProbs[result.language] ?? 0.0
        return (result.language, prob)
    }

    func transcribe(
        audio: [Float], language: String,
        prompt: String, beamSize: Int,
        noSpeechThold: Float, logprobThold: Float
    ) async throws -> [String: Any] {
        guard let w = whisper else {
            throw NSError(domain: "whisperkit-helper", code: 1,
                          userInfo: [NSLocalizedDescriptionKey: "not loaded"])
        }

        // Build DecodingOptions
        let task: DecodingTask = .transcribe   // never translate; we transcribe as-is
        let useLang: String? = (language == "auto" || language.isEmpty) ? nil : language

        var promptTokens: [Int]? = nil
        if !prompt.isEmpty {
            promptTokens = w.tokenizer?.encode(text: prompt).filter { $0 < 50257 }
        }

        // Argument order matches DecodingOptions.init exactly. Reordering
        // these is a Swift compile error.
        let options = DecodingOptions(
            verbose: false,
            task: task,
            language: useLang,
            temperature: 0.0,
            temperatureIncrementOnFallback: 0.2,
            temperatureFallbackCount: 5,
            sampleLength: 224,
            usePrefillPrompt: !(promptTokens?.isEmpty ?? true),
            withoutTimestamps: false,
            wordTimestamps: false,
            clipTimestamps: [],
            promptTokens: promptTokens,
            suppressBlank: true,
            logProbThreshold: logprobThold,
            noSpeechThreshold: noSpeechThold,
            concurrentWorkerCount: 4
        )

        let t0 = Date()
        let results: [TranscriptionResult] = try await w.transcribe(
            audioArray: audio, decodeOptions: options
        )
        let tookMs = Int(Date().timeIntervalSince(t0) * 1000)

        // Aggregate results
        var fullText = ""
        var segments: [[String: Any]] = []
        var logProbs: [Float] = []
        var detectedLang: String = useLang ?? "en"
        for r in results {
            fullText += r.text
            detectedLang = r.language
            for seg in r.segments {
                segments.append([
                    "text": seg.text,
                    "t0": Int(seg.start * 1000),
                    "t1": Int(seg.end * 1000),
                    "probability": exp(seg.avgLogprob),  // map logprob → probability
                ])
                logProbs.append(seg.avgLogprob)
            }
        }
        let avgLogprob = logProbs.isEmpty ? 0.0 : logProbs.reduce(0, +) / Float(logProbs.count)

        return [
            "text": fullText,
            "segments": segments,
            "avg_logprob": avgLogprob,
            "avg_confidence": Double(exp(avgLogprob)),
            "detected_lang": detectedLang,
            "took_ms": tookMs,
        ]
    }

    func unload() {
        whisper = nil
    }
}

// MARK: - Main

@main
struct WhisperKitHelper {
    static func main() async {
        let state = State()
        emit(["event": "ready", "version": "0.13.0"])

        // Read one JSON line at a time from stdin.
        while let line = readLine(strippingNewline: true) {
            guard !line.isEmpty,
                  let data = line.data(using: .utf8) else { continue }

            let req: Request
            do {
                req = try decoder.decode(Request.self, from: data)
            } catch {
                emitError(nil, "bad request: \(error.localizedDescription)")
                continue
            }

            await handle(req: req, state: state)
        }
    }

    static func handle(req: Request, state: State) async {
        switch req.op {
        case "ping":
            emit(["event": "pong"])

        case "load":
            guard let path = req.model_path else {
                emitError(req.id, "load requires model_path")
                return
            }
            do {
                let info = try await state.load(modelPath: path)
                emit([
                    "event": "loaded",
                    "model": info.model,
                    "took_ms": info.tookMs,
                ])
            } catch {
                emitError(req.id, "load failed: \(error.localizedDescription)")
            }

        case "set_lang":
            guard let code = req.code else {
                emitError(req.id, "set_lang requires code")
                return
            }
            await state.setLanguage(code)
            emit(["event": "set_lang_ok", "code": code])

        case "set_vocab":
            await state.setVocab(req.words ?? [])
            emit(["event": "set_vocab_ok"])

        case "detect":
            guard let b64 = req.audio_b64,
                  let audio = decodeAudio(b64) else {
                emitError(req.id, "detect requires audio_b64 (float32 PCM)")
                return
            }
            do {
                let r = try await state.detect(audio)
                emit([
                    "event": "detect_result",
                    "id": req.id as Any,
                    "code": r.code,
                    "prob": Double(r.prob),
                ])
            } catch {
                emitError(req.id, "detect failed: \(error.localizedDescription)")
            }

        case "transcribe":
            guard let b64 = req.audio_b64,
                  let audio = decodeAudio(b64) else {
                emitError(req.id, "transcribe requires audio_b64 (float32 PCM)")
                return
            }
            do {
                let r = try await state.transcribe(
                    audio: audio,
                    language: req.lang ?? "auto",
                    prompt: req.prompt ?? "",
                    beamSize: req.beam_size ?? 0,
                    noSpeechThold: req.no_speech_thold ?? 0.6,
                    logprobThold: req.logprob_thold ?? -1.0
                )
                var payload = r
                payload["event"] = "transcribe_result"
                if let id = req.id { payload["id"] = id }
                emit(payload)
            } catch {
                emitError(req.id, "transcribe failed: \(error.localizedDescription)")
            }

        case "unload":
            await state.unload()
            emit(["event": "unloaded"])

        default:
            emitError(req.id, "unknown op: \(req.op)")
        }
    }

    static func decodeAudio(_ b64: String) -> [Float]? {
        // Audio is base64-encoded float32 PCM little-endian at 16 kHz.
        guard let data = Data(base64Encoded: b64) else { return nil }
        return data.withUnsafeBytes { buf -> [Float] in
            let f = buf.bindMemory(to: Float.self)
            return Array(f)
        }
    }
}
