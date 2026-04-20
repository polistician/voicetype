# test_intent.py
import pytest

from intent import route, Intent


# Table: (transcription, expected_action, expected_payload_desc or None)
CASES = [
    # --- dictate: no trigger ---
    ("let me send you an email about the meeting", "dictate", None),
    ("this is a snippet of code I wrote", "dictate", None),  # "snippet" mid-sentence should NOT trigger
    ("", "dictate", None),

    # --- paste_snippet: clean trigger ---
    ("snippet deploy v3", "paste_snippet", "deploy v3"),
    ("snippet the one for crypto app deployment", "paste_snippet", "the one for crypto app deployment"),
    ("insert snippet pytest watch", "paste_snippet", "pytest watch"),
    ("paste snippet brew cleanup", "paste_snippet", "brew cleanup"),
    ("use snippet deploy soma", "paste_snippet", "deploy soma"),

    # --- paste_snippet: fuzzy trigger (Whisper misrecognitions) ---
    ("snipped deploy v3", "paste_snippet", "deploy v3"),
    ("snip it deploy v3", "paste_snippet", "deploy v3"),
    ("senate deploy v3", "paste_snippet", "deploy v3"),   # Whisper sometimes mishears
    ("snippets deploy v3", "paste_snippet", "deploy v3"),  # plural

    # --- open_overview variants ---
    ("open snippet overview", "open_overview", None),
    ("open snippets", "open_overview", None),
    ("show snippet manager", "open_overview", None),
    ("show snippets", "open_overview", None),
    ("launch snippet overlay", "open_overview", None),
    ("bring up the snippet list", "open_overview", None),

    # --- save_snippet ---
    ("save snippet", "save_snippet", None),
    ("save snippet from clipboard", "save_snippet", None),
    ("new snippet", "save_snippet", None),
    ("create snippet from clipboard", "save_snippet", None),

    # --- case + punctuation robustness ---
    ("Snippet Deploy v3", "paste_snippet", "Deploy v3"),
    ("Snippet, deploy v3.", "paste_snippet", "deploy v3"),
    ("SNIPPET DEPLOY V3", "paste_snippet", "DEPLOY V3"),

    # --- open_help ---
    ("show help", "open_help", None),
    ("open help", "open_help", None),
    ("Show help.", "open_help", None),
    # Whisper misrecognitions of "help"
    ("open hub", "open_help", None),
    ("show hub", "open_help", None),
    ("open halp", "open_help", None),
    # "help" alone should NOT trigger — too ambiguous
    ("help me find that file", "dictate", None),
    # "hub" alone should NOT trigger
    ("the hub and spoke model", "dictate", None),
]


@pytest.mark.parametrize("text,expected_action,expected_desc", CASES)
def test_route(text, expected_action, expected_desc):
    r = route(text)
    assert r.action == expected_action, f"{text!r} → got {r.action}, expected {expected_action}"
    if expected_desc is not None:
        assert r.payload.get("description", "").strip() == expected_desc.strip()


def test_route_returns_intent_dataclass():
    r = route("snippet x")
    assert isinstance(r, Intent)
    assert hasattr(r, "action")
    assert hasattr(r, "payload")
    assert hasattr(r, "confidence")


def test_dictate_has_full_text_in_payload():
    r = route("let me explain the plan")
    assert r.action == "dictate"
    assert r.payload.get("text") == "let me explain the plan"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
