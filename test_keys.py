"""Tests for the keys.py wrapper around keys_helper.swift."""
import pytest
from keys import KeyStore, KeyNotFound


@pytest.fixture
def store():
    s = KeyStore()
    try:
        s.delete("test_account")
    except KeyNotFound:
        pass
    yield s
    try:
        s.delete("test_account")
    except KeyNotFound:
        pass


def test_set_and_get(store):
    store.set("test_account", "secret_value")
    assert store.get("test_account") == "secret_value"


def test_get_missing_raises(store):
    with pytest.raises(KeyNotFound):
        store.get("not_a_real_account")


def test_delete(store):
    store.set("test_account", "x")
    store.delete("test_account")
    with pytest.raises(KeyNotFound):
        store.get("test_account")


def test_list(store):
    store.set("test_account", "x")
    accounts = store.list()
    assert "test_account" in accounts
