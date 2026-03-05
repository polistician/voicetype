# test_paster.py
import subprocess
from paster import Paster

def test_paster_sets_clipboard():
    """Paste should set the clipboard content."""
    p = Paster()
    p._set_clipboard("voxtype test 12345")
    result = subprocess.run(["pbpaste"], capture_output=True, text=True)
    assert result.stdout == "voxtype test 12345"

def test_paster_restores_clipboard():
    """After paste, original clipboard should be restored."""
    # Set known clipboard content
    subprocess.run(["pbcopy"], input="original content", text=True)
    p = Paster()
    # Save, set new, restore
    old = p._get_clipboard()
    p._set_clipboard("temporary")
    p._set_clipboard(old)
    result = subprocess.run(["pbpaste"], capture_output=True, text=True)
    assert result.stdout == "original content"

def test_paster_handles_empty():
    """Empty string should not crash."""
    p = Paster()
    p.paste("")  # Should be a no-op

if __name__ == "__main__":
    test_paster_sets_clipboard()
    print("PASS: test_paster_sets_clipboard")
    test_paster_restores_clipboard()
    print("PASS: test_paster_restores_clipboard")
    test_paster_handles_empty()
    print("PASS: test_paster_handles_empty")
    print("All tests passed!")
