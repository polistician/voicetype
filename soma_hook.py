"""SOMA hook for VoxType — sends transcripts to SOMA after pasting.

Add to VoxType by importing and calling after transcription:
    from soma_hook import send_to_soma
    send_to_soma(text)
"""
import threading
import urllib.request
import json
import os

SOMA_URL = os.environ.get("SOMA_URL", "https://soma.polistician.ai")
SOMA_TOKEN = os.environ.get("SOMA_TOKEN", "")


def send_to_soma(transcript: str, source: str = "voxtype"):
    """Non-blocking send to SOMA Vox API. Fire and forget."""
    if not transcript or not transcript.strip():
        return
    threading.Thread(
        target=_send, args=(transcript, source), daemon=True
    ).start()


def _send(transcript: str, source: str):
    try:
        data = json.dumps({"transcript": transcript, "source": source}).encode()
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
        # Silent fail — VoxType must never break because of SOMA
        pass
