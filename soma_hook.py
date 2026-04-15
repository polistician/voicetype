"""SOMA hook for VoxType — sends transcripts + voice quality data to SOMA.

Two modes:
  send_to_soma(text)              — basic, just the transcript
  send_to_soma_rich(rich_result)  — includes confidence, timing, low-confidence words

The rich mode feeds SOMA's voice profile learning, which in turn:
1. Improves future transcription (vocabulary → Whisper initial_prompt)
2. Detects pronunciation patterns (→ Luna coaching targets)
3. Infers cognitive state from speech tempo (→ Sage/engram)
"""
import threading
import urllib.request
import json
import os

SOMA_URL = os.environ.get("SOMA_URL", "https://soma.polistician.ai")
SOMA_TOKEN = os.environ.get("SOMA_TOKEN", "")


def send_to_soma(transcript: str, source: str = "voxtype"):
    """Non-blocking send — basic transcript only. Fire and forget."""
    if not transcript or not transcript.strip():
        return
    payload = {"transcript": transcript, "source": source}
    threading.Thread(target=_send, args=(payload,), daemon=True).start()


def send_to_soma_rich(rich_result: dict, source: str = "voxtype"):
    """Non-blocking send — rich data including confidence and timing.

    rich_result is the output of TranscriberV2.transcribe_rich():
    {text, segments, avg_confidence, low_confidence_words, duration_ms, words_per_minute}
    """
    text = rich_result.get("text", "").strip()
    if not text:
        return
    payload = {
        "transcript": text,
        "source": source,
        "avg_confidence": rich_result.get("avg_confidence"),
        "words_per_minute": rich_result.get("words_per_minute"),
        "low_confidence_words": rich_result.get("low_confidence_words", []),
        "duration_ms": rich_result.get("duration_ms", 0),
    }
    threading.Thread(target=_send, args=(payload,), daemon=True).start()


def _send(payload: dict):
    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{SOMA_URL}/api/vox/ingest",
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {SOMA_TOKEN}" if SOMA_TOKEN else "",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            result = json.loads(resp.read())
            if result.get("intent"):
                print(f"[SOMA] {result['intent']}: {result.get('result', {}).get('response', '')[:60]}", flush=True)
    except Exception:
        pass
