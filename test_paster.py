# test_paster.py
from unittest.mock import MagicMock
from paster import Paster


def test_paster_handles_empty():
    """Empty string should not crash."""
    p = Paster()
    p.paste("")  # Should be a no-op


def test_paster_no_hotkey_noop():
    """paste() without a hotkey set must silently do nothing."""
    p = Paster()
    p.paste("hello")  # No AttributeError, no crash


def test_paster_delegates_to_hotkey():
    """paste() must call hotkey.paste() with the exact text."""
    mock_hotkey = MagicMock()
    p = Paster()
    p.set_hotkey(mock_hotkey)
    p.paste("hello")
    mock_hotkey.paste.assert_called_once_with("hello")
