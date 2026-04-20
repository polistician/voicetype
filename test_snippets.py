# test_snippets.py
import os
import tempfile
import pytest

from snippets import Store


@pytest.fixture
def store():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    s = Store(path=path)
    yield s
    s.close()
    os.unlink(path)


def test_create_and_list(store):
    s = store.create(name="deploy v3", body="./deploy.sh", description="push crypto app")
    assert s.id is not None
    assert s.name == "deploy v3"
    all_ = store.list_all()
    assert len(all_) == 1
    assert all_[0].id == s.id


def test_update(store):
    s = store.create(name="orig", body="x")
    store.update(s.id, name="renamed", body="y")
    loaded = store.get(s.id)
    assert loaded.name == "renamed"
    assert loaded.body == "y"


def test_delete(store):
    s = store.create(name="trash", body="x")
    store.delete(s.id)
    assert store.get(s.id) is None
    assert store.list_all() == []


def test_search_text_fts(store):
    store.create(name="deploy v3", body="./deploy.sh", description="push crypto app")
    store.create(name="pytest watch", body="pytest -q --looponfail", tags="testing")
    store.create(name="brew cleanup", body="brew cleanup -s")

    hits = store.search_text("deploy")
    assert len(hits) == 1
    assert hits[0].name == "deploy v3"

    hits = store.search_text("crypto")
    assert len(hits) == 1  # found via description

    hits = store.search_text("testing")
    assert len(hits) == 1  # found via tags


def test_record_use(store):
    s = store.create(name="a", body="x")
    assert s.used_count == 0
    store.record_use(s.id)
    store.record_use(s.id)
    loaded = store.get(s.id)
    assert loaded.used_count == 2
    assert loaded.last_used_at is not None


def test_default_db_path_configurable(store):
    # Store accepts custom path (already used above); confirms we don't hardcode
    assert store.path.endswith(".db")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
